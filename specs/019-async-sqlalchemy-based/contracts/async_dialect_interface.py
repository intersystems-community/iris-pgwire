"""
Contract definition for IRISDialectAsync_psycopg.

This file defines the interface contract that the async dialect implementation MUST satisfy.
Used for contract testing (T003-T007) to ensure implementation compliance.

Design Principle: Test-Driven Development (Constitutional Principle II)
- Write contract tests BEFORE implementation
- Tests MUST fail initially (no implementation exists)
- Implement to make tests pass
- Validates compliance with this contract

Location: /Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/contracts/async_dialect_interface.py
Related: /Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py (implementation target)
"""

from typing import Protocol, Callable, Tuple, List, Dict, Type, Any
from types import ModuleType


class AsyncDialectInterface(Protocol):
    """
    Contract for IRISDialectAsync_psycopg async dialect class.

    This protocol defines the REQUIRED interface that the async dialect implementation
    must provide to enable async SQLAlchemy operations with IRIS via PGWire.

    Inheritance Requirements:
    - MUST inherit from IRISDialect (IRIS-specific features)
    - MUST inherit from PGDialectAsync_psycopg (PostgreSQL async transport)
    - MRO: IRISDialect methods take precedence over PGDialectAsync_psycopg

    Constitutional Compliance:
    - FR-003: Must properly resolve to async dialect variant
    - FR-004: Must maintain all IRIS-specific features (VECTOR types, INFORMATION_SCHEMA)
    - FR-005: Must use proper async connection pool class
    """

    # Class attributes (REQUIRED)
    driver: str  # MUST be "psycopg"
    is_async: bool  # MUST be True
    supports_statement_cache: bool  # MUST be True (prepared statements)
    supports_native_boolean: bool  # MUST be True (PostgreSQL wire protocol)

    @classmethod
    def import_dbapi(cls) -> ModuleType:
        """
        Import and return psycopg module for async connections.

        Contract Requirements:
        - MUST return psycopg module (not a custom wrapper)
        - Module MUST support AsyncConnection class
        - Module MUST be the same psycopg used by sync dialect (dual-mode)

        Returns:
            psycopg module with AsyncConnection support

        Example:
            >>> dbapi = IRISDialectAsync_psycopg.import_dbapi()
            >>> assert hasattr(dbapi, 'AsyncConnection')
            >>> assert dbapi.__name__ == 'psycopg'

        Related:
            - FR-008: Must work with psycopg async connection objects
            - T003: Contract test validates this method
        """
        ...

    @classmethod
    def get_pool_class(cls, url: Any) -> Type:
        """
        Return async connection pool class for async engine.

        Contract Requirements:
        - MUST return AsyncAdaptedQueuePool from sqlalchemy.pool
        - Pool class MUST support async connection management
        - MUST handle greenlet-based async/sync bridging

        Args:
            url: SQLAlchemy URL object (may be None in some contexts)

        Returns:
            AsyncAdaptedQueuePool class

        Example:
            >>> from sqlalchemy.pool import AsyncAdaptedQueuePool
            >>> pool_cls = IRISDialectAsync_psycopg.get_pool_class(None)
            >>> assert pool_cls == AsyncAdaptedQueuePool

        Related:
            - FR-005: Must use proper async connection pool class
            - T004: Contract test validates pool class
        """
        ...

    def create_connect_args(self, url: Any) -> Tuple[List, Dict]:
        """
        Convert SQLAlchemy URL to psycopg async connection arguments.

        Contract Requirements:
        - MUST parse iris+psycopg:// connection URL
        - MUST default to port 5432 (PGWire) not 1972 (IRIS SuperServer)
        - MUST convert 'database' key to 'dbname' (psycopg naming)
        - MUST preserve username, password, host, port from URL
        - MUST pass through query parameters (timeout, SSL options, etc.)

        Args:
            url: SQLAlchemy URL object (e.g., iris+psycopg://localhost:5432/USER)

        Returns:
            Tuple of (args_list, kwargs_dict) for psycopg.AsyncConnection.connect()

        Example:
            >>> from sqlalchemy.engine import make_url
            >>> url = make_url("iris+psycopg://localhost:5432/USER")
            >>> args, kwargs = dialect.create_connect_args(url)
            >>> assert args == []
            >>> assert kwargs['dbname'] == 'USER'
            >>> assert kwargs['host'] == 'localhost'
            >>> assert kwargs['port'] == 5432

        Related:
            - FR-001: Must support iris+psycopg:// connection string format
            - T005: Contract test validates URL parsing
        """
        ...

    def on_connect(self) -> Callable:
        """
        Return connection initialization callback.

        Contract Requirements:
        - MUST return callable that accepts connection object
        - Callable MUST initialize IRIS-specific connection state
        - MUST skip IRIS-specific cursor checks (cursor.sqlcode, %CHECKPRIV)
        - MUST set self._dictionary_access (default: False)
        - MUST set self.vector_cosine_similarity (default: None)
        - MUST NOT make blocking calls (use asyncio.to_thread if needed)

        Returns:
            Callable[[Any], None] - Connection initialization function

        Example:
            >>> callback = dialect.on_connect()
            >>> assert callable(callback)
            >>> # callback(connection) called by SQLAlchemy after connection

        Related:
            - FR-004: Must maintain IRIS-specific features
            - T006: Contract test validates initialization
        """
        ...

    def do_executemany(
        self, cursor: Any, query: str, params: List[Dict], context: Any = None
    ) -> None:
        """
        Execute parameterized query multiple times asynchronously.

        Contract Requirements:
        - MUST execute query for each parameter set in params list
        - MUST use cursor.execute() in loop (NOT psycopg executemany)
        - MUST strip trailing semicolons from query (IRIS compatibility)
        - MUST handle async cursor operations properly
        - MUST preserve parameter order and types

        Args:
            cursor: psycopg AsyncCursor instance
            query: SQL query string with parameter placeholders (%s)
            params: List of parameter dicts/tuples for each execution
            context: Optional SQLAlchemy execution context

        Example:
            >>> query = "INSERT INTO test VALUES (%s, %s)"
            >>> params = [(1, 'a'), (2, 'b'), (3, 'c')]
            >>> dialect.do_executemany(cursor, query, params)
            >>> # Executes: INSERT INTO test VALUES (1, 'a')
            >>> #           INSERT INTO test VALUES (2, 'b')
            >>> #           INSERT INTO test VALUES (3, 'c')

        Related:
            - FR-007: Must execute bulk inserts efficiently in async mode
            - T006: Contract test validates bulk execution
        """
        ...

    def _get_server_version_info(self, connection: Any) -> Tuple[int, int, int]:
        """
        Return IRIS server version as tuple.

        Contract Requirements:
        - MUST return 3-tuple of (major, minor, patch) integers
        - MUST NOT access connection._connection_info (IRIS-specific, not in psycopg)
        - MAY return default version (2025, 1, 0) if detection not possible
        - MUST NOT raise exceptions (return default on error)

        Args:
            connection: SQLAlchemy connection wrapper

        Returns:
            Tuple[int, int, int] - Version as (major, minor, patch)

        Example:
            >>> version = dialect._get_server_version_info(connection)
            >>> assert len(version) == 3
            >>> assert all(isinstance(v, int) for v in version)
            >>> # Example: (2025, 1, 0) for IRIS 2025.1.0

        Related:
            - FR-004: Must maintain IRIS-specific features
        """
        ...

    def get_isolation_level(self, dbapi_conn: Any) -> int:
        """
        Get current transaction isolation level.

        Contract Requirements:
        - MUST return integer isolation level code
        - MUST NOT execute IRIS-specific SQL (? placeholders not supported)
        - MAY return default level (1 = READ COMMITTED) if detection not possible
        - MUST handle psycopg async connections (not IRIS connections)

        Args:
            dbapi_conn: psycopg AsyncConnection instance

        Returns:
            int - Isolation level code (0=READ UNCOMMITTED, 1=READ COMMITTED, etc.)

        Example:
            >>> level = dialect.get_isolation_level(connection)
            >>> assert isinstance(level, int)
            >>> assert level in [0, 1, 2, 3]  # Valid isolation levels

        Related:
            - FR-006: Must support async transaction management
        """
        ...

    def set_isolation_level(self, dbapi_conn: Any, level: int) -> None:
        """
        Set transaction isolation level.

        Contract Requirements:
        - MUST accept psycopg AsyncConnection instance
        - MAY implement as no-op (isolation levels handled by PGWire/IRIS defaults)
        - MUST NOT raise exceptions on unsupported levels
        - MUST handle async context properly if implemented

        Args:
            dbapi_conn: psycopg AsyncConnection instance
            level: Isolation level code to set

        Example:
            >>> dialect.set_isolation_level(connection, 1)
            >>> # May be no-op, relying on IRIS defaults

        Related:
            - FR-006: Must support async transaction management
        """
        ...

    def do_begin_twophase(self, connection: Any, xid: Any) -> None:
        """
        Disable two-phase commit BEGIN (not supported via PGWire).

        Contract Requirements:
        - MUST implement as no-op (pass statement)
        - MUST NOT raise exceptions
        - Two-phase commit not supported in IRIS via PGWire protocol

        Args:
            connection: Database connection
            xid: Transaction identifier

        Related:
            - FR-006: Transaction management (two-phase explicitly unsupported)
        """
        ...

    def do_prepare_twophase(self, connection: Any, xid: Any) -> None:
        """
        Disable two-phase commit PREPARE (not supported via PGWire).

        Contract Requirements:
        - MUST implement as no-op (pass statement)
        - MUST NOT raise exceptions
        - Two-phase commit not supported in IRIS via PGWire protocol

        Args:
            connection: Database connection
            xid: Transaction identifier

        Related:
            - FR-006: Transaction management (two-phase explicitly unsupported)
        """
        ...

    def do_rollback_twophase(
        self, connection: Any, xid: Any, is_prepared: bool = True, recover: bool = False
    ) -> None:
        """
        Disable two-phase commit ROLLBACK (not supported via PGWire).

        Contract Requirements:
        - MUST implement as no-op (pass statement)
        - MUST NOT raise exceptions
        - Two-phase commit not supported in IRIS via PGWire protocol

        Args:
            connection: Database connection
            xid: Transaction identifier
            is_prepared: Whether transaction is in prepared state
            recover: Whether to recover prepared transactions

        Related:
            - FR-006: Transaction management (two-phase explicitly unsupported)
        """
        ...

    def do_commit_twophase(
        self, connection: Any, xid: Any, is_prepared: bool = True, recover: bool = False
    ) -> None:
        """
        Disable two-phase commit COMMIT (not supported via PGWire).

        Contract Requirements:
        - MUST implement as no-op (pass statement)
        - MUST NOT raise exceptions
        - Two-phase commit not supported in IRIS via PGWire protocol

        Args:
            connection: Database connection
            xid: Transaction identifier
            is_prepared: Whether transaction is in prepared state
            recover: Whether to recover prepared transactions

        Related:
            - FR-006: Transaction management (two-phase explicitly unsupported)
        """
        ...


class SyncDialectResolverInterface(Protocol):
    """
    Contract for async dialect resolution in sync dialect class.

    This protocol defines the REQUIRED method that the sync dialect (IRISDialect_psycopg)
    must implement to enable SQLAlchemy async dialect resolution.

    Critical: This is the KEY method that enables create_async_engine() to work.
    Without this method, SQLAlchemy defaults to sync dialect and raises AwaitRequired errors.
    """

    @classmethod
    def get_async_dialect_cls(cls, url: Any) -> Type[AsyncDialectInterface]:
        """
        Return async dialect class for create_async_engine().

        Contract Requirements:
        - MUST be implemented as class method in IRISDialect_psycopg (sync dialect)
        - MUST return IRISDialectAsync_psycopg class (not instance)
        - Returned class MUST implement AsyncDialectInterface protocol
        - SQLAlchemy calls this when create_async_engine() is used
        - MUST return same class for all URL variants (stateless)

        Args:
            url: SQLAlchemy URL object (may be None)

        Returns:
            IRISDialectAsync_psycopg class

        Example:
            >>> from sqlalchemy_iris.psycopg import IRISDialect_psycopg
            >>> async_cls = IRISDialect_psycopg.get_async_dialect_cls(None)
            >>> assert async_cls.__name__ == 'IRISDialectAsync_psycopg'
            >>> assert async_cls.is_async == True
            >>> assert issubclass(async_cls, IRISDialect)

        Related:
            - FR-003: Must properly resolve to async dialect variant
            - T010: Implementation task for this method
            - Root Cause: This method is the solution to AwaitRequired errors

        Critical Implementation Note:
            This is the SINGLE MOST IMPORTANT method for async support.
            Without this, SQLAlchemy cannot resolve to async dialect.
        """
        ...


# Contract Validation Tests (T003-T007)
# These tests MUST be written BEFORE implementation and MUST fail initially.
# See: /Users/tdyar/ws/iris-pgwire/tests/contract/test_async_dialect_contract.py

"""
Contract Test Examples (TDD - Write BEFORE Implementation):

def test_async_dialect_import_dbapi():
    '''T003: Validate DBAPI import returns psycopg module with AsyncConnection.'''
    from sqlalchemy_iris.psycopg import IRISDialectAsync_psycopg
    dbapi = IRISDialectAsync_psycopg.import_dbapi()
    assert dbapi.__name__ == 'psycopg'
    assert hasattr(dbapi, 'AsyncConnection')

def test_async_dialect_pool_class():
    '''T004: Validate pool class returns AsyncAdaptedQueuePool.'''
    from sqlalchemy.pool import AsyncAdaptedQueuePool
    from sqlalchemy_iris.psycopg import IRISDialectAsync_psycopg
    pool_cls = IRISDialectAsync_psycopg.get_pool_class(None)
    assert pool_cls == AsyncAdaptedQueuePool

def test_async_dialect_url_parsing():
    '''T005: Validate connection URL parsing for PGWire defaults.'''
    from sqlalchemy.engine import make_url
    from sqlalchemy_iris.psycopg import IRISDialectAsync_psycopg
    url = make_url("iris+psycopg://localhost:5432/USER")
    dialect = IRISDialectAsync_psycopg()
    args, kwargs = dialect.create_connect_args(url)
    assert kwargs['dbname'] == 'USER'
    assert kwargs['port'] == 5432

def test_sync_dialect_async_resolver():
    '''T003: Validate sync dialect returns async variant class.'''
    from sqlalchemy_iris.psycopg import IRISDialect_psycopg
    async_cls = IRISDialect_psycopg.get_async_dialect_cls(None)
    assert async_cls.__name__ == 'IRISDialectAsync_psycopg'
    assert async_cls.is_async == True

def test_async_engine_creation():
    '''T004: Validate async engine creation resolves to async dialect.'''
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine("iris+psycopg://localhost:5432/USER")
    assert engine.dialect.is_async == True
    assert engine.dialect.__class__.__name__ == 'IRISDialectAsync_psycopg'
"""
