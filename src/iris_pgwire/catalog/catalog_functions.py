"""
PostgreSQL Catalog Function Emulation

Implements native IRIS SQL functions that emulate PostgreSQL's system catalog functions.
These functions enable transparent introspection by ORMs like Drizzle, Prisma, SQLAlchemy,
and any PostgreSQL-compatible client without ORM-specific query detection workarounds.

Implemented functions:
- format_type(type_oid, typmod) → type name string
- pg_get_constraintdef(constraint_oid, pretty?) → constraint SQL
- pg_get_serial_sequence(table, column) → sequence name or NULL
- pg_get_viewdef(view_oid, pretty?) → view SQL or NULL (intentionally limited)
- pg_get_indexdef(index_oid, column?, pretty?) → index DDL

References:
- Feature 033: Generic PostgreSQL Catalog Functions
- contracts/catalog_functions_api.md
- contracts/format_type_contract.md
- contracts/constraint_def_contract.md
"""

import time
from dataclasses import dataclass
from typing import Any

import structlog

from ..type_mapping import TypeModifier, get_type_by_oid
from iris_pgwire.schema_mapper import IRIS_SCHEMA
from .oid_generator import OIDGenerator

logger = structlog.get_logger()


@dataclass
class CatalogFunctionResult:
    """Result from a catalog function call."""

    function_name: str
    arguments: list[Any]
    result: str | None  # NULL for non-existent objects
    error: str | None = None


class CatalogFunctionHandler:
    """
    Handler for PostgreSQL catalog function emulation.

    Integrates with Feature 031 catalog infrastructure (OIDGenerator, pg_constraint,
    pg_index) and queries IRIS INFORMATION_SCHEMA for metadata.
    """

    def __init__(self, oid_generator: OIDGenerator, executor):
        """
        Initialize catalog function handler.

        Args:
            oid_generator: OIDGenerator from Feature 031
            executor: IRISExecutor instance for querying INFORMATION_SCHEMA
        """
        self.oid_gen = oid_generator
        self.executor = executor
        self._oid_cache: dict[int, dict[str, Any]] = {}

    # ========================================================================
    # T007: format_type(type_oid, typmod)
    # ========================================================================

    def format_type(self, type_oid: int, typmod: int) -> str | None:
        """
        Convert type OID and modifier to human-readable type name.

        Implements PostgreSQL format_type() function per contracts/format_type_contract.md

        Args:
            type_oid: PostgreSQL type OID from pg_type.oid
            typmod: Type modifier (-1 for no modifier)

        Returns:
            Formatted type name, or None for unknown OIDs

        Examples:
            format_type(23, -1) → "integer"
            format_type(1043, 259) → "character varying(255)"
            format_type(1700, 655366) → "numeric(10,2)"
            format_type(99999, -1) → None
        """
        # Lookup type by OID
        type_info = get_type_by_oid(type_oid)
        if not type_info:
            logger.debug("Unknown type OID", type_oid=type_oid)
            return None

        pg_data_type, pg_udt_name = type_info

        # Apply type modifier for parameterized types
        if typmod > 0:
            # Character types: varchar(n), char(n)
            if type_oid in (1042, 1043):  # char, varchar
                length = TypeModifier.decode_char_length(typmod)
                if length is not None:
                    return f"{pg_data_type}({length})"

            # Numeric type: numeric(p,s)
            elif type_oid == 1700:  # numeric
                precision_scale = TypeModifier.decode_numeric_precision(typmod)
                if precision_scale:
                    precision, scale = precision_scale
                    return f"numeric({precision},{scale})"

            # Timestamp/Time types: timestamp(p), time(p)
            elif type_oid in (1083, 1114, 1184, 1266):  # time, timestamp variants
                precision = TypeModifier.decode_timestamp_precision(typmod)
                if precision is not None:
                    # Format: timestamp(p) without time zone, time(p) with time zone, etc.
                    if type_oid == 1083:  # time without time zone
                        return f"time({precision}) without time zone"
                    elif type_oid == 1114:  # timestamp without time zone
                        return f"timestamp({precision}) without time zone"
                    elif type_oid == 1184:  # timestamp with time zone
                        return f"timestamp({precision}) with time zone"
                    elif type_oid == 1266:  # time with time zone
                        return f"time({precision}) with time zone"

            # Bit types: bit(n), bit varying(n)
            elif type_oid in (1560, 1562):  # bit, bit varying
                length = TypeModifier.decode_bit_length(typmod)
                if length is not None:
                    return f"{pg_data_type}({length})"

        # Return base type name
        return pg_data_type

    # ========================================================================
    # T008: pg_get_constraintdef(constraint_oid, pretty?)
    # ========================================================================

    def pg_get_constraintdef(self, constraint_oid: int, pretty: bool = False) -> str | None:
        """
        Get constraint definition as SQL text.

        Implements PostgreSQL pg_get_constraintdef() per contracts/constraint_def_contract.md

        Args:
            constraint_oid: Constraint OID from pg_constraint.oid
            pretty: Format with newlines (currently ignored)

        Returns:
            Constraint definition string, or None for non-existent constraints

        Examples:
            pg_get_constraintdef(pk_oid) → "PRIMARY KEY (id)"
            pg_get_constraintdef(fk_oid) → "FOREIGN KEY (author_id) REFERENCES users(id)"
            pg_get_constraintdef(uq_oid) → "UNIQUE (email)"
            pg_get_constraintdef(99999) → None
        """
        # Query INFORMATION_SCHEMA for constraint metadata
        constraint_info = self._get_constraint_metadata(constraint_oid)
        if not constraint_info:
            logger.debug("Constraint not found", constraint_oid=constraint_oid)
            return None

        constraint_type = constraint_info["constraint_type"]
        constraint_name = constraint_info["constraint_name"]
        schema = constraint_info["constraint_schema"]

        # Get constrained columns (may be empty for CHECK constraints)
        columns = self._get_constraint_columns(schema, constraint_name)

        # Format by constraint type
        if constraint_type == "CHECK":
            # CHECK constraints may not have columns in KEY_COLUMN_USAGE
            # Return placeholder per plan.md
            logger.debug("CHECK constraint format - placeholder", constraint_name=constraint_name)
            return "CHECK ((expression))"

        if not columns:
            logger.warning("No columns found for constraint", constraint_name=constraint_name)
            return None

        column_list = ", ".join(columns)

        if constraint_type == "PRIMARY KEY":
            return f"PRIMARY KEY ({column_list})"

        elif constraint_type == "UNIQUE":
            return f"UNIQUE ({column_list})"

        elif constraint_type == "FOREIGN KEY":
            # Get referenced table and columns
            ref_info = self._get_fk_references(schema, constraint_name)
            if not ref_info:
                logger.warning("FK reference info not found", constraint_name=constraint_name)
                return None

            ref_table = ref_info["ref_table"]
            ref_columns = ref_info["ref_columns"]
            update_rule = ref_info["update_rule"]
            delete_rule = ref_info["delete_rule"]

            ref_column_list = ", ".join(ref_columns)
            fk_def = f"FOREIGN KEY ({column_list}) REFERENCES {ref_table}({ref_column_list})"

            # Add action clauses (only if not NO ACTION)
            if update_rule and update_rule != "NO ACTION":
                fk_def += f" ON UPDATE {update_rule}"
            if delete_rule and delete_rule != "NO ACTION":
                fk_def += f" ON DELETE {delete_rule}"

            return fk_def

        return None

    # ========================================================================
    # T009: pg_get_serial_sequence(table, column)
    # ========================================================================

    def pg_get_serial_sequence(self, table: str, column: str) -> str | None:
        """
        Get sequence name for a SERIAL/IDENTITY column.

        Implements PostgreSQL pg_get_serial_sequence() per contracts/catalog_functions_api.md

        Args:
            table: Table name (may include schema prefix "schema.table")
            column: Column name

        Returns:
            Fully qualified sequence name (e.g., "public.users_id_seq"), or None

        Examples:
            pg_get_serial_sequence('users', 'id') → "public.users_id_seq" (if serial)
            pg_get_serial_sequence('users', 'name') → None
            pg_get_serial_sequence('public.posts', 'id') → "public.posts_id_seq"
        """
        # Parse schema.table if provided
        if "." in table:
            schema, table_name = table.split(".", 1)
        else:
            schema = IRIS_SCHEMA  # Default IRIS schema
            table_name = table

        # Query IRIS INFORMATION_SCHEMA.COLUMNS for auto-increment
        query = f"""
            SELECT COLUMN_DEFAULT, IS_IDENTITY
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{schema}'
              AND TABLE_NAME = '{table_name}'
              AND COLUMN_NAME = '{column}'
        """

        try:
            result = self.executor._execute_iris_query(query)
            if not result or not result.get("rows"):
                return None

            row = result["rows"][0]
            column_default = row[0]
            is_identity = row[1] if len(row) > 1 else None

            # Check for auto-increment indicators
            if is_identity == "YES" or (
                column_default and "IDENTITY" in str(column_default).upper()
            ):
                # PostgreSQL convention: table_column_seq
                sequence_name = f"{table_name}_{column}_seq"
                return f"public.{sequence_name}"

            return None

        except Exception as e:
            logger.warning(
                "Error checking serial sequence", table=table, column=column, error=str(e)
            )
            return None

    # ========================================================================
    # T010: pg_get_indexdef(index_oid, column?, pretty?)
    # ========================================================================

    def pg_get_indexdef(self, index_oid: int, column: int = 0, pretty: bool = False) -> str | None:
        """
        Get CREATE INDEX statement for an index.

        Implements PostgreSQL pg_get_indexdef() per contracts/catalog_functions_api.md

        Args:
            index_oid: Index OID from pg_index.indexrelid
            column: Column number (0 for full definition, >0 for single column name)
            pretty: Format with indentation (currently ignored)

        Returns:
            CREATE INDEX statement or column name, or None

        Examples:
            pg_get_indexdef(oid, 0) → "CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)"
            pg_get_indexdef(oid, 1) → "id"
            pg_get_indexdef(99999, 0) → None
        """
        # Query index metadata from pg_index/pg_class emulation
        index_info = self._get_index_metadata(index_oid)
        if not index_info:
            logger.debug("Index not found", index_oid=index_oid)
            return None

        # If column > 0, return column name
        if column > 0:
            index_columns = index_info.get("index_columns", [])
            if column <= len(index_columns):
                return index_columns[column - 1]
            return None

        # Build CREATE INDEX statement
        index_name = index_info["index_name"]
        table_name = index_info["table_name"]
        is_unique = index_info.get("is_unique", False)
        index_columns = index_info.get("index_columns", [])

        unique_clause = "UNIQUE " if is_unique else ""
        column_list = ", ".join(index_columns)

        return f"CREATE {unique_clause}INDEX {index_name} ON public.{table_name} USING btree ({column_list})"

    # ========================================================================
    # T011: pg_get_viewdef(view_oid, pretty?)
    # ========================================================================

    def pg_get_viewdef(self, view_oid: int, pretty: bool = False) -> str | None:
        """
        Get view definition SQL (intentionally limited).

        Per plan.md, this is intentionally out of scope for initial implementation.
        Always returns NULL.

        Args:
            view_oid: View OID from pg_class.oid (relkind='v')
            pretty: Format with indentation (ignored)

        Returns:
            Always None (view definitions not yet supported)
        """
        logger.debug("pg_get_viewdef intentionally returns NULL (out of scope)", view_oid=view_oid)
        return None

    # ========================================================================
    # T016-T018: Helper Methods
    # ========================================================================

    def _get_constraint_metadata(self, constraint_oid: int) -> dict[str, Any] | None:
        """
        Get constraint metadata from INFORMATION_SCHEMA by OID.

        Args:
            constraint_oid: Constraint OID

        Returns:
            Dict with constraint_type, constraint_name, constraint_schema, table_name
        """
        # Reverse lookup constraint name from OID (requires OID cache)
        # For now, query all constraints and match OID
        query = f"""
            SELECT CONSTRAINT_SCHEMA, CONSTRAINT_NAME, CONSTRAINT_TYPE, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = '{IRIS_SCHEMA}'
        """

        try:
            result = self.executor._execute_iris_query(query)
            if not result or not result.get("rows"):
                return None

            # Find matching OID
            for row in result["rows"]:
                schema, name, ctype, table = row[:4]
                computed_oid = self.oid_gen.get_constraint_oid(name, schema)
                if computed_oid == constraint_oid:
                    return {
                        "constraint_schema": schema,
                        "constraint_name": name,
                        "constraint_type": ctype,
                        "table_name": table,
                    }

            return None

        except Exception as e:
            logger.error(
                "Error querying constraint metadata", constraint_oid=constraint_oid, error=str(e)
            )
            return None

    def _get_constraint_columns(self, schema: str, constraint_name: str) -> list[str]:
        """
        Get column names for a constraint in definition order.

        Args:
            schema: Schema name
            constraint_name: Constraint name

        Returns:
            List of column names in ordinal position order
        """
        query = f"""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE CONSTRAINT_SCHEMA = '{schema}'
              AND CONSTRAINT_NAME = '{constraint_name}'
            ORDER BY ORDINAL_POSITION
        """

        try:
            result = self.executor._execute_iris_query(query)
            if not result or not result.get("rows"):
                return []

            return [row[0].lower() for row in result["rows"]]

        except Exception as e:
            logger.error(
                "Error querying constraint columns", constraint_name=constraint_name, error=str(e)
            )
            return []

    def _get_fk_references(self, schema: str, constraint_name: str) -> dict[str, Any] | None:
        """
        Get foreign key reference details.

        Args:
            schema: Schema name
            constraint_name: FK constraint name

        Returns:
            Dict with ref_table, ref_columns, update_rule, delete_rule
        """
        # Get FK metadata
        query = f"""
            SELECT UNIQUE_CONSTRAINT_SCHEMA, UNIQUE_CONSTRAINT_NAME, UPDATE_RULE, DELETE_RULE
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = '{schema}'
              AND CONSTRAINT_NAME = '{constraint_name}'
        """

        try:
            result = self.executor._execute_iris_query(query)
            if not result or not result.get("rows"):
                return None

            row = result["rows"][0]
            ref_schema, ref_constraint_name, update_rule, delete_rule = row[:4]

            # Get referenced table name
            ref_table_query = f"""
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
                WHERE CONSTRAINT_SCHEMA = '{ref_schema}'
                  AND CONSTRAINT_NAME = '{ref_constraint_name}'
            """

            ref_table_result = self.executor._execute_iris_query(ref_table_query)
            if not ref_table_result or not ref_table_result.get("rows"):
                return None

            ref_table = ref_table_result["rows"][0][0]

            # Get referenced columns
            ref_columns = self._get_constraint_columns(ref_schema, ref_constraint_name)

            return {
                "ref_table": ref_table.lower(),
                "ref_columns": ref_columns,
                "update_rule": update_rule,
                "delete_rule": delete_rule,
            }

        except Exception as e:
            logger.error(
                "Error querying FK references", constraint_name=constraint_name, error=str(e)
            )
            return None

    def _get_index_metadata(self, index_oid: int) -> dict[str, Any] | None:
        """
        Get index metadata from pg_index emulation.

        Args:
            index_oid: Index OID

        Returns:
            Dict with index_name, table_name, is_unique, index_columns
        """
        # Query pg_index and pg_class emulation
        # For now, return None (requires integration with Feature 031 pg_index)
        logger.debug("Index metadata query not yet implemented", index_oid=index_oid)
        return None

    # ========================================================================
    # Public Handler Interface
    # ========================================================================

    def handle(self, function_name: str, arguments: tuple[Any, ...]) -> CatalogFunctionResult:
        """
        Handle catalog function call with timing and debug logging (FR-018).

        Args:
            function_name: Function name (e.g., 'format_type')
            arguments: Function arguments tuple

        Returns:
            CatalogFunctionResult with result or error
        """
        # T034: Debug logging with timing per FR-018
        start_time = time.perf_counter()

        logger.debug(
            "Catalog function call started",
            function=function_name,
            arguments=arguments,
        )

        try:
            if function_name == "format_type":
                type_oid = int(arguments[0])
                typmod = int(arguments[1]) if len(arguments) > 1 else -1
                result = self.format_type(type_oid, typmod)

            elif function_name == "pg_get_constraintdef":
                constraint_oid = int(arguments[0])
                pretty = arguments[1].lower() == "true" if len(arguments) > 1 else False
                result = self.pg_get_constraintdef(constraint_oid, pretty)

            elif function_name == "pg_get_serial_sequence":
                table = str(arguments[0])
                column = str(arguments[1])
                result = self.pg_get_serial_sequence(table, column)

            elif function_name == "pg_get_viewdef":
                view_oid = int(arguments[0])
                pretty = arguments[1].lower() == "true" if len(arguments) > 1 else False
                result = self.pg_get_viewdef(view_oid, pretty)

            elif function_name == "pg_get_indexdef":
                index_oid = int(arguments[0])
                column = int(arguments[1]) if len(arguments) > 1 and arguments[1] else 0
                pretty = arguments[2].lower() == "true" if len(arguments) > 2 else False
                result = self.pg_get_indexdef(index_oid, column, pretty)

            else:
                logger.warning("Unknown catalog function requested", function=function_name)
                return CatalogFunctionResult(
                    function_name=function_name,
                    arguments=list(arguments),
                    result=None,
                    error=f"Unknown catalog function: {function_name}",
                )

            # T034: Log completion with timing
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(
                "Catalog function completed",
                function=function_name,
                elapsed_ms=f"{elapsed_ms:.2f}",
                result_type=type(result).__name__,
                result_is_null=result is None,
            )

            return CatalogFunctionResult(
                function_name=function_name,
                arguments=list(arguments),
                result=result,
                error=None,
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Catalog function error",
                function=function_name,
                elapsed_ms=f"{elapsed_ms:.2f}",
                error=str(e),
                error_type=type(e).__name__,
            )
            return CatalogFunctionResult(
                function_name=function_name,
                arguments=list(arguments),
                result=None,
                error=str(e),
            )
