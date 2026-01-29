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
        print(f"DEBUG: CatalogRouter.handle_catalog_query received: {sql[:100]!r}", flush=True)
        sql_upper = sql.upper()
        logger.debug(f"CatalogRouter.handle_catalog_query: sql={sql}, sql_upper={sql_upper}")

        # pg_enum - Return empty with column metadata (no enums defined)
        if "PG_ENUM" in sql_upper:
            logger.debug("Matched PG_ENUM block")
            logger.info(
                "Intercepting pg_enum query (returning empty with column metadata)",
                sql_preview=sql[:100],
                session_id=session_id,
            )
            columns = []
            as_pattern = re.compile(r"(?:[\w\.]+(?:\([^)]*\))?)\s+AS\s+(\w+)", re.IGNORECASE)
            aliases = as_pattern.findall(sql)

            if aliases:
                for alias in aliases:
                    columns.append(
                        {
                            "name": alias,
                            "type_oid": 25,  # text type
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

            return {
                "success": True,
                "rows": [],
                "columns": columns,
                "row_count": 0,
                "command": "SELECT",
                "command_tag": "SELECT 0",
            }

        # pg_type - Use PgTypeEmulator (Moved up and simplified as requested)
        if "PG_TYPE" in sql_upper:
            logger.debug("Matched PG_TYPE block")
            logger.info("Intercepting pg_type query", sql_preview=sql[:150], session_id=session_id)
            emulator = PgTypeEmulator(self.oid_gen)
            columns = emulator.get_column_definitions()
            all_rows = emulator.get_all_as_rows()

            # Handle filtering by typname if present in SQL
            rows = all_rows
            name_match = re.search(r"typname\s*=\s*'([^']+)'", sql, re.IGNORECASE)
            if name_match:
                target_name = name_match.group(1).lower()
                rows = [r for r in all_rows if r[1] == target_name]

            # Handle column selection filtering logic from IRISExecutor
            requested_namespaces = None
            if params and len(params) > 0 and params[0] is not None:
                requested_namespaces = self._extract_filter_names(params[0])
                requested_namespaces = [n.lower() for n in requested_namespaces]

            include_types = True
            if requested_namespaces is not None and "pg_catalog" not in requested_namespaces:
                include_types = False

            if not include_types:
                rows = []

            # Handle SELECT clause filtering (subset of columns)
            select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
            if select_match:
                select_clause = select_match.group(1).lower()
                # Basic column filtering for pg_type
                avail_cols = [c["name"] for c in columns]
                requested_indices = []
                final_columns = []
                for i, col_name in enumerate(avail_cols):
                    if col_name in select_clause:
                        requested_indices.append(i)
                        final_columns.append(columns[i])

                if requested_indices:
                    rows = [[row[i] for i in requested_indices] for row in rows]
                    columns = final_columns

            return {
                "success": True,
                "rows": [tuple(r) for r in rows],
                "columns": columns,
                "row_count": len(rows),
                "command": "SELECT",
                "command_tag": f"SELECT {len(rows)}",
            }

        # pg_extension - Return empty results with standard columns
        if "PG_EXTENSION" in sql_upper:
            logger.debug("Matched PG_EXTENSION block")
            logger.info(
                "Intercepting pg_extension query", sql_preview=sql[:100], session_id=session_id
            )
            columns = [
                {
                    "name": "oid",
                    "type_oid": 26,
                    "type_size": 4,
                    "type_modifier": -1,
                    "format_code": 0,
                },
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
            return {
                "success": True,
                "rows": [],
                "columns": columns,
                "row_count": 0,
                "command": "SELECT",
                "command_tag": "SELECT 0",
            }

        # pg_namespace - Use PgNamespaceEmulator
        is_simple_pg_namespace = (
            "PG_NAMESPACE" in sql_upper
            and re.search(r"\bFROM\s+PG_NAMESPACE\b", sql_upper)
            and "JOIN" not in sql_upper
            and len(re.findall(r"\bFROM\b", sql_upper)) <= 2
        )

        if is_simple_pg_namespace:
            logger.debug("Matched PG_NAMESPACE block")
            logger.info(
                "Intercepting SIMPLE pg_namespace query",
                sql_preview=sql[:150],
                session_id=session_id,
            )
            emulator = PgNamespaceEmulator()
            columns = emulator.get_column_definitions()
            all_rows = emulator.get_all_as_rows()

            # Handle filtering by nspname if present in params
            filtered_rows = all_rows
            if params and len(params) > 0 and params[0] is not None:
                filter_names = self._extract_filter_names(params[0])
                if filter_names:
                    filter_names_lower = [n.lower() for n in filter_names if n]
                    filtered_rows = [
                        row for row in all_rows if row[1].lower() in filter_names_lower
                    ]

            # Handle column selection
            select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
            if select_match:
                select_clause = select_match.group(1).lower()
                has_nspname = "nspname" in select_clause or "namespace_name" in select_clause
                has_oid = (
                    "oid" in select_clause and "nspname" not in select_clause.split("oid")[0][-5:]
                )
                if has_nspname and not has_oid:
                    result_columns = [columns[1]]  # nspname
                    if "namespace_name" in select_clause:
                        result_columns[0] = result_columns[0].copy()
                        result_columns[0]["name"] = "namespace_name"
                    rows = [(row[1],) for row in filtered_rows]
                else:
                    result_columns = columns
                    rows = filtered_rows
            else:
                result_columns = columns
                rows = filtered_rows

            return {
                "success": True,
                "rows": rows,
                "columns": result_columns,
                "row_count": len(rows),
                "command": "SELECT",
                "command_tag": f"SELECT {len(rows)}",
            }

        # pg_class - Use PgClassEmulator
        is_simple_pg_class = (
            "PG_CLASS" in sql_upper
            and "PG_ATTRIBUTE" not in sql_upper
            and "ATT.ATTTYPID" not in sql_upper
            and "INFO.COLUMN_NAME" not in sql_upper
        )

        if is_simple_pg_class:
            logger.debug("Matched PG_CLASS block")
            if executor:
                logger.info(
                    "Intercepting pg_class query", sql_preview=sql[:200], session_id=session_id
                )
                try:
                    tables_sql = """
                        SELECT TABLE_NAME, TABLE_TYPE, TABLE_SCHEMA
                        FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                        ORDER BY TABLE_SCHEMA, TABLE_NAME
                    """
                    # Use executor to fetch real tables from IRIS
                    iris_result = await executor.execute_query(tables_sql, session_id=session_id)
                    if not iris_result.get("success"):
                        raise RuntimeError(f"Failed to fetch tables: {iris_result.get('error')}")

                    iris_tables = iris_result.get("rows", [])

                    emulator = PgClassEmulator(self.oid_gen)
                    schema_mapping = {
                        IRIS_SCHEMA.lower(): "public",
                        IRIS_SCHEMA: "public",
                        "%Library": "pg_catalog",
                        "INFORMATION_SCHEMA": "information_schema",
                    }

                    # Handle namespace filtering
                    target_namespaces = ["public"]
                    if params and len(params) > 0 and params[0] is not None:
                        target_namespaces = self._extract_filter_names(params[0])
                        target_namespaces = [n.lower() for n in target_namespaces]

                    for table_name, table_type, table_schema in iris_tables:
                        pg_namespace = schema_mapping.get(table_schema, table_schema.lower())
                        if pg_namespace in target_namespaces:
                            pg_class = emulator.from_iris_table(
                                table_name, table_type, schema=table_schema
                            )
                            # Patch namespace OID if needed (emulator uses 'public' OID by default)
                            if pg_namespace == "pg_catalog":
                                pg_class.relnamespace = 11
                            elif pg_namespace == "information_schema":
                                pg_class.relnamespace = 11323

                            emulator.add_table(pg_class)

                    return {
                        "success": True,
                        "rows": emulator.get_all_as_rows(),
                        "columns": emulator.get_column_definitions(),
                        "row_count": len(emulator.get_all()),
                        "command": "SELECT",
                        "command_tag": f"SELECT {len(emulator.get_all())}",
                    }
                except Exception as e:
                    logger.error(f"pg_class interception failed: {e}")
            else:
                # Fallback if no executor
                logger.debug("pg_class matched but no executor available")
                emulator = PgClassEmulator(self.oid_gen)
                return {
                    "success": True,
                    "rows": [],
                    "columns": emulator.get_column_definitions(),
                    "row_count": 0,
                    "command": "SELECT",
                    "command_tag": "SELECT 0",
                }

        # Prisma column info query - Use PgAttributeEmulator
        if (
            "INFO.TABLE_NAME" in sql_upper
            and "INFO.COLUMN_NAME" in sql_upper
            and "FORMAT_TYPE" in sql_upper
        ):
            logger.debug("Matched Prisma column info block")
            if executor:
                logger.info(
                    "Intercepting Prisma column info query",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )
                try:
                    columns_sql = f"""
                        SELECT
                            'public' AS namespace,
                            TABLE_NAME,
                            COLUMN_NAME,
                            DATA_TYPE,
                            COALESCE(NUMERIC_PRECISION, 0) AS numeric_precision,
                            COALESCE(NUMERIC_SCALE, 0) AS numeric_scale,
                            COALESCE(CHARACTER_MAXIMUM_LENGTH, 0) AS max_length,
                            IS_NULLABLE,
                            COLUMN_DEFAULT,
                            ORDINAL_POSITION
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}'
                        ORDER BY TABLE_NAME, ORDINAL_POSITION
                    """
                    iris_result = await executor.execute_query(columns_sql, session_id=session_id)
                    if not iris_result.get("success"):
                        raise RuntimeError(f"Failed to fetch columns: {iris_result.get('error')}")

                    iris_columns = iris_result.get("rows", [])

                    # We need to return a very specific format for Prisma
                    # Instead of using emulator directly, we follow IRISExecutor's custom logic
                    # which Prisma expects.
                    from iris_pgwire.type_mapping import get_type_mapping

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
                    # Ensure they have all required keys for PostgreSQL protocol
                    for col in response_columns:
                        col.update({"type_size": -1, "type_modifier": -1, "format_code": 0})

                    rows = []
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

                        data_type = pg_type_name
                        full_data_type = formatted_type
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
                                data_type,
                                full_data_type,
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

                    return {
                        "success": True,
                        "rows": rows,
                        "columns": response_columns,
                        "row_count": len(rows),
                        "command": "SELECT",
                        "command_tag": f"SELECT {len(rows)}",
                    }
                except Exception as e:
                    logger.error(f"Prisma column info query failed: {e}")
            else:
                # Fallback if no executor
                logger.debug("Prisma column info matched but no executor available")
                emulator = PgAttributeEmulator(self.oid_gen)
                return {
                    "success": True,
                    "rows": [],
                    "columns": emulator.get_column_definitions(),
                    "row_count": 0,
                    "command": "SELECT",
                    "command_tag": "SELECT 0",
                }

        # pg_attribute - Composite types / general attribute query
        if "PG_ATTRIBUTE" in sql_upper or "ATT.ATTNAME" in sql_upper or "ATT.ATTTYPID" in sql_upper:
            logger.debug("Matched PG_ATTRIBUTE block")
            logger.info(
                "Intercepting pg_attribute query", sql_preview=sql[:150], session_id=session_id
            )
            emulator = PgAttributeEmulator(self.oid_gen)
            return {
                "success": True,
                "rows": [],
                "columns": emulator.get_column_definitions(),
                "row_count": 0,
                "command": "SELECT",
                "command_tag": "SELECT 0",
            }

        # pg_constraint - Use PgConstraintEmulator
        if "PG_CONSTRAINT" in sql_upper or "CONSTR.CONNAME" in sql_upper:
            logger.debug("Matched PG_CONSTRAINT block")
            logger.info(
                "Intercepting pg_constraint query", sql_preview=sql[:200], session_id=session_id
            )
            emulator = PgConstraintEmulator(self.oid_gen)

            # Simple check for certain Prisma queries that expect empty results for now
            is_check_constraint_query = (
                "NOT IN" in sql_upper
                and ("'P'" in sql_upper or "'U'" in sql_upper or "'F'" in sql_upper)
                and "CONTYPE" in sql_upper
            )
            if is_check_constraint_query:
                return {
                    "success": True,
                    "rows": [],
                    "columns": emulator.get_column_definitions(),
                    "row_count": 0,
                    "command": "SELECT",
                    "command_tag": "SELECT 0",
                }

            if executor:
                try:
                    constraints_sql = f"""
                        SELECT
                            'public' AS namespace,
                            TABLE_NAME,
                            CONSTRAINT_NAME,
                            CONSTRAINT_TYPE
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
                        WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}'
                        ORDER BY TABLE_NAME, CONSTRAINT_NAME
                    """
                    iris_result = await executor.execute_query(
                        constraints_sql, session_id=session_id
                    )
                    if iris_result.get("success"):
                        iris_constraints = iris_result.get("rows", [])
                        type_map = {
                            "PRIMARY KEY": "p",
                            "UNIQUE": "u",
                            "FOREIGN KEY": "f",
                            "CHECK": "c",
                        }
                        rows = []
                        for constraint in iris_constraints:
                            namespace = constraint[0]
                            table_name = constraint[1].lower()
                            constraint_name = constraint[2].lower()
                            iris_type = constraint[3]
                            pg_type = type_map.get(iris_type, "c")

                            # Simplified column names retrieval (similar to IRISExecutor)
                            col_sql = f"""
                                SELECT COLUMN_NAME
                                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                                WHERE CONSTRAINT_NAME = '{constraint[2]}'
                                ORDER BY ORDINAL_POSITION
                            """
                            col_result = await executor.execute_query(
                                col_sql, session_id=session_id
                            )
                            col_names = [r[0].lower() for r in col_result.get("rows", [])]

                            # We don't fully populate all PgConstraint fields here to match IRISExecutor's
                            # simplified row format for now, or we could use emulator.
                            # IRISExecutor returned: (namespace, table_name, constraint_name, pg_type, definition, col_names_str)
                            # which doesn't perfectly match PgConstraint columns.

                            # For compatibility with what IRISExecutor was doing:
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

                        # Custom columns to match IRISExecutor's expected output
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

                        return {
                            "success": True,
                            "rows": rows,
                            "columns": custom_columns,
                            "row_count": len(rows),
                            "command": "SELECT",
                            "command_tag": f"SELECT {len(rows)}",
                        }
                except Exception as e:
                    logger.error(f"pg_constraint query failed: {e}")

            return {
                "success": True,
                "rows": [],
                "columns": emulator.get_column_definitions(),
                "row_count": 0,
                "command": "SELECT",
                "command_tag": "SELECT 0",
            }

        # pg_index - Use PgIndexEmulator
        if "PG_INDEX" in sql_upper:
            logger.debug("Matched PG_INDEX block")
            logger.info("Intercepting pg_index query", sql_preview=sql[:150], session_id=session_id)
            emulator = PgIndexEmulator(self.oid_gen)
            return {
                "success": True,
                "rows": [],
                "columns": emulator.get_column_definitions(),
                "row_count": 0,
                "command": "SELECT",
                "command_tag": "SELECT 0",
            }

        # pg_attrdef - Use PgAttrdefEmulator
        if "PG_ATTRDEF" in sql_upper:
            logger.debug("Matched PG_ATTRDEF block")
            logger.info(
                "Intercepting pg_attrdef query", sql_preview=sql[:150], session_id=session_id
            )
            emulator = PgAttrdefEmulator(self.oid_gen)
            return {
                "success": True,
                "rows": [],
                "columns": emulator.get_column_definitions(),
                "row_count": 0,
                "command": "SELECT",
                "command_tag": "SELECT 0",
            }

        # Default fallback for other catalog tables (empty)
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
