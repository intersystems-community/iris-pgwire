# Data Model: Prisma Catalog Support

**Feature Branch**: `031-prisma-catalog-support`
**Created**: 2025-12-23
**Status**: Complete

---

## Overview

This document defines the data structures for PostgreSQL system catalog emulation. Each catalog table is mapped from IRIS INFORMATION_SCHEMA sources with deterministic OID generation.

---

## Core Data Structures

### 1. OID Generator

```python
from dataclasses import dataclass
from typing import Literal
import hashlib

@dataclass
class ObjectIdentity:
    """Identity tuple for OID generation."""
    namespace: str  # Schema name (e.g., 'SQLUser')
    object_type: Literal['namespace', 'table', 'column', 'constraint', 'index', 'type']
    object_name: str  # Fully qualified name

    @property
    def identity_string(self) -> str:
        return f"{self.namespace}:{self.object_type}:{self.object_name}"


class OIDGenerator:
    """
    Generate stable, deterministic OIDs for IRIS database objects.

    PostgreSQL reserves OIDs 0-16383 for system use.
    User objects should use OIDs >= 16384.
    """

    # Well-known namespace OIDs (match PostgreSQL)
    PG_CATALOG_OID = 11  # pg_catalog namespace
    PUBLIC_OID = 2200    # public namespace (standard PostgreSQL)

    # Reserved OID ranges
    SYSTEM_OID_MAX = 16383
    USER_OID_START = 16384

    def __init__(self):
        self._cache: dict[str, int] = {}

    def get_oid(self, identity: ObjectIdentity) -> int:
        """Get or generate OID for an object."""
        key = identity.identity_string

        if key not in self._cache:
            self._cache[key] = self._generate_oid(key)

        return self._cache[key]

    def _generate_oid(self, identity_string: str) -> int:
        """Generate deterministic OID from identity string."""
        # SHA-256 hash of identity
        hash_bytes = hashlib.sha256(identity_string.encode()).digest()

        # Extract 32-bit value from first 4 bytes
        raw_oid = int.from_bytes(hash_bytes[:4], byteorder='big')

        # Ensure OID is in valid user range
        if raw_oid < self.USER_OID_START:
            raw_oid += self.USER_OID_START

        return raw_oid

    def get_namespace_oid(self, namespace: str) -> int:
        """Get OID for a namespace/schema."""
        if namespace.lower() in ('pg_catalog', 'pg_catalog'):
            return self.PG_CATALOG_OID
        elif namespace.lower() in ('public', 'sqluser'):
            return self.PUBLIC_OID
        else:
            return self.get_oid(ObjectIdentity(
                namespace='',
                object_type='namespace',
                object_name=namespace
            ))
```

---

### 2. pg_namespace (Schema/Namespace Catalog)

**PostgreSQL Definition**: Stores namespace (schema) information.

```python
@dataclass
class PgNamespace:
    """pg_catalog.pg_namespace row."""
    oid: int           # Namespace OID
    nspname: str       # Namespace name (e.g., 'public')
    nspowner: int      # Owner OID (use 10 for postgres superuser)
    nspacl: str | None # Access privileges (NULL = default)


class PgNamespaceEmulator:
    """
    Emulate pg_namespace from IRIS metadata.

    Maps:
    - 'public' -> SQLUser (configurable)
    - 'pg_catalog' -> system types namespace
    """

    STATIC_NAMESPACES = [
        PgNamespace(oid=11, nspname='pg_catalog', nspowner=10, nspacl=None),
        PgNamespace(oid=2200, nspname='public', nspowner=10, nspacl=None),
        PgNamespace(oid=11323, nspname='information_schema', nspowner=10, nspacl=None),
    ]

    def get_all(self) -> list[PgNamespace]:
        """Return all namespaces."""
        return self.STATIC_NAMESPACES

    def get_by_name(self, name: str) -> PgNamespace | None:
        """Get namespace by name."""
        for ns in self.STATIC_NAMESPACES:
            if ns.nspname == name:
                return ns
        return None

    def get_by_oid(self, oid: int) -> PgNamespace | None:
        """Get namespace by OID."""
        for ns in self.STATIC_NAMESPACES:
            if ns.oid == oid:
                return ns
        return None
```

---

### 3. pg_class (Relations Catalog)

**PostgreSQL Definition**: Stores information about tables, indexes, sequences, views, etc.

```python
from typing import Literal

RelKind = Literal['r', 'i', 'S', 'v', 'm', 'c', 'f', 'p']
# r = ordinary table, i = index, S = sequence, v = view,
# m = materialized view, c = composite type, f = foreign table, p = partitioned table

@dataclass
class PgClass:
    """pg_catalog.pg_class row."""
    oid: int                  # Table OID
    relname: str              # Relation name
    relnamespace: int         # Namespace OID (pg_namespace.oid)
    reltype: int              # OID of data type for this relation's row type
    reloftype: int            # OID of composite type, 0 if not based on type
    relowner: int             # Owner OID
    relam: int                # Access method OID (0 for tables)
    relfilenode: int          # File node (not relevant for IRIS)
    reltablespace: int        # Tablespace OID (0 for default)
    relpages: int             # Estimated pages (statistics)
    reltuples: float          # Estimated rows (statistics)
    relallvisible: int        # Pages marked all-visible
    reltoastrelid: int        # TOAST table OID (0 for IRIS)
    relhasindex: bool         # True if has any indexes
    relisshared: bool         # True if shared across databases
    relpersistence: str       # 'p' = permanent, 'u' = unlogged, 't' = temp
    relkind: RelKind          # Relation kind
    relnatts: int             # Number of user columns
    relchecks: int            # Number of CHECK constraints
    relhasrules: bool         # Has rewrite rules
    relhastriggers: bool      # Has triggers
    relhassubclass: bool      # Has inheritance children
    relrowsecurity: bool      # Has row security
    relforcerowsecurity: bool # Force row security
    relispopulated: bool      # True if materialized view is populated
    relreplident: str         # Replica identity
    relispartition: bool      # Is a partition
    relrewrite: int           # Rewriting xid
    relfrozenxid: int         # Frozen transaction ID
    relminmxid: int           # Minimum multixact ID
    relacl: str | None        # Access privileges
    reloptions: str | None    # Access method options


class PgClassEmulator:
    """
    Emulate pg_class from IRIS INFORMATION_SCHEMA.TABLES.

    Query source:
    SELECT TABLE_NAME, TABLE_TYPE
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = 'SQLUser'
    """

    def __init__(self, oid_generator: OIDGenerator):
        self.oid_gen = oid_generator

    def from_iris_table(self, schema: str, table_name: str, table_type: str) -> PgClass:
        """Convert IRIS table metadata to pg_class row."""
        # Determine relkind from TABLE_TYPE
        relkind: RelKind = 'r' if table_type == 'BASE TABLE' else 'v'

        table_oid = self.oid_gen.get_oid(ObjectIdentity(
            namespace=schema,
            object_type='table',
            object_name=table_name
        ))

        namespace_oid = self.oid_gen.get_namespace_oid('public')

        return PgClass(
            oid=table_oid,
            relname=table_name.lower(),  # PostgreSQL uses lowercase
            relnamespace=namespace_oid,
            reltype=0,                    # No row type
            reloftype=0,
            relowner=10,                  # postgres superuser
            relam=0,                      # No access method for tables
            relfilenode=table_oid,        # Use OID as filenode
            reltablespace=0,              # Default tablespace
            relpages=1,                   # Estimate
            reltuples=0,                  # Unknown
            relallvisible=0,
            reltoastrelid=0,              # No TOAST
            relhasindex=False,            # Will be updated
            relisshared=False,
            relpersistence='p',           # Permanent
            relkind=relkind,
            relnatts=0,                   # Will be updated
            relchecks=0,
            relhasrules=False,
            relhastriggers=False,
            relhassubclass=False,
            relrowsecurity=False,
            relforcerowsecurity=False,
            relispopulated=True,
            relreplident='d',             # Default
            relispartition=False,
            relrewrite=0,
            relfrozenxid=0,
            relminmxid=0,
            relacl=None,
            reloptions=None
        )
```

---

### 4. pg_attribute (Column Catalog)

**PostgreSQL Definition**: Stores information about table columns.

```python
@dataclass
class PgAttribute:
    """pg_catalog.pg_attribute row."""
    attrelid: int       # Table OID (pg_class.oid)
    attname: str        # Column name
    atttypid: int       # Data type OID (pg_type.oid)
    attstattarget: int  # Statistics target (default -1)
    attlen: int         # Type length (-1 for variable length)
    attnum: int         # Column number (1-indexed for user columns)
    attndims: int       # Array dimensions (0 if not array)
    attcacheoff: int    # Cache offset (-1)
    atttypmod: int      # Type modifier (e.g., varchar(255) -> 255+4)
    attbyval: bool      # Passed by value
    attstorage: str     # Storage strategy ('p', 'e', 'm', 'x')
    attalign: str       # Alignment ('c', 's', 'i', 'd')
    attnotnull: bool    # NOT NULL constraint
    atthasdef: bool     # Has default value
    atthasmissing: bool # Has missing value
    attidentity: str    # Identity column type ('' = not identity)
    attgenerated: str   # Generated column type ('' = not generated)
    attisdropped: bool  # Column is dropped
    attislocal: bool    # Locally defined (not inherited)
    attinhcount: int    # Inheritance count
    attcollation: int   # Collation OID
    attacl: str | None  # Column privileges
    attoptions: str | None  # Attribute options
    attfdwoptions: str | None  # FDW options
    attmissingval: str | None  # Missing value


class PgAttributeEmulator:
    """
    Emulate pg_attribute from IRIS INFORMATION_SCHEMA.COLUMNS.

    Query source:
    SELECT COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION, IS_NULLABLE, COLUMN_DEFAULT
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'SQLUser' AND TABLE_NAME = ?
    ORDER BY ORDINAL_POSITION
    """

    # IRIS type to PostgreSQL type OID mapping
    TYPE_OID_MAP = {
        'BIGINT': 20,       # int8
        'BIT': 16,          # bool
        'CHAR': 1042,       # bpchar
        'DATE': 1082,       # date
        'DECIMAL': 1700,    # numeric
        'DOUBLE': 701,      # float8
        'INTEGER': 23,      # int4
        'NUMERIC': 1700,    # numeric
        'SMALLINT': 21,     # int2
        'TIME': 1083,       # time
        'TIMESTAMP': 1114,  # timestamp
        'TINYINT': 21,      # int2
        'VARBINARY': 17,    # bytea
        'VARCHAR': 1043,    # varchar
        'LONGVARCHAR': 25,  # text
        'LONGVARBINARY': 17, # bytea
    }

    # Type length mapping
    TYPE_LEN_MAP = {
        'BIGINT': 8,
        'BIT': 1,
        'DATE': 4,
        'DOUBLE': 8,
        'INTEGER': 4,
        'SMALLINT': 2,
        'TIME': 8,
        'TIMESTAMP': 8,
        'TINYINT': 2,
    }

    def __init__(self, oid_generator: OIDGenerator):
        self.oid_gen = oid_generator

    def from_iris_column(
        self,
        schema: str,
        table_name: str,
        column_name: str,
        data_type: str,
        ordinal_position: int,
        is_nullable: str,
        column_default: str | None
    ) -> PgAttribute:
        """Convert IRIS column metadata to pg_attribute row."""

        table_oid = self.oid_gen.get_oid(ObjectIdentity(
            namespace=schema,
            object_type='table',
            object_name=table_name
        ))

        # Parse data type (handle VARCHAR(255) etc.)
        base_type = data_type.split('(')[0].upper()
        type_oid = self.TYPE_OID_MAP.get(base_type, 25)  # Default to text
        type_len = self.TYPE_LEN_MAP.get(base_type, -1)  # Default to variable

        # Calculate type modifier for VARCHAR(n)
        atttypmod = -1
        if '(' in data_type:
            try:
                size = int(data_type.split('(')[1].rstrip(')').split(',')[0])
                if base_type in ('VARCHAR', 'CHAR'):
                    atttypmod = size + 4  # PostgreSQL adds 4 to varchar length
            except (ValueError, IndexError):
                pass

        return PgAttribute(
            attrelid=table_oid,
            attname=column_name.lower(),
            atttypid=type_oid,
            attstattarget=-1,
            attlen=type_len,
            attnum=ordinal_position,
            attndims=0,
            attcacheoff=-1,
            atttypmod=atttypmod,
            attbyval=type_len in (1, 2, 4, 8) and type_len > 0,
            attstorage='p' if type_len > 0 else 'x',
            attalign='d' if type_len == 8 else 'i',
            attnotnull=(is_nullable.upper() == 'NO'),
            atthasdef=(column_default is not None),
            atthasmissing=False,
            attidentity='',
            attgenerated='',
            attisdropped=False,
            attislocal=True,
            attinhcount=0,
            attcollation=0,
            attacl=None,
            attoptions=None,
            attfdwoptions=None,
            attmissingval=None
        )
```

---

### 5. pg_constraint (Constraints Catalog)

**PostgreSQL Definition**: Stores constraints (PK, FK, UNIQUE, CHECK).

```python
from typing import Literal

ConstraintType = Literal['c', 'f', 'p', 'u', 't', 'x']
# c = check, f = foreign key, p = primary key, u = unique, t = trigger, x = exclusion

@dataclass
class PgConstraint:
    """pg_catalog.pg_constraint row."""
    oid: int                  # Constraint OID
    conname: str              # Constraint name
    connamespace: int         # Namespace OID
    contype: ConstraintType   # Constraint type
    condeferrable: bool       # Is deferrable
    condeferred: bool         # Is deferred by default
    convalidated: bool        # Has been validated
    conrelid: int             # Table OID (0 if not table constraint)
    contypid: int             # Domain OID (0 if not domain constraint)
    conindid: int             # Index OID for UNIQUE/PK (0 otherwise)
    conparentid: int          # Parent constraint OID (partitioning)
    confrelid: int            # Referenced table OID (FK only)
    confupdtype: str          # FK update action (a=no action, r=restrict, c=cascade, n=set null, d=set default)
    confdeltype: str          # FK delete action
    confmatchtype: str        # FK match type (f=full, p=partial, s=simple)
    conislocal: bool          # Locally defined
    coninhcount: int          # Inheritance count
    connoinherit: bool        # No inherit
    conkey: list[int]         # Constrained columns (attnum array)
    confkey: list[int]        # Referenced columns (FK only)
    conpfeqop: list[int]      # PK=FK equality operators
    conppeqop: list[int]      # PK=PK equality operators
    conffeqop: list[int]      # FK=FK equality operators
    conexclop: list[int]      # Exclusion operators
    conbin: str | None        # CHECK expression (internal)


class PgConstraintEmulator:
    """
    Emulate pg_constraint from IRIS metadata.

    Query sources:
    - INFORMATION_SCHEMA.TABLE_CONSTRAINTS
    - INFORMATION_SCHEMA.KEY_COLUMN_USAGE
    - INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
    """

    def __init__(self, oid_generator: OIDGenerator):
        self.oid_gen = oid_generator

    def from_iris_constraint(
        self,
        schema: str,
        table_name: str,
        constraint_name: str,
        constraint_type: str,  # 'PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE'
        column_positions: list[int],
        ref_table_name: str | None = None,
        ref_column_positions: list[int] | None = None
    ) -> PgConstraint:
        """Convert IRIS constraint metadata to pg_constraint row."""

        constraint_oid = self.oid_gen.get_oid(ObjectIdentity(
            namespace=schema,
            object_type='constraint',
            object_name=constraint_name
        ))

        table_oid = self.oid_gen.get_oid(ObjectIdentity(
            namespace=schema,
            object_type='table',
            object_name=table_name
        ))

        namespace_oid = self.oid_gen.get_namespace_oid('public')

        # Map constraint type
        contype: ConstraintType = 'p'  # Default primary key
        if constraint_type == 'FOREIGN KEY':
            contype = 'f'
        elif constraint_type == 'UNIQUE':
            contype = 'u'
        elif constraint_type == 'CHECK':
            contype = 'c'

        # FK-specific fields
        confrelid = 0
        confkey: list[int] = []
        if contype == 'f' and ref_table_name:
            confrelid = self.oid_gen.get_oid(ObjectIdentity(
                namespace=schema,
                object_type='table',
                object_name=ref_table_name
            ))
            confkey = ref_column_positions or []

        return PgConstraint(
            oid=constraint_oid,
            conname=constraint_name.lower(),
            connamespace=namespace_oid,
            contype=contype,
            condeferrable=False,
            condeferred=False,
            convalidated=True,
            conrelid=table_oid,
            contypid=0,
            conindid=0,  # Will be set if backing index exists
            conparentid=0,
            confrelid=confrelid,
            confupdtype='a' if contype == 'f' else ' ',
            confdeltype='a' if contype == 'f' else ' ',
            confmatchtype='s' if contype == 'f' else ' ',
            conislocal=True,
            coninhcount=0,
            connoinherit=True,
            conkey=column_positions,
            confkey=confkey,
            conpfeqop=[],
            conppeqop=[],
            conffeqop=[],
            conexclop=[],
            conbin=None
        )
```

---

### 6. pg_index (Index Catalog)

**PostgreSQL Definition**: Stores information about indexes.

```python
@dataclass
class PgIndex:
    """pg_catalog.pg_index row."""
    indexrelid: int       # Index OID (pg_class.oid)
    indrelid: int         # Table OID (pg_class.oid)
    indnatts: int         # Total columns in index
    indnkeyatts: int      # Key columns (excluding INCLUDE)
    indisunique: bool     # Is unique index
    indisprimary: bool    # Is primary key index
    indisexclusion: bool  # Is exclusion constraint
    indimmediate: bool    # Unique check enforced immediately
    indisclustered: bool  # Table was clustered on this index
    indisvalid: bool      # Index is valid
    indcheckxmin: bool    # Check xmin
    indisready: bool      # Index is ready
    indislive: bool       # Index is live
    indisreplident: bool  # Is replica identity
    indkey: list[int]     # Column numbers (attnum array)
    indcollation: list[int]  # Collation OIDs
    indclass: list[int]   # Operator class OIDs
    indoption: list[int]  # Per-column flags
    indexprs: str | None  # Expression trees (for expression indexes)
    indpred: str | None   # Partial index predicate


class PgIndexEmulator:
    """
    Emulate pg_index from IRIS metadata.

    Note: IRIS INFORMATION_SCHEMA doesn't directly expose indexes.
    We generate index entries for primary key constraints and
    potentially query %Dictionary.CompiledIndex for additional indexes.
    """

    def __init__(self, oid_generator: OIDGenerator):
        self.oid_gen = oid_generator

    def from_primary_key(
        self,
        schema: str,
        table_name: str,
        constraint_name: str,
        column_positions: list[int]
    ) -> tuple[PgClass, PgIndex]:
        """
        Generate pg_class and pg_index entries for a primary key.

        Returns both the index relation (pg_class) and index details (pg_index).
        """
        table_oid = self.oid_gen.get_oid(ObjectIdentity(
            namespace=schema,
            object_type='table',
            object_name=table_name
        ))

        index_oid = self.oid_gen.get_oid(ObjectIdentity(
            namespace=schema,
            object_type='index',
            object_name=f"{table_name}_{constraint_name}_idx"
        ))

        namespace_oid = self.oid_gen.get_namespace_oid('public')

        # Create pg_class entry for the index
        index_class = PgClass(
            oid=index_oid,
            relname=f"{table_name.lower()}_{constraint_name.lower()}_idx",
            relnamespace=namespace_oid,
            reltype=0,
            reloftype=0,
            relowner=10,
            relam=403,  # btree access method
            relfilenode=index_oid,
            reltablespace=0,
            relpages=1,
            reltuples=0,
            relallvisible=0,
            reltoastrelid=0,
            relhasindex=False,
            relisshared=False,
            relpersistence='p',
            relkind='i',  # index
            relnatts=len(column_positions),
            relchecks=0,
            relhasrules=False,
            relhastriggers=False,
            relhassubclass=False,
            relrowsecurity=False,
            relforcerowsecurity=False,
            relispopulated=True,
            relreplident='n',
            relispartition=False,
            relrewrite=0,
            relfrozenxid=0,
            relminmxid=0,
            relacl=None,
            reloptions=None
        )

        # Create pg_index entry
        index_entry = PgIndex(
            indexrelid=index_oid,
            indrelid=table_oid,
            indnatts=len(column_positions),
            indnkeyatts=len(column_positions),
            indisunique=True,
            indisprimary=True,
            indisexclusion=False,
            indimmediate=True,
            indisclustered=False,
            indisvalid=True,
            indcheckxmin=False,
            indisready=True,
            indislive=True,
            indisreplident=False,
            indkey=column_positions,
            indcollation=[0] * len(column_positions),
            indclass=[1978] * len(column_positions),  # int4_ops
            indoption=[0] * len(column_positions),
            indexprs=None,
            indpred=None
        )

        return index_class, index_entry
```

---

### 7. pg_attrdef (Column Defaults Catalog)

**PostgreSQL Definition**: Stores default values for columns.

```python
@dataclass
class PgAttrdef:
    """pg_catalog.pg_attrdef row."""
    oid: int        # Default definition OID
    adrelid: int    # Table OID
    adnum: int      # Column number
    adbin: str      # Default expression (internal nodeToString)


class PgAttrdefEmulator:
    """
    Emulate pg_attrdef from IRIS INFORMATION_SCHEMA.COLUMNS.COLUMN_DEFAULT.
    """

    def __init__(self, oid_generator: OIDGenerator):
        self.oid_gen = oid_generator

    def from_iris_default(
        self,
        schema: str,
        table_name: str,
        column_name: str,
        column_num: int,
        default_value: str
    ) -> PgAttrdef:
        """Convert IRIS column default to pg_attrdef row."""

        default_oid = self.oid_gen.get_oid(ObjectIdentity(
            namespace=schema,
            object_type='default',
            object_name=f"{table_name}.{column_name}"
        ))

        table_oid = self.oid_gen.get_oid(ObjectIdentity(
            namespace=schema,
            object_type='table',
            object_name=table_name
        ))

        return PgAttrdef(
            oid=default_oid,
            adrelid=table_oid,
            adnum=column_num,
            adbin=default_value  # Store as-is for now
        )
```

---

## Catalog Router Architecture

```python
from dataclasses import dataclass
from typing import Any

@dataclass
class CatalogQueryResult:
    """Result from catalog query execution."""
    success: bool
    rows: list[tuple[Any, ...]]
    columns: list[dict[str, Any]]  # Column metadata
    row_count: int


class CatalogRouter:
    """
    Route pg_catalog queries to appropriate emulators.

    Intercepts queries to:
    - pg_catalog.pg_namespace
    - pg_catalog.pg_class
    - pg_catalog.pg_attribute
    - pg_catalog.pg_constraint
    - pg_catalog.pg_index
    - pg_catalog.pg_type
    - pg_catalog.pg_attrdef
    """

    def __init__(self, iris_schema: str = 'SQLUser'):
        self.iris_schema = iris_schema
        self.oid_gen = OIDGenerator()

        # Initialize emulators
        self.pg_namespace = PgNamespaceEmulator()
        self.pg_class = PgClassEmulator(self.oid_gen)
        self.pg_attribute = PgAttributeEmulator(self.oid_gen)
        self.pg_constraint = PgConstraintEmulator(self.oid_gen)
        self.pg_index = PgIndexEmulator(self.oid_gen)
        self.pg_attrdef = PgAttrdefEmulator(self.oid_gen)

    def can_handle(self, sql: str) -> bool:
        """Check if SQL targets pg_catalog."""
        sql_upper = sql.upper()
        return 'PG_CATALOG' in sql_upper or any(
            table in sql_upper for table in [
                'PG_NAMESPACE', 'PG_CLASS', 'PG_ATTRIBUTE',
                'PG_CONSTRAINT', 'PG_INDEX', 'PG_TYPE', 'PG_ATTRDEF'
            ]
        )

    def execute(self, sql: str, params: list | None = None) -> CatalogQueryResult:
        """Execute catalog query and return results."""
        # Parse SQL to determine target table and conditions
        # Route to appropriate emulator
        # Return formatted results
        pass
```

---

## Type Mapping Reference

### IRIS to PostgreSQL Type OIDs

| IRIS Type | PostgreSQL Type | OID |
|-----------|----------------|-----|
| BIGINT | int8 | 20 |
| BIT | bool | 16 |
| CHAR | bpchar | 1042 |
| DATE | date | 1082 |
| DECIMAL | numeric | 1700 |
| DOUBLE | float8 | 701 |
| INTEGER | int4 | 23 |
| NUMERIC | numeric | 1700 |
| SMALLINT | int2 | 21 |
| TIME | time | 1083 |
| TIMESTAMP | timestamp | 1114 |
| TINYINT | int2 | 21 |
| VARBINARY | bytea | 17 |
| VARCHAR | varchar | 1043 |
| LONGVARCHAR | text | 25 |
| VECTOR | vector | 16388 |

---

## Summary

This data model provides the foundation for PostgreSQL catalog emulation:

1. **OIDGenerator**: Deterministic OID generation for all IRIS objects
2. **PgNamespace**: Schema/namespace catalog (static + dynamic)
3. **PgClass**: Table/view/index catalog from INFORMATION_SCHEMA.TABLES
4. **PgAttribute**: Column catalog from INFORMATION_SCHEMA.COLUMNS
5. **PgConstraint**: Constraint catalog from TABLE_CONSTRAINTS
6. **PgIndex**: Index catalog from primary keys (extendable)
7. **PgAttrdef**: Default values from COLUMN_DEFAULT
8. **CatalogRouter**: Query routing to appropriate emulators
