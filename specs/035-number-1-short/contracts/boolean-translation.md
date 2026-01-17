# Contract: Boolean Default Translation

**Feature**: 035-number-1-short  
**Version**: 1.0  
**Date**: 2026-01-17

## Overview

This contract defines how PostgreSQL boolean default literals (`true`/`false`) are translated to IRIS-compatible defaults (`1`/`0`).

---

## Translation Rules

### DEFAULT true

**Pattern**: `DEFAULT true` (case-insensitive, word boundary)

**Behavior**: Replace with `DEFAULT 1`

**Examples**:
```sql
-- Input
"is_active" boolean DEFAULT true NOT NULL

-- Output
"is_active" boolean DEFAULT 1 NOT NULL
```

### DEFAULT false

**Pattern**: `DEFAULT false` (case-insensitive, word boundary)

**Behavior**: Replace with `DEFAULT 0`

**Examples**:
```sql
-- Input
"is_debug_mode_enabled" boolean DEFAULT false NOT NULL

-- Output
"is_debug_mode_enabled" boolean DEFAULT 0 NOT NULL
```

---

## Context Safety

### String Literal Protection

Boolean keywords inside string literals MUST NOT be modified.

**Examples**:
```sql
-- Input (NOT modified)
INSERT INTO t (message) VALUES ('This is true')

-- Output (unchanged)
INSERT INTO t (message) VALUES ('This is true')
```

### Comment Protection

Boolean keywords inside comments MUST NOT be modified.

**Examples**:
```sql
-- Input (NOT modified)
-- Set default to true for new users
CREATE TABLE t (active BIT DEFAULT 1)

-- Output (comment unchanged)
-- Set default to true for new users
CREATE TABLE t (active BIT DEFAULT 1)
```

```sql
-- Input (NOT modified)
/* When true, enables feature */
CREATE TABLE t (enabled BIT)

-- Output (comment unchanged)
/* When true, enables feature */
CREATE TABLE t (enabled BIT)
```

---

## Detection Pattern

### Regex Pattern

```
DEFAULT\s+(true|false)\b
```

With flags: `re.IGNORECASE`

### Word Boundary Requirement

The `\b` word boundary prevents false matches:
- `truetype` → NOT matched (no word boundary after "true")
- `falsehood` → NOT matched (no word boundary after "false")

---

## Context Detection Algorithm

Before applying regex replacement:

1. **Identify string literals**: Find all `'...'` spans
2. **Identify line comments**: Find all `--...` to end of line
3. **Identify block comments**: Find all `/*...*/` spans
4. **Mark safe regions**: Regions outside all protected spans
5. **Apply replacement**: Only in safe regions

---

## Statement Contexts

### CREATE TABLE

```sql
-- Input
CREATE TABLE users (
    id INT,
    is_active boolean DEFAULT true NOT NULL,
    is_admin boolean DEFAULT false NOT NULL
)

-- Output
CREATE TABLE users (
    id INT,
    is_active boolean DEFAULT 1 NOT NULL,
    is_admin boolean DEFAULT 0 NOT NULL
)
```

### ALTER TABLE ADD COLUMN

```sql
-- Input
ALTER TABLE users ADD COLUMN verified boolean DEFAULT false NOT NULL

-- Output
ALTER TABLE users ADD COLUMN verified boolean DEFAULT 0 NOT NULL
```

### ALTER TABLE ALTER COLUMN SET DEFAULT

```sql
-- Input
ALTER TABLE users ALTER COLUMN active SET DEFAULT true

-- Output
ALTER TABLE users ALTER COLUMN active SET DEFAULT 1
```

---

## Test Scenarios

| ID | Input | Expected Output | Verification |
|----|-------|-----------------|--------------|
| B-001 | `DEFAULT true` | `DEFAULT 1` | Literal translated |
| B-002 | `DEFAULT false` | `DEFAULT 0` | Literal translated |
| B-003 | `DEFAULT TRUE` | `DEFAULT 1` | Case-insensitive |
| B-004 | `DEFAULT False` | `DEFAULT 0` | Mixed case |
| B-005 | `'true'` in string | `'true'` unchanged | String protected |
| B-006 | `-- true` in comment | `-- true` unchanged | Comment protected |
| B-007 | `/* false */` | `/* false */` unchanged | Block comment protected |
| B-008 | Multiple in one statement | Both translated | All occurrences handled |
| B-009 | `truetype` | `truetype` unchanged | Word boundary respected |

---

## Performance

- Regex is compiled at module load time
- Context detection uses single-pass scanning
- Total overhead target: <1ms per statement

---

## Error Conditions

| Condition | Handling |
|-----------|----------|
| Nested quotes | Handled by quote matching algorithm |
| Escaped quotes (`''`) | Treated as part of string literal |
| Unclosed comment | May incorrectly protect remaining SQL |
