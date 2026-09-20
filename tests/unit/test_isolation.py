"""Unit tests for sql_translator/isolation.py.

Every IRIS behaviour asserted here was measured against IRIS 2026.2 CE in the
`iris-pgwire-db` container, not recalled:

    SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED   -> SQLCODE 0
    SET TRANSACTION ISOLATION LEVEL READ COMMITTED     -> SQLCODE 0
    SET TRANSACTION ISOLATION LEVEL REPEATABLE READ    -> SQLCODE -96
    SET TRANSACTION ISOLATION LEVEL SERIALIZABLE       -> SQLCODE -1
"""

import dataclasses

import pytest

from iris_pgwire.sql_translator.isolation import (
    DEFAULT_ISOLATION_LEVEL,
    IsolationRequest,
    parse_isolation_show,
    parse_set_isolation,
)

# ---------------------------------------------------------------------------
# parse_set_isolation — spellings that must be recognised
# ---------------------------------------------------------------------------


class TestParseSetIsolationSpellings:
    @pytest.mark.parametrize(
        "sql",
        [
            "SET TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "SET LOCAL TRANSACTION ISOLATION LEVEL READ COMMITTED",
            "set transaction isolation level read committed",
            "SET TRANSACTION ISOLATION LEVEL READ COMMITTED;",
            "SET transaction_isolation = 'read committed'",
            "SET transaction_isolation TO 'read committed'",
            "SET default_transaction_isolation = 'read committed'",
            "SET TRANSACTION_ISOLATION='READ COMMITTED'",
        ],
    )
    def test_recognised(self, sql):
        req = parse_set_isolation(sql)
        assert req is not None, sql
        assert req.level == "read committed"

    def test_modifiers_tolerated(self):
        req = parse_set_isolation("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE")
        assert req is not None
        assert req.level == "read committed"

    def test_modifier_first(self):
        req = parse_set_isolation("SET TRANSACTION READ WRITE, ISOLATION LEVEL READ COMMITTED")
        assert req is not None
        assert req.level == "read committed"

    @pytest.mark.parametrize(
        "sql",
        [
            "SET application_name = 'x'",
            "SET extra_float_digits = 3",
            "SET TimeZone = 'UTC'",
            "RESET ALL",
            "SELECT 1",
            "",
            # READ ONLY / READ WRITE carry no isolation level of their own.
            "SET TRANSACTION READ ONLY",
            "SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE",
        ],
    )
    def test_not_an_isolation_statement(self, sql):
        assert parse_set_isolation(sql) is None


# ---------------------------------------------------------------------------
# parse_set_isolation — which levels IRIS can actually honour
# ---------------------------------------------------------------------------


class TestParseSetIsolationSupport:
    def test_read_committed_supported(self):
        req = parse_set_isolation("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        assert req.supported is True
        assert req.iris_sql == "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"

    def test_read_uncommitted_supported(self):
        req = parse_set_isolation("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        assert req.supported is True
        assert req.level == "read uncommitted"
        assert req.iris_sql == "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"

    @pytest.mark.parametrize(
        "level_sql, level",
        [
            ("REPEATABLE READ", "repeatable read"),
            ("SERIALIZABLE", "serializable"),
        ],
    )
    def test_stronger_levels_unsupported(self, level_sql, level):
        req = parse_set_isolation(f"SET TRANSACTION ISOLATION LEVEL {level_sql}")
        assert req is not None
        assert req.level == level
        # IRIS rejects both (-96 and -1 respectively). Reporting fake success would
        # promise a guarantee the database cannot keep.
        assert req.supported is False
        assert req.iris_sql is None

    def test_unsupported_carries_sqlstate(self):
        req = parse_set_isolation("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        assert req.sqlstate == "0A000"
        assert req.condition == "feature_not_supported"
        assert "serializable" in req.message.lower()
        assert "read committed" in req.message.lower()

    def test_message_classifies_to_the_same_sqlstate(self):
        """Paths that carry only an error string must still reach 0A000."""
        from iris_pgwire.sql_translator.sqlstate import classify_iris_error

        req = parse_set_isolation("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        assert classify_iris_error(req.message) == (req.sqlstate, req.condition)

    def test_supported_has_no_error_fields(self):
        req = parse_set_isolation("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        assert req.sqlstate is None
        assert req.message is None

    def test_garbage_level_is_not_recognised(self):
        assert parse_set_isolation("SET TRANSACTION ISOLATION LEVEL BANANA") is None


# ---------------------------------------------------------------------------
# parse_isolation_show — both spellings clients send
# ---------------------------------------------------------------------------


class TestParseIsolationShow:
    @pytest.mark.parametrize(
        "sql, column",
        [
            ("SHOW TRANSACTION ISOLATION LEVEL", "transaction_isolation"),
            ("SHOW transaction_isolation", "transaction_isolation"),
            ("SHOW TRANSACTION_ISOLATION", "transaction_isolation"),
            ("SHOW default_transaction_isolation", "default_transaction_isolation"),
            ("show transaction isolation level;", "transaction_isolation"),
        ],
    )
    def test_recognised(self, sql, column):
        assert parse_isolation_show(sql) == column

    @pytest.mark.parametrize(
        "sql",
        [
            "SHOW server_version",
            "SHOW TIMEZONE",
            "SELECT 1",
            "",
        ],
    )
    def test_not_recognised(self, sql):
        assert parse_isolation_show(sql) is None


# ---------------------------------------------------------------------------
# Default reported level
# ---------------------------------------------------------------------------


class TestDefault:
    def test_default_is_iris_truth_not_postgres_default(self):
        """IRIS runs READ UNCOMMITTED unless told otherwise; report that, not PG's default."""
        assert DEFAULT_ISOLATION_LEVEL == "read uncommitted"

    def test_default_is_a_valid_postgres_value(self):
        # psycopg/JDBC parse the reply against PostgreSQL's own vocabulary.
        assert DEFAULT_ISOLATION_LEVEL in {
            "read uncommitted",
            "read committed",
            "repeatable read",
            "serializable",
        }


class TestIsolationRequestShape:
    def test_is_frozen(self):
        req = IsolationRequest(level="read committed", supported=True, iris_sql="SET ...")
        with pytest.raises(dataclasses.FrozenInstanceError):
            req.level = "serializable"  # type: ignore[misc]
