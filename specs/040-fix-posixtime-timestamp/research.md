# Research: Fix POSIXTIME/TIMESTAMP Handling

**Branch**: `040-fix-posixtime-timestamp` | **Date**: 2026-02-18

## Summary

No external research required. All decisions were resolved via spec clarification sessions and confirmed against the existing codebase. This document records the findings for traceability.

---

## Decision 1 — POSIXTIME Encoding Formula

**Question**: What is the correct formula to decode an IRIS `%PosixTime` value to a Unix timestamp?

**Decision**: `unix_microseconds = posixtime_value - POSIXTIME_OFFSET` where `POSIXTIME_OFFSET = 1152921504606846976` (2^60).

**Rationale**: The constant and the correct `int` branch already exist and are correct in `_serialize_value()` (lines 532–534 of `iris_executor.py`). The bug is only in the missing `str` branch, which must use the same formula.

**Verification**:
```python
POSIXTIME_OFFSET = 1152921504606846976
value = 1154692939441846976
unix_us = value - POSIXTIME_OFFSET  # → 1771434835000000
from datetime import datetime, timedelta
ts = datetime(1970, 1, 1) + timedelta(microseconds=unix_us)
# → datetime(2026, 2, 18, 17, 13, 55)  ✓
```

**Rejected alternative**: `int(value) // 10**9` — this treats the raw integer as Unix nanoseconds, which is wrong; it produces 2006 instead of 2026.

---

## Decision 2 — IRIS JDBC Extended Type Codes

**Question**: What are the correct JDBC type code values for IRIS extended DATE/TIME/TIMESTAMP?

**Decision**: 
- `1091` → DATE (PostgreSQL OID `1082`)
- `1092` → TIME (PostgreSQL OID `1083`)  
- `1093` → TIMESTAMP (PostgreSQL OID `1114`)

Also add standard JDBC aliases `91`, `92`, `93` for the same mappings.

**Rationale**: Confirmed from bug report (observed `type_code=1093` in `cursor.description` for a TIMESTAMP column). The existing `int_type_mapping` in `_iris_type_to_pg_oid()` includes codes 9 and 10 for DATE/TIMESTAMP respectively (IRIS internal codes), but omits the JDBC-standard `9x` and `109x` series returned by the DBAPI cursor.

**Source**: Bug report + IRIS JDBC documentation. The 109x codes are IRIS-specific extensions to standard JDBC type codes (91/92/93 = standard SQL type codes for DATE/TIME/TIMESTAMP per JDBC spec).

---

## Decision 3 — Timezone Offset Handling (Inbound)

**Question**: How should ISO 8601 strings with non-UTC timezone offsets be handled when normalizing inbound parameters?

**Decision**: Convert to UTC, then format as `YYYY-MM-DD HH:MM:SS[.ffffff]` (UTC-equivalent time, offset stripped).

**Rationale**: IRIS `%PosixTime` stores moments in time, not local times. Converting to UTC before storing is semantically correct and consistent with how psycopg3 handles timezone-aware datetimes internally.

**Rejected alternative B**: Strip offset as-is (keep local digits) — lossy and incorrect; two timestamps in different zones representing the same moment would be stored differently.  
**Rejected alternative C**: Reject non-UTC — overly restrictive; breaks psycopg3's default behavior of sending aware datetimes.

---

## Decision 4 — Backward Compatibility (OID Change)

**Question**: Should the OID change from 1043→1114 for `type_code=1093` be gated behind a feature flag?

**Decision**: No flag. The current behavior is a bug. Update all tests that assert the incorrect behavior.

**Rationale**: OID 1043 (VARCHAR) for a TIMESTAMP column is objectively wrong. Any client code that "works" with the current behavior works despite the bug (it receives a string and manually parses it). After the fix, such clients will receive a properly typed `datetime` object, which is strictly better. No known consumer depends on the broken behavior.

---

## Decision 5 — Constant Location (DRY)

**Question**: Should `POSIXTIME_OFFSET` be moved to a shared constants module?

**Decision**: Keep it in `iris_executor.py` as the authoritative definition; `dbapi_executor.py` imports it from there.

**Rationale**: Moving it to a new shared module would add file creation overhead with no functional benefit. The import relationship (`dbapi_executor` → `iris_executor`) already exists implicitly (both are in the same package). A direct import is the minimal change.

---

## No Further Unknowns

All spec items (FR-001 through FR-008, SC-001 through SC-010) are fully resolved. No external library APIs, no new services, no infrastructure changes required.
