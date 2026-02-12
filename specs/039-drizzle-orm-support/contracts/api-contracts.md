# API Contracts: Drizzle ORM DDL Translation

## Overview

This document defines the internal API contracts for the Drizzle ORM DDL translation feature. Since iris-pgwire is a library (not a REST service), these contracts define the Python API surfaces, extension points, and integration patterns.

---

## Public API Contracts

### 1. DDLTranslator Class

**Purpose**: Main entry point for translating PostgreSQL DDL to IRIS SQL.

**Module**: `src/iris_pgwire/sql_translator/ddl_translator.py`

```python
from typing import List, Optional
from iris_pgwire.sql_translator.ddl_translator import DDLTranslator, DDLStatement, DDLTranslationError

class DDLTranslator:
    """Translates PostgreSQL DDL statements to IRIS-compatible SQL."""
    
    def __init__(
        self,
        type_mapping: Optional[Dict[str, str]] = None,
        reserved_words: Optional[Set[str]] = None,
        strict_mode: bool = True
    ):
        """
        Initialize DDL translator.
        
        Args:
            type_mapping: Custom PostgreSQL → IRIS type mappings (extends defaults)
            reserved_words: Custom IRIS reserved words set (extends defaults)
            strict_mode: If True, error on unsupported features; if False, skip with warnings
        """
        pass
    
    def translate_statement(self, sql: str) -> DDLStatement:
        """
        Translate a single DDL statement.
        
        Args:
            sql: PostgreSQL DDL SQL string
            
        Returns:
            DDLStatement object with translated_sql and metadata
            
        Raises:
            DDLTranslationError: If statement cannot be translated
            ValueError: If SQL is not valid DDL
        """
        pass
    
    def translate_migration_file(self, file_path: str) -> List[DDLStatement]:
        """
        Parse and translate all DDL statements in a migration file.
        
        Args:
            file_path: Path to .sql migration file
            
        Returns:
            List of translated DDLStatement objects
            
        Raises:
            DDLTranslationError: If any statement fails translation
            FileNotFoundError: If file doesn't exist
        """
        pass
    
    def validate_type_precision(self, pg_type: str, precision: int, scale: Optional[int] = None) -> bool:
        """
        Check if PostgreSQL type precision is supported in IRIS.
        
        Args:
            pg_type: PostgreSQL type name (e.g., "numeric")
            precision: Numeric precision
            scale: Numeric scale (optional)
            
        Returns:
            True if supported, False otherwise
            
        Raises:
            DDLTranslationError: If precision exceeds IRIS limits
        """
        pass
    
    def get_reserved_words(self) -> Set[str]:
        """
        Get set of IRIS reserved words that require quoting.
        
        Returns:
            Set of uppercase reserved words
        """
        pass
```

**Error Handling Contract**:
```python
class DDLTranslationError(Exception):
    """Raised when DDL translation fails."""
    
    def __init__(
        self,
        statement: str,
        error_code: str,
        message: str,
        suggested_fix: Optional[str] = None
    ):
        self.statement = statement
        self.error_code = error_code
        self.message = message
        self.suggested_fix = suggested_fix
        super().__init__(message)
```

**Usage Example**:
```python
translator = DDLTranslator(strict_mode=True)

try:
    statement = translator.translate_statement(
        'CREATE TABLE "users" ("id" uuid PRIMARY KEY, "level" integer);'
    )
    print(statement.translated_sql)
    # Output: CREATE TABLE "users" ("id" UUID PRIMARY KEY, "level" INTEGER);
    
except DDLTranslationError as e:
    print(f"Error ({e.error_code}): {e.message}")
    if e.suggested_fix:
        print(f"Suggestion: {e.suggested_fix}")
```

---

### 2. MigrationExecutor Class

**Purpose**: Executes translated DDL migrations with transaction management and journal tracking.

**Module**: `src/iris_pgwire/migrations/executor.py`

```python
from typing import Optional, Callable
from iris_pgwire.migrations.executor import MigrationExecutor, MigrationResult

class MigrationExecutor:
    """Executes Drizzle migrations against IRIS with atomic transactions."""
    
    def __init__(
        self,
        connection: Any,  # DBAPI connection or IRIS embedded connection
        translator: Optional[DDLTranslator] = None,
        lock_timeout_seconds: int = 30,
        on_progress: Optional[Callable[[str, int, int], None]] = None
    ):
        """
        Initialize migration executor.
        
        Args:
            connection: Database connection (DBAPI or IRIS embedded)
            translator: DDL translator instance (uses default if None)
            lock_timeout_seconds: Max time to wait for migration lock
            on_progress: Callback for progress updates (message, current, total)
        """
        pass
    
    def execute_migration(self, file_path: str) -> MigrationResult:
        """
        Execute a single migration file with transaction safety.
        
        Process:
        1. Acquire exclusive lock on __drizzle_migrations
        2. Check if migration already applied (journal lookup)
        3. Start transaction
        4. Translate and execute all DDL statements
        5. On success: COMMIT, update journal, release lock
        6. On failure: ROLLBACK, DO NOT update journal, release lock
        
        Args:
            file_path: Path to migration .sql file
            
        Returns:
            MigrationResult with status, execution time, warnings/errors
            
        Raises:
            MigrationLockError: If lock cannot be acquired
            MigrationAlreadyAppliedError: If migration hash exists in journal
            DDLTranslationError: If translation fails
        """
        pass
    
    def execute_migrations(self, directory: str) -> List[MigrationResult]:
        """
        Execute all pending migrations in directory (ordered by filename).
        
        Args:
            directory: Path to migrations directory
            
        Returns:
            List of MigrationResult objects (one per file)
        """
        pass
    
    def get_applied_migrations(self) -> List[str]:
        """
        Get list of migration hashes from journal.
        
        Returns:
            List of migration hashes that have been applied
        """
        pass
    
    def create_journal_table(self) -> None:
        """
        Create __drizzle_migrations journal table if not exists.
        
        SQL:
            CREATE TABLE "__drizzle_migrations" (
                "id" INTEGER PRIMARY KEY AUTO INCREMENT,
                "hash" VARCHAR(255) NOT NULL UNIQUE,
                "created_at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        pass
```

**Result Contract**:
```python
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class MigrationStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # Already applied
    
@dataclass
class MigrationResult:
    filename: str
    status: MigrationStatus
    execution_time_ms: int
    statements_executed: int
    warnings: List[str]
    errors: List[str]
    applied_at: Optional[datetime]
```

**Usage Example**:
```python
import psycopg

# Connect via pgwire
conn = psycopg.connect("postgresql://user:pass@localhost:55433/USER")

executor = MigrationExecutor(
    connection=conn,
    on_progress=lambda msg, current, total: print(f"[{current}/{total}] {msg}")
)

# Ensure journal table exists
executor.create_journal_table()

# Execute all pending migrations
results = executor.execute_migrations("./drizzle/migrations")

for result in results:
    if result.status == MigrationStatus.SUCCESS:
        print(f"✓ {result.filename} ({result.execution_time_ms}ms)")
    elif result.status == MigrationStatus.SKIPPED:
        print(f"⊘ {result.filename} (already applied)")
    else:
        print(f"✗ {result.filename}")
        for error in result.errors:
            print(f"  Error: {error}")
```

---

### 3. Type Mapping Registry Extensions

**Purpose**: Extend existing type mapping for PostgreSQL → IRIS translation.

**Module**: `src/iris_pgwire/type_mapping.py`

```python
# Existing type_mapping registry from iris-pgwire
from iris_pgwire.type_mapping import TypeMappingRegistry

# New DDL-specific mappings to add
DDL_TYPE_MAPPINGS = {
    # PostgreSQL Type → IRIS Type (DDL context)
    "text": "VARCHAR(*)",  # Unlimited length
    "boolean": "BIT",
    "uuid": "UUID",
    "jsonb": "JSON",
    "json": "JSON",
    "timestamp with time zone": "TIMESTAMP",
    "timestamp without time zone": "TIMESTAMP",
    "serial": "INTEGER",  # + AUTO_INCREMENT constraint
    "bigserial": "BIGINT",  # + AUTO_INCREMENT constraint
    "smallserial": "SMALLINT",  # + AUTO_INCREMENT constraint
    "double precision": "DOUBLE",
    "real": "REAL",
    "bytea": "VARBINARY(*)",
    "interval": "INTERVAL",
    
    # Type families (require precision/scale)
    "numeric": "NUMERIC",  # Max precision: 38
    "decimal": "NUMERIC",  # Max precision: 38
    "character varying": "VARCHAR",  # Alias for VARCHAR
    "character": "CHAR",
    "varchar": "VARCHAR",
    "char": "CHAR",
}

# Precision limits
TYPE_PRECISION_LIMITS = {
    "NUMERIC": {"max_precision": 38, "max_scale": 19},
    "DECIMAL": {"max_precision": 38, "max_scale": 19},
    "VARCHAR": {"max_length": 32767},  # IRIS VARCHAR limit
    "CHAR": {"max_length": 32767},
}
```

**Extension API**:
```python
def register_custom_type_mapping(pg_type: str, iris_type: str, precision_limit: Optional[int] = None) -> None:
    """
    Register a custom PostgreSQL → IRIS type mapping.
    
    Args:
        pg_type: PostgreSQL type name
        iris_type: IRIS type name
        precision_limit: Optional max precision for numeric types
    """
    pass
```

---

### 4. Reserved Word Checker

**Purpose**: Validate identifiers against IRIS reserved words.

**Module**: `src/iris_pgwire/sql_translator/reserved_words.py`

```python
class ReservedWordChecker:
    """Check identifiers against IRIS reserved words."""
    
    def __init__(self, reserved_words: Optional[Set[str]] = None):
        """
        Initialize with IRIS reserved words.
        
        Args:
            reserved_words: Custom set (uses default IRIS keywords if None)
        """
        self.reserved_words = reserved_words or self._load_iris_reserved_words()
    
    def is_reserved(self, identifier: str) -> bool:
        """
        Check if identifier is an IRIS reserved word.
        
        Args:
            identifier: Unquoted identifier (table/column/index name)
            
        Returns:
            True if reserved word, False otherwise
        """
        return identifier.upper() in self.reserved_words
    
    def quote_if_needed(self, identifier: str) -> str:
        """
        Quote identifier if it's a reserved word.
        
        Args:
            identifier: Raw identifier
            
        Returns:
            Quoted identifier if reserved, unchanged otherwise
            
        Examples:
            "level" → '"level"' (reserved)
            "user_id" → "user_id" (not reserved)
        """
        if self.is_reserved(identifier):
            return f'"{identifier}"'
        return identifier
    
    @staticmethod
    def _load_iris_reserved_words() -> Set[str]:
        """Load IRIS reserved words from internal registry."""
        # https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_reservedwords
        return {
            "LEVEL", "KEY", "TRIGGER", "OPTION", "POSITION", "INTERVAL", "ZONE",
            "SECOND", "MINUTE", "HOUR", "DAY", "MONTH", "YEAR",
            # ... (full list loaded from resource file)
        }
```

---

### 5. Integration with Existing SQLTranslator

**Purpose**: Hook DDL translation into existing iris-pgwire translation pipeline.

**Module**: `src/iris_pgwire/sql_translator/translator.py` (existing)

```python
class SQLTranslator:
    """Existing SQL translator - extends to handle DDL."""
    
    def __init__(self, ..., enable_ddl_translation: bool = False):
        """
        Args:
            enable_ddl_translation: Enable DDL statement translation (opt-in)
        """
        self.ddl_translator = DDLTranslator() if enable_ddl_translation else None
    
    def normalize_sql(self, sql: str, ...) -> str:
        """
        Existing method - extended to detect and route DDL.
        
        Process:
        1. Detect statement type (SELECT/INSERT/UPDATE/DELETE/DDL)
        2. If DDL and enable_ddl_translation: route to DDLTranslator
        3. Otherwise: existing DML/DQL translation pipeline
        """
        if self.ddl_translator and self._is_ddl_statement(sql):
            statement = self.ddl_translator.translate_statement(sql)
            return statement.translated_sql
        
        # Existing DML/DQL translation
        return self._normalize_dml(sql)
    
    @staticmethod
    def _is_ddl_statement(sql: str) -> bool:
        """Detect if SQL is DDL (CREATE/ALTER/DROP)."""
        first_word = sql.strip().split()[0].upper()
        return first_word in ("CREATE", "ALTER", "DROP", "TRUNCATE")
```

**Backward Compatibility**: DDL translation is opt-in via `enable_ddl_translation` flag to avoid breaking existing users.

---

## Internal Component Contracts

### 6. DDL Parser

**Purpose**: Parse PostgreSQL DDL into structured AST.

**Module**: `src/iris_pgwire/sql_translator/ddl_parser.py`

```python
from typing import Union
from dataclasses import dataclass

@dataclass
class CreateTableStatement:
    table_name: str
    schema_name: Optional[str]
    columns: List[ColumnDefinition]
    constraints: List[ConstraintDefinition]
    if_not_exists: bool
    
@dataclass
class AlterTableStatement:
    table_name: str
    schema_name: Optional[str]
    action: str  # ADD_COLUMN, DROP_COLUMN, ADD_CONSTRAINT, etc.
    column: Optional[ColumnDefinition]
    constraint: Optional[ConstraintDefinition]
    
@dataclass
class CreateIndexStatement:
    index_name: str
    table_name: str
    columns: List[IndexColumn]
    is_unique: bool
    where_clause: Optional[str]
    include_columns: Optional[List[str]]
    index_type: Optional[str]
    is_concurrent: bool

class DDLParser:
    """Parse PostgreSQL DDL statements into structured format."""
    
    def parse(self, sql: str) -> Union[CreateTableStatement, AlterTableStatement, CreateIndexStatement, ...]:
        """
        Parse DDL SQL into structured statement object.
        
        Args:
            sql: PostgreSQL DDL SQL
            
        Returns:
            Statement object (CreateTableStatement, etc.)
            
        Raises:
            ValueError: If SQL is not valid DDL or cannot be parsed
        """
        pass
```

**Implementation Note**: Use `sqlparse` library for initial tokenization, then custom logic for DDL-specific parsing.

---

### 7. Type Translator

**Purpose**: Translate PostgreSQL types to IRIS equivalents with validation.

**Module**: `src/iris_pgwire/sql_translator/type_translator.py`

```python
from dataclasses import dataclass

@dataclass
class TypeTranslation:
    iris_type: str
    precision: Optional[int]
    scale: Optional[int]
    warnings: List[str]

class TypeTranslator:
    """Translate PostgreSQL types to IRIS types."""
    
    def __init__(self, type_mapping: Dict[str, str], precision_limits: Dict[str, Dict]):
        self.type_mapping = type_mapping
        self.precision_limits = precision_limits
    
    def translate_type(
        self,
        pg_type: str,
        precision: Optional[int] = None,
        scale: Optional[int] = None
    ) -> TypeTranslation:
        """
        Translate PostgreSQL type to IRIS type.
        
        Args:
            pg_type: PostgreSQL type name
            precision: Type precision (for numeric/varchar)
            scale: Type scale (for numeric/decimal)
            
        Returns:
            TypeTranslation with IRIS type and metadata
            
        Raises:
            DDLTranslationError: If type unsupported or precision exceeds limits
        """
        iris_type = self.type_mapping.get(pg_type.lower())
        if not iris_type:
            raise DDLTranslationError(
                statement=pg_type,
                error_code="UNSUPPORTED_TYPE",
                message=f"PostgreSQL type '{pg_type}' has no IRIS equivalent",
                suggested_fix="Use alternative type or contact iris-pgwire maintainers"
            )
        
        # Validate precision if applicable
        if precision and iris_type in self.precision_limits:
            max_precision = self.precision_limits[iris_type]["max_precision"]
            if precision > max_precision:
                raise DDLTranslationError(
                    statement=f"{pg_type}({precision})",
                    error_code="TYPE_PRECISION_EXCEEDED",
                    message=f"{iris_type} precision {precision} exceeds IRIS limit of {max_precision}",
                    suggested_fix=f"Use {iris_type}({max_precision}) or alternative type"
                )
        
        return TypeTranslation(
            iris_type=iris_type,
            precision=precision,
            scale=scale,
            warnings=[]
        )
```

---

### 8. Constraint Translator

**Purpose**: Translate PostgreSQL constraints to IRIS equivalents.

**Module**: `src/iris_pgwire/sql_translator/constraint_translator.py`

```python
class ConstraintTranslator:
    """Translate PostgreSQL constraints to IRIS syntax."""
    
    def translate_primary_key(self, columns: List[str]) -> str:
        """Generate IRIS PRIMARY KEY constraint."""
        return f"PRIMARY KEY ({', '.join(columns)})"
    
    def translate_foreign_key(
        self,
        columns: List[str],
        referenced_table: str,
        referenced_columns: List[str],
        on_delete: Optional[str] = None,
        on_update: Optional[str] = None
    ) -> str:
        """
        Generate IRIS FOREIGN KEY constraint.
        
        Supports CASCADE and RESTRICT actions per spec clarification.
        """
        fk = f"FOREIGN KEY ({', '.join(columns)}) REFERENCES {referenced_table} ({', '.join(referenced_columns)})"
        
        if on_delete:
            fk += f" ON DELETE {on_delete}"
        if on_update:
            fk += f" ON UPDATE {on_update}"
        
        return fk
    
    def translate_unique(self, columns: List[str]) -> str:
        """Generate IRIS UNIQUE constraint."""
        return f"UNIQUE ({', '.join(columns)})"
    
    def translate_check(self, expression: str) -> str:
        """Generate IRIS CHECK constraint."""
        # Note: Expression may need SQL dialect translation
        return f"CHECK ({expression})"
```

---

## Configuration Contracts

### 9. DDL Translation Configuration

**Module**: `src/iris_pgwire/config.py`

```python
from dataclasses import dataclass

@dataclass
class DDLTranslationConfig:
    """Configuration for DDL translation behavior."""
    
    # Translation behavior
    strict_mode: bool = True  # Error on unsupported features vs skip with warnings
    auto_quote_reserved_words: bool = True  # Automatically quote IRIS reserved words
    validate_precision: bool = True  # Validate type precision against IRIS limits
    
    # Migration execution
    lock_timeout_seconds: int = 30  # Max time to wait for migration lock
    enable_advisory_locks: bool = True  # Use LOCK TABLE for concurrency control
    transaction_isolation: str = "READ COMMITTED"  # Transaction isolation level
    
    # Error handling
    fail_fast: bool = True  # Stop on first error vs continue with warnings
    log_warnings: bool = True  # Log precision loss warnings
    
    # Type mapping
    custom_type_mappings: Dict[str, str] = None  # Custom PG → IRIS type overrides
    custom_reserved_words: Set[str] = None  # Additional reserved words
    
    def __post_init__(self):
        self.custom_type_mappings = self.custom_type_mappings or {}
        self.custom_reserved_words = self.custom_reserved_words or set()
```

---

## CLI Integration Contract

### 10. Command-Line Interface

**Purpose**: Provide CLI tool for running migrations outside of application code.

**Module**: `src/iris_pgwire/cli.py` (new)

```bash
# Execute migrations
python -m iris_pgwire.migrations \
  --host localhost \
  --port 55433 \
  --user USER \
  --password SYS \
  --migrations-dir ./drizzle/migrations

# Dry-run (translate without executing)
python -m iris_pgwire.migrations \
  --dry-run \
  --migrations-dir ./drizzle/migrations \
  --output translated-migrations/

# Check migration status
python -m iris_pgwire.migrations \
  --status \
  --host localhost \
  --port 55433
```

**Output Format** (JSON for scripting):
```json
{
  "status": "success",
  "migrations_applied": 3,
  "migrations_pending": 0,
  "execution_time_ms": 1234,
  "results": [
    {
      "filename": "0001_init.sql",
      "status": "success",
      "execution_time_ms": 456,
      "statements": 5,
      "warnings": []
    }
  ]
}
```

---

## Testing Contracts

### 11. Test Fixtures

**Module**: `tests/fixtures/drizzle_migrations.py`

```python
import pytest

@pytest.fixture
def sample_drizzle_migration() -> str:
    """Sample Drizzle migration SQL."""
    return '''
    CREATE TABLE "users" (
      "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      "email" text NOT NULL UNIQUE,
      "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX "user_email_idx" ON "users" ("email");
    '''

@pytest.fixture
def ddl_translator() -> DDLTranslator:
    """DDL translator instance for testing."""
    return DDLTranslator(strict_mode=True)

@pytest.fixture
def migration_executor(iris_connection) -> MigrationExecutor:
    """Migration executor with test connection."""
    return MigrationExecutor(connection=iris_connection)
```

### 12. Integration Test Contract

**Module**: `tests/integration/test_drizzle_migration.py`

```python
def test_basic_table_creation(migration_executor, tmp_path):
    """Test CREATE TABLE translation and execution."""
    migration_file = tmp_path / "0001_init.sql"
    migration_file.write_text('''
        CREATE TABLE "products" (
            "id" serial PRIMARY KEY,
            "name" text NOT NULL,
            "price" numeric(10, 2)
        );
    ''')
    
    result = migration_executor.execute_migration(str(migration_file))
    
    assert result.status == MigrationStatus.SUCCESS
    assert result.statements_executed == 1
    assert len(result.errors) == 0

def test_type_precision_error(ddl_translator):
    """Test error on numeric precision exceeding IRIS limits."""
    sql = 'CREATE TABLE "test" ("value" numeric(1000, 500));'
    
    with pytest.raises(DDLTranslationError) as exc_info:
        ddl_translator.translate_statement(sql)
    
    assert exc_info.value.error_code == "TYPE_PRECISION_EXCEEDED"
    assert "38" in exc_info.value.message  # IRIS limit mentioned

def test_reserved_word_auto_quoting(ddl_translator):
    """Test automatic quoting of IRIS reserved words."""
    sql = 'CREATE TABLE "workflow" ("level" integer, "key" text);'
    
    statement = ddl_translator.translate_statement(sql)
    
    assert '"level"' in statement.translated_sql  # Quoted
    assert '"key"' in statement.translated_sql    # Quoted

def test_unsupported_index_feature(ddl_translator):
    """Test error on partial index with WHERE clause."""
    sql = 'CREATE INDEX "active_users" ON "users" ("email") WHERE "active" = true;'
    
    with pytest.raises(DDLTranslationError) as exc_info:
        ddl_translator.translate_statement(sql)
    
    assert exc_info.value.error_code == "UNSUPPORTED_INDEX_FEATURE"
    assert "WHERE clause" in exc_info.value.message

def test_concurrent_migration_locking(migration_executor):
    """Test that concurrent migrations wait for lock."""
    # Simulate two executors attempting migration simultaneously
    # First should succeed, second should wait or error
    pass

def test_transaction_rollback_on_failure(migration_executor, tmp_path):
    """Test that partial migration failures rollback entire transaction."""
    migration_file = tmp_path / "0002_fail.sql"
    migration_file.write_text('''
        CREATE TABLE "test1" ("id" integer);
        CREATE TABLE "test2" ("invalid_column" unsupported_type);
    ''')
    
    result = migration_executor.execute_migration(str(migration_file))
    
    assert result.status == MigrationStatus.FAILED
    # Verify test1 table was NOT created (rollback worked)
    # Verify journal NOT updated
```

---

## Backward Compatibility Guarantees

1. **Opt-In DDL Translation**: Existing iris-pgwire users are unaffected unless they explicitly enable `enable_ddl_translation=True`
2. **Non-Breaking Type Mapping**: DDL type mappings extend (not replace) existing DML/DQL type registry
3. **Isolated Migration State**: `__drizzle_migrations` journal table does not conflict with existing schema
4. **Error Isolation**: DDL translation errors do not affect DML/DQL query execution

---

## Performance Contracts

1. **Translation Performance**: DDL translation adds <10ms overhead per statement
2. **Lock Contention**: Migration lock timeout configurable (default 30s)
3. **Transaction Scope**: All DDL in single migration file executed in one transaction (all-or-nothing)
4. **Memory Footprint**: Parser holds max 1 migration file in memory at a time

---

## Security Contracts

1. **SQL Injection Prevention**: All identifiers validated and quoted before execution
2. **Permission Checks**: Migrations execute with connection's user permissions (no privilege escalation)
3. **Audit Trail**: All migrations logged in `__drizzle_migrations` with timestamp
4. **No Credential Storage**: CLI accepts connection params but does not persist credentials

---

## Versioning & Deprecation Policy

1. **Semantic Versioning**: DDL translation feature follows iris-pgwire's semver
2. **Deprecation Warnings**: 2-version deprecation cycle for breaking changes
3. **Feature Flags**: New experimental features gated behind opt-in flags
4. **Migration Path**: Clear migration guides for breaking changes

---

## References

- [IRIS SQL DDL Reference](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_COMMANDS)
- [Drizzle Migrations Documentation](https://orm.drizzle.team/docs/migrations)
- [iris-pgwire Type Mapping](https://github.com/caretdev/iris-pgwire/blob/main/src/iris_pgwire/type_mapping.py)
- [PostgreSQL DDL Commands](https://www.postgresql.org/docs/current/ddl.html)
