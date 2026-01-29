# Contract: Catalog Emulation Interface

## Service: CatalogRouter

The `CatalogRouter` is the central component responsible for identifying and handling PostgreSQL system catalog queries.

### Methods

#### `handle_catalog_query(sql: str, params: Any, session_id: str, executor: Any) -> dict | None`

Processes an incoming SQL query. If the query targets a supported catalog table, it returns a result dictionary compatible with the `IRISExecutor` and `DBAPIExecutor` return formats.

- **Inputs**:
    - `sql`: The raw SQL query string.
    - `params`: Optional query parameters.
    - `session_id`: Unique identifier for the client session.
    - `executor`: Reference to the calling executor (used for metadata lookups if needed).
- **Outputs**:
    - `dict`: A dictionary containing `success`, `rows`, `columns`, `row_count`, and `command_tag`.
    - `None`: If the query is NOT a catalog query and should be passed through to IRIS.

### Supported Catalog Tables

- `pg_type`: Full emulation with 21 standard types.
- `pg_enum`: Empty result set with correct metadata.
- `pg_extension`: Empty result set with correct metadata.
- `pg_namespace`: Emulated (already partially implemented).
- `pg_class`: Emulated (already partially implemented).
- `pg_attribute`: Emulated (already partially implemented).

### Expected Return Format

```json
{
  "success": true,
  "rows": [[16, "bool", 11, 10, ...]],
  "columns": [
    {"name": "oid", "type_oid": 26},
    {"name": "typname", "type_oid": 19},
    ...
  ],
  "row_count": 1,
  "command_tag": "SELECT 1"
}
```
