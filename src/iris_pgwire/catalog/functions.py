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
        return f"{CATALOG_SCHEMA}.{self.name}"

    def create_sql(self) -> str:
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

CATALOG_FUNCTIONS: tuple[CatalogFunction, ...] = (PG_OID, PG_PUBLIC_SCHEMA, PG_ARRAY)
