# Contract: SQL Normalization Pipeline

## Purpose
Define the required ordering and behaviors for SQL normalization so that IRIS receives compatible statements without client-side rewrites.

## Inputs
- Raw SQL statement from PostgreSQL client.

## Outputs
- Normalized SQL statement suitable for IRIS execution.

## Rules
1. **Parameter translation precedes normalization**: `$n` placeholders MUST be translated to `?` before any normalization steps run.
2. **Schema mapping**: Unqualified `public` schema references MUST map to the configured IRIS schema.
3. **Identifier normalization**: Unquoted identifiers MUST be normalized for IRIS compatibility.
4. **Date literal translation**: ISO date literals MUST be translated to IRIS-accepted forms.
5. **JSON operator translation**: `->` and `->>` MUST be mapped to IRIS JSON equivalents.
6. **Vector type normalization**: Vector type declarations MUST be normalized to IRIS vector syntax.

## Error Handling
- If translation fails, return a clear error indicating the unsupported construct.

## Acceptance Criteria
- Given a SQL statement with parameters and supported constructs, the output is valid IRIS SQL.
- Given a statement with unsupported constructs, a clear, actionable error is returned.