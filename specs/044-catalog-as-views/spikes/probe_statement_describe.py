"""Does a *statement* Describe declare the same types the DataRow is encoded as?

Prisma's driver sends Parse → Describe(S) → Bind → Execute. It reads the column
types from the RowDescription that answers the **statement** Describe, then
decodes the DataRow bytes that were encoded at **Execute**. If those two are
computed by different routes and disagree, a one-byte bool arrives under a
varchar declaration and the client fails — which is exactly what
`prisma db pull` reports:

    called `Result::unwrap()` on an `Err` value: "Getting is_partition from
    ResultRow { ... types: [Text, ...], values: [Text(Some("\\0")), ...] }
    as bool failed"

psycopg3 cannot reproduce it: it describes the *portal*, after Bind, so it takes
the other route and sees the right types. Hence this raw client, which speaks the
message sequence Prisma actually uses.

Usage: python probe_statement_describe.py [host] [port]
"""

from __future__ import annotations

import socket
import struct
import sys

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2] if len(sys.argv) > 2 else 5432)

# Prisma's table-introspection query, captured verbatim off the wire.
SQL = """SELECT
  tbl.relname AS table_name,
  namespace.nspname as namespace,
  (tbl.relhassubclass and tbl.relkind = 'p') as is_partition,
  (tbl.relhassubclass and tbl.relkind = 'r') as has_subclass,
  tbl.relrowsecurity as has_row_level_security,
  reloptions,
  obj_description(tbl.oid, 'pg_class') as description
FROM pg_class AS tbl
INNER JOIN pg_namespace AS namespace ON namespace.oid = tbl.relnamespace
WHERE
  (
    (tbl.relkind = 'r' AND tbl.relispartition = 'f')
      OR
    tbl.relkind = 'p'
  )
  AND namespace.nspname = ANY ( $1 )
ORDER BY namespace, table_name;"""

# What PostgreSQL declares for these columns, and therefore what a client will
# try to decode the bytes as.
EXPECTED = {
    "table_name": 19,  # name
    "namespace": 19,  # name
    "is_partition": 16,  # bool
    "has_subclass": 16,  # bool
    "has_row_level_security": 16,  # bool
    "reloptions": 1009,  # text[]
    "description": 25,  # text
}

# name (19), text (25) and varchar (1043) are all length-prefixed strings on the
# wire, in both formats, so a client decodes any of them the same way — Prisma
# reads these three as Text and is satisfied. Reporting them as failures would
# bury the ones that actually break a client, so they are counted separately.
STRING_FAMILY = {19, 25, 1043}

# How many bytes a binary value of each type must occupy, where it is fixed.
BINARY_WIDTH = {16: 1, 21: 2, 23: 4, 26: 4, 20: 8}


def msg(kind: bytes, body: bytes) -> bytes:
    return kind + struct.pack("!I", len(body) + 4) + body


def cstr(text: str) -> bytes:
    return text.encode() + b"\x00"


class Conn:
    def __init__(self, host: str, port: int):
        self.sock = socket.create_connection((host, port), timeout=30)
        self.buf = b""

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def read_message(self) -> tuple[bytes, bytes]:
        while len(self.buf) < 5:
            self._fill()
        kind = self.buf[:1]
        (length,) = struct.unpack("!I", self.buf[1:5])
        while len(self.buf) < 1 + length:
            self._fill()
        body = self.buf[5 : 1 + length]
        self.buf = self.buf[1 + length :]
        return kind, body

    def _fill(self) -> None:
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionError("server closed the connection")
        self.buf += chunk

    def startup(self, user: str, database: str, password: str) -> None:
        params = b"".join(cstr(k) + cstr(v) for k, v in (("user", user), ("database", database)))
        payload = struct.pack("!I", 196608) + params + b"\x00"
        self.send(struct.pack("!I", len(payload) + 4) + payload)
        while True:
            kind, body = self.read_message()
            if kind == b"R":
                (auth,) = struct.unpack("!I", body[:4])
                if auth == 0:
                    continue
                if auth == 3:  # cleartext
                    self.send(msg(b"p", cstr(password)))
                    continue
                raise RuntimeError(f"unsupported auth method {auth}")
            if kind == b"Z":
                return
            if kind == b"E":
                raise RuntimeError(f"startup failed: {body!r}")


def parse_row_description(body: bytes) -> list[tuple[str, int, int]]:
    (count,) = struct.unpack("!H", body[:2])
    offset = 2
    fields = []
    for _ in range(count):
        end = body.index(b"\x00", offset)
        name = body[offset:end].decode()
        offset = end + 1
        _table, _col, type_oid, _size, _mod, fmt = struct.unpack("!IHIhih", body[offset : offset + 18])
        offset += 18
        fields.append((name, type_oid, fmt))
    return fields


def parse_data_row(body: bytes) -> list[bytes | None]:
    (count,) = struct.unpack("!H", body[:2])
    offset = 2
    values: list[bytes | None] = []
    for _ in range(count):
        (length,) = struct.unpack("!i", body[offset : offset + 4])
        offset += 4
        if length == -1:
            values.append(None)
        else:
            values.append(body[offset : offset + length])
            offset += length
    return values


def main() -> int:
    conn = Conn(HOST, PORT)
    conn.startup("_SYSTEM", "USER", "SYS")

    # Prisma's order: Parse, Describe(statement), Bind, Execute, Sync.
    conn.send(msg(b"P", cstr("probe") + cstr(SQL) + struct.pack("!H", 0)))
    conn.send(msg(b"D", b"S" + cstr("probe")))
    # One text[] parameter, sent in text format, binary results requested.
    param = b"{public}"
    bind = (
        cstr("")
        + cstr("probe")
        + struct.pack("!H", 0)  # parameter format codes: all text
        + struct.pack("!H", 1)
        + struct.pack("!i", len(param))
        + param
        + struct.pack("!HH", 1, 1)  # result format codes: all binary
    )
    conn.send(msg(b"B", bind))
    conn.send(msg(b"E", cstr("") + struct.pack("!I", 0)))
    conn.send(msg(b"S", b""))

    described: list[tuple[str, int, int]] = []
    rows: list[list[bytes | None]] = []
    errors: list[str] = []
    while True:
        kind, body = conn.read_message()
        if kind == b"t":  # ParameterDescription
            continue
        if kind == b"T":
            described = parse_row_description(body)
        elif kind == b"D":
            rows.append(parse_data_row(body))
        elif kind == b"E":
            errors.append(body.decode(errors="replace"))
        elif kind == b"Z":
            break

    if errors:
        for err in errors:
            print("  ERROR", err[:200])
        return 1
    if not described:
        print("  FAIL no RowDescription answered the statement Describe")
        return 1

    print("Statement Describe declared:\n")
    failures = 0
    inexact = 0
    for name, type_oid, _fmt in described:
        want = EXPECTED.get(name)
        if want is None or type_oid == want:
            verdict = "ok  "
        elif want in STRING_FAMILY and type_oid in STRING_FAMILY:
            verdict = "~   "
            inexact += 1
        else:
            verdict = "FAIL"
            failures += 1
        note = "" if want is None else f"(PostgreSQL: {want})"
        print(f"  {verdict} {name:24} oid={type_oid:<6}{note}")

    if not rows:
        print("\n  FAIL no rows came back, so the encoding cannot be checked")
        return 1

    print(f"\nFirst DataRow, against those declarations ({len(rows)} rows total):\n")
    for (name, type_oid, _fmt), value in zip(described, rows[0]):
        want_width = BINARY_WIDTH.get(type_oid)
        actual = "NULL" if value is None else f"{len(value)} byte(s) {value!r}"
        ok = value is None or want_width is None or len(value) == want_width
        failures += not ok
        detail = "" if want_width is None else f"declared type needs {want_width}"
        print(f"  {'ok  ' if ok else 'FAIL'} {name:24} {actual:28} {detail}")

    if inexact:
        print(f"\n{inexact} column(s) marked ~ : a different string type than PostgreSQL declares,")
        print("which every client decodes identically. Fidelity gap, not a failure.")
    print(f"\n{'PASS' if not failures else f'{failures} mismatch(es) that break a client'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
