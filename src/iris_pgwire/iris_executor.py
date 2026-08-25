"""
IRIS SQL Executor for PostgreSQL Wire Protocol

Handles SQL execution against IRIS using embedded Python or external connection.
Based on patterns from caretdev/sqlalchemy-iris for proven IRIS integration.
"""

import asyncio
import concurrent.futures
import contextvars
import datetime as dt
import re
import threading
import time
from decimal import Decimal
from typing import Any

import structlog

from ._noop_cursor import NoopCursor
from .catalog import CatalogRouter  # Feature: Consolidated catalog emulation
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
    TransactionTranslator,
)  # Feature 022: PostgreSQL transaction verb translation
from .sql_translator.alias_extractor import AliasExtractor  # Column alias preservation
from .sql_translator.array_literal import rewrite_array_literals
from .sql_translator.array_params import (
    encode_inlist_params,
    expand_array_literals,
    has_array_param,
    rewrite_any_col_to_instr,
    rewrite_any_to_inlist,
)
from .sql_translator.boolean_expr import (
    has_boolean_literal_comparison,
    has_boolean_projection,
    rewrite_boolean_literal_comparisons,
    rewrite_boolean_projections,
)
from .sql_translator.metadata_cache import MetadataCache
from .sql_translator.parser import get_parser
from .sql_translator.performance_monitor import MetricType, PerformanceTracker, get_monitor
from .sql_translator.pg_functions import (
    has_pg_function_call,
    rewrite_pg_function_calls,
)
from .sql_translator.returning_plan import ReturningPlan
from .sql_translator.verbatim import is_verbatim
from .type_mapping import (
    load_type_mappings_from_file,
)  # Configurable type mapping

# IRIS POSIXTIME constants
POSIXTIME_OFFSET = 1152921504606846976
POSIXTIME_MAX = POSIXTIME_OFFSET + 7258118400000000  # ~2200-01-01

logger = structlog.get_logger()

# Pre-compiled patterns for LIMIT/OFFSET parameter detection (used by inline_limit_offset_params)
_LIMIT_OFFSET_Q = re.compile(r"\bLIMIT\s+\?\s+OFFSET\s+\?", re.IGNORECASE)
_LIMIT_Q_COMMA_Q = re.compile(r"\bLIMIT\s+\?\s*,\s*\?", re.IGNORECASE)
_LIMIT_Q = re.compile(r"\bLIMIT\s+\?", re.IGNORECASE)
_OFFSET_Q = re.compile(r"\bOFFSET\s+\?", re.IGNORECASE)


def inline_limit_offset_params(sql: str, params: list) -> tuple[str, list]:
    """Inline LIMIT/OFFSET ? placeholders with their bound values.

    IRIS does not support parameterized LIMIT or OFFSET.  The parameter
    values must be substituted as integer literals before the query reaches
    the IRIS SQL engine.  All other (non-LIMIT/OFFSET) ? placeholders and
    their corresponding params are left untouched.

    Returns (new_sql, new_params) where LIMIT/OFFSET placeholders have been
    replaced with literals and removed from params.
    """
    if not params or "?" not in sql:
        return sql, params

    params = list(params)

    def _placeholder_index(query: str, abs_pos: int) -> int:
        return query[:abs_pos].count("?")

    # Identify which 0-based param indexes are LIMIT / OFFSET positions
    limit_idxs: set[int] = set()
    offset_idxs: set[int] = set()

    for m in _LIMIT_OFFSET_Q.finditer(sql):
        local = m.group(0)
        fq = local.find("?")
        sq = local.find("?", fq + 1)
        limit_idxs.add(_placeholder_index(sql, m.start() + fq))
        offset_idxs.add(_placeholder_index(sql, m.start() + sq))

    for m in _LIMIT_Q_COMMA_Q.finditer(sql):
        local = m.group(0)
        fq = local.find("?")
        sq = local.find("?", fq + 1)
        # MySQL-style: LIMIT offset, count
        offset_idxs.add(_placeholder_index(sql, m.start() + fq))
        limit_idxs.add(_placeholder_index(sql, m.start() + sq))

    for m in _LIMIT_Q.finditer(sql):
        local = m.group(0)
        fq = local.find("?")
        idx = _placeholder_index(sql, m.start() + fq)
        if idx not in offset_idxs:
            limit_idxs.add(idx)

    for m in _OFFSET_Q.finditer(sql):
        local = m.group(0)
        fq = local.find("?")
        idx = _placeholder_index(sql, m.start() + fq)
        if idx not in limit_idxs:
            offset_idxs.add(idx)

    inline_idxs = limit_idxs | offset_idxs
    if not inline_idxs:
        return sql, params

    # Replace placeholders in order (right-to-left to preserve offsets)
    q_positions = [m.start() for m in re.finditer(r"\?", sql)]
    result = list(sql)
    removed: set[int] = set()

    for q_order, q_pos in enumerate(q_positions):
        if q_order in inline_idxs and q_order < len(params):
            value = params[q_order]
            if value is None:
                continue  # Don't inline NULL — leave as ?
            result[q_pos] = str(int(value))
            removed.add(q_order)

    new_sql = "".join(result)
    new_params = [v for i, v in enumerate(params) if i not in removed]
    return new_sql, new_params


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
        strict_single_connection: bool = False,
        query_timeout: float = 30.0,
    ):
        self.iris_config = iris_config
        self.server = server  # Reference to server for P4 cancellation
        self.connection_pool_size = connection_pool_size
        self.connection_pool_timeout = connection_pool_timeout
        self.enable_query_cache = enable_query_cache
        self.query_cache_size = query_cache_size
        self.strict_single_connection = strict_single_connection
        self.query_timeout = query_timeout

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
        self.metadata_cache = MetadataCache()

        self.sql_pipeline = SQLPipeline()
        self.sql_interceptor = SQLInterceptor(self)
        self.sql_translator = self.sql_pipeline.translator
        self.sql_parser = get_parser()
        self.transaction_translator = TransactionTranslator()
        self.catalog_router = CatalogRouter()  # Feature: Consolidated catalog emulation

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

        # IRIS LONGVARCHAR/CLOB columns are returned as stream objects with a .read() method.
        # Convert them to strings so the wire protocol can serialize them as text.
        if hasattr(value, "read") and callable(value.read):
            try:
                return value.read()
            except Exception:
                return str(value)

        return value

    def _get_normalized_sql(self, sql: str, execution_path: str = "direct") -> str:
        # SQL pgwire authored itself is already in IRIS's dialect. Normalising it
        # corrupts ObjectScript function bodies — see sql_translator/verbatim.py.
        if is_verbatim():
            return sql

        if not self.enable_query_cache:
            return self.sql_translator.normalize_sql(
                sql, execution_path=execution_path, executor=self
            )

        cache_key = (sql, execution_path)
        with self._query_cache_lock:
            if cache_key in self._query_cache:
                val = self._query_cache.pop(cache_key)
                self._query_cache[cache_key] = val
                return val

        normalized = self.sql_translator.normalize_sql(
            sql, execution_path=execution_path, executor=self
        )

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

        # Pattern 2: CAST of any expression, not just a parameter.
        #
        # This used to require CAST(? AS type), which covered the asyncpg case it
        # was written for and missed the one the boolean-projection rewrite
        # produces:
        #
        #   CAST(CASE WHEN a <> 0 AND b = 'p' THEN 1 ELSE 0 END AS BIT) AS is_partition
        #
        # so that column was described as int4. A client that asked for binary
        # results and reads it as bool then gets four bytes where it expects one.
        #
        # Anchor on the tail — `AS <type>) AS <column>` — then walk back to the
        # matching open paren and confirm CAST precedes it, rather than trusting
        # the shape. `(SELECT b AS c) AS flag` matches the tail but is not a cast.
        tail_pattern = rf"\bAS\s+(\w+)\s*\)\s+AS\s+{re.escape(column_name.upper())}\b"
        for match in re.finditer(tail_pattern, sql_upper):
            # Start inside the type word: the closing paren belongs to the
            # CAST we are trying to identify, so counting it would consume it.
            if self._encloses_a_cast(sql_upper, match.end(1) - 1):
                return type_map.get(match.group(1).lower())

        return None

    @staticmethod
    def _encloses_a_cast(sql_upper: str, position: int) -> bool:
        """True if the parenthesis closing at/after `position` was opened by CAST."""
        depth = 0
        for index in range(position, -1, -1):
            char = sql_upper[index]
            if char == ")":
                depth += 1
            elif char == "(":
                if depth == 0:
                    return sql_upper[:index].rstrip().endswith("CAST")
                depth -= 1
        return False

    def _detect_catalog_column_type_oid(self, sql: str, item_index: int) -> int | None:
        """PostgreSQL type OID for the catalog column at `item_index`, if it is one.

        Delegates to the shared resolver. This logic used to live here alone,
        which is exactly how the dbapi backend — a *different* executor class —
        kept declaring varchar for catalog booleans long after this was fixed
        (T011h). One implementation, both callers.
        """
        from .sql_translator.column_types import catalog_column_type_oid

        return catalog_column_type_oid(sql, item_index)

    def _override_types_from_sql(
        self, columns: list[dict[str, Any]], sql: str
    ) -> list[dict[str, Any]]:
        """Apply the types the statement settles, over whatever IRIS reported.

        Applied last and on every materialization path, so a Describe (which
        executes with dummy parameters and so may return no rows) declares the
        same types as an Execute that returns several — T011h.

        Skipped when the counts differ: a `SELECT *` expansion would otherwise
        land an override on the wrong column.
        """
        if not columns or not sql:
            return columns
        resolved = self._resolve_sql_column_type_oids(sql)
        if len(resolved) != len(columns):
            return columns
        return [
            {**col, "type_oid": oid} if oid is not None else col
            for col, oid in zip(columns, resolved)
        ]

    def _resolve_sql_column_type_oids(self, sql: str) -> list[int | None]:
        """Per select-list item: the type the statement itself settles, or None.

        Row-count independent, so a Describe that returns no rows declares the
        same types as an Execute that returns several.
        """
        from .sql_translator.column_types import resolve_column_type_oids

        try:
            return resolve_column_type_oids(sql)
        except Exception as exc:  # noqa: BLE001 — never fail a query over metadata
            logger.debug("SQL column-type resolution failed", error=str(exc))
            return []

    def has_returning_clause(self, query: str) -> bool:
        """
        Check if query has a RETURNING clause.
        """
        if not query:
            return False
        return bool(re.search(r"\bRETURNING\b", query, re.IGNORECASE | re.DOTALL))

    def get_returning_columns(self, query: str) -> list[str]:
        """
        Extract column names from RETURNING clause.
        """
        match = re.search(r"RETURNING\s+(.+?)(?=$|;)", query, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        cols_str = match.group(1).strip()
        if cols_str == "*":
            return ["*"]
        return [c.strip() for c in cols_str.split(",")]

    def _get_table_columns_from_schema(
        self, table: str, session_id: str | None = None
    ) -> list[str]:
        """
        Query INFORMATION_SCHEMA.COLUMNS for the given table.
        Returns the list of column names in order.
        """
        if self.strict_single_connection:
            logger.debug("Strict single connection enabled - skipping schema-based column lookup")
            return []
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
        if self.strict_single_connection:
            logger.debug("Strict single connection enabled - skipping schema-based type lookup")
            return None
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
            # Explicitly return VARCHAR (1043) for all strings.
            # Feature 036 fix: Avoid mapping to INT4 or other types even if numeric.
            # UUID detection removed: a UUID-looking string in a VARCHAR column should
            # remain VARCHAR. The correct UUID OID comes from _get_column_type_from_schema
            # when the column is declared as UUID type in the schema.
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
        # PostgreSQL text wire format for TIMESTAMP is "YYYY-MM-DD HH:MM:SS.ffffff"
        # (space separator, no trailing Z/timezone — psycopg TimestampLoader requires this)
        if type_oid == 1114:
            if isinstance(value, int):
                # Convert IRIS/PostgreSQL microsecond integer to PostgreSQL text format
                try:
                    if value >= POSIXTIME_OFFSET:
                        # IRIS POSIXTIME (microseconds since 1970-01-01)
                        unix_us = value - POSIXTIME_OFFSET
                        epoch = dt.datetime(1970, 1, 1)
                        ts_obj = epoch + dt.timedelta(microseconds=unix_us)
                    else:
                        # PostgreSQL legacy/IRIS microsecond integer (microseconds since 2000-01-01)
                        epoch = dt.datetime(2000, 1, 1)
                        ts_obj = epoch + dt.timedelta(microseconds=value)

                    # PostgreSQL wire text format: space separator, no timezone suffix
                    return ts_obj.strftime("%Y-%m-%d %H:%M:%S.%f")
                except Exception:
                    return value
            elif isinstance(value, dt.datetime):
                return value.strftime("%Y-%m-%d %H:%M:%S.%f")
            elif isinstance(value, str):
                stripped = value.strip()
                if stripped.isdigit():
                    # POSIXTIME encoded as digit string — correct formula (NOT // 10**9)
                    unix_us = int(stripped) - POSIXTIME_OFFSET
                    ts_obj = dt.datetime(1970, 1, 1) + dt.timedelta(microseconds=unix_us)
                    return ts_obj.strftime("%Y-%m-%d %H:%M:%S.%f")
                else:
                    # Pre-decoded datetime string from IRIS driver — parse and reformat
                    for fmt in (
                        "%Y-%m-%d %H:%M:%S.%f",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%dT%H:%M:%S.%f",
                        "%Y-%m-%dT%H:%M:%S",
                    ):
                        try:
                            ts_obj = dt.datetime.strptime(stripped.rstrip("Z"), fmt)
                            return ts_obj.strftime("%Y-%m-%d %H:%M:%S.%f")
                        except ValueError:
                            continue
                    return value  # unrecognised format — pass through unchanged

        # OID 1082 = DATE
        if type_oid == 1082 and isinstance(value, int):
            # IRIS Horolog to PG Days already handled in row loop, but for safety:
            return value

        return value

    def _postprocess_rows(self, rows: list[list], columns: list[dict[str, Any]]) -> None:
        """
        Post-process result rows in-place: POSIXTIME detection, value serialization,
        and DATE format conversion. Shared by embedded and external execution paths.
        """
        if not rows or not columns:
            return

        PG_EPOCH = dt.date(2000, 1, 1)
        column_type_oids = [col["type_oid"] for col in columns]

        for row_idx, row in enumerate(rows):
            for col_idx, value in enumerate(row):
                if col_idx >= len(column_type_oids):
                    continue

                type_oid = column_type_oids[col_idx]

                # Detect POSIXTIME masquerading as INT4/INT8
                if type_oid in (20, 23) and isinstance(value, int):
                    if POSIXTIME_OFFSET <= value <= POSIXTIME_MAX:
                        type_oid = 1114
                        if row_idx == 0:
                            columns[col_idx]["type_oid"] = 1114

                # Robust serialization (TIMESTAMP, etc.)
                rows[row_idx][col_idx] = self._serialize_value(rows[row_idx][col_idx], type_oid)
                value = rows[row_idx][col_idx]

                # DATE conversion: IRIS ISO string → PG days since 2000-01-01
                if type_oid == 1082 and value is not None:
                    try:
                        if isinstance(value, str):
                            date_obj = dt.datetime.strptime(value, "%Y-%m-%d").date()
                            rows[row_idx][col_idx] = (date_obj - PG_EPOCH).days
                        elif isinstance(value, int):
                            rows[row_idx][col_idx] = self._convert_iris_horolog_date_to_pg(value)
                    except Exception as date_err:
                        logger.warning(
                            "Failed to convert date value",
                            row=row_idx,
                            col=col_idx,
                            value=value,
                            error=str(date_err),
                        )

    def _prepare_sql(
        self,
        sql: str,
        params: list | None,
        execution_path: str,
        session_id: str | None = None,
        original_sql: str | None = None,
    ) -> tuple[str, list | None, "ReturningPlan", float]:
        """
        Shared pre-execution pipeline (steps 1–7) used by both embedded and external paths.

        Returns:
            (optimized_sql, optimized_params, returning_plan, optimization_time_ms)
        """
        # 1. Transaction Translation
        translated = self.transaction_translator.translate_transaction_command(sql)

        # 2. SQL Normalization
        optimized_sql = self._get_normalized_sql(translated, execution_path=execution_path)

        # Log SLA violations
        norm_metrics = self.sql_translator.get_normalization_metrics()
        if norm_metrics["sla_violated"]:
            logger.warning(
                "SQL normalization exceeded 5ms SLA",
                normalization_time_ms=norm_metrics["normalization_time_ms"],
                session_id=session_id,
            )

        # 3. Parameter Normalization
        optimized_params = self._normalize_parameters(params)

        # 4. Vector Optimization
        t_opt_start = time.perf_counter()
        try:
            from .vector_optimizer import optimize_vector_query

            new_sql, new_params = optimize_vector_query(optimized_sql, optimized_params)
            if new_sql != optimized_sql or new_params != optimized_params:
                logger.debug(
                    "Vector optimization applied",
                    params_before=len(optimized_params) if optimized_params else 0,
                    params_after=len(new_params) if new_params else 0,
                    session_id=session_id,
                )
                optimized_sql = new_sql
                optimized_params = new_params
        except ImportError:
            pass
        except Exception as opt_error:
            logger.warning(
                "Vector optimization failed, using normalized query",
                error=str(opt_error),
                session_id=session_id,
            )
        t_opt_elapsed = (time.perf_counter() - t_opt_start) * 1000

        # 5. RETURNING / ON CONFLICT parsing
        # Use original_sql (pre-translation) for RETURNING detection when available.
        # translated sql (optimized_sql) has the RETURNING clause stripped because IRIS
        # doesn't support it natively — so ReturningPlan must inspect the original.
        _sql_for_plan = original_sql if original_sql else optimized_sql
        plan = ReturningPlan.from_sql(
            _sql_for_plan,
            metadata_cache=self.metadata_cache,
            executor=self,
        )
        if plan.has_returning:
            logger.info(
                "RETURNING clause detected - will emulate",
                operation=plan.operation,
                table=plan.table,
                columns=plan.columns,
                session_id=session_id,
            )
        # Strip RETURNING / ON CONFLICT from the *translated* optimized_sql.
        # When original_sql was provided, plan.stripped_sql is the original (untranslated)
        # SQL with only RETURNING removed — we must NOT use it to overwrite optimized_sql or
        # we'd undo the entire normalization pipeline (DEFAULT, $1 params, schema names, etc.
        # still present → IRIS SQLCODE -12).
        # Instead, apply the same stripping regex directly to optimized_sql.
        if original_sql:
            optimized_sql = ReturningPlan._strip_clauses(
                optimized_sql, plan.returning_clause, plan.on_conflict_clause
            )
        else:
            optimized_sql = plan.stripped_sql

        # 6. Semicolon Stripping
        optimized_sql = optimized_sql.strip().rstrip(";")

        # 7. Schema Translation
        sql_upper = sql.upper()
        if (
            '"public"' in sql_upper
            and not sql_upper.startswith("CREATE")
            and not sql_upper.startswith("ALTER")
        ):
            optimized_sql = self._get_normalized_sql(sql, execution_path=execution_path)

        return optimized_sql, optimized_params, plan, t_opt_elapsed

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
                        captured_iris.sql.exec(
                            "select vector_cosine(to_vector('1'), to_vector('1'))"
                        )
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
            if isinstance(param, dt.datetime):
                # datetime MUST be checked before date (datetime is a subclass of date)
                if param.tzinfo is not None:
                    param = param.astimezone(dt.UTC).replace(tzinfo=None)
                new_params[i] = param.strftime("%Y-%m-%d %H:%M:%S.%f")
            elif isinstance(param, dt.date):
                new_params[i] = param.strftime("%Y-%m-%d")
            elif isinstance(param, int) and MIN_TIMESTAMP < param < MAX_TIMESTAMP:
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
                    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
                    r"(Z|([+-])(\d{2}):?(\d{2}))?$",
                    param,
                )
                if ts_match:
                    date_part, time_part = ts_match.group(1), ts_match.group(2)
                    tz_sign, tz_hh, tz_mm = ts_match.group(4), ts_match.group(5), ts_match.group(6)
                    if tz_sign and tz_hh:
                        # Non-UTC offset: convert to UTC
                        offset_mins = (int(tz_hh) * 60 + int(tz_mm or 0)) * (
                            1 if tz_sign == "+" else -1
                        )
                        fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in time_part else "%Y-%m-%d %H:%M:%S"
                        naive = dt.datetime.strptime(f"{date_part} {time_part}", fmt)
                        utc = naive - dt.timedelta(minutes=offset_mins)
                        new_params[i] = utc.strftime(fmt)
                    else:
                        new_params[i] = f"{date_part} {time_part}"
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
        self, sql: str, params: list | None = None, session_id: str | None = None, **kwargs
    ) -> dict[str, Any]:
        """
        Execute SQL query against IRIS with proper async threading
        """
        try:
            # Feature 022: Apply PostgreSQL→IRIS transaction verb translation FIRST
            sql = self.transaction_translator.translate_transaction_command(sql)

            # Feature: Handle catalog emulation shared across all paths
            catalog_result = await self.catalog_router.handle_catalog_query(
                sql, params, session_id, self
            )
            if catalog_result is not None:
                return catalog_result

            intercept_result = self.sql_interceptor.intercept(sql, params, session_id)
            if intercept_result.intercepted:
                return intercept_result.result

            # Rewrite ARRAY['a','b'] constructor syntax to '{a,b}' before IRIS
            # sees the query — IRIS cannot parse the constructor at all (feature 047).
            sql = rewrite_array_literals(sql)

            # Rewrite `col = ANY($n)` to `col %INLIST $n`. IRIS has no
            # ANY(array) construct — it reaches the parser as
            # "SELECT expected, ? found" — and the rewrite has to happen
            # whether or not values are bound, because Describe prepares the
            # statement with nothing bound. Applied to every statement rather
            # than only intercepted ones: catalog tables served by IRIS views
            # reach the database for real (feature 044).
            if has_array_param(sql):
                sql = expand_array_literals(rewrite_any_to_inlist(sql))
                params = encode_inlist_params(sql, params)

            # Rewrite `expr = ANY(col)` where col is a bare column reference
            # (catalog array columns like conkey/indkey stored as text).
            sql = rewrite_any_col_to_instr(sql)

            # Rewrite a boolean expression used as a projected value into
            # CAST(CASE WHEN ... AS BIT). IRIS has no boolean type and takes
            # AND/OR only in a predicate, so `(a AND b = 1) AS flag` fails at
            # parse time with "ERROR: ) expected, AND found". Prisma's table
            # query projects two of these.
            if has_boolean_projection(sql):
                sql = rewrite_boolean_projections(sql)

            # Point unqualified catalog function calls at the PGWire schema.
            # IRIS resolves `obj_description(...)` against the default schema
            # and reports SQLUSER.OBJ_DESCRIPTION does not exist.
            if has_pg_function_call(sql):
                sql = rewrite_pg_function_calls(sql)

            # `relispartition = 'f'` -> `relispartition = 0`. The views hold 0/1
            # for the columns PostgreSQL declares bool, and comparing one to the
            # string 'f' inside a nested predicate group crashes IRIS outright
            # (SQLCODE -400) rather than erroring — the shape Prisma emits.
            if has_boolean_literal_comparison(sql):
                sql = rewrite_boolean_literal_comparisons(sql)

            # IRIS does not accept parameterized LIMIT/OFFSET — inline them.
            if params and re.search(r"\b(?:LIMIT|OFFSET)\s+\?", sql, re.IGNORECASE):
                sql, params = inline_limit_offset_params(sql, params)

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
                    result = await self._execute_embedded_async(
                        sql, params, session_id, original_sql=kwargs.get("original_sql")
                    )
                else:
                    logger.warning("🔍 DEBUG: Taking EXTERNAL path → _execute_external_async()")
                    result = await self._execute_external_async(
                        sql, params, session_id, original_sql=kwargs.get("original_sql")
                    )

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

        RETURNING SUPPORT: When SQL contains RETURNING clause, executes each INSERT
        individually and aggregates the returned rows from all inserts.
        """
        # Strip ON CONFLICT clause before sending to IRIS — IRIS has no upsert syntax.
        # For DO NOTHING: duplicate key errors are caught and suppressed below.
        # For DO UPDATE: not supported via execute_many; falls through to execute_query.
        if re.search(r"\bON\s+CONFLICT\b", sql, re.IGNORECASE):
            plan = ReturningPlan.from_sql(sql)
            sql = ReturningPlan._strip_clauses(sql, plan.returning_clause, plan.on_conflict_clause)
            sql = sql.strip().rstrip(";")

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
                    result = await self._execute_many_with_returning(sql, params_list, session_id)
                    job.mark_completed(rows_inserted=result.get("rows_affected", len(params_list)))
                else:
                    # ALWAYS try native fast-insert path first
                    try:
                        result = await self._execute_many_native(sql, params_list, session_id)
                        job.mark_completed(
                            rows_inserted=result.get("rows_affected", len(params_list))
                        )
                    except Exception as native_error:
                        logger.warning(
                            "Native executemany() failed, falling back to string inlining",
                            error=str(native_error)[:200],
                            session_id=session_id,
                        )
                        # Fallback to string inlining (reliable but slower)
                        result = await self._execute_many_inline_fallback(
                            sql, params_list, session_id
                        )
                        job.mark_completed(
                            rows_inserted=result.get("rows_affected", len(params_list))
                        )

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
        plan = ReturningPlan.from_sql(sql, metadata_cache=self.metadata_cache, executor=self)

        if not plan.operation or not plan.table:
            logger.warning(
                "Could not parse RETURNING clause, falling back to standard execute_many",
                sql=sql[:100],
                session_id=session_id,
            )
            return await self._execute_many_native(sql, params_list, session_id)

        logger.info(
            "execute_many with RETURNING: processing batch individually",
            operation=plan.operation,
            table=plan.table,
            columns=plan.columns,
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
                            iris.sql.exec(plan.stripped_sql, *normalized_params)
                        else:
                            iris.sql.exec(plan.stripped_sql)
                else:
                    conn = self._get_pooled_connection(session_id=session_id)
                    cursor = conn.cursor()
                    try:
                        normalized_params = self._normalize_parameters(params)
                        if normalized_params:
                            cursor.execute(plan.stripped_sql, tuple(normalized_params))
                        else:
                            cursor.execute(plan.stripped_sql)
                        conn.commit()
                    finally:
                        cursor.close()
                        self._return_connection(conn, session_id=session_id)

                # Emulate RETURNING for this row
                rows, meta = self._emulate_returning(
                    plan=plan,
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
                batch_size=len(params_list),
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

        with self._connection_lock:
            for executor in self.session_executors.values():
                executor.shutdown(wait=False)
            self.session_executors.clear()
            for conn in self._connection_pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._connection_pool.clear()
            self._active_count = 0

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
                    # Normalize parameters for IRIS (e.g. ISO timestamps)
                    normalized_row_params = self._normalize_parameters(row_params)

                    inline_sql = "N/A"
                    try:
                        # Build inline SQL by replacing ? placeholders with actual values
                        inline_sql = normalized_sql
                        for param_value in normalized_row_params:
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
        connection: Any = None,
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
            return NoopCursor()

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
                # Use provided connection if available, otherwise get one from pool
                if connection is None:
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
                    if cursor:
                        try:
                            cursor.close()
                        except Exception:
                            pass
                    raise e
        except Exception as e:
            result = self.ddl_handler.handle(sql, e)
            if result.success and result.skipped:
                return NoopCursor()
            raise e

    def _parse_returning_clause(
        self, sql: str
    ) -> tuple[str | None, str | None, Any, str | None, str]:
        """
        Parse RETURNING clause from SQL and return metadata.
        Returns: (operation, table, columns, where_clause, stripped_sql)
        """
        plan = ReturningPlan.from_sql(sql, metadata_cache=self.metadata_cache, executor=self)
        return plan.operation, plan.table, plan.columns, plan.where_clause, plan.stripped_sql

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
        col_match = re.search(r"INSERT\s+INTO\s+[^\s(]+\s*\(\s*([^)]+)\s*\)", sql, re.IGNORECASE)
        if not col_match:
            return None, None

        columns_str = col_match.group(1)
        columns = [c.strip().strip('"').strip("'").lower() for c in columns_str.split(",")]

        # Find ID column position (common names: id, uuid, _id)
        id_col_names = ["id", "uuid", "_id"]
        id_col_idx = None
        id_col_name = None
        for i, col in enumerate(columns):
            if col in id_col_names:
                id_col_idx = i
                # Return UPPERCASE so the WHERE clause matches IRIS's stored column name.
                # IRIS stores unquoted column names as uppercase; using "id" (lowercase)
                # in a quoted identifier fails silently and returns 0 rows.
                id_col_name = col.upper()
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
        values_match = re.search(r"VALUES\s*\(\s*(.+?)\s*\)", sql, re.IGNORECASE | re.DOTALL)
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
                elif char == "," and not in_quote:
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
        plan: ReturningPlan,
        params: list | None,
        is_embedded: bool,
        connection: Any = None,
        session_id: str | None = None,
        original_sql: str | None = None,
        override_operation: str | None = None,
        override_where: str | None = None,
    ) -> tuple[list[Any], Any]:
        """
        Emulate PostgreSQL RETURNING clause for IRIS.

        Returns: (rows, metadata)
        """
        import re

        # CRITICAL FIX: Normalize table name to UPPERCASE for IRIS compatibility
        operation = override_operation or plan.operation
        table = plan.table
        table_normalized = table.upper() if table else None
        table_lower = table.lower() if table else ""
        columns = plan.columns
        where_clause = override_where or plan.where_clause

        # Handle columns as list or '*'
        if columns == "*":
            # Expand * early to get real column names
            expanded_cols = self._expand_select_star(
                f"SELECT * FROM {IRIS_SCHEMA}.{table_normalized}", 0, session_id=session_id
            )
            if expanded_cols:
                columns = expanded_cols
                col_list = ", ".join([f'"{col}"' for col in columns])
            else:
                col_list = "*"
        else:
            if plan.column_meta:
                col_list = plan.select_list
            else:
                # columns is a list of expressions/names. Preserve them but quote simple identifiers.
                processed_cols = []
                for col in columns:
                    if re.match(r"^\"?\w+\"?$", col):
                        # Simple identifier - quote it
                        clean_col = col.strip('"')
                        processed_cols.append(f'"{clean_col}"')
                    else:
                        # Expression - leave as is
                        processed_cols.append(col)
                col_list = ", ".join(processed_cols)

        rows = []
        meta = None

        # Helper to execute and materialize results
        def _fetch_results(captured_sql, select_params=None):
            if is_embedded:
                iris = self._import_iris()
                if iris:
                    res = (
                        iris.sql.exec(captured_sql, *select_params)
                        if select_params
                        else iris.sql.exec(captured_sql)
                    )
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
                        f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE %ID = ?',
                        [last_id],
                    )
                    if not rows and isinstance(columns, list):
                        id_cols = [
                            c
                            for c in columns
                            if c.lower() in ("id", "identity", "pk", table_lower + "id")
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

                    select_sql = f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE {translated_where}'

                    # Extract WHERE clause parameters (they are the last N parameters)
                    where_param_count = len(re.findall(r"\?", where_clause))
                    where_params = (
                        params[-where_param_count:] if params and where_param_count > 0 else None
                    )
                    rows, meta = _fetch_results(select_sql, where_params)

            # Build/Fix metadata
            if meta is None or not any("type_oid" in c for c in meta if isinstance(c, dict)):
                # cursor_meta holds the raw cursor.description from _fetch_results.
                # It is a sequence of 7-tuples: (name, type_code, ...).
                # Use type_code via _iris_type_to_pg_oid as a reliable fallback
                # before _infer_type_from_value, which can misidentify value types
                # (e.g. IRIS returning "12345" as int for a VARCHAR column).
                cursor_meta = meta  # raw cursor.description before we rebuild it
                column_defs = plan.column_meta or []
                if column_defs:
                    new_meta = []
                    for idx, col_meta in enumerate(column_defs):
                        col_name = col_meta.alias or col_meta.normalized_name
                        col_oid = self._get_column_type_from_schema(
                            table, col_name, session_id=session_id
                        )
                        if col_oid is None and cursor_meta and idx < len(cursor_meta):
                            # Use IRIS cursor type_code (element [1] of description tuple)
                            type_code = cursor_meta[idx][1] if len(cursor_meta[idx]) > 1 else None
                            if type_code is not None:
                                col_oid = self._iris_type_to_pg_oid(type_code)
                        if col_oid is None and rows and idx < len(rows[0]):
                            col_oid = self._infer_type_from_value(rows[0][idx], col_name)
                        new_meta.append(
                            {
                                "name": col_name,
                                "type_oid": col_oid or 1043,
                                "type_size": -1,
                                "type_modifier": -1,
                                "format_code": 0,
                            }
                        )
                    meta = new_meta
                elif isinstance(columns, list):
                    new_meta = []
                    for i, col in enumerate(columns):
                        # Extract alias or column name
                        col_name = col
                        alias_match = re.search(r"\s+AS\s+\"?(\w+)\"?$", col, re.IGNORECASE)
                        if alias_match:
                            col_name = alias_match.group(1)
                        else:
                            col_name = col_name.strip('"')
                            if "." in col_name:
                                col_name = col_name.split(".")[-1]

                        col_oid = self._get_column_type_from_schema(
                            table, col_name, session_id=session_id
                        )
                        if col_oid is None and cursor_meta and i < len(cursor_meta):
                            # Use IRIS cursor type_code (element [1] of description tuple)
                            type_code = cursor_meta[i][1] if len(cursor_meta[i]) > 1 else None
                            if type_code is not None:
                                col_oid = self._iris_type_to_pg_oid(type_code)
                        if col_oid is None and rows:
                            # Last resort: infer from value
                            col_oid = self._infer_type_from_value(rows[0][i], col_name)

                        new_meta.append(
                            {
                                "name": col_name,
                                "type_oid": col_oid or 1043,
                                "type_size": -1,
                                "type_modifier": -1,
                                "format_code": 0,
                            }
                        )
                    meta = new_meta
                else:
                    # columns is '*' and expansion failed
                    pass

        except Exception as e:
            logger.error(f"RETURNING emulation failed for {operation}", error=str(e))

        return rows, meta

    def _is_unique_violation(self, error: Exception) -> bool:
        message = str(error).lower()
        return any(keyword in message for keyword in ("unique", "duplicate", "constraint"))

    def _map_insert_column_values(self, plan: ReturningPlan, params: list | None) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if not params:
            return values
        for idx, column in enumerate(plan.insert_columns):
            if idx < len(params):
                values[column] = params[idx]
        return values

    def _prepare_conflict_set_clause(
        self, plan: ReturningPlan, column_values: dict[str, Any]
    ) -> tuple[str, list[Any]]:
        if not plan.conflict_set_clause:
            return "", []
        params: list[Any] = []
        pattern = re.compile(r"\bEXCLUDED\.\"?(\w+)\"?", re.IGNORECASE)

        def _replace(match: re.Match) -> str:
            column = match.group(1).lower()
            params.append(column_values.get(column))
            return "?"

        set_clause = pattern.sub(_replace, plan.conflict_set_clause)
        return set_clause, params

    def _prepare_conflict_where_clause(
        self, plan: ReturningPlan, column_values: dict[str, Any]
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column in plan.conflict_target_columns:
            identifier = column.upper()
            clauses.append(f'"{identifier}" = ?')
            params.append(column_values.get(column))

        where_clause = " AND ".join(clauses)
        if plan.conflict_where_clause:
            if where_clause:
                where_clause = f"{where_clause} AND {plan.conflict_where_clause}"
            else:
                where_clause = plan.conflict_where_clause
        return where_clause, params

    def _handle_on_conflict_update(
        self,
        plan: ReturningPlan,
        params: list | None,
        connection: Any,
        session_id: str | None,
        original_sql: str | None,
    ) -> tuple[list[Any], Any]:
        if not plan.table:
            raise RuntimeError("Cannot emulate ON CONFLICT without target table")
        if not plan.conflict_set_clause or not plan.conflict_target_columns:
            raise RuntimeError("ON CONFLICT DO UPDATE clause is incomplete")

        column_values = self._map_insert_column_values(plan, params)
        set_clause, set_params = self._prepare_conflict_set_clause(plan, column_values)
        where_clause, where_params = self._prepare_conflict_where_clause(plan, column_values)

        if not set_clause or not where_clause:
            raise RuntimeError("Insufficient data to build ON CONFLICT UPDATE")

        update_sql = f'UPDATE {IRIS_SCHEMA}."{plan.table}" SET {set_clause} WHERE {where_clause}'
        cursor = self._safe_execute(
            update_sql,
            set_params + where_params,
            is_embedded=False,
            session_id=session_id,
            connection=connection,
        )
        try:
            cursor.close()
        except Exception:
            pass

        rows, meta = self._emulate_returning(
            plan,
            params=where_params,
            is_embedded=False,
            connection=connection,
            session_id=session_id,
            original_sql=original_sql,
            override_operation="UPDATE",
            override_where=where_clause,
        )
        return rows, meta

    def _close_cursor_if_possible(self, cursor: Any) -> None:
        """Safely close a cursor-like resource without raising."""
        if cursor and hasattr(cursor, "close"):
            try:
                cursor.close()
            except Exception:
                pass

    def _execute_embedded_statement_sequence(
        self, statements: list[str], params: list | None, session_id: str | None
    ) -> Any:
        """Execute statement sequence for embedded mode and return the final cursor."""
        if not statements:
            return NoopCursor()

        if len(statements) > 1:
            logger.info(
                "Executing multiple statements",
                statement_count=len(statements),
                session_id=session_id,
            )

        for stmt in statements[:-1]:
            tmp_result = self._safe_execute(stmt, None, is_embedded=True, session_id=session_id)
            self._close_cursor_if_possible(tmp_result)

        return self._safe_execute(statements[-1], params, is_embedded=True, session_id=session_id)

    def _resolve_embedded_returning_result(
        self,
        result: Any,
        plan: ReturningPlan,
        delete_rows: list[Any],
        delete_meta: Any,
        params: list | None,
        session_id: str | None,
        original_sql: str | None,
    ) -> Any:
        if not plan.has_returning or not plan.columns:
            return result

        if plan.operation == "DELETE":
            return MockResult(delete_rows, delete_meta)

        rows, meta = self._emulate_returning(
            plan,
            params=params,
            is_embedded=True,
            session_id=session_id,
            original_sql=original_sql,
        )
        return MockResult(rows, meta)

    def _materialize_embedded_result(
        self,
        result: Any,
        optimized_sql: str,
        optimized_sql_upper: str,
        sql: str,
        session_id: str | None,
    ) -> tuple[list[list[Any]], list[dict[str, Any]]]:
        rows: list[list[Any]] = []
        columns: list[dict[str, Any]] = []

        meta = getattr(result, "_meta", None)
        if meta:
            for col_info in meta:
                iris_col_name = col_info.get("name", "")
                iris_type = col_info.get("type", "VARCHAR")
                precomputed_oid = col_info.get("type_oid")
                normalized_name = self._normalize_iris_column_name(
                    iris_col_name, optimized_sql, iris_type
                )
                type_oid = (
                    precomputed_oid
                    if precomputed_oid is not None
                    else self._iris_type_to_pg_oid(iris_type)
                )

                if iris_type == 2:
                    if (
                        "AS INTEGER" in optimized_sql_upper or "AS INT" in optimized_sql_upper
                    ) and type_oid != 23:
                        type_oid = 23
                    elif (
                        "AS NUMERIC" not in optimized_sql_upper
                        and "AS DECIMAL" not in optimized_sql_upper
                        and type_oid not in (701, 23)
                    ):
                        type_oid = 701

                if "CURRENT_TIMESTAMP" in optimized_sql_upper and type_oid in (25, 1043):
                    type_oid = 1114

                columns.append(
                    {
                        "name": normalized_name,
                        "type_oid": type_oid,
                        "type_size": col_info.get("size", -1),
                        "type_modifier": -1,
                        "format_code": 0,
                    }
                )

        try:
            for row in result:
                if isinstance(row, list | tuple):
                    normalized_row = [self._normalize_iris_null(value) for value in row]
                    rows.append(normalized_row)
                else:
                    normalized_value = self._normalize_iris_null(row)
                    rows.append([normalized_value])
        except Exception as fetch_error:
            logger.warning(
                "Error fetching IRIS result rows",
                error=str(fetch_error),
                session_id=session_id,
            )

        if not columns:
            if rows:
                columns = self._discover_metadata(
                    sql, session_id, expected_count=len(rows[0]), rows=rows
                )
            elif optimized_sql_upper.startswith("SELECT"):
                columns = self._discover_metadata(sql, session_id)

        columns = self._override_types_from_sql(columns, optimized_sql)
        self._postprocess_rows(rows, columns)
        return rows, columns

    async def _execute_embedded_async(
        self,
        sql: str,
        params: list | None = None,
        session_id: str | None = None,
        original_sql: str | None = None,
    ) -> dict[str, Any]:
        """Execute query in IRIS embedded Python environment (async wrapper)"""

        def _sync_execute(captured_sql, captured_params, captured_session_id):
            """Synchronous IRIS execution in thread pool"""
            sql = captured_sql
            params = captured_params
            session_id = captured_session_id

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
                            logger.warning(
                                "Namespace not ready, retrying...",
                                namespace=effective_ns,
                                attempt=attempt + 1,
                            )
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

            try:
                # PROFILING: Track detailed timing
                t_start_total = time.perf_counter()

                # Get or create connection
                self._get_iris_connection()

                # Steps 1-7: Shared pre-execution pipeline
                optimized_sql, optimized_params, plan, t_opt_elapsed = self._prepare_sql(
                    sql,
                    params,
                    execution_path="direct",
                    session_id=session_id,
                    original_sql=original_sql,
                )
                optimized_sql_upper = optimized_sql.upper()
                returning_operation = plan.operation
                returning_table = plan.table
                returning_columns = plan.columns

                # POSTGRESQL COMPATIBILITY: Handle SHOW commands that IRIS doesn't support
                # Intercept and return fake results for PostgreSQL compatibility
                if optimized_sql.upper().strip().startswith("SHOW "):
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
                    session_id=session_id,
                )

                # PROFILING: IRIS execution timing
                t_iris_start = time.perf_counter()

                # Pre-fetch rows for DELETE RETURNING (must happen before deletion)
                delete_returning_rows = []
                delete_returning_meta = None
                if plan.operation == "DELETE" and plan.columns:
                    delete_returning_rows, delete_returning_meta = self._emulate_returning(
                        plan,
                        optimized_params,
                        is_embedded=True,
                    )
                    if delete_returning_rows:
                        logger.info(
                            "Pre-DELETE: Row(s) captured for RETURNING",
                            row_count=len(delete_returning_rows),
                            session_id=session_id,
                        )

                statements = self._split_sql_statements(optimized_sql)
                result = self._execute_embedded_statement_sequence(
                    statements, optimized_params, session_id
                )

                result = self._resolve_embedded_returning_result(
                    result,
                    plan,
                    delete_returning_rows,
                    delete_returning_meta,
                    optimized_params,
                    session_id,
                    sql,
                )

                t_iris_elapsed = (time.perf_counter() - t_iris_start) * 1000
                execution_time = (time.perf_counter() - start_time) * 1000

                # PROFILING: Result processing timing
                t_fetch_start = time.perf_counter()

                rows, columns = self._materialize_embedded_result(
                    result, optimized_sql, optimized_sql_upper, sql, session_id
                )
                t_fetch_elapsed = (time.perf_counter() - t_fetch_start) * 1000

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

        # Execute in thread pool to avoid blocking event loop.
        #
        # Through a copied context, because run_in_executor does not carry
        # ContextVars into the worker thread the way asyncio.to_thread does —
        # and _prepare_sql, which runs in there, reads one. Without this the
        # verbatim-SQL guard silently read its default and the catalog function
        # installer's ObjectScript bodies were translated after all.
        loop = asyncio.get_event_loop()
        context = contextvars.copy_context()
        return await loop.run_in_executor(
            self._get_executor(session_id),
            lambda: context.run(_sync_execute, sql, params, session_id),
        )

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
                for _row in result:
                    break
            except Exception:
                pass

            # Method 3: Check for description attribute (DB-API 2.0 standard)
            if hasattr(result, "description") and result.description:
                for col_desc in result.description:
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
                _,
                _,
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
                else:
                    # A catalog column carries its PostgreSQL type even when the
                    # value cannot show it — bool and text[] both arrive as an
                    # int or None from IRIS.
                    catalog_oid = self._detect_catalog_column_type_oid(sql, i)
                    if catalog_oid:
                        inferred_type = catalog_oid

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

    def _materialize_external_result(
        self,
        cursor: Any,
        optimized_sql: str,
        optimized_sql_upper: str,
        sql: str,
        session_id: str | None,
    ) -> tuple[list[list[Any]], list[dict[str, Any]]]:
        if not cursor:
            return [], []

        rows: list[list[Any]] = []
        columns: list[dict[str, Any]] = []

        description = getattr(cursor, "_meta", None) or getattr(cursor, "description", None)
        if description:
            for desc in description:
                if isinstance(desc, dict):
                    iris_col_name = desc.get("name", "")
                    iris_type = desc.get("iris_type", desc.get("type", "VARCHAR"))
                    precomputed_oid = desc.get("type_oid")
                    type_size = desc.get("size", -1)
                else:
                    iris_col_name = desc[0]
                    iris_type = desc[1] if len(desc) > 1 else "VARCHAR"
                    precomputed_oid = None
                    type_size = desc[2] if len(desc) > 2 else -1

                col_name = self._normalize_iris_column_name(iris_col_name, optimized_sql, iris_type)
                type_oid = (
                    precomputed_oid
                    if precomputed_oid is not None
                    else self._iris_type_to_pg_oid(iris_type)
                )

                if iris_type == 2:
                    if (
                        "AS INTEGER" in optimized_sql_upper or "AS INT" in optimized_sql_upper
                    ) and type_oid != 23:
                        type_oid = 23
                    elif (
                        "AS NUMERIC" not in optimized_sql_upper
                        and "AS DECIMAL" not in optimized_sql_upper
                        and type_oid not in (701, 23)
                    ):
                        type_oid = 701

                if "CURRENT_TIMESTAMP" in optimized_sql_upper and type_oid == 1043:
                    type_oid = 1114

                columns.append(
                    {
                        "name": col_name,
                        "type_oid": type_oid,
                        "type_size": type_size,
                        "type_modifier": -1,
                        "format_code": 0,
                    }
                )

        try:
            results = cursor.fetchall() if hasattr(cursor, "fetchall") else []
            for row in results:
                if isinstance(row, list | tuple):
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
                    rows.append([row])
        except Exception as fetch_error:
            logger.warning(
                "Failed to fetch external IRIS results",
                error=str(fetch_error),
                session_id=session_id,
            )

        if not columns:
            if rows:
                columns = self._discover_metadata(
                    sql, session_id, expected_count=len(rows[0]), rows=rows
                )
            elif optimized_sql_upper.startswith("SELECT"):
                columns = self._discover_metadata(sql, session_id)

        columns = self._override_types_from_sql(columns, optimized_sql)
        self._postprocess_rows(rows, columns)
        return rows, columns

    async def _execute_external_async(
        self,
        sql: str,
        params: list | None = None,
        session_id: str | None = None,
        original_sql: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute SQL using external IRIS connection with proper async threading
        """

        import threading

        # Shared flag: asyncio side sets this True when wait_for times out so the
        # sync thread knows to close (evict) the connection instead of recycling it.
        timed_out = threading.Event()

        def _sync_external_execute(captured_sql, captured_params, captured_session_id):
            """Synchronous external IRIS execution in thread pool"""
            sql = captured_sql
            params = captured_params
            session_id = captured_session_id

            conn = None
            cursor = None

            try:
                # PROFILING: Track detailed timing
                t_start_total = time.perf_counter()

                # Steps 1-7: Shared pre-execution pipeline
                optimized_sql, optimized_params, plan, t_opt_elapsed = self._prepare_sql(
                    sql,
                    params,
                    execution_path="external",
                    session_id=session_id,
                    original_sql=original_sql,
                )
                optimized_sql_upper = optimized_sql.upper()

                # Pre-process parameters to convert lists to IRIS vector strings
                # This ensures the DBAPI driver doesn't convert them to {...} format
                if optimized_params:
                    processed_params = []
                    for p in optimized_params:
                        if isinstance(p, list):
                            processed_params.append("[" + ",".join(str(float(v)) for v in p) + "]")
                        else:
                            # Feature 036: Ensure we pass strings or numbers, not complex objects
                            if p is not None and not isinstance(
                                p, int | float | str | bool | bytes
                            ):
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
                if plan.operation == "DELETE" and plan.columns:
                    delete_returning_rows, delete_returning_meta = self._emulate_returning(
                        plan,
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
                    tmp_cursor = self._safe_execute(
                        stmt, None, is_embedded=False, session_id=session_id, connection=conn
                    )
                    if tmp_cursor:
                        try:
                            tmp_cursor.close()
                        except Exception:
                            pass

                # Execute last statement and handle ON CONFLICT if needed
                cursor = None
                conflict_emulated = False
                try:
                    cursor = self._safe_execute(
                        statements[-1],
                        optimized_params,
                        is_embedded=False,
                        session_id=session_id,
                        connection=conn,
                    )
                except Exception as exc:
                    if plan.conflict_action and self._is_unique_violation(exc):
                        if plan.conflict_action == "DO NOTHING":
                            logger.info(
                                "ON CONFLICT DO NOTHING handled in executor",
                                table=plan.table,
                                session_id=session_id,
                            )
                            cursor = MockResult([], None)
                            conflict_emulated = True
                        else:
                            rows, meta = self._handle_on_conflict_update(
                                plan,
                                optimized_params,
                                conn,
                                session_id,
                                sql,
                            )
                            cursor = MockResult(rows, meta)
                            conflict_emulated = True
                    else:
                        raise

                # RETURNING emulation
                if plan.has_returning and plan.columns and not conflict_emulated:
                    if plan.operation == "DELETE":
                        cursor = MockResult(delete_returning_rows, delete_returning_meta)
                    else:
                        rows, meta = self._emulate_returning(
                            plan,
                            optimized_params,
                            is_embedded=False,
                            connection=conn,
                            session_id=session_id,
                            original_sql=sql,
                        )
                        cursor = MockResult(rows, meta)

                # Commit for non-SELECT statements to ensure visibility for emulation and durability
                if not statements[-1].upper().strip().startswith("SELECT"):
                    try:
                        conn.commit()
                    except Exception as commit_err:
                        logger.warning(f"Failed to commit {statements[-1][:50]}: {commit_err}")

                t_iris_elapsed = (time.perf_counter() - t_iris_start) * 1000
                execution_time = (time.perf_counter() - start_time) * 1000

                # PROFILING: Result processing timing
                t_fetch_start = time.perf_counter()
                rows, columns = self._materialize_external_result(
                    cursor, optimized_sql, optimized_sql_upper, sql, session_id
                )
                t_fetch_elapsed = (time.perf_counter() - t_fetch_start) * 1000

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

            finally:
                if cursor and hasattr(cursor, "close"):
                    try:
                        cursor.close()
                    except Exception:
                        pass
                if conn:
                    if timed_out.is_set():
                        # Evict — don't return a lock-held connection to the pool
                        try:
                            conn.close()
                        except Exception:
                            pass
                        logger.warning(
                            "Evicted timed-out IRIS connection from pool",
                            session_id=session_id,
                        )
                    else:
                        self._return_connection(conn, session_id=session_id)

        # Execute in thread pool to avoid blocking event loop.
        # Wrap with a per-query timeout to prevent lock-wait cascades from
        # exhausting the connection pool (PGWIRE_QUERY_TIMEOUT, default 30s).
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            self._get_executor(session_id), _sync_external_execute, sql, params, session_id
        )
        try:
            return await asyncio.wait_for(future, timeout=self.query_timeout)
        except TimeoutError:
            timed_out.set()  # Signal the sync thread to evict the connection
            logger.error(
                "Query timed out — connection will be evicted from pool",
                sql_preview=sql[:120],
                timeout_seconds=self.query_timeout,
                session_id=session_id,
            )
            raise RuntimeError(
                f"Query execution timed out after {self.query_timeout}s. "
                "The IRIS connection is being evicted to prevent pool exhaustion."
            )

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

    def _is_connection_alive(self, conn) -> bool:
        """Check if an IRIS connection is still alive."""
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except Exception:
            return False

    def _get_pooled_connection(self, session_id: str | None = None):
        if session_id and session_id in self.session_connections:
            conn = self.session_connections[session_id]
            # Verify session connection is still alive
            if self._is_connection_alive(conn):
                return conn
            else:
                logger.warning(
                    "Session connection died, removing and creating new one", session_id=session_id
                )
                try:
                    conn.close()
                except Exception:
                    pass
                del self.session_connections[session_id]
                with self._connection_lock:
                    self._active_count -= 1

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
                if self._is_connection_alive(conn):
                    return conn
                else:
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

    async def close_session(self, session_id: str):
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
                table_regex = (
                    r'(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:(?:"?\w+"?)\s*\.\s*)*"?(\w+)"?'
                )
                table_match = re.search(table_regex, sql, re.IGNORECASE)
                if table_match:
                    table_name = table_match.group(1)
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
                # Standard JDBC type codes (IRIS also returns these)
                91: 1082,  # JDBC DATE → pg date
                92: 1083,  # JDBC TIME → pg time
                93: 1114,  # JDBC TIMESTAMP → pg timestamp
                # IRIS extended type codes (returned for TIMESTAMP/POSIXTIME columns)
                1091: 1082,  # IRIS extended DATE → pg date
                1092: 1083,  # IRIS extended TIME → pg time
                1093: 1114,  # IRIS extended TIMESTAMP → pg timestamp
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
            if self.embedded_mode:
                iris = self._import_iris()
                if iris:
                    iris.sql.exec("ROLLBACK")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._get_executor(session_id), _sync_rollback, session_id
        )

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
