"""Spec 052 US2: PGWire's own savepoint stack, mapped onto IRIS savepoints.

IRIS has no RELEASE, deletes a savepoint when it is rolled back to, and allows 254 savepoints
alive in one transaction ($TLEVEL 255 fails with -400 and loses the work). Measured 2026-11-14
(research.md R4): re-establishing a savepoint after ROLLBACK TO works; ROLLBACK TO s4 of s1..s10
leaves $TLEVEL 4, so it frees s4 and everything after it; a duplicate name rolls back to the most
recent one. The stack answers as PostgreSQL does and returns the IRIS statements to send.
"""

from __future__ import annotations

import pytest

from iris_pgwire.savepoints import (
    MAX_IRIS_SAVEPOINTS,
    SavepointError,
    SavepointStack,
    normalise_name,
    parse_savepoint_statement,
)


def _iris(name: int) -> str:
    return f"pgw_sp_{name}"


class TestParsing:
    @pytest.mark.parametrize(
        ("sql", "parsed"),
        [
            ("SAVEPOINT s", ("savepoint", "s")),
            ('savepoint "_pg3_1"', ("savepoint", '"_pg3_1"')),
            ("ROLLBACK TO s", ("rollback_to", "s")),
            ("ROLLBACK TO SAVEPOINT s", ("rollback_to", "s")),
            ("rollback work to savepoint S1;", ("rollback_to", "S1")),
            ("ROLLBACK TRANSACTION TO s", ("rollback_to", "s")),
            ('ROLLBACK TO "my savepoint"', ("rollback_to", '"my savepoint"')),
            ("RELEASE s", ("release", "s")),
            ("RELEASE SAVEPOINT s", ("release", "s")),
            ('release savepoint "a""b"', ("release", '"a""b"')),
            ("  SAVEPOINT s ;  ", ("savepoint", "s")),
            ("-- x\nSAVEPOINT s", ("savepoint", "s")),
        ],
    )
    def test_every_spelling(self, sql, parsed):
        assert parse_savepoint_statement(sql) == parsed

    @pytest.mark.parametrize(
        "sql",
        [
            "ROLLBACK",
            "COMMIT",
            "SELECT 'savepoint s'",
            "INSERT INTO release VALUES (1)",
            "SAVEPOINT",
            "RELEASE SAVEPOINT",
            "SAVEPOINTS s",
        ],
    )
    def test_everything_else(self, sql):
        assert parse_savepoint_statement(sql) is None


class TestNames:
    def test_unquoted_names_fold_to_lower_case(self):
        assert normalise_name("S1") == normalise_name("s1") == "s1"

    def test_quoted_names_are_exact(self):
        assert normalise_name('"S1"') == "S1"
        assert normalise_name('"S1"') != normalise_name("s1")

    def test_doubled_quotes_are_one_quote(self):
        assert normalise_name('"a""b"') == 'a"b'

    def test_a_quoted_lower_case_name_equals_the_unquoted_one(self):
        assert normalise_name('"s1"') == normalise_name("S1")


class TestStack:
    def test_savepoint_sends_an_internal_name(self):
        stack = SavepointStack()
        assert stack.savepoint("s") == [f"SAVEPOINT {_iris(1)}"]
        assert stack.depth == 1

    def test_rollback_to_rolls_back_and_re_establishes(self):
        stack = SavepointStack()
        stack.savepoint("s")
        assert stack.rollback_to("s") == [
            f"ROLLBACK TO SAVEPOINT {_iris(1)}",
            f"SAVEPOINT {_iris(1)}",
        ]
        assert stack.depth == 1  # the savepoint survives, as on PostgreSQL

    def test_rollback_to_twice_works(self):
        stack = SavepointStack()
        stack.savepoint("s")
        stack.rollback_to("s")
        assert stack.rollback_to("s")[0] == f"ROLLBACK TO SAVEPOINT {_iris(1)}"

    def test_rollback_to_an_earlier_one_drops_the_later(self):
        stack = SavepointStack()
        stack.savepoint("a")
        stack.savepoint("b")
        stack.rollback_to("a")
        with pytest.raises(SavepointError) as excinfo:
            stack.rollback_to("b")
        assert excinfo.value.sqlstate == "3B001"

    def test_the_most_recent_duplicate_wins(self):
        stack = SavepointStack()
        stack.savepoint("a")
        stack.savepoint("a")
        assert stack.rollback_to("a")[0] == f"ROLLBACK TO SAVEPOINT {_iris(2)}"
        assert stack.depth == 2

    def test_release_sends_nothing_and_drops_the_named_and_later(self):
        stack = SavepointStack()
        stack.savepoint("a")
        stack.savepoint("b")
        stack.savepoint("c")
        assert stack.release("b") == []
        assert stack.depth == 1
        with pytest.raises(SavepointError):
            stack.rollback_to("c")
        assert stack.rollback_to("a")[0] == f"ROLLBACK TO SAVEPOINT {_iris(1)}"

    def test_release_of_a_duplicate_releases_the_most_recent(self):
        stack = SavepointStack()
        stack.savepoint("a")
        stack.savepoint("a")
        stack.release("a")
        assert stack.rollback_to("a")[0] == f"ROLLBACK TO SAVEPOINT {_iris(1)}"

    @pytest.mark.parametrize("verb", ["rollback_to", "release"])
    def test_an_unknown_name_is_3b001_with_postgresqls_message(self, verb):
        stack = SavepointStack()
        stack.savepoint("a")
        with pytest.raises(SavepointError) as excinfo:
            getattr(stack, verb)("nosuch")
        assert (excinfo.value.sqlstate, excinfo.value.condition) == (
            "3B001",
            "invalid_savepoint_specification",
        )
        assert str(excinfo.value) == 'savepoint "nosuch" does not exist'

    def test_names_compare_by_identifier_rules(self):
        stack = SavepointStack()
        stack.savepoint("S1")
        stack.rollback_to('"s1"')  # same name
        with pytest.raises(SavepointError):
            stack.rollback_to('"S1"')  # a different, quoted, upper-case name

    def test_internal_names_stay_unique_after_a_release(self):
        stack = SavepointStack()
        stack.savepoint("a")
        stack.release("a")
        assert stack.savepoint("b") == [f"SAVEPOINT {_iris(2)}"]

    def test_clear_forgets_everything(self):
        stack = SavepointStack()
        stack.savepoint("a")
        stack.clear()
        assert stack.depth == 0
        assert stack.savepoint("b") == [f"SAVEPOINT {_iris(1)}"]


class TestTheIrisLimit:
    def test_the_limit_is_254(self):
        assert MAX_IRIS_SAVEPOINTS == 254

    def test_the_255th_savepoint_is_refused_before_iris_sees_it(self):
        stack = SavepointStack()
        for i in range(MAX_IRIS_SAVEPOINTS):
            stack.savepoint(f"s{i}")
        with pytest.raises(SavepointError) as excinfo:
            stack.savepoint("one_too_many")
        assert (excinfo.value.sqlstate, excinfo.value.condition) == (
            "54000",
            "program_limit_exceeded",
        )
        assert "254" in str(excinfo.value)

    def test_released_savepoints_still_count(self):
        """IRIS keeps a released savepoint alive: it has no RELEASE."""
        stack = SavepointStack()
        for i in range(MAX_IRIS_SAVEPOINTS):
            stack.savepoint("s")
            stack.release("s")
        assert stack.depth == 0
        with pytest.raises(SavepointError):
            stack.savepoint("s")

    def test_rolling_back_frees_the_levels_it_rolls_back(self):
        """Measured: ROLLBACK TO s4 of s1..s10 leaves $TLEVEL 4; re-establishing makes it 5."""
        stack = SavepointStack()
        for i in range(1, 11):
            stack.savepoint(f"s{i}")
        stack.rollback_to("s4")
        assert stack.iris_alive == 4
        for i in range(MAX_IRIS_SAVEPOINTS - 4):
            stack.savepoint(f"t{i}")
        with pytest.raises(SavepointError):
            stack.savepoint("over")

    def test_released_savepoints_after_the_target_are_freed_by_rolling_back(self):
        stack = SavepointStack()
        stack.savepoint("a")
        for _ in range(100):
            stack.savepoint("x")
            stack.release("x")
        assert stack.iris_alive == 101
        stack.rollback_to("a")
        assert stack.iris_alive == 1

    def test_a_refused_savepoint_changes_nothing(self):
        stack = SavepointStack()
        for i in range(MAX_IRIS_SAVEPOINTS):
            stack.savepoint(f"s{i}")
        with pytest.raises(SavepointError):
            stack.savepoint("over")
        assert stack.depth == MAX_IRIS_SAVEPOINTS
        assert stack.rollback_to("s0")[0] == f"ROLLBACK TO SAVEPOINT {_iris(1)}"
