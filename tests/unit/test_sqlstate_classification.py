"""T027 / FR-008e: a client must be able to tell whose fault an error is.

Every failure used to reach the client as SQLSTATE `42000`
(`syntax_error_or_access_rule_violation`) — an IRIS internal crash, a genuine
syntax error, an undefined column and a unique-key violation alike. A client's
retry and reporting logic keys on the SQLSTATE *class*, so it concluded "fix your
query" when the database had broken, and ORMs could not recognise a duplicate-key
insert at all.

This became a requirement when CHK046 decided that passing an IRIS failure
through is acceptable: pass-through is only honest if the error is *classified*.

Both sides of the mapping are measured, not recalled:

  IRIS 2026.2 SQLCODEs        PostgreSQL 15 SQLSTATEs
  -29  field not found        42703  undefined_column
  -30  table/view not found   42P01  undefined_table
  -359 function not found     42883  undefined_function
  -23  label not listed       42P01  (PostgreSQL: missing FROM-clause entry)
  -1   invalid SQL statement  42601  syntax_error
  -4   term expected          42601  syntax_error
  -25  input after end        42601  syntax_error
  -119 UNIQUE/PK constraint   23505  unique_violation
  -108 required field missing 23502  not_null_violation
  -104 field validation       22000  data_exception
  -149 error inside an installed SQL function  XX000  internal_error
  -400 fatal error            XX000  internal_error

`-1` and `-149` were measured later than the rest, while verifying over the wire
(`specs/044-catalog-as-views/spikes/verify_sqlstate_e2e.py`): `SELECT FROM WHERE`
is `-1`, not `-4`, and a throw inside `PGWire.PG_ARRAY` is `-149`.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.sqlstate import (
    DEFAULT_SQLSTATE,
    classify_iris_error,
)


def state(message: str) -> str:
    return classify_iris_error(message)[0]


class TestMeasuredMappings:
    """Each input is a real IRIS 2026.2 message, trimmed."""

    @pytest.mark.parametrize(
        ("sqlcode", "detail", "expected"),
        [
            (-29, "Field not found in the applicable tables", "42703"),
            (-30, "Table or view not found", "42P01"),
            (-359, "SQL Function (function stored procedure) not found", "42883"),
            (-23, "Label is not listed among the applicable tables", "42P01"),
            (-1, "Invalid SQL statement", "42601"),
            (-4, "A term expected, beginning with one of the following", "42601"),
            (-25, "Input encountered after end of query", "42601"),
            (-149, "SQL Function encountered an error", "XX000"),
            (-119, "UNIQUE or PRIMARY KEY constraint failed", "23505"),
            (-108, "Required field missing; INSERT or UPDATE", "23502"),
            (-104, "Field validation failed in INSERT", "22000"),
            (-400, "Fatal error occurred", "XX000"),
        ],
    )
    def test_sqlcode_drives_the_classification(self, sqlcode, detail, expected):
        message = f"<SQL ERROR>; Details: [SQLCODE: <{sqlcode}>:<{detail}>] [Location: <Prepare>]"
        assert state(message) == expected

    def test_the_full_message_from_a_real_crash(self):
        """The shape that motivated this: an IRIS internal failure."""
        message = (
            "<SQL ERROR>; Details: [SQLCODE: <-400>:<Fatal error occurred>] "
            "[Location: <ServerLoop>] [%msg: <Error compiling cached query class "
            "%sqlcq.USER.cls283: ERROR: <UNDEFINED>aptv^%qaqpnl *ptv(\" *** \")>]"
        )
        assert state(message) == "XX000", "a database crash must not blame the client's SQL"

    def test_a_crash_and_a_syntax_error_are_distinguishable(self):
        """The whole point — these used to be identical to a client."""
        crash = "[SQLCODE: <-400>:<Fatal error occurred>]"
        syntax = "[SQLCODE: <-4>:<A term expected>]"
        assert state(crash) != state(syntax)
        assert state(crash).startswith("XX"), "internal error class"
        assert state(syntax).startswith("42"), "client-error class"


class TestConditionNames:
    """The condition name accompanies the code in the ErrorResponse."""

    @pytest.mark.parametrize(
        ("sqlcode", "expected_name"),
        [
            (-29, "undefined_column"),
            (-30, "undefined_table"),
            (-359, "undefined_function"),
            (-119, "unique_violation"),
            (-108, "not_null_violation"),
            (-400, "internal_error"),
            (-4, "syntax_error"),
        ],
    )
    def test_names_match_postgresql_condition_names(self, sqlcode, expected_name):
        _, name = classify_iris_error(f"[SQLCODE: <{sqlcode}>:<whatever>]")
        assert name == expected_name


class TestFallbackIsConservative:
    """An unrecognised error must not be mis-classified into a confident lie."""

    @pytest.mark.parametrize(
        "message",
        [
            "",
            "something entirely unexpected",
            "[SQLCODE: <-9999>:<a code this table does not know>]",
            "no sqlcode here at all",
        ],
    )
    def test_unknown_errors_keep_the_previous_behaviour(self, message):
        assert state(message) == DEFAULT_SQLSTATE

    def test_the_default_is_what_shipped_before(self):
        """Unmapped codes must not change behaviour for anyone relying on it."""
        assert DEFAULT_SQLSTATE == "42000"

    def test_a_positive_sqlcode_is_not_an_error(self):
        """100 is 'no more rows', not a failure; it must not be classified."""
        assert state("[SQLCODE: <100>:<no more data>]") == DEFAULT_SQLSTATE


class TestCallerSuppliedFallback:
    """Some call sites already report something better than 42000.

    The query paths reported `08000` (connection_exception) for *any* exception,
    which is right for a dropped socket and wrong for an IRIS `-30`. So a caller
    keeps its own code when nothing is recognised, and loses it when something is.
    """

    def test_an_unrecognised_error_keeps_the_callers_code(self):
        assert classify_iris_error("socket closed", default=("08000", "connection_exception")) == (
            "08000",
            "connection_exception",
        )

    def test_a_recognised_error_overrides_the_callers_code(self):
        """Measured over the wire: an IRIS -30 used to arrive as 08000."""
        message = "Statement processing failed: [SQLCODE: <-30>:<Table or view not found>]"
        assert classify_iris_error(message, default=("08000", "connection_exception")) == (
            "42P01",
            "undefined_table",
        )

    def test_an_empty_message_keeps_the_callers_code(self):
        assert classify_iris_error("", default=("XX000", "internal_error"))[0] == "XX000"


class TestMessagePatternFallback:
    """Not every path carries a SQLCODE; the text still says what happened."""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Field 'NO_SUCH_COL' not found in the applicable tables", "42703"),
            ("Table or view not found", "42P01"),
            ("User defined SQL function 'SQLUSER.X' does not exist", "42883"),
            ("UNIQUE or PRIMARY KEY constraint failed", "23505"),
            ("Exception caught during dSQL statement %Execute: 5475", "XX000"),
        ],
    )
    def test_recognised_without_a_sqlcode(self, message, expected):
        assert state(message) == expected


class TestTheEmbeddedBackendWordsErrorsDifferently:
    """The two backends do not share a single error message shape.

    Measured inside the container against `iris.sql.exec` (embedded) beside the
    DB-API messages above: embedded carries **no SQLCODE at all** and different
    wording for every family, so classification that only reads DB-API messages
    silently degrades to `42000` on the default backend. These strings are
    verbatim from `spikes/` output, trimmed only of the trailing `^ SELECT ...`
    echo.
    """

    @pytest.mark.parametrize(
        ("label", "message", "expected"),
        [
            ("undefined table", "Table 'SQLUSER.NO_SUCH_TABLE_XYZ' not found", "42P01"),
            ("no such schema", "Table 'NOSUCHSCHEMA.NOSUCHTABLE' not found", "42P01"),
            (
                "undefined column",
                "Field 'NO_SUCH_COL' not found in the applicable tables",
                "42703",
            ),
            (
                "undefined function",
                "User defined SQL function 'SQLUSER.NO_SUCH_FUNCTION_XYZ' does not exist",
                "42883",
            ),
            ("syntax, reserved word", "IDENTIFIER expected, reserved word WHERE found", "42601"),
            ("syntax, trailing input", "Input ()) encountered after end of query", "42601"),
            (
                "syntax, dangling comma",
                "A term expected, beginning with either of:  identifier, constant",
                "42601",
            ),
            ("syntax, unbalanced quote", "Closing quote (') missing", "42601"),
            (
                "unique violation",
                "Table 'SQLUser.T', Constraint 'T_PKEY2', Field(s) id=1; failed unique check",
                "23505",
            ),
            ("not null violation", "'id' in table 'SQLUser.T' is a required field", "23502"),
            (
                "value too long",
                "Field 'SQLUser.T.name' (value 'way too long for ten') failed validation",
                "22000",
            ),
            (
                "bad numeric",
                "Field 'SQLUser.T.id' (value 'notanint') failed validation",
                "22000",
            ),
            (
                "internal failure",
                "Unexpected error occurred:  <LIST>%QRS0o+20^%sqlcq.USER.cls267.1",
                "XX000",
            ),
        ],
    )
    def test_embedded_wording_classifies_the_same_as_dbapi(self, label, message, expected):
        assert state(message) == expected, label

    def test_no_embedded_message_carries_a_sqlcode(self):
        """Why the message patterns are not merely a fallback on this backend."""
        assert "SQLCODE" not in "Table 'SQLUSER.NO_SUCH_TABLE_XYZ' not found"

    def test_a_column_error_is_not_swallowed_by_the_table_pattern(self):
        """Both mention a table; order in the pattern list decides, so pin it."""
        assert state("Field 'X' not found in the applicable tables") == "42703"


class TestWiredIntoTheProtocol:
    def test_the_protocol_classifies_rather_than_hardcoding(self):
        """Both error sites used to pass a literal "42000"."""
        import inspect

        from iris_pgwire import protocol

        source = inspect.getsource(protocol)
        assert "classify_iris_error(" in source, (
            "protocol.py still hardcodes a SQLSTATE; an IRIS crash will be reported "
            "as the client's syntax error"
        )

    def test_no_error_site_still_passes_a_bare_42000(self):
        import inspect

        from iris_pgwire import protocol

        source = inspect.getsource(protocol)
        assert '"42000"' not in source, "an unclassified 42000 is back in protocol.py"

    def test_the_query_paths_no_longer_report_08000_unconditionally(self):
        """Measured regression: an IRIS -30 reached the client as 08000.

        `08000` tells a client the *connection* failed, so a driver may discard
        the session over a plain typo. It must only be the fallback now.
        """
        import inspect

        from iris_pgwire import protocol

        for name in ("handle_query", "_handle_single_statement", "handle_execute_message"):
            method = getattr(protocol.PGWireProtocol, name, None)
            if method is None:
                continue
            body = inspect.getsource(method)
            if '"08000"' in body or '"42P03"' in body:
                assert "classify_iris_error(" in body, (
                    f"{name} still reports a fixed SQLSTATE for every failure"
                )
