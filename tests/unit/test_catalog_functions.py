"""
Unit Tests for PostgreSQL Catalog Function Emulation

Tests format_type, pg_get_constraintdef, pg_get_serial_sequence,
pg_get_indexdef, pg_get_viewdef, and the handle() dispatch interface.
No live IRIS connection required — all executor calls are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.catalog.catalog_functions import CatalogFunctionHandler, CatalogFunctionResult
from iris_pgwire.catalog.oid_generator import OIDGenerator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def oid_gen():
    return OIDGenerator()


@pytest.fixture()
def executor():
    return MagicMock()


@pytest.fixture()
def handler(oid_gen, executor):
    return CatalogFunctionHandler(oid_gen, executor)


# ---------------------------------------------------------------------------
# CatalogFunctionResult dataclass
# ---------------------------------------------------------------------------


class TestCatalogFunctionResult:
    def test_basic_creation(self):
        result = CatalogFunctionResult(
            function_name="format_type",
            arguments=[23, -1],
            result="integer",
        )
        assert result.function_name == "format_type"
        assert result.arguments == [23, -1]
        assert result.result == "integer"
        assert result.error is None

    def test_null_result(self):
        result = CatalogFunctionResult(
            function_name="pg_get_viewdef",
            arguments=[99999],
            result=None,
            error=None,
        )
        assert result.result is None
        assert result.error is None

    def test_error_result(self):
        result = CatalogFunctionResult(
            function_name="format_type",
            arguments=[],
            result=None,
            error="something went wrong",
        )
        assert result.error == "something went wrong"


# ---------------------------------------------------------------------------
# format_type
# ---------------------------------------------------------------------------


class TestFormatType:
    def test_integer_no_modifier(self, handler):
        assert handler.format_type(23, -1) == "integer"

    def test_text_no_modifier(self, handler):
        assert handler.format_type(25, -1) == "text"

    def test_boolean_no_modifier(self, handler):
        assert handler.format_type(16, -1) == "boolean"

    def test_bigint_no_modifier(self, handler):
        assert handler.format_type(20, -1) == "bigint"

    def test_smallint_no_modifier(self, handler):
        assert handler.format_type(21, -1) == "smallint"

    def test_real_no_modifier(self, handler):
        assert handler.format_type(700, -1) == "real"

    def test_double_precision_no_modifier(self, handler):
        assert handler.format_type(701, -1) == "double precision"

    def test_varchar_with_length(self, handler):
        # typmod = length + 4 → 255 + 4 = 259
        result = handler.format_type(1043, 259)
        assert result == "character varying(255)"

    def test_char_with_length(self, handler):
        result = handler.format_type(1042, 14)  # length=10
        assert result == "character(10)"

    def test_varchar_no_modifier(self, handler):
        result = handler.format_type(1043, -1)
        assert result == "character varying"

    def test_numeric_with_precision_scale(self, handler):
        # typmod = ((10 << 16) + 2) + 4 = 655366
        result = handler.format_type(1700, 655366)
        assert result == "numeric(10,2)"

    def test_numeric_no_modifier(self, handler):
        result = handler.format_type(1700, -1)
        assert result == "numeric"

    def test_timestamp_without_tz(self, handler):
        # typmod = precision + something; decode_timestamp_precision logic
        # precision=6 → typmod=6 (> 0)
        result = handler.format_type(1114, 6)
        assert "timestamp" in result
        assert "without time zone" in result

    def test_timestamp_with_tz(self, handler):
        result = handler.format_type(1184, 6)
        assert "timestamp" in result
        assert "with time zone" in result

    def test_time_without_tz(self, handler):
        result = handler.format_type(1083, 6)
        assert "time" in result
        assert "without time zone" in result

    def test_time_with_tz(self, handler):
        result = handler.format_type(1266, 6)
        assert "time" in result
        assert "with time zone" in result

    def test_bit_fixed_length(self, handler):
        result = handler.format_type(1560, 8)  # bit(4) → typmod=8
        assert "bit" in result

    def test_bit_varying(self, handler):
        result = handler.format_type(1562, 8)
        assert "bit varying" in result

    def test_unknown_oid_returns_none(self, handler):
        assert handler.format_type(99999, -1) is None

    def test_oid_zero_modifier_returns_base_type(self, handler):
        # typmod=0 (<=0) → no modifier applied
        result = handler.format_type(23, 0)
        assert result == "integer"

    def test_uuid_type(self, handler):
        result = handler.format_type(2950, -1)
        assert result == "uuid"

    def test_jsonb_type(self, handler):
        result = handler.format_type(3802, -1)
        assert result == "jsonb"

    def test_json_type(self, handler):
        result = handler.format_type(114, -1)
        assert result == "json"

    def test_date_type(self, handler):
        result = handler.format_type(1082, -1)
        assert result == "date"

    def test_bytea_type(self, handler):
        result = handler.format_type(17, -1)
        assert result == "bytea"


# ---------------------------------------------------------------------------
# pg_get_constraintdef
# ---------------------------------------------------------------------------


class TestPgGetConstraintdef:
    def _make_handler_with_constraint(self, oid_gen, executor, cname, ctype, schema="SQLUser"):
        """Helper that wires executor to return a constraint matching the generated OID."""
        oid = oid_gen.get_constraint_oid(cname, schema)

        handler = CatalogFunctionHandler(oid_gen, executor)

        # _get_constraint_metadata
        executor._execute_iris_query.side_effect = None

        def fake_query(query):
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query and "TABLE_NAME" not in query.replace("TABLE_CONSTRAINTS", ""):
                # Detect which query by content keywords
                if "UNIQUE_CONSTRAINT_SCHEMA" in query:
                    return None
                # Main constraint listing
                return {
                    "rows": [
                        [schema, cname, ctype, "mytable"],
                    ]
                }
            if "KEY_COLUMN_USAGE" in query:
                return {"rows": [["id"], ["name"]]}
            return None

        executor._execute_iris_query.side_effect = fake_query
        return handler, oid

    def test_primary_key(self, oid_gen, executor):
        cname = "pk_users"
        oid = oid_gen.get_constraint_oid(cname, "SQLUser")
        handler = CatalogFunctionHandler(oid_gen, executor)

        call_count = [0]

        def fake_query(query):
            call_count[0] += 1
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query:
                return {"rows": [["SQLUser", cname, "PRIMARY KEY", "users"]]}
            if "KEY_COLUMN_USAGE" in query:
                return {"rows": [["id"]]}
            return None

        executor._execute_iris_query.side_effect = fake_query
        result = handler.pg_get_constraintdef(oid)
        assert result == "PRIMARY KEY (id)"

    def test_unique_constraint(self, oid_gen, executor):
        cname = "uq_email"
        oid = oid_gen.get_constraint_oid(cname, "SQLUser")
        handler = CatalogFunctionHandler(oid_gen, executor)

        def fake_query(query):
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query:
                return {"rows": [["SQLUser", cname, "UNIQUE", "users"]]}
            if "KEY_COLUMN_USAGE" in query:
                return {"rows": [["email"]]}
            return None

        executor._execute_iris_query.side_effect = fake_query
        result = handler.pg_get_constraintdef(oid)
        assert result == "UNIQUE (email)"

    def test_check_constraint(self, oid_gen, executor):
        cname = "chk_age"
        oid = oid_gen.get_constraint_oid(cname, "SQLUser")
        handler = CatalogFunctionHandler(oid_gen, executor)

        def fake_query(query):
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query:
                return {"rows": [["SQLUser", cname, "CHECK", "users"]]}
            if "KEY_COLUMN_USAGE" in query:
                return {"rows": []}
            return None

        executor._execute_iris_query.side_effect = fake_query
        result = handler.pg_get_constraintdef(oid)
        assert result == "CHECK ((expression))"

    def test_foreign_key(self, oid_gen, executor):
        cname = "fk_author"
        oid = oid_gen.get_constraint_oid(cname, "SQLUser")
        handler = CatalogFunctionHandler(oid_gen, executor)

        call_log = []

        def fake_query(query):
            call_log.append(query[:60])
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query and "UNIQUE_CONSTRAINT" not in query:
                return {"rows": [["SQLUser", cname, "FOREIGN KEY", "posts"]]}
            if "KEY_COLUMN_USAGE" in query and cname in query:
                return {"rows": [["author_id"]]}
            if "REFERENTIAL_CONSTRAINTS" in query:
                return {"rows": [["SQLUser", "pk_users", "NO ACTION", "CASCADE"]]}
            if "TABLE_CONSTRAINTS" in query and "pk_users" in query:
                return {"rows": [["SQLUser", "pk_users", "PRIMARY KEY", "users"]]}
            if "KEY_COLUMN_USAGE" in query and "pk_users" in query:
                return {"rows": [["id"]]}
            return None

        executor._execute_iris_query.side_effect = fake_query
        result = handler.pg_get_constraintdef(oid)
        assert result is not None
        assert "FOREIGN KEY" in result
        assert "author_id" in result

    def test_fk_with_on_delete_rule(self, oid_gen, executor):
        cname = "fk_cascade"
        oid = oid_gen.get_constraint_oid(cname, "SQLUser")
        handler = CatalogFunctionHandler(oid_gen, executor)

        def fake_query(query):
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query and "UNIQUE_CONSTRAINT" not in query:
                return {"rows": [["SQLUser", cname, "FOREIGN KEY", "posts"]]}
            if "KEY_COLUMN_USAGE" in query and cname in query:
                return {"rows": [["user_id"]]}
            if "REFERENTIAL_CONSTRAINTS" in query:
                return {"rows": [["SQLUser", "pk_users", "NO ACTION", "CASCADE"]]}
            if "TABLE_CONSTRAINTS" in query and "pk_users" in query:
                return {"rows": [["SQLUser", "pk_users", "PRIMARY KEY", "users"]]}
            if "KEY_COLUMN_USAGE" in query and "pk_users" in query:
                return {"rows": [["id"]]}
            return None

        executor._execute_iris_query.side_effect = fake_query
        result = handler.pg_get_constraintdef(oid)
        assert "ON DELETE CASCADE" in result

    def test_nonexistent_constraint_returns_none(self, oid_gen, executor):
        handler = CatalogFunctionHandler(oid_gen, executor)
        executor._execute_iris_query.return_value = {"rows": []}
        result = handler.pg_get_constraintdef(99999999)
        assert result is None

    def test_executor_returns_none_gives_none(self, oid_gen, executor):
        handler = CatalogFunctionHandler(oid_gen, executor)
        executor._execute_iris_query.return_value = None
        assert handler.pg_get_constraintdef(12345) is None

    def test_executor_exception_returns_none(self, oid_gen, executor):
        handler = CatalogFunctionHandler(oid_gen, executor)
        executor._execute_iris_query.side_effect = RuntimeError("db error")
        assert handler.pg_get_constraintdef(12345) is None

    def test_pretty_flag_accepted(self, oid_gen, executor):
        cname = "pk_test"
        oid = oid_gen.get_constraint_oid(cname, "SQLUser")
        handler = CatalogFunctionHandler(oid_gen, executor)

        def fake_query(query):
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query:
                return {"rows": [["SQLUser", cname, "PRIMARY KEY", "test"]]}
            if "KEY_COLUMN_USAGE" in query:
                return {"rows": [["id"]]}
            return None

        executor._execute_iris_query.side_effect = fake_query
        # pretty=True should not crash, result same
        result = handler.pg_get_constraintdef(oid, pretty=True)
        assert result == "PRIMARY KEY (id)"

    def test_pk_no_columns_returns_none(self, oid_gen, executor):
        """PRIMARY KEY with no columns found returns None."""
        cname = "pk_orphan"
        oid = oid_gen.get_constraint_oid(cname, "SQLUser")
        handler = CatalogFunctionHandler(oid_gen, executor)

        def fake_query(query):
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query:
                return {"rows": [["SQLUser", cname, "PRIMARY KEY", "t"]]}
            if "KEY_COLUMN_USAGE" in query:
                return {"rows": []}
            return None

        executor._execute_iris_query.side_effect = fake_query
        assert handler.pg_get_constraintdef(oid) is None

    def test_fk_no_ref_info_returns_none(self, oid_gen, executor):
        cname = "fk_noref"
        oid = oid_gen.get_constraint_oid(cname, "SQLUser")
        handler = CatalogFunctionHandler(oid_gen, executor)

        def fake_query(query):
            if "TABLE_CONSTRAINTS" in query and "KEY_COLUMN_USAGE" not in query and "UNIQUE_CONSTRAINT" not in query:
                return {"rows": [["SQLUser", cname, "FOREIGN KEY", "posts"]]}
            if "KEY_COLUMN_USAGE" in query:
                return {"rows": [["col"]]}
            if "REFERENTIAL_CONSTRAINTS" in query:
                return {"rows": []}  # no referential data
            return None

        executor._execute_iris_query.side_effect = fake_query
        assert handler.pg_get_constraintdef(oid) is None


# ---------------------------------------------------------------------------
# pg_get_serial_sequence
# ---------------------------------------------------------------------------


class TestPgGetSerialSequence:
    def test_identity_column_returns_sequence_name(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": [["", "YES"]]}
        result = handler.pg_get_serial_sequence("users", "id")
        assert result == "public.users_id_seq"

    def test_identity_via_column_default(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": [["IDENTITY(1,1)", "NO"]]}
        result = handler.pg_get_serial_sequence("users", "id")
        assert result == "public.users_id_seq"

    def test_non_serial_column_returns_none(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": [["", "NO"]]}
        result = handler.pg_get_serial_sequence("users", "name")
        assert result is None

    def test_column_not_found_returns_none(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": []}
        result = handler.pg_get_serial_sequence("users", "nonexistent")
        assert result is None

    def test_executor_returns_none_gives_none(self, handler, executor):
        executor._execute_iris_query.return_value = None
        assert handler.pg_get_serial_sequence("users", "id") is None

    def test_executor_exception_returns_none(self, handler, executor):
        executor._execute_iris_query.side_effect = RuntimeError("connection lost")
        assert handler.pg_get_serial_sequence("users", "id") is None

    def test_schema_dot_table_parses_correctly(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": [["", "YES"]]}
        result = handler.pg_get_serial_sequence("myschema.orders", "order_id")
        assert result == "public.orders_order_id_seq"

    def test_default_schema_applied_when_no_dot(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": [["", "YES"]]}
        result = handler.pg_get_serial_sequence("products", "id")
        assert result == "public.products_id_seq"

    def test_only_one_element_row(self, handler, executor):
        """Row with only one column (no is_identity) — column_default None."""
        executor._execute_iris_query.return_value = {"rows": [[None]]}
        assert handler.pg_get_serial_sequence("t", "c") is None


# ---------------------------------------------------------------------------
# pg_get_indexdef
# ---------------------------------------------------------------------------


class TestPgGetIndexdef:
    def test_nonexistent_index_returns_none(self, handler):
        # _get_index_metadata always returns None (not yet implemented)
        assert handler.pg_get_indexdef(99999) is None

    def test_column_request_on_nonexistent_index_returns_none(self, handler):
        assert handler.pg_get_indexdef(99999, column=1) is None

    def test_full_def_with_mocked_metadata(self, oid_gen, executor):
        handler = CatalogFunctionHandler(oid_gen, executor)
        # Patch _get_index_metadata to return something
        index_info = {
            "index_name": "users_pkey",
            "table_name": "users",
            "is_unique": True,
            "index_columns": ["id"],
        }
        handler._get_index_metadata = MagicMock(return_value=index_info)
        result = handler.pg_get_indexdef(12345, 0)
        assert "CREATE UNIQUE INDEX" in result
        assert "users_pkey" in result
        assert "users" in result
        assert "id" in result

    def test_non_unique_index(self, oid_gen, executor):
        handler = CatalogFunctionHandler(oid_gen, executor)
        index_info = {
            "index_name": "idx_name",
            "table_name": "orders",
            "is_unique": False,
            "index_columns": ["created_at"],
        }
        handler._get_index_metadata = MagicMock(return_value=index_info)
        result = handler.pg_get_indexdef(12345, 0)
        assert result.startswith("CREATE INDEX")
        assert "UNIQUE" not in result

    def test_column_request_returns_column_name(self, oid_gen, executor):
        handler = CatalogFunctionHandler(oid_gen, executor)
        index_info = {
            "index_name": "idx_composite",
            "table_name": "tbl",
            "is_unique": False,
            "index_columns": ["col_a", "col_b"],
        }
        handler._get_index_metadata = MagicMock(return_value=index_info)
        assert handler.pg_get_indexdef(12345, column=1) == "col_a"
        assert handler.pg_get_indexdef(12345, column=2) == "col_b"

    def test_column_out_of_range_returns_none(self, oid_gen, executor):
        handler = CatalogFunctionHandler(oid_gen, executor)
        index_info = {
            "index_name": "idx",
            "table_name": "tbl",
            "is_unique": False,
            "index_columns": ["col_a"],
        }
        handler._get_index_metadata = MagicMock(return_value=index_info)
        assert handler.pg_get_indexdef(12345, column=5) is None


# ---------------------------------------------------------------------------
# pg_get_viewdef
# ---------------------------------------------------------------------------


class TestPgGetViewdef:
    def test_always_returns_none(self, handler):
        assert handler.pg_get_viewdef(12345) is None

    def test_pretty_flag_still_none(self, handler):
        assert handler.pg_get_viewdef(12345, pretty=True) is None

    def test_zero_oid_returns_none(self, handler):
        assert handler.pg_get_viewdef(0) is None


# ---------------------------------------------------------------------------
# handle() dispatch
# ---------------------------------------------------------------------------


class TestHandleDispatch:
    def test_format_type_dispatch(self, handler):
        result = handler.handle("format_type", (23, -1))
        assert isinstance(result, CatalogFunctionResult)
        assert result.function_name == "format_type"
        assert result.result == "integer"
        assert result.error is None

    def test_format_type_single_arg(self, handler):
        result = handler.handle("format_type", (23,))
        assert result.result == "integer"

    def test_pg_get_viewdef_dispatch(self, handler):
        result = handler.handle("pg_get_viewdef", (99999,))
        assert result.function_name == "pg_get_viewdef"
        assert result.result is None
        assert result.error is None

    def test_pg_get_viewdef_pretty_dispatch(self, handler):
        result = handler.handle("pg_get_viewdef", (99999, "true"))
        assert result.result is None

    def test_unknown_function_returns_error(self, handler):
        result = handler.handle("pg_does_not_exist", (1, 2))
        assert result.result is None
        assert result.error is not None
        assert "Unknown catalog function" in result.error

    def test_pg_get_serial_sequence_dispatch(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": [["", "YES"]]}
        result = handler.handle("pg_get_serial_sequence", ("users", "id"))
        assert result.function_name == "pg_get_serial_sequence"
        assert result.result == "public.users_id_seq"

    def test_pg_get_constraintdef_dispatch_not_found(self, handler, executor):
        executor._execute_iris_query.return_value = None
        result = handler.handle("pg_get_constraintdef", (99999,))
        assert result.function_name == "pg_get_constraintdef"
        assert result.result is None
        assert result.error is None

    def test_pg_get_indexdef_dispatch_not_found(self, handler):
        result = handler.handle("pg_get_indexdef", (99999,))
        assert result.function_name == "pg_get_indexdef"
        assert result.result is None

    def test_pg_get_indexdef_dispatch_with_column(self, handler):
        result = handler.handle("pg_get_indexdef", (99999, 1, "false"))
        assert result.result is None

    def test_handle_exception_yields_error_result(self, handler):
        """If the underlying method raises, handle() catches and returns error."""
        handler.format_type = MagicMock(side_effect=ValueError("boom"))
        result = handler.handle("format_type", (23, -1))
        assert result.error is not None
        assert "boom" in result.error

    def test_arguments_preserved_in_result(self, handler):
        result = handler.handle("format_type", (23, -1))
        assert result.arguments == [23, -1]

    def test_unknown_function_arguments_preserved(self, handler):
        result = handler.handle("not_a_function", ("a", "b"))
        assert result.arguments == ["a", "b"]


# ---------------------------------------------------------------------------
# _parse_pretty helper
# ---------------------------------------------------------------------------


class TestParsePretty:
    def test_true_string(self, handler):
        assert CatalogFunctionHandler._parse_pretty(("true",), index=0) is True

    def test_false_string(self, handler):
        assert CatalogFunctionHandler._parse_pretty(("false",), index=0) is False

    def test_TRUE_uppercase(self, handler):
        assert CatalogFunctionHandler._parse_pretty(("TRUE",), index=0) is True

    def test_missing_index_returns_false(self, handler):
        assert CatalogFunctionHandler._parse_pretty((), index=1) is False

    def test_default_index_is_1(self, handler):
        # args has index 0 but default index=1 — so returns False
        assert CatalogFunctionHandler._parse_pretty(("true",)) is False


# ---------------------------------------------------------------------------
# _get_constraint_columns helper
# ---------------------------------------------------------------------------


class TestGetConstraintColumns:
    def test_returns_lowercase_columns(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": [["UserID"], ["Name"]]}
        cols = handler._get_constraint_columns("SQLUser", "pk_test")
        assert cols == ["userid", "name"]

    def test_empty_result(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": []}
        assert handler._get_constraint_columns("SQLUser", "no_such") == []

    def test_none_result(self, handler, executor):
        executor._execute_iris_query.return_value = None
        assert handler._get_constraint_columns("SQLUser", "x") == []

    def test_exception_returns_empty(self, handler, executor):
        executor._execute_iris_query.side_effect = RuntimeError("oops")
        assert handler._get_constraint_columns("SQLUser", "x") == []


# ---------------------------------------------------------------------------
# _get_fk_references helper (via _fetch_referential_constraint / _fetch_referenced_table)
# ---------------------------------------------------------------------------


class TestGetFkReferences:
    def test_full_fk_ref(self, handler, executor):
        # _fetch_referential_constraint returns (ref_schema, ref_constraint_name, update_rule, delete_rule)
        # _fetch_referenced_table queries TABLE_CONSTRAINTS for TABLE_NAME, returns rows[0][0]
        # _get_constraint_columns queries KEY_COLUMN_USAGE
        def fake(query):
            if "REFERENTIAL_CONSTRAINTS" in query:
                return {"rows": [["SQLUser", "pk_users", "NO ACTION", "NO ACTION"]]}
            if "TABLE_CONSTRAINTS" in query:
                # _fetch_referenced_table returns TABLE_NAME from row[0][0]
                return {"rows": [["users"]]}
            if "KEY_COLUMN_USAGE" in query:
                return {"rows": [["id"]]}
            return None

        executor._execute_iris_query.side_effect = fake
        result = handler._get_fk_references("SQLUser", "fk_author")
        assert result is not None
        assert result["ref_table"] == "users"
        assert result["ref_columns"] == ["id"]

    def test_missing_referential_constraint_returns_none(self, handler, executor):
        executor._execute_iris_query.return_value = {"rows": []}
        assert handler._get_fk_references("SQLUser", "fk_x") is None

    def test_missing_ref_table_returns_none(self, handler, executor):
        def fake(query):
            if "REFERENTIAL_CONSTRAINTS" in query:
                return {"rows": [["SQLUser", "pk_ref", "NO ACTION", "NO ACTION"]]}
            if "TABLE_CONSTRAINTS" in query:
                return {"rows": []}
            return None

        executor._execute_iris_query.side_effect = fake
        assert handler._get_fk_references("SQLUser", "fk_y") is None

    def test_exception_returns_none(self, handler, executor):
        executor._execute_iris_query.side_effect = RuntimeError("fail")
        assert handler._get_fk_references("SQLUser", "fk_z") is None
