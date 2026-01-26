"""
IRIS SQL Executor for PostgreSQL Wire Protocol

Handles SQL execution against IRIS using embedded Python or external connection.
Based on patterns from caretdev/sqlalchemy-iris for proven IRIS integration.
"""

import asyncio
import concurrent.futures
import datetime as dt
import re
import threading
import time
from typing import Any

import structlog

from .catalog.oid_generator import OIDGenerator  # OID generation for catalog emulation

# IRIS POSIXTIME constants
POSIXTIME_OFFSET = 1152921504606846976
POSIXTIME_MAX = POSIXTIME_OFFSET + 7258118400000000  # ~2200-01-01
from .conversions import (
    BulkInsertJob,
    DdlErrorHandler,
    DdlSplitter,
    horolog_to_pg,
    pg_to_horolog,
)
from .schema_mapper import (
    IRIS_SCHEMA,
    translate_output_schema,
)  # Feature 030: PostgreSQL schema mapping
from .sql_translator import (
    SQLInterceptor,
    SQLPipeline,
    SQLTranslator,  # Feature 021: PostgreSQL→IRIS normalization
    TransactionTranslator,
)  # Feature 022: PostgreSQL transaction verb translation
from .sql_translator.parser import get_parser
from .sql_translator.alias_extractor import AliasExtractor  # Column alias preservation
from .sql_translator.performance_monitor import MetricType, PerformanceTracker, get_monitor
from .type_mapping import (
    get_type_mapping,
    load_type_mappings_from_file,
)  # Configurable type mapping

logger = structlog.get_logger()


class MockResult:
    """Mock result object for RETURNING emulation"""

    def __init__(self, rows, meta=None):
        self._rows = rows if rows is not None else []
        self._meta = meta
        self.description = meta
        self.rowcount = len(self._rows)
        self._index = 0

    def __iter__(self):
        return iter(self._rows)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        if self._index < len(self._rows):
            row = self._rows[self._index]
            self._index += 1
            return row
        return None

    def fetch(self):
        return self._rows

    def close(self):
        pass


class IRISExecutor:
    """
    IRIS SQL Execution Handler

    Manages SQL execution against IRIS database using embedded Python when available,
    or external connection as fallback. Implements patterns proven in caretdev
    SQLAlchemy implementation.
    """

    backend_type: str = "embedded"

    def __init__(
        self,
        iris_config: dict[str, Any],
        server=None,
        connection_pool_size: int = 10,
        connection_pool_timeout: float = 5.0,
        enable_query_cache: bool = True,
        query_cache_size: int = 1000,
    ):
        self.iris_config = iris_config
        self.server = server  # Reference to server for P4 cancellation
        self.connection_pool_size = connection_pool_size
        self.connection_pool_timeout = connection_pool_timeout
        self.enable_query_cache = enable_query_cache
        self.query_cache_size = query_cache_size

        self.connection = None
        self.session_connections = {}
        self.session_executors = {}  # Thread affinity: one executor per session
        self.session_namespaces = {}  # Feature 034: Per-session IRIS namespace
        self.embedded_mode = False
        self.backend_type = "embedded"  # Feature 018: Backend identification
        self.vector_support = False

        # Thread pool for async IRIS operations (constitutional requirement)
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=connection_pool_size, thread_name_prefix="iris_executor"
        )

        # Performance monitoring
        self.performance_monitor = get_monitor()

        # Column alias extraction for PostgreSQL compatibility
        self.alias_extractor = AliasExtractor()

        # DDL idempotency and splitting handlers
        self.ddl_handler = DdlErrorHandler()
        self.ddl_splitter = DdlSplitter()

        self.sql_pipeline = SQLPipeline()
        self.sql_interceptor = SQLInterceptor(self)
        self.sql_translator = self.sql_pipeline.translator
        self.sql_parser = get_parser()
        self.transaction_translator = TransactionTranslator()

        # Connection pool management
        self._connection_lock = threading.Condition(threading.RLock())
        self._connection_pool = []
        self._active_count = 0
        self._max_connections = connection_pool_size

        # Query cache (LRU)
        self._query_cache = {}
        self._query_cache_lock = threading.Lock()

        # Load custom type mappings from configuration file (if exists)
        # This allows users to customize IRIS→PostgreSQL type mappings
        # for ORM compatibility (Prisma, SQLAlchemy, etc.)
        load_type_mappings_from_file()

        # Attempt to detect IRIS environment
        self._detect_iris_environment()

        logger.info(
            "IRIS executor initialized",
            host=self.iris_config.get("host"),
            port=self.iris_config.get("port"),
            namespace=self.iris_config.get("namespace"),
            embedded_mode=self.embedded_mode,
        )

    def _import_iris(self):
        """
        Gracefully import InterSystems IRIS module.
        Handles both embedded Python and external driver environments.
        """
        try:
            import iris

            return iris
        except ImportError:
            try:
                # Fallback for some environments
                import intersystems_iris as iris

                return iris
            except ImportError:
                return None

    def _detect_iris_environment(self):
        """Detect if we're running in IRIS embedded Python environment"""
        iris = self._import_iris()
        if iris:
            # Check if we're in embedded mode by testing for embedded-specific features
            if hasattr(iris, "sql") and hasattr(iris.sql, "exec"):
                self.embedded_mode = True
                print("🚀 IRIS embedded Python detected", flush=True)
                logger.info("IRIS embedded Python detected")
                return True
            else:
                # We have iris module but not embedded - use external connection
                self.embedded_mode = False
                print("🔌 IRIS Python driver available, using external connection", flush=True)
                logger.info("IRIS Python driver available, using external connection")
                return False
        else:
            self.embedded_mode = False
            print("❌ IRIS Python driver not available", flush=True)
            logger.info("IRIS Python driver not available")
            return False

    def set_session_namespace(self, session_id: str, namespace: str):
        """Set the IRIS namespace for a specific session (Feature 034)."""
        with self._connection_lock:
            self.session_namespaces[session_id] = namespace
            logger.info("Session namespace registered", session_id=session_id, namespace=namespace)

    def _get_session_namespace(self, session_id: str | None) -> str:
        """Get the effective namespace for a session."""
        if session_id and session_id in self.session_namespaces:
            return self.session_namespaces[session_id]
        return self.iris_config.get("namespace", "USER")

    def _get_executor(self, session_id: str | None = None) -> concurrent.futures.Executor:
        """
        Get the appropriate executor for the given session.
        Ensures thread affinity for sessions by using a dedicated single-threaded executor.
        """
        if not session_id:
            return self.thread_pool

        with self._connection_lock:
            if session_id not in self.session_executors:
                self.session_executors[session_id] = concurrent.futures.ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix=f"iris_session_{session_id}"
                )
            return self.session_executors[session_id]

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

    def _get_normalized_sql(self, sql: str, execution_path: str = "direct") -> str:
        if not self.enable_query_cache:
            return self.sql_translator.normalize_sql(sql, execution_path=execution_path)

        cache_key = (sql, execution_path)
        with self._query_cache_lock:
            if cache_key in self._query_cache:
                val = self._query_cache.pop(cache_key)
                self._query_cache[cache_key] = val
                return val

        normalized = self.sql_translator.normalize_sql(sql, execution_path=execution_path)

        with self._query_cache_lock:
            if cache_key in self._query_cache:
                self._query_cache.pop(cache_key)

            self._query_cache[cache_key] = normalized
            if len(self._query_cache) > self.query_cache_size:
                try:
                    self._query_cache.pop(next(iter(self._query_cache)))
                except (StopIteration, KeyError):
                    pass

        return normalized

    def _convert_iris_horolog_date_to_pg(self, horolog_days: int) -> int:
        """Convert IRIS Horolog date to PostgreSQL date format using centralized utility."""
        return horolog_to_pg(horolog_days)

    def _convert_pg_date_to_iris_horolog(self, pg_days: int) -> int:
        """Convert PostgreSQL date format to IRIS Horolog date using centralized utility."""
        return pg_to_horolog(pg_days)

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

    def has_returning_clause(self, query: str) -> bool:
        """
        Check if query has a RETURNING clause.
        """
        if not query:
            return False
        return bool(re.search(r"\bRETURNING\b", query, re.IGNORECASE | re.DOTALL))

    def _get_table_columns_from_schema(
        self, table: str, session_id: str | None = None
    ) -> list[str]:
        """
        Query INFORMATION_SCHEMA.COLUMNS for the given table.
        Returns the list of column names in order.
        """
        try:
            table_clean = table.strip('"').strip("'")
            metadata_sql = f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER('{table_clean}')
                AND LOWER(TABLE_SCHEMA) = LOWER('{IRIS_SCHEMA}')
                ORDER BY ORDINAL_POSITION
            """
            if self.embedded_mode:
                iris = self._import_iris()
                if iris:
                    result = iris.sql.exec(metadata_sql)
                    return [row[0] for row in result]
                else:
                    logger.warning("IRIS module not available in embedded mode")
            else:
                conn = self._get_pooled_connection(session_id=session_id)
                cursor = conn.cursor()
                try:
                    cursor.execute(metadata_sql)
                    rows = cursor.fetchall()
                    return [row[0] for row in rows]
                finally:
                    cursor.close()
                    self._return_connection(conn, session_id=session_id)
        except Exception as e:
            logger.debug(f"Failed to get columns from schema for {table}: {e}")
        return []

    def _get_column_type_from_schema(
        self, table: str, column: str, session_id: str | None = None
    ) -> int | None:
        """
        Query INFORMATION_SCHEMA.COLUMNS for the given table and column.
        Returns the PostgreSQL type OID.
        """
        try:
            table_clean = table.strip('"').strip("'")
            column_clean = column.strip('"').strip("'")
            metadata_sql = f"""
                SELECT DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER('{table_clean}')
                AND LOWER(COLUMN_NAME) = LOWER('{column_clean}')
                AND LOWER(TABLE_SCHEMA) = LOWER('{IRIS_SCHEMA}')
            """
            if self.embedded_mode:
                iris = self._import_iris()
                if iris:
                    result = iris.sql.exec(metadata_sql)
                    row = next(iter(result), None)
                else:
                    row = None
            else:
                conn = self._get_pooled_connection(session_id=session_id)
                cursor = conn.cursor()
                try:
                    cursor.execute(metadata_sql)
                    row = cursor.fetchone()
                finally:
                    cursor.close()
                    self._return_connection(conn, session_id=session_id)

            if row:
                iris_type = row[0]
                return self._map_iris_type_to_oid(iris_type)
        except Exception as e:
            logger.debug(f"Failed to get type from schema for {table}.{column}: {e}")
        return None

    def _infer_type_from_value(self, value, column_name: str | None = None) -> int:
        """
        Infer PostgreSQL type OID from Python value

        Args:
            value: Python value from result row
            column_name: Optional column name for better inference

        Returns:
            PostgreSQL type OID (int)
        """
        # Import Decimal for type checking
        from decimal import Decimal

        # INT4 range limits
        INT4_MIN = -2147483648  # -2^31
        INT4_MAX = 2147483647  # 2^31 - 1

        if value is None:
            return 1043  # VARCHAR (most flexible for NULL)
        elif isinstance(value, bool):
            return 16  # BOOL
        elif isinstance(value, int):
            # IRIS POSIXTIME detection (1114)
            if POSIXTIME_OFFSET <= value <= POSIXTIME_MAX:
                return 1114  # TIMESTAMP

            # BIGINT (20) for ID/Key columns or if value exceeds INT4 range
            if column_name and any(k in column_name.lower() for k in ("id", "key")):
                return 20  # BIGINT
            if INT4_MIN <= value <= INT4_MAX:
                return 23  # INTEGER (INT4)
            else:
                return 20  # BIGINT (INT8) for large integers
        elif isinstance(value, float):
            return 701  # FLOAT8/DOUBLE
        elif isinstance(value, Decimal):
            return 1700  # NUMERIC/DECIMAL
        elif isinstance(value, bytes):
            return 17
        elif isinstance(value, dt.datetime):
            return 1114
        elif isinstance(value, dt.date):
            return 1082
        elif isinstance(value, str):
            # Check for UUID pattern
            uuid_pattern = (
                r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
            )
            if re.match(uuid_pattern, value):
                return 2950  # UUID

            # Explicitly return VARCHAR (1043) for all other strings
            # Feature 036 fix: Avoid mapping to INT4 or other types even if numeric
            return 1043  # VARCHAR
        else:
            return 1043  # Default to VARCHAR

    def _serialize_value(self, value: Any, type_oid: int) -> Any:
        """
        Robust value serialization for PostgreSQL wire protocol compatibility.
        Converts IRIS-specific types (like microsecond timestamps) to protocol-friendly formats.
        """
        if value is None:
            return None

        # OID 1114 = TIMESTAMP
        if type_oid == 1114:
            if isinstance(value, int):
                # Convert IRIS/PostgreSQL microsecond integer to ISO8601 string
                try:
                    import datetime

                    if value >= POSIXTIME_OFFSET:
                        # IRIS POSIXTIME (microseconds since 1970-01-01)
                        unix_us = value - POSIXTIME_OFFSET
                        epoch = datetime.datetime(1970, 1, 1)
                        ts_obj = epoch + datetime.timedelta(microseconds=unix_us)
                    else:
                        # PostgreSQL legacy/IRIS microsecond integer (microseconds since 2000-01-01)
                        epoch = datetime.datetime(2000, 1, 1)
                        ts_obj = epoch + datetime.timedelta(microseconds=value)

                    # Return ISO8601 string preferred by node-postgres and other clients
                    return ts_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                except Exception:
                    return value
            elif isinstance(value, dt.datetime):
                return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # OID 1082 = DATE
        if type_oid == 1082 and isinstance(value, int):
            # IRIS Horolog to PG Days already handled in row loop, but for safety:
            return value

        return value

    def _split_sql_statements(self, sql: str) -> list[str]:
        """
        Split SQL string into individual statements, handling semicolons properly.
        Uses DdlSplitter for robust comment and quote-aware splitting.

        Args:
            sql: SQL string potentially containing multiple statements

        Returns:
            List of individual SQL statements (semicolons removed, whitespace stripped)
        """
        # Phase 1: Robust splitting by semicolons
        statements = self.ddl_splitter.split(sql)

        # Phase 2: Split multi-action ALTER TABLE statements
        final_statements = []
        for stmt in statements:
            if stmt.upper().startswith("ALTER TABLE"):
                split_ddl = self.ddl_splitter.split_alter_table(stmt)
                final_statements.extend(split_ddl)
            else:
                final_statements.append(stmt)

        logger.debug(
            "Split SQL into statements",
            total_statements=len(final_statements),
            original_statements=len(statements),
            original_length=len(sql),
        )

        return final_statements

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

        def _sync_test(captured_self, captured_iris):
            if captured_iris is None:
                return False
            # Simple test query
            result = captured_iris.sql.exec("SELECT 1 as test_column").fetch()
            return result[0]["test_column"] == 1

        iris = self._import_iris()

        # Run in thread to avoid blocking asyncio loop
        result = await asyncio.to_thread(_sync_test, self, iris)
        if not result:
            raise RuntimeError("IRIS embedded test query failed")

    async def _test_external_connection(self):
        """Test external IRIS connection using intersystems driver"""
        try:

            def _sync_test(captured_self, captured_iris_config, captured_iris):
                # Test real connection to IRIS
                try:
                    if captured_iris is None:
                        raise ImportError("IRIS module not available")

                    conn = captured_iris.connect(
                        hostname=captured_iris_config["host"],
                        port=captured_iris_config["port"],
                        namespace=captured_iris_config["namespace"],
                        username=captured_iris_config["username"],
                        password=captured_iris_config["password"],
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
                        if key not in captured_iris_config:
                            raise ValueError(f"Missing IRIS config: {key}")
                    return True

            iris = self._import_iris()

            result = await asyncio.to_thread(_sync_test, self, self.iris_config, iris)

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

                def _sync_vector_test(captured_self, captured_iris):
                    try:
                        if captured_iris is None:
                            return False
                        # Test query from caretdev implementation
                        captured_iris.sql.exec("select vector_cosine(to_vector('1'), to_vector('1'))")
                        return True
                    except Exception as e:
                        # Vector support not available (license or feature not enabled)
                        logger.debug("Vector test query failed", error=str(e))
                        return False

                iris = self._import_iris()

                result = await asyncio.to_thread(_sync_vector_test, self, iris)

                self.vector_support = result
                if result:
                    logger.info("IRIS vector support detected")
                else:
                    logger.info("IRIS vector support not available (license or feature disabled)")

            else:
                # For external connections, test using DBAPI
                def _sync_vector_test_external(captured_self):
                    connection = None
                    try:
                        connection = captured_self._get_pooled_connection()
                        cursor = connection.cursor()
                        cursor.execute("select vector_cosine(to_vector('1'), to_vector('1'))")
                        cursor.fetchone()
                        cursor.close()
                        return True
                    except Exception as e:
                        logger.debug("Vector test query failed (external)", error=str(e))
                        return False
                    finally:
                        if connection:
                            captured_self._return_connection(connection)

                result = await asyncio.to_thread(_sync_vector_test_external, self)
                self.vector_support = result
                if result:
                    logger.info("IRIS vector support detected (external)")
                else:
                    logger.info("IRIS vector support not available (external)")

        except Exception as e:
            self.vector_support = False
            logger.info("IRIS vector support test failed", error=str(e))

    def _normalize_parameters(self, params: list | tuple | None) -> list:
        """
        Normalize parameters for IRIS compatibility.
        - Normalize ISO 8601 timestamp strings (strip T/Z/offsets)
        - Convert PostgreSQL epoch timestamps (int) to IRIS format
        - Convert Python lists to IRIS vector strings [...]
        """
        if not params:
            return []

        # Constants for timestamp conversion
        PG_EPOCH = dt.datetime(2000, 1, 1)
        MIN_TIMESTAMP = 500_000_000_000_000  # ~2015
        MAX_TIMESTAMP = 1_500_000_000_000_000  # ~2047

        new_params = list(params)
        for i, param in enumerate(new_params):
            if isinstance(param, int) and MIN_TIMESTAMP < param < MAX_TIMESTAMP:
                # PostgreSQL timestamp in microseconds
                try:
                    timestamp_obj = PG_EPOCH + dt.timedelta(microseconds=param)
                    new_params[i] = timestamp_obj.strftime("%Y-%m-%d %H:%M:%S.%f")
                    logger.debug(
                        "Converted PostgreSQL timestamp to IRIS format",
                        param_index=i,
                        original_value=param,
                        converted_value=new_params[i],
                    )
                except (ValueError, OverflowError) as e:
                    logger.warning(
                        "Failed to convert timestamp parameter",
                        param_index=i,
                        value=param,
                        error=str(e),
                    )
            elif isinstance(param, str):
                # FR-004: Normalize ISO 8601 timestamp strings for IRIS
                # Handles: YYYY-MM-DD[T ]HH:MM:SS[.fff][Z|[+-]HH:MM]
                ts_match = re.match(
                    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?:Z|[+-]\d{2}:?(\d{2})?)?$",
                    param,
                )
                if ts_match:
                    new_params[i] = f"{ts_match.group(1)} {ts_match.group(2)}"
                    logger.debug(
                        "Normalized ISO timestamp parameter",
                        original=param,
                        normalized=new_params[i],
                    )
            elif isinstance(param, list):
                # Feature 026: Convert Python list to IRIS vector string format [...]
                new_params[i] = "[" + ",".join(str(float(v)) for v in param) + "]"
                logger.debug(
                    "Converted list parameter to IRIS vector format",
                    param_index=i,
                    vector_length=len(param),
                )
        return new_params

    async def execute_query(
        self, sql: str, params: list | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute SQL query against IRIS with proper async threading
        """
        try:
            # Feature 022: Apply PostgreSQL→IRIS transaction verb translation FIRST
            sql = self.transaction_translator.translate_transaction_command(sql)

            intercept_result = self.sql_interceptor.intercept(sql, params, session_id)
            if intercept_result.intercepted:
                return intercept_result.result

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

                # Feature 026: Handle DDL idempotency (IF NOT EXISTS)
                # Check both for raised exceptions and for success=False results
                if not result.get("success", True):
                    error_msg = result.get("error", "")
                    ddl_result = self.ddl_handler.handle(sql, Exception(error_msg))
                    if ddl_result.success and ddl_result.skipped:
                        logger.info(
                            f"DDL idempotency: skipped '{ddl_result.object_name}' because it already exists",
                            sql=sql[:100],
                        )
                        result = {
                            "success": True,
                            "rows": [],
                            "columns": [],
                            "row_count": 0,
                            "command": ddl_result.command,
                            "command_tag": f"{ddl_result.command} 0",
                        }
                elif "error" in result and not result.get("success", True):
                    # Fallback for other result formats
                    pass

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

        NEW: Integrates BulkInsertJob for tracking and supports native fast-insert path
        with string inlining fallback for maximum reliability.
        
        RETURNING SUPPORT: When SQL contains RETURNING clause, executes each INSERT
        individually and aggregates the returned rows from all inserts.
        """
        job = BulkInsertJob(
            table_name=self._extract_table_name(sql) or "unknown", total_rows=len(params_list)
        )
        job.mark_started()

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
                    job_id=job.job_id,
                )

                # Check for RETURNING clause - requires special handling
                if self.has_returning_clause(sql):
                    result = await self._execute_many_with_returning(
                        sql, params_list, session_id
                    )
                    job.mark_completed(rows_inserted=result.get("rows_affected", len(params_list)))
                else:
                    # ALWAYS try native fast-insert path first
                    try:
                        result = await self._execute_many_native(sql, params_list, session_id)
                        job.mark_completed(rows_inserted=result.get("rows_affected", len(params_list)))
                    except Exception as native_error:
                        logger.warning(
                            "Native executemany() failed, falling back to string inlining",
                            error=str(native_error)[:200],
                            session_id=session_id,
                        )
                        # Fallback to string inlining (reliable but slower)
                        result = await self._execute_many_inline_fallback(sql, params_list, session_id)
                        job.mark_completed(rows_inserted=result.get("rows_affected", len(params_list)))

                # Add performance metadata
                result["execution_metadata"] = {
                    "execution_time_ms": tracker.start_time
                    and (time.perf_counter() - tracker.start_time) * 1000,
                    "embedded_mode": self.embedded_mode,
                    "execution_path": result.get("_execution_path", "unknown"),
                    "batch_size": len(params_list),
                    "session_id": session_id,
                    "rows_per_second": job.rows_per_second(),
                    "job_id": job.job_id,
                }

                return result
        except Exception as e:
            job.mark_failed(str(e))
            raise

    async def _execute_many_with_returning(
        self, sql: str, params_list: list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute batch INSERT/UPDATE/DELETE with RETURNING clause.
        
        Since IRIS doesn't support native RETURNING, we execute each statement
        individually and aggregate the returned rows.
        
        Returns: dict with 'rows' containing all returned rows from all inserts.
        """
        # Parse the RETURNING clause
        operation, table, columns, where_clause, stripped_sql = self._parse_returning_clause(sql)
        
        if not operation or not table:
            logger.warning(
                "Could not parse RETURNING clause, falling back to standard execute_many",
                sql=sql[:100],
                session_id=session_id,
            )
            return await self._execute_many_native(sql, params_list, session_id)
        
        logger.info(
            "execute_many with RETURNING: processing batch individually",
            operation=operation,
            table=table,
            columns=columns,
            batch_size=len(params_list),
            session_id=session_id,
        )
        
        all_rows = []
        all_meta = None
        
        for i, params in enumerate(params_list):
            # Execute the stripped SQL (without RETURNING)
            try:
                if self.embedded_mode:
                    iris = self._import_iris()
                    if iris:
                        normalized_params = self._normalize_parameters(params)
                        if normalized_params:
                            iris.sql.exec(stripped_sql, *normalized_params)
                        else:
                            iris.sql.exec(stripped_sql)
                else:
                    conn = self._get_pooled_connection(session_id=session_id)
                    cursor = conn.cursor()
                    try:
                        normalized_params = self._normalize_parameters(params)
                        if normalized_params:
                            cursor.execute(stripped_sql, tuple(normalized_params))
                        else:
                            cursor.execute(stripped_sql)
                        conn.commit()
                    finally:
                        cursor.close()
                        self._return_connection(conn, session_id=session_id)
                
                # Emulate RETURNING for this row
                rows, meta = self._emulate_returning(
                    operation=operation,
                    table=table,
                    columns=columns,
                    where_clause=where_clause,
                    params=params,
                    is_embedded=self.embedded_mode,
                    session_id=session_id,
                    original_sql=sql,
                )
                
                if rows:
                    all_rows.extend(rows)
                if meta and not all_meta:
                    all_meta = meta
                    
            except Exception as e:
                logger.error(
                    "execute_many with RETURNING: row failed",
                    row_index=i,
                    error=str(e),
                    session_id=session_id,
                )
                raise
        
        logger.info(
            "execute_many with RETURNING: completed",
            total_rows_returned=len(all_rows),
            batch_size=len(params_list),
            session_id=session_id,
        )
        
        # Build column info from metadata
        columns_info = []
        if all_meta:
            for col_info in all_meta:
                if isinstance(col_info, dict):
                    columns_info.append(col_info)
                elif hasattr(col_info, "name"):
                    columns_info.append({"name": col_info.name, "type_oid": 1043})
        
        return {
            "success": True,
            "rows": all_rows,
            "columns": columns_info,
            "rows_affected": len(params_list),
            "_execution_path": "execute_many_with_returning",
        }

    async def _execute_many_native(
        self, sql: str, params_list: list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """Native executemany with parameter binding using DBAPI."""
        return await self._execute_many_external_async(sql, params_list, session_id)

    async def _execute_many_inline_fallback(
        self, sql: str, params_list: list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """Fallback to string inlining for batch operations."""
        if self.embedded_mode:
            return await self._execute_many_embedded_async(sql, params_list, session_id)
        else:
            # NEW: Implement robust fallback for external mode
            # This executes each INSERT individually in the sequence
            logger.warning(
                "Using sequential fallback for external batch operation", 
                session_id=session_id,
                batch_size=len(params_list)
            )
            rows_affected = 0
            for params in params_list:
                await self.execute_query(sql, params, session_id)
                rows_affected += 1
            
            return {
                "success": True,
                "rows_affected": rows_affected,
                "_execution_path": "execute_many_sequential_fallback",
            }

    async def close(self) -> None:
        """Close executor and resources. Part of Executor protocol."""
        if self.thread_pool:
            self.thread_pool.shutdown(wait=True)
        
        # Close all active connections
        for conn in self.session_connections.values():
            try:
                conn.close()
            except:
                pass
        self.session_connections.clear()
        
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection = None

    def _extract_table_name(self, sql: str) -> str | None:
        """Extract table name from INSERT statement."""
        match = re.search(r"INSERT\s+INTO\s+(\w+)", sql, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    async def _execute_many_embedded_async(
        self, sql: str, params_list: list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute batch SQL using IRIS embedded Python executemany() with proper async threading.

        This method leverages IRIS's native batch execution capabilities for maximum performance.
        """

        def _sync_execute_many(sql, params_list, session_id):
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
            iris = self._import_iris()
            if not iris:
                return {
                    "success": False,
                    "error": "IRIS module not found",
                    "rows": [],
                    "columns": [],
                    "row_count": 0,
                    "command_tag": "ERROR",
                    "execution_time_ms": 0,
                }

            logger.info(
                "🚀 EXECUTING BATCH IN EMBEDDED MODE (loop-based)",
                sql_preview=sql[:100],
                batch_size=len(params_list),
                session_id=session_id,
            )

            try:
                # Ensure correct namespace context in background thread (Feature 022)
                if hasattr(iris, "system") and hasattr(iris.system, "Process"):
                    iris.system.Process.SetNamespace(self.iris_config.get("namespace", "USER"))

                # Feature 022: Apply PostgreSQL→IRIS transaction verb translation
                transaction_translated_sql = (
                    self.transaction_translator.translate_transaction_command(sql)
                )

                # Feature 021: Apply PostgreSQL→IRIS SQL normalization
                normalized_sql = self._get_normalized_sql(
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
                for row_params in params_list:
                    inline_sql = "N/A"
                    try:
                        # Build inline SQL by replacing ? placeholders with actual values
                        inline_sql = normalized_sql
                        for param_value in row_params:
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
                            params=row_params[:3] if len(row_params) > 3 else row_params,
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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._get_executor(session_id), _sync_execute_many, sql, params_list, session_id
        )

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

        def _sync_execute_many(sql, params_list, session_id):
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
                connection = self._get_pooled_connection(session_id=session_id)

                # Feature 022: Apply PostgreSQL→IRIS transaction verb translation
                transaction_translated_sql = (
                    self.transaction_translator.translate_transaction_command(sql)
                )

                # Feature 021: Apply PostgreSQL→IRIS SQL normalization
                normalized_sql = self._get_normalized_sql(
                    transaction_translated_sql, execution_path="batch"
                )

                # Normalize each parameter set in the batch
                final_params_list = []
                for p_set in params_list:
                    final_params_list.append(self._normalize_parameters(p_set))

                # Strip trailing semicolon
                if normalized_sql.rstrip().endswith(";"):
                    normalized_sql = normalized_sql.rstrip().rstrip(";")

                # Pre-process parameters to convert lists to IRIS vector strings
                # This ensures the DBAPI driver doesn't convert them to {...} format
                if final_params_list:
                    # FAST PATH: Check if any processing is needed
                    needs_processing = False
                    first_batch = final_params_list[0]
                    for p in first_batch:
                        if isinstance(p, list):
                            needs_processing = True
                            break

                    if needs_processing:
                        processed_params_list = []
                        for params_batch in final_params_list:
                            processed_params = [
                                "[" + ",".join(map(str, p)) + "]" if isinstance(p, list) else p
                                for p in params_batch
                            ]
                            processed_params_list.append(processed_params)
                        final_params_list = processed_params_list

                logger.info(
                    "Executing executemany() batch (external mode)",
                    sql_preview=normalized_sql[:100],
                    batch_size=len(final_params_list),
                    session_id=session_id,
                )

                # Execute batch using DBAPI cursor.executemany()
                # KEY OPTIMIZATION: Uses IRIS "Fast Insert" feature
                start_time = time.perf_counter()

                cursor = connection.cursor()
                cursor.executemany(normalized_sql, final_params_list)

                execution_time = (time.perf_counter() - start_time) * 1000
                rows_affected = (
                    cursor.rowcount if hasattr(cursor, "rowcount") else len(final_params_list)
                )

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
                    "batch_size": len(final_params_list),
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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._get_executor(session_id), _sync_execute_many, sql, params_list, session_id
        )

    def _split_multi_row_insert(self, sql: str) -> list[str]:
        """
        Split a multi-row INSERT statement into individual INSERT statements.

        IRIS doesn't support INSERT INTO table (cols) VALUES (...), (...).
        This method converts it to multiple single-row INSERTs.
        """
        # Match: INSERT INTO table (cols) VALUES (v1), (v2), ...
        # Pattern captures: prefix (up to VALUES), and the values part
        pattern = re.compile(
            r"(INSERT\s+INTO\s+[\w\.\"]+\s*(?:\([^)]+\))?\s*VALUES\s*)(.+)",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(sql)
        if not match:
            return [sql]

        prefix = match.group(1)
        values_part = match.group(2).strip()

        # Split values by ), but be careful with nested parentheses
        # For simplicity, we match ), followed by whitespace and (
        rows = re.split(r"\s*\)\s*,\s*\(", values_part)

        if len(rows) <= 1:
            return [sql]

        # Reconstruct individual statements
        statements = []
        for i, row in enumerate(rows):
            clean_row = row.strip()
            if i == 0:
                if not clean_row.endswith(")"):
                    clean_row += ")"
            elif i == len(rows) - 1:
                if not clean_row.startswith("("):
                    clean_row = "(" + clean_row
            else:
                if not clean_row.startswith("("):
                    clean_row = "(" + clean_row
                if not clean_row.endswith(")"):
                    clean_row += ")"

            # Ensure semicolon termination for each statement
            stmt = f"{prefix}{clean_row}"
            if not stmt.endswith(";"):
                stmt += ";"
            statements.append(stmt)

        return statements

    def _safe_execute(
        self,
        sql: str,
        params: list | None = None,
        is_embedded: bool = True,
        session_id: str | None = None,
    ) -> Any:
        """Execute SQL with DDL idempotency handling."""
        iris = self._import_iris()
        if not iris:
            raise RuntimeError("IRIS module not available")

        # Skip execution for empty statements or comment-only statements
        # This avoids sending no-op SQL or comments to the IRIS SQL engine
        sql_stripped = sql.strip() if sql else ""
        if (
            not sql_stripped
            or (sql_stripped.startswith("--") and "\n" not in sql_stripped)
            or (sql_stripped.startswith("/*") and sql_stripped.endswith("*/"))
        ):

            class SkipCursor:
                def __init__(self):
                    self.description = None
                    self.rowcount = 0

                def close(self):
                    pass

                def fetchall(self):
                    return []

                def fetchone(self):
                    return None

                def __iter__(self):
                    return iter([])

            return SkipCursor()

        # CRITICAL FIX: Strip trailing semicolon for ALL execution paths
        # IRIS SQL engine often fails if a semicolon is present at the end of DDL
        # or parameterized queries when sent via driver or iris.sql.exec().
        if sql:
            sql = sql.strip().rstrip(";")

        try:
            if is_embedded:
                # Embedded mode - return cursor-like object
                if params is not None and len(params) > 0:
                    # CRITICAL FIX: iris.sql.exec() doesn't properly handle None for
                    # nullable FK columns - causes referential integrity failures.
                    # When params contain None, inline the values instead of binding.
                    if any(p is None for p in params):
                        inline_sql = sql
                        for param_value in params:
                            if param_value is None:
                                sql_literal = "NULL"
                            elif isinstance(param_value, bool):
                                # IRIS expects 1/0 for BIT columns
                                sql_literal = "1" if param_value else "0"
                            elif isinstance(param_value, int | float):
                                sql_literal = str(param_value)
                            else:
                                # Strings need quoting and escaping
                                escaped_value = str(param_value).replace("'", "''")
                                sql_literal = f"'{escaped_value}'"
                            inline_sql = inline_sql.replace("?", sql_literal, 1)
                        logger.debug(
                            "Using inline SQL for None params",
                            original_sql=sql[:100],
                            inline_sql=inline_sql[:100],
                        )
                        return iris.sql.exec(inline_sql)
                    return iris.sql.exec(sql, *params)
                return iris.sql.exec(sql)

            else:
                # External mode - use DBAPI cursor
                connection = self._get_pooled_connection(session_id=session_id)
                cursor = connection.cursor()
                try:
                    if params is not None:
                        dbapi_params = tuple(params) if isinstance(params, list) else params
                        cursor.execute(sql, dbapi_params)
                    else:
                        cursor.execute(sql)
                    return cursor
                except Exception as e:
                    # Don't close cursor here, let the caller handle it
                    # But if execution failed, we might need to cleanup
                    raise e
        except Exception as e:
            result = self.ddl_handler.handle(sql, e)
            if result.success and result.skipped:
                # Return a dummy cursor object that has a None description
                class DummyCursor:
                    def __init__(self):
                        self.description = None
                        self.rowcount = 0

                    def close(self):
                        pass

                    def fetchall(self):
                        return []

                    def fetchone(self):
                        return None

                    def __iter__(self):
                        return iter([])

                return DummyCursor()
            raise e

    def _parse_returning_clause(
        self, sql: str
    ) -> tuple[str | None, str | None, Any, str | None, str]:
        """
        Parse RETURNING clause from SQL and return metadata.
        Returns: (operation, table, columns, where_clause, stripped_sql)
        """
        import re

        returning_operation = None
        returning_table = None
        returning_columns = None
        returning_where_clause = None
        stripped_sql = sql

        # Use improved regex to handle trailing semicolons and greedy matching
        # Pattern: look for RETURNING followed by anything until semicolon or end of string
        returning_pattern = r"\s+RETURNING\s+(.*?)($|;)"
        returning_match = re.search(returning_pattern, sql, re.IGNORECASE | re.DOTALL)

        if not returning_match:
            return None, None, None, None, sql

        returning_clause = returning_match.group(1).strip()

        # Parse column names from RETURNING clause
        if returning_clause == "*":
            returning_columns = "*"
        else:
            # Parse column names from RETURNING clause
            # Or just: col1, col2, ...
            raw_cols = [c.strip() for c in returning_clause.split(",")]
            returning_columns = []
            for col in raw_cols:
                # Extract just the column name (last part after dots)
                # Handle aliased columns like "col AS alias"
                if " AS " in col.upper():
                    col_match = re.search(r'"?(\w+)"?\s*$', col)
                else:
                    col_match = re.search(r'"?(\w+)"?\s*$', col)

                if col_match:
                    returning_columns.append(col_match.group(1).lower())

        # Determine operation type and extract table/where clause
        sql_upper = sql.upper().strip()
        if sql_upper.startswith("INSERT"):
            returning_operation = "INSERT"
            table_match = re.search(
                rf'INSERT\s+INTO\s+(?:{re.escape(IRIS_SCHEMA)}\s*\.\s*)?"?(\w+)"?',
                sql,
                re.IGNORECASE,
            )
            if table_match:
                returning_table = table_match.group(1)
        elif sql_upper.startswith("UPDATE"):
            returning_operation = "UPDATE"
            table_match = re.search(
                rf'UPDATE\s+(?:{re.escape(IRIS_SCHEMA)}\s*\.\s*)?"?(\w+)"?',
                sql,
                re.IGNORECASE,
            )
            if table_match:
                returning_table = table_match.group(1)
            # Extract WHERE clause (everything between WHERE and RETURNING)
            where_match = re.search(
                r"\bWHERE\s+(.+?)\s+RETURNING\b",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
            if where_match:
                returning_where_clause = where_match.group(1).strip()
        elif sql_upper.startswith("DELETE"):
            returning_operation = "DELETE"
            table_match = re.search(
                rf'DELETE\s+FROM\s+(?:{re.escape(IRIS_SCHEMA)}\s*\.\s*)?"?(\w+)"?',
                sql,
                re.IGNORECASE,
            )
            if table_match:
                returning_table = table_match.group(1)
            # Extract WHERE clause
            where_match = re.search(
                r"\bWHERE\s+(.+?)\s+RETURNING\b",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
            if where_match:
                returning_where_clause = where_match.group(1).strip()

        stripped_sql = re.sub(
            r"\s+RETURNING\s+.*?(?=$|;)",
            "",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
            count=1,
        )

        return (
            returning_operation,
            returning_table,
            returning_columns,
            returning_where_clause,
            stripped_sql,
        )

    def _extract_insert_id_from_sql(
        self, sql: str, params: list | None, session_id: str | None = None
    ) -> tuple[str | None, Any]:
        """
        Extract the ID value from an INSERT statement for UUID-based systems.
        
        Returns: (id_column_name, id_value) or (None, None) if not found.
        
        Handles:
        - INSERT INTO table (id, col1, col2) VALUES ($1, $2, $3) with params
        - INSERT INTO table (id, col1, col2) VALUES ('uuid', 'val1', 'val2') with literals
        """
        import re
        
        # Parse column list from INSERT
        col_match = re.search(
            r'INSERT\s+INTO\s+[^\s(]+\s*\(\s*([^)]+)\s*\)',
            sql,
            re.IGNORECASE
        )
        if not col_match:
            return None, None
            
        columns_str = col_match.group(1)
        columns = [c.strip().strip('"').strip("'").lower() for c in columns_str.split(',')]
        
        # Find ID column position (common names: id, uuid, _id)
        id_col_names = ['id', 'uuid', '_id']
        id_col_idx = None
        id_col_name = None
        for i, col in enumerate(columns):
            if col in id_col_names:
                id_col_idx = i
                id_col_name = col
                break
        
        if id_col_idx is None:
            return None, None
        
        # Extract value at that position
        # Check if we have params (parameterized query)
        if params and len(params) > id_col_idx:
            id_value = params[id_col_idx]
            logger.debug(
                "Extracted ID from params",
                id_column=id_col_name,
                id_value=str(id_value)[:50],
                session_id=session_id,
            )
            return id_col_name, id_value
        
        # Try to parse from VALUES clause (literal values)
        values_match = re.search(
            r'VALUES\s*\(\s*(.+?)\s*\)',
            sql,
            re.IGNORECASE | re.DOTALL
        )
        if values_match:
            values_str = values_match.group(1)
            # Split by comma, but respect quoted strings
            values = []
            current = ""
            in_quote = False
            quote_char = None
            for char in values_str:
                if char in ("'", '"') and not in_quote:
                    in_quote = True
                    quote_char = char
                    current += char
                elif char == quote_char and in_quote:
                    in_quote = False
                    quote_char = None
                    current += char
                elif char == ',' and not in_quote:
                    values.append(current.strip())
                    current = ""
                else:
                    current += char
            if current.strip():
                values.append(current.strip())
            
            if len(values) > id_col_idx:
                id_value = values[id_col_idx].strip("'").strip('"')
                logger.debug(
                    "Extracted ID from VALUES literal",
                    id_column=id_col_name,
                    id_value=str(id_value)[:50],
                    session_id=session_id,
                )
                return id_col_name, id_value
        
        return None, None

    def _emulate_returning(
        self,
        operation: str,
        table: str,
        columns: list[str] | str,
        where_clause: str | None,
        params: list | None,
        is_embedded: bool,
        connection: Any = None,
        session_id: str | None = None,
        original_sql: str | None = None,
    ) -> tuple[list[Any], Any]:
        """
        Emulate PostgreSQL RETURNING clause for IRIS.

        Returns: (rows, metadata)
        """
        import re

        # CRITICAL FIX: Normalize table name to UPPERCASE for IRIS compatibility
        # IRIS stores table names in uppercase in INFORMATION_SCHEMA
        table_normalized = table.upper() if table else table

        # Handle columns as list or '*'
        if columns == "*":
            col_list = "*"
        else:
            col_list = ", ".join([f'"{col}"' for col in columns])

        rows = []
        meta = None

        # Helper to execute and materialize results
        def _fetch_results(captured_sql, select_params=None):
            if is_embedded:
                iris = self._import_iris()
                if iris:
                    res = iris.sql.exec(captured_sql, *select_params) if select_params else iris.sql.exec(captured_sql)
                    return list(res), getattr(res, "_meta", None)
                return [], None
            else:
                cursor = connection.cursor()
                if select_params:
                    fetch_params = (
                        tuple(select_params) if isinstance(select_params, list) else select_params
                    )
                    cursor.execute(captured_sql, fetch_params)
                else:
                    cursor.execute(captured_sql)
                r = cursor.fetchall()
                m = cursor.description
                cursor.close()
                return r, m

        try:
            if operation == "INSERT":
                # Method 1: Try LAST_IDENTITY() for auto-increment IDs
                id_rows, _ = _fetch_results("SELECT LAST_IDENTITY()")
                last_id = id_rows[0][0] if id_rows and id_rows[0] else None

                if last_id is not None and last_id != "" and last_id != 0:
                    # Try lookup by %ID first
                    rows, meta = _fetch_results(
                        f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE %ID = ?', [last_id]
                    )
                    if not rows and columns != "*":
                        id_cols = [
                            c
                            for c in columns
                            if c.lower() in ("id", "identity", "pk", table.lower() + "id")
                        ]
                        for id_col in id_cols:
                            rows, meta = _fetch_results(
                                f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE "{id_col}" = ?',
                                [last_id],
                            )
                            if rows:
                                break

                    # Try %ID lookup using hardcoded query if other lookups failed
                    if not rows:
                        rows, meta = _fetch_results(
                            f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE %ID = (SELECT LAST_IDENTITY())'
                        )

                # Method 2: For UUID-based systems, extract ID from INSERT VALUES
                if not rows and original_sql:
                    id_col_name, id_value = self._extract_insert_id_from_sql(
                        original_sql, list(params) if params else None, session_id
                    )
                    if id_col_name and id_value:
                        logger.info(
                            "RETURNING emulation: Using extracted ID from INSERT",
                            id_column=id_col_name,
                            id_value=str(id_value)[:50],
                            table=table_normalized,
                            session_id=session_id,
                        )
                        rows, meta = _fetch_results(
                            f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE "{id_col_name}" = ?',
                            [id_value],
                        )

                # Method 3 (LAST RESORT): TOP 1 ORDER BY %ID DESC - risky under concurrency
                if not rows:
                    logger.warning(
                        "RETURNING emulation: Falling back to TOP 1 (risky under concurrency)",
                        table=table_normalized,
                        session_id=session_id,
                    )
                    rows, meta = _fetch_results(
                        f'SELECT TOP 1 {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" ORDER BY %ID DESC'
                    )

            elif operation in ("UPDATE", "DELETE"):
                if where_clause:
                    # Translate schema references in WHERE clause
                    translated_where = re.sub(
                        r'"public"\s*\.\s*"(\w+)"',
                        rf'{IRIS_SCHEMA}."\1"',
                        where_clause,
                        flags=re.IGNORECASE,
                    )
                    translated_where = re.sub(
                        r'\bpublic\s*\.\s*"(\w+)"',
                        rf'{IRIS_SCHEMA}."\1"',
                        translated_where,
                        flags=re.IGNORECASE,
                    )

                    select_sql = (
                        f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE {translated_where}'
                    )

                    # Extract WHERE clause parameters (they are the last N parameters)
                    where_param_count = len(re.findall(r"\?", where_clause))
                    where_params = (
                        params[-where_param_count:] if params and where_param_count > 0 else None
                    )
                    rows, meta = _fetch_results(select_sql, where_params)

            # Feature 036: Build proper metadata with actual IRIS types if needed
            if meta is None or not any("type_oid" in c for c in meta if isinstance(c, dict)):
                if columns == "*":
                    # For SELECT *, expand from schema
                    col_names = self._expand_select_star(
                        f"RETURNING * FROM {IRIS_SCHEMA}.{table}", 0, session_id=session_id
                    )
                    if col_names:
                        new_meta = []
                        for col in col_names:
                            col_oid = self._get_column_type_from_schema(
                                table, col, session_id=session_id
                            )
                            new_meta.append(
                                {
                                    "name": col,
                                    "type_oid": col_oid or 1043,
                                    "type_size": -1,
                                    "type_modifier": -1,
                                    "format_code": 0,
                                }
                            )
                        meta = new_meta
                else:
                    new_meta = []
                    for i, col in enumerate(columns):
                        col_oid = self._get_column_type_from_schema(
                            table, col, session_id=session_id
                        )
                        if col_oid is None and rows:
                            # Fallback to inference from value
                            col_oid = self._infer_type_from_value(rows[0][i], col)

                        new_meta.append(
                            {
                                "name": col,
                                "type_oid": col_oid or 1043,
                                "type_size": -1,
                                "type_modifier": -1,
                                "format_code": 0,
                            }
                        )
                    meta = new_meta

        except Exception as e:
            logger.error(f"RETURNING emulation failed for {operation}", error=str(e))

        return rows, meta

    async def _execute_embedded_async(
        self, sql: str, params: list | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        """Execute query in IRIS embedded Python environment (async wrapper)"""

        def _sync_execute(captured_sql, captured_params, captured_session_id):
            """Synchronous IRIS execution in thread pool"""
            sql = captured_sql
            params = captured_params
            session_id = captured_session_id
            optimized_sql = sql
            optimized_params = params
            sql_upper = sql.upper()
            sql_upper_check = sql.upper()
            optimized_sql_upper = sql_upper
            optimized_sql_upper_check = sql_upper_check
            optimized_sql_upper_stripped = sql_upper.strip()

            iris = self._import_iris()
            if not iris:
                return {
                    "success": False,
                    "error": "IRIS module not found",
                    "rows": [],
                    "columns": [],
                    "row_count": 0,
                    "command_tag": "ERROR",
                    "execution_time_ms": 0,
                }

            if hasattr(iris, "system") and hasattr(iris.system, "Process"):
                effective_ns = self._get_session_namespace(session_id)
                # Feature 034: Add retry for SetNamespace to handle environment timing issues
                for attempt in range(3):
                    try:
                        # Try to switch to %SYS first to "reset" the namespace context if it's stuck
                        if attempt > 0:
                            iris.system.Process.SetNamespace("%SYS")
                        iris.system.Process.SetNamespace(effective_ns)
                        break
                    except Exception as e:
                        if "<NAMESPACE>" in str(e) and attempt < 2:
                            logger.warning("Namespace not ready, retrying...", namespace=effective_ns, attempt=attempt+1)
                            time.sleep(0.5)
                            continue
                        raise

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

            # pg_enum - Return empty with column metadata (no enums defined)
            # CRITICAL: PostgreSQL protocol requires RowDescription even for 0-row results
            if "PG_ENUM" in optimized_sql_upper:
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
                as_pattern = re.compile(r"(?:[\w\.]+(?:\([^)]*\))?)\s+AS\s+(\w+)", re.IGNORECASE)
                aliases = as_pattern.findall(sql)

                # DEBUG: Log what the regex found
                logger.warning(
                    f"🔍 pg_enum regex debug: sql_len={len(sql)}, aliases_found={aliases}, sql_first_200={sql[:200]!r}"
                )

                if aliases:
                    # We found AS aliases - use those as column names
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
                    # Fallback to default columns
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

            # pg_namespace - Return standard PostgreSQL namespaces for Prisma/ORM introspection
            # Prisma queries: SELECT namespace.nspname ... FROM pg_namespace WHERE nspname = ANY($1)
            # CRITICAL: Prisma needs 'public' schema to discover tables
            # CRITICAL: Only intercept SIMPLE pg_namespace queries, not complex JOINs
            # Complex queries like "SELECT ... FROM pg_namespace JOIN pg_class" should go to CatalogRouter
            import re

            is_simple_pg_namespace = (
                "PG_NAMESPACE" in optimized_sql_upper
                and
                # Must have FROM pg_namespace (direct table access)
                re.search(r"\bFROM\s+PG_NAMESPACE\b", optimized_sql_upper)
                and
                # Must NOT have JOIN (which indicates complex query)
                "JOIN" not in optimized_sql_upper
                and
                # Must NOT have multiple FROM clauses (subqueries are OK)
                len(re.findall(r"\bFROM\b", optimized_sql_upper)) <= 2  # Allow 1 main + 1 subquery
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
                    (IRIS_SCHEMA.lower(), 16384),  # IRIS default schema mapped to custom OID
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
                            if param0.startswith("{") and param0.endswith("}"):
                                inner = param0[1:-1]
                                if inner:
                                    filter_names = [s.strip().strip('"') for s in inner.split(",")]
                            # Handle Python-like array format: [public] or ['public']
                            elif param0.startswith("[") and param0.endswith("]"):
                                inner = param0[1:-1].strip()
                                if inner:
                                    # Remove any quotes around values
                                    filter_names = [
                                        s.strip().strip('"').strip("'") for s in inner.split(",")
                                    ]
                            elif param0 == "[]" or param0 == "{}":
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
                            (name, oid)
                            for name, oid in all_namespaces
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
                    has_oid = (
                        "oid" in select_clause
                        and "nspname" not in select_clause.split("oid")[0][-5:]
                    )

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
            if "PG_CONSTRAINT" in optimized_sql_upper or "CONSTR.CONNAME" in optimized_sql_upper:
                logger.info(
                    "Intercepting pg_constraint query (returning from INFORMATION_SCHEMA)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Check if this is a check/exclusion constraint query
                # SPECIFIC pattern: contype NOT IN ('p', 'u', 'f') - filters for check/exclusion only
                # MUST NOT match WITH rawindex queries which also have condeferrable/condeferred
                is_check_constraint_query = (
                    "NOT IN" in optimized_sql_upper
                    and ("'P'" in optimized_sql_upper or "'U'" in optimized_sql_upper or "'F'" in optimized_sql_upper)
                    and "CONTYPE" in optimized_sql_upper  # Must explicitly filter by contype
                )

                # Also detect specific check constraint columns, but NOT if it's a WITH rawindex query
                is_rawindex_query = "WITH RAWINDEX" in optimized_sql_upper
                has_deferrable = "IS_DEFERRABLE" in optimized_sql_upper  # Only exact match, not CONDEFERRABLE
                has_deferred = "IS_DEFERRED" in optimized_sql_upper  # Only exact match, not CONDEFERRED

                # Check constraint query: has is_deferrable/is_deferred columns AND NOT a rawindex query
                if is_check_constraint_query or (
                    has_deferrable and has_deferred and not is_rawindex_query
                ):
                    logger.info(
                        "Check/exclusion constraint query detected - returning empty result",
                        is_check_query=is_check_constraint_query,
                        has_deferrable=has_deferrable,
                        session_id=session_id,
                    )
                    # Return empty result with expected columns for check constraint query
                    columns = [
                        {
                            "name": "namespace",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "table_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "constraint_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "constraint_type",
                            "type_oid": 18,
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # char
                        {
                            "name": "constraint_definition",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # text
                        {
                            "name": "is_deferrable",
                            "type_oid": 16,
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # bool
                        {
                            "name": "is_deferred",
                            "type_oid": 16,
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # bool
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
                    iris = self._import_iris()
                    if not iris:
                        raise RuntimeError("IRIS module not available")

                    # Query INFORMATION_SCHEMA for constraints
                    # Map constraint types: PRIMARY KEY -> p, UNIQUE -> u, FOREIGN KEY -> f
                    constraints_sql = """
                        SELECT
                            'public' AS namespace,
                            TABLE_NAME,
                            CONSTRAINT_NAME,
                            CONSTRAINT_TYPE
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
                        WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}'
                        ORDER BY TABLE_NAME, CONSTRAINT_NAME
                    """
                    result = iris.sql.exec(constraints_sql)
                    iris_constraints = list(result)

                    logger.info(
                        f"Found {len(iris_constraints)} constraints in IRIS",
                        constraints=iris_constraints[:5],
                    )

                    # Prisma expects: namespace, table_name, constraint_name, constraint_type, constraint_definition
                    # Also need column info for primary key constraints
                    columns = [
                        {
                            "name": "namespace",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "table_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "constraint_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "constraint_type",
                            "type_oid": 18,
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # char
                        {
                            "name": "constraint_definition",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # text
                        {
                            "name": "column_names",
                            "type_oid": 1009,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # text[]
                    ]

                    # Map IRIS constraint types to PostgreSQL single-char types
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
                            col_names_str = (
                                "{" + ",".join(col_names) + "}"
                            )  # PostgreSQL array format
                        except Exception:
                            col_names = []
                            col_names_str = "{}"

                        # Build constraint definition
                        if pg_type == "p":
                            definition = f"PRIMARY KEY ({', '.join(col_names)})"
                        elif pg_type == "u":
                            definition = f"UNIQUE ({', '.join(col_names)})"
                        else:
                            definition = ""

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
                        {
                            "name": "namespace",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "table_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "constraint_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "constraint_type",
                            "type_oid": 18,
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "constraint_definition",
                            "type_oid": 25,
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

            # INFORMATION_SCHEMA.SEQUENCES - Return empty sequence information for Prisma
            # Prisma queries sequences using PostgreSQL-style syntax with colons
            # IRIS interprets : as host variable prefix, so we intercept this
            if "INFORMATION_SCHEMA.SEQUENCES" in optimized_sql_upper or (
                "SEQUENCE_NAME" in optimized_sql_upper and "SEQUENCE_SCHEMA" in optimized_sql_upper
            ):
                logger.info(
                    "Intercepting sequence query (returning empty - IRIS sequences not exposed)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Return empty result for sequence queries
                columns = [
                    {
                        "name": "sequence_name",
                        "type_oid": 19,
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "namespace",
                        "type_oid": 19,
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "start_value",
                        "type_oid": 20,
                        "type_size": 8,
                        "type_modifier": -1,
                        "format_code": 0,
                    },  # bigint
                    {
                        "name": "min_value",
                        "type_oid": 20,
                        "type_size": 8,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "max_value",
                        "type_oid": 20,
                        "type_size": 8,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "increment_by",
                        "type_oid": 20,
                        "type_size": 8,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "cycle",
                        "type_oid": 16,
                        "type_size": 1,
                        "type_modifier": -1,
                        "format_code": 0,
                    },  # bool
                    {
                        "name": "cache_size",
                        "type_oid": 20,
                        "type_size": 8,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
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
            if "PG_EXTENSION" in optimized_sql_upper:
                logger.info(
                    "Intercepting pg_extension query (returning empty - IRIS has no PG extensions)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Return empty result with minimal columns for extension queries
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
                        "name": "extversion",
                        "type_oid": 25,
                        "type_size": -1,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
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
            if "PG_PROC" in optimized_sql_upper:
                logger.info(
                    "Intercepting pg_proc query (returning empty - IRIS procedures not exposed)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Return empty result with minimal columns for procedure queries
                columns = [
                    {
                        "name": "oid",
                        "type_oid": 26,
                        "type_size": 4,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "proname",
                        "type_oid": 19,
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "pronamespace",
                        "type_oid": 26,
                        "type_size": 4,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
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
            if "PG_VIEWS" in optimized_sql_upper:
                logger.info(
                    "Intercepting pg_views query (returning empty - IRIS views not exposed)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                # Return empty result with correct columns for view queries
                # Prisma expects: view_name, view_sql, namespace, description
                columns = [
                    {
                        "name": "view_name",
                        "type_oid": 19,
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "view_sql",
                        "type_oid": 25,
                        "type_size": -1,
                        "type_modifier": -1,
                        "format_code": 0,
                    },  # text
                    {
                        "name": "namespace",
                        "type_oid": 19,
                        "type_size": 64,
                        "type_modifier": -1,
                        "format_code": 0,
                    },
                    {
                        "name": "description",
                        "type_oid": 25,
                        "type_size": -1,
                        "type_modifier": -1,
                        "format_code": 0,
                    },  # text
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
                "PG_CLASS" in optimized_sql_upper
                and "PG_ATTRIBUTE" not in optimized_sql_upper  # Not a column info query
                and "ATT.ATTTYPID" not in optimized_sql_upper  # Not a column type query
                and "INFO.COLUMN_NAME" not in optimized_sql_upper  # Not an information_schema column query
            )

            if is_simple_pg_class:
                logger.info(
                    "Intercepting pg_class query (returning tables from INFORMATION_SCHEMA)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                try:
                    iris = self._import_iris()
                    if not iris:
                        raise RuntimeError("IRIS module not available")

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
                    # {IRIS_SCHEMA} -> public (Prisma expects 'public')
                    schema_mapping = {
                        IRIS_SCHEMA.lower(): "public",
                        IRIS_SCHEMA: "public",
                        "%Library": "pg_catalog",
                        "INFORMATION_SCHEMA": "information_schema",
                    }

                    # CRITICAL: Create OIDGenerator for table OIDs
                    # Prisma needs OIDs to JOIN pg_class with pg_attribute for column info
                    OIDGenerator()

                    # Build pg_class-like response based on Prisma's expected columns
                    # NOTE: Only return columns that Prisma's query requests - do NOT add OID
                    # Prisma's query: SELECT tbl.relname AS table_name, namespace.nspname as namespace, ...
                    columns = [
                        {
                            "name": "table_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "namespace",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "is_partition",
                            "type_oid": 16,
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "has_subclass",
                            "type_oid": 16,
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "has_row_level_security",
                            "type_oid": 16,
                            "type_size": 1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "reloptions",
                            "type_oid": 1009,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # text[]
                        {
                            "name": "description",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                    ]

                    # Filter by namespace if params contain schema filter
                    target_namespaces = ["public"]  # Default to public
                    if params and len(params) > 0 and params[0] is not None:
                        param0 = params[0]
                        if isinstance(param0, list):
                            target_namespaces = [n.lower() for n in param0]
                        elif isinstance(param0, str):
                            # Parse array string
                            if param0.startswith("[") and param0.endswith("]"):
                                inner = param0[1:-1].strip()
                                if inner:
                                    target_namespaces = [
                                        s.strip().strip('"').strip("'").lower()
                                        for s in inner.split(",")
                                    ]
                            elif param0.startswith("{") and param0.endswith("}"):
                                inner = param0[1:-1]
                                if inner:
                                    target_namespaces = [
                                        s.strip().strip('"').lower() for s in inner.split(",")
                                    ]
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
                            rows.append(
                                (
                                    table_name.lower(),  # table_name (lowercase for PostgreSQL)
                                    pg_namespace,  # namespace
                                    False,  # is_partition
                                    False,  # has_subclass
                                    False,  # has_row_level_security
                                    None,  # reloptions (array)
                                    None,  # description
                                )
                            )

                    logger.info(
                        f"pg_class: returning {len(rows)} tables for namespaces {target_namespaces}"
                    )

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
            if (
                "INFO.TABLE_NAME" in optimized_sql_upper
                and "INFO.COLUMN_NAME" in optimized_sql_upper
                and "FORMAT_TYPE" in optimized_sql_upper
            ):
                logger.info(
                    "Intercepting Prisma column info query (returning IRIS columns from INFORMATION_SCHEMA)",
                    sql_preview=sql[:200],
                    session_id=session_id,
                )

                try:
                    iris = self._import_iris()
                    if not iris:
                        raise RuntimeError("IRIS module not available")

                    # Query INFORMATION_SCHEMA.COLUMNS for column metadata
                    # Filter by {IRIS_SCHEMA} schema (maps to public)
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
                        WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}'
                        ORDER BY TABLE_NAME, ORDINAL_POSITION
                    """
                    result = iris.sql.exec(columns_sql)
                    iris_columns = list(result)

                    logger.info(
                        f"Found {len(iris_columns)} columns in IRIS", column_count=len(iris_columns)
                    )

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
                        {
                            "name": "namespace",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "table_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "column_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "data_type",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # SQL standard name (e.g., 'integer')
                        {
                            "name": "full_data_type",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # Full type with precision
                        {
                            "name": "formatted_type",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "udt_name",
                            "type_oid": 19,
                            "type_size": 64,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # PostgreSQL internal name (e.g., 'int4')
                        {
                            "name": "numeric_precision",
                            "type_oid": 23,
                            "type_size": 4,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "numeric_scale",
                            "type_oid": 23,
                            "type_size": 4,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "character_maximum_length",
                            "type_oid": 23,
                            "type_size": 4,
                            "type_modifier": -1,
                            "format_code": 0,
                        },  # Prisma expects this name
                        {
                            "name": "is_nullable",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "column_default",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "ordinal_position",
                            "type_oid": 23,
                            "type_size": 4,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "is_identity",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                        {
                            "name": "is_generated",
                            "type_oid": 25,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        },
                    ]

                    rows = []
                    for col in iris_columns:
                        namespace = col[0]
                        table_name = col[1].lower()  # Lowercase for PostgreSQL
                        column_name = col[2].lower()
                        iris_data_type = col[3].upper() if col[3] else "VARCHAR"
                        # Convert to int, handling strings and None
                        numeric_precision = int(col[4]) if col[4] and str(col[4]).isdigit() else 0
                        numeric_scale = int(col[5]) if col[5] and str(col[5]).isdigit() else 0
                        max_length = int(col[6]) if col[6] and str(col[6]).isdigit() else 0
                        is_nullable = "YES" if col[7] == "YES" else "NO"
                        column_default = col[8]
                        ordinal_position = int(col[9]) if col[9] and str(col[9]).isdigit() else 0

                        # Map to PostgreSQL format_type and udt_name using configurable type mapping
                        base_type = iris_data_type.split("(")[0]
                        pg_type, udt_name, _type_oid = get_type_mapping(base_type)

                        # Build formatted_type with precision/length
                        if max_length > 0 and pg_type in ("character varying", "character"):
                            formatted_type = f"{pg_type}({max_length})"
                        elif numeric_precision > 0 and pg_type == "numeric":
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
                            if "AUTOINCREMENT" in default_upper or "ROWVERSION" in default_upper:
                                clean_default = None  # Will be handled by @id or identity
                            elif default_upper in ("NULL", ""):
                                clean_default = None
                            else:
                                clean_default = column_default

                        # Detect identity columns (IRIS uses AUTOINCREMENT)
                        is_identity = "NO"
                        if column_default and "AUTOINCREMENT" in str(column_default).upper():
                            is_identity = "YES"  # Prisma uses this to detect @id

                        rows.append(
                            (
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
                                "NEVER",  # is_generated
                            )
                        )

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
                "PG_ATTRIBUTE" in optimized_sql_upper
                or "ATT.ATTNAME" in optimized_sql_upper
                or "ATT.ATTTYPID" in optimized_sql_upper
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
            if "PG_TYPE" in optimized_sql_upper or "PG_CATALOG" in optimized_sql_upper:
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
                            if param0.startswith("{") and param0.endswith("}"):
                                inner = param0[1:-1]
                                if inner:
                                    filter_names = [s.strip().strip('"') for s in inner.split(",")]
                            # Handle Python-like array format: ['public']
                            elif param0.startswith("[") and param0.endswith("]"):
                                inner = param0[1:-1].strip()
                                if inner:
                                    filter_names = [
                                        s.strip().strip('"').strip("'") for s in inner.split(",")
                                    ]
                            elif param0 == "[]" or param0 == "{}":
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
                        logger.info(
                            f"🔍 pg_type: pg_catalog not in {requested_namespaces}, returning 0 rows"
                        )

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

                # 1. Transaction Translation
                transaction_translated_sql = (
                    self.transaction_translator.translate_transaction_command(sql)
                )

                # 2. SQL Normalization
                normalized_sql = self._get_normalized_sql(
                    transaction_translated_sql, execution_path="direct"
                )
                optimized_sql = normalized_sql

                # Log transaction translation metrics
                txn_metrics = self.transaction_translator.get_translation_metrics()
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
                norm_metrics = self.sql_translator.get_normalization_metrics()
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

                # 3. Parameter Normalization
                # CRITICAL: Normalize parameters for IRIS compatibility (timestamps, lists, etc.)
                optimized_params = self._normalize_parameters(params)

                # 4. Vector Optimization
                # Apply vector query optimization (convert parameterized vectors to literals)
                optimization_applied = False
                t_opt_start = time.perf_counter()

                try:
                    from .vector_optimizer import optimize_vector_query

                    logger.debug(
                        "Vector optimizer: checking query",
                        sql_preview=optimized_sql[:200],
                        param_count=len(optimized_params) if optimized_params else 0,
                        session_id=session_id,
                    )

                    # CRITICAL: Pass currently optimized_sql and optimized_params
                    new_sql, new_params = optimize_vector_query(optimized_sql, optimized_params)

                    optimization_applied = (new_sql != optimized_sql) or (
                        new_params != optimized_params
                    )

                    if optimization_applied:
                        logger.info(
                            "Vector optimization applied",
                            sql_changed=(new_sql != optimized_sql),
                            params_changed=(new_params != optimized_params),
                            params_before=len(optimized_params) if optimized_params else 0,
                            params_after=len(new_params) if new_params else 0,
                            optimized_sql_preview=new_sql[:200],
                            session_id=session_id,
                        )
                        optimized_sql = new_sql
                        optimized_params = new_params
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

                # PROFILING: Optimization complete
                t_opt_elapsed = (time.perf_counter() - t_opt_start) * 1000

                # 5. RETURNING Parsing/Stripping (IRIS doesn't support it natively)
                (
                    returning_operation,
                    returning_table,
                    returning_columns,
                    returning_where_clause,
                    optimized_sql,
                ) = self._parse_returning_clause(optimized_sql)

                if returning_operation:
                    logger.info(
                        "RETURNING clause detected - will emulate",
                        operation=returning_operation,
                        table=returning_table,
                        columns=returning_columns,
                        session_id=session_id,
                    )

                # 6. Semicolon Stripping
                # CRITICAL: Strip trailing semicolon
                # IRIS cannot handle "SELECT ... WHERE id = ?;" (fails with SQLCODE=-52)
                optimized_sql = optimized_sql.strip().rstrip(";")

                # 7. Schema Translation
                # CRITICAL: Translate PostgreSQL schema names to IRIS schema names
                # Prisma/Drizzle send: "public"."tablename" but IRIS needs: {IRIS_SCHEMA}.TABLENAME
                if (
                    '"public"' in optimized_sql_upper_check
                    and not optimized_sql_upper_check.startswith("CREATE")
                    and not optimized_sql_upper_check.startswith("ALTER")
                ):
                    optimized_sql = self._get_normalized_sql(sql, execution_path="embedded")
                    logger.info(
                        f"Schema translation applied: public -> {IRIS_SCHEMA}",
                        original_sql=optimized_sql[:100],
                    )

                # POSTGRESQL COMPATIBILITY: Handle SHOW commands that IRIS doesn't support
                # Intercept and return fake results for PostgreSQL compatibility
                if optimized_sql_upper_stripped.startswith("SHOW "):
                    logger.info(
                        "Intercepting SHOW command (PostgreSQL compatibility shim)",
                        sql=optimized_sql[:100],
                        session_id=session_id,
                    )
                    return self._handle_show_command(optimized_sql, session_id)

                # Final parameter conversion for IRIS
                if optimized_params:
                    optimized_params = tuple(optimized_params)

                # Execute query with performance tracking
                start_time = time.perf_counter()

                if returning_operation:
                    logger.info(
                        "RETURNING clause detected - will emulate",
                        operation=returning_operation,
                        table=returning_table,
                        columns=returning_columns,
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
                    sql=optimized_sql[:1000],  # Log first 1000 chars
                    sql_ends_with_semicolon=optimized_sql.rstrip().endswith(";"),
                    has_params=optimized_params is not None and len(optimized_params) > 0,
                    session_id=session_id,
                )

                # PROFILING: IRIS execution timing
                t_iris_start = time.perf_counter()

                # Pre-fetch rows for DELETE RETURNING (must happen before deletion)
                delete_returning_rows = []
                delete_returning_meta = None
                if returning_operation == "DELETE" and returning_columns:
                    delete_returning_rows, delete_returning_meta = self._emulate_returning(
                        returning_operation,
                        returning_table,
                        returning_columns,
                        returning_where_clause,
                        optimized_params,
                        is_embedded=True,
                    )
                    if delete_returning_rows:
                        logger.info(
                            "Pre-DELETE: Row(s) captured for RETURNING",
                            row_count=len(delete_returning_rows),
                            session_id=session_id,
                        )

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
                        self._safe_execute(stmt, None, is_embedded=True, session_id=session_id)

                    # Execute last statement and capture results
                    last_stmt = statements[-1]
                    logger.debug(
                        f"Executing final statement: {last_stmt[:80]}...", session_id=session_id
                    )
                    result = self._safe_execute(
                        last_stmt, optimized_params, is_embedded=True, session_id=session_id
                    )
                else:
                    # Single statement - execute normally
                    result = self._safe_execute(
                        optimized_sql, optimized_params, is_embedded=True, session_id=session_id
                    )

                # RETURNING emulation: After INSERT/UPDATE/DELETE, fetch the affected row(s)
                if returning_operation and returning_columns:
                    if returning_operation == "DELETE":
                        # Use pre-captured rows for DELETE
                        result = MockResult(delete_returning_rows, delete_returning_meta)
                    else:
                        # Emulate for INSERT/UPDATE - pass original SQL for UUID extraction
                        rows, meta = self._emulate_returning(
                            returning_operation,
                            returning_table,
                            returning_columns,
                            returning_where_clause,
                            optimized_params,
                            is_embedded=True,
                            original_sql=sql,  # Pass original SQL for UUID extraction
                        )
                        result = MockResult(rows, meta)

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
                        col_name = self._normalize_iris_column_name(
                            iris_col_name, optimized_sql, iris_type
                        )

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

                        if iris_type == 2:
                            # Check for explicit casts
                            if "AS INTEGER" in optimized_sql_upper or "AS INT" in optimized_sql_upper:
                                # Already handled by asyncpg CAST INTEGER fix - don't override
                                pass
                            elif "AS NUMERIC" not in optimized_sql_upper and "AS DECIMAL" not in optimized_sql_upper:
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
                        if "CURRENT_TIMESTAMP" in optimized_sql_upper and type_oid == 25:
                            logger.info(
                                "🔧 OVERRIDING CURRENT_TIMESTAMP type OID 1043 (VARCHAR) → 1114 (TIMESTAMP)",
                                column_name=col_name,
                                original_oid=type_oid,
                                reason="CURRENT_TIMESTAMP function should return TIMESTAMP type",
                            )
                            type_oid = 1114  # TIMESTAMP

                        # CRITICAL FIX: CURRENT_TIMESTAMP returns type 1043 (VARCHAR) in IRIS
                        # but should be type 1114 (TIMESTAMP) for Npgsql compatibility
                        if "CURRENT_TIMESTAMP" in optimized_sql_upper_check and type_oid == 1043:
                            logger.info(
                                "🔧 OVERRIDING CURRENT_TIMESTAMP type OID 1043 (VARCHAR) → 1114 (TIMESTAMP)",
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

                # Layer 1-3: Column metadata discovery if missing
                if not columns:
                    if rows:
                        columns = self._discover_metadata(
                            sql, session_id, expected_count=len(rows[0]), rows=rows
                        )
                    elif optimized_sql_upper.startswith("SELECT"):
                        columns = self._discover_metadata(sql, session_id)

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

                    # Convert and serialize values in-place
                    for row_idx, row in enumerate(rows):
                        for col_idx, value in enumerate(row):
                            if col_idx < len(column_type_oids):
                                type_oid = column_type_oids[col_idx]

                                if type_oid in (20, 23) and isinstance(value, int):
                                    if POSIXTIME_OFFSET <= value <= POSIXTIME_MAX:
                                        type_oid = 1114
                                        if row_idx == 0:
                                            columns[col_idx]["type_oid"] = 1114

                                # Robust serialization (TIMESTAMP, etc.)
                                rows[row_idx][col_idx] = self._serialize_value(
                                    rows[row_idx][col_idx], type_oid
                                )
                                value = rows[row_idx][col_idx]

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

                # Determine command tag
                affected_count = len(rows)
                command_tag = self._determine_command_tag(sql, affected_count)

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
                logger.error(
                    "IRIS embedded execution failed",
                    sql=sql[:100] + "..." if len(sql) > 100 else sql,
                    error=str(e),
                    session_id=session_id,
                )
                # Feature 026: Determine command tag for failed DDL too (needed for command_tag in protocol)
                command_tag = self._determine_command_tag(sql, 0)
                return {
                    "success": False,
                    "error": str(e),
                    "rows": [],
                    "columns": [],
                    "row_count": 0,
                    "command_tag": command_tag,
                    "execution_time_ms": 0,
                }

        # Execute in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._get_executor(session_id), _sync_execute, sql, params, session_id)

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
            iris = self._import_iris()
            if not iris:
                return None

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
            try:
                for row in result:
                    break
            except Exception:
                pass

            # Method 3: Check for description attribute (DB-API 2.0 standard)
            if hasattr(result, "description") and result.description:
                for col_desc in result.description:
                    if isinstance(col_desc, (list, tuple)) and len(col_desc) > 0:
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

    def _discover_metadata(
        self,
        sql: str,
        session_id: str | None = None,
        expected_count: int | None = None,
        rows: list[list[Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Unified multi-layer metadata discovery for IRIS queries.
        Supports discovery even when rows are empty (Describe phase).

        Layers:
        1. LIMIT 0 check (Database-native approach)
        1.5. SELECT * expansion using INFORMATION_SCHEMA
        2. SQL Parsing (Explicit column extraction)
        3. Generic fallback
        """
        columns = []
        sql_upper = sql.strip().upper()

        # Layer 0.5: Explicit RETURNING columns (Feature 034 fix)
        if "RETURNING" in sql_upper:
            (
                returning_operation,
                returning_table,
                returning_columns,
                returning_where_clause,
                stripped_sql,
            ) = self._parse_returning_clause(sql)

            if returning_operation:
                if returning_columns == "*":
                    # For RETURNING *, expand columns using Layer 1.5 logic immediately
                    expanded_names = self._expand_select_star(
                        sql, expected_count or 0, session_id=session_id
                    )
                    if expanded_names:
                        logger.info("✅ Layer 0.5 SUCCESS: RETURNING * metadata discovery")
                        for i, name in enumerate(expanded_names):
                            col_oid = self._get_column_type_from_schema(
                                returning_table, name, session_id=session_id
                            )
                            if col_oid is None:
                                col_oid = (
                                    self._infer_type_from_value(rows[0][i], name)
                                    if rows and i < len(rows[0])
                                    else 1043
                                )
                            columns.append(
                                {
                                    "name": name,
                                    "type_oid": col_oid,
                                    "type_size": -1,
                                    "type_modifier": -1,
                                    "format_code": 0,
                                }
                            )
                        return columns
                elif isinstance(returning_columns, list) and returning_columns:
                    logger.info("✅ Layer 0.5 SUCCESS: RETURNING metadata discovery")
                    for i, name in enumerate(returning_columns):
                        # Try to get type from schema for accuracy
                        col_oid = self._get_column_type_from_schema(
                            returning_table, name, session_id=session_id
                        )

                        if col_oid is None:
                            # Fallback to inference from value
                            col_oid = (
                                self._infer_type_from_value(rows[0][i], name)
                                if rows and i < len(rows[0])
                                else 1043
                            )

                        columns.append(
                            {
                                "name": name,
                                "type_oid": col_oid,
                                "type_size": -1,
                                "type_modifier": -1,
                                "format_code": 0,
                            }
                        )
                    if expected_count is None or len(columns) == expected_count:
                        return columns

        # Layer 1: LIMIT 0 pattern
        limit_zero_names = self._discover_metadata_with_limit_zero(sql, session_id)
        if limit_zero_names and (expected_count is None or len(limit_zero_names) == expected_count):
            logger.info("✅ Layer 1 SUCCESS: LIMIT 0 metadata discovery")
            for i, name in enumerate(limit_zero_names):
                inferred_type = (
                    self._infer_type_from_value(rows[0][i], name)
                    if rows and i < len(rows[0])
                    else 1043
                )
                columns.append(
                    {
                        "name": name,
                        "type_oid": inferred_type,
                        "type_size": -1,
                        "type_modifier": -1,
                        "format_code": 0,
                    }
                )
            return columns

        # Layer 1.5: SELECT * expansion
        if "*" in sql_upper and ("SELECT" in sql_upper or "RETURNING" in sql_upper):
            expanded_names = self._expand_select_star(
                sql, expected_count or 0, session_id=session_id
            )
            if expanded_names and (expected_count is None or len(expanded_names) == expected_count):
                logger.info("✅ Layer 1.5 SUCCESS: Table metadata expansion")
                for i, name in enumerate(expanded_names):
                    inferred_type = (
                        self._infer_type_from_value(rows[0][i], name)
                        if rows and i < len(rows[0])
                        else 1043
                    )
                    columns.append(
                        {
                            "name": name,
                            "type_oid": inferred_type,
                            "type_size": -1,
                            "type_modifier": -1,
                            "format_code": 0,
                        }
                    )
                return columns

        # Layer 2: SQL Parsing (Explicit columns)
        extracted_aliases = self.alias_extractor.extract_column_aliases(sql)
        if extracted_aliases and (
            expected_count is None or len(extracted_aliases) == expected_count
        ):
            logger.info("✅ Layer 2 SUCCESS: SQL parsing column extraction")
            for i, alias in enumerate(extracted_aliases):
                col_name = alias.lower() if isinstance(alias, str) else alias
                inferred_type = (
                    self._infer_type_from_value(rows[0][i], col_name)
                    if rows and i < len(rows[0])
                    else 1043
                )

                # Check for CAST overrides
                cast_oid = self._detect_cast_type_oid(sql, col_name)
                if cast_oid:
                    inferred_type = cast_oid

                # Handle CURRENT_TIMESTAMP
                if "CURRENT_TIMESTAMP" in sql_upper and inferred_type == 1043:
                    inferred_type = 1114

                col_name = self._normalize_iris_column_name(col_name, sql, inferred_type)
                columns.append(
                    {
                        "name": col_name,
                        "type_oid": inferred_type,
                        "type_size": -1,
                        "type_modifier": -1,
                        "format_code": 0,
                    }
                )
            return columns

        # Layer 3: Last resort fallback
        actual_count = expected_count if expected_count is not None else 1
        logger.info(f"⚠️ Layer 3: Using generic fallback for {actual_count} columns")
        use_qcolumn = "SELECT" in sql_upper and "FROM" not in sql_upper

        for i in range(actual_count):
            col_name = "?column?" if use_qcolumn else f"column{i + 1}"
            inferred_type = (
                self._infer_type_from_value(rows[0][i], col_name)
                if rows and i < len(rows[0])
                else 1043
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
        return columns

    async def _execute_external_async(
        self, sql: str, params: list | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute SQL using external IRIS connection with proper async threading
        """

        def _sync_external_execute(captured_sql, captured_params, captured_session_id):
            """Synchronous external IRIS execution in thread pool"""
            sql = captured_sql
            params = captured_params
            session_id = captured_session_id
            optimized_sql = sql
            optimized_params = params
            sql_upper = sql.upper()
            sql_upper_check = sql.upper()

            # Initialize optimized derived variables at the top to avoid UnboundLocalError
            optimized_sql_upper = sql_upper
            optimized_sql_upper_check = sql_upper_check
            optimized_sql_upper_stripped = sql_upper.strip()
            try:
                # PROFILING: Track detailed timing
                t_start_total = time.perf_counter()

                # Use intersystems-irispython driver

                # 1. Transaction Translation
                transaction_translated_sql = (
                    self.transaction_translator.translate_transaction_command(sql)
                )

                # 2. SQL Normalization
                normalized_sql = self._get_normalized_sql(
                    transaction_translated_sql, execution_path="external"
                )
                optimized_sql = normalized_sql

                # Log transaction translation metrics (external mode)
                txn_metrics = self.transaction_translator.get_translation_metrics()
                logger.debug(
                    "Transaction verb translation applied (external mode)",
                    total_translations=txn_metrics["total_translations"],
                    avg_time_ms=txn_metrics["avg_translation_time_ms"],
                    sla_violations=txn_metrics["sla_violations"],
                    sql_original_preview=sql[:100],
                    sql_translated_preview=transaction_translated_sql[:100],
                    session_id=session_id,
                )

                # Log normalization metrics
                norm_metrics = self.sql_translator.get_normalization_metrics()
                logger.debug(
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

                # 3. Parameter Normalization
                # CRITICAL: Normalize parameters for IRIS compatibility (timestamps, lists, etc.)
                optimized_params = self._normalize_parameters(params)

                # 4. Vector Optimization
                # Apply vector query optimization (convert parameterized vectors to literals)
                optimization_applied = False
                t_opt_start = time.perf_counter()

                try:
                    from .vector_optimizer import optimize_vector_query

                    logger.debug(
                        "Vector optimizer: checking query (external mode)",
                        sql_preview=optimized_sql[:200],
                        param_count=len(optimized_params) if optimized_params else 0,
                        session_id=session_id,
                    )

                    # CRITICAL: Pass currently optimized_sql and optimized_params
                    new_sql, new_params = optimize_vector_query(optimized_sql, optimized_params)

                    optimization_applied = (new_sql != optimized_sql) or (
                        new_params != optimized_params
                    )

                    if optimization_applied:
                        logger.debug(
                            "Vector optimization applied (external mode)",
                            sql_changed=(new_sql != optimized_sql),
                            params_changed=(new_params != optimized_params),
                            params_before=len(optimized_params) if optimized_params else 0,
                            params_after=len(new_params) if new_params else 0,
                            optimized_sql_preview=new_sql[:200],
                            session_id=session_id,
                        )
                        optimized_sql = new_sql
                        optimized_params = new_params
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

                # PROFILING: Optimization complete
                t_opt_elapsed = (time.perf_counter() - t_opt_start) * 1000

                # 5. RETURNING Parsing/Stripping (IRIS doesn't support it natively)
                (
                    returning_operation,
                    returning_table,
                    returning_columns,
                    returning_where_clause,
                    optimized_sql,
                ) = self._parse_returning_clause(optimized_sql)

                if returning_operation:
                    logger.info(
                        "RETURNING clause detected - will emulate (external mode)",
                        operation=returning_operation,
                        table=returning_table,
                        columns=returning_columns,
                        session_id=session_id,
                    )

                # 6. Semicolon Stripping
                # CRITICAL: Strip trailing semicolon
                # IRIS cannot handle "SELECT ... WHERE id = ?;" (fails with SQLCODE=-52)
                optimized_sql = optimized_sql.strip().rstrip(";")

                # 7. Schema Translation
                # CRITICAL: Translate PostgreSQL schema names to IRIS schema names
                # Prisma/Drizzle send: "public"."tablename" but IRIS needs: {IRIS_SCHEMA}.TABLENAME
                if (
                    '"public"' in optimized_sql_upper_check
                    and not optimized_sql_upper_check.startswith("CREATE")
                    and not optimized_sql_upper_check.startswith("ALTER")
                ):
                    optimized_sql = self._get_normalized_sql(sql, execution_path="external")
                    logger.info(
                        f"Schema translation applied (external): public -> {IRIS_SCHEMA}",
                        original_sql=optimized_sql[:100],
                    )

                # Pre-process parameters to convert lists to IRIS vector strings
                # This ensures the DBAPI driver doesn't convert them to {...} format
                if optimized_params:
                    processed_params = []
                    for p in optimized_params:
                        if isinstance(p, list):
                            processed_params.append("[" + ",".join(str(float(v)) for v in p) + "]")
                        else:
                            # Feature 036: Ensure we pass strings or numbers, not complex objects
                            if p is not None and not isinstance(p, (int, float, str, bool, bytes)):
                                processed_params.append(str(p))
                            else:
                                processed_params.append(p)
                    optimized_params = processed_params

                # Performance tracking
                start_time = time.perf_counter()

                # PROFILING: Connection timing
                t_conn_start = time.perf_counter()

                # Get connection from pool (or create new one)
                conn = self._get_pooled_connection(session_id=session_id)

                t_conn_elapsed = (time.perf_counter() - t_conn_start) * 1000

                # Pre-fetch rows for DELETE RETURNING
                delete_returning_rows = []
                delete_returning_meta = None
                if returning_operation == "DELETE" and returning_columns:
                    delete_returning_rows, delete_returning_meta = self._emulate_returning(
                        returning_operation,
                        returning_table,
                        returning_columns,
                        returning_where_clause,
                        optimized_params,
                        is_embedded=False,
                        connection=conn,
                    )
                    if delete_returning_rows:
                        logger.info(
                            "Pre-DELETE: Row(s) captured for RETURNING (external)",
                            row_count=len(delete_returning_rows),
                            session_id=session_id,
                        )

                # PROFILING: IRIS execution timing
                t_iris_start = time.perf_counter()

                # CRITICAL FIX: Split SQL by semicolons and handle multi-action ALTER TABLE
                statements = self._split_sql_statements(optimized_sql)

                if not statements:
                    # Should not happen given _split_sql_statements logic, but for safety
                    return {"success": True, "rows": [], "columns": []}

                # Execute all statements except the last
                for stmt in statements[:-1]:
                    self._safe_execute(stmt, None, is_embedded=False, session_id=session_id)

                # Execute last statement and capture cursor
                cursor = self._safe_execute(
                    statements[-1], optimized_params, is_embedded=False, session_id=session_id
                )

                # RETURNING emulation
                if returning_operation and returning_columns:
                    if returning_operation == "DELETE":
                        # Use pre-captured rows
                        cursor = MockResult(delete_returning_rows, delete_returning_meta)
                    else:
                        # Emulate for INSERT/UPDATE - pass original SQL for UUID extraction
                        rows, meta = self._emulate_returning(
                            returning_operation,
                            returning_table,
                            returning_columns,
                            returning_where_clause,
                            optimized_params,
                            is_embedded=False,
                            connection=conn,
                            original_sql=sql,  # Pass original SQL for UUID extraction
                        )
                        cursor = MockResult(rows, meta)

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
                        if isinstance(desc, dict):
                            iris_col_name = desc.get("name", "")
                            iris_type = desc.get("iris_type", "VARCHAR")
                            precomputed_oid = desc.get("type_oid")
                        else:
                            iris_col_name = desc[0]
                            iris_type = desc[1] if len(desc) > 1 else "VARCHAR"
                            precomputed_oid = None

                        # CRITICAL: Normalize IRIS column names to PostgreSQL conventions
                        # IRIS generates HostVar_1, Expression_1, Aggregate_1 for unnamed columns
                        # PostgreSQL uses ?column?, type names (int4), or function names (count)
                        col_name = self._normalize_iris_column_name(
                            iris_col_name, optimized_sql, iris_type
                        )

                        # DEBUG: Log IRIS type for arithmetic expressions (external mode)
                        logger.info(
                            "🔍 IRIS metadata type discovery (EXTERNAL MODE)",
                            original_column_name=iris_col_name,
                            normalized_column_name=col_name,
                            iris_type=iris_type,
                            desc=desc,
                            sql_preview=optimized_sql[:200],
                        )

                        if precomputed_oid is not None:
                            type_oid = precomputed_oid
                        else:
                            # CRITICAL FIX: IRIS type code 2 means NUMERIC, but for decimal literals
                            # like 3.14, we want FLOAT8 so node-postgres returns a number, not a string.
                            # Override to FLOAT8 UNLESS explicitly cast to NUMERIC/DECIMAL or INTEGER
                            type_oid = self._iris_type_to_pg_oid(iris_type)

                            optimized_sql_upper_check = optimized_sql.upper()

                            if iris_type == 2:
                                # Check for explicit casts
                                if "AS INTEGER" in optimized_sql_upper_check or "AS INT" in optimized_sql_upper_check:
                                    # CAST(? AS INTEGER) - override to INT4
                                    logger.info(
                                        "🔧 OVERRIDING IRIS type code 2 (NUMERIC) → OID 23 (INT4)",
                                        column_name=col_name,
                                        original_oid=type_oid,
                                        reason="SQL contains CAST to INTEGER",
                                    )
                                    type_oid = 23  # INT4
                                elif (
                                    "AS NUMERIC" not in optimized_sql_upper_check
                                    and "AS DECIMAL" not in optimized_sql_upper_check
                                ):
                                    # No explicit NUMERIC/DECIMAL cast → make it FLOAT8
                                    logger.info(
                                        "🔧 OVERRIDING IRIS type code 2 (NUMERIC) → OID 701 (FLOAT8)",
                                        column_name=col_name,
                                        original_oid=type_oid,
                                        reason="Decimal literal without explicit NUMERIC/DECIMAL cast",
                                    )
                                    type_oid = 701  # FLOAT8

                            # CRITICAL FIX: CURRENT_TIMESTAMP returns type 1043 (VARCHAR) in IRIS
                            # but should be type 1114 (TIMESTAMP) for Npgsql compatibility
                            if "CURRENT_TIMESTAMP" in optimized_sql_upper_check and type_oid == 1043:
                                logger.info(
                                    "🔧 OVERRIDING CURRENT_TIMESTAMP type OID 1043 (VARCHAR) → 1114 (TIMESTAMP)",
                                    column_name=col_name,
                                    original_oid=type_oid,
                                    reason="CURRENT_TIMESTAMP function should return TIMESTAMP type",
                                )
                                type_oid = 1114  # TIMESTAMP

                        columns.append(
                            {
                                "name": col_name,
                                "type_oid": type_oid,
                                "type_size": desc[2]
                                if not isinstance(desc, dict) and len(desc) > 2
                                else -1,
                                "type_modifier": -1,
                                "format_code": 0,  # Text format
                            }
                        )

                if (sql.upper().strip().startswith("SELECT") or returning_operation) and columns:
                    try:
                        results = cursor.fetchall()

                        for row in results:
                            if isinstance(row, list | tuple):
                                # Convert row to list and handle type-specific conversions
                                processed_row = list(row)
                                for i, val in enumerate(processed_row):
                                    if i < len(columns):
                                        oid = columns[i]["type_oid"]
                                        if oid in (20, 21, 23, 26) and val is not None:
                                            try:
                                                processed_row[i] = int(val)
                                            except (ValueError, TypeError):
                                                pass
                                        elif oid in (700, 701) and val is not None:
                                            try:
                                                processed_row[i] = float(val)
                                            except (ValueError, TypeError):
                                                pass
                                rows.append(processed_row)
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
                self._return_connection(conn, session_id=session_id)

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

                    # Convert and serialize values in-place
                    for row_idx, row in enumerate(rows):
                        for col_idx, value in enumerate(row):
                            if col_idx < len(column_type_oids):
                                type_oid = column_type_oids[col_idx]

                                if type_oid in (20, 23) and isinstance(value, int):
                                    if POSIXTIME_OFFSET <= value <= POSIXTIME_MAX:
                                        type_oid = 1114
                                        if row_idx == 0:
                                            columns[col_idx]["type_oid"] = 1114

                                # Robust serialization (TIMESTAMP, etc.)
                                rows[row_idx][col_idx] = self._serialize_value(
                                    rows[row_idx][col_idx], type_oid
                                )
                                value = rows[row_idx][col_idx]

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
                affected_count = len(rows)
                if affected_count == 0 and hasattr(cursor, "rowcount") and cursor.rowcount > 0:
                    affected_count = cursor.rowcount
                command_tag = self._determine_command_tag(sql, affected_count)

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

                # Feature 030: Schema output translation ({IRIS_SCHEMA} → public)
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
                    sql=optimized_sql[:100] + "..." if len(optimized_sql) > 100 else optimized_sql,
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
        return await loop.run_in_executor(self._get_executor(session_id), _sync_external_execute, sql, params, session_id)

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

    def _get_pooled_connection(self, session_id: str | None = None):
        if session_id and session_id in self.session_connections:
            return self.session_connections[session_id]

        iris = self._import_iris()
        if not iris:
            raise RuntimeError("IRIS module not available")

        with self._connection_lock:
            # Wait for a connection to be available if we've reached the limit
            start_time = time.time()
            while not self._connection_pool and self._active_count >= self._max_connections:
                elapsed = time.time() - start_time
                remaining = self.connection_pool_timeout - elapsed
                if remaining <= 0:
                    logger.error(
                        "Connection pool exhausted and timeout reached",
                        timeout=self.connection_pool_timeout,
                        active_count=self._active_count,
                        pool_size=len(self._connection_pool),
                    )
                    raise ConnectionError(
                        f"Connection pool timeout after {self.connection_pool_timeout}s"
                    )

                if not self._connection_lock.wait(remaining):
                    raise ConnectionError(
                        f"Connection pool timeout after {self.connection_pool_timeout}s"
                    )

            if self._connection_pool:
                conn = self._connection_pool.pop()
                # Feature 018: Add simple health check for pooled connections
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.close()
                except Exception:
                    logger.warning("Pooled connection failed health check, creating new one")
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self._active_count -= 1
                    # Recurse once to get another connection or create new
                    return self._get_pooled_connection(session_id)
            else:
                conn = iris.connect(
                    hostname=self.iris_config["host"],
                    port=self.iris_config["port"],
                    namespace=self.iris_config["namespace"],
                    username=self.iris_config["username"],
                    password=self.iris_config["password"],
                )
                self._active_count += 1

            if session_id:
                self.session_connections[session_id] = conn

            return conn

    def _return_connection(self, conn, session_id: str | None = None):
        if session_id:
            # Session connections stay active until session close
            return

        with self._connection_lock:
            if len(self._connection_pool) < self._max_connections:
                self._connection_pool.append(conn)
            else:
                try:
                    conn.close()
                except Exception:
                    pass
                self._active_count -= 1
            self._connection_lock.notify()

    def close(self):
        """Shutdown connection pool and executors."""
        with self._connection_lock:
            # Shutdown thread pool
            self.thread_pool.shutdown(wait=False)

            # Shutdown session executors
            for executor in self.session_executors.values():
                executor.shutdown(wait=False)
            self.session_executors.clear()

            # Close pooled connections
            for conn in self._connection_pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connection_pool.clear()
            self._active_count = 0

    def close_session(self, session_id: str):
        with self._connection_lock:
            # Shutdown and remove session executor for thread affinity
            executor = self.session_executors.pop(session_id, None)
            if executor:
                executor.shutdown(wait=False)

            # Feature 034: Clean up session namespace
            if session_id in self.session_namespaces:
                del self.session_namespaces[session_id]

            conn = self.session_connections.pop(session_id, None)
            if conn:
                logger.info(
                    "Closing session and returning connection to pool", session_id=session_id
                )
                self._return_connection(conn)

    def _expand_select_star(
        self, sql: str, expected_columns: int, session_id: str | None = None
    ) -> list[str] | None:
        try:
            import re

            # Extract table name from SQL for schema-based column lookup
            # Handle both SELECT * FROM table and INSERT/UPDATE ... RETURNING *
            table_name = None
            sql_upper = sql.upper()
            
            if "RETURNING" in sql_upper:
                # For INSERT/UPDATE/DELETE ... RETURNING *, extract table from INTO/UPDATE/FROM
                # INSERT INTO table_name ...
                insert_match = re.search(r"INSERT\s+INTO\s+([^\s(]+)", sql, re.IGNORECASE)
                if insert_match:
                    table_name = insert_match.group(1)
                else:
                    # UPDATE table_name SET ...
                    update_match = re.search(r"UPDATE\s+([^\s]+)\s+SET", sql, re.IGNORECASE)
                    if update_match:
                        table_name = update_match.group(1)
                    else:
                        # DELETE FROM table_name ...
                        delete_match = re.search(r"DELETE\s+FROM\s+([^\s]+)", sql, re.IGNORECASE)
                        if delete_match:
                            table_name = delete_match.group(1)
            else:
                # SELECT * FROM table_name ...
                from_match = re.search(r"FROM\s+([^\s,;()]+)", sql, re.IGNORECASE)
                if from_match:
                    table_name = from_match.group(1)
            
            # Method 0 (Preferred): Use INFORMATION_SCHEMA for reliable column names
            if table_name:
                # Strip schema prefix if present (e.g., SQLUser.workflow -> workflow)
                if "." in table_name:
                    table_name = table_name.split(".")[-1]
                # Strip quotes
                table_name = table_name.strip('"').strip("'")
                
                logger.debug(
                    "Attempting schema-based column discovery",
                    table_name=table_name,
                    session_id=session_id,
                )
                
                schema_columns = self._get_table_columns_from_schema(table_name, session_id)
                if schema_columns:
                    # Verify column count matches if we have expected_columns
                    if expected_columns == 0 or len(schema_columns) == expected_columns:
                        logger.info(
                            "Schema-based column discovery succeeded",
                            table_name=table_name,
                            columns=schema_columns,
                            session_id=session_id,
                        )
                        return schema_columns
                    else:
                        logger.debug(
                            "Schema columns count mismatch, falling back",
                            schema_count=len(schema_columns),
                            expected=expected_columns,
                            session_id=session_id,
                        )

            # Fallback: Try LIMIT 0 metadata discovery (doesn't work well with IRIS)
            iris = self._import_iris()
            if not iris:
                return None

            if "RETURNING" in sql.upper():
                sql = re.sub(r"RETURNING\s+\*", "SELECT *", sql, flags=re.IGNORECASE)
                select_match = re.search(r"SELECT\s+.*", sql, re.IGNORECASE | re.DOTALL)
                if select_match:
                    sql = select_match.group(0)

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
                -7: 16,  # BIT → bool
                -6: 21,  # TINYINT → int2
                -5: 20,  # BIGINT → int8
                1: 1042,  # CHAR → bpchar
                2: 1700,  # numeric
                3: 20,  # int8
                4: 23,  # int4
                5: 701,  # float8
                8: 701,  # float8 (IRIS DOUBLE)
                9: 1082,  # date
                10: 1114,  # timestamp
                12: 1043,  # varchar
                16: 16,  # bool
                17: 17,  # bytea
            }
            return int_type_mapping.get(iris_type, 1043)  # Default to VARCHAR

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
        return type_mapping.get(str(iris_type).upper(), 1043)  # Default to VARCHAR

    def _extract_table_names_from_select(self, sql: str) -> list[str]:
        """
        Extract all table names from SELECT query (multi-table aware).

        Handles:
        - SELECT * FROM table_name
        - SELECT * FROM table_a JOIN table_b
        - SELECT * FROM "schema"."table_name"

        Returns:
            List of table names
        """
        import re

        from_match = re.search(r"FROM\s+([A-Za-z_][A-Za-z0-9_]*)", sql, re.IGNORECASE)
        if not from_match:
            # Try quoted identifier fallback
            match = re.search(r'\bFROM\s+(?:"?\w+"?\s*\.\s*)*"?(\w+)"?', sql, re.IGNORECASE)
            if match:
                return [match.group(1)]
            return []

        table_names = [from_match.group(1)]

        # Extract JOINs
        join_matches = re.findall(r"JOIN\s+([A-Za-z_][A-Za-z0-9_]*)", sql, re.IGNORECASE)
        table_names.extend(join_matches)

        # Handle quoted JOINs
        quoted_join_matches = re.findall(
            r'\bJOIN\s+(?:"?\w+"?\s*\.\s*)*"?(\w+)"?', sql, re.IGNORECASE
        )
        for t in quoted_join_matches:
            if t not in table_names:
                table_names.append(t)

        return table_names

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

        return type_map.get(normalized_type, 1043)  # Default to VARCHAR (OID 1043)

    def _determine_command_tag(self, sql: str, row_count: int) -> str:
        """Determine PostgreSQL command tag from SQL"""
        # Normalize: strip and get first word
        sql_clean = sql.strip().upper()
        if not sql_clean:
            return "UNKNOWN"

        first_word = sql_clean.split()[0] if sql_clean.split() else ""

        if first_word == "SELECT":
            return "SELECT"
        elif first_word == "INSERT":
            return f"INSERT 0 {row_count}"
        elif first_word == "UPDATE":
            return f"UPDATE {row_count}"
        elif first_word == "DELETE":
            return f"DELETE {row_count}"
        elif first_word == "MERGE":
            return f"MERGE {row_count}"
        elif first_word == "TRUNCATE":
            return "TRUNCATE"
        elif first_word in ("CREATE", "DROP", "ALTER", "BEGIN", "COMMIT", "ROLLBACK", "SHOW"):
            return first_word
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

        def _sync_begin(captured_session_id):
            session_id = captured_session_id
            if self.embedded_mode:
                iris = self._import_iris()
                if iris:
                    iris.sql.exec("START TRANSACTION")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._get_executor(session_id), _sync_begin, session_id)

    async def commit_transaction(self, session_id: str | None = None):
        """Commit transaction with async threading"""

        def _sync_commit(captured_session_id):
            session_id = captured_session_id
            if self.embedded_mode:
                iris = self._import_iris()
                if iris:
                    iris.sql.exec("COMMIT")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._get_executor(session_id), _sync_commit, session_id)

    async def rollback_transaction(self, session_id: str | None = None):
        """Rollback transaction with async threading"""

        def _sync_rollback(captured_session_id):
            session_id = captured_session_id
            if self.embedded_mode:
                iris = self._import_iris()
                if iris:
                    iris.sql.exec("ROLLBACK")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._get_executor(session_id), _sync_rollback, session_id)

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

            def _sync_cancel(captured_self, captured_pid, captured_secret):
                # In embedded mode, we could potentially use IRIS job control
                # For now, return success for demo purposes
                # Production would implement actual IRIS job termination
                logger.info("Embedded query cancellation (demo mode)", pid=captured_pid)
                return True

            return await asyncio.to_thread(_sync_cancel, self, backend_pid, backend_secret)

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
