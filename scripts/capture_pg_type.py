"""Capture pg_catalog.pg_type rows from a real PostgreSQL, as the data behind our pg_type view.

    python scripts/capture_pg_type.py <host> <port> <user> <password> <dbname> > \\
        src/iris_pgwire/catalog/pg_type_data.py

The reference must be PostgreSQL 16 with the `vector` extension created (the
`pgvector/pgvector:pg16` image does this with `CREATE EXTENSION vector`). Run it again against a
newer reference to refresh the data; `tests/unit/test_pg_type_view.py` pins the invariants the
refreshed rows must still satisfy.

Why captured and not written by hand: clients decide how to decode a column from `typreceive` and
friends, by *name*. The ADBC PostgreSQL driver maps `int4recv` to a 32-bit integer and has no idea
what a guessed name means. PostgreSQL is the authority on its own catalog.

Which rows: every type this server can put in a RowDescription, plus the array type of each. The
list is `WANTED`; the test `test_every_oid_the_server_can_emit_has_a_row` fails if the server
starts emitting an OID that is not here.
"""

import datetime
import sys

import psycopg

# Scalar types and their array types are fetched together (typarray). vector is an extension type,
# so its OID is whatever that database assigned; it is renumbered below to the OID this project has
# always used for it.
WANTED = [
    16, 17, 18, 19, 20, 21, 23, 25, 26, 114, 700, 701, 705, 1042, 1043, 1082, 1083, 1114, 1184,
    1186, 1266, 1560, 1562, 1700, 2950, 3802,
]  # fmt: skip
VECTOR_OID, VECTOR_ARRAY_OID = 16388, 16389

COLUMNS = [
    "oid", "typname", "typnamespace", "typowner", "typlen", "typbyval", "typtype", "typcategory",
    "typispreferred", "typisdefined", "typdelim", "typrelid", "typsubscript", "typelem", "typarray",
    "typinput", "typoutput", "typreceive", "typsend", "typmodin", "typmodout", "typanalyze",
    "typalign", "typstorage", "typnotnull", "typbasetype", "typtypmod", "typndims", "typcollation",
    "typdefaultbin", "typdefault", "typacl",
]  # fmt: skip
REGPROC = {"typsubscript", "typinput", "typoutput", "typreceive", "typsend", "typmodin",
           "typmodout", "typanalyze"}  # fmt: skip


def select_list() -> str:
    # regproc columns come back as their function names; pg_node_tree and aclitem[] as text.
    return ", ".join(
        f"{c}::text AS {c}" if c in REGPROC or c in ("typdefaultbin", "typacl") else c
        for c in COLUMNS
    )


def fetch(cur, where: str, params: tuple) -> list[dict]:
    cur.execute(f"SELECT {select_list()} FROM pg_catalog.pg_type WHERE {where} ORDER BY oid", params)
    names = [d.name for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def main() -> None:
    host, port, user, password, dbname = sys.argv[1:6]
    with psycopg.connect(host=host, port=int(port), user=user, password=password, dbname=dbname) as conn:
        cur = conn.cursor()
        version = conn.execute("SHOW server_version").fetchone()[0]
        scalars = fetch(cur, "oid = ANY(%s)", (WANTED,))
        arrays = fetch(cur, "oid = ANY(%s)", ([r["typarray"] for r in scalars if r["typarray"]],))
        vector = fetch(cur, "typname = 'vector' AND typtype = 'b'", ())
        vector_array = fetch(cur, "typname = '_vector'", ())
        if len(vector) != 1 or len(vector_array) != 1:
            sys.exit("the reference has no `vector` extension: run CREATE EXTENSION vector there")
        ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]

    # Renumber the extension type to the OIDs this project already used for it.
    vec, vec_arr = dict(vector[0]), dict(vector_array[0])
    for row, new in ((vec, VECTOR_OID), (vec_arr, VECTOR_ARRAY_OID)):
        row["oid"] = new
    vec["typarray"], vec_arr["typelem"] = VECTOR_ARRAY_OID, VECTOR_OID

    rows = scalars + arrays + [vec, vec_arr]
    rows.sort(key=lambda r: r["oid"])
    out = sys.stdout
    out.write('"""pg_type rows captured from a real PostgreSQL. Generated: do not edit by hand.\n\n')
    out.write(f"Source: PostgreSQL {version} with pgvector {ext}, captured "
              f"{datetime.date.today().isoformat()} by scripts/capture_pg_type.py.\n")
    out.write("Regenerate with that script; tests/unit/test_pg_type_view.py pins the invariants.\n")
    out.write('The `vector` type and its array are renumbered to 16388 and 16389.\n"""\n\n')
    out.write("# fmt: off\n")
    out.write(f"PG_TYPE_COLUMNS = {tuple(COLUMNS)!r}\n\n")
    out.write("PG_TYPE_ROWS = (\n")
    for r in rows:
        out.write(f"    {tuple(r[c] for c in COLUMNS)!r},\n")
    out.write(")\n# fmt: on\n")


if __name__ == "__main__":
    main()
