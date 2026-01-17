# Contract: ALTER TABLE Compatibility

## Purpose
Define how ALTER TABLE SET DATA TYPE and DROP NOT NULL behave for IRIS.

## Inputs
- ALTER TABLE statements that change column type or nullability.

## Outputs
- IRIS-compatible ALTER TABLE statements or clear errors when unsupported.

## Rules
1. **SET DATA TYPE translation**: `ALTER COLUMN x SET DATA TYPE T` MUST be translated to `ALTER COLUMN x T` when supported.
2. **DROP NOT NULL translation**: `ALTER COLUMN x DROP NOT NULL` MUST be translated to `ALTER COLUMN x NULL` when supported.
3. **Best-effort behavior**: When IRIS rejects the operation due to constraints, return a clear, actionable error.

## Error Handling
- Errors MUST indicate the column and operation that failed and suggest IRIS constraints as the cause.

## Acceptance Criteria
- Supported ALTER TABLE changes execute successfully in IRIS.
- Unsupported changes return clear, actionable errors.