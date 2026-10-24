"""Capture PostgreSQL's binary encoding of sample values, as the oracle for value_encoding.py.

    python scripts/capture_binary_values.py <host> <port> <user> <password> <dbname> > \\
        tests/unit/binary_value_fixtures.py

For each case this asks a real PostgreSQL for `COPY (SELECT <literal>::<type>) TO STDOUT (FORMAT
binary)` and keeps the bytes of the one field. That is exactly what PostgreSQL puts in a binary
DataRow or a binary COPY, so a client that decodes PostgreSQL's output decodes ours.

The Python values are the forms the executors in this repository actually hand to the encoder. A
case may list several; all of them must encode to the same bytes.
"""

import datetime
import struct
import sys

import psycopg

PGCOPY_SIGNATURE = b"PGCOPY\n\xff\r\n\x00"

# (label, type oid, SQL literal with cast, python expressions that must all encode identically)
CASES = [
    ("bool true", 16, "true::bool", ["True", "1", "'t'"]),
    ("bool false", 16, "false::bool", ["False", "0", "'f'"]),
    ("int2", 21, "(-5)::int2", ["-5", "'-5'"]),
    ("int4", 23, "123456::int4", ["123456", "'123456'"]),
    ("int4 min", 23, "(-2147483648)::int4", ["-2147483648"]),
    ("int8", 20, "(-9007199254740993)::int8", ["-9007199254740993"]),
    ("oid", 26, "4294967295::oid", ["4294967295"]),
    ("float4", 700, "1.5::float4", ["1.5"]),
    ("float8", 701, "2.5::float8", ["2.5", "'2.5'"]),
    ("float8 negative", 701, "(-1e100)::float8", ["-1e100"]),
    ("text", 25, "'héllo'::text", ["'héllo'"]),
    ("varchar", 1043, "'v'::varchar", ["'v'"]),
    ("bpchar", 1042, "'ab'::bpchar(2)", ["'ab'"]),
    ("name", 19, "'abc'::name", ["'abc'"]),
    ("date", 1082, "'2026-10-24'::date", [
        "9793", "datetime.date(2026, 10, 24)", "'2026-10-24'"]),
    ("date before 2000", 1082, "'1999-12-31'::date", [
        "-1", "datetime.date(1999, 12, 31)", "'1999-12-31'"]),
    ("time", 1083, "'12:34:56.789012'::time", [
        "datetime.time(12, 34, 56, 789012)", "'12:34:56.789012'"]),
    ("time midnight", 1083, "'00:00:00'::time", ["datetime.time(0, 0)", "'00:00:00'", "0"]),
    ("time whole seconds", 1083, "'12:34:56'::time", ["datetime.time(12, 34, 56)", "45296"]),
    ("timestamp", 1114, "'2026-10-24 12:34:56.789012'::timestamp", [
        "datetime.datetime(2026, 10, 24, 12, 34, 56, 789012)", "'2026-10-24 12:34:56.789012'"]),
    ("timestamp before 2000", 1114, "'1999-12-31 23:59:59'::timestamp", [
        "datetime.datetime(1999, 12, 31, 23, 59, 59)", "'1999-12-31 23:59:59'"]),
    ("timestamptz", 1184, "'2026-10-24 12:34:56+00'::timestamptz", [
        "datetime.datetime(2026, 10, 24, 12, 34, 56)", "'2026-10-24 12:34:56'"]),
    ("numeric zero", 1700, "0::numeric", ["Decimal('0')", "0", "'0'"]),
    ("numeric one", 1700, "1::numeric", ["Decimal('1')", "1", "1.0"]),
    ("numeric negative", 1700, "(-1)::numeric", ["Decimal('-1')", "-1"]),
    ("numeric fractional", 1700, "12345.6789::numeric", [
        "Decimal('12345.6789')", "12345.6789", "'12345.6789'"]),
    ("numeric small", 1700, "0.00001::numeric", ["Decimal('0.00001')", "'0.00001'"]),
    ("numeric trailing zeros", 1700, "1.50::numeric", ["Decimal('1.50')", "'1.50'"]),
    ("numeric large", 1700, "100000000000000::numeric", ["Decimal('100000000000000')",
                                                          "100000000000000"]),
    ("numeric nan", 1700, "'NaN'::numeric", ["Decimal('NaN')", "float('nan')"]),
    ("bytea", 17, "'\\xdeadbeef'::bytea", ["b'\\xde\\xad\\xbe\\xef'", "'\\\\xdeadbeef'"]),
    ("bytea empty", 17, "''::bytea", ["b''"]),
    ("uuid", 2950, "'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::uuid", [
        "'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'",
        "uuid.UUID('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11')"]),
    ("json", 114, "'{\"a\": 1}'::json", ["'{\"a\": 1}'", "{'a': 1}"]),
    ("jsonb", 3802, "'{\"a\": 1}'::jsonb", ["'{\"a\": 1}'", "{'a': 1}"]),
    ("int4 array", 1007, "'{1,2,3}'::int4[]", ["[1, 2, 3]", "'{1,2,3}'"]),
    ("int4 array with null", 1007, "'{1,NULL,3}'::int4[]", ["[1, None, 3]", "'{1,NULL,3}'"]),
    ("int4 array empty", 1007, "'{}'::int4[]", ["[]", "'{}'"]),
    ("int8 array", 1016, "'{1,2}'::int8[]", ["[1, 2]", "'{1,2}'"]),
    ("float8 array", 1022, "'{1.5,2.5}'::float8[]", ["[1.5, 2.5]", "'{1.5,2.5}'"]),
    ("bool array", 1000, "'{t,f}'::bool[]", ["[True, False]", "'{t,f}'"]),
    ("text array", 1009, "'{a,\"b c\",NULL}'::text[]", ["['a', 'b c', None]", "'{a,\"b c\",NULL}'"]),
    ("varchar array", 1015, "'{x,y}'::varchar[]", ["['x', 'y']", "'{x,y}'"]),
    ("date array", 1182, "'{2026-10-24}'::date[]", ["[datetime.date(2026, 10, 24)]",
                                                    "'{2026-10-24}'"]),
    ("timestamp array", 1115, "'{\"2026-10-24 12:34:56\"}'::timestamp[]", [
        "[datetime.datetime(2026, 10, 24, 12, 34, 56)]"]),
    ("numeric array", 1231, "'{1.5,2}'::numeric[]", ["[Decimal('1.5'), Decimal('2')]"]),
    ("uuid array", 2951, "'{a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11}'::uuid[]", [
        "['a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11']"]),
    ("vector", 16388, "'[1.5,2.5,3]'::vector", ["[1.5, 2.5, 3.0]", "'[1.5,2.5,3]'", "'1.5,2.5,3'"]),
]  # fmt: skip


def field_bytes(conn, literal: str) -> bytes | None:
    """The bytes of the single field in a one-row, one-column binary COPY."""
    with conn.cursor() as cur, cur.copy(f"COPY (SELECT {literal}) TO STDOUT (FORMAT binary)") as c:
        stream = b"".join(bytes(chunk) for chunk in c)
    assert stream.startswith(PGCOPY_SIGNATURE), stream[:16]
    (ext_len,) = struct.unpack("!i", stream[15:19])
    pos = 19 + ext_len
    (nfields,) = struct.unpack("!h", stream[pos : pos + 2])
    assert nfields == 1, nfields
    (length,) = struct.unpack("!i", stream[pos + 2 : pos + 6])
    return None if length == -1 else stream[pos + 6 : pos + 6 + length]


def main() -> None:
    host, port, user, password, dbname = sys.argv[1:6]
    with psycopg.connect(
        host=host, port=int(port), user=user, password=password, dbname=dbname, autocommit=True
    ) as conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        out = sys.stdout
        out.write('"""PostgreSQL binary encodings of sample values. Generated: do not edit.\n\n')
        out.write(f"Source: PostgreSQL {version}, pgvector {ext[0] if ext else '-'}, captured ")
        out.write(f"{datetime.date.today().isoformat()} by scripts/capture_binary_values.py.\n")
        out.write("Each case: (label, type oid, expected field bytes as hex, python values).\n")
        out.write('"""\n\n')
        out.write("import datetime\nimport uuid\nfrom decimal import Decimal\n\n")
        out.write("# fmt: off\nCASES = [\n")
        for label, oid, literal, values in CASES:
            # The vector literal is typed in the reference's own OID space; the OID below is ours.
            data = field_bytes(conn, literal)
            out.write(f"    ({label!r}, {oid}, {data.hex()!r}, [{', '.join(values)}]),\n")
        out.write("]\n# fmt: on\n")


if __name__ == "__main__":
    main()
