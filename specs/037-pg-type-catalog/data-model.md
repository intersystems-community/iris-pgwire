# Data Model: PostgreSQL Catalog Emulation

## Entities

### PgType
Represents a row in the `pg_catalog.pg_type` table.

| Field | Type | Description |
|-------|------|-------------|
| oid | integer | Object identifier (standard PostgreSQL OID) |
| typname | string | Name of the data type |
| typnamespace | integer | OID of the namespace (always 11 for pg_catalog) |
| typowner | integer | OID of the owner (defaults to 10 for postgres) |
| typlen | integer | Internal storage size |
| typbyval | boolean | Whether the type is passed by value |
| typtype | char | Type category (b = base) |
| typcategory | char | Category code (B = Boolean, N = Numeric, S = String, D = Date/Time, V = Bit-string, U = User-defined) |
| typispreferred | boolean | Whether the type is preferred for its category |
| typisdefined | boolean | Whether the type is defined |
| typdelim | char | Delimiter used for arrays of this type |
| typrelid | integer | OID of the relation (0 for base types) |
| typelem | integer | OID of the element type (0 for non-arrays) |
| typarray | integer | OID of the array type |
| typinput | string | Input function name |
| typoutput | string | Output function name |
| typnotnull | boolean | Whether the type is non-nullable |

## Static Data: Standard Types

The following 21 types will be emulated:

1.  **bool** (OID 16, category B)
2.  **bytea** (OID 17, category U)
3.  **char** (OID 18, category S)
4.  **name** (OID 19, category S)
5.  **int8** (OID 20, category N)
6.  **int2** (OID 21, category N)
7.  **int4** (OID 23, category N)
8.  **text** (OID 25, category S)
9.  **oid** (OID 26, category N)
10. **float4** (OID 700, category N)
11. **float8** (OID 701, category N)
12. **bpchar** (OID 1042, category S)
13. **varchar** (OID 1043, category S)
14. **date** (OID 1082, category D)
15. **time** (OID 1083, category D)
16. **timestamp** (OID 1114, category D)
17. **timestamptz** (OID 1184, category D)
18. **bit** (OID 1560, category V)
19. **numeric** (OID 1700, category N)
20. **uuid** (OID 2950, category U)
21. **vector** (OID 16388, category U) - Special IRIS vector support

## Mappings

### Unknown Types
Any IRIS type not explicitly mapped to one of the above will default to:
- **typname**: 'text'
- **oid**: 25
- **typcategory**: 'S'
