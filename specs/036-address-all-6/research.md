# Research Findings

No outstanding **NEEDS CLARIFICATION** items were identified. All technical decisions are based on existing driver conventions and best practices.

## Decisions
- **DDL handling**: Skip unsupported constructs with warnings (default) and provide `strict_ddl` flag for strict mode.
- **Enum mapping**: Translate registered enum types to `VARCHAR(64)`.
- **Index handling**: Skip indexes referencing tables that were not created.

## Rationale
These choices preserve backward compatibility with existing migration scripts while giving users control over strictness.
