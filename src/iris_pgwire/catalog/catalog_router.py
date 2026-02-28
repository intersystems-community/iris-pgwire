"""
Catalog Router

Routes pg_catalog and information_schema queries to appropriate emulators.
Handles query parsing, array parameter translation, and regclass resolution.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from iris_pgwire.type_mapping import get_type_mapping

from .oid_generator import OIDGenerator
from .pg_attrdef import PgAttrdefEmulator
from .pg_attribute import PgAttributeEmulator
from .pg_class import PgClassEmulator
from .pg_constraint import PgConstraintEmulator
from .pg_index import PgIndexEmulator
from .pg_namespace import PgNamespaceEmulator
from .pg_type import PgTypeEmulator

logger = structlog.get_logger(__name__)


@dataclass
class CatalogQueryResult:
    """
    Result from a catalog query execution.

    Matches the format expected by iris_executor.py.
    """

    success: bool
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    command_tag: str = "SELECT"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format expected by iris_executor."""
        return {
            "success": self.success,
            "rows": self.rows,
            "columns": self.columns,
            "row_count": self.row_count,
            "command_tag": self.command_tag,
            "error": self.error,
        }


class CatalogRouter:
    """
    Route catalog queries to emulators.

    Responsibilities:
    - Detect pg_catalog/information_schema queries
    - Extract referenced catalog tables
    - Translate array parameters (ANY($1) → IN)
    - Resolve regclass casts
    """

    # PostgreSQL catalog tables we emulate
    CATALOG_TABLES = {
        "pg_class",
        "pg_namespace",
        "pg_attribute",
        "pg_constraint",
        "pg_index",
        "pg_attrdef",
        "pg_type",
        "pg_proc",
        "pg_description",
        "pg_depend",
        "pg_am",
        "pg_collation",
        "pg_database",
        "pg_enum",
        "pg_extension",
        "pg_foreign_table",
        "pg_inherits",
        "pg_roles",
        "pg_settings",
        "pg_stat_user_tables",
        "pg_trigger",
        "pg_views",
        "pg_indexes",
    }

    # information_schema tables
    INFO_SCHEMA_TABLES = {
        "tables",
        "columns",
        "table_constraints",
        "key_column_usage",
        "referential_constraints",
        "schemata",
        "views",
    }

    CATALOG_HANDLER_PRIORITY = [
        "pg_enum",
        "pg_type",
        "pg_extension",
        "pg_namespace",
        "pg_class",
        "information_schema.columns",
        "pg_attribute",
        "pg_constraint",
        "pg_index",
        "pg_attrdef",
    ]

    def __init__(self, oid_generator: OIDGenerator | None = None):
        """
        Initialize catalog router.

        Args:
            oid_generator: Optional OIDGenerator for regclass resolution
        """
        self.oid_gen = oid_generator or OIDGenerator()

        # Patterns for query detection
        self._pg_catalog_pattern = re.compile(r"\bpg_catalog\.(\w+)\b", re.IGNORECASE)
        self._pg_table_pattern = re.compile(r"\bpg_(\w+)\b", re.IGNORECASE)
        self._info_schema_pattern = re.compile(r"\binformation_schema\.(\w+)\b", re.IGNORECASE)
        self._any_param_pattern = re.compile(r"=\s*ANY\s*\(\s*\$(\d+)\s*\)", re.IGNORECASE)
        self._regclass_pattern = re.compile(r"'([^']+)'::regclass", re.IGNORECASE)
        self._catalog_handler_map = {
            "pg_enum": self._handle_pg_enum,
            "pg_type": self._handle_pg_type,
            "pg_extension": self._handle_pg_extension,
            "pg_namespace": self._handle_pg_namespace,
            "pg_class": self._handle_pg_class,
            "information_schema.columns": self._handle_information_schema_columns,
            "pg_attribute": self._handle_pg_attribute,
            "pg_constraint": self._handle_pg_constraint,
            "pg_index": self._handle_pg_index,
            "pg_attrdef": self._handle_pg_attrdef,
        }

    def can_handle(self, query: str) -> bool:
        """
        Check if query targets pg_catalog or information_schema.

        Args:
            query: SQL query string

        Returns:
            True if query targets system catalogs
        """
        upper_query = query.upper()

        # Check for explicit pg_catalog or information_schema prefix
        if "PG_CATALOG" in upper_query or "INFORMATION_SCHEMA" in upper_query:
            return True

        # Check for pg_* tables without prefix
        tables = self.extract_catalog_tables(query)
        return len(tables) > 0

    def extract_catalog_tables(self, query: str) -> set[str]:
        """
        Extract catalog table names from query.

        Args:
            query: SQL query string

        Returns:
            Set of catalog table names (lowercase)
        """
        words = set(re.findall(r"\b(\w+)\b", query.lower()))
        tables: set[str] = set()

        # Find pg_* references
        for word in words:
            if word.startswith("pg_"):
                if word in self.CATALOG_TABLES or len(word) > 3:
                    tables.add(word)

        # Find information_schema tables
        if "information_schema" in words:
            for word in words:
                if word in self.INFO_SCHEMA_TABLES:
                    tables.add(f"information_schema.{word}")

        return tables

    def has_array_param(self, query: str) -> bool:
        """
        Check if query contains ANY($n) array parameter pattern.

        Args:
            query: SQL query string

        Returns:
            True if query contains array parameter
        """
        return bool(self._any_param_pattern.search(query))

    def translate_array_param(self, query: str, values: list[Any], param_index: int = 1) -> str:
        """
        Translate ANY($n) to IN (value1, value2, ...).

        Args:
            query: SQL query with ANY($n) pattern
            values: List of values to expand
            param_index: Parameter index (default 1)

        Returns:
            Query with IN clause instead of ANY
        """
        if not values:
            # Empty array - use impossible condition
            return re.sub(
                rf"=\s*ANY\s*\(\s*\${param_index}\s*\)",
                "IN (NULL)",
                query,
                flags=re.IGNORECASE,
            )

        # Format values for IN clause
        formatted_values = []
        for v in values:
            if isinstance(v, str):
                # Escape single quotes and wrap in quotes
                escaped = v.replace("'", "''")
                formatted_values.append(f"'{escaped}'")
            elif v is None:
                formatted_values.append("NULL")
            else:
                formatted_values.append(str(v))

        in_clause = f"IN ({', '.join(formatted_values)})"

        return re.sub(
            rf"=\s*ANY\s*\(\s*\${param_index}\s*\)",
            in_clause,
            query,
            flags=re.IGNORECASE,
        )

    def has_regclass_cast(self, query: str) -> bool:
        """
        Check if query contains ::regclass cast.

        Args:
            query: SQL query string

        Returns:
            True if query contains regclass cast
        """
        return bool(self._regclass_pattern.search(query))

    def resolve_regclass(self, table_name: str, schema: str = IRIS_SCHEMA) -> int:
        """
        Resolve table name to OID (like ::regclass).

        Args:
            table_name: Table name (may include schema prefix)
            schema: Default schema if not specified in name

        Returns:
            Table OID
        """
        # Handle schema.table format
        if "." in table_name:
            parts = table_name.split(".", 1)
            schema = parts[0]
            table_name = parts[1]

        # Handle quoted identifiers
        table_name = table_name.strip('"')

        return self.oid_gen.get_table_oid(table_name, schema)

    def translate_regclass_casts(self, query: str, schema: str = IRIS_SCHEMA) -> str:
        """
        Replace 'tablename'::regclass with resolved OID.

        Args:
            query: SQL query with regclass casts
            schema: Default schema for resolution

        Returns:
            Query with OIDs instead of regclass casts
        """

        def replace_regclass(match: re.Match) -> str:
            table_name = match.group(1)
            oid = self.resolve_regclass(table_name, schema)
            return str(oid)

        return self._regclass_pattern.sub(replace_regclass, query)

    def get_target_catalog(self, query: str) -> str | None:
        """
        Get primary catalog table targeted by query.

        Args:
            query: SQL query string

        Returns:
            Primary catalog table name or None
        """
        tables = self.extract_catalog_tables(query)
        if not tables:
            return None

        # Priority order for Prisma queries
        priority = [
            "pg_class",
            "pg_attribute",
            "pg_namespace",
            "pg_constraint",
            "pg_index",
            "pg_attrdef",
            "pg_type",
        ]

        for table in priority:
            if table in tables:
                return table

        # Return first found
        return next(iter(tables))

    async def handle_catalog_query(
        self,
        sql: str,
        params: list | tuple | None = None,
        session_id: str | None = None,
        executor=None,
    ) -> dict[str, Any] | None:
        """
        Intercept and emulate PostgreSQL system catalog queries.
        Consolidated from IRISExecutor for use in both embedded and external modes.
        """
        sql_upper = sql.upper()
        logger.debug(
            "CatalogRouter.handle_catalog_query",
            sql=sql,
            sql_upper=sql_upper,
            session_id=session_id,
        )

        tables = self.extract_catalog_tables(sql)
        for table in self.CATALOG_HANDLER_PRIORITY:
            if table not in tables:
                continue
            handler = self._catalog_handler_map.get(table)
            if not handler:
                continue
            result = await handler(sql, sql_upper, params, session_id, executor)
            if result is not None:
                return result

        if self.can_handle(sql):
            target = self.get_target_catalog(sql)
            logger.info(f"Intercepting {target} query (empty fallback)", session_id=session_id)
            return {
                "success": True,
                "rows": [],
                "columns": [],
                "row_count": 0,
                "command": "SELECT",
                "command_tag": "SELECT 0",
            }

        return None

    async def _handle_pg_enum(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        if "PG_ENUM" not in sql_upper:
            return None

        logger.debug("Matched PG_ENUM block")
        logger.info(
            "Intercepting pg_enum query (returning empty with column metadata)",
            sql_preview=sql[:100],
            session_id=session_id,
        )
        columns = self._build_pg_enum_columns(sql)
        return self._build_success_response([], columns)

    async def _handle_pg_type(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        if "PG_TYPE" not in sql_upper:
            return None

        logger.debug("Matched PG_TYPE block")
        logger.info("Intercepting pg_type query", sql_preview=sql[:150], session_id=session_id)
        emulator = PgTypeEmulator(self.oid_gen)
        columns = emulator.get_column_definitions()
        rows = [list(row) for row in emulator.get_all_as_rows()]

        rows = self._filter_pg_type_rows_by_name(sql, rows)
        rows = self._filter_pg_type_rows_by_namespace(rows, params)
        columns, rows = self._project_pg_type_columns(sql, columns, rows)
        rows = [tuple(row) for row in rows]
        return self._build_success_response(rows, columns)

    async def _handle_pg_extension(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        if "PG_EXTENSION" not in sql_upper:
            return None

        logger.debug("Matched PG_EXTENSION block")
        logger.info("Intercepting pg_extension query", sql_preview=sql[:100], session_id=session_id)
        columns = [
            {"name": "oid", "type_oid": 26, "type_size": 4, "type_modifier": -1, "format_code": 0},
            {
                "name": "extname",
                "type_oid": 19,
                "type_size": 64,
                "type_modifier": -1,
                "format_code": 0,
            },
            {
                "name": "extowner",
                "type_oid": 26,
                "type_size": 4,
                "type_modifier": -1,
                "format_code": 0,
            },
            {
                "name": "extnamespace",
                "type_oid": 26,
                "type_size": 4,
                "type_modifier": -1,
                "format_code": 0,
            },
            {
                "name": "extrelocatable",
                "type_oid": 16,
                "type_size": 1,
                "type_modifier": -1,
                "format_code": 0,
            },
            {
                "name": "extversion",
                "type_oid": 25,
                "type_size": -1,
                "type_modifier": -1,
                "format_code": 0,
            },
            {
                "name": "extconfig",
                "type_oid": 1009,
                "type_size": -1,
                "type_modifier": -1,
                "format_code": 0,
            },
            {
                "name": "extcondition",
                "type_oid": 1009,
                "type_size": -1,
                "type_modifier": -1,
                "format_code": 0,
            },
        ]
        return self._build_success_response([], columns)

    async def _handle_pg_namespace(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        is_simple_pg_namespace = (
            "PG_NAMESPACE" in sql_upper
            and re.search(r"\bFROM\s+PG_NAMESPACE\b", sql_upper)
            and "JOIN" not in sql_upper
            and len(re.findall(r"\bFROM\b", sql_upper)) <= 2
        )

        if not is_simple_pg_namespace:
            return None

        logger.debug("Matched PG_NAMESPACE block")
        logger.info(
            "Intercepting SIMPLE pg_namespace query",
            sql_preview=sql[:150],
            session_id=session_id,
        )

        emulator = PgNamespaceEmulator()
        columns = emulator.get_column_definitions()
        rows = emulator.get_all_as_rows()

        rows = self._filter_namespace_rows(rows, params)
        projected = self._project_namespace_columns(sql, columns, rows)
        if projected:
            return projected

        return self._build_success_response(rows, columns)

    async def _handle_pg_class(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        is_simple_pg_class = (
            "PG_CLASS" in sql_upper
            and "PG_ATTRIBUTE" not in sql_upper
            and "ATT.ATTTYPID" not in sql_upper
            and "INFO.COLUMN_NAME" not in sql_upper
        )

        if not is_simple_pg_class:
            return None

        logger.debug("Matched PG_CLASS block")
        logger.info(
            "Intercepting pg_class query",
            sql_preview=sql[:200],
            session_id=session_id,
        )
        if not executor:
            logger.debug("pg_class matched but no executor available")
            emulator = PgClassEmulator(self.oid_gen)
            return self._empty_emulator_response(emulator)

        return await self._build_pg_class_response(params, executor, session_id)

    async def _handle_information_schema_columns(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        if not self._matches_prisma_column_info(sql, sql_upper):
            return None

        logger.debug("Matched Prisma column info block")
        logger.info(
            "Intercepting Prisma column info query",
            sql_preview=sql[:200],
            session_id=session_id,
        )
        if not executor:
            logger.debug("Prisma column info matched but no executor available")
            emulator = PgAttributeEmulator(self.oid_gen)
            return self._empty_emulator_response(emulator)

        return await self._build_prisma_column_info_response(executor, session_id)

    async def _handle_pg_attribute(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        if not (
            "PG_ATTRIBUTE" in sql_upper or "ATT.ATTNAME" in sql_upper or "ATT.ATTTYPID" in sql_upper
        ):
            return None

        logger.debug("Matched PG_ATTRIBUTE block")
        logger.info("Intercepting pg_attribute query", sql_preview=sql[:150], session_id=session_id)
        emulator = PgAttributeEmulator(self.oid_gen)
        return self._empty_emulator_response(emulator)

    async def _handle_pg_constraint(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        if not self._matches_pg_constraint(sql_upper):
            return None

        logger.debug("Matched PG_CONSTRAINT block")
        logger.info(
            "Intercepting pg_constraint query", sql_preview=sql[:200], session_id=session_id
        )
        emulator = PgConstraintEmulator(self.oid_gen)

        if self._is_check_constraint_query(sql_upper):
            return self._empty_emulator_response(emulator)

        if not executor:
            return self._empty_emulator_response(emulator)

        return await self._build_pg_constraint_rows(executor, emulator, session_id)

    async def _handle_pg_index(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        if "PG_INDEX" not in sql_upper:
            return None

        logger.debug("Matched PG_INDEX block")
        logger.info("Intercepting pg_index query", sql_preview=sql[:150], session_id=session_id)
        emulator = PgIndexEmulator(self.oid_gen)
        return self._empty_emulator_response(emulator)

    async def _handle_pg_attrdef(
        self,
        sql: str,
        sql_upper: str,
        params: list | tuple | None,
        session_id: str | None,
        executor,
    ) -> dict[str, Any] | None:
        if "PG_ATTRDEF" not in sql_upper:
            return None

        logger.debug("Matched PG_ATTRDEF block")
        logger.info("Intercepting pg_attrdef query", sql_preview=sql[:150], session_id=session_id)
        emulator = PgAttrdefEmulator(self.oid_gen)
        return self._empty_emulator_response(emulator)

    def _build_success_response(
        self, rows: list[tuple[Any, ...]], columns: list[dict[str, Any]]
    ) -> dict[str, Any]:
        row_count = len(rows)
        return {
            "success": True,
            "rows": rows,
            "columns": columns,
            "row_count": row_count,
            "command": "SELECT",
            "command_tag": f"SELECT {row_count}",
        }

    def _empty_emulator_response(self, emulator) -> dict[str, Any]:
        columns = emulator.get_column_definitions()
        return self._build_success_response([], columns)

    def _build_pg_enum_columns(self, sql: str) -> list[dict[str, Any]]:
        columns: list[dict[str, Any]] = []
        pattern = re.compile(r"(?:[\w\.]+(?:\([^)]*\))?)\s+AS\s+(\w+)", re.IGNORECASE)
        aliases = pattern.findall(sql)

        if aliases:
            for alias in aliases:
                columns.append(
                    {
                        "name": alias,
                        "type_oid": 25,
                        "type_size": -1,
                        "type_modifier": -1,
                        "format_code": 0,
                    }
                )

        if not columns:
            columns = [
                {
                    "name": "oid",
                    "type_oid": 26,
                    "type_size": 4,
                    "type_modifier": -1,
                    "format_code": 0,
                },
                {
                    "name": "enumlabel",
                    "type_oid": 19,
                    "type_size": 64,
                    "type_modifier": -1,
                    "format_code": 0,
                },
            ]

        return columns

    def _filter_pg_type_rows_by_name(self, sql: str, rows: list[list[Any]]) -> list[list[Any]]:
        name_match = re.search(r"typname\s*=\s*'([^']+)'", sql, re.IGNORECASE)
        if not name_match:
            return rows

        target_name = name_match.group(1).lower()
        return [row for row in rows if row[1] == target_name]

    def _filter_pg_type_rows_by_namespace(
        self, rows: list[list[Any]], params: list | tuple | None
    ) -> list[list[Any]]:
        if not params or len(params) == 0 or params[0] is None:
            return rows

        requested_namespaces = [n.lower() for n in self._extract_filter_names(params[0])]
        if "pg_catalog" not in requested_namespaces:
            return []

        return rows

    def _project_pg_type_columns(
        self, sql: str, columns: list[dict[str, Any]], rows: list[list[Any]]
    ) -> tuple[list[dict[str, Any]], list[list[Any]]]:
        select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
        if not select_match:
            return columns, rows

        clause = select_match.group(1).lower()
        available = [c["name"] for c in columns]
        indices: list[int] = []
        select_columns: list[dict[str, Any]] = []
        for idx, col_name in enumerate(available):
            if col_name in clause:
                indices.append(idx)
                select_columns.append(columns[idx])

        if not indices:
            return columns, rows

        projected_rows = [[row[i] for i in indices] for row in rows]
        return select_columns, projected_rows

    def _filter_namespace_rows(
        self, rows: list[tuple[Any, ...]], params: list | tuple | None
    ) -> list[tuple[Any, ...]]:
        if not params or len(params) == 0 or params[0] is None:
            return rows

        filter_names = [name.lower() for name in self._extract_filter_names(params[0]) if name]
        if not filter_names:
            return rows

        return [row for row in rows if row[1].lower() in filter_names]

    def _project_namespace_columns(
        self, sql: str, columns: list[dict[str, Any]], rows: list[tuple[Any, ...]]
    ) -> dict[str, Any] | None:
        select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
        if not select_match:
            return None

        select_clause = select_match.group(1).lower()
        has_nspname = "nspname" in select_clause or "namespace_name" in select_clause
        has_oid = "oid" in select_clause and "nspname" not in select_clause.split("oid")[0][-5:]
        if not (has_nspname and not has_oid):
            return None

        result_column = columns[1].copy()
        if "namespace_name" in select_clause:
            result_column["name"] = "namespace_name"

        result_rows = [(row[1],) for row in rows]
        return self._build_success_response(result_rows, [result_column])

    def _matches_pg_constraint(self, sql_upper: str) -> bool:
        return "PG_CONSTRAINT" in sql_upper or "CONSTR.CONNAME" in sql_upper

    def _is_check_constraint_query(self, sql_upper: str) -> bool:
        return (
            "NOT IN" in sql_upper
            and ("'P'" in sql_upper or "'U'" in sql_upper or "'F'" in sql_upper)
            and "CONTYPE" in sql_upper
        )

    async def _build_pg_constraint_rows(
        self, executor, emulator: PgConstraintEmulator, session_id: str | None
    ) -> dict[str, Any]:
        constraints_sql = (
            "SELECT\n"
            "    'public' AS namespace,\n"
            "    TABLE_NAME,\n"
            "    CONSTRAINT_NAME,\n"
            "    CONSTRAINT_TYPE\n"
            "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS\n"
            f"WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}'\n"
            "ORDER BY TABLE_NAME, CONSTRAINT_NAME\n"
        )

        try:
            iris_result = await executor.execute_query(constraints_sql, session_id=session_id)
            if iris_result.get("success"):
                iris_constraints = iris_result.get("rows", [])
                type_map = {
                    "PRIMARY KEY": "p",
                    "UNIQUE": "u",
                    "FOREIGN KEY": "f",
                    "CHECK": "c",
                }
                rows: list[tuple[Any, ...]] = []
                for constraint in iris_constraints:
                    namespace = constraint[0]
                    table_name = constraint[1].lower()
                    constraint_name = constraint[2].lower()
                    iris_type = constraint[3]
                    pg_type = type_map.get(iris_type, "c")

                    col_sql = (
                        "SELECT COLUMN_NAME\n"
                        "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE\n"
                        f"WHERE CONSTRAINT_NAME = '{constraint[2]}'\n"
                        "ORDER BY ORDINAL_POSITION\n"
                    )
                    col_result = await executor.execute_query(col_sql, session_id=session_id)
                    col_names = [r[0].lower() for r in col_result.get("rows", [])]

                    definition = ""
                    if pg_type == "p":
                        definition = f"PRIMARY KEY ({', '.join(col_names)})"
                    elif pg_type == "u":
                        definition = f"UNIQUE ({', '.join(col_names)})"

                    col_names_str = "{" + ",".join(col_names) + "}"
                    rows.append(
                        (
                            namespace,
                            table_name,
                            constraint_name,
                            pg_type,
                            definition,
                            col_names_str,
                        )
                    )

                custom_columns = [
                    {"name": "namespace", "type_oid": 19},
                    {"name": "table_name", "type_oid": 19},
                    {"name": "constraint_name", "type_oid": 19},
                    {"name": "constraint_type", "type_oid": 18},
                    {"name": "constraint_definition", "type_oid": 25},
                    {"name": "column_names", "type_oid": 1009},
                ]
                for col in custom_columns:
                    col.update({"type_size": -1, "type_modifier": -1, "format_code": 0})

                return self._build_success_response(rows, custom_columns)
        except Exception as e:
            logger.error(f"pg_constraint query failed: {e}")

        return self._empty_emulator_response(emulator)

    def _namespace_filters(self, params: list | tuple | None) -> list[str]:
        target_namespaces = ["public"]
        if params and len(params) > 0 and params[0] is not None:
            target_namespaces = [name.lower() for name in self._extract_filter_names(params[0])]
        return target_namespaces

    async def _build_pg_class_response(
        self, params: list | tuple | None, executor, session_id: str | None
    ) -> dict[str, Any]:
        emulator = PgClassEmulator(self.oid_gen)
        tables_sql = (
            "SELECT TABLE_NAME, TABLE_TYPE, TABLE_SCHEMA\n"
            "FROM INFORMATION_SCHEMA.TABLES\n"
            "WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')\n"
            "ORDER BY TABLE_SCHEMA, TABLE_NAME\n"
        )
        try:
            iris_result = await executor.execute_query(tables_sql, session_id=session_id)
            if not iris_result.get("success"):
                raise RuntimeError(f"Failed to fetch tables: {iris_result.get('error')}")

            iris_tables = iris_result.get("rows", [])
            schema_mapping = {
                IRIS_SCHEMA.lower(): "public",
                IRIS_SCHEMA: "public",
                "%Library": "pg_catalog",
                "INFORMATION_SCHEMA": "information_schema",
            }

            target_namespaces = self._namespace_filters(params)
            for table_name, table_type, table_schema in iris_tables:
                pg_namespace = schema_mapping.get(table_schema, table_schema.lower())
                if pg_namespace not in target_namespaces:
                    continue

                pg_class = emulator.from_iris_table(table_name, table_type, schema=table_schema)
                if pg_namespace == "pg_catalog":
                    pg_class.relnamespace = 11
                elif pg_namespace == "information_schema":
                    pg_class.relnamespace = 11323

                emulator.add_table(pg_class)

            return self._build_success_response(
                emulator.get_all_as_rows(), emulator.get_column_definitions()
            )
        except Exception as exc:
            logger.error(f"pg_class interception failed: {exc}")
            return self._empty_emulator_response(emulator)

    def _matches_prisma_column_info(self, sql: str, sql_upper: str) -> bool:
        return (
            "information_schema.columns" in sql.lower()
            and "INFO.TABLE_NAME" in sql_upper
            and "INFO.COLUMN_NAME" in sql_upper
            and "FORMAT_TYPE" in sql_upper
        )

    async def _build_prisma_column_info_response(
        self, executor, session_id: str | None
    ) -> dict[str, Any]:
        columns_sql = (
            "SELECT\n"
            "    'public' AS namespace,\n"
            "    TABLE_NAME,\n"
            "    COLUMN_NAME,\n"
            "    DATA_TYPE,\n"
            "    COALESCE(NUMERIC_PRECISION, 0) AS numeric_precision,\n"
            "    COALESCE(NUMERIC_SCALE, 0) AS numeric_scale,\n"
            "    COALESCE(CHARACTER_MAXIMUM_LENGTH, 0) AS max_length,\n"
            "    IS_NULLABLE,\n"
            "    COLUMN_DEFAULT,\n"
            "    ORDINAL_POSITION\n"
            "FROM INFORMATION_SCHEMA.COLUMNS\n"
            f"WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}'\n"
            "ORDER BY TABLE_NAME, ORDINAL_POSITION\n"
        )
        try:
            iris_result = await executor.execute_query(columns_sql, session_id=session_id)
            if not iris_result.get("success"):
                raise RuntimeError(f"Failed to fetch columns: {iris_result.get('error')}")

            iris_columns = iris_result.get("rows", [])
            response_columns = [
                {"name": "namespace", "type_oid": 19},
                {"name": "table_name", "type_oid": 19},
                {"name": "column_name", "type_oid": 19},
                {"name": "data_type", "type_oid": 25},
                {"name": "full_data_type", "type_oid": 25},
                {"name": "formatted_type", "type_oid": 25},
                {"name": "udt_name", "type_oid": 19},
                {"name": "numeric_precision", "type_oid": 23},
                {"name": "numeric_scale", "type_oid": 23},
                {"name": "character_maximum_length", "type_oid": 23},
                {"name": "is_nullable", "type_oid": 25},
                {"name": "column_default", "type_oid": 25},
                {"name": "ordinal_position", "type_oid": 23},
                {"name": "is_identity", "type_oid": 25},
                {"name": "is_generated", "type_oid": 25},
            ]
            for col in response_columns:
                col.update({"type_size": -1, "type_modifier": -1, "format_code": 0})

            rows: list[tuple[Any, ...]] = []
            for col in iris_columns:
                namespace = col[0]
                table_name = col[1].lower()
                column_name = col[2].lower()
                iris_data_type = col[3].upper() if col[3] else "VARCHAR"
                numeric_precision = int(col[4]) if col[4] and str(col[4]).isdigit() else 0
                numeric_scale = int(col[5]) if col[5] and str(col[5]).isdigit() else 0
                max_length = int(col[6]) if col[6] and str(col[6]).isdigit() else 0
                is_nullable = "YES" if col[7] == "YES" else "NO"
                column_default = col[8]
                ordinal_position = int(col[9]) if col[9] and str(col[9]).isdigit() else 0

                base_type = iris_data_type.split("(")[0]
                pg_type_name, udt_name, _type_oid = get_type_mapping(base_type)

                if max_length > 0 and pg_type_name in ("character varying", "character"):
                    formatted_type = f"{pg_type_name}({max_length})"
                elif numeric_precision > 0 and pg_type_name == "numeric":
                    formatted_type = f"numeric({numeric_precision},{numeric_scale})"
                else:
                    formatted_type = pg_type_name

                clean_default = None
                if column_default:
                    default_upper = str(column_default).upper()
                    if (
                        "AUTOINCREMENT" not in default_upper
                        and "ROWVERSION" not in default_upper
                        and default_upper not in ("NULL", "")
                    ):
                        clean_default = column_default
                is_identity = (
                    "YES"
                    if column_default and "AUTOINCREMENT" in str(column_default).upper()
                    else "NO"
                )

                rows.append(
                    (
                        namespace,
                        table_name,
                        column_name,
                        pg_type_name,
                        formatted_type,
                        formatted_type,
                        udt_name,
                        numeric_precision,
                        numeric_scale,
                        max_length,
                        is_nullable,
                        clean_default,
                        ordinal_position,
                        is_identity,
                        "NEVER",
                    )
                )

            return self._build_success_response(rows, response_columns)
        except Exception as exc:
            logger.error(f"Prisma column info query failed: {exc}")
            emulator = PgAttributeEmulator(self.oid_gen)
            return self._empty_emulator_response(emulator)

    def _extract_filter_names(self, param: Any) -> list[str]:
        """Utility to extract filter names from various parameter formats."""
        filter_names = []
        if isinstance(param, list):
            filter_names = param
        elif isinstance(param, str):
            try:
                parsed = json.loads(param)
                if isinstance(parsed, list):
                    filter_names = parsed
                else:
                    filter_names = [str(parsed)]
            except json.JSONDecodeError:
                if param.startswith("{") and param.endswith("}"):
                    inner = param[1:-1]
                    if inner:
                        filter_names = [s.strip().strip('"') for s in inner.split(",")]
                elif param.startswith("[") and param.endswith("]"):
                    inner = param[1:-1].strip()
                    if inner:
                        filter_names = [s.strip().strip('"').strip("'") for s in inner.split(",")]
                elif param == "[]" or param == "{}":
                    filter_names = []
                else:
                    filter_names = [param]
        else:
            filter_names = [str(param)]
        return filter_names
