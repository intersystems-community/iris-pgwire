# Data Model: IRIS SQL Constructs Translation

**Date**: 2025-01-19 | **Feature**: 004-iris-sql-constructs

## Core Entities

### SQL Translation Request
```python
@dataclass
class TranslationRequest:
    original_sql: str
    parameters: Optional[Dict[str, Any]] = None
    session_context: Optional[Dict[str, str]] = None
    debug_mode: bool = False
```

**Fields**:
- `original_sql`: Raw SQL containing IRIS-specific constructs
- `parameters`: Parameter bindings for prepared statements
- `session_context`: Connection-specific settings (timezone, encoding)
- `debug_mode`: Enable detailed trace logging

**Validation Rules**:
- original_sql must be non-empty string
- parameters must be JSON-serializable if provided
- session_context values must be strings

### SQL Translation Result
```python
@dataclass
class TranslationResult:
    translated_sql: str
    construct_mappings: List[ConstructMapping]
    performance_stats: PerformanceStats
    warnings: List[str] = field(default_factory=list)
    debug_trace: Optional[DebugTrace] = None
```

**Fields**:
- `translated_sql`: PostgreSQL-compatible SQL
- `construct_mappings`: Applied transformations
- `performance_stats`: Translation timing and cache metrics
- `warnings`: Non-fatal issues during translation
- `debug_trace`: Detailed parsing and decision log

**Validation Rules**:
- translated_sql must be valid PostgreSQL syntax
- construct_mappings must contain all applied transformations
- performance_stats.translation_time_ms must be ≤ 50ms

### Construct Mapping
```python
@dataclass
class ConstructMapping:
    construct_type: ConstructType
    original_syntax: str
    translated_syntax: str
    confidence: float
    source_location: TextLocation
```

**Fields**:
- `construct_type`: Category of IRIS construct (FUNCTION, SYNTAX, DATATYPE, HINT)
- `original_syntax`: IRIS-specific SQL fragment
- `translated_syntax`: PostgreSQL equivalent
- `confidence`: Translation accuracy score (0.0-1.0)
- `source_location`: Position in original SQL

**State Transitions**:
- DETECTED → MAPPED → VALIDATED → APPLIED

### Function Mapping Registry
```python
@dataclass
class FunctionMapping:
    iris_function: str
    postgres_function: str
    parameter_mapping: Optional[Callable] = None
    requires_context: bool = False
    confidence: float = 1.0
```

**Fields**:
- `iris_function`: IRIS function name pattern (e.g., "%SYSTEM.Version.GetNumber")
- `postgres_function`: PostgreSQL equivalent (e.g., "version()")
- `parameter_mapping`: Optional parameter transformation function
- `requires_context`: Whether mapping needs session context
- `confidence`: Mapping reliability score

**Relationships**:
- One-to-many: IRIS function → PostgreSQL implementations
- Many-to-one: IRIS functions → PostgreSQL function (consolidation)

### Data Type Converter
```python
@dataclass
class TypeMapping:
    iris_type: str
    postgres_type: str
    postgres_oid: int
    conversion_function: Optional[Callable] = None
    precision_loss: bool = False
```

**Fields**:
- `iris_type`: IRIS data type name (e.g., "ROWVERSION", "%List")
- `postgres_type`: PostgreSQL type name (e.g., "bytea", "jsonb")
- `postgres_oid`: PostgreSQL type OID for wire protocol
- `conversion_function`: Value transformation logic
- `precision_loss`: Whether conversion loses data fidelity

### Translation Cache Entry
```python
@dataclass
class CacheEntry:
    query_signature: str
    translated_sql: str
    construct_mappings: List[ConstructMapping]
    cache_timestamp: datetime
    hit_count: int = 0
    last_access: datetime = field(default_factory=datetime.utcnow)
```

**Fields**:
- `query_signature`: Hash of normalized original SQL
- `translated_sql`: Cached translation result
- `construct_mappings`: Cached transformation metadata
- `cache_timestamp`: Entry creation time
- `hit_count`: Access frequency counter
- `last_access`: LRU eviction tracking

**Lifecycle**:
- Creation: Hash(original_sql) → signature
- Access: hit_count++, last_access = now
- Eviction: LRU + TTL based on cache_timestamp

### Performance Statistics
```python
@dataclass
class PerformanceStats:
    translation_time_ms: float
    parsing_time_ms: float
    mapping_time_ms: float
    validation_time_ms: float
    cache_hit: bool
    constructs_detected: int
    constructs_translated: int
```

**Validation Rules**:
- translation_time_ms ≤ 50ms (SLA requirement)
- constructs_translated ≤ constructs_detected
- All timing values ≥ 0

### Debug Trace
```python
@dataclass
class DebugTrace:
    parsing_steps: List[ParsingStep]
    mapping_decisions: List[MappingDecision]
    validation_results: List[ValidationResult]
    performance_breakdown: Dict[str, float]
```

**Fields**:
- `parsing_steps`: SQL tokenization and AST building
- `mapping_decisions`: Construct identification and translation choices
- `validation_results`: Semantic equivalence checks
- `performance_breakdown`: Detailed timing by operation

---

## Entity Relationships

```
TranslationRequest
    ↓ (processes)
ConstructMapping ←→ FunctionMapping
    ↓ (validates)      ↓ (uses)
TranslationResult ←→ TypeMapping
    ↓ (caches)
CacheEntry
```

## Validation Rules Summary

1. **Performance Constraints**: Translation time ≤ 50ms
2. **Semantic Preservation**: Translated SQL must produce equivalent results
3. **Protocol Compliance**: PostgreSQL syntax and type compatibility
4. **Cache Coherency**: TTL-based invalidation with schema change detection
5. **Debug Data**: Complete traceability when debug_mode enabled