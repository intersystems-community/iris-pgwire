"""
IRIS SQL Executor for PostgreSQL Wire Protocol

Handles SQL execution against IRIS using embedded Python or external connection.
Based on patterns from caretdev/sqlalchemy-iris for proven IRIS integration.
"""

import asyncio
import concurrent.futures
import threading
import time
from typing import Any

import structlog

from .schema_mapper import translate_output_schema  # Feature 030: PostgreSQL schema mapping
from .sql_translator import (
    SQLTranslator,  # Feature 021: PostgreSQL→IRIS normalization
    TransactionTranslator,
)  # Feature 022: PostgreSQL transaction verb translation
from .sql_translator.alias_extractor import AliasExtractor  # Column alias preservation
from .sql_translator.performance_monitor import MetricType, PerformanceTracker, get_monitor
from .type_mapping import get_type_mapping, load_type_mappings_from_file  # Configurable type mapping
from .catalog.oid_generator import OIDGenerator  # OID generation for catalog emulation

logger = structlog.get_logger()


class IRISExecutor:
    """
    IRIS SQL Execution Handler

    Manages SQL execution against IRIS database using embedded Python when available,
    or external connection as fallback. Implements patterns proven in caretdev
    SQLAlchemy implementation.
    """

    def __init__(self, iris_config: dict[str, Any], server=None):
        self.iris_config = iris_config
        self.server = server  # Reference to server for P4 cancellation
        self.connection = None
        self.embedded_mode = False
        self.vector_support = False

        # Thread pool for async IRIS operations (constitutional requirement)
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=10, thread_name_prefix="iris_executor"
        )

        # Performance monitoring
        self.performance_monitor = get_monitor()

        # Column alias extraction for PostgreSQL compatibility
        self.alias_extractor = AliasExtractor()

        # Connection pool management
        self._connection_lock = threading.RLock()
        self._connection_pool = []
        self._max_connections = 10

        # Load custom type mappings from configuration file (if exists)
        # This allows users to customize IRIS→PostgreSQL type mappings
        # for ORM compatibility (Prisma, SQLAlchemy, etc.)
        load_type_mappings_from_file()

        # Attempt to detect IRIS environment
        self._detect_iris_environment()

        logger.info(
            "IRIS executor initialized",
            host=iris_config.get("host"),
            port=iris_config.get("port"),
            namespace=iris_config.get("namespace"),
            embedded_mode=self.embedded_mode,
        )

    def _detect_iris_environment(self):
        """Detect if we're running in IRIS embedded Python environment"""
        try:
            # Try to import IRIS embedded Python module
            import iris

            # Check if we're in embedded mode by testing for embedded-specific features
            if hasattr(iris, "sql") and hasattr(iris.sql, "exec"):
                self.embedded_mode = True
                logger.info("IRIS embedded Python detected")
                return True
            else:
                # We have iris module but not embedded - use external connection
                self.embedded_mode = False
                logger.info("IRIS Python driver available, using external connection")
                return False
        except ImportError:
            self.embedded_mode = False
            logger.info("IRIS Python driver not available")
            return False

    def _normalize_iris_null(self, value):
        """
        Normalize IRIS NULL representations to Python None.

        IRIS Behavior:
        - Simple queries: Returns empty string '' for NULL
        - Prepared statements: Returns '.*@%SYS.Python' for NULL parameters

        Args:
            value: Value from IRIS result row

        Returns:
            Python None for NULL values, original value otherwise
        """
        if value is None:
            return None

        # Check if value is a string
        if isinstance(value, str):
            # Empty string from simple query NULL
            if value == "":
                return None

            # IRIS Python object representation from prepared statement NULL
            # Pattern: '13@%SYS.Python', '6@%SYS.Python', etc.
            if "@%SYS.Python" in value:
                return None

        return value

    def _convert_iris_horolog_date_to_pg(self, horolog_days: int) -> int:
        """
        Convert IRIS Horolog date to PostgreSQL date format.

        IRIS Horolog Format:
        - Stores dates as days since 1840-12-31 (base date)
        - Example: 67699 days = 2025-11-13

        PostgreSQL Date Format:
        - Stores dates as days since 2000-01-01 (J2000 epoch)
        - Example: 9448 days = 2025-11-13

        Args:
            horolog_days: IRIS Horolog date value (days since 1840-12-31)

        Returns:
            PostgreSQL date value (days since 2000-01-01)
        """
        import datetime

        # IRIS Horolog base date: 1840-12-31
        HOROLOG_BASE = datetime.date(1840, 12, 31)

        # PostgreSQL J2000 epoch: 2000-01-01
        PG_EPOCH = datetime.date(2000, 1, 1)

        # Calculate offset between IRIS and PostgreSQL epochs
        # Days from 1840-12-31 to 2000-01-01
        EPOCH_OFFSET = (PG_EPOCH - HOROLOG_BASE).days

        # Convert IRIS Horolog days to PostgreSQL days
        pg_days = horolog_days - EPOCH_OFFSET

        logger.debug(
            "Converted IRIS Horolog date to PostgreSQL format",
            horolog_days=horolog_days,
            pg_days=pg_days,
            epoch_offset=EPOCH_OFFSET,
        )

        return pg_days

    def _convert_pg_date_to_iris_horolog(self, pg_days: int) -> int:
        """
        Convert PostgreSQL date format to IRIS Horolog date.

        PostgreSQL Date Format:
        - Stores dates as days since 2000-01-01 (J2000 epoch)

        IRIS Horolog Format:
        - Stores dates as days since 1840-12-31 (base date)

        Args:
            pg_days: PostgreSQL date value (days since 2000-01-01)

        Returns:
            IRIS Horolog date value (days since 1840-12-31)
        """
        import datetime

        # IRIS Horolog base date: 1840-12-31
        HOROLOG_BASE = datetime.date(1840, 12, 31)

        # PostgreSQL J2000 epoch: 2000-01-01
        PG_EPOCH = datetime.date(2000, 1, 1)

        # Calculate offset between IRIS and PostgreSQL epochs
        EPOCH_OFFSET = (PG_EPOCH - HOROLOG_BASE).days

        # Convert PostgreSQL days to IRIS Horolog days
        horolog_days = pg_days + EPOCH_OFFSET

        logger.debug(
            "Converted PostgreSQL date to IRIS Horolog format",
            pg_days=pg_days,
            horolog_days=horolog_days,
            epoch_offset=EPOCH_OFFSET,
        )

        return horolog_days

    def _detect_cast_type_oid(self, sql: str, column_name: str) -> int | None:
        """
        Detect type OID from CAST expressions in SQL (2025-11-14 asyncpg boolean fix).

        When IRIS doesn't provide type metadata, we can infer types from CAST expressions
        like $1::bool, CAST(? AS BIT), or CAST(? AS INTEGER).

        Args:
            sql: SQL query string
            column_name: Column name to search for casts

        Returns:
            Type OID if cast detected, None otherwise

        References:
            - asyncpg test_prepared_with_multiple_params: boolean values returned as int
        """
        import re

        sql_upper = sql.upper()

        type_map = {
            "bool": 16,  # boolean
            "boolean": 16,  # boolean
            "bit": 16,  # IRIS uses BIT for boolean
            "int": 23,  # int4
            "integer": 23,  # int4
            "bigint": 20,  # int8
            "smallint": 21,  # int2
            "text": 25,  # text
            "varchar": 1043,  # varchar
            "date": 1082,  # date
            "timestamp": 1114,  # timestamp
            "float": 701,  # float8
            "double": 701,  # float8
        }

        # Pattern 1: PostgreSQL-style type cast (::type)
        # Match: "$1::bool AS column_name"
        pg_cast_pattern = rf"\$\d+::(\w+)\s+AS\s+{re.escape(column_name.upper())}"
        match = re.search(pg_cast_pattern, sql_upper)

        if match:
            cast_type = match.group(1).lower()
            return type_map.get(cast_type)

        # Pattern 2: CAST function (CAST(? AS type) AS column_name)
        # Match: "CAST(? AS BIT) AS flag" or "CAST(? AS INTEGER) AS num"
        cast_func_pattern = rf"CAST\(\?\s+AS\s+(\w+)\)\s+AS\s+{re.escape(column_name.upper())}"
        match = re.search(cast_func_pattern, sql_upper)

        if match:
            cast_type = match.group(1).lower()
            return type_map.get(cast_type)

        return None

    def _infer_type_from_value(self, value) -> int:
        """
        Infer PostgreSQL type OID from Python value

        Args:
            value: Python value from result row

        Returns:
            PostgreSQL type OID (int)
        """
        # Import Decimal for type checking
        from decimal import Decimal

        # INT4 range limits
        INT4_MIN = -2147483648  # -2^31
        INT4_MAX = 2147483647   # 2^31 - 1

        if value is None:
            return 25  # VARCHAR (most flexible for NULL)
        elif isinstance(value, bool):
            return 16  # BOOL
        elif isinstance(value, int):
            # CRITICAL FIX: Check if integer exceeds INT4 range
            # IRIS returns timestamps as large integers that can exceed INT4 max
            # These need to be sent as INT8 (BIGINT) to avoid binary encoding errors
            if INT4_MIN <= value <= INT4_MAX:
                return 23  # INTEGER (INT4)
            else:
                return 20  # BIGINT (INT8) for large integers
        elif isinstance(value, float):
            return 701  # FLOAT8/DOUBLE
        elif isinstance(value, Decimal):
            return 1700  # NUMERIC/DECIMAL
        elif isinstance(value, bytes):
            return 17  # BYTEA
        elif isinstance(value, str):
            return 25  # VARCHAR/TEXT
        else:
            return 25  # Default to VARCHAR

    def _split_sql_statements(self, sql: str) -> list[str]:
        """
        Split SQL string into individual statements, handling semicolons properly.

        CRITICAL FIX for issue: "Input (;) encountered after end of query"
        IRIS cannot execute multiple statements in a single iris.sql.exec() call.

        This function splits by semicolons while respecting:
        - String literals (single and double quotes)
        - Comments (-- and /* */)
        - Semicolons inside string literals are NOT statement separators

        Args:
            sql: SQL string potentially containing multiple statements

        Returns:
            List of individual SQL statements (semicolons removed, whitespace stripped)
        """
        statements = []
        current_stmt = []
        in_single_quote = False
        in_double_quote = False
        in_line_comment = False
        in_block_comment = False
        i = 0

        while i < len(sql):
            char = sql[i]

            # Handle line comments (-- to end of line)
            if not in_single_quote and not in_double_quote and not in_block_comment:
                if i < len(sql) - 1 and sql[i : i + 2] == "--":
                    in_line_comment = True
                    current_stmt.append(char)
                    i += 1
                    continue

            # End of line comment
            if in_line_comment:
                current_stmt.append(char)
                if char == "\n":
                    in_line_comment = False
                i += 1
                continue

            # Handle block comments (/* ... */)
            if not in_single_quote and not in_double_quote and not in_line_comment:
                if i < len(sql) - 1 and sql[i : i + 2] == "/*":
                    in_block_comment = True
                    current_stmt.append(char)
                    i += 1
                    continue
                elif i < len(sql) - 1 and sql[i : i + 2] == "*/":
                    in_block_comment = False
                    current_stmt.append(char)
                    i += 1
                    continue

            if in_block_comment:
                current_stmt.append(char)
                i += 1
                continue

            # Toggle quote states
            if char == "'" and not in_double_quote:
                # Handle escaped quotes
                if i > 0 and sql[i - 1] == "\\":
                    current_stmt.append(char)
                else:
                    in_single_quote = not in_single_quote
                    current_stmt.append(char)
            elif char == '"' and not in_single_quote:
                if i > 0 and sql[i - 1] == "\\":
                    current_stmt.append(char)
                else:
                    in_double_quote = not in_double_quote
                    current_stmt.append(char)
            # Statement separator (semicolon outside quotes)
            elif char == ";" and not in_single_quote and not in_double_quote:
                # End of statement - save it
                stmt = "".join(current_stmt).strip()
                if stmt:  # Skip empty statements
                    statements.append(stmt)
                current_stmt = []
            else:
                current_stmt.append(char)

            i += 1

        # Add final statement if any
        stmt = "".join(current_stmt).strip()
        if stmt:
            statements.append(stmt)

        logger.debug(
            "Split SQL into statements", total_statements=len(statements), original_length=len(sql)
        )

        return statements

    async def test_connection(self):
        """Test IRIS connectivity before starting server"""
        try:
            if self.embedded_mode:
                # In embedded mode, skip connection test at startup
                # IRIS is already available via iris.sql.exec()
                logger.info(
                    "IRIS embedded mode detected - skipping connection test", embedded_mode=True
                )
            else:
                await self._test_external_connection()

            # Test vector support (from caretdev pattern)
            await self._test_vector_support()

            logger.info(
                "IRIS connection test successful",
                embedded_mode=self.embedded_mode,
                vector_support=self.vector_support,
            )

        except Exception as e:
            logger.error("IRIS connection test failed", error=str(e))
            raise ConnectionError(f"Cannot connect to IRIS: {e}")

    async def _test_embedded_connection(self):
        """Test IRIS embedded Python connection"""

        def _sync_test():
            import iris

            # Simple test query
            result = iris.sql.exec("SELECT 1 as test_column").fetch()
            return result[0]["test_column"] == 1

        # Run in thread to avoid blocking asyncio loop
        result = await asyncio.to_thread(_sync_test)
        if not result:
            raise RuntimeError("IRIS embedded test query failed")

    async def _test_external_connection(self):
        """Test external IRIS connection using intersystems driver"""
        try:

            def _sync_test():
                import iris

                # Test real connection to IRIS
                try:
                    conn = iris.connect(
                        hostname=self.iris_config["host"],
                        port=self.iris_config["port"],
                        namespace=self.iris_config["namespace"],
                        username=self.iris_config["username"],
                        password=self.iris_config["password"],
                    )

                    # Test simple query
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    cursor.close()
                    conn.close()

                    return result[0] == 1

                except Exception as e:
                    logger.warning(
                        "Real IRIS connection failed, config validation only", error=str(e)
                    )
                    # Fallback to config validation
                    required_keys = ["host", "port", "username", "password", "namespace"]
                    for key in required_keys:
                        if key not in self.iris_config:
                            raise ValueError(f"Missing IRIS config: {key}")
                    return True

            result = await asyncio.to_thread(_sync_test)

            logger.info(
                "IRIS connection test successful",
                host=self.iris_config["host"],
                port=self.iris_config["port"],
                namespace=self.iris_config["namespace"],
            )
            return result

        except Exception as e:
            logger.error("IRIS connection test failed", error=str(e))
            raise

    async def _test_vector_support(self):
        """Test if IRIS vector support is available (from caretdev pattern)"""
        try:
            if self.embedded_mode:

                def _sync_vector_test():
                    import iris

                    try:
                        # Test query from caretdev implementation
                        iris.sql.exec("select vector_cosine(to_vector('1'), to_vector('1'))")
                        return True
                    except Exception as e:
                        # Vector support not available (license or feature not enabled)
                        logger.debug("Vector test query failed", error=str(e))
                        return False

                result = await asyncio.to_thread(_sync_vector_test)
                self.vector_support = result
                if result:
                    logger.info("IRIS vector support detected")
                else:
                    logger.info("IRIS vector support not available (license or feature disabled)")

            else:
                # For external connections, assume no vector support in P0
                self.vector_support = False
                logger.info("Vector support detection skipped for external connection")

        except Exception as e:
            self.vector_support = False
            logger.info("IRIS vector support test failed", error=str(e))

    async def execute_query(
        self, sql: str, params: list | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute SQL query against IRIS with proper async threading

        Args:
            sql: SQL query string (should already be translated by protocol layer)
            params: Optional query parameters
            session_id: Optional session identifier for performance tracking

        Returns:
            Dictionary with query results and metadata
        """
        try:
            # Feature 022: Apply PostgreSQL→IRIS transaction verb translation FIRST
            # This must happen before any other processing
            from .sql_translator import TransactionTranslator

            transaction_translator = TransactionTranslator()
            sql = transaction_translator.translate_transaction_command(sql)

            # Intercept PostgreSQL system function calls and return stub results
            sql_upper = sql.upper().strip().rstrip(";")

            # DEBUG: Log sql_upper for DISCARD ALL debugging
            if "DISCARD" in sql_upper:
                logger.warning(
                    f"🔍 DEBUG sql_upper check: sql_upper='{sql_upper}' | startswith('DISCARD ALL')={sql_upper.startswith('DISCARD ALL')} | equals='DISCARD ALL'={sql_upper == 'DISCARD ALL'}"
                )

            # SHOW command - Return PostgreSQL configuration values
            if sql_upper.startswith("SHOW "):
                param_name = sql_upper[5:].strip()  # Extract parameter name
                logger.info("Intercepting SHOW command", param=param_name, session_id=session_id)
                # Common PostgreSQL parameters
                show_values = {
                    "SERVER_VERSION": "16.0 (InterSystems IRIS)",
                    "SERVER_VERSION_NUM": "160000",
                    "CLIENT_ENCODING": "UTF8",
                    "DATESTYLE": "ISO, MDY",
                    "TIMEZONE": "UTC",
                    "STANDARD_CONFORMING_STRINGS": "on",
                    "INTEGER_DATETIMES": "on",
                    "INTERVALSTYLE": "postgres",
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

            # Handle Prisma schema existence check query:
            # SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = ?), version(), current_setting('server_version_num')::integer
            # Prisma sends this to check if the target schema exists before introspection
            # CRITICAL: Must be checked BEFORE generic CURRENT_SETTING handler
            # CRITICAL: The ::integer cast means current_setting must return INTEGER type_oid (23), not TEXT (25)
            if "EXISTS" in sql_upper and "PG_NAMESPACE" in sql_upper and "VERSION" in sql_upper:
                logger.info(
                    "Intercepting Prisma schema existence check query",
                    sql=sql[:150],
                    session_id=session_id,
                )
                # Determine which schema Prisma is checking
                # params[0] should be the schema name (e.g., 'public')
                # CRITICAL FIX: During Describe phase, params may be None or contain dummy values
                # Default to True for 'public' schema which Prisma always expects to exist
                schema_exists = True  # Default: 'public' exists
                schema_name = 'public'  # Default schema

                if params and len(params) > 0 and params[0] is not None:
                    # Actual parameter provided - validate it
                    schema_name = params[0] if isinstance(params[0], str) else str(params[0])
                    # Handle 'None' string that might come from str(None)
                    if schema_name.lower() != 'none':
                        schema_exists = schema_name.lower() in ['public', 'sqluser', 'pg_catalog', 'information_schema']
                    else:
                        # 'None' string means no param provided - default to public exists
                        schema_name = 'public'
                        schema_exists = True

                logger.info(f"Prisma checking schema '{schema_name}', exists={schema_exists}")

                return {
                    "success": True,
                    "rows": [[
                        schema_exists,  # EXISTS result (boolean)
                        "PostgreSQL 16.0 (InterSystems IRIS)",  # version()
                        160000  # current_setting('server_version_num')::integer - MUST be int, not string!
                    ]],
                    "columns": [
                        {
                            "name": "exists",
                            "type_oid": 16,  # bool
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "version",
                            "type_oid": 25,  # text
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "numeric_version",  # Match Prisma's expected column name
                            "type_oid": 23,  # int4 - CRITICAL: Prisma casts to ::integer
                            "type_size": 4,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                    ],
                    "row_count": 1,
                }

            # Handle asyncpg type introspection query: SELECT CURRENT_SETTING('jit') AS CUR, SET_CONFIG('jit', 'off', FALSE) AS NEW
            if "CURRENT_SETTING" in sql_upper and "SET_CONFIG" in sql_upper:
                logger.info(
                    "Intercepting asyncpg type introspection query",
                    sql=sql[:150],
                    session_id=session_id,
                )
                return {
                    "success": True,
                    "rows": [["off", "off"]],  # Two columns: CUR and NEW
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

            # CURRENT_SETTING(name) - Return configuration parameter value (single call)
            if "CURRENT_SETTING" in sql_upper:
                logger.info(
                    "Intercepting CURRENT_SETTING function call",
                    sql=sql[:100],
                    session_id=session_id,
                )
                return {
                    "success": True,
                    "rows": [["off"]],  # Return 'off' for JIT and other settings
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

            # SET_CONFIG(name, value, is_local) - Set configuration parameter (single call)
            if "SET_CONFIG" in sql_upper:
                logger.info(
                    "Intercepting SET_CONFIG function call", sql=sql[:100], session_id=session_id
                )
                return {
                    "success": True,
                    "rows": [["off"]],  # Return the value that was set
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

            # PG_ADVISORY_UNLOCK_ALL() - Release all advisory locks
            if "PG_ADVISORY_UNLOCK_ALL" in sql_upper:
                logger.info(
                    "Intercepting PG_ADVISORY_UNLOCK_ALL function call",
                    sql=sql[:100],
                    session_id=session_id,
                )
                return {"success": True, "rows": [], "columns": [], "row_count": 0}

            # CURRENT_DATABASE() - Return current database name
            if "CURRENT_DATABASE" in sql_upper:
                logger.info(
                    "Intercepting CURRENT_DATABASE function call",
                    sql=sql[:100],
                    session_id=session_id,
                )
                # Get namespace from connection config (external mode) or embedded mode
                namespace_name = getattr(
                    self, "iris_namespace", "USER"
                )  # Default to USER if not set
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

            # VERSION() - Return PostgreSQL version string
            if "VERSION()" in sql_upper or sql_upper.startswith("SELECT VERSION"):
                logger.info(
                    "Intercepting VERSION() function call", sql=sql[:100], session_id=session_id
                )
                version_string = "PostgreSQL 16.0 (InterSystems IRIS PGWire Protocol)"
                return {
                    "success": True,
                    "rows": [[version_string]],
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

            # DISCARD ALL - PostgreSQL session reset/cleanup command
            # Sent by Npgsql during connection teardown - IRIS doesn't support this
            if sql_upper.startswith("DISCARD ALL") or sql_upper == "DISCARD ALL":
                logger.info(
                    "Intercepting DISCARD ALL command (Npgsql cleanup)",
                    sql=sql[:100],
                    session_id=session_id,
                )
                return {
                    "success": True,
                    "rows": [],
                    "columns": [],
                    "row_count": 0,
                    "command": "DISCARD",
                    "command_tag": "DISCARD ALL",
                }

            # Performance tracking for constitutional compliance
            with PerformanceTracker(
                MetricType.API_RESPONSE_TIME,
                "iris_executor",
                session_id=session_id,
                sql_length=len(sql),
            ) as tracker:

                # P5: Vector query detection for enhanced logging
                if self.vector_support and "VECTOR" in sql.upper():
                    logger.debug(
                        "Vector query detected",
                        sql=sql[:100] + "..." if len(sql) > 100 else sql,
                        session_id=session_id,
                    )

                # Use async execution with thread pool
                # DEBUG: Log execution path decision
                logger.warning(
                    f"🔍 DEBUG: execute_query() branching - embedded_mode = {self.embedded_mode}"
                )
                if self.embedded_mode:
                    logger.warning("🔍 DEBUG: Taking EMBEDDED path → _execute_embedded_async()")
                    result = await self._execute_embedded_async(sql, params, session_id)
                else:
                    logger.warning("🔍 DEBUG: Taking EXTERNAL path → _execute_external_async()")
                    result = await self._execute_external_async(sql, params, session_id)

                # Add performance metadata
                result["execution_metadata"] = {
                    "execution_time_ms": tracker.start_time
                    and (time.perf_counter() - tracker.start_time) * 1000,
                    "embedded_mode": self.embedded_mode,
                    "vector_support": self.vector_support,
                    "session_id": session_id,
                    "sql_length": len(sql),
                }

                # Record performance metrics
                if tracker.violation:
                    logger.warning(
                        "IRIS execution SLA violation",
                        actual_time_ms=tracker.violation.actual_value_ms,
                        sla_threshold_ms=tracker.violation.sla_threshold_ms,
                        session_id=session_id,
                    )

                return result

        except Exception as e:
            logger.error(
                "SQL execution failed",
                sql=sql[:100] + "..." if len(sql) > 100 else sql,
                error=str(e),
                session_id=session_id,
            )
            raise

    async def execute_many(
        self, sql: str, params_list: list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute SQL with multiple parameter sets using executemany() for batch operations.

        This method provides SIGNIFICANT performance improvements for bulk INSERT operations:
        - Community benchmark: IRIS 1.48s vs PostgreSQL 4.58s (4× faster)
        - Projected throughput: 2,400-10,000+ rows/sec (vs 600 rows/sec with individual INSERTs)
        - Leverages IRIS "Fast Insert" optimization (client-side normalization)

        Args:
            sql: SQL statement with parameter placeholders (e.g., "INSERT INTO table VALUES (?, ?)")
            params_list: List of parameter tuples, one per execution
                        Example: [(1, 'a'), (2, 'b'), (3, 'c')]
            session_id: Optional session identifier for performance tracking

        Returns:
            Dictionary with:
                - success: True if all executions succeeded
                - rows_affected: Total number of rows affected
                - execution_metadata: Performance timing information

        Raises:
            Exception: If any execution in the batch fails

        Constitutional Compliance:
            - Uses asyncio.to_thread() for non-blocking execution (Principle IV)
            - Applies transaction translation and SQL normalization (Features 021-022)
            - Performance tracking for constitutional SLA compliance

        References:
            - Community benchmark: community.intersystems.com/post/performance-tests-iris-postgresql-mysql-using-python
            - COPY Performance Investigation: docs/COPY_PERFORMANCE_INVESTIGATION.md
        """
        try:
            # Performance tracking for constitutional compliance
            with PerformanceTracker(
                MetricType.API_RESPONSE_TIME,
                "iris_executor_many",
                session_id=session_id,
                sql_length=len(sql),
            ) as tracker:

                logger.info(
                    "execute_many() called",
                    sql_preview=sql[:100],
                    batch_size=len(params_list),
                    session_id=session_id,
                )

                # ARCHITECTURE FIX: ALWAYS try DBAPI executemany() first (fast path)
                # Even in embedded mode (irispython), we can connect to localhost via DBAPI
                # This leverages connection independence: execution mode ≠ connection mode
                # Fall back to loop-based execution only if DBAPI fails
                try:
                    logger.debug("Attempting DBAPI executemany() fast path", session_id=session_id)
                    result = await self._execute_many_external_async(sql, params_list, session_id)
                    logger.info(
                        "✅ DBAPI executemany() succeeded (fast path)",
                        rows_affected=result.get("rows_affected", 0),
                        session_id=session_id,
                    )
                except Exception as dbapi_error:
                    logger.warning(
                        "DBAPI executemany() failed, falling back to loop-based execution",
                        error=str(dbapi_error)[:200],
                        error_type=type(dbapi_error).__name__,
                        session_id=session_id,
                    )
                    # Fallback to loop-based execution (slower but reliable)
                    result = await self._execute_many_embedded_async(sql, params_list, session_id)
                    logger.info(
                        "✅ Loop-based execution succeeded (fallback path)",
                        rows_affected=result.get("rows_affected", 0),
                        session_id=session_id,
                    )

                # Add performance metadata (including which path was actually used)
                result["execution_metadata"] = {
                    "execution_time_ms": tracker.start_time
                    and (time.perf_counter() - tracker.start_time) * 1000,
                    "embedded_mode": self.embedded_mode,
                    "execution_path": result.get(
                        "_execution_path", "unknown"
                    ),  # 'dbapi_executemany' or 'loop_fallback'
                    "batch_size": len(params_list),
                    "session_id": session_id,
                    "sql_length": len(sql),
                }

                # Record performance metrics
                if tracker.violation:
                    logger.warning(
                        "execute_many() SLA violation",
                        actual_time_ms=tracker.violation.actual_value_ms,
                        sla_threshold_ms=tracker.violation.sla_threshold_ms,
                        batch_size=len(params_list),
                        session_id=session_id,
                    )

                return result

        except Exception as e:
            logger.error(
                "execute_many() failed",
                sql=sql[:100] + "..." if len(sql) > 100 else sql,
                batch_size=len(params_list),
                error=str(e),
                session_id=session_id,
            )
            raise

    async def _execute_many_embedded_async(
        self, sql: str, params_list: list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute batch SQL using IRIS embedded Python executemany() with proper async threading.

        This method leverages IRIS's native batch execution capabilities for maximum performance.
        """

        def _sync_execute_many():
            """
            Synchronous IRIS batch execution in thread pool.

            ARCHITECTURE NOTE for Embedded Mode:
            In embedded mode (irispython), iris.dbapi is shadowed by embedded iris module.
            Therefore, we use loop-based execution with iris.sql.exec() instead of
            cursor.executemany(). While this doesn't leverage IRIS "Fast Insert",
            it works reliably in all modes.

            For external mode, use _execute_many_external_async() which supports
            true executemany() with DBAPI.
            """
            import iris

            logger.info(
                "🚀 EXECUTING BATCH IN EMBEDDED MODE (loop-based)",
                sql_preview=sql[:100],
                batch_size=len(params_list),
                session_id=session_id,
            )

            try:
                # Feature 022: Apply PostgreSQL→IRIS transaction verb translation
                transaction_translator = TransactionTranslator()
                transaction_translated_sql = transaction_translator.translate_transaction_command(
                    sql
                )

                # Feature 021: Apply PostgreSQL→IRIS SQL normalization
                translator = SQLTranslator()
                normalized_sql = translator.normalize_sql(
                    transaction_translated_sql, execution_path="batch"
                )

                # Strip trailing semicolon
                if normalized_sql.rstrip().endswith(";"):
                    normalized_sql = normalized_sql.rstrip().rstrip(";")

                logger.info(
                    "Executing batch with loop (embedded mode - inline SQL values)",
                    sql_preview=normalized_sql[:100],
                    batch_size=len(params_list),
                    session_id=session_id,
                )

                # Execute batch using loop with iris.sql.exec() - INLINE SQL VALUES
                # CRITICAL: Cannot use parameter binding in embedded mode (values become '15@%SYS.Python')
                # Must build inline SQL with values directly in the SQL string
                start_time = time.perf_counter()

                rows_affected = 0
                for params in params_list:
                    try:
                        # Build inline SQL by replacing ? placeholders with actual values
                        inline_sql = normalized_sql
                        for param_value in params:
                            # Convert value to SQL literal
                            if param_value is None:
                                sql_literal = "NULL"
                            elif isinstance(param_value, int | float):
                                # Numbers can be used directly
                                sql_literal = str(param_value)
                            else:
                                # Strings need quoting and escaping
                                escaped_value = str(param_value).replace("'", "''")
                                sql_literal = f"'{escaped_value}'"

                            # Replace first occurrence of ? with the value
                            inline_sql = inline_sql.replace("?", sql_literal, 1)

                        logger.debug(f"Executing inline SQL: {inline_sql[:150]}...")
                        iris.sql.exec(inline_sql)
                        rows_affected += 1
                    except Exception as row_error:
                        logger.error(
                            f"Failed to execute row {rows_affected + 1}: {row_error}",
                            params=params[:3] if len(params) > 3 else params,
                            inline_sql_preview=(
                                inline_sql[:200] if "inline_sql" in locals() else "N/A"
                            ),
                        )
                        raise

                execution_time = (time.perf_counter() - start_time) * 1000

                logger.info(
                    "✅ Batch execution COMPLETE (loop-based)",
                    rows_affected=rows_affected,
                    execution_time_ms=execution_time,
                    throughput_rows_per_sec=(
                        int(rows_affected / (execution_time / 1000)) if execution_time > 0 else 0
                    ),
                    session_id=session_id,
                )

                return {
                    "success": True,
                    "rows_affected": rows_affected,
                    "execution_time_ms": execution_time,
                    "batch_size": len(params_list),
                    "rows": [],  # Batch operations don't return rows
                    "columns": [],
                    "_execution_path": "loop_fallback",  # Tag for metadata
                }

            except Exception as e:
                logger.error(
                    "Batch execution failed in IRIS (loop-based)",
                    error=str(e),
                    error_type=type(e).__name__,
                    batch_size=len(params_list),
                    session_id=session_id,
                )
                raise

        # Execute in thread pool to avoid blocking event loop
        return await asyncio.to_thread(_sync_execute_many)

    async def _execute_many_external_async(
        self, sql: str, params_list: list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute batch SQL using external DBAPI executemany() for optimal performance.

        THIS IS WHERE THE PERFORMANCE GAINS HAPPEN:
        - Uses cursor.executemany() with pooled DBAPI connection
        - Leverages IRIS "Fast Insert" optimization
        - Community benchmark: IRIS 1.48s vs PostgreSQL 4.58s (4× faster)
        - Expected throughput: 2,400-10,000+ rows/sec
        """

        def _sync_execute_many():
            """Synchronous IRIS DBAPI executemany() in thread pool"""

            logger.info(
                "🚀 EXECUTING BATCH IN EXTERNAL MODE (executemany)",
                sql_preview=sql[:100],
                batch_size=len(params_list),
                session_id=session_id,
            )

            connection = None
            cursor = None

            try:
                # Get pooled connection
                connection = self._get_pooled_connection()

                # Feature 022: Apply PostgreSQL→IRIS transaction verb translation
                transaction_translator = TransactionTranslator()
                transaction_translated_sql = transaction_translator.translate_transaction_command(
                    sql
                )

                # Feature 021: Apply PostgreSQL→IRIS SQL normalization
                translator = SQLTranslator()
                normalized_sql = translator.normalize_sql(
                    transaction_translated_sql, execution_path="batch"
                )

                # Strip trailing semicolon
                if normalized_sql.rstrip().endswith(";"):
                    normalized_sql = normalized_sql.rstrip().rstrip(";")

                logger.info(
                    "Executing executemany() batch (external mode)",
                    sql_preview=normalized_sql[:100],
                    batch_size=len(params_list),
                    session_id=session_id,
                )

                # Execute batch using DBAPI cursor.executemany()
                # KEY OPTIMIZATION: Uses IRIS "Fast Insert" feature
                start_time = time.perf_counter()

                cursor = connection.cursor()
                cursor.executemany(normalized_sql, params_list)

                execution_time = (time.perf_counter() - start_time) * 1000
                rows_affected = cursor.rowcount if hasattr(cursor, "rowcount") else len(params_list)

                logger.info(
                    "✅ executemany() COMPLETE (external mode)",
                    rows_affected=rows_affected,
                    execution_time_ms=execution_time,
                    throughput_rows_per_sec=(
                        int(rows_affected / (execution_time / 1000)) if execution_time > 0 else 0
                    ),
                    session_id=session_id,
                )

                return {
                    "success": True,
                    "rows_affected": rows_affected,
                    "execution_time_ms": execution_time,
                    "batch_size": len(params_list),
                    "rows": [],
                    "columns": [],
                    "_execution_path": "dbapi_executemany",  # Tag for metadata
                }

            except Exception as e:
                logger.error(
                    "executemany() failed in external mode",
                    error=str(e),
                    error_type=type(e).__name__,
                    batch_size=len(params_list),
                    session_id=session_id,
                )
                raise

            finally:
                # Clean up cursor (connection returns to pool)
                if cursor:
                    try:
                        cursor.close()
                    except Exception:
                        pass
                if connection:
                    try:
                        self._return_connection(connection)
                    except Exception:
                        pass

        # Execute in thread pool to avoid blocking event loop
        return await asyncio.to_thread(_sync_execute_many)

    async def _execute_embedded_async(
        self, sql: str, params: list | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute SQL using IRIS embedded Python with proper async threading

        This method runs the blocking IRIS operations in a thread pool to avoid
        blocking the event loop, following constitutional async requirements.
        """

        def _sync_execute():
            """Synchronous IRIS execution in thread pool"""
            import iris

            # Log entry to embedded execution path
            logger.info(
                "🔍 EXECUTING IN EMBEDDED MODE",
                sql_preview=sql[:100],
                has_params=params is not None,
                param_count=len(params) if params else 0,
                session_id=session_id,
            )

            # CRITICAL: Intercept PostgreSQL system catalog queries BEFORE any translation
            # - asyncpg queries pg_type when it sees OID 0 (unspecified) in ParameterDescription
            # - Npgsql queries pg_type during connection bootstrap to build type registry
            # - IRIS doesn't have PostgreSQL system catalogs (pg_type, pg_enum, pg_catalog)
            # Solution: Return FAKE pg_type data with standard PostgreSQL type OIDs
            sql_upper = sql.upper()

            # pg_enum - Return empty with column metadata (no enums defined)
            # CRITICAL: PostgreSQL protocol requires RowDescription even for 0-row results
            if "PG_ENUM" in sql_upper:
                logger.info(
                    "Intercepting pg_enum query (returning empty with column metadata)",
                    sql_preview=sql[:100],
                    session_id=session_id,
                )
                # Parse SELECT clause using regex to extract all "... AS alias" patterns
                # This handles function calls with commas like obj_description(t.oid, 'pg_type') AS description
                import re

                columns = []
                # Match patterns like: expression AS alias
                # expression can be: column, table.column, function(args)
                as_pattern = re.compile(
                    r'(?:[\w\.]+(?:\([^)]*\))?)\s+AS\s+(\w+)',
                    re.IGNORECASE
                )
                aliases = as_pattern.findall(sql)

                # DEBUG: Log what the regex found
                logger.warning(
                    f"🔍 pg_enum regex debug: sql_len={len(sql)}, aliases_found={aliases}, sql_first_200={sql[:200]!r}"
                )

                if aliases:
                    # We found AS aliases - use those as column names
                    for alias in aliases:
                        columns.append({
                            "name": alias,
                            "type_oid": 25,  # text type
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        })

                if not columns:
                    # Fallback to default columns
                    columns = [
                        {"name": "oid", "type_oid": 26, "type_size": 4, "type_modifier": -1, "format_code": 0},
                        {"name": "enumlabel", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                    ]

                return {
                    "success": True,
                    "rows": [],
                    "columns": columns,
                    "row_count": 0,
                    "command": "SELECT",
                    "command_tag": "SELECT 0",
                }

            # pg_namespace - Return standard PostgreSQL namespaces for Prisma/ORM introspection
            # Prisma queries: SELECT namespace.nspname ... FROM pg_namespace WHERE nspname = ANY($1)
            # CRITICAL: Prisma needs 'public' schema to discover tables
            # CRITICAL: Only intercept SIMPLE pg_namespace queries, not complex JOINs
            # Complex queries like "SELECT ... FROM pg_namespace JOIN pg_class" should go to CatalogRouter
            import re
            is_simple_pg_namespace = (
                "PG_NAMESPACE" in sql_upper and
                # Must have FROM pg_namespace (direct table access)
                re.search(r"\bFROM\s+PG_NAMESPACE\b", sql_upper) and
                # Must NOT have JOIN (which indicates complex query)
                "JOIN" not in sql_upper and
                # Must NOT have multiple FROM clauses (subqueries are OK)
                len(re.findall(r"\bFROM\b", sql_upper)) <= 2  # Allow 1 main + 1 subquery
            )

            if is_simple_pg_namespace:
                logger.info(
                    "Intercepting SIMPLE pg_namespace query (returning standard namespaces)",
                    sql_preview=sql[:150],
                    session_id=session_id,
                )

                # Define namespace columns
                columns = [
                    {
                        "name": "nspname",
                        "type_oid": 19,  # name type
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "oid",
                        "type_oid": 26,  # oid type
                        "type_size": 4,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                ]

                # Standard PostgreSQL namespaces
                # OIDs match PostgreSQL's well-known values
                all_namespaces = [
                    ("public", 2200),
                    ("pg_catalog", 11),
                    ("information_schema", 11323),
                    ("sqluser", 16384),  # IRIS default schema mapped to custom OID
                ]

                # Check if query filters by specific namespaces (ANY clause)
                # Prisma sends: WHERE nspname = ANY($1) with params=['public']
                filtered_namespaces = all_namespaces
                if params and len(params) > 0 and params[0] is not None:
                    # params[0] could be:
                    # - A list: ['public', 'pg_catalog']
                    # - A string representing a list: "['public']" or "{public}"
                    # - A single string: 'public'
                    filter_names = []
                    param0 = params[0]

                    if isinstance(param0, list):
                        filter_names = param0
                    elif isinstance(param0, str):
                        # Try to parse string-encoded lists
                        import json
                        try:
                            # Handle JSON array format: ["public", "pg_catalog"]
                            parsed = json.loads(param0)
                            if isinstance(parsed, list):
                                filter_names = parsed
                            else:
                                filter_names = [str(parsed)]
                        except json.JSONDecodeError:
                            # Handle PostgreSQL array format: {public,pg_catalog}
                            if param0.startswith('{') and param0.endswith('}'):
                                inner = param0[1:-1]
                                if inner:
                                    filter_names = [s.strip().strip('"') for s in inner.split(',')]
                            # Handle Python-like array format: [public] or ['public']
                            elif param0.startswith('[') and param0.endswith(']'):
                                inner = param0[1:-1].strip()
                                if inner:
                                    # Remove any quotes around values
                                    filter_names = [s.strip().strip('"').strip("'") for s in inner.split(',')]
                            elif param0 == '[]' or param0 == '{}':
                                # Empty array - return all namespaces
                                filter_names = []
                            else:
                                # Single value
                                filter_names = [param0]
                    else:
                        filter_names = [str(param0)]

                    # Only filter if we have actual names
                    if filter_names:
                        filter_names_lower = [n.lower() for n in filter_names if n]
                        filtered_namespaces = [
                            (name, oid) for name, oid in all_namespaces
                            if name.lower() in filter_names_lower
                        ]
                        logger.info(
                            f"pg_namespace: filtering by {filter_names}, found {len(filtered_namespaces)} matches"
                        )
                    else:
                        logger.info("pg_namespace: empty filter, returning all namespaces")

                # Check if query requests only nspname (single column) or both columns
                # Prisma query: SELECT namespace.nspname as namespace_name FROM pg_namespace
                import re
                select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
                if select_match:
                    select_clause = select_match.group(1).lower()
                    # Check what columns are requested
                    has_nspname = "nspname" in select_clause or "namespace_name" in select_clause
                    has_oid = "oid" in select_clause and "nspname" not in select_clause.split("oid")[0][-5:]

                    if has_nspname and not has_oid:
                        # Only nspname requested (Prisma pattern)
                        columns = [columns[0]]  # Just nspname
                        # Check for alias
                        if "namespace_name" in select_clause:
                            columns[0] = columns[0].copy()
                            columns[0]["name"] = "namespace_name"
                        rows = [(name,) for name, _ in filtered_namespaces]
                    else:
                        # Both columns
                        rows = [tuple(ns) for ns in filtered_namespaces]
                else:
                    # Default: return both columns
                    rows = [tuple(ns) for ns in filtered_namespaces]

                return {
                    "success": True,
                    "rows": rows,
                    "columns": columns,
                    "row_count": len(rows),
                    "command": "SELECT",
                    "command_tag": f"SELECT {len(rows)}",
                }

            # pg_constraint - Return constraint information from IRIS INFORMATION_SCHEMA
            # Prisma sends MULTIPLE types of pg_constraint queries:
            # 1. Primary/Unique/Foreign key query - needs constraint_definition, column_names
            # 2. Check/exclusion constraint query - needs is_deferrable, is_deferred
            # 3. Index query (WITH rawindex) - needs index info, NOT check constraints
            # 4. Foreign key relationships query - needs parent/child column info
            # CRITICAL: Must check BEFORE pg_class since constraint queries also reference pg_class
            if "PG_CONSTRAINT" in sql_upper or "CONSTR.CONNAME" in sql_upper:
                logger.info(
                    "Intercepting pg_constraint query (returning from INFORMATION_SCHEMA)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Check if this is a check/exclusion constraint query
                # SPECIFIC pattern: contype NOT IN ('p', 'u', 'f') - filters for check/exclusion only
                # MUST NOT match WITH rawindex queries which also have condeferrable/condeferred
                is_check_constraint_query = (
                    "NOT IN" in sql_upper and
                    ("'P'" in sql_upper or "'U'" in sql_upper or "'F'" in sql_upper) and
                    "CONTYPE" in sql_upper  # Must explicitly filter by contype
                )

                # Also detect specific check constraint columns, but NOT if it's a WITH rawindex query
                is_rawindex_query = "WITH RAWINDEX" in sql_upper
                has_deferrable = "IS_DEFERRABLE" in sql_upper  # Only exact match, not CONDEFERRABLE
                has_deferred = "IS_DEFERRED" in sql_upper  # Only exact match, not CONDEFERRED

                # Check constraint query: has is_deferrable/is_deferred columns AND NOT a rawindex query
                if is_check_constraint_query or (has_deferrable and has_deferred and not is_rawindex_query):
                    logger.info(
                        "Check/exclusion constraint query detected - returning empty result",
                        is_check_query=is_check_constraint_query,
                        has_deferrable=has_deferrable,
                        session_id=session_id,
                    )
                    # Return empty result with expected columns for check constraint query
                    columns = [
                        {"name": "namespace", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "table_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "constraint_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "constraint_type", "type_oid": 18, "type_size": 1, "type_modifier": -1, "format_code": 0},  # char
                        {"name": "constraint_definition", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},  # text
                        {"name": "is_deferrable", "type_oid": 16, "type_size": 1, "type_modifier": -1, "format_code": 0},  # bool
                        {"name": "is_deferred", "type_oid": 16, "type_size": 1, "type_modifier": -1, "format_code": 0},  # bool
                    ]
                    return {
                        "success": True,
                        "rows": [],
                        "columns": columns,
                        "row_count": 0,
                        "command": "SELECT",
                        "command_tag": "SELECT 0",
                    }

                try:
                    import iris

                    # Query INFORMATION_SCHEMA for constraints
                    # Map constraint types: PRIMARY KEY -> p, UNIQUE -> u, FOREIGN KEY -> f
                    constraints_sql = """
                        SELECT
                            'public' AS namespace,
                            TABLE_NAME,
                            CONSTRAINT_NAME,
                            CONSTRAINT_TYPE
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
                        WHERE TABLE_SCHEMA = 'SQLUser'
                        ORDER BY TABLE_NAME, CONSTRAINT_NAME
                    """
                    result = iris.sql.exec(constraints_sql)
                    iris_constraints = list(result)

                    logger.info(f"Found {len(iris_constraints)} constraints in IRIS", constraints=iris_constraints[:5])

                    # Prisma expects: namespace, table_name, constraint_name, constraint_type, constraint_definition
                    # Also need column info for primary key constraints
                    columns = [
                        {"name": "namespace", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "table_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "constraint_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "constraint_type", "type_oid": 18, "type_size": 1, "type_modifier": -1, "format_code": 0},  # char
                        {"name": "constraint_definition", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},  # text
                        {"name": "column_names", "type_oid": 1009, "type_size": -1, "type_modifier": -1, "format_code": 0},  # text[]
                    ]

                    # Map IRIS constraint types to PostgreSQL single-char types
                    type_map = {
                        'PRIMARY KEY': 'p',
                        'UNIQUE': 'u',
                        'FOREIGN KEY': 'f',
                        'CHECK': 'c',
                    }

                    rows = []
                    for constraint in iris_constraints:
                        namespace = constraint[0]
                        table_name = constraint[1].lower()
                        constraint_name = constraint[2].lower()
                        iris_type = constraint[3]
                        pg_type = type_map.get(iris_type, 'c')

                        # Get columns for this constraint
                        col_sql = f"""
                            SELECT COLUMN_NAME
                            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                            WHERE CONSTRAINT_NAME = '{constraint[2]}'
                            ORDER BY ORDINAL_POSITION
                        """
                        try:
                            col_result = iris.sql.exec(col_sql)
                            col_names = [r[0].lower() for r in col_result]
                            col_names_str = '{' + ','.join(col_names) + '}'  # PostgreSQL array format
                        except Exception:
                            col_names = []
                            col_names_str = '{}'

                        # Build constraint definition
                        if pg_type == 'p':
                            definition = f"PRIMARY KEY ({', '.join(col_names)})"
                        elif pg_type == 'u':
                            definition = f"UNIQUE ({', '.join(col_names)})"
                        else:
                            definition = ""

                        rows.append((
                            namespace,
                            table_name,
                            constraint_name,
                            pg_type,
                            definition,
                            col_names_str,
                        ))

                    logger.info(f"Returning {len(rows)} constraints to Prisma")

                    return {
                        "success": True,
                        "rows": rows,
                        "columns": columns,
                        "row_count": len(rows),
                        "command": "SELECT",
                        "command_tag": f"SELECT {len(rows)}",
                    }

                except Exception as e:
                    logger.error(f"pg_constraint query failed: {e}", error=str(e))
                    # Fall through to empty result
                    columns = [
                        {"name": "namespace", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "table_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "constraint_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "constraint_type", "type_oid": 18, "type_size": 1, "type_modifier": -1, "format_code": 0},
                        {"name": "constraint_definition", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},
                    ]
                    return {
                        "success": True,
                        "rows": [],
                        "columns": columns,
                        "row_count": 0,
                        "command": "SELECT",
                        "command_tag": "SELECT 0",
                    }

            # INFORMATION_SCHEMA.SEQUENCES - Return empty sequence information for Prisma
            # Prisma queries sequences using PostgreSQL-style syntax with colons
            # IRIS interprets : as host variable prefix, so we intercept this
            if "INFORMATION_SCHEMA.SEQUENCES" in sql_upper or ("SEQUENCE_NAME" in sql_upper and "SEQUENCE_SCHEMA" in sql_upper):
                logger.info(
                    "Intercepting sequence query (returning empty - IRIS sequences not exposed)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Return empty result for sequence queries
                columns = [
                    {"name": "sequence_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                    {"name": "namespace", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                    {"name": "start_value", "type_oid": 20, "type_size": 8, "type_modifier": -1, "format_code": 0},  # bigint
                    {"name": "min_value", "type_oid": 20, "type_size": 8, "type_modifier": -1, "format_code": 0},
                    {"name": "max_value", "type_oid": 20, "type_size": 8, "type_modifier": -1, "format_code": 0},
                    {"name": "increment_by", "type_oid": 20, "type_size": 8, "type_modifier": -1, "format_code": 0},
                    {"name": "cycle", "type_oid": 16, "type_size": 1, "type_modifier": -1, "format_code": 0},  # bool
                    {"name": "cache_size", "type_oid": 20, "type_size": 8, "type_modifier": -1, "format_code": 0},
                ]

                return {
                    "success": True,
                    "rows": [],  # No sequences to report
                    "columns": columns,
                    "row_count": 0,
                    "command": "SELECT",
                    "command_tag": "SELECT 0",
                }

            # pg_extension - Return empty extension information for Prisma introspection
            # Prisma queries pg_extension for installed PostgreSQL extensions
            # IRIS doesn't have PostgreSQL-style extensions, return empty
            if "PG_EXTENSION" in sql_upper:
                logger.info(
                    "Intercepting pg_extension query (returning empty - IRIS has no PG extensions)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Return empty result with minimal columns for extension queries
                columns = [
                    {"name": "oid", "type_oid": 26, "type_size": 4, "type_modifier": -1, "format_code": 0},
                    {"name": "extname", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                    {"name": "extversion", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},
                ]

                return {
                    "success": True,
                    "rows": [],  # No extensions installed
                    "columns": columns,
                    "row_count": 0,
                    "command": "SELECT",
                    "command_tag": "SELECT 0",
                }

            # pg_proc - Return empty function/procedure information for Prisma introspection
            # Prisma queries pg_proc for stored procedures and functions
            # IRIS doesn't expose stored procedures via pg_proc, so return empty
            if "PG_PROC" in sql_upper:
                logger.info(
                    "Intercepting pg_proc query (returning empty - IRIS procedures not exposed)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Return empty result with minimal columns for procedure queries
                columns = [
                    {"name": "oid", "type_oid": 26, "type_size": 4, "type_modifier": -1, "format_code": 0},
                    {"name": "proname", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                    {"name": "pronamespace", "type_oid": 26, "type_size": 4, "type_modifier": -1, "format_code": 0},
                ]

                return {
                    "success": True,
                    "rows": [],  # No procedures to report
                    "columns": columns,
                    "row_count": 0,
                    "command": "SELECT",
                    "command_tag": "SELECT 0",
                }

            # pg_views - Return empty view information for Prisma introspection
            # Prisma sends queries like:
            # SELECT views.viewname AS view_name, views.definition AS view_sql, views.schemaname AS namespace, ...
            # FROM pg_catalog.pg_views views INNER JOIN pg_catalog.pg_namespace ...
            # CRITICAL: Must check BEFORE pg_class since view queries may JOIN with pg_class
            if "PG_VIEWS" in sql_upper:
                logger.info(
                    "Intercepting pg_views query (returning empty - IRIS views not exposed)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Return empty result with correct columns for view queries
                # Prisma expects: view_name, view_sql, namespace, description
                columns = [
                    {"name": "view_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                    {"name": "view_sql", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},  # text
                    {"name": "namespace", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                    {"name": "description", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},  # text
                ]

                return {
                    "success": True,
                    "rows": [],  # No views to report
                    "columns": columns,
                    "row_count": 0,
                    "command": "SELECT",
                    "command_tag": "SELECT 0",
                }

            # pg_class - Return table information from IRIS INFORMATION_SCHEMA
            # Prisma sends complex queries like:
            # SELECT tbl.relname AS table_name, namespace.nspname as namespace, ...
            # FROM pg_class AS tbl JOIN pg_namespace AS namespace ON ...
            # WHERE namespace.nspname = ANY($1) AND tbl.relkind IN ('r', 'p')
            # CRITICAL: Only intercept simple pg_class table queries, not JOINs with pg_attribute for column info
            is_simple_pg_class = (
                "PG_CLASS" in sql_upper and
                "PG_ATTRIBUTE" not in sql_upper and  # Not a column info query
                "ATT.ATTTYPID" not in sql_upper and  # Not a column type query
                "INFO.COLUMN_NAME" not in sql_upper  # Not an information_schema column query
            )

            if is_simple_pg_class:
                logger.info(
                    "Intercepting pg_class query (returning tables from INFORMATION_SCHEMA)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                try:
                    import iris

                    # Query INFORMATION_SCHEMA for table list
                    tables_sql = """
                        SELECT TABLE_NAME, TABLE_SCHEMA
                        FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_TYPE = 'BASE TABLE'
                        ORDER BY TABLE_SCHEMA, TABLE_NAME
                    """
                    result = iris.sql.exec(tables_sql)
                    iris_tables = [(row[0], row[1]) for row in result]

                    logger.info(f"Found {len(iris_tables)} tables in IRIS", tables=iris_tables[:10])

                    # Map IRIS schemas to PostgreSQL namespaces
                    # SQLUser -> public (Prisma expects 'public')
                    schema_mapping = {
                        'sqluser': 'public',
                        'SQLUser': 'public',
                        '%Library': 'pg_catalog',
                        'INFORMATION_SCHEMA': 'information_schema',
                    }

                    # CRITICAL: Create OIDGenerator for table OIDs
                    # Prisma needs OIDs to JOIN pg_class with pg_attribute for column info
                    oid_gen = OIDGenerator()

                    # Build pg_class-like response based on Prisma's expected columns
                    # NOTE: Only return columns that Prisma's query requests - do NOT add OID
                    # Prisma's query: SELECT tbl.relname AS table_name, namespace.nspname as namespace, ...
                    columns = [
                        {"name": "table_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "namespace", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "is_partition", "type_oid": 16, "type_size": 1, "type_modifier": -1, "format_code": 0},
                        {"name": "has_subclass", "type_oid": 16, "type_size": 1, "type_modifier": -1, "format_code": 0},
                        {"name": "has_row_level_security", "type_oid": 16, "type_size": 1, "type_modifier": -1, "format_code": 0},
                        {"name": "reloptions", "type_oid": 1009, "type_size": -1, "type_modifier": -1, "format_code": 0},  # text[]
                        {"name": "description", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},
                    ]

                    # Filter by namespace if params contain schema filter
                    target_namespaces = ['public']  # Default to public
                    if params and len(params) > 0 and params[0] is not None:
                        param0 = params[0]
                        if isinstance(param0, list):
                            target_namespaces = [n.lower() for n in param0]
                        elif isinstance(param0, str):
                            # Parse array string
                            if param0.startswith('[') and param0.endswith(']'):
                                inner = param0[1:-1].strip()
                                if inner:
                                    target_namespaces = [s.strip().strip('"').strip("'").lower() for s in inner.split(',')]
                            elif param0.startswith('{') and param0.endswith('}'):
                                inner = param0[1:-1]
                                if inner:
                                    target_namespaces = [s.strip().strip('"').lower() for s in inner.split(',')]
                            else:
                                target_namespaces = [param0.lower()]

                    logger.info(f"pg_class: filtering for namespaces {target_namespaces}")

                    rows = []
                    for table_name, table_schema in iris_tables:
                        # Map IRIS schema to PostgreSQL namespace
                        pg_namespace = schema_mapping.get(table_schema, table_schema.lower())

                        # Only include tables in target namespaces
                        if pg_namespace in target_namespaces:
                            # Return only the 7 columns that Prisma's query requests
                            rows.append((
                                table_name.lower(),  # table_name (lowercase for PostgreSQL)
                                pg_namespace,        # namespace
                                False,               # is_partition
                                False,               # has_subclass
                                False,               # has_row_level_security
                                None,                # reloptions (array)
                                None,                # description
                            ))

                    logger.info(f"pg_class: returning {len(rows)} tables for namespaces {target_namespaces}")

                    return {
                        "success": True,
                        "rows": rows,
                        "columns": columns,
                        "row_count": len(rows),
                        "command": "SELECT",
                        "command_tag": f"SELECT {len(rows)}",
                    }

                except Exception as e:
                    logger.error(f"pg_class interception failed: {e}", error=str(e))
                    # Fall through to normal execution (which will fail, but gives proper error)

            # Prisma column info query - Return IRIS column metadata from INFORMATION_SCHEMA
            # Prisma sends:
            # SELECT oid.namespace, info.table_name, info.column_name, format_type(att.atttypid, att.atttypmod) as formatted_type, ...
            # FROM information_schema.columns info JOIN pg_attribute att ON ...
            # WHERE namespace = ANY($1) AND table_name = ANY($2)
            # CRITICAL: Must be BEFORE generic pg_attribute handler
            if "INFO.TABLE_NAME" in sql_upper and "INFO.COLUMN_NAME" in sql_upper and "FORMAT_TYPE" in sql_upper:
                logger.info(
                    "Intercepting Prisma column info query (returning IRIS columns from INFORMATION_SCHEMA)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                try:
                    import iris

                    # Query INFORMATION_SCHEMA.COLUMNS for column metadata
                    # Filter by SQLUser schema (maps to public)
                    columns_sql = """
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
                        WHERE TABLE_SCHEMA = 'SQLUser'
                        ORDER BY TABLE_NAME, ORDINAL_POSITION
                    """
                    result = iris.sql.exec(columns_sql)
                    iris_columns = list(result)

                    logger.info(f"Found {len(iris_columns)} columns in IRIS", column_count=len(iris_columns))

                    # Type mapping is now configurable via type_mapping module
                    # Uses get_type_mapping() which can be configured via:
                    # - Environment variables (PGWIRE_TYPE_MAP_<TYPE>=pg_type:udt_name:oid)
                    # - Configuration file (type_mapping.json)
                    # - Programmatic API (configure_type_mapping())
                    #
                    # CRITICAL: Prisma uses udt_name (e.g., 'int4', 'varchar') for type mapping
                    # data_type is the SQL standard name, udt_name is the PostgreSQL internal name

                    # Build response with Prisma's expected columns
                    # Prisma expects: namespace, table_name, column_name, data_type, full_data_type,
                    # formatted_type, udt_name, numeric_precision, numeric_scale, max_length, is_nullable,
                    # column_default, ordinal_position, is_identity, is_generated
                    # CRITICAL: udt_name is used by Prisma for type mapping (int4 → Int, varchar → String)
                    response_columns = [
                        {"name": "namespace", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "table_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "column_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},
                        {"name": "data_type", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},  # SQL standard name (e.g., 'integer')
                        {"name": "full_data_type", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},  # Full type with precision
                        {"name": "formatted_type", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},
                        {"name": "udt_name", "type_oid": 19, "type_size": 64, "type_modifier": -1, "format_code": 0},  # PostgreSQL internal name (e.g., 'int4')
                        {"name": "numeric_precision", "type_oid": 23, "type_size": 4, "type_modifier": -1, "format_code": 0},
                        {"name": "numeric_scale", "type_oid": 23, "type_size": 4, "type_modifier": -1, "format_code": 0},
                        {"name": "character_maximum_length", "type_oid": 23, "type_size": 4, "type_modifier": -1, "format_code": 0},  # Prisma expects this name
                        {"name": "is_nullable", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},
                        {"name": "column_default", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},
                        {"name": "ordinal_position", "type_oid": 23, "type_size": 4, "type_modifier": -1, "format_code": 0},
                        {"name": "is_identity", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},
                        {"name": "is_generated", "type_oid": 25, "type_size": -1, "type_modifier": -1, "format_code": 0},
                    ]

                    rows = []
                    for col in iris_columns:
                        namespace = col[0]
                        table_name = col[1].lower()  # Lowercase for PostgreSQL
                        column_name = col[2].lower()
                        iris_data_type = col[3].upper() if col[3] else 'VARCHAR'
                        # Convert to int, handling strings and None
                        numeric_precision = int(col[4]) if col[4] and str(col[4]).isdigit() else 0
                        numeric_scale = int(col[5]) if col[5] and str(col[5]).isdigit() else 0
                        max_length = int(col[6]) if col[6] and str(col[6]).isdigit() else 0
                        is_nullable = 'YES' if col[7] == 'YES' else 'NO'
                        column_default = col[8]
                        ordinal_position = int(col[9]) if col[9] and str(col[9]).isdigit() else 0

                        # Map to PostgreSQL format_type and udt_name using configurable type mapping
                        base_type = iris_data_type.split('(')[0]
                        pg_type, udt_name, _type_oid = get_type_mapping(base_type)

                        # Build formatted_type with precision/length
                        if max_length > 0 and pg_type in ('character varying', 'character'):
                            formatted_type = f"{pg_type}({max_length})"
                        elif numeric_precision > 0 and pg_type == 'numeric':
                            formatted_type = f"numeric({numeric_precision},{numeric_scale})"
                        else:
                            formatted_type = pg_type

                        # data_type is the base PostgreSQL type name (lowercase)
                        data_type = pg_type
                        # full_data_type includes precision/scale (same as formatted_type for Prisma)
                        full_data_type = formatted_type

                        # Clean up column_default - remove IRIS-specific syntax
                        # Prisma expects NULL for no default, or valid SQL expression
                        clean_default = None
                        if column_default:
                            default_upper = str(column_default).upper()
                            # Skip IRIS internal defaults that aren't meaningful to Prisma
                            if 'AUTOINCREMENT' in default_upper or 'ROWVERSION' in default_upper:
                                clean_default = None  # Will be handled by @id or identity
                            elif default_upper in ('NULL', ''):
                                clean_default = None
                            else:
                                clean_default = column_default

                        # Detect identity columns (IRIS uses AUTOINCREMENT)
                        is_identity = 'NO'
                        if column_default and 'AUTOINCREMENT' in str(column_default).upper():
                            is_identity = 'YES'  # Prisma uses this to detect @id

                        rows.append((
                            namespace,
                            table_name,
                            column_name,
                            data_type,  # SQL standard name (e.g., 'integer')
                            full_data_type,  # Full type with precision
                            formatted_type,
                            udt_name,  # PostgreSQL internal name (e.g., 'int4') - CRITICAL for Prisma type mapping
                            numeric_precision,
                            numeric_scale,
                            max_length,  # character_maximum_length
                            is_nullable,
                            clean_default,
                            ordinal_position,
                            is_identity,
                            'NEVER',  # is_generated
                        ))

                    logger.info(f"Returning {len(rows)} column definitions to Prisma")

                    return {
                        "success": True,
                        "rows": rows,
                        "columns": response_columns,
                        "row_count": len(rows),
                        "command": "SELECT",
                        "command_tag": f"SELECT {len(rows)}",
                    }

                except Exception as e:
                    logger.error(f"Prisma column info query failed: {e}", error=str(e))
                    # Fall through to generic handler

            # Composite types queries (pg_attribute, att.attname) - Return empty with column metadata
            # Npgsql queries for composite type definitions, but IRIS doesn't have these
            # CRITICAL: PostgreSQL protocol requires RowDescription even for 0-row results
            if (
                "PG_ATTRIBUTE" in sql_upper
                or "ATT.ATTNAME" in sql_upper
                or "ATT.ATTTYPID" in sql_upper
            ):
                logger.info(
                    "Intercepting composite types query (returning empty with column metadata)",
                    sql_preview=sql[:150],
                    session_id=session_id,
                )
                # Define expected columns for composite types query (oid, attname, atttypid)
                columns = [
                    {
                        "name": "oid",
                        "type_oid": 26,
                        "type_size": 4,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "attname",
                        "type_oid": 19,
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "atttypid",
                        "type_oid": 26,
                        "type_size": 4,
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

            # pg_type - Return standard PostgreSQL types for Npgsql type registry
            # CRITICAL FIX: Parse SELECT clause to return columns in requested order
            # Npgsql sends different queries with different column structures
            if "PG_TYPE" in sql_upper or "PG_CATALOG" in sql_upper:
                logger.info(
                    "Intercepting pg_type query (parsing SELECT clause for column order)",
                    sql_preview=sql[:150],
                    session_id=session_id,
                )

                # Define all available columns with their data
                # nspname: namespace name ('pg_catalog' for built-in types)
                # oid: type OID (unique identifier)
                # typname: type name (e.g., 'int4', 'text', 'bool')
                # typtype: type category ('b'=base, 'c'=composite, 'e'=enum, etc.)
                # typnotnull: always False for base types
                # elemtypoid: 0 for non-array types, array element type OID for array types
                available_columns = {
                    "nspname": {
                        "type_oid": 19,
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    "oid": {"type_oid": 26, "type_size": 4, "type_modifier": -1, "format_code": 0},
                    "typname": {
                        "type_oid": 19,
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    "typtype": {
                        "type_oid": 18,
                        "type_size": 1,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    "typnotnull": {
                        "type_oid": 16,
                        "type_size": 1,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    "elemtypoid": {
                        "type_oid": 26,
                        "type_size": 4,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                }

                # Base type data
                base_types = {
                    "nspname": "pg_catalog",
                    "oid": [
                        16,
                        17,
                        20,
                        21,
                        23,
                        25,
                        700,
                        701,
                        1042,
                        1043,
                        1082,
                        1083,
                        1114,
                        1184,
                        1560,
                        1700,
                        16388,
                    ],
                    "typname": [
                        "bool",
                        "bytea",
                        "int8",
                        "int2",
                        "int4",
                        "text",
                        "float4",
                        "float8",
                        "bpchar",
                        "varchar",
                        "date",
                        "time",
                        "timestamp",
                        "timestamptz",
                        "bit",
                        "numeric",
                        "vector",
                    ],
                    "typtype": "b",
                    "typnotnull": False,
                    "elemtypoid": 0,
                }

                # Parse SELECT clause to extract requested columns
                # Extract text between SELECT and FROM
                import re

                select_match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
                if not select_match:
                    # Fallback to default 6-column structure
                    logger.warning(
                        "Could not parse SELECT clause, using default 6-column structure"
                    )
                    requested_columns = [
                        "nspname",
                        "oid",
                        "typname",
                        "typtype",
                        "typnotnull",
                        "elemtypoid",
                    ]
                    column_aliases = {}
                else:
                    select_clause = select_match.group(1)
                    # Extract column names (handle aliases like "t.oid", "ns.nspname")
                    # Remove table prefixes (ns., t., typ., att., etc.)
                    column_parts = [col.strip() for col in select_clause.split(",")]
                    requested_columns = []
                    column_aliases = {}  # Maps source column to alias
                    for part in column_parts:
                        # Extract column name after dot (if exists) or use whole part
                        if "." in part:
                            col_name = part.split(".")[-1].strip()
                        else:
                            col_name = part.strip()

                        # Handle AS aliases - extract both source column and alias
                        alias = None
                        if " AS " in col_name.upper():
                            parts = col_name.split()
                            as_idx = next(i for i, p in enumerate(parts) if p.upper() == "AS")
                            col_name = parts[0]  # Source column name
                            alias = parts[as_idx + 1] if as_idx + 1 < len(parts) else None

                        # Check if this is a known column
                        if col_name in available_columns:
                            requested_columns.append(col_name)
                            if alias:
                                column_aliases[col_name] = alias
                        else:
                            logger.warning(
                                f"Unknown column '{col_name}' in SELECT clause, skipping"
                            )

                    if not requested_columns:
                        # Fallback if no known columns found
                        logger.warning(
                            "No recognized columns in SELECT clause, using default 6-column structure"
                        )
                        requested_columns = [
                            "nspname",
                            "oid",
                            "typname",
                            "typtype",
                            "typnotnull",
                            "elemtypoid",
                        ]
                        column_aliases = {}

                logger.info(f"🔍 Parsed SELECT clause: requesting columns {requested_columns}")

                # Parse namespace filter from WHERE clause (nspname = ANY(?))
                # Prisma sends: WHERE nspname = ANY($1) with params=['public']
                requested_namespaces = None  # None means no filter, return all
                if params and len(params) > 0 and params[0] is not None:
                    # Parse namespace parameter similar to pg_namespace handler
                    filter_names = []
                    param0 = params[0]

                    if isinstance(param0, list):
                        filter_names = param0
                    elif isinstance(param0, str):
                        import json
                        try:
                            parsed = json.loads(param0)
                            if isinstance(parsed, list):
                                filter_names = parsed
                            else:
                                filter_names = [str(parsed)]
                        except json.JSONDecodeError:
                            # Handle PostgreSQL array format: {public,pg_catalog}
                            if param0.startswith('{') and param0.endswith('}'):
                                inner = param0[1:-1]
                                if inner:
                                    filter_names = [s.strip().strip('"') for s in inner.split(',')]
                            # Handle Python-like array format: ['public']
                            elif param0.startswith('[') and param0.endswith(']'):
                                inner = param0[1:-1].strip()
                                if inner:
                                    filter_names = [s.strip().strip('"').strip("'") for s in inner.split(',')]
                            elif param0 == '[]' or param0 == '{}':
                                filter_names = []
                            else:
                                filter_names = [param0]
                    else:
                        filter_names = [str(param0)]

                    if filter_names:
                        requested_namespaces = [n.lower() for n in filter_names if n]
                        logger.info(f"🔍 pg_type: filtering by namespaces {requested_namespaces}")

                # Check if pg_catalog is in requested namespaces
                # All built-in types are in pg_catalog namespace
                include_types = True
                if requested_namespaces is not None:
                    if "pg_catalog" not in requested_namespaces:
                        # Only return types if pg_catalog is requested
                        include_types = False
                        logger.info(f"🔍 pg_type: pg_catalog not in {requested_namespaces}, returning 0 rows")

                # Build rows based on requested column order
                rows = []
                if include_types:
                    for i in range(len(base_types["oid"])):
                        row = []
                        for col_name in requested_columns:
                            if col_name in ["oid", "typname"]:
                                # These are lists (one value per type)
                                row.append(base_types[col_name][i])
                            else:
                                # These are scalars (same for all types)
                                row.append(base_types[col_name])
                        rows.append(tuple(row))

                # Build column metadata in requested order (use aliases if defined)
                columns = []
                for col_name in requested_columns:
                    col_meta = available_columns[col_name].copy()
                    # Use alias if defined, otherwise use source column name
                    col_meta["name"] = column_aliases.get(col_name, col_name)
                    columns.append(col_meta)

                return {
                    "success": True,
                    "rows": rows,
                    "columns": columns,
                    "row_count": len(rows),
                    "command": "SELECT",
                    "command_tag": f"SELECT {len(rows)}",
                }

            try:
                # PROFILING: Track detailed timing
                t_start_total = time.perf_counter()

                # Get or create connection
                self._get_iris_connection()

                # Feature 022: Apply PostgreSQL→IRIS transaction verb translation
                # CRITICAL: Transaction translation MUST occur BEFORE Feature 021 normalization (FR-010)
                transaction_translator = TransactionTranslator()
                transaction_translated_sql = transaction_translator.translate_transaction_command(
                    sql
                )

                # Feature 021: Apply PostgreSQL→IRIS SQL normalization
                # CRITICAL: Normalization MUST occur BEFORE vector optimization (FR-012)
                translator = SQLTranslator()
                normalized_sql = translator.normalize_sql(
                    transaction_translated_sql, execution_path="direct"
                )

                # Log transaction translation metrics
                txn_metrics = transaction_translator.get_translation_metrics()
                logger.info(
                    "Transaction verb translation applied",
                    total_translations=txn_metrics["total_translations"],
                    avg_time_ms=txn_metrics["avg_translation_time_ms"],
                    sla_violations=txn_metrics["sla_violations"],
                    sql_original_preview=sql[:100],
                    sql_translated_preview=transaction_translated_sql[:100],
                    session_id=session_id,
                )

                # Log normalization metrics
                norm_metrics = translator.get_normalization_metrics()
                logger.info(
                    "SQL normalization applied",
                    identifiers_normalized=norm_metrics["identifier_count"],
                    dates_translated=norm_metrics["date_literal_count"],
                    normalization_time_ms=norm_metrics["normalization_time_ms"],
                    sla_violated=norm_metrics["sla_violated"],
                    sql_before_preview=transaction_translated_sql[:100],
                    sql_after_preview=normalized_sql[:100],
                    session_id=session_id,
                )

                if norm_metrics["sla_violated"]:
                    logger.warning(
                        "SQL normalization exceeded 5ms SLA",
                        normalization_time_ms=norm_metrics["normalization_time_ms"],
                        session_id=session_id,
                    )

                # Apply vector query optimization (convert parameterized vectors to literals)
                # Use normalized_sql as input instead of original sql
                optimized_sql = normalized_sql
                optimized_params = params
                optimization_applied = False

                # PROFILING: Optimization timing
                t_opt_start = time.perf_counter()

                try:
                    from .vector_optimizer import optimize_vector_query

                    logger.debug(
                        "Vector optimizer: checking query",
                        sql_preview=normalized_sql[:200],
                        param_count=len(params) if params else 0,
                        session_id=session_id,
                    )

                    # CRITICAL: Pass normalized_sql (not original sql) per FR-012
                    optimized_sql, optimized_params = optimize_vector_query(normalized_sql, params)

                    optimization_applied = (optimized_sql != normalized_sql) or (
                        optimized_params != params
                    )

                    if optimization_applied:
                        logger.info(
                            "Vector optimization applied",
                            sql_changed=(optimized_sql != normalized_sql),
                            params_changed=(optimized_params != params),
                            params_before=len(params) if params else 0,
                            params_after=len(optimized_params) if optimized_params else 0,
                            optimized_sql_preview=optimized_sql[:200],
                            session_id=session_id,
                        )
                    else:
                        logger.debug(
                            "Vector optimization not applicable",
                            reason="No vector patterns found or params unchanged",
                            session_id=session_id,
                        )

                except ImportError as e:
                    logger.warning(
                        "Vector optimizer not available", error=str(e), session_id=session_id
                    )
                except Exception as opt_error:
                    logger.warning(
                        "Vector optimization failed, using normalized query",
                        error=str(opt_error),
                        session_id=session_id,
                    )
                    optimized_sql, optimized_params = normalized_sql, params

                # PROFILING: Optimization complete
                t_opt_elapsed = (time.perf_counter() - t_opt_start) * 1000

                # POSTGRESQL COMPATIBILITY: Handle SHOW commands that IRIS doesn't support
                # Intercept and return fake results for PostgreSQL compatibility
                sql_upper_stripped = optimized_sql.strip().upper()
                if sql_upper_stripped.startswith("SHOW "):
                    logger.info(
                        "Intercepting SHOW command (PostgreSQL compatibility shim)",
                        sql=optimized_sql[:100],
                        session_id=session_id,
                    )
                    return self._handle_show_command(optimized_sql, session_id)

                # Execute query with performance tracking
                start_time = time.perf_counter()

                # CRITICAL: Strip trailing semicolon when using parameters
                # IRIS cannot handle "SELECT ... WHERE id = ?;" (fails with SQLCODE=-52)
                # but works fine with "SELECT ... WHERE id = ?" (no semicolon)
                if optimized_params and optimized_sql.rstrip().endswith(";"):
                    original_len = len(optimized_sql)
                    optimized_sql = optimized_sql.rstrip().rstrip(";")
                    logger.info(
                        "Removed trailing semicolon for parameterized query",
                        original_sql_len=original_len,
                        new_sql_len=len(optimized_sql),
                        sql_preview=optimized_sql[:80],
                        param_count=len(optimized_params),
                        session_id=session_id,
                    )

                # CRITICAL: Translate PostgreSQL schema names to IRIS schema names
                # Prisma sends: "public"."tablename" but IRIS needs: SQLUser.TABLENAME
                import re
                import datetime as dt
                original_sql_for_log = optimized_sql[:80]

                # CRITICAL: Convert PostgreSQL timestamp microseconds to IRIS timestamp strings
                # Prisma sends timestamps as int64 microseconds since 2000-01-01 (PostgreSQL epoch)
                # IRIS expects timestamps as ISO 8601 strings
                if optimized_params and re.search(r'\bINSERT\b', optimized_sql, re.IGNORECASE):
                    # Check for timestamp-like values (large integers that could be microseconds)
                    # PostgreSQL epoch is 2000-01-01, so timestamps from 2020-2030 are roughly:
                    # 20 years * 365 * 24 * 60 * 60 * 1_000_000 = ~630_720_000_000_000
                    # 30 years = ~946_080_000_000_000
                    PG_EPOCH = dt.datetime(2000, 1, 1, 0, 0, 0)
                    MIN_TIMESTAMP = 500_000_000_000_000  # ~2015
                    MAX_TIMESTAMP = 1_500_000_000_000_000  # ~2047

                    new_params = list(optimized_params)
                    for i, param in enumerate(new_params):
                        if isinstance(param, int) and MIN_TIMESTAMP < param < MAX_TIMESTAMP:
                            # This looks like a PostgreSQL timestamp in microseconds
                            try:
                                timestamp_obj = PG_EPOCH + dt.timedelta(microseconds=param)
                                new_params[i] = timestamp_obj.strftime("%Y-%m-%d %H:%M:%S.%f")
                                logger.info(
                                    "Converted PostgreSQL timestamp to IRIS format",
                                    param_index=i,
                                    original_value=param,
                                    converted_value=new_params[i],
                                    session_id=session_id,
                                )
                            except (ValueError, OverflowError) as e:
                                logger.warning(
                                    "Failed to convert timestamp parameter",
                                    param_index=i,
                                    value=param,
                                    error=str(e),
                                    session_id=session_id,
                                )
                    optimized_params = tuple(new_params)
                # Replace "public"."tablename" with SQLUser."tablename" (preserve quotes on tablename)
                optimized_sql = re.sub(
                    r'"public"\s*\.\s*"(\w+)"',
                    r'SQLUser."\1"',
                    optimized_sql,
                    flags=re.IGNORECASE
                )
                # Also handle public."tablename" without quotes on public
                optimized_sql = re.sub(
                    r'\bpublic\s*\.\s*"(\w+)"',
                    r'SQLUser."\1"',
                    optimized_sql,
                    flags=re.IGNORECASE
                )
                if original_sql_for_log != optimized_sql[:80]:
                    logger.info(
                        "Schema translation applied: public -> SQLUser",
                        original_preview=original_sql_for_log,
                        translated_preview=optimized_sql[:80],
                        session_id=session_id,
                    )

                # CRITICAL: Handle INSERT/UPDATE/DELETE...RETURNING (IRIS doesn't support RETURNING)
                # Prisma sends: INSERT INTO table (cols) VALUES (vals) RETURNING col1, col2, ...
                #           or: UPDATE table SET ... WHERE ... RETURNING col1, col2, ...
                #           or: DELETE FROM table WHERE ... RETURNING col1, col2, ...
                # We need to: 1) Strip RETURNING, 2) Execute statement, 3) Return the affected row(s)
                returning_columns = None
                returning_table = None
                returning_where_clause = None  # For UPDATE/DELETE
                returning_operation = None  # 'INSERT', 'UPDATE', or 'DELETE'
                if re.search(r'\bRETURNING\b', optimized_sql, re.IGNORECASE):
                    # Extract RETURNING columns
                    returning_match = re.search(
                        r'\bRETURNING\s+(.+)$',
                        optimized_sql,
                        re.IGNORECASE | re.DOTALL
                    )
                    if returning_match:
                        returning_clause = returning_match.group(1).strip()
                        # Parse column names from RETURNING clause
                        # Format: "schema"."table"."col1", "schema"."table"."col2", ...
                        # Or just: col1, col2, ...
                        raw_cols = [c.strip() for c in returning_clause.split(',')]
                        returning_columns = []
                        for col in raw_cols:
                            # Extract just the column name (last part after dots)
                            col_match = re.search(r'"?(\w+)"?\s*$', col)
                            if col_match:
                                returning_columns.append(col_match.group(1))

                        # Determine operation type and extract table/where clause
                        sql_upper = optimized_sql.upper()
                        if sql_upper.strip().startswith('INSERT'):
                            returning_operation = 'INSERT'
                            # Extract table name from INSERT INTO clause
                            table_match = re.search(
                                r'INSERT\s+INTO\s+(?:SQLUser\s*\.\s*)?"?(\w+)"?',
                                optimized_sql,
                                re.IGNORECASE
                            )
                            if table_match:
                                returning_table = table_match.group(1)
                        elif sql_upper.strip().startswith('UPDATE'):
                            returning_operation = 'UPDATE'
                            # Extract table name from UPDATE clause
                            table_match = re.search(
                                r'UPDATE\s+(?:SQLUser\s*\.\s*)?"?(\w+)"?',
                                optimized_sql,
                                re.IGNORECASE
                            )
                            if table_match:
                                returning_table = table_match.group(1)
                            # Extract WHERE clause (everything between WHERE and RETURNING)
                            where_match = re.search(
                                r'\bWHERE\s+(.+?)\s+RETURNING\b',
                                optimized_sql,
                                re.IGNORECASE | re.DOTALL
                            )
                            if where_match:
                                returning_where_clause = where_match.group(1).strip()
                        elif sql_upper.strip().startswith('DELETE'):
                            returning_operation = 'DELETE'
                            # Extract table name from DELETE FROM clause
                            table_match = re.search(
                                r'DELETE\s+FROM\s+(?:SQLUser\s*\.\s*)?"?(\w+)"?',
                                optimized_sql,
                                re.IGNORECASE
                            )
                            if table_match:
                                returning_table = table_match.group(1)
                            # Extract WHERE clause
                            where_match = re.search(
                                r'\bWHERE\s+(.+?)\s+RETURNING\b',
                                optimized_sql,
                                re.IGNORECASE | re.DOTALL
                            )
                            if where_match:
                                returning_where_clause = where_match.group(1).strip()

                        logger.info(
                            "RETURNING clause detected - will emulate",
                            returning_operation=returning_operation,
                            returning_columns=returning_columns,
                            returning_table=returning_table,
                            returning_where_clause=returning_where_clause[:100] if returning_where_clause else None,
                            session_id=session_id,
                        )

                        # Strip RETURNING clause from SQL
                        optimized_sql = re.sub(
                            r'\s+RETURNING\s+.+$',
                            '',
                            optimized_sql,
                            flags=re.IGNORECASE | re.DOTALL
                        )
                        logger.info(
                            "Stripped RETURNING clause",
                            sql_preview=optimized_sql[:100],
                            session_id=session_id,
                        )

                logger.debug(
                    "Executing IRIS query",
                    sql_preview=optimized_sql[:200],
                    param_count=len(optimized_params) if optimized_params else 0,
                    optimization_applied=optimization_applied,
                    session_id=session_id,
                )

                # Log the actual SQL being sent to IRIS for debugging
                logger.info(
                    "About to execute iris.sql.exec",
                    sql_ends_with_semicolon=optimized_sql.rstrip().endswith(";"),
                    sql_last_20=optimized_sql.rstrip()[-20:],
                    has_params=optimized_params is not None and len(optimized_params) > 0,
                    session_id=session_id,
                )

                # PROFILING: IRIS execution timing
                t_iris_start = time.perf_counter()

                # SPECIAL CASE: DELETE with RETURNING - we need to SELECT BEFORE deleting
                # because after DELETE the row won't exist anymore
                delete_returning_result = None
                if returning_operation == 'DELETE' and returning_columns and returning_table and returning_where_clause:
                    try:
                        col_list = ", ".join([f'"{col}"' for col in returning_columns])
                        # Translate the WHERE clause schema references
                        translated_where = re.sub(
                            r'"public"\s*\.\s*"(\w+)"',
                            r'SQLUser."\1"',
                            returning_where_clause,
                            flags=re.IGNORECASE
                        )
                        translated_where = re.sub(
                            r'\bpublic\s*\.\s*"(\w+)"',
                            r'SQLUser."\1"',
                            translated_where,
                            flags=re.IGNORECASE
                        )
                        select_sql = f'SELECT {col_list} FROM SQLUser."{returning_table}" WHERE {translated_where}'

                        # Count ? placeholders to get params
                        where_param_count = len(re.findall(r'\?', returning_where_clause))
                        if optimized_params and where_param_count > 0:
                            # For DELETE, all params are for WHERE clause
                            where_params = optimized_params[-where_param_count:]
                            logger.info(
                                "Pre-DELETE: Fetching row before deletion",
                                select_sql=select_sql[:200],
                                where_params=where_params,
                                session_id=session_id,
                            )
                            delete_returning_result = iris.sql.exec(select_sql, *where_params)
                        else:
                            delete_returning_result = iris.sql.exec(select_sql)

                        # Materialize the result before DELETE (iterator would be invalid after)
                        delete_returning_rows = list(delete_returning_result)
                        logger.info(
                            "Pre-DELETE: Row captured for RETURNING",
                            row_count=len(delete_returning_rows),
                            session_id=session_id,
                        )
                    except Exception as e:
                        logger.error(
                            "Pre-DELETE SELECT failed",
                            error=str(e),
                            session_id=session_id,
                        )
                        delete_returning_rows = []

                # CRITICAL FIX: Split SQL by semicolons to handle multiple statements
                # IRIS iris.sql.exec() cannot handle "STMT1; STMT2" in a single call
                statements = self._split_sql_statements(optimized_sql)

                if len(statements) > 1:
                    logger.info(
                        "Executing multiple statements",
                        statement_count=len(statements),
                        session_id=session_id,
                    )

                    # Execute all statements except the last (don't capture results)
                    for stmt in statements[:-1]:
                        logger.debug(
                            f"Executing intermediate statement: {stmt[:80]}...",
                            session_id=session_id,
                        )
                        if optimized_params is not None and len(optimized_params) > 0:
                            iris.sql.exec(stmt, *optimized_params)
                        else:
                            iris.sql.exec(stmt)

                    # Execute last statement and capture results
                    last_stmt = statements[-1]
                    logger.debug(
                        f"Executing final statement: {last_stmt[:80]}...", session_id=session_id
                    )
                    if optimized_params is not None and len(optimized_params) > 0:
                        result = iris.sql.exec(last_stmt, *optimized_params)
                    else:
                        result = iris.sql.exec(last_stmt)
                else:
                    # Single statement - execute normally
                    if optimized_params is not None and len(optimized_params) > 0:
                        result = iris.sql.exec(optimized_sql, *optimized_params)
                    else:
                        result = iris.sql.exec(optimized_sql)

                # RETURNING emulation: After INSERT/UPDATE/DELETE, fetch the affected row(s)
                if returning_columns and returning_table and returning_operation:
                    logger.info(
                        f"Emulating RETURNING for {returning_operation}",
                        table=returning_table,
                        columns=returning_columns,
                        operation=returning_operation,
                        session_id=session_id,
                    )
                    try:
                        col_list = ", ".join([f'"{col}"' for col in returning_columns])

                        if returning_operation == 'INSERT':
                            # Get the last inserted ID using LAST_IDENTITY()
                            id_result = iris.sql.exec("SELECT LAST_IDENTITY()")
                            last_id = None
                            for row in id_result:
                                last_id = row[0]
                                break

                            # Handle empty string (LAST_IDENTITY() returns '' for non-IDENTITY tables)
                            if last_id is None or last_id == '' or last_id == 0:
                                # Fallback: use MAX(id) - not ideal for concurrent inserts but works
                                logger.info(
                                    "LAST_IDENTITY() returned empty, falling back to MAX(id)",
                                    last_id_value=repr(last_id),
                                    session_id=session_id,
                                )
                                max_result = iris.sql.exec(f'SELECT MAX("id") FROM SQLUser."{returning_table}"')
                                for row in max_result:
                                    last_id = row[0]
                                    break

                            if last_id is not None and last_id != '' and last_id != 0:
                                # Build SELECT to fetch the inserted row
                                select_sql = f'SELECT {col_list} FROM SQLUser."{returning_table}" WHERE "id" = ?'
                                logger.info(
                                    "Fetching inserted row",
                                    select_sql=select_sql,
                                    last_id=last_id,
                                    session_id=session_id,
                                )
                                result = iris.sql.exec(select_sql, last_id)
                            else:
                                logger.warning(
                                    "Could not determine last inserted ID - RETURNING emulation may fail",
                                    last_id_value=repr(last_id),
                                    session_id=session_id,
                                )

                        elif returning_operation == 'DELETE':
                            # For DELETE, we already captured the row BEFORE deletion
                            # Use the pre-captured delete_returning_rows
                            if delete_returning_rows:
                                logger.info(
                                    "Using pre-captured DELETE RETURNING rows",
                                    row_count=len(delete_returning_rows),
                                    session_id=session_id,
                                )
                                # Create a mock result object that yields the pre-captured rows
                                class MockResult:
                                    def __init__(self, rows):
                                        self._rows = rows
                                        self._meta = None  # No metadata available
                                    def __iter__(self):
                                        return iter(self._rows)
                                result = MockResult(delete_returning_rows)
                            else:
                                logger.warning(
                                    "DELETE RETURNING: No pre-captured rows available",
                                    session_id=session_id,
                                )

                        elif returning_operation == 'UPDATE':
                            # For UPDATE, use the WHERE clause to fetch the affected row(s)
                            if returning_where_clause:
                                # Translate the WHERE clause schema references
                                translated_where = re.sub(
                                    r'"public"\s*\.\s*"(\w+)"',
                                    r'SQLUser."\1"',
                                    returning_where_clause,
                                    flags=re.IGNORECASE
                                )
                                # Also handle unquoted public references
                                translated_where = re.sub(
                                    r'\bpublic\s*\.\s*"(\w+)"',
                                    r'SQLUser."\1"',
                                    translated_where,
                                    flags=re.IGNORECASE
                                )

                                # Build SELECT with the same WHERE clause
                                select_sql = f'SELECT {col_list} FROM SQLUser."{returning_table}" WHERE {translated_where}'

                                logger.info(
                                    f"Fetching UPDATEd row(s) using WHERE clause",
                                    select_sql=select_sql[:200],
                                    param_count=len(optimized_params) if optimized_params else 0,
                                    session_id=session_id,
                                )

                                # For UPDATE, the WHERE clause params are the LAST params
                                # Prisma UPDATE format: UPDATE SET col=$1 WHERE id=$2
                                # Note: By this point, $N placeholders have been converted to ?
                                where_param_count = len(re.findall(r'\?', returning_where_clause))

                                if optimized_params and where_param_count > 0:
                                    # Take the last N params for the WHERE clause
                                    where_params = optimized_params[-where_param_count:]
                                    logger.info(
                                        "Using WHERE clause parameters",
                                        where_param_count=where_param_count,
                                        where_params=where_params,
                                        session_id=session_id,
                                    )

                                    # The SELECT already uses ? placeholders
                                    result = iris.sql.exec(select_sql, *where_params)
                                else:
                                    # No params needed
                                    result = iris.sql.exec(select_sql)
                            else:
                                logger.warning(
                                    "UPDATE without WHERE clause - RETURNING emulation may fail",
                                    session_id=session_id,
                                )
                    except Exception as e:
                        logger.error(
                            "RETURNING emulation failed",
                            error=str(e),
                            operation=returning_operation,
                            session_id=session_id,
                        )

                t_iris_elapsed = (time.perf_counter() - t_iris_start) * 1000
                execution_time = (time.perf_counter() - start_time) * 1000

                # PROFILING: Result processing timing
                t_fetch_start = time.perf_counter()

                # Fetch all results
                rows = []
                columns = []

                # Get column metadata if available
                if hasattr(result, "_meta") and result._meta:
                    for col_info in result._meta:
                        # Get original IRIS column name
                        iris_col_name = col_info.get("name", "")
                        iris_type = col_info.get("type", "VARCHAR")

                        # CRITICAL: Normalize IRIS column names to PostgreSQL conventions
                        # IRIS generates HostVar_1, Expression_1, Aggregate_1 for unnamed columns
                        # PostgreSQL uses ?column?, type names (int4), or function names (count)
                        col_name = self._normalize_iris_column_name(iris_col_name, sql, iris_type)

                        # DEBUG: Log IRIS type for arithmetic expressions
                        logger.info(
                            "🔍 IRIS metadata type discovery",
                            original_column_name=iris_col_name,
                            normalized_column_name=col_name,
                            iris_type=iris_type,
                            col_info=col_info,
                        )

                        # Get PostgreSQL type OID
                        type_oid = self._iris_type_to_pg_oid(iris_type)

                        # CRITICAL FIX: IRIS type code 2 means NUMERIC, but for decimal literals
                        # like 3.14, we want FLOAT8 so node-postgres returns a number, not a string.
                        # Override to FLOAT8 UNLESS explicitly cast to NUMERIC/DECIMAL or INTEGER
                        sql_upper = sql.upper()

                        if iris_type == 2:
                            # Check for explicit casts
                            if "AS INTEGER" in sql_upper or "AS INT" in sql_upper:
                                # Already handled by asyncpg CAST INTEGER fix - don't override
                                pass
                            elif "AS NUMERIC" not in sql_upper and "AS DECIMAL" not in sql_upper:
                                # No explicit NUMERIC/DECIMAL cast → make it FLOAT8
                                logger.info(
                                    "🔧 OVERRIDING IRIS type code 2 (NUMERIC) → OID 701 (FLOAT8)",
                                    column_name=col_name,
                                    original_oid=type_oid,
                                    reason="Decimal literal without explicit NUMERIC/DECIMAL cast",
                                )
                                type_oid = 701  # FLOAT8

                        # CRITICAL FIX: CURRENT_TIMESTAMP returns type 25 (TEXT) in IRIS
                        # but should be type 1114 (TIMESTAMP) for Npgsql compatibility
                        if "CURRENT_TIMESTAMP" in sql_upper and type_oid == 25:
                            logger.info(
                                "🔧 OVERRIDING CURRENT_TIMESTAMP type OID 25 (TEXT) → 1114 (TIMESTAMP)",
                                column_name=col_name,
                                original_oid=type_oid,
                                reason="CURRENT_TIMESTAMP function should return TIMESTAMP type",
                            )
                            type_oid = 1114  # TIMESTAMP

                        columns.append(
                            {
                                "name": col_name,
                                "type_oid": type_oid,
                                "type_size": col_info.get("size", -1),
                                "type_modifier": -1,
                                "format_code": 0,  # Text format
                            }
                        )

                # Fetch rows
                try:
                    for row in result:
                        if isinstance(row, list | tuple):
                            # Normalize IRIS NULL representations to Python None
                            normalized_row = [self._normalize_iris_null(value) for value in row]
                            rows.append(normalized_row)
                        else:
                            # Single value result
                            normalized_value = self._normalize_iris_null(row)
                            rows.append([normalized_value])
                except Exception as fetch_error:
                    logger.warning(
                        "Error fetching IRIS result rows",
                        error=str(fetch_error),
                        session_id=session_id,
                    )

                # If we have rows but no column metadata, discover column info using hybrid approach
                # Implements 3-layer strategy from Perplexity research (2025-11-11):
                # Layer 1: LIMIT 0 metadata discovery (protocol-native)
                # Layer 2: SQL parsing with correlation validation
                # Layer 3: Generic fallback

                logger.info(
                    "🔍 METADATA DISCOVERY CHECK",
                    has_rows=len(rows) > 0,
                    has_columns=len(columns) > 0,
                    will_attempt_discovery=len(rows) > 0 and len(columns) == 0,
                    session_id=session_id,
                )

                if rows and not columns:
                    first_row = rows[0] if rows else []
                    num_columns = len(first_row)

                    # Layer 1: Try LIMIT 0 metadata discovery (BEST - database-native)
                    discovered_aliases = self._discover_metadata_with_limit_zero(sql, session_id)

                    if discovered_aliases and len(discovered_aliases) == num_columns:
                        logger.info(
                            "✅ Layer 1 SUCCESS: LIMIT 0 metadata discovery",
                            aliases=discovered_aliases,
                            column_count=num_columns,
                            session_id=session_id,
                        )
                        # Infer types from first row data
                        for i, alias in enumerate(discovered_aliases):
                            inferred_type = (
                                self._infer_type_from_value(first_row[i])
                                if i < len(first_row)
                                else 25
                            )
                            # CRITICAL: Lowercase column names for PostgreSQL compatibility
                            col_name = alias.lower() if isinstance(alias, str) else alias
                            # Apply same normalization as result._meta path
                            col_name = self._normalize_iris_column_name(
                                col_name, sql, inferred_type
                            )
                            columns.append(
                                {
                                    "name": col_name,
                                    "type_oid": inferred_type,
                                    "type_size": -1,
                                    "type_modifier": -1,
                                    "format_code": 0,
                                }
                            )
                    else:
                        # Layer 1.5: Try table metadata expansion for SELECT * queries (NEW)
                        if discovered_aliases:
                            logger.warning(
                                "Layer 1 count mismatch",
                                discovered=len(discovered_aliases),
                                actual=num_columns,
                                session_id=session_id,
                            )

                        # Check if this is a SELECT * FROM table query
                        table_columns = self._expand_select_star(sql, num_columns, session_id)

                        if table_columns and len(table_columns) == num_columns:
                            logger.info(
                                "✅ Layer 1.5 SUCCESS: Table metadata expansion for SELECT *",
                                aliases=table_columns,
                                column_count=num_columns,
                                session_id=session_id,
                            )
                            # Infer types from first row data
                            for i, col_name in enumerate(table_columns):
                                inferred_type = (
                                    self._infer_type_from_value(first_row[i])
                                    if i < len(first_row)
                                    else 25
                                )
                                # Column names from INFORMATION_SCHEMA are already in correct case
                                columns.append(
                                    {
                                        "name": col_name,
                                        "type_oid": inferred_type,
                                        "type_size": -1,
                                        "type_modifier": -1,
                                        "format_code": 0,
                                    }
                                )
                        else:
                            # Layer 2: Try SQL parsing with correlation (FALLBACK)
                            if table_columns:
                                logger.warning(
                                    "Layer 1.5 count mismatch",
                                    discovered=len(table_columns),
                                    actual=num_columns,
                                    session_id=session_id,
                                )

                            # CRITICAL: Use original SQL to preserve case sensitivity for PostgreSQL clients
                            # psycopg and other PostgreSQL clients expect lowercase column names
                            extracted_aliases = self.alias_extractor.extract_column_aliases(sql)

                            if extracted_aliases and len(extracted_aliases) == num_columns:
                                logger.info(
                                    "✅ Layer 2 SUCCESS: SQL parsing with correlation",
                                    aliases=extracted_aliases,
                                    column_count=num_columns,
                                    session_id=session_id,
                                )
                                # Infer types from first row data
                                for i, alias in enumerate(extracted_aliases):
                                    # CRITICAL: Lowercase column names for PostgreSQL compatibility
                                    col_name = alias.lower() if isinstance(alias, str) else alias
                                    # Apply same normalization as result._meta path
                                    inferred_type = (
                                        self._infer_type_from_value(first_row[i])
                                        if i < len(first_row)
                                        else 25
                                    )

                                    # CRITICAL FIX (2025-11-14): Check for CAST expressions in SQL
                                    # IRIS returns integer 1 for boolean values, but we need OID 16 (bool)
                                    cast_type_oid = self._detect_cast_type_oid(sql, col_name)
                                    if cast_type_oid:
                                        logger.info(
                                            "✅ Detected CAST type override",
                                            column=col_name,
                                            inferred_oid=inferred_type,
                                            cast_oid=cast_type_oid,
                                            session_id=session_id,
                                        )
                                        inferred_type = cast_type_oid

                                    # CRITICAL FIX: CURRENT_TIMESTAMP returns type 25 (TEXT) in IRIS
                                    # but should be type 1114 (TIMESTAMP) for Npgsql compatibility
                                    if "CURRENT_TIMESTAMP" in sql.upper() and inferred_type == 25:
                                        logger.info(
                                            "🔧 OVERRIDING CURRENT_TIMESTAMP type OID 25 (TEXT) → 1114 (TIMESTAMP)",
                                            column_name=col_name,
                                            original_oid=inferred_type,
                                            reason="CURRENT_TIMESTAMP function should return TIMESTAMP type",
                                        )
                                        inferred_type = 1114  # TIMESTAMP

                                    col_name = self._normalize_iris_column_name(
                                        col_name, sql, inferred_type
                                    )
                                    columns.append(
                                        {
                                            "name": col_name,
                                            "type_oid": inferred_type,
                                            "type_size": -1,
                                            "type_modifier": -1,
                                            "format_code": 0,
                                        }
                                    )
                            else:
                                # Layer 3: Generic fallback (LAST RESORT)
                                if extracted_aliases:
                                    logger.warning(
                                        "Layer 2 count mismatch - falling back to generic",
                                        extracted=len(extracted_aliases),
                                        actual=num_columns,
                                        session_id=session_id,
                                    )
                                logger.info(
                                    "⚠️ Layer 3: Using generic column names",
                                    column_count=num_columns,
                                    session_id=session_id,
                                )
                                # Infer types from first row data even with generic names
                                # CRITICAL: For SELECT without FROM (literals), use ?column? for PostgreSQL compatibility
                                sql_upper = sql.upper()
                                use_qcolumn = "SELECT" in sql_upper and "FROM" not in sql_upper

                                for i in range(num_columns):
                                    inferred_type = (
                                        self._infer_type_from_value(first_row[i])
                                        if i < len(first_row)
                                        else 25
                                    )
                                    # Use ?column? for literal queries (SELECT 1, SELECT 'hello')
                                    # Otherwise use generic column1, column2, etc.
                                    col_name = "?column?" if use_qcolumn else f"column{i+1}"
                                    columns.append(
                                        {
                                            "name": col_name,
                                            "type_oid": inferred_type,
                                            "type_size": -1,
                                            "type_modifier": -1,
                                            "format_code": 0,
                                        }
                                    )

                # CRITICAL: For SELECT queries with 0 rows, we MUST generate column metadata
                # PostgreSQL protocol requires RowDescription for ALL SELECT queries
                # JDBC executeQuery() will fail with "No results were returned" without it
                sql_upper = sql.strip().upper()
                if not rows and not columns and sql_upper.startswith("SELECT"):
                    logger.info(
                        "Empty SELECT result - generating column metadata from table structure",
                        sql=sql[:100],
                        session_id=session_id,
                    )

                    # Extract table name from SELECT query (simple parsing)
                    table_name = self._extract_table_name_from_select(sql)

                    if table_name:
                        # Query INFORMATION_SCHEMA for column metadata
                        try:
                            metadata_sql = f"""
                                SELECT column_name, data_type
                                FROM INFORMATION_SCHEMA.COLUMNS
                                WHERE LOWER(table_name) = LOWER('{table_name}')
                                ORDER BY ordinal_position
                            """

                            # Execute metadata query (recursion-safe - won't trigger this path again)
                            metadata_result = iris.sql.exec(metadata_sql)
                            metadata_rows = list(metadata_result)

                            if metadata_rows:
                                for col_name, col_type in metadata_rows:
                                    # Map IRIS types to PostgreSQL OIDs
                                    type_oid = self._map_iris_type_to_oid(col_type)
                                    columns.append(
                                        {
                                            "name": col_name,
                                            "type_oid": type_oid,
                                            "type_size": -1,
                                            "type_modifier": -1,
                                            "format_code": 0,
                                        }
                                    )
                                logger.info(
                                    f"✅ Generated {len(columns)} column metadata from table structure",
                                    table=table_name,
                                    columns=[c["name"] for c in columns],
                                    session_id=session_id,
                                )
                            else:
                                # No metadata found - fall back to generic
                                logger.warning(
                                    f"No column metadata found for table {table_name}, using generic",
                                    session_id=session_id,
                                )
                                columns.append(
                                    {
                                        "name": "column1",
                                        "type_oid": 25,  # TEXT
                                        "type_size": -1,
                                        "type_modifier": -1,
                                        "format_code": 0,
                                    }
                                )
                        except Exception as metadata_error:
                            logger.warning(
                                "Failed to query column metadata",
                                error=str(metadata_error),
                                table=table_name,
                                session_id=session_id,
                            )
                            # Fall back to generic column
                            columns.append(
                                {
                                    "name": "column1",
                                    "type_oid": 25,  # TEXT
                                    "type_size": -1,
                                    "type_modifier": -1,
                                    "format_code": 0,
                                }
                            )
                    else:
                        # Couldn't parse table name - use generic column
                        logger.warning(
                            "Could not extract table name from SELECT, using generic column",
                            sql=sql[:100],
                            session_id=session_id,
                        )
                        columns.append(
                            {
                                "name": "column1",
                                "type_oid": 25,  # TEXT
                                "type_size": -1,
                                "type_modifier": -1,
                                "format_code": 0,
                            }
                        )

                # PROFILING: Fetch complete
                t_fetch_elapsed = (time.perf_counter() - t_fetch_start) * 1000

                # CRITICAL: Convert IRIS date format to PostgreSQL format
                # IRIS returns dates as ISO strings (e.g., '2024-01-15')
                # PostgreSQL wire protocol expects dates as INTEGER days since 2000-01-01
                # This conversion MUST happen before returning results to clients
                if rows and columns:
                    import datetime

                    # PostgreSQL J2000 epoch: 2000-01-01
                    PG_EPOCH = datetime.date(2000, 1, 1)

                    # Build type_oid lookup by column index
                    column_type_oids = [col["type_oid"] for col in columns]

                    # Convert date values in-place
                    for row_idx, row in enumerate(rows):
                        for col_idx, value in enumerate(row):
                            if col_idx < len(column_type_oids):
                                type_oid = column_type_oids[col_idx]

                                # OID 1082 = DATE type
                                if type_oid == 1082 and value is not None:
                                    try:
                                        # IRIS returns dates as ISO strings (YYYY-MM-DD)
                                        if isinstance(value, str):
                                            # Parse ISO date string
                                            date_obj = datetime.datetime.strptime(
                                                value, "%Y-%m-%d"
                                            ).date()
                                            # Convert to PostgreSQL days since 2000-01-01
                                            pg_days = (date_obj - PG_EPOCH).days
                                            rows[row_idx][col_idx] = pg_days
                                            logger.debug(
                                                "Converted date string to PostgreSQL format",
                                                row=row_idx,
                                                col=col_idx,
                                                iris_string=value,
                                                pg_days=pg_days,
                                                date_obj=str(date_obj),
                                            )
                                        # Handle integer Horolog format (if IRIS returns raw days)
                                        elif isinstance(value, int):
                                            pg_date = self._convert_iris_horolog_date_to_pg(value)
                                            rows[row_idx][col_idx] = pg_date
                                            logger.debug(
                                                "Converted Horolog date to PostgreSQL format",
                                                row=row_idx,
                                                col=col_idx,
                                                iris_horolog=value,
                                                pg_days=pg_date,
                                            )
                                    except Exception as date_err:
                                        logger.warning(
                                            "Failed to convert date value",
                                            row=row_idx,
                                            col=col_idx,
                                            value=value,
                                            value_type=type(value),
                                            error=str(date_err),
                                        )
                                        # Keep original value if conversion fails

                t_total_elapsed = (time.perf_counter() - t_start_total) * 1000

                # Determine command tag based on SQL type
                command_tag = self._determine_command_tag(sql, len(rows))

                # PROFILING: Log detailed breakdown
                logger.info(
                    "⏱️ EMBEDDED EXECUTION TIMING",
                    total_ms=round(t_total_elapsed, 2),
                    optimization_ms=round(t_opt_elapsed, 2),
                    iris_exec_ms=round(t_iris_elapsed, 2),
                    fetch_ms=round(t_fetch_elapsed, 2),
                    overhead_ms=round(t_total_elapsed - t_iris_elapsed, 2),
                    session_id=session_id,
                )

                # Feature 030: Schema output translation (SQLUser → public)
                # Only apply to information_schema queries that return schema columns
                if rows and columns:
                    column_names = [col.get("name", "") for col in columns]
                    rows = translate_output_schema(rows, column_names)

                return {
                    "success": True,
                    "rows": rows,
                    "columns": columns,
                    "row_count": len(rows),
                    "command_tag": command_tag,
                    "execution_time_ms": execution_time,
                    "iris_metadata": {"embedded_mode": True, "connection_type": "embedded_python"},
                    "profiling": {
                        "total_ms": t_total_elapsed,
                        "optimization_ms": t_opt_elapsed,
                        "iris_execution_ms": t_iris_elapsed,
                        "fetch_ms": t_fetch_elapsed,
                        "overhead_ms": t_total_elapsed - t_iris_elapsed,
                    },
                }

            except Exception as e:
                # IRIS SQLCODE 100 = "No rows found" - treat as success with 0 rows
                # This is NOT an error - it's a normal response for DELETE/UPDATE with no matches
                if hasattr(e, "sqlcode") and e.sqlcode == 100:
                    logger.info(
                        "IRIS SQLCODE 100 - No rows found (success with 0 rows)",
                        sql=sql[:100] + "..." if len(sql) > 100 else sql,
                        session_id=session_id,
                    )
                    # Determine command tag from SQL
                    sql_upper = sql.strip().upper()
                    if sql_upper.startswith("DELETE"):
                        command_tag = "DELETE"
                    elif sql_upper.startswith("UPDATE"):
                        command_tag = "UPDATE"
                    elif sql_upper.startswith("INSERT"):
                        command_tag = "INSERT"
                    else:
                        command_tag = "UNKNOWN"

                    return {
                        "success": True,  # SQLCODE 100 is success!
                        "rows": [],
                        "columns": [],
                        "row_count": 0,
                        "command_tag": command_tag,
                        "execution_time_ms": 0,
                    }

                # Real error - propagate it
                logger.error(
                    "IRIS embedded execution failed",
                    sql=sql[:100] + "..." if len(sql) > 100 else sql,
                    error=str(e),
                    session_id=session_id,
                )
                return {
                    "success": False,
                    "error": str(e),
                    "rows": [],
                    "columns": [],
                    "row_count": 0,
                    "command_tag": "ERROR",
                    "execution_time_ms": 0,
                }

        # Execute in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_execute)

    async def _execute_external_async(
        self, sql: str, params: list | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute SQL using external IRIS connection with proper async threading
        """

        def _sync_external_execute():
            """Synchronous external IRIS execution in thread pool"""
            try:
                # PROFILING: Track detailed timing
                t_start_total = time.perf_counter()

                # Use intersystems-irispython driver

                # Feature 022: Apply PostgreSQL→IRIS transaction verb translation
                # CRITICAL: Transaction translation MUST occur BEFORE Feature 021 normalization (FR-010)
                transaction_translator = TransactionTranslator()
                transaction_translated_sql = transaction_translator.translate_transaction_command(
                    sql
                )

                # Feature 021: Apply PostgreSQL→IRIS SQL normalization
                # CRITICAL: Normalization MUST occur BEFORE vector optimization (FR-012)
                translator = SQLTranslator()
                normalized_sql = translator.normalize_sql(
                    transaction_translated_sql, execution_path="external"
                )

                # Log transaction translation metrics (external mode)
                txn_metrics = transaction_translator.get_translation_metrics()
                logger.info(
                    "Transaction verb translation applied (external mode)",
                    total_translations=txn_metrics["total_translations"],
                    avg_time_ms=txn_metrics["avg_translation_time_ms"],
                    sla_violations=txn_metrics["sla_violations"],
                    sql_original_preview=sql[:100],
                    sql_translated_preview=transaction_translated_sql[:100],
                    session_id=session_id,
                )

                # Log normalization metrics
                norm_metrics = translator.get_normalization_metrics()
                logger.info(
                    "SQL normalization applied (external mode)",
                    identifiers_normalized=norm_metrics["identifier_count"],
                    dates_translated=norm_metrics["date_literal_count"],
                    normalization_time_ms=norm_metrics["normalization_time_ms"],
                    sla_violated=norm_metrics["sla_violated"],
                    sql_before_preview=transaction_translated_sql[:100],
                    sql_after_preview=normalized_sql[:100],
                    session_id=session_id,
                )

                if norm_metrics["sla_violated"]:
                    logger.warning(
                        "SQL normalization exceeded 5ms SLA (external mode)",
                        normalization_time_ms=norm_metrics["normalization_time_ms"],
                        session_id=session_id,
                    )

                # Apply vector query optimization (convert parameterized vectors to literals)
                # Use normalized_sql as input instead of original sql
                optimized_sql = normalized_sql
                optimized_params = params
                optimization_applied = False

                # PROFILING: Optimization timing
                t_opt_start = time.perf_counter()

                try:
                    from .vector_optimizer import optimize_vector_query

                    logger.debug(
                        "Vector optimizer: checking query (external mode)",
                        sql_preview=normalized_sql[:200],
                        param_count=len(params) if params else 0,
                        session_id=session_id,
                    )

                    # CRITICAL: Pass normalized_sql (not original sql) per FR-012
                    optimized_sql, optimized_params = optimize_vector_query(normalized_sql, params)

                    optimization_applied = (optimized_sql != normalized_sql) or (
                        optimized_params != params
                    )

                    if optimization_applied:
                        logger.info(
                            "Vector optimization applied (external mode)",
                            sql_changed=(optimized_sql != normalized_sql),
                            params_changed=(optimized_params != params),
                            params_before=len(params) if params else 0,
                            params_after=len(optimized_params) if optimized_params else 0,
                            optimized_sql_preview=optimized_sql[:200],
                            session_id=session_id,
                        )
                    else:
                        logger.debug(
                            "Vector optimization not applicable (external mode)",
                            reason="No vector patterns found or params unchanged",
                            session_id=session_id,
                        )

                except ImportError as e:
                    logger.warning(
                        "Vector optimizer not available (external mode)",
                        error=str(e),
                        session_id=session_id,
                    )
                except Exception as opt_error:
                    logger.warning(
                        "Vector optimization failed, using normalized query (external mode)",
                        error=str(opt_error),
                        session_id=session_id,
                    )
                    optimized_sql, optimized_params = normalized_sql, params

                # PROFILING: Optimization complete
                t_opt_elapsed = (time.perf_counter() - t_opt_start) * 1000

                # Performance tracking
                start_time = time.perf_counter()

                # PROFILING: Connection timing
                t_conn_start = time.perf_counter()

                # Get connection from pool (or create new one)
                conn = self._get_pooled_connection()

                t_conn_elapsed = (time.perf_counter() - t_conn_start) * 1000

                # PROFILING: IRIS execution timing
                t_iris_start = time.perf_counter()

                # Execute query
                cursor = conn.cursor()
                if optimized_params is not None and len(optimized_params) > 0:
                    cursor.execute(optimized_sql, optimized_params)
                else:
                    cursor.execute(optimized_sql)

                # CRITICAL DEBUG: Log exact SQL sent to IRIS
                logger.info(
                    "🔍 DBAPI SQL EXECUTED",
                    sql=optimized_sql,
                    params=optimized_params,
                    session_id=session_id,
                )

                t_iris_elapsed = (time.perf_counter() - t_iris_start) * 1000
                execution_time = (time.perf_counter() - start_time) * 1000

                # PROFILING: Result processing timing
                t_fetch_start = time.perf_counter()

                # Process results
                rows = []
                columns = []

                # Get column information
                if cursor.description:
                    for desc in cursor.description:
                        # Get original IRIS column name and type
                        iris_col_name = desc[0]
                        iris_type = desc[1] if len(desc) > 1 else "VARCHAR"

                        # CRITICAL: Normalize IRIS column names to PostgreSQL conventions
                        # IRIS generates HostVar_1, Expression_1, Aggregate_1 for unnamed columns
                        # PostgreSQL uses ?column?, type names (int4), or function names (count)
                        col_name = self._normalize_iris_column_name(iris_col_name, sql, iris_type)

                        # DEBUG: Log IRIS type for arithmetic expressions (external mode)
                        logger.info(
                            "🔍 IRIS metadata type discovery (EXTERNAL MODE)",
                            original_column_name=iris_col_name,
                            normalized_column_name=col_name,
                            iris_type=iris_type,
                            desc=desc,
                            sql_preview=optimized_sql[:200],
                        )

                        # CRITICAL FIX: IRIS type code 2 means NUMERIC, but for decimal literals
                        # like 3.14, we want FLOAT8 so node-postgres returns a number, not a string.
                        # Override to FLOAT8 UNLESS explicitly cast to NUMERIC/DECIMAL or INTEGER
                        type_oid = self._iris_type_to_pg_oid(iris_type)

                        sql_upper_check = optimized_sql.upper()

                        if iris_type == 2:
                            # Check for explicit casts
                            if "AS INTEGER" in sql_upper_check or "AS INT" in sql_upper_check:
                                # CAST(? AS INTEGER) - override to INT4
                                logger.info(
                                    "🔧 OVERRIDING IRIS type code 2 (NUMERIC) → OID 23 (INT4)",
                                    column_name=col_name,
                                    original_oid=type_oid,
                                    reason="SQL contains CAST to INTEGER",
                                )
                                type_oid = 23  # INT4
                            elif (
                                "AS NUMERIC" not in sql_upper_check
                                and "AS DECIMAL" not in sql_upper_check
                            ):
                                # No explicit NUMERIC/DECIMAL cast → make it FLOAT8
                                logger.info(
                                    "🔧 OVERRIDING IRIS type code 2 (NUMERIC) → OID 701 (FLOAT8)",
                                    column_name=col_name,
                                    original_oid=type_oid,
                                    reason="Decimal literal without explicit NUMERIC/DECIMAL cast",
                                )
                                type_oid = 701  # FLOAT8

                        columns.append(
                            {
                                "name": col_name,
                                "type_oid": type_oid,
                                "type_size": desc[2] if len(desc) > 2 else -1,
                                "type_modifier": -1,
                                "format_code": 0,  # Text format
                            }
                        )

                # Fetch all rows for SELECT queries
                if sql.upper().strip().startswith("SELECT") and columns:
                    try:
                        results = cursor.fetchall()

                        # CRITICAL DEBUG: Log exact values returned by IRIS DBAPI
                        logger.info(
                            "🔍 DBAPI RAW RESULTS",
                            raw_results=results,
                            result_count=len(results) if results else 0,
                            first_row=results[0] if results else None,
                            first_row_type=type(results[0]) if results else None,
                            first_value=results[0][0] if results and len(results[0]) > 0 else None,
                            first_value_type=(
                                type(results[0][0]) if results and len(results[0]) > 0 else None
                            ),
                            session_id=session_id,
                        )

                        for row in results:
                            if isinstance(row, list | tuple):
                                rows.append(list(row))
                            else:
                                # Single value result
                                rows.append([row])
                    except Exception as fetch_error:
                        logger.warning(
                            "Failed to fetch external IRIS results",
                            error=str(fetch_error),
                            session_id=session_id,
                        )

                cursor.close()
                # Return connection to pool instead of closing
                self._return_connection(conn)

                # PROFILING: Fetch complete
                t_fetch_elapsed = (time.perf_counter() - t_fetch_start) * 1000

                # CRITICAL: Convert IRIS date format to PostgreSQL format (EXTERNAL MODE)
                # Same conversion logic as embedded mode
                if rows and columns:
                    import datetime

                    # PostgreSQL J2000 epoch: 2000-01-01
                    PG_EPOCH = datetime.date(2000, 1, 1)

                    # Build type_oid lookup by column index
                    column_type_oids = [col["type_oid"] for col in columns]

                    # Convert date values in-place
                    for row_idx, row in enumerate(rows):
                        for col_idx, value in enumerate(row):
                            if col_idx < len(column_type_oids):
                                type_oid = column_type_oids[col_idx]

                                # OID 1082 = DATE type
                                if type_oid == 1082 and value is not None:
                                    try:
                                        # IRIS returns dates as ISO strings (YYYY-MM-DD)
                                        if isinstance(value, str):
                                            # Parse ISO date string
                                            date_obj = datetime.datetime.strptime(
                                                value, "%Y-%m-%d"
                                            ).date()
                                            # Convert to PostgreSQL days since 2000-01-01
                                            pg_days = (date_obj - PG_EPOCH).days
                                            rows[row_idx][col_idx] = pg_days
                                            logger.debug(
                                                "Converted date string to PostgreSQL format (external)",
                                                row=row_idx,
                                                col=col_idx,
                                                iris_string=value,
                                                pg_days=pg_days,
                                                date_obj=str(date_obj),
                                            )
                                        # Handle integer Horolog format (if IRIS returns raw days)
                                        elif isinstance(value, int):
                                            pg_date = self._convert_iris_horolog_date_to_pg(value)
                                            rows[row_idx][col_idx] = pg_date
                                            logger.debug(
                                                "Converted Horolog date to PostgreSQL format (external)",
                                                row=row_idx,
                                                col=col_idx,
                                                iris_horolog=value,
                                                pg_days=pg_date,
                                            )
                                    except Exception as date_err:
                                        logger.warning(
                                            "Failed to convert date value (external mode)",
                                            row=row_idx,
                                            col=col_idx,
                                            value=value,
                                            value_type=type(value),
                                            error=str(date_err),
                                        )
                                        # Keep original value if conversion fails

                t_total_elapsed = (time.perf_counter() - t_start_total) * 1000

                # Determine command tag
                command_tag = self._determine_command_tag(sql, len(rows))

                # PROFILING: Log detailed breakdown
                logger.info(
                    "⏱️ EXTERNAL EXECUTION TIMING",
                    total_ms=round(t_total_elapsed, 2),
                    optimization_ms=round(t_opt_elapsed, 2),
                    connection_ms=round(t_conn_elapsed, 2),
                    iris_exec_ms=round(t_iris_elapsed, 2),
                    fetch_ms=round(t_fetch_elapsed, 2),
                    overhead_ms=round(t_total_elapsed - t_iris_elapsed, 2),
                    session_id=session_id,
                )

                # Feature 030: Schema output translation (SQLUser → public)
                # Only apply to information_schema queries that return schema columns
                if rows and columns:
                    column_names = [col.get("name", "") for col in columns]
                    rows = translate_output_schema(rows, column_names)

                return {
                    "success": True,
                    "rows": rows,
                    "columns": columns,
                    "row_count": len(rows),
                    "command_tag": command_tag,
                    "execution_time_ms": execution_time,
                    "iris_metadata": {"embedded_mode": False, "connection_type": "external_driver"},
                    "profiling": {
                        "total_ms": t_total_elapsed,
                        "optimization_ms": t_opt_elapsed,
                        "connection_ms": t_conn_elapsed,
                        "iris_execution_ms": t_iris_elapsed,
                        "fetch_ms": t_fetch_elapsed,
                        "overhead_ms": t_total_elapsed - t_iris_elapsed,
                    },
                }

            except Exception as e:
                logger.error(
                    "IRIS external execution failed",
                    sql=sql[:100] + "..." if len(sql) > 100 else sql,
                    error=str(e),
                    session_id=session_id,
                )
                return {
                    "success": False,
                    "error": str(e),
                    "rows": [],
                    "columns": [],
                    "row_count": 0,
                    "command_tag": "ERROR",
                    "execution_time_ms": 0,
                }

        # Execute in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_external_execute)

    def _get_iris_connection(self):
        """
        Get or create IRIS connection for embedded mode batch operations.

        ARCHITECTURE NOTE:
        In embedded mode (irispython), we use iris.sql.exec() for individual queries.
        For batch operations, we fall back to loop-based execution instead of
        executemany() because the iris.dbapi module is shadowed by the embedded
        iris module.

        This method is a placeholder for potential future optimization.
        """
        # For embedded mode, we don't use DBAPI connections
        # The _execute_many_embedded_async() method will use iris.sql.exec() in a loop
        return None

    def _get_pooled_connection(self):
        """
        Get a connection from the pool or create a new one.

        Implements simple connection pooling for external IRIS connections
        to avoid the 7ms connection overhead on every query.
        """
        import iris

        with self._connection_lock:
            # Try to get a connection from the pool
            if self._connection_pool:
                conn = self._connection_pool.pop()

                # Validate the connection is still alive
                try:
                    # Quick test query
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                    cursor.close()
                    return conn
                except Exception:
                    # Connection is dead, create a new one
                    try:
                        conn.close()
                    except Exception:
                        pass

            # No connections available or connection was dead - create new one
            conn = iris.connect(
                hostname=self.iris_config["host"],
                port=self.iris_config["port"],
                namespace=self.iris_config["namespace"],
                username=self.iris_config["username"],
                password=self.iris_config["password"],
            )

            return conn

    def _return_connection(self, conn):
        """
        Return a connection to the pool for reuse.

        Args:
            conn: IRIS connection to return to pool
        """
        with self._connection_lock:
            # Only keep up to max_connections in the pool
            if len(self._connection_pool) < self._max_connections:
                self._connection_pool.append(conn)
            else:
                # Pool is full, close this connection
                try:
                    conn.close()
                except Exception:
                    pass

    def _expand_select_star(
        self, sql: str, expected_columns: int, session_id: str | None = None
    ) -> list[str] | None:
        """
        Layer 1.5: Expand SELECT * queries using INFORMATION_SCHEMA (2025-11-14 fix).

        When a query contains "SELECT * FROM table", IRIS doesn't provide column metadata
        in the result object. This method queries INFORMATION_SCHEMA to get the actual
        column names from the table definition.

        Args:
            sql: Original SQL query
            expected_columns: Number of columns in the actual result
            session_id: Optional session identifier for logging

        Returns:
            List of column names if successful, None if method fails

        References:
            - asyncpg test failure: KeyError 'id' in test_fetch_all_rows (2025-11-14)
        """
        try:
            import re

            import iris

            # Extract table name from SELECT * FROM table_name pattern
            # Handle variations: SELECT *, SELECT * FROM, with ORDER BY, WHERE, etc.
            select_star_pattern = r"SELECT\s+\*\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)"
            match = re.search(select_star_pattern, sql, re.IGNORECASE)

            if not match:
                logger.debug(
                    "Not a SELECT * FROM table query - pattern did not match",
                    sql=sql[:100],
                    session_id=session_id,
                )
                return None

            table_name = match.group(1)

            logger.debug(
                "Detected SELECT * query - expanding via INFORMATION_SCHEMA",
                table_name=table_name,
                sql=sql[:100],
                session_id=session_id,
            )

            # Query INFORMATION_SCHEMA for column names
            metadata_sql = f"""
                SELECT column_name
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(table_name) = LOWER('{table_name}')
                ORDER BY ordinal_position
            """

            result = iris.sql.exec(metadata_sql)
            column_names = [row[0] for row in result]

            if column_names:
                logger.info(
                    "✅ SELECT * expansion successful",
                    table=table_name,
                    columns=column_names,
                    expected=expected_columns,
                    actual=len(column_names),
                    session_id=session_id,
                )
                return column_names
            else:
                logger.warning(
                    "No columns found in INFORMATION_SCHEMA",
                    table=table_name,
                    session_id=session_id,
                )
                return None

        except Exception as e:
            logger.debug(
                "SELECT * expansion failed",
                error=str(e),
                error_type=type(e).__name__,
                session_id=session_id,
            )
            return None

    def _discover_metadata_with_limit_zero(
        self, sql: str, session_id: str | None = None
    ) -> list[str] | None:
        """
        Layer 1: Discover column metadata using LIMIT 0 pattern (database-native approach).

        This implements the protocol-native solution recommended by Perplexity research:
        Execute the query with LIMIT 0 to discover column structure without fetching data.

        Args:
            sql: Original SQL query
            session_id: Optional session identifier for logging

        Returns:
            List of column names if successful, None if method fails

        References:
            - Perplexity research 2025-11-11: "LIMIT 0 pattern for metadata discovery"
            - PostgreSQL Parse/Describe mechanism alternative
        """
        try:
            import iris

            # Wrap original query in subquery with LIMIT 0 to discover structure
            # Pattern: SELECT * FROM (original_query) AS _metadata LIMIT 0
            metadata_query = f"SELECT * FROM ({sql}) AS _metadata_discovery LIMIT 0"

            logger.debug(
                "Attempting LIMIT 0 metadata discovery",
                original_sql=sql[:100],
                metadata_sql=metadata_query[:150],
                session_id=session_id,
            )

            # Execute metadata query - should return 0 rows but expose column structure
            result = iris.sql.exec(metadata_query)

            # Try to extract column names from result metadata
            column_names = []

            # Method 1: Check for _meta attribute (IRIS may expose this)
            if hasattr(result, "_meta") and result._meta:
                for col_info in result._meta:
                    if isinstance(col_info, dict) and "name" in col_info:
                        column_names.append(col_info["name"])
                    elif hasattr(col_info, "name"):
                        column_names.append(col_info.name)

                if column_names:
                    logger.info(
                        "LIMIT 0 metadata discovery: extracted from _meta",
                        columns=column_names,
                        session_id=session_id,
                    )
                    return column_names

            # Method 2: Try iterating result (even with 0 rows, may expose structure)
            # Some database APIs expose column info through iteration interface
            try:
                # Attempt to get first row (should be empty)
                for _row in result:
                    # We shouldn't reach here with LIMIT 0, but if we do,
                    # we can infer column count from row length
                    break
            except Exception:
                pass

            # Method 3: Check for description attribute (DB-API 2.0 standard)
            if hasattr(result, "description") and result.description:
                for col_desc in result.description:
                    # DB-API 2.0: description is list of 7-tuples (name, type, ...)
                    if isinstance(col_desc, list | tuple) and len(col_desc) > 0:
                        column_names.append(str(col_desc[0]))
                    elif hasattr(col_desc, "name"):
                        column_names.append(col_desc.name)

                if column_names:
                    logger.info(
                        "LIMIT 0 metadata discovery: extracted from description",
                        columns=column_names,
                        session_id=session_id,
                    )
                    return column_names

            # No metadata could be extracted
            logger.debug(
                "LIMIT 0 metadata discovery: no metadata exposed by IRIS", session_id=session_id
            )
            return None

        except Exception as e:
            logger.debug(
                "LIMIT 0 metadata discovery failed",
                error=str(e),
                error_type=type(e).__name__,
                session_id=session_id,
            )
            return None

    def _normalize_iris_column_name(self, iris_name: str, sql: str, iris_type: str | int) -> str:
        """
        Normalize IRIS-generated column names to PostgreSQL-compatible names.

        IRIS generates generic names like HostVar_1, Expression_1, Aggregate_1
        when no explicit alias is provided. PostgreSQL uses different conventions.

        Args:
            iris_name: Original column name from IRIS
            sql: Original SQL query for context
            iris_type: IRIS type code for type-specific naming

        Returns:
            PostgreSQL-compatible column name
        """
        # Lowercase for PostgreSQL compatibility
        normalized = iris_name.lower()

        logger.info(
            "🔍 _normalize_iris_column_name CALLED",
            iris_name=iris_name,
            normalized=normalized,
            sql_preview=sql[:100],
            iris_type=iris_type,
        )

        # Pattern 0: Literal column names (e.g., '1' for SELECT 1, 'second query' for SELECT 'second query')
        # IRIS sometimes returns the literal value as the column name instead of HostVar_N
        # These should be mapped to ?column? for PostgreSQL compatibility

        # Helper: Check if SQL has explicit alias near this literal value
        def has_explicit_alias_for_literal(literal_val: str, sql_text: str) -> str | None:
            """
            Check if SQL contains 'literal_val AS alias' pattern.
            Returns the alias if found, None otherwise.

            Examples:
            - "SELECT 1 AS id" with literal='1' → returns 'id'
            - "SELECT 'first' AS name" with literal='first' → returns 'name'
            """
            import re

            # Pattern 1: numeric literal followed by AS alias
            # Match: "1 AS id", "2.5 AS score"
            if literal_val.replace(".", "").replace("-", "").isdigit():
                pattern = rf"\b{re.escape(literal_val)}\s+AS\s+(\w+)"
                match = re.search(pattern, sql_text, re.IGNORECASE)
                if match:
                    return match.group(1).lower()

            # Pattern 2: string literal followed by AS alias
            # Match: "'first' AS name", '"hello" AS greeting'
            else:
                # Try both single and double quotes
                pattern1 = rf"'{re.escape(literal_val)}'\s+AS\s+(\w+)"
                pattern2 = rf'"{re.escape(literal_val)}"\s+AS\s+(\w+)'
                match = re.search(pattern1, sql_text, re.IGNORECASE) or re.search(
                    pattern2, sql_text, re.IGNORECASE
                )
                if match:
                    return match.group(1).lower()

            return None

        # Case 1: Pure numeric column name (e.g., '1', '42', '3.14', '-5')
        try:
            float(normalized)

            # Check if this literal has an explicit alias in SQL
            explicit_alias = has_explicit_alias_for_literal(normalized, sql)
            if explicit_alias:
                logger.info(
                    f"🔍 NUMERIC LITERAL with EXPLICIT ALIAS: '{normalized}' → '{explicit_alias}'",
                    iris_name=iris_name,
                    normalized=normalized,
                )
                return explicit_alias

            logger.info(
                "🔍 NUMERIC COLUMN DETECTED → returning '?column?'",
                iris_name=iris_name,
                normalized=normalized,
            )
            return "?column?"
        except ValueError:
            logger.debug("Not a numeric column name", normalized=normalized)
            pass

        # Case 2: Generic column names for SELECT without FROM (e.g., SELECT 'hello', SELECT 1+2)
        # ONLY convert generic names, preserve explicit aliases and expression types
        sql_upper = sql.upper()
        if "SELECT" in sql_upper and "FROM" not in sql_upper:
            # ONLY apply ?column? to truly generic column names (column, column1, etc.)
            # This preserves explicit aliases (AS id) and type names from casts (int4)
            if normalized in ("column", "column1", "column2", "column3", "column4", "column5"):
                # Additional check: make sure there's no explicit AS alias in the SQL
                # If "AS <normalized>" appears, keep the original name
                sql_lower = sql.lower()
                if f" as {normalized}" not in sql_lower and f' as "{normalized}"' not in sql_lower:
                    return "?column?"

            # Check if the column name appears as a string literal in the SQL
            # Remove quotes and check if it matches
            unquoted = normalized.replace("'", "").replace('"', "").strip()
            sql_lower = sql.lower()

            # If the unquoted column name appears in the SQL as a quoted string
            if f"'{unquoted}'" in sql_lower or f'"{unquoted}"' in sql_lower:
                return "?column?"

        # Pattern 1: HostVar_N (unnamed literals) → ?column?
        if normalized.startswith("hostvar_"):
            return "?column?"

        # Pattern 2: Expression_N (casts/expressions)
        if normalized.startswith("expression_"):
            # Check for type cast patterns in SQL
            sql_upper = sql.upper()

            # ::int or CAST(? AS INTEGER) → int4
            if "::INT" in sql_upper or ("CAST" in sql_upper and "AS INTEGER" in sql_upper):
                return "int4"
            # ::bigint or CAST(? AS BIGINT) → int8
            elif "::BIGINT" in sql_upper or ("CAST" in sql_upper and "AS BIGINT" in sql_upper):
                return "int8"
            # ::smallint or CAST(? AS SMALLINT) → int2
            elif "::SMALLINT" in sql_upper or ("CAST" in sql_upper and "AS SMALLINT" in sql_upper):
                return "int2"
            # ::text or CAST(? AS TEXT) → text
            elif "::TEXT" in sql_upper or ("CAST" in sql_upper and "AS TEXT" in sql_upper):
                return "text"
            # ::varchar or CAST(? AS VARCHAR) → varchar
            elif "::VARCHAR" in sql_upper or ("CAST" in sql_upper and "AS VARCHAR" in sql_upper):
                return "varchar"
            # ::bool or CAST(? AS BOOL) → bool
            elif "::BOOL" in sql_upper or ("CAST" in sql_upper and "AS BIT" in sql_upper):
                return "bool"
            # ::date or CAST(? AS DATE) → date
            elif "::DATE" in sql_upper or ("CAST" in sql_upper and "AS DATE" in sql_upper):
                return "date"
            else:
                # Generic expression without clear type → ?column?
                return "?column?"

        # Pattern 3: Aggregate_N (aggregate functions)
        if normalized.startswith("aggregate_"):
            # Detect aggregate function from SQL
            sql_upper = sql.upper()

            if "COUNT(" in sql_upper:
                return "count"
            elif "SUM(" in sql_upper:
                return "sum"
            elif "AVG(" in sql_upper:
                return "avg"
            elif "MIN(" in sql_upper:
                return "min"
            elif "MAX(" in sql_upper:
                return "max"
            else:
                # Unknown aggregate → keep lowercase name
                return normalized

        # Pattern 3.5: PostgreSQL type name mapping (for cast expressions)
        # IRIS returns 'INTEGER', 'BIGINT', etc. but PostgreSQL clients expect 'int4', 'int8'
        postgres_type_mapping = {
            "integer": "int4",
            "bigint": "int8",
            "smallint": "int2",
            "real": "float4",
            "double": "float8",
            "double precision": "float8",
            "character varying": "varchar",
            "character": "char",
        }

        if normalized in postgres_type_mapping:
            pg_type = postgres_type_mapping[normalized]
            logger.info(f"🔧 Type name mapping: '{normalized}' → '{pg_type}'")
            return pg_type

        # Pattern 4: Named columns → keep original (lowercased)
        return normalized

    def _iris_type_to_pg_oid(self, iris_type: str | int) -> int:
        """Convert IRIS data type to PostgreSQL OID"""
        # Handle both string type names and integer type codes
        if isinstance(iris_type, int):
            # Map IRIS integer type codes to PostgreSQL OIDs
            # CRITICAL: Based on actual IRIS behavior for SQL literals:
            # - type_code=4 returns Python int (e.g., SELECT 1) → INTEGER
            # - type_code=2 returns Python Decimal (e.g., SELECT 3.14) → NUMERIC
            int_type_mapping = {
                -7: 16,  # BIT → bool (IRIS type code for BIT columns)
                1: 23,  # int4
                2: 1700,  # numeric (FIXED: was 21/int2, but IRIS returns Decimal for numeric literals)
                3: 20,  # int8
                4: 23,  # int4 (FIXED: was 700/float4, but IRIS returns int for integer literals)
                5: 701,  # float8
                8: 1083,  # time (FIXED: was 1082/date - IRIS type code 8 is TIME)
                9: 1082,  # date (FIXED: was 1083/time - IRIS type code 9 is DATE)
                10: 1114,  # timestamp
                12: 1043,  # varchar
                16: 16,  # bool
                17: 17,  # bytea
            }
            return int_type_mapping.get(iris_type, 25)  # Default to text

        # Handle string type names
        type_mapping = {
            "VARCHAR": 1043,  # varchar
            "CHAR": 1042,  # bpchar
            "TEXT": 25,  # text
            "INTEGER": 23,  # int4
            "BIGINT": 20,  # int8
            "SMALLINT": 21,  # int2
            "DECIMAL": 1700,  # numeric
            "NUMERIC": 1700,  # numeric
            "DOUBLE": 701,  # float8
            "FLOAT": 700,  # float4
            "DATE": 1082,  # date
            "TIME": 1083,  # time
            "TIMESTAMP": 1114,  # timestamp
            "BOOLEAN": 16,  # bool
            "BINARY": 17,  # bytea
            "VARBINARY": 17,  # bytea
            "VECTOR": 16388,  # custom vector type
        }
        return type_mapping.get(str(iris_type).upper(), 25)  # Default to text

    def _extract_table_name_from_select(self, sql: str) -> str | None:
        """
        Extract table name from SELECT query (simple parsing).

        Handles:
        - SELECT * FROM table_name
        - SELECT col1, col2 FROM table_name
        - SELECT * FROM "table_name"
        - SELECT * FROM "schema"."table_name" (Prisma format)
        - SELECT * FROM schema."table_name"
        - SELECT * FROM table_name WHERE ...

        Returns:
            Table name or None if cannot parse
        """
        import re

        # CRITICAL FIX: Handle Prisma-style quoted identifiers
        # Prisma sends: FROM "public"."test_users"
        # We need to extract "test_users" (the table name, not schema)

        # Pattern 1: FROM "schema"."table_name" - extract last quoted identifier
        match = re.search(r'\bFROM\s+(?:"?\w+"?\s*\.\s*)*"?(\w+)"?', sql, re.IGNORECASE)
        if match:
            table_name = match.group(1)
            logger.debug(f"Extracted table name: {table_name}", sql=sql[:100])
            return table_name

        # Fallback: Simple unquoted table name
        match = re.search(r"\bFROM\s+(\w+)", sql, re.IGNORECASE)
        if match:
            table_name = match.group(1)
            logger.debug(f"Extracted table name (simple): {table_name}", sql=sql[:100])
            return table_name

        return None

    def _map_iris_type_to_oid(self, iris_type: str) -> int:
        """
        Map IRIS data type to PostgreSQL type OID.

        Args:
            iris_type: IRIS data type (e.g., 'INT', 'VARCHAR', 'DATE')

        Returns:
            PostgreSQL type OID
        """
        type_map = {
            "INT": 23,  # int4
            "INTEGER": 23,  # int4
            "BIGINT": 20,  # int8
            "SMALLINT": 21,  # int2
            "VARCHAR": 1043,  # varchar
            "CHAR": 1042,  # char
            "TEXT": 25,  # text
            "DATE": 1082,  # date
            "TIME": 1083,  # time
            "TIMESTAMP": 1114,  # timestamp
            "DOUBLE": 701,  # float8
            "FLOAT": 701,  # float8
            "NUMERIC": 1700,  # numeric
            "DECIMAL": 1700,  # numeric
            "BIT": 1560,  # bit
            "BOOLEAN": 16,  # bool
            "VARBINARY": 17,  # bytea
        }

        # Normalize type name (remove size, etc.)
        normalized_type = iris_type.upper().split("(")[0].strip()

        return type_map.get(normalized_type, 25)  # Default to TEXT (OID 25)

    def _determine_command_tag(self, sql: str, row_count: int) -> str:
        """Determine PostgreSQL command tag from SQL"""
        sql_upper = sql.upper().strip()

        if sql_upper.startswith("SELECT"):
            return "SELECT"
        elif sql_upper.startswith("INSERT"):
            return f"INSERT 0 {row_count}"
        elif sql_upper.startswith("UPDATE"):
            return f"UPDATE {row_count}"
        elif sql_upper.startswith("DELETE"):
            return f"DELETE {row_count}"
        elif sql_upper.startswith("CREATE"):
            return "CREATE"
        elif sql_upper.startswith("DROP"):
            return "DROP"
        elif sql_upper.startswith("ALTER"):
            return "ALTER"
        elif sql_upper.startswith("BEGIN"):
            return "BEGIN"
        elif sql_upper.startswith("COMMIT"):
            return "COMMIT"
        elif sql_upper.startswith("ROLLBACK"):
            return "ROLLBACK"
        elif sql_upper.startswith("SHOW"):
            return "SHOW"
        else:
            return "UNKNOWN"

    def _handle_show_command(self, sql: str, session_id: str | None = None) -> dict[str, Any]:
        """
        Handle PostgreSQL SHOW commands that IRIS doesn't support.

        Returns fake/default values for PostgreSQL compatibility.

        Args:
            sql: SHOW command SQL
            session_id: Optional session identifier

        Returns:
            Dictionary with fake query results
        """
        sql_upper = sql.strip().upper()

        # Map of SHOW commands to their default values
        show_responses = {
            "SHOW TRANSACTION ISOLATION LEVEL": "read committed",
            "SHOW SERVER_VERSION": "16.0 (InterSystems IRIS)",
            "SHOW SERVER_ENCODING": "UTF8",
            "SHOW CLIENT_ENCODING": "UTF8",
            "SHOW DATESTYLE": "ISO, MDY",
            "SHOW TIMEZONE": "UTC",
            "SHOW STANDARD_CONFORMING_STRINGS": "on",
            "SHOW INTEGER_DATETIMES": "on",
            "SHOW INTERVALSTYLE": "postgres",
            "SHOW IS_SUPERUSER": "off",
            "SHOW APPLICATION_NAME": "",
        }

        # Normalize the SQL (remove trailing semicolon and extra whitespace)
        normalized_show = sql_upper.rstrip(";").strip()

        # Find matching SHOW command
        response_value = None
        column_name = "setting"  # Default column name for SHOW results

        for show_cmd, default_value in show_responses.items():
            if normalized_show.startswith(show_cmd):
                response_value = default_value
                # Extract column name from command (e.g., "transaction_isolation_level")
                parts = show_cmd.split(" ", 1)
                if len(parts) > 1:
                    column_name = parts[1].lower().replace(" ", "_")
                break

        # If not found in map, return generic error-like response
        if response_value is None:
            logger.warning(
                "Unknown SHOW command, returning empty result", sql=sql[:100], session_id=session_id
            )
            response_value = ""
            column_name = "setting"

        logger.info(
            "SHOW command shim returning fake result",
            command=normalized_show,
            response_value=response_value,
            session_id=session_id,
        )

        # Return result in the format expected by protocol.py
        return {
            "success": True,
            "rows": [[response_value]],  # Single row, single column
            "columns": [
                {
                    "name": column_name,
                    "type_oid": 25,  # TEXT type
                    "type_size": -1,
                    "type_modifier": -1,
                    "format_code": 0,
                }
            ],
            "row_count": 1,
            "command_tag": "SHOW",
            "execution_time_ms": 0.1,  # Negligible time for fake result
            "iris_metadata": {"embedded_mode": self.embedded_mode, "connection_type": "show_shim"},
        }

    async def shutdown(self):
        """Shutdown the executor and cleanup resources"""
        try:
            if self.thread_pool:
                self.thread_pool.shutdown(wait=True)
                logger.info("IRIS executor shutdown completed")
        except Exception as e:
            logger.warning("Error during IRIS executor shutdown", error=str(e))

    # Transaction management methods (using async threading)
    async def begin_transaction(self, session_id: str | None = None):
        """Begin a transaction with async threading"""

        def _sync_begin():
            if self.embedded_mode:
                import iris

                iris.sql.exec("START TRANSACTION")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_begin)

    async def commit_transaction(self, session_id: str | None = None):
        """Commit transaction with async threading"""

        def _sync_commit():
            if self.embedded_mode:
                import iris

                iris.sql.exec("COMMIT")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_commit)

    async def rollback_transaction(self, session_id: str | None = None):
        """Rollback transaction with async threading"""

        def _sync_rollback():
            if self.embedded_mode:
                import iris

                iris.sql.exec("ROLLBACK")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_rollback)

    async def cancel_query(self, backend_pid: int, backend_secret: int):
        """
        Cancel a running query (P4 implementation)

        Since IRIS SQL doesn't have PostgreSQL-style CANCEL QUERY, we implement
        this using process termination and connection management.
        """
        try:
            logger.info(
                "Processing query cancellation request",
                backend_pid=backend_pid,
                backend_secret="***",
            )

            # P4: Query cancellation via connection termination
            # In production, this would:
            # 1. Validate backend_secret against stored secret for backend_pid
            # 2. Find the active connection/query for that PID
            # 3. Terminate the IRIS connection/process
            # 4. Clean up resources

            if self.embedded_mode:
                # For embedded mode, we could use IRIS job control
                success = await self._cancel_embedded_query(backend_pid, backend_secret)
            else:
                # For external connections, terminate the connection
                success = await self._cancel_external_query(backend_pid, backend_secret)

            if success:
                logger.info("Query cancellation successful", backend_pid=backend_pid)
            else:
                logger.warning(
                    "Query cancellation failed - PID not found or secret mismatch",
                    backend_pid=backend_pid,
                )

            return success

        except Exception as e:
            logger.error("Query cancellation error", backend_pid=backend_pid, error=str(e))
            return False

    async def _cancel_embedded_query(self, backend_pid: int, backend_secret: int) -> bool:
        """Cancel query in IRIS embedded mode"""
        try:

            def _sync_cancel():
                # In embedded mode, we could potentially use IRIS job control
                # For now, return success for demo purposes
                # Production would implement actual IRIS job termination
                logger.info("Embedded query cancellation (demo mode)")
                return True

            return await asyncio.to_thread(_sync_cancel)

        except Exception as e:
            logger.error("Embedded query cancellation failed", error=str(e))
            return False

    async def _cancel_external_query(self, backend_pid: int, backend_secret: int) -> bool:
        """Cancel query for external IRIS connection"""
        try:
            # P4: Use server's connection registry to find and terminate connection
            if not self.server:
                logger.warning("No server reference for cancellation")
                return False

            # Find the target connection
            target_protocol = self.server.find_connection_for_cancellation(
                backend_pid, backend_secret
            )

            if not target_protocol:
                logger.warning("Connection not found for cancellation", backend_pid=backend_pid)
                return False

            # Terminate the connection - this will stop any running queries
            logger.info(
                "Terminating connection for query cancellation",
                backend_pid=backend_pid,
                connection_id=target_protocol.connection_id,
            )

            # Close the connection which will abort any running IRIS queries
            if not target_protocol.writer.is_closing():
                target_protocol.writer.close()
                try:
                    await target_protocol.writer.wait_closed()
                except Exception:
                    pass  # Connection may already be closed

            return True

        except Exception as e:
            logger.error("External query cancellation failed", error=str(e))
            return False

    def get_iris_type_mapping(self) -> dict[str, dict[str, Any]]:
        """
        Get IRIS to PostgreSQL type mappings (based on caretdev patterns)

        Returns type mapping for pg_catalog implementation
        """
        return {
            # Standard PostgreSQL types (from caretdev)
            "BIGINT": {"oid": 20, "typname": "int8", "typlen": 8},
            "BIT": {"oid": 1560, "typname": "bit", "typlen": -1},
            "DATE": {"oid": 1082, "typname": "date", "typlen": 4},
            "DOUBLE": {"oid": 701, "typname": "float8", "typlen": 8},
            "INTEGER": {"oid": 23, "typname": "int4", "typlen": 4},
            "NUMERIC": {"oid": 1700, "typname": "numeric", "typlen": -1},
            "SMALLINT": {"oid": 21, "typname": "int2", "typlen": 2},
            "TIME": {"oid": 1083, "typname": "time", "typlen": 8},
            "TIMESTAMP": {"oid": 1114, "typname": "timestamp", "typlen": 8},
            "TINYINT": {"oid": 21, "typname": "int2", "typlen": 2},  # Map to smallint
            "VARBINARY": {"oid": 17, "typname": "bytea", "typlen": -1},
            "VARCHAR": {"oid": 1043, "typname": "varchar", "typlen": -1},
            "LONGVARCHAR": {"oid": 25, "typname": "text", "typlen": -1},
            "LONGVARBINARY": {"oid": 17, "typname": "bytea", "typlen": -1},
            # IRIS-specific types with P5 vector support
            "VECTOR": {"oid": 16388, "typname": "vector", "typlen": -1},
            "EMBEDDING": {
                "oid": 16389,
                "typname": "vector",
                "typlen": -1,
            },  # Map IRIS EMBEDDING to vector
        }

    def get_server_info(self) -> dict[str, Any]:
        """Get IRIS server information for PostgreSQL compatibility"""
        return {
            "server_version": "16.0 (InterSystems IRIS)",
            "server_version_num": "160000",
            "embedded_mode": self.embedded_mode,
            "vector_support": self.vector_support,
            "protocol_version": "3.0",
        }

    # P5: Vector/Embedding Support

    def get_vector_functions(self) -> dict[str, str]:
        """
        Get pgvector-compatible function mappings to IRIS vector functions

        Maps PostgreSQL/pgvector syntax to IRIS VECTOR functions
        """
        return {
            # Distance functions (pgvector compatibility)
            "vector_cosine_distance": "VECTOR_COSINE",
            "cosine_distance": "VECTOR_COSINE",
            "euclidean_distance": "VECTOR_DOT_PRODUCT",  # IRIS equivalent
            "inner_product": "VECTOR_DOT_PRODUCT",
            # Vector operations
            "vector_dims": "VECTOR_DIM",
            "vector_norm": "VECTOR_NORM",
            # IRIS-specific vector functions
            "to_vector": "TO_VECTOR",
            "vector_dot_product": "VECTOR_DOT_PRODUCT",
            "vector_cosine": "VECTOR_COSINE",
        }

    def translate_vector_query(self, sql: str) -> str:
        """
        P5: Translate pgvector syntax to IRIS VECTOR syntax

        Converts PostgreSQL/pgvector queries to use IRIS vector functions
        """
        try:
            vector_functions = self.get_vector_functions()
            translated_sql = sql

            # Replace pgvector operators with IRIS functions
            # <-> operator (cosine distance) -> VECTOR_COSINE
            if "<->" in translated_sql:
                # Pattern: column <-> '[1,2,3]' becomes VECTOR_COSINE(column, TO_VECTOR('[1,2,3]'))
                import re

                pattern = r"([\w\.]+)\s*<->\s*([^\s]+)"

                def replace_cosine(match):
                    col, vec = match.groups()
                    return f"VECTOR_COSINE({col}, TO_VECTOR({vec}))"

                translated_sql = re.sub(pattern, replace_cosine, translated_sql)

            # <#> operator (negative inner product) -> -VECTOR_DOT_PRODUCT
            if "<#>" in translated_sql:
                import re

                pattern = r"([\w\.]+)\s*<#>\s*([^\s]+)"

                def replace_inner_product(match):
                    col, vec = match.groups()
                    return f"(-VECTOR_DOT_PRODUCT({col}, TO_VECTOR({vec})))"

                translated_sql = re.sub(pattern, replace_inner_product, translated_sql)

            # <=> operator (cosine distance) -> VECTOR_COSINE
            if "<=>" in translated_sql:
                import re

                pattern = r"([\w\.]+)\s*<=>\s*([^\s]+)"

                def replace_cosine_distance(match):
                    col, vec = match.groups()
                    return f"VECTOR_COSINE({col}, TO_VECTOR({vec}))"

                translated_sql = re.sub(pattern, replace_cosine_distance, translated_sql)

            # Replace function names
            for pg_func, iris_func in vector_functions.items():
                translated_sql = translated_sql.replace(pg_func, iris_func)

            return translated_sql

        except Exception as e:
            logger.warning("Vector query translation failed", error=str(e), sql=sql[:100])
            return sql  # Return original if translation fails
