# Contract: DDL Splitting and Comment Handling

## Purpose
Ensure multi-statement SQL and DDL with comments are split safely without corrupting statement boundaries.

## Inputs
- SQL text potentially containing multiple statements, comments, and string literals.

## Outputs
- Ordered list of individual SQL statements, preserving semantics.

## Rules
1. **Comment-aware splitting**: Semicolons inside `--` or `/* */` comments MUST NOT split statements.
2. **String-aware splitting**: Semicolons inside single or double-quoted strings MUST NOT split statements.
3. **Leading comments**: Leading comment blocks MUST be preserved with their associated statement.
4. **ALTER TABLE multi-action**: Multi-action `ALTER TABLE` statements MUST be decomposed into single-action statements for IRIS execution.

## Error Handling
- If DDL decomposition fails, return a clear error that includes the original statement context.

## Acceptance Criteria
- DDL scripts with comments and multiple statements execute in order without corruption.
- Multi-action ALTER TABLE statements are split into valid IRIS statements.