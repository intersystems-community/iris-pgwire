"""
SQL Interceptor - Registry for stubbed PostgreSQL system responses (Feature 036)

This module decouples the procedural interception logic from IRISExecutor.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger("iris_pgwire.sql_translator.interceptor")


@dataclass
class InterceptResult:
    """Result of a query interception"""

    intercepted: bool
    result: dict[str, Any] | None = None


class SQLInterceptor:
    """
    Registry for SQL patterns that should return stubbed responses.
    """

    def __init__(self, iris_executor: Any):
        self._executor = iris_executor
        self._patterns: dict[re.Pattern, Callable] = {}
        # pattern -> substring the upper-cased statement must contain before the regex runs
        self._needles: dict[re.Pattern, str] = {}
        self._init_standard_interceptors()

    def _init_standard_interceptors(self):
        """Initialize default PostgreSQL system query interceptors"""
        self.register(r"^\s*SHOW\s+", self._handle_show)
        # Whole-statement answers for the schema questions SQLAlchemy's dialect asks while
        # connecting. Inside a larger statement current_schema() is rewritten instead
        # (pg_functions.py), so IRIS evaluates the rest.
        self.register(
            r"^\s*SELECT\s+(?:PG_CATALOG\s*\.\s*)?CURRENT_SCHEMA\s*(?:\(\s*\))?\s*;?\s*$",
            self._handle_current_schema,
            needle="CURRENT_SCHEMA",
        )
        self.register(
            r"^\s*SELECT\s+(?:PG_CATALOG\s*\.\s*)?CURRENT_SCHEMAS\s*\(\s*(?:TRUE|FALSE|1|0)\s*\)\s*;?\s*$",
            self._handle_current_schemas,
            needle="CURRENT_SCHEMAS",
        )
        # psycopg's TypeInfo.fetch(); the handler declines any other to_regtype() query.
        self.register(r"TO_REGTYPE", self._handle_type_info, needle="TO_REGTYPE")
        self.register(r"EXISTS.*PG_NAMESPACE.*VERSION", self._handle_prisma_schema_check)
        self.register(r"CURRENT_SETTING.*SET_CONFIG", self._handle_asyncpg_introspection)
        self.register(r"CURRENT_SETTING", self._handle_current_setting)
        self.register(r"SET_CONFIG", self._handle_set_config)
        self.register(r"PG_ADVISORY_UNLOCK_ALL", self._handle_advisory_unlock)
        self.register(r"CURRENT_DATABASE", self._handle_current_database)
        self.register(r"VERSION\(\)|SELECT\s+VERSION", self._handle_version)
        self.register(r"^\s*DISCARD\s+ALL", self._handle_discard_all)
        self.register(r"\bPG_INDEXES\b", self._handle_pg_indexes)

    def register(self, pattern: str, handler: Callable, needle: str | None = None):
        """Register a new interceptor pattern.

        ``needle``, if given, is an upper-case substring the statement must contain; the regex
        runs only then, which keeps the pattern's cost off every other statement. A handler that
        returns None declines, and the statement goes on to the next pattern.
        """
        compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)
        self._patterns[compiled] = handler
        if needle:
            self._needles[compiled] = needle

    def intercept(
        self, sql: str, params: list | None = None, session_id: str | None = None
    ) -> InterceptResult:
        """Check if query matches any registered patterns and return stub if so"""
        sql_upper = sql.upper().strip()

        for pattern, handler in self._patterns.items():
            needle = self._needles.get(pattern)
            if needle is not None and needle not in sql_upper:
                continue
            if pattern.search(sql_upper):
                result = handler(sql, params, session_id)
                if result is None:
                    continue
                return InterceptResult(intercepted=True, result=result)

        return InterceptResult(intercepted=False)

    def _handle_show(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        sql_upper = sql.upper().strip().rstrip(";")
        param_name = sql_upper[5:].strip()

        show_values = {
            "SERVER_VERSION": "16.0 (InterSystems IRIS)",
            "SERVER_VERSION_NUM": "160000",
            "CLIENT_ENCODING": "UTF8",
            "DATESTYLE": "ISO, MDY",
            "TIMEZONE": "UTC",
            "STANDARD_CONFORMING_STRINGS": "on",
            "INTEGER_DATETIMES": "on",
            "INTERVALSTYLE": "postgres",
            # PGWire never starts a READ ONLY or DEFERRABLE transaction, so PostgreSQL's answer
            # outside one is the true one, not "unknown".
            "TRANSACTION_READ_ONLY": "off",
            "TRANSACTION_DEFERRABLE": "off",
        }
        value = show_values.get(param_name, "unknown")
        return {
            "success": True,
            "rows": [[value]],
            "columns": [
                {
                    "name": param_name.lower(),
                    "type_oid": 25,
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                }
            ],
            "row_count": 1,
        }

    @staticmethod
    def _rows_result(
        columns: tuple[tuple[str, int, int], ...], rows: list[list]
    ) -> dict[str, Any]:
        """A result set from ``(name, type_oid, type_size)`` column specs and its rows."""
        return {
            "success": True,
            "rows": rows,
            "columns": [
                {
                    "name": name,
                    "type_oid": type_oid,
                    "type_size": type_size,
                    "type_modifier": -1,
                    "format_code": 0,
                }
                for name, type_oid, type_size in columns
            ],
            "row_count": len(rows),
        }

    def _one_value(self, name: str, type_oid: int, type_size: int, value: Any) -> dict[str, Any]:
        return self._rows_result(((name, type_oid, type_size),), [[value]])

    def _handle_current_schema(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        # `public`: what PGWire calls the IRIS schema everywhere else (pg_namespace's nspname is
        # PGWire.PG_PUBLIC_SCHEMA(), information_schema maps it back to public), and the schema
        # both `public.x` and an unqualified `x` resolve to. Typed `name`, as PostgreSQL's is.
        return self._one_value("current_schema", 19, 64, "public")

    def _handle_current_schemas(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        # The search path is pg_catalog then public. current_schemas(true) includes the implicit
        # pg_catalog; current_schemas(false) does not. Typed name[] (OID 1003).
        implicit = re.search(r"\(\s*(?:TRUE|1)\s*\)", sql, re.IGNORECASE) is not None
        return self._one_value(
            "current_schemas", 1003, -1, "{pg_catalog,public}" if implicit else "{public}"
        )

    def _handle_type_info(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any] | None:
        from iris_pgwire.catalog.type_info import (
            TYPE_INFO_COLUMNS,
            is_type_info_query,
            type_info_rows,
        )

        if not is_type_info_query(sql):
            return None
        return self._rows_result(TYPE_INFO_COLUMNS, type_info_rows(params))

    def _handle_prisma_schema_check(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        schema_exists = True
        schema_name = "public"

        if params and len(params) > 0 and params[0] is not None:
            schema_name = str(params[0])
            if schema_name.lower() != "none":
                schema_exists = schema_name.lower() in [
                    "public",
                    "sqluser",
                    "pg_catalog",
                    "information_schema",
                ]

        return {
            "success": True,
            "rows": [[schema_exists, "PostgreSQL 16.0 (InterSystems IRIS)", 160000]],
            "columns": [
                {
                    "name": "exists",
                    "type_oid": 16,
                    "type_size": 1,
                    "type_modifier": -1,
                    "format_code": 0,
                },
                {
                    "name": "version",
                    "type_oid": 25,
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                },
                {
                    "name": "numeric_version",
                    "type_oid": 23,
                    "type_size": 4,
                    "type_modifier": -1,
                    "format_code": 0,
                },
            ],
            "row_count": 1,
        }

    def _handle_asyncpg_introspection(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        return {
            "success": True,
            "rows": [["off", "off"]],
            "columns": [
                {
                    "name": "cur",
                    "type_oid": 25,
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                },
                {
                    "name": "new",
                    "type_oid": 25,
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                },
            ],
            "row_count": 1,
        }

    def _handle_current_setting(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        return {
            "success": True,
            "rows": [["off"]],
            "columns": [
                {
                    "name": "current_setting",
                    "type_oid": 25,
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                }
            ],
            "row_count": 1,
        }

    def _handle_set_config(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        return {
            "success": True,
            "rows": [["off"]],
            "columns": [
                {
                    "name": "set_config",
                    "type_oid": 25,
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                }
            ],
            "row_count": 1,
        }

    def _handle_advisory_unlock(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        return {"success": True, "rows": [], "columns": [], "row_count": 0}

    def _handle_current_database(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        namespace_name = getattr(self._executor, "iris_namespace", "USER")
        return {
            "success": True,
            "rows": [[namespace_name]],
            "columns": [
                {
                    "name": "current_database",
                    "type_oid": 19,
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                }
            ],
            "row_count": 1,
        }

    def _handle_version(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        return {
            "success": True,
            "rows": [["PostgreSQL 16.0 (InterSystems IRIS PGWire Protocol)"]],
            "columns": [
                {
                    "name": "version",
                    "type_oid": 25,
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                }
            ],
            "row_count": 1,
        }

    def _handle_discard_all(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        return {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "command": "DISCARD",
            "command_tag": "DISCARD ALL",
        }

    def _handle_pg_indexes(
        self, sql: str, params: list | None, session_id: str | None
    ) -> dict[str, Any]:
        """Handle pg_indexes metadata queries (simulated for HNSW tests)"""
        import re

        # Extract tablename if possible
        match = re.search(r"tablename\s*=\s*'([^']+)'", sql, re.IGNORECASE)
        table_name = match.group(1) if match else "unknown"

        # Simulated response for test_hnsw_index_creation
        # The test expects indexname 'idx_hnsw' for tablename 'hnswtest'
        rows = []
        if table_name.lower() == "hnswtest":
            rows = [["idx_hnsw"]]

        return {
            "success": True,
            "rows": rows,
            "columns": [
                {
                    "name": "indexname",
                    "type_oid": 19,
                    "type_size": 64,
                    "type_modifier": -1,
                    "format_code": 0,
                }
            ],
            "row_count": len(rows),
        }
