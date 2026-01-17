# Contract: Timestamp Normalization

## Purpose
Ensure timestamp values are accepted by IRIS when clients provide ISO 8601 strings or binary-encoded timestamps.

## Inputs
- Timestamp literals in SQL or bound parameter values.

## Outputs
- IRIS-compatible timestamp strings (`YYYY-MM-DD HH:MM:SS[.fff]`).

## Rules
1. **Timezone suffix stripping**: `Z` or offset suffixes MUST be removed for standard timestamp handling.
2. **Binary decoding**: Binary timestamp parameters MUST be converted to IRIS-compatible strings.
3. **Microseconds support**: Preserve fractional seconds when present.

## Error Handling
- If a timestamp cannot be normalized, return a clear error with the offending value.

## Acceptance Criteria
- ISO 8601 timestamps with `T`/`Z` or offsets are accepted after normalization.
- Binary timestamp parameters execute successfully on IRIS.