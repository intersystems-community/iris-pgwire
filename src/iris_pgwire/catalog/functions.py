"""SQL functions pgwire installs into IRIS to support catalog emulation.

Each is created with `CREATE OR REPLACE FUNCTION … LANGUAGE OBJECTSCRIPT`,
which is ordinary SQL DDL. That matters for two reasons:

* it works over any connection, so the same installer runs on the embedded and
  DBAPI backends without shipping a `.cls` file or reaching for
  `$SYSTEM.OBJ.Load`, which needs the source on the *server's* filesystem;
* the functions are the reason the catalog views can be defined at all —
  `$SYSTEM.Encryption.SHAHash` is not SQL-callable (SQLCODE -12), and a literal
  `'public'` in view DDL gets rewritten to the IRIS schema name on its way in.

They install before the views, which depend on them.

Writing ObjectScript inside SQL DDL has two sharp edges, both of which cost a
debugging round here:

* The SQL parser reads a bare `:` as a host-variable marker, so `for i = 1:1:4`
  fails with "Parameter Name error, First value cannot be a digit". Every loop
  below is a `while` for that reason. Colons inside string literals are fine.
* This DDL goes through pgwire's own translation pipeline, which uppercases
  identifiers — and IRIS class names are case-sensitive. `RETURNS %Library.List`
  arrives as `%LIBRARY.LIST` and fails with "Class does not exist". So no class
  name may appear in a declaration here; SQL type names such as `VARCHAR` are
  case-insensitive and come through intact.
"""

from __future__ import annotations

from dataclasses import dataclass

from iris_pgwire.schema_mapper import IRIS_SCHEMA

CATALOG_SCHEMA = "PGWire"

# PostgreSQL reserves OIDs below this for system objects.
USER_OID_START = 16384


@dataclass(frozen=True)
class CatalogFunction:
    """One `CREATE FUNCTION` pgwire owns."""

    name: str
    signature: str
    returns: str
    body: str
    purpose: str

    @property
    def qualified_name(self) -> str:
        """Return the schema-qualified function name."""
        return f"{CATALOG_SCHEMA}.{self.name}"

    def create_sql(self) -> str:
        """Return the CREATE OR REPLACE FUNCTION DDL string."""
        return (
            f"CREATE OR REPLACE FUNCTION {self.qualified_name}({self.signature}) "
            f"RETURNS {self.returns} LANGUAGE OBJECTSCRIPT {self.body}"
        )


# Must stay byte-for-byte equivalent to OIDGenerator._generate_oid in
# catalog/oid_generator.py, which is still live for handler-backed tables while
# the migration to views is incomplete: SHA-256 of the identity string, first
# four bytes big-endian, lifted into the user range by ADDING the start offset
# when below it. Not a modulus — that would give the same object different OIDs
# depending on which path answered, and a client joining pg_class to
# pg_attribute across the two would silently match nothing.
PG_OID = CatalogFunction(
    name="PG_OID",
    signature="identity VARCHAR(512)",
    returns="INTEGER",
    purpose="deterministic OID for a catalog object identity string",
    body=f"""{{
  if identity = "" {{ quit {USER_OID_START} }}
  set hash = $SYSTEM.Encryption.SHAHash(256, identity)
  set n = 0, i = 1
  while i < 5 {{ set n = (n * 256) + $ascii($extract(hash, i))  set i = i + 1 }}
  if n < {USER_OID_START} {{ set n = n + {USER_OID_START} }}
  quit n
}}""",
)

# Assembled from two halves so the string "public" never appears as a literal:
# the translation layer rewrites a literal 'public' to the IRIS schema name,
# which is exactly the value this function exists to hide.
PG_PUBLIC_SCHEMA = CatalogFunction(
    name="PG_PUBLIC_SCHEMA",
    signature="",
    returns="VARCHAR(64)",
    purpose="the PostgreSQL-facing name of the default schema",
    body="""{
  quit "pub" _ "lic"
}""",
)

# IRIS's %INLIST takes its whole match set as a single value in $LIST format,
# which is what makes it the right target for PostgreSQL's `col = ANY($1)`: one
# placeholder in, one placeholder out, so the parameter count the client is told
# at Describe still holds at Bind.
#
# No Python path can produce a $LIST, though — the DBAPI rejects a Python list
# and its own IRISList alike ("Unsupported argument type"), and the embedded
# path accepts a list and silently matches nothing. Rather than reproduce the
# undocumented $LIST byte format in Python, the elements arrive as one ordinary
# string parameter and $LISTBUILD assembles them here, on documented ground.
#
# Encoding (see sql_translator.pg_array.encode_pg_array): `<count>|` followed by
# `<len>:<value>` per element, len in characters, -1 for a NULL element.
# Length-prefixed rather than delimited, so no value needs escaping and none can
# be misread — which is what rules out $LISTFROMSTRING.
#
# Malformed input throws. A length prefix wrong by one character slides the rest
# of the parse, and the result would be a query quietly returning the wrong
# rows — the failure mode this whole catalog effort exists to remove. NULL and
# the empty string are not malformed: they build an empty list, which is both
# what `= ANY('{}')` means and what Describe needs, since it prepares the
# statement with a dummy NULL bound.
#
# `$char(0)` appears twice because that is how IRIS SQL spells the empty string
# (measured: binding '' delivers a one-byte \x00 here, binding NULL delivers a
# genuinely empty string, and an empty column value is stored as \x00). So the
# guard has to accept it as "nothing bound", and a zero-length *element* has to
# be built as $char(0) or it will never match an empty column value — silently,
# which is why the integration test that found this drives the installed
# function rather than a Python mirror of it.
PG_ARRAY = CatalogFunction(
    name="PG_ARRAY",
    signature="encoded VARCHAR(32000)",
    # A $LIST is a string of bytes to ObjectScript, and %INLIST reads the value,
    # not the declaration — verified equivalent to `RETURNS %Library.List`,
    # which cannot be used here because the DDL is uppercased on its way in.
    returns="VARCHAR(32000)",
    purpose="build the match set for %INLIST from one bound string parameter",
    body="""{
  if (encoded = "") || (encoded = $char(0)) { quit "" }
  set bar = $find(encoded, "|")
  if bar = 0 { throw ##class(%Exception.SQL).CreateFromSQLCODE(-400, "PG_ARRAY: missing element count") }
  set expected = $extract(encoded, 1, bar - 2)
  set list = "", pos = bar, len = $length(encoded), found = 0
  while pos <= len {
    set colon = $find(encoded, ":", pos)
    if colon = 0 { throw ##class(%Exception.SQL).CreateFromSQLCODE(-400, "PG_ARRAY: truncated element") }
    set count = $extract(encoded, pos, colon - 2)
    set found = found + 1
    if count = -1 {
      set list = list _ $listbuild()
      set pos = colon
    } else {
      if (colon + count - 1) > len { throw ##class(%Exception.SQL).CreateFromSQLCODE(-400, "PG_ARRAY: element overruns input") }
      set value = $extract(encoded, colon, colon + count - 1)
      if value = "" { set value = $char(0) }
      set list = list _ $listbuild(value)
      set pos = colon + count
    }
  }
  if found '= expected { throw ##class(%Exception.SQL).CreateFromSQLCODE(-400, "PG_ARRAY: declared " _ expected _ " elements, parsed " _ found) }
  quit list
}""",
)

# Clients project a comment for the object they are describing. IRIS has no
# equivalent that is reachable from an OID — our OIDs are a one-way hash, so
# there is nothing to look the object back up by — and PostgreSQL returns NULL
# for an object with no comment, which is the honest answer here. Returning
# NULL is what lets the introspection query succeed; inventing a description
# would put made-up text in a generated schema file.
#
# `quit ""` reaches SQL as NULL (measured), so no special casing is needed.
OBJ_DESCRIPTION = CatalogFunction(
    name="OBJ_DESCRIPTION",
    signature="objectOid INTEGER, catalogName VARCHAR(64)",
    returns="VARCHAR(4000)",
    purpose="the comment on a catalog object; always NULL, as IRIS records none",
    body="""{
  quit ""
}""",
)

# Prisma's constraints query calls `pg_get_constraintdef(constr.oid)`. An unknown
# function fails the statement at *prepare* time (SQLCODE -359), whatever the
# result set would have been — so this has to exist even for a query that returns
# no rows, and returning NULL for a constraint that does exist would be the kind
# of fabricated answer FR-008c forbids (spec FR-020).
#
# Our OIDs are a one-way hash, so there is nothing to look an object back up by.
# The lookup instead recomputes PG_OID over the constraint names and matches —
# O(constraints) per call, which is the trade the spec's "introspection is a
# development-time operation" assumption exists to permit.
#
# The rendering follows what PostgreSQL emits for the three kinds IRIS supports,
# verified side by side against real metadata:
#
#   PRIMARY KEY (cid)
#   UNIQUE (code)
#   FOREIGN KEY (parent_id) REFERENCES t015parent(id) ON DELETE CASCADE
#
# `NO ACTION` is PostgreSQL's default and is left implicit, as PostgreSQL does.
# The referenced table is lowercased to match `pg_class.relname`, which the
# pg_class view also lowercases — a client compares the two as text.
PG_GET_CONSTRAINTDEF = CatalogFunction(
    name="PG_GET_CONSTRAINTDEF",
    signature="constraintOid INTEGER",
    returns="VARCHAR(4000)",
    purpose="the DDL text of a constraint, as pg_get_constraintdef renders it",
    body=f"""{{
  new cname, ctype, cols, reftable, refcols, delrule, updrule, text
  set cname = ""
  &sql(SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE INTO :cname, :ctype
       FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
       WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}'
         AND PGWire.PG_OID('{IRIS_SCHEMA.lower()}' _ ':constraint:'
             || LOWER(CONSTRAINT_NAME)) = :constraintOid)
  if (SQLCODE '= 0) || (cname = "") {{ quit "" }}
  set cols = ""
  &sql(SELECT LIST(COLUMN_NAME) INTO :cols
       FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
       WHERE CONSTRAINT_SCHEMA = '{IRIS_SCHEMA}' AND CONSTRAINT_NAME = :cname)
  if ctype = "PRIMARY KEY" {{ quit "PRIMARY KEY (" _ cols _ ")" }}
  if ctype = "UNIQUE" {{ quit "UNIQUE (" _ cols _ ")" }}
  if ctype '= "FOREIGN KEY" {{ quit ctype }}
  set reftable = "", refcols = "", delrule = "", updrule = ""
  &sql(SELECT UNIQUE_CONSTRAINT_TABLE, UPDATE_RULE, DELETE_RULE
       INTO :reftable, :updrule, :delrule
       FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
       WHERE CONSTRAINT_SCHEMA = '{IRIS_SCHEMA}' AND CONSTRAINT_NAME = :cname)
  &sql(SELECT LIST(REFERENCED_COLUMN_NAME) INTO :refcols
       FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
       WHERE CONSTRAINT_SCHEMA = '{IRIS_SCHEMA}' AND CONSTRAINT_NAME = :cname
         AND REFERENCED_COLUMN_NAME IS NOT NULL)
  set text = "FOREIGN KEY (" _ cols _ ") REFERENCES "
      _ $zconvert(reftable, "L") _ "(" _ refcols _ ")"
  if (updrule '= "") && (updrule '= "NO ACTION") {{ set text = text _ " ON UPDATE " _ updrule }}
  if (delrule '= "") && (delrule '= "NO ACTION") {{ set text = text _ " ON DELETE " _ delrule }}
  quit text
}}""",
)

# Renders a type OID and modifier the way PostgreSQL's format_type does, because
# that string is what an ORM writes into a generated schema. Every case below was
# measured against postgres:15-alpine rather than recalled:
#
#   format_type(23, -1)        -> integer
#   format_type(1043, 104)     -> character varying(100)
#   format_type(1043, -1)      -> character varying          (no modifier, no parens)
#   format_type(1042, 14)      -> character(10)
#   format_type(1700, 655366)  -> numeric(10,2)
#   format_type(1700, -1)      -> numeric
#   format_type(1114, -1)      -> timestamp without time zone
#   format_type(701, -1)       -> double precision
#   format_type(16, -1)        -> boolean
#   format_type(99999, -1)     -> ???                        (unknown OID)
#
# The modifier encoding is PostgreSQL's: varchar and char carry length + 4, and
# numeric packs precision * 65536 + scale + 4. `\\` is integer division in
# ObjectScript and `#` is modulo.
FORMAT_TYPE = CatalogFunction(
    name="FORMAT_TYPE",
    signature="typeOid INTEGER, typeMod INTEGER",
    returns="VARCHAR(128)",
    purpose="render a type OID and modifier as PostgreSQL's format_type does",
    body="""{
  new mod, prec, scale
  set mod = typeMod
  if mod = "" { set mod = -1 }
  if typeOid = 23 { quit "integer" }
  if typeOid = 20 { quit "bigint" }
  if typeOid = 21 { quit "smallint" }
  if typeOid = 16 { quit "boolean" }
  if typeOid = 25 { quit "text" }
  if typeOid = 700 { quit "real" }
  if typeOid = 701 { quit "double precision" }
  if typeOid = 1082 { quit "date" }
  if typeOid = 1083 { quit "time without time zone" }
  if typeOid = 1114 { quit "timestamp without time zone" }
  if typeOid = 1184 { quit "timestamp with time zone" }
  if typeOid = 1043 {
    if mod < 5 { quit "character varying" }
    quit "character varying(" _ (mod - 4) _ ")"
  }
  if typeOid = 1042 {
    if mod < 5 { quit "character" }
    quit "character(" _ (mod - 4) _ ")"
  }
  if typeOid = 1700 {
    if mod < 5 { quit "numeric" }
    set prec = (mod - 4) \\ 65536
    set scale = (mod - 4) # 65536
    quit "numeric(" _ prec _ "," _ scale _ ")"
  }
  quit "???"
}""",
)

# PostgreSQL stores a parse tree in pg_attrdef.adbin and renders it with
# pg_get_expr. We have the default's expression *text* and no parse tree, so the
# pg_attrdef view carries the text in adbin and this returns it unchanged — an
# honest rendering of what IRIS records, and what a client writes into a
# generated schema. The relation OID is accepted and unused, as the signature
# requires it.
PG_GET_EXPR = CatalogFunction(
    name="PG_GET_EXPR",
    signature="expressionText VARCHAR(4000), relationOid INTEGER",
    returns="VARCHAR(4000)",
    purpose="render a stored default expression; ours is already text",
    body="""{
  quit expressionText
}""",
)

# The column-level counterpart of OBJ_DESCRIPTION, and NULL for the same reason:
# IRIS records no per-column comment reachable from an OID and a column number,
# and PostgreSQL returns NULL for an uncommented column. Inventing text would put
# it in a generated schema file.
COL_DESCRIPTION = CatalogFunction(
    name="COL_DESCRIPTION",
    signature="relationOid INTEGER, columnNumber INTEGER",
    returns="VARCHAR(4000)",
    purpose="the comment on a column; always NULL, as IRIS records none",
    body="""{
  quit ""
}""",
)

# PostgreSQL format(pattern, arg...) — feature 047.
#
# IRIS SQL functions cannot be variadic, so this ships as two fixed-arity
# variants. The rewriter in sql_translator/pg_functions.py counts arguments
# and routes to the right one.
#
# Substitution modes (spec FR-001):
#   %s -> arg as-is
#   %I -> "identifier" — wrap in double-quotes, escape internal double-quotes
#   %L -> 'literal'   — wrap in single-quotes, escape internal single-quotes
#   %% -> literal %
#
# NULL handling: PostgreSQL format() returns NULL if any argument is NULL.
# NULL arrives as "" from IRIS SQL, so "" is treated as NULL and returns "".
#
# ObjectScript loop note: no colons in loop syntax — use `while`, not `for i=1:1:n`.
FORMAT2 = CatalogFunction(
    name="FORMAT2",
    signature="pattern VARCHAR(4096), arg1 VARCHAR(4096)",
    returns="VARCHAR(4096)",
    purpose="PostgreSQL format(pattern, arg) — %s/%I/%L substitution",
    body="""{
  set result = "", i = 1, len = $length(pattern)
  if arg1 '= "" {
    while i <= len {
      set ch = $extract(pattern, i)
      if ch '= "%" {
        set result = result _ ch
        set i = i + 1
      } else {
        set i = i + 1
        if i > len {
          set result = result _ "%"
          set i = len + 1
        } else {
          set spec = $extract(pattern, i)
          set i = i + 1
          if spec = "%" {
            set result = result _ "%"
          } elseif spec = "s" {
            set result = result _ arg1
          } elseif spec = "I" {
            set dq = $char(34)
            set escaped = $replace(arg1, dq, dq _ dq)
            set result = result _ dq _ escaped _ dq
          } elseif spec = "L" {
            set escaped = $replace(arg1, "'", "''")
            set result = result _ "'" _ escaped _ "'"
          } else {
            throw ##class(%Exception.SQL).CreateFromSQLCODE(-400, "FORMAT2: unknown format code %" _ spec)
          }
        }
      }
    }
  }
  quit result
}""",
)

FORMAT3 = CatalogFunction(
    name="FORMAT3",
    signature="pattern VARCHAR(4096), arg1 VARCHAR(4096), arg2 VARCHAR(4096)",
    returns="VARCHAR(4096)",
    purpose="PostgreSQL format(pattern, arg1, arg2) — %s/%I/%L substitution",
    body="""{
  set result = "", i = 1, len = $length(pattern), argidx = 0, gotnull = 0
  while i <= len {
    set ch = $extract(pattern, i)
    if ch '= "%" {
      set result = result _ ch
      set i = i + 1
    } else {
      set i = i + 1
      if i > len {
        set result = result _ "%"
        set i = len + 1
      } else {
        set spec = $extract(pattern, i)
        set i = i + 1
        if spec = "%" {
          set result = result _ "%"
        } elseif (spec = "s") || (spec = "I") || (spec = "L") {
          set argidx = argidx + 1
          set curarg = $select(argidx = 1: arg1, 1: arg2)
          if curarg = "" {
            set gotnull = 1
            set i = len + 1
          } else {
            if spec = "s" {
              set result = result _ curarg
            } elseif spec = "I" {
              set dq = $char(34)
              set escaped = $replace(curarg, dq, dq _ dq)
              set result = result _ dq _ escaped _ dq
            } else {
              set escaped = $replace(curarg, "'", "''")
              set result = result _ "'" _ escaped _ "'"
            }
          }
        } else {
          throw ##class(%Exception.SQL).CreateFromSQLCODE(-400, "FORMAT3: unknown format code %" _ spec)
        }
      }
    }
  }
  quit $select(gotnull = 1: "", 1: result)
}""",
)

# PostgreSQL jsonb_build_object(k, v, ...) — feature 047.
#
# Returns a JSON object string. Wire type is declared VARCHAR but the
# pg_functions rewriter annotates it as OID 114 (json) in
# CATALOG_COLUMN_TYPE_OIDS if needed. surp reads it as a string so the
# distinction is invisible in practice.
#
# NULL values render as JSON null.
# Keys must not be NULL (PostgreSQL raises an error; we do the same).
JSONB_BUILD_OBJECT4 = CatalogFunction(
    name="JSONB_BUILD_OBJECT4",
    signature="k1 VARCHAR(512), v1 VARCHAR(4096), k2 VARCHAR(512), v2 VARCHAR(4096)",
    returns="VARCHAR(32767)",
    purpose="PostgreSQL jsonb_build_object(k1,v1,k2,v2) — returns JSON object string",
    # $char(34) = double-quote character. Used instead of "" escaping to avoid
    # Python string quoting confusion with the triple-quoted body string.
    body="""{
  new dq, bs
  set dq = $char(34), bs = $char(92)
  if (k1 = "") || (k2 = "") {
    throw ##class(%Exception.SQL).CreateFromSQLCODE(-400, "JSONB_BUILD_OBJECT4: key must not be NULL")
  }
  set ek1 = $replace(k1, dq, bs _ dq)
  set ek2 = $replace(k2, dq, bs _ dq)
  set ev1 = $replace($replace(v1, bs, bs _ bs), dq, bs _ dq)
  set ev2 = $replace($replace(v2, bs, bs _ bs), dq, bs _ dq)
  set jv1 = $select(v1 = "": "null", 1: dq _ ev1 _ dq)
  set jv2 = $select(v2 = "": "null", 1: dq _ ev2 _ dq)
  quit "{" _ dq _ ek1 _ dq _ ":" _ jv1 _ "," _ dq _ ek2 _ dq _ ":" _ jv2 _ "}"
}""",
)

JSONB_BUILD_OBJECT6 = CatalogFunction(
    name="JSONB_BUILD_OBJECT6",
    signature="k1 VARCHAR(512), v1 VARCHAR(4096), k2 VARCHAR(512), v2 VARCHAR(4096), k3 VARCHAR(512), v3 VARCHAR(4096)",
    returns="VARCHAR(32767)",
    purpose="PostgreSQL jsonb_build_object(k1,v1,k2,v2,k3,v3) — returns JSON object string",
    body="""{
  new dq, bs
  set dq = $char(34), bs = $char(92)
  if (k1 = "") || (k2 = "") || (k3 = "") {
    throw ##class(%Exception.SQL).CreateFromSQLCODE(-400, "JSONB_BUILD_OBJECT6: key must not be NULL")
  }
  set ek1 = $replace(k1, dq, bs _ dq)
  set ek2 = $replace(k2, dq, bs _ dq)
  set ek3 = $replace(k3, dq, bs _ dq)
  set ev1 = $replace($replace(v1, bs, bs _ bs), dq, bs _ dq)
  set ev2 = $replace($replace(v2, bs, bs _ bs), dq, bs _ dq)
  set ev3 = $replace($replace(v3, bs, bs _ bs), dq, bs _ dq)
  set jv1 = $select(v1 = "": "null", 1: dq _ ev1 _ dq)
  set jv2 = $select(v2 = "": "null", 1: dq _ ev2 _ dq)
  set jv3 = $select(v3 = "": "null", 1: dq _ ev3 _ dq)
  quit "{" _ dq _ ek1 _ dq _ ":" _ jv1 _ "," _ dq _ ek2 _ dq _ ":" _ jv2 _ "," _ dq _ ek3 _ dq _ ":" _ jv3 _ "}"
}""",
)


JSONB_CONTAINS = CatalogFunction(
    name="JSONB_CONTAINS",
    signature="left_json VARCHAR(65535), right_json VARCHAR(65535)",
    returns="INTEGER",
    purpose="PostgreSQL jsonb @> containment operator — returns 1 if right_json is contained in left_json, 0 otherwise",
    body="""{
  // Empty / null right operand is always contained
  if (right_json = "") || (right_json = "{}") || (right_json = "[]") { quit 1 }
  if (left_json = "") || (left_json = "null") { quit 0 }
  try {
    set tLeft = ##class(%DynamicAbstractObject).%FromJSON(left_json)
    set tRight = ##class(%DynamicAbstractObject).%FromJSON(right_json)
  } catch ex {
    // Malformed JSON — cannot determine containment
    quit 0
  }
  // Object containment: every key-value in tRight must exist with equal value in tLeft
  if tRight.%IsA("%DynamicObject") {
    if 'tLeft.%IsA("%DynamicObject") { quit 0 }
    set tIter = tRight.%GetIterator()
    while tIter.%GetNext(.tKey, .tRVal) {
      set tLVal = tLeft.%Get(tKey)
      // For nested objects/arrays: compare serialized JSON strings
      if $isobject(tRVal) {
        set tLSer = $select($isobject(tLVal): tLVal.%ToJSON(), 1: "")
        set tRSer = tRVal.%ToJSON()
        if tLSer '= tRSer { quit 0 }
      } else {
        if tLVal '= tRVal { quit 0 }
      }
    }
    quit 1
  }
  // Array containment: every element of tRight must appear in tLeft
  if tRight.%IsA("%DynamicArray") {
    if 'tLeft.%IsA("%DynamicArray") { quit 0 }
    set tIterR = tRight.%GetIterator()
    while tIterR.%GetNext(, .tRVal) {
      set tFound = 0
      set tIterL = tLeft.%GetIterator()
      while tIterL.%GetNext(, .tLVal) {
        if $isobject(tRVal) && $isobject(tLVal) {
          if tLVal.%ToJSON() = tRVal.%ToJSON() { set tFound = 1  quit }
        } elseif tLVal = tRVal {
          set tFound = 1  quit
        }
      }
      if 'tFound { quit 0 }
    }
    quit 1
  }
  // Scalar equality
  quit (tLeft = tRight)
}""",
)


CATALOG_FUNCTIONS: tuple[CatalogFunction, ...] = (
    PG_OID,
    PG_PUBLIC_SCHEMA,
    PG_ARRAY,
    OBJ_DESCRIPTION,
    # After PG_OID: the body calls it.
    PG_GET_CONSTRAINTDEF,
    FORMAT_TYPE,
    PG_GET_EXPR,
    COL_DESCRIPTION,
    # Feature 047: surp lint/ERD support
    FORMAT2,
    FORMAT3,
    JSONB_BUILD_OBJECT4,
    JSONB_BUILD_OBJECT6,
    # Feature 050: jsonb @> containment operator
    JSONB_CONTAINS,
)
