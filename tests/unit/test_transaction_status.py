"""Spec 052 US1: the aborted-transaction rule as a pure state machine.

PostgreSQL aborts a transaction block on any error: ReadyForQuery reports ``E``, every later
statement except one that ends the transaction is refused with 25P02, and COMMIT rolls back. The
transitions are data-model.md "Transaction status"; the protocol layer only asks this module.
"""

from __future__ import annotations

import pytest

from iris_pgwire.transaction_status import (
    FAILED,
    IDLE,
    IN_TRANSACTION,
    after_error,
    after_rollback_to,
    after_success,
    commit_rolls_back,
    is_exit_statement,
    refusal,
)

COMMIT_FORMS = [
    "COMMIT",
    "commit",
    "COMMIT WORK",
    "COMMIT TRANSACTION",
    "END",
    "END WORK",
    "END TRANSACTION",
]
ROLLBACK_FORMS = [
    "ROLLBACK",
    "rollback",
    "ROLLBACK WORK",
    "ROLLBACK TRANSACTION",
    "ABORT",
    "ABORT WORK",
    "ABORT TRANSACTION",
]
ROLLBACK_TO_FORMS = [
    "ROLLBACK TO s",
    "ROLLBACK TO SAVEPOINT s",
    'rollback to "_pg3_1"',
    "ROLLBACK WORK TO SAVEPOINT s",
    "ROLLBACK TRANSACTION TO s",
]


class TestStatusBytes:
    def test_the_bytes_are_readyforquerys(self):
        assert (IDLE, IN_TRANSACTION, FAILED) == (b"I", b"T", b"E")


class TestExitStatements:
    @pytest.mark.parametrize("sql", COMMIT_FORMS + ROLLBACK_FORMS + ROLLBACK_TO_FORMS)
    def test_these_end_or_repair_the_transaction(self, sql):
        assert is_exit_statement(sql)

    @pytest.mark.parametrize(
        "sql",
        ["  commit ;", "COMMIT;", "-- done\nCOMMIT", "/* x */ ROLLBACK", "rollback\n", "END\t;"],
    )
    def test_comments_whitespace_and_a_semicolon_do_not_matter(self, sql):
        assert is_exit_statement(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO t VALUES (1)",
            "SELECT 1",
            "SAVEPOINT s",
            "RELEASE s",
            "RELEASE SAVEPOINT s",
            "BEGIN",
            "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "SELECT 'commit'",
            "COMMITTED",
            "ENDS",
            "ROLLBACKS",
            "",
        ],
    )
    def test_everything_else_is_not(self, sql):
        assert not is_exit_statement(sql)


class TestRefusal:
    def test_an_ordinary_statement_in_a_failed_transaction_is_25p02(self):
        sqlstate, condition, message = refusal(FAILED, "INSERT INTO t VALUES (2)")
        assert (sqlstate, condition) == ("25P02", "in_failed_sql_transaction")
        # PostgreSQL's wording, which clients and people search for.
        assert message == (
            "current transaction is aborted, commands ignored until end of transaction block"
        )

    @pytest.mark.parametrize("sql", COMMIT_FORMS + ROLLBACK_FORMS + ROLLBACK_TO_FORMS)
    def test_exit_statements_pass_in_a_failed_transaction(self, sql):
        assert refusal(FAILED, sql) is None

    @pytest.mark.parametrize("status", [IDLE, IN_TRANSACTION])
    def test_nothing_is_refused_outside_the_failed_state(self, status):
        assert refusal(status, "INSERT INTO t VALUES (2)") is None


class TestTransitions:
    def test_an_error_in_a_transaction_aborts_it(self):
        assert after_error(IN_TRANSACTION) == FAILED

    def test_an_error_outside_a_transaction_changes_nothing(self):
        assert after_error(IDLE) == IDLE

    def test_an_error_in_a_failed_transaction_stays_failed(self):
        assert after_error(FAILED) == FAILED

    def test_commit_rolls_back_only_a_failed_transaction(self):
        assert commit_rolls_back(FAILED)
        assert not commit_rolls_back(IN_TRANSACTION)
        assert not commit_rolls_back(IDLE)

    def test_a_successful_rollback_to_repairs_a_failed_transaction(self):
        assert after_rollback_to(FAILED, succeeded=True) == IN_TRANSACTION

    def test_a_failed_rollback_to_leaves_it_failed(self):
        assert after_rollback_to(FAILED, succeeded=False) == FAILED

    def test_rollback_to_in_an_open_transaction_keeps_it_open(self):
        assert after_rollback_to(IN_TRANSACTION, succeeded=True) == IN_TRANSACTION


class TestAfterSuccess:
    """What a statement that succeeded does to the status, whatever path it took."""

    @pytest.mark.parametrize(
        "sql",
        [
            "BEGIN",
            "begin isolation level read committed",
            "START TRANSACTION",
            "start transaction isolation level read uncommitted",
            "BEGIN WORK",
        ],
    )
    def test_a_begin_opens_a_transaction(self, sql):
        assert after_success(IDLE, sql) == IN_TRANSACTION

    @pytest.mark.parametrize("sql", COMMIT_FORMS + ROLLBACK_FORMS)
    def test_commit_and_rollback_end_it(self, sql):
        assert after_success(IN_TRANSACTION, sql) == IDLE
        assert after_success(FAILED, sql) == IDLE

    @pytest.mark.parametrize("sql", ROLLBACK_TO_FORMS)
    def test_rollback_to_repairs_and_does_not_end_it(self, sql):
        assert after_success(FAILED, sql) == IN_TRANSACTION
        assert after_success(IN_TRANSACTION, sql) == IN_TRANSACTION

    @pytest.mark.parametrize("sql", ["INSERT INTO t VALUES (1)", "SAVEPOINT s", "RELEASE s"])
    def test_anything_else_changes_nothing(self, sql):
        for status in (IDLE, IN_TRANSACTION):
            assert after_success(status, sql) == status


class TestSavepointsOutsideATransaction:
    """FR-007a: PostgreSQL refuses them with 25P01, naming the statement."""

    @pytest.mark.parametrize(
        ("sql", "verb"),
        [
            ("SAVEPOINT s", "SAVEPOINT"),
            ("ROLLBACK TO s", "ROLLBACK TO SAVEPOINT"),
            ("ROLLBACK TO SAVEPOINT s", "ROLLBACK TO SAVEPOINT"),
            ("RELEASE s", "RELEASE SAVEPOINT"),
        ],
    )
    def test_refused_when_idle(self, sql, verb):
        sqlstate, condition, message = refusal(IDLE, sql)
        assert (sqlstate, condition) == ("25P01", "no_active_sql_transaction")
        assert message == f"{verb} can only be used in transaction blocks"

    def test_allowed_in_a_transaction(self):
        assert refusal(IN_TRANSACTION, "SAVEPOINT s") is None
