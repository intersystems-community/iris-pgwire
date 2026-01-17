# Contract: DEFAULT in VALUES Handling

## Purpose
Provide IRIS-compatible behavior for INSERT statements that use `DEFAULT` within a VALUES list.

## Inputs
- INSERT statement with column list and VALUES list that may contain `DEFAULT`.

## Outputs
- INSERT statement rewritten to omit DEFAULT column/value pairs.

## Rules
1. **DEFAULT removal**: Columns paired with `DEFAULT` in VALUES MUST be removed from both column list and values list.
2. **Row integrity**: Remaining columns and values MUST preserve ordering and alignment.
3. **Row-level DEFAULT VALUES**: `INSERT INTO table DEFAULT VALUES` passes through unchanged.

## Error Handling
- If DEFAULT removal would empty the column list while values remain, return a clear error.

## Acceptance Criteria
- INSERT statements with per-column DEFAULT values execute successfully in IRIS.
- Defaults are applied as defined by table schema.