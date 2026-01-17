# Research: PostgreSQL DDL Compatibility (ENUM, RLS, Boolean Defaults)

**Feature**: 035-number-1-short  
**Date**: 2026-01-17

## Research Summary

This document captures research findings for implementing PostgreSQL DDL compatibility for ENUM types, Row Level Security statements, and boolean default literals in iris-pgwire.

---

## 1. ENUM Type Handling

### Decision
Skip `CREATE TYPE ... AS ENUM` statements with no-op success. Translate column type references from registered enum types to `VARCHAR(64)`. Strip enum type casts from expressions.

### Rationale
- IRIS does not have native ENUM type support
- VARCHAR(64) provides sufficient storage for typical enum values (most under 32 chars)
- No value constraint enforcement (per clarification) simplifies implementation
- Existing sim_sql_patch.py has proven this approach works for Drizzle migrations

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| Map to IRIS lookup table | Too complex; requires DDL generation and FK constraints |
| Use CHECK constraints | IRIS CHECK constraint syntax differs; would still need VARCHAR base |
| Reject enum usage entirely | Would break 13+ migration statements unnecessarily |

### Implementation Approach
1. **Statement Detection**: Regex pattern `CREATE\s+TYPE\s+["']?[\w.]+["']?\s+AS\s+ENUM`
2. **Registry**: Session-scoped set of registered enum type names (lowercase, unqualified)
3. **Column Translation**: Replace `"enum_type"` with `VARCHAR(64)` in column definitions
4. **Cast Handling**: Strip `::["']?[\w.]+["']?` casts when target is registered enum
5. **DROP TYPE**: Skip for registered enum types

### Evidence
From sim_sql_patch.py (lines 55-63):
```python
enum_match = re.match(r"^CREATE\s+TYPE\s+\"?([\w.]+)\"?\s+AS\s+ENUM\s*\((.*)\)\s*;?$", sql_clean, ...)
if enum_match:
    type_name = enum_match.group(1).split(".")[-1]
    self.enum_types.add(type_name.lower())
    return ""  # Skip
```

---

## 2. Row Level Security Statement Handling

### Decision
Skip all RLS-related statements with no-op success response:
- `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`
- `ALTER TABLE ... DISABLE ROW LEVEL SECURITY`
- `CREATE POLICY ... ON ...`
- `DROP POLICY ... ON ...`

### Rationale
- IRIS uses different security model (Resource-based, Role-based access control)
- RLS is PostgreSQL-specific feature with no IRIS equivalent
- Migrations still complete successfully when RLS is skipped
- Per clarification: fail-safe skip (no-op result)

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| Translate to IRIS security | No semantic equivalent; would require complex mapping |
| Return error to client | Would break migrations unnecessarily |
| Log warning only | Still need to return success to client |

### Implementation Approach
1. **Statement Detection**: Four regex patterns:
   - `ALTER\s+TABLE\s+.*\bENABLE\s+ROW\s+LEVEL\s+SECURITY`
   - `ALTER\s+TABLE\s+.*\bDISABLE\s+ROW\s+LEVEL\s+SECURITY`
   - `CREATE\s+POLICY\s+`
   - `DROP\s+POLICY\s+`
2. **Response**: Return success with command tag matching statement type

### Evidence
From sim_sql_patch.py (lines 33-34, 47-49):
```python
if re.match(r"ALTER\s+TABLE\b.*\b(ENABLE|DISABLE)\s+ROW\s+LEVEL\s+SECURITY\b", sql_upper):
    return True  # should_skip
```

---

## 3. Boolean Default Translation

### Decision
Translate `DEFAULT true` to `DEFAULT 1` and `DEFAULT false` to `DEFAULT 0` in DDL statements. Must not affect string literals or comments.

### Rationale
- IRIS uses BIT type for boolean columns, expects 0/1 for defaults
- PostgreSQL uses `true`/`false` keywords in DDL
- 48 migration statements use this pattern
- String/comment safety prevents false positives

### Alternatives Considered
| Alternative | Rejected Because |
|-------------|------------------|
| Translate at parameter binding | Does not help DDL defaults which are literals |
| Use IRIS BOOLEAN type | IRIS maps BOOLEAN to BIT anyway; same issue |
| Keep as true/false | IRIS SQL parser rejects these keywords |

### Implementation Approach
1. **Pattern**: `\bDEFAULT\s+(true|false)\b` with word boundaries
2. **Context Safety**: 
   - Skip if inside single quotes (string literal)
   - Skip if inside `--` comment to end of line
   - Skip if inside `/* */` block comment
3. **Replacement**: `DEFAULT 1` or `DEFAULT 0`

### Evidence
From sim_sql_patch.py (lines 89-90):
```python
s = re.sub(r"DEFAULT\s+true\b", "DEFAULT 1", s, flags=re.IGNORECASE)
s = re.sub(r"DEFAULT\s+false\b", "DEFAULT 0", s, flags=re.IGNORECASE)
```

---

## 4. Translation Pipeline Order

### Decision
Add new translations to the normalizer pipeline in this order:
1. Existing: Parameter translation ($n → ?)
2. Existing: Schema mapping (public → SQLUser)
3. **NEW**: Statement filter (skip CREATE TYPE, RLS, etc.)
4. **NEW**: Enum type translation (column types, casts)
5. **NEW**: Boolean default translation
6. Existing: Identifier normalization
7. Existing: DATE translation
8. Existing: JSON operator translation
9. Existing: VECTOR type translation
10. Existing: DEFAULT in VALUES rewrite

### Rationale
- Statement filtering must happen early to avoid processing skipped statements
- Enum translation must happen before identifier normalization (preserves type names)
- Boolean translation can happen at any point (word boundary patterns are robust)

---

## 5. Session-Scoped Enum Registry

### Decision
Maintain enum type registry at session/connection level, not globally.

### Rationale
- Different connections may run different migrations
- Enum types are defined per-database in PostgreSQL
- Session scope matches PostgreSQL semantics
- Prevents cross-connection contamination

### Implementation Approach
- Add `_enum_types: set[str]` to SQLTranslator or PGWireProtocol instance
- Register types when CREATE TYPE is skipped
- Clear on connection close

---

## 6. Performance Considerations

### Decision
All new translations use compiled regex patterns and simple string operations.

### Rationale
- Constitution requires <5ms translation overhead
- Regex compilation is O(1) at module load
- Pattern matching is O(n) where n = SQL length
- Typical DDL statements are <1KB

### Validation
- Add timing assertions to contract tests
- Include in E2E performance validation

---

## Research Status

All research tasks complete. No NEEDS CLARIFICATION items remain.

| Topic | Status | Decision |
|-------|--------|----------|
| ENUM handling | Complete | Skip + VARCHAR(64) translation |
| RLS handling | Complete | Skip with no-op success |
| Boolean defaults | Complete | Translate true→1, false→0 |
| Pipeline order | Complete | Filter → Enum → Boolean → existing |
| Registry scope | Complete | Session-scoped |
| Performance | Complete | Compiled regex, <5ms |
