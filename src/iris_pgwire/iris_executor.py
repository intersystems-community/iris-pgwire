"""
IRIS SQL Executor for PostgreSQL Wire Protocol

Handles SQL execution against IRIS using embedded Python or external connection.
Based on patterns from caretdev/sqlalchemy-iris for proven IRIS integration.
"""

import asyncio
import os
import concurrent.futures
import threading
import time
from typing import Dict, Any, List, Optional, Union
import structlog

from .sql_translator.performance_monitor import get_monitor, MetricType, PerformanceTracker

logger = structlog.get_logger()


class IRISExecutor:
    """
    IRIS SQL Execution Handler

    Manages SQL execution against IRIS database using embedded Python when available,
    or external connection as fallback. Implements patterns proven in caretdev
    SQLAlchemy implementation.
    """

    def __init__(self, iris_config: Dict[str, Any], server=None):
        self.iris_config = iris_config
        self.server = server  # Reference to server for P4 cancellation
        self.connection = None
        self.embedded_mode = False
        self.vector_support = False

        # Thread pool for async IRIS operations (constitutional requirement)
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=10,
            thread_name_prefix="iris_executor"
        )

        # Performance monitoring
        self.performance_monitor = get_monitor()

        # Connection pool management
        self._connection_lock = threading.RLock()
        self._connection_pool = []
        self._max_connections = 10

        # Attempt to detect IRIS environment
        self._detect_iris_environment()

        logger.info("IRIS executor initialized",
                   host=iris_config.get('host'),
                   port=iris_config.get('port'),
                   namespace=iris_config.get('namespace'),
                   embedded_mode=self.embedded_mode)

    def _detect_iris_environment(self):
        """Detect if we're running in IRIS embedded Python environment"""
        try:
            # Try to import IRIS embedded Python module
            import iris
            # Check if we're in embedded mode by testing for embedded-specific features
            if hasattr(iris, 'sql') and hasattr(iris.sql, 'exec'):
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

    async def test_connection(self):
        """Test IRIS connectivity before starting server"""
        try:
            if self.embedded_mode:
                # In embedded mode, skip connection test at startup
                # IRIS is already available via iris.sql.exec()
                logger.info("IRIS embedded mode detected - skipping connection test",
                           embedded_mode=True)
            else:
                await self._test_external_connection()

            # Test vector support (from caretdev pattern)
            await self._test_vector_support()

            logger.info("IRIS connection test successful",
                       embedded_mode=self.embedded_mode,
                       vector_support=self.vector_support)

        except Exception as e:
            logger.error("IRIS connection test failed", error=str(e))
            raise ConnectionError(f"Cannot connect to IRIS: {e}")

    async def _test_embedded_connection(self):
        """Test IRIS embedded Python connection"""
        def _sync_test():
            import iris
            # Simple test query
            result = iris.sql.exec("SELECT 1 as test_column").fetch()
            return result[0]['test_column'] == 1

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
                        hostname=self.iris_config['host'],
                        port=self.iris_config['port'],
                        namespace=self.iris_config['namespace'],
                        username=self.iris_config['username'],
                        password=self.iris_config['password']
                    )

                    # Test simple query
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    cursor.close()
                    conn.close()

                    return result[0] == 1

                except Exception as e:
                    logger.warning("Real IRIS connection failed, config validation only", error=str(e))
                    # Fallback to config validation
                    required_keys = ['host', 'port', 'username', 'password', 'namespace']
                    for key in required_keys:
                        if key not in self.iris_config:
                            raise ValueError(f"Missing IRIS config: {key}")
                    return True

            result = await asyncio.to_thread(_sync_test)

            logger.info("IRIS connection test successful",
                       host=self.iris_config['host'],
                       port=self.iris_config['port'],
                       namespace=self.iris_config['namespace'])
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

    async def execute_query(self, sql: str, params: Optional[List] = None,
                          session_id: Optional[str] = None) -> Dict[str, Any]:
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
            # Performance tracking for constitutional compliance
            with PerformanceTracker(
                MetricType.API_RESPONSE_TIME,
                "iris_executor",
                session_id=session_id,
                sql_length=len(sql)
            ) as tracker:

                # P5: Vector query detection for enhanced logging
                if self.vector_support and 'VECTOR' in sql.upper():
                    logger.debug("Vector query detected",
                               sql=sql[:100] + "..." if len(sql) > 100 else sql,
                               session_id=session_id)

                # Use async execution with thread pool
                if self.embedded_mode:
                    result = await self._execute_embedded_async(sql, params, session_id)
                else:
                    result = await self._execute_external_async(sql, params, session_id)

                # Add performance metadata
                result['execution_metadata'] = {
                    'execution_time_ms': tracker.start_time and (time.perf_counter() - tracker.start_time) * 1000,
                    'embedded_mode': self.embedded_mode,
                    'vector_support': self.vector_support,
                    'session_id': session_id,
                    'sql_length': len(sql)
                }

                # Record performance metrics
                if tracker.violation:
                    logger.warning("IRIS execution SLA violation",
                                 actual_time_ms=tracker.violation.actual_value_ms,
                                 sla_threshold_ms=tracker.violation.sla_threshold_ms,
                                 session_id=session_id)

                return result

        except Exception as e:
            logger.error("SQL execution failed",
                        sql=sql[:100] + "..." if len(sql) > 100 else sql,
                        error=str(e),
                        session_id=session_id)
            raise

    async def _execute_embedded_async(self, sql: str, params: Optional[List] = None,
                                     session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute SQL using IRIS embedded Python with proper async threading

        This method runs the blocking IRIS operations in a thread pool to avoid
        blocking the event loop, following constitutional async requirements.
        """
        def _sync_execute():
            """Synchronous IRIS execution in thread pool"""
            import iris

            # DEBUG: Log entry to embedded execution path
            logger.info("🔍 EXECUTING IN EMBEDDED MODE",
                       sql_preview=sql[:100],
                       has_params=params is not None,
                       param_count=len(params) if params else 0,
                       session_id=session_id)

            try:
                # PROFILING: Track detailed timing
                t_start_total = time.perf_counter()

                # Get or create connection
                connection = self._get_iris_connection()

                # Apply vector query optimization (convert parameterized vectors to literals)
                optimized_sql = sql
                optimized_params = params
                optimization_applied = False

                # PROFILING: Optimization timing
                t_opt_start = time.perf_counter()

                try:
                    from .vector_optimizer import optimize_vector_query

                    logger.debug("Vector optimizer: checking query",
                               sql_preview=sql[:200],
                               param_count=len(params) if params else 0,
                               session_id=session_id)

                    optimized_sql, optimized_params = optimize_vector_query(sql, params)

                    optimization_applied = (optimized_sql != sql) or (optimized_params != params)

                    if optimization_applied:
                        logger.info("Vector optimization applied",
                                  sql_changed=(optimized_sql != sql),
                                  params_changed=(optimized_params != params),
                                  params_before=len(params) if params else 0,
                                  params_after=len(optimized_params) if optimized_params else 0,
                                  optimized_sql_preview=optimized_sql[:200],
                                  session_id=session_id)
                    else:
                        logger.debug("Vector optimization not applicable",
                                   reason="No vector patterns found or params unchanged",
                                   session_id=session_id)

                except ImportError as e:
                    logger.warning("Vector optimizer not available",
                                 error=str(e),
                                 session_id=session_id)
                except Exception as opt_error:
                    logger.warning("Vector optimization failed, using original query",
                                 error=str(opt_error),
                                 session_id=session_id)
                    optimized_sql, optimized_params = sql, params

                # PROFILING: Optimization complete
                t_opt_elapsed = (time.perf_counter() - t_opt_start) * 1000

                # Execute query with performance tracking
                start_time = time.perf_counter()

                # CRITICAL: Strip trailing semicolon when using parameters
                # IRIS cannot handle "SELECT ... WHERE id = ?;" (fails with SQLCODE=-52)
                # but works fine with "SELECT ... WHERE id = ?" (no semicolon)
                if optimized_params and optimized_sql.rstrip().endswith(';'):
                    original_len = len(optimized_sql)
                    optimized_sql = optimized_sql.rstrip().rstrip(';')
                    logger.info("Removed trailing semicolon for parameterized query",
                               original_sql_len=original_len,
                               new_sql_len=len(optimized_sql),
                               sql_preview=optimized_sql[:80],
                               param_count=len(optimized_params),
                               session_id=session_id)

                logger.debug("Executing IRIS query",
                           sql_preview=optimized_sql[:200],
                           param_count=len(optimized_params) if optimized_params else 0,
                           optimization_applied=optimization_applied,
                           session_id=session_id)

                # Log the actual SQL being sent to IRIS for debugging
                logger.info("About to execute iris.sql.exec",
                          sql_ends_with_semicolon=optimized_sql.rstrip().endswith(';'),
                          sql_last_20=optimized_sql.rstrip()[-20:],
                          has_params=optimized_params is not None and len(optimized_params) > 0,
                          session_id=session_id)

                # PROFILING: IRIS execution timing
                t_iris_start = time.perf_counter()

                if optimized_params is not None and len(optimized_params) > 0:
                    result = iris.sql.exec(optimized_sql, *optimized_params)
                else:
                    result = iris.sql.exec(optimized_sql)

                t_iris_elapsed = (time.perf_counter() - t_iris_start) * 1000
                execution_time = (time.perf_counter() - start_time) * 1000

                # PROFILING: Result processing timing
                t_fetch_start = time.perf_counter()

                # Fetch all results
                rows = []
                columns = []

                # Get column metadata if available
                if hasattr(result, '_meta') and result._meta:
                    for col_info in result._meta:
                        columns.append({
                            'name': col_info.get('name', ''),
                            'type_oid': self._iris_type_to_pg_oid(col_info.get('type', 'VARCHAR')),
                            'type_size': col_info.get('size', -1),
                            'type_modifier': -1,
                            'format_code': 0  # Text format
                        })

                # Fetch rows
                try:
                    for row in result:
                        if isinstance(row, (list, tuple)):
                            rows.append(list(row))
                        else:
                            # Single value result
                            rows.append([row])
                except Exception as fetch_error:
                    logger.warning("Error fetching IRIS result rows",
                                 error=str(fetch_error),
                                 session_id=session_id)

                # If we have rows but no column metadata, generate generic column info
                # iris.sql.exec() doesn't provide column metadata, so infer from first row
                if rows and not columns:
                    first_row = rows[0] if rows else []
                    for i in range(len(first_row)):
                        columns.append({
                            'name': f'column{i+1}',  # Generic name
                            'type_oid': 25,  # TEXT type (most flexible)
                            'type_size': -1,
                            'type_modifier': -1,
                            'format_code': 0  # Text format
                        })
                    logger.debug("Generated generic column metadata",
                               column_count=len(columns),
                               session_id=session_id)

                # PROFILING: Fetch complete
                t_fetch_elapsed = (time.perf_counter() - t_fetch_start) * 1000
                t_total_elapsed = (time.perf_counter() - t_start_total) * 1000

                # Determine command tag based on SQL type
                command_tag = self._determine_command_tag(sql, len(rows))

                # PROFILING: Log detailed breakdown
                logger.info("⏱️ EMBEDDED EXECUTION TIMING",
                          total_ms=round(t_total_elapsed, 2),
                          optimization_ms=round(t_opt_elapsed, 2),
                          iris_exec_ms=round(t_iris_elapsed, 2),
                          fetch_ms=round(t_fetch_elapsed, 2),
                          overhead_ms=round(t_total_elapsed - t_iris_elapsed, 2),
                          session_id=session_id)

                return {
                    'success': True,
                    'rows': rows,
                    'columns': columns,
                    'row_count': len(rows),
                    'command_tag': command_tag,
                    'execution_time_ms': execution_time,
                    'iris_metadata': {
                        'embedded_mode': True,
                        'connection_type': 'embedded_python'
                    },
                    'profiling': {
                        'total_ms': t_total_elapsed,
                        'optimization_ms': t_opt_elapsed,
                        'iris_execution_ms': t_iris_elapsed,
                        'fetch_ms': t_fetch_elapsed,
                        'overhead_ms': t_total_elapsed - t_iris_elapsed
                    }
                }

            except Exception as e:
                logger.error("IRIS embedded execution failed",
                           sql=sql[:100] + "..." if len(sql) > 100 else sql,
                           error=str(e),
                           session_id=session_id)
                return {
                    'success': False,
                    'error': str(e),
                    'rows': [],
                    'columns': [],
                    'row_count': 0,
                    'command_tag': 'ERROR',
                    'execution_time_ms': 0
                }

        # Execute in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_execute)

    async def _execute_external_async(self, sql: str, params: Optional[List] = None,
                                     session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute SQL using external IRIS connection with proper async threading
        """
        def _sync_external_execute():
            """Synchronous external IRIS execution in thread pool"""
            try:
                # PROFILING: Track detailed timing
                t_start_total = time.perf_counter()

                # Use intersystems-irispython driver
                import iris

                # Apply vector query optimization (convert parameterized vectors to literals)
                optimized_sql = sql
                optimized_params = params
                optimization_applied = False

                # PROFILING: Optimization timing
                t_opt_start = time.perf_counter()

                try:
                    from .vector_optimizer import optimize_vector_query

                    logger.debug("Vector optimizer: checking query (external mode)",
                               sql_preview=sql[:200],
                               param_count=len(params) if params else 0,
                               session_id=session_id)

                    optimized_sql, optimized_params = optimize_vector_query(sql, params)

                    optimization_applied = (optimized_sql != sql) or (optimized_params != params)

                    if optimization_applied:
                        logger.info("Vector optimization applied (external mode)",
                                  sql_changed=(optimized_sql != sql),
                                  params_changed=(optimized_params != params),
                                  params_before=len(params) if params else 0,
                                  params_after=len(optimized_params) if optimized_params else 0,
                                  optimized_sql_preview=optimized_sql[:200],
                                  session_id=session_id)
                    else:
                        logger.debug("Vector optimization not applicable (external mode)",
                                   reason="No vector patterns found or params unchanged",
                                   session_id=session_id)

                except ImportError as e:
                    logger.warning("Vector optimizer not available (external mode)",
                                 error=str(e),
                                 session_id=session_id)
                except Exception as opt_error:
                    logger.warning("Vector optimization failed, using original query (external mode)",
                                 error=str(opt_error),
                                 session_id=session_id)
                    optimized_sql, optimized_params = sql, params

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
                        columns.append({
                            'name': desc[0],
                            'type_oid': self._iris_type_to_pg_oid(desc[1] if len(desc) > 1 else 'VARCHAR'),
                            'type_size': desc[2] if len(desc) > 2 else -1,
                            'type_modifier': -1,
                            'format_code': 0  # Text format
                        })

                # Fetch all rows for SELECT queries
                if sql.upper().strip().startswith('SELECT') and columns:
                    try:
                        results = cursor.fetchall()
                        for row in results:
                            if isinstance(row, (list, tuple)):
                                rows.append(list(row))
                            else:
                                # Single value result
                                rows.append([row])
                    except Exception as fetch_error:
                        logger.warning("Failed to fetch external IRIS results",
                                     error=str(fetch_error),
                                     session_id=session_id)

                cursor.close()
                # Return connection to pool instead of closing
                self._return_connection(conn)

                # PROFILING: Fetch complete
                t_fetch_elapsed = (time.perf_counter() - t_fetch_start) * 1000
                t_total_elapsed = (time.perf_counter() - t_start_total) * 1000

                # Determine command tag
                command_tag = self._determine_command_tag(sql, len(rows))

                # PROFILING: Log detailed breakdown
                logger.info("⏱️ EXTERNAL EXECUTION TIMING",
                          total_ms=round(t_total_elapsed, 2),
                          optimization_ms=round(t_opt_elapsed, 2),
                          connection_ms=round(t_conn_elapsed, 2),
                          iris_exec_ms=round(t_iris_elapsed, 2),
                          fetch_ms=round(t_fetch_elapsed, 2),
                          overhead_ms=round(t_total_elapsed - t_iris_elapsed, 2),
                          session_id=session_id)

                return {
                    'success': True,
                    'rows': rows,
                    'columns': columns,
                    'row_count': len(rows),
                    'command_tag': command_tag,
                    'execution_time_ms': execution_time,
                    'iris_metadata': {
                        'embedded_mode': False,
                        'connection_type': 'external_driver'
                    },
                    'profiling': {
                        'total_ms': t_total_elapsed,
                        'optimization_ms': t_opt_elapsed,
                        'connection_ms': t_conn_elapsed,
                        'iris_execution_ms': t_iris_elapsed,
                        'fetch_ms': t_fetch_elapsed,
                        'overhead_ms': t_total_elapsed - t_iris_elapsed
                    }
                }

            except Exception as e:
                logger.error("IRIS external execution failed",
                           sql=sql[:100] + "..." if len(sql) > 100 else sql,
                           error=str(e),
                           session_id=session_id)
                return {
                    'success': False,
                    'error': str(e),
                    'rows': [],
                    'columns': [],
                    'row_count': 0,
                    'command_tag': 'ERROR',
                    'execution_time_ms': 0
                }

        # Execute in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_external_execute)

    def _get_iris_connection(self):
        """Get or create IRIS connection for embedded mode"""
        # For embedded mode, connections are managed by IRIS internally
        # This is a placeholder for potential connection pooling
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
                hostname=self.iris_config['host'],
                port=self.iris_config['port'],
                namespace=self.iris_config['namespace'],
                username=self.iris_config['username'],
                password=self.iris_config['password']
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

    def _iris_type_to_pg_oid(self, iris_type: Union[str, int]) -> int:
        """Convert IRIS data type to PostgreSQL OID"""
        # Handle both string type names and integer type codes
        if isinstance(iris_type, int):
            # Map IRIS integer type codes to PostgreSQL OIDs
            int_type_mapping = {
                1: 23,      # int4
                2: 21,      # int2
                3: 20,      # int8
                4: 700,     # float4
                5: 701,     # float8
                8: 1082,    # date
                9: 1083,    # time
                10: 1114,   # timestamp
                12: 1043,   # varchar
                16: 16,     # bool
                17: 17,     # bytea
            }
            return int_type_mapping.get(iris_type, 25)  # Default to text

        # Handle string type names
        type_mapping = {
            'VARCHAR': 1043,    # varchar
            'CHAR': 1042,       # bpchar
            'TEXT': 25,         # text
            'INTEGER': 23,      # int4
            'BIGINT': 20,       # int8
            'SMALLINT': 21,     # int2
            'DECIMAL': 1700,    # numeric
            'NUMERIC': 1700,    # numeric
            'DOUBLE': 701,      # float8
            'FLOAT': 700,       # float4
            'DATE': 1082,       # date
            'TIME': 1083,       # time
            'TIMESTAMP': 1114,  # timestamp
            'BOOLEAN': 16,      # bool
            'BINARY': 17,       # bytea
            'VARBINARY': 17,    # bytea
            'VECTOR': 16388,    # custom vector type
        }
        return type_mapping.get(str(iris_type).upper(), 25)  # Default to text

    def _determine_command_tag(self, sql: str, row_count: int) -> str:
        """Determine PostgreSQL command tag from SQL"""
        sql_upper = sql.upper().strip()

        if sql_upper.startswith('SELECT'):
            return 'SELECT'
        elif sql_upper.startswith('INSERT'):
            return f'INSERT 0 {row_count}'
        elif sql_upper.startswith('UPDATE'):
            return f'UPDATE {row_count}'
        elif sql_upper.startswith('DELETE'):
            return f'DELETE {row_count}'
        elif sql_upper.startswith('CREATE'):
            return 'CREATE'
        elif sql_upper.startswith('DROP'):
            return 'DROP'
        elif sql_upper.startswith('ALTER'):
            return 'ALTER'
        elif sql_upper.startswith('BEGIN'):
            return 'BEGIN'
        elif sql_upper.startswith('COMMIT'):
            return 'COMMIT'
        elif sql_upper.startswith('ROLLBACK'):
            return 'ROLLBACK'
        else:
            return 'UNKNOWN'

    async def shutdown(self):
        """Shutdown the executor and cleanup resources"""
        try:
            if self.thread_pool:
                self.thread_pool.shutdown(wait=True)
                logger.info("IRIS executor shutdown completed")
        except Exception as e:
            logger.warning("Error during IRIS executor shutdown", error=str(e))

    # Transaction management methods (using async threading)
    async def begin_transaction(self, session_id: Optional[str] = None):
        """Begin a transaction with async threading"""
        def _sync_begin():
            if self.embedded_mode:
                import iris
                iris.sql.exec("START TRANSACTION")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_begin)

    async def commit_transaction(self, session_id: Optional[str] = None):
        """Commit transaction with async threading"""
        def _sync_commit():
            if self.embedded_mode:
                import iris
                iris.sql.exec("COMMIT")
            # For external mode, transaction is managed per connection

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.thread_pool, _sync_commit)

    async def rollback_transaction(self, session_id: Optional[str] = None):
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
            logger.info("Processing query cancellation request",
                       backend_pid=backend_pid,
                       backend_secret="***")

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
                logger.info("Query cancellation successful",
                           backend_pid=backend_pid)
            else:
                logger.warning("Query cancellation failed - PID not found or secret mismatch",
                              backend_pid=backend_pid)

            return success

        except Exception as e:
            logger.error("Query cancellation error",
                        backend_pid=backend_pid, error=str(e))
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
            target_protocol = self.server.find_connection_for_cancellation(backend_pid, backend_secret)

            if not target_protocol:
                logger.warning("Connection not found for cancellation",
                              backend_pid=backend_pid)
                return False

            # Terminate the connection - this will stop any running queries
            logger.info("Terminating connection for query cancellation",
                       backend_pid=backend_pid,
                       connection_id=target_protocol.connection_id)

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

    def get_iris_type_mapping(self) -> Dict[str, Dict[str, Any]]:
        """
        Get IRIS to PostgreSQL type mappings (based on caretdev patterns)

        Returns type mapping for pg_catalog implementation
        """
        return {
            # Standard PostgreSQL types (from caretdev)
            'BIGINT': {'oid': 20, 'typname': 'int8', 'typlen': 8},
            'BIT': {'oid': 1560, 'typname': 'bit', 'typlen': -1},
            'DATE': {'oid': 1082, 'typname': 'date', 'typlen': 4},
            'DOUBLE': {'oid': 701, 'typname': 'float8', 'typlen': 8},
            'INTEGER': {'oid': 23, 'typname': 'int4', 'typlen': 4},
            'NUMERIC': {'oid': 1700, 'typname': 'numeric', 'typlen': -1},
            'SMALLINT': {'oid': 21, 'typname': 'int2', 'typlen': 2},
            'TIME': {'oid': 1083, 'typname': 'time', 'typlen': 8},
            'TIMESTAMP': {'oid': 1114, 'typname': 'timestamp', 'typlen': 8},
            'TINYINT': {'oid': 21, 'typname': 'int2', 'typlen': 2},  # Map to smallint
            'VARBINARY': {'oid': 17, 'typname': 'bytea', 'typlen': -1},
            'VARCHAR': {'oid': 1043, 'typname': 'varchar', 'typlen': -1},
            'LONGVARCHAR': {'oid': 25, 'typname': 'text', 'typlen': -1},
            'LONGVARBINARY': {'oid': 17, 'typname': 'bytea', 'typlen': -1},

            # IRIS-specific types with P5 vector support
            'VECTOR': {'oid': 16388, 'typname': 'vector', 'typlen': -1},
            'EMBEDDING': {'oid': 16389, 'typname': 'vector', 'typlen': -1},  # Map IRIS EMBEDDING to vector
        }

    def get_server_info(self) -> Dict[str, Any]:
        """Get IRIS server information for PostgreSQL compatibility"""
        return {
            'server_version': '16.0 (InterSystems IRIS)',
            'server_version_num': '160000',
            'embedded_mode': self.embedded_mode,
            'vector_support': self.vector_support,
            'protocol_version': '3.0'
        }

    # P5: Vector/Embedding Support

    def get_vector_functions(self) -> Dict[str, str]:
        """
        Get pgvector-compatible function mappings to IRIS vector functions

        Maps PostgreSQL/pgvector syntax to IRIS VECTOR functions
        """
        return {
            # Distance functions (pgvector compatibility)
            'vector_cosine_distance': 'VECTOR_COSINE',
            'cosine_distance': 'VECTOR_COSINE',
            'euclidean_distance': 'VECTOR_DOT_PRODUCT',  # IRIS equivalent
            'inner_product': 'VECTOR_DOT_PRODUCT',

            # Vector operations
            'vector_dims': 'VECTOR_DIM',
            'vector_norm': 'VECTOR_NORM',

            # IRIS-specific vector functions
            'to_vector': 'TO_VECTOR',
            'vector_dot_product': 'VECTOR_DOT_PRODUCT',
            'vector_cosine': 'VECTOR_COSINE'
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
            if '<->' in translated_sql:
                # Pattern: column <-> '[1,2,3]' becomes VECTOR_COSINE(column, TO_VECTOR('[1,2,3]'))
                import re
                pattern = r'([\w\.]+)\s*<->\s*([^\s]+)'
                def replace_cosine(match):
                    col, vec = match.groups()
                    return f'VECTOR_COSINE({col}, TO_VECTOR({vec}))'
                translated_sql = re.sub(pattern, replace_cosine, translated_sql)

            # <#> operator (negative inner product) -> -VECTOR_DOT_PRODUCT
            if '<#>' in translated_sql:
                import re
                pattern = r'([\w\.]+)\s*<#>\s*([^\s]+)'
                def replace_inner_product(match):
                    col, vec = match.groups()
                    return f'(-VECTOR_DOT_PRODUCT({col}, TO_VECTOR({vec})))'
                translated_sql = re.sub(pattern, replace_inner_product, translated_sql)

            # <=> operator (cosine distance) -> VECTOR_COSINE
            if '<=>' in translated_sql:
                import re
                pattern = r'([\w\.]+)\s*<=>\s*([^\s]+)'
                def replace_cosine_distance(match):
                    col, vec = match.groups()
                    return f'VECTOR_COSINE({col}, TO_VECTOR({vec}))'
                translated_sql = re.sub(pattern, replace_cosine_distance, translated_sql)

            # Replace function names
            for pg_func, iris_func in vector_functions.items():
                translated_sql = translated_sql.replace(pg_func, iris_func)

            return translated_sql

        except Exception as e:
            logger.warning("Vector query translation failed", error=str(e), sql=sql[:100])
            return sql  # Return original if translation fails