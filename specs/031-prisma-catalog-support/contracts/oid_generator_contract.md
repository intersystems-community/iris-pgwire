# Contract: OID Generator

**Feature**: 031-prisma-catalog-support
**Component**: `catalog/oid_generator.py`
**Created**: 2025-12-23

---

## Purpose

Generate stable, deterministic Object Identifiers (OIDs) for IRIS database objects to satisfy PostgreSQL catalog requirements.

---

## Input Contracts

### IC-1: Generate OID for database object

**Function Signature**:
```python
def get_oid(namespace: str, object_type: str, object_name: str) -> int
```

**Parameters**:
| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| namespace | str | Schema/database name | 'SQLUser' |
| object_type | str | Object category | 'table', 'column', 'constraint' |
| object_name | str | Unique object name | 'users', 'users.id' |

**Valid object_type values**:
- `'namespace'` - Schema/namespace
- `'table'` - Table or view
- `'column'` - Table column (format: `table.column`)
- `'constraint'` - Constraint
- `'index'` - Index
- `'type'` - Data type
- `'default'` - Column default (format: `table.column`)

### IC-2: Get namespace OID

**Function Signature**:
```python
def get_namespace_oid(namespace: str) -> int
```

**Special Cases**:
| Namespace | Expected OID | Notes |
|-----------|-------------|-------|
| `'pg_catalog'` | 11 | PostgreSQL system catalog |
| `'public'` | 2200 | Default user schema |
| `'information_schema'` | 11323 | SQL standard schema |
| Other | Generated | Hash-based |

### IC-3: Get table OID by name

**Function Signature**:
```python
def get_table_oid(schema: str, table_name: str) -> int
```

**Equivalent to**: `get_oid(schema, 'table', table_name)`

---

## Output Contracts

### OC-1: OID range

**Constraints**:
- PostgreSQL system OIDs: 1-16383 (reserved)
- User OIDs: 16384-4294967295 (generated)
- Generated OIDs MUST be ≥ 16384

### OC-2: Determinism

**Invariant**: Same inputs MUST produce same OID:
```python
oid1 = get_oid('SQLUser', 'table', 'users')
oid2 = get_oid('SQLUser', 'table', 'users')
assert oid1 == oid2  # Always true
```

### OC-3: Uniqueness

**Invariant**: Different inputs SHOULD produce different OIDs:
```python
oid1 = get_oid('SQLUser', 'table', 'users')
oid2 = get_oid('SQLUser', 'table', 'orders')
assert oid1 != oid2  # Expected (cryptographic hash collision improbable)
```

### OC-4: Persistence

**Invariant**: OIDs persist across:
- Multiple queries in same session
- Different database connections
- Server restarts
- IRIS container restarts

---

## Test Contracts

### TC-1: Basic OID generation

```python
def test_oid_generation_basic():
    """
    Given: Object identity (schema, type, name)
    When: Generate OID
    Then: Return valid 32-bit unsigned integer >= 16384
    """
    gen = OIDGenerator()
    oid = gen.get_oid('SQLUser', 'table', 'users')

    assert isinstance(oid, int)
    assert 16384 <= oid <= 4294967295
```

### TC-2: OID determinism

```python
def test_oid_determinism():
    """
    Given: Same object identity
    When: Generate OID multiple times
    Then: Return same value each time
    """
    gen1 = OIDGenerator()
    gen2 = OIDGenerator()  # Fresh instance

    oid1 = gen1.get_oid('SQLUser', 'table', 'users')
    oid2 = gen2.get_oid('SQLUser', 'table', 'users')

    assert oid1 == oid2
```

### TC-3: OID uniqueness

```python
def test_oid_uniqueness():
    """
    Given: Different object identities
    When: Generate OIDs
    Then: Return unique values
    """
    gen = OIDGenerator()

    oids = [
        gen.get_oid('SQLUser', 'table', 'users'),
        gen.get_oid('SQLUser', 'table', 'orders'),
        gen.get_oid('SQLUser', 'column', 'users.id'),
        gen.get_oid('SQLUser', 'column', 'users.name'),
        gen.get_oid('SQLUser', 'constraint', 'users_pkey'),
    ]

    assert len(oids) == len(set(oids))  # All unique
```

### TC-4: Well-known namespace OIDs

```python
def test_well_known_namespace_oids():
    """
    Given: Well-known namespace names
    When: Get namespace OID
    Then: Return standard PostgreSQL OIDs
    """
    gen = OIDGenerator()

    assert gen.get_namespace_oid('pg_catalog') == 11
    assert gen.get_namespace_oid('public') == 2200
    assert gen.get_namespace_oid('information_schema') == 11323
```

### TC-5: Cache behavior

```python
def test_oid_cache():
    """
    Given: OID generator with cache
    When: Request same OID multiple times
    Then: Return cached value (no rehash)
    """
    gen = OIDGenerator()

    # First call generates and caches
    oid1 = gen.get_oid('SQLUser', 'table', 'users')

    # Second call returns cached
    oid2 = gen.get_oid('SQLUser', 'table', 'users')

    assert oid1 == oid2
    assert ('SQLUser', 'table', 'users') in gen._cache
```

### TC-6: Case sensitivity

```python
def test_oid_case_handling():
    """
    Given: Object names with different cases
    When: Generate OIDs
    Then: Treat as same or different based on PostgreSQL behavior
    """
    gen = OIDGenerator()

    # PostgreSQL is case-insensitive for unquoted identifiers
    # OID generation should normalize to lowercase
    oid_lower = gen.get_oid('SQLUser', 'table', 'users')
    oid_upper = gen.get_oid('SQLUser', 'table', 'USERS')

    # Should be same (normalized)
    assert oid_lower == oid_upper
```

### TC-7: Column OID format

```python
def test_column_oid_format():
    """
    Given: Column identity with table.column format
    When: Generate OID
    Then: Return unique OID for each column
    """
    gen = OIDGenerator()

    oid_id = gen.get_oid('SQLUser', 'column', 'users.id')
    oid_name = gen.get_oid('SQLUser', 'column', 'users.name')
    oid_other = gen.get_oid('SQLUser', 'column', 'orders.id')

    assert oid_id != oid_name  # Different columns same table
    assert oid_id != oid_other  # Same column name different table
```

---

## Implementation Algorithm

```python
import hashlib

class OIDGenerator:
    """Deterministic OID generation using SHA-256 hashing."""

    WELL_KNOWN_NAMESPACES = {
        'pg_catalog': 11,
        'public': 2200,
        'information_schema': 11323,
    }

    USER_OID_START = 16384

    def __init__(self):
        self._cache: dict[tuple[str, str, str], int] = {}

    def get_oid(self, namespace: str, object_type: str, object_name: str) -> int:
        """Generate deterministic OID for object."""
        # Normalize inputs
        key = (namespace.lower(), object_type.lower(), object_name.lower())

        if key not in self._cache:
            identity = f"{key[0]}:{key[1]}:{key[2]}"
            hash_bytes = hashlib.sha256(identity.encode()).digest()
            raw_oid = int.from_bytes(hash_bytes[:4], byteorder='big')

            # Ensure in user OID range
            if raw_oid < self.USER_OID_START:
                raw_oid += self.USER_OID_START

            self._cache[key] = raw_oid

        return self._cache[key]

    def get_namespace_oid(self, namespace: str) -> int:
        """Get OID for namespace, using well-known values where applicable."""
        ns_lower = namespace.lower()
        if ns_lower in self.WELL_KNOWN_NAMESPACES:
            return self.WELL_KNOWN_NAMESPACES[ns_lower]
        return self.get_oid('', 'namespace', namespace)
```

---

## Performance Contract

- Generation time: <0.1ms per OID
- Cache lookup: O(1)
- Memory: O(n) where n = unique objects accessed
- Thread safety: Not required (single-threaded per connection)
