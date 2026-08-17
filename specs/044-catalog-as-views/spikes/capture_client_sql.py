"""Capture the SQL a real client sends, verbatim, by sitting in front of pgwire.

The server's own logs truncate SQL to a ~150-character preview, so the exact
text a client sends cannot be recovered from them — and for feature 044 the
exact text is the requirement. Every query in the spec's Constraints section was
captured with this, including the one that showed `pg_get_constraintdef(...)` in
the select list, which turned out to be the reason the router never declined
Prisma's constraints query.

This is a transparent TCP relay: it logs client→server Parse and Query message
bodies and forwards everything unchanged in both directions, so the client and
the server behave exactly as they would without it.

    python capture_client_sql.py 5433 5432 /tmp/wire.txt &
    DATABASE_URL="postgresql://_SYSTEM:SYS@127.0.0.1:5433/USER?schema=public" \
        npx prisma db pull --force

Then read /tmp/wire.txt. Note the file can contain raw bytes from other message
types, so read it as text with errors="replace".
"""

import asyncio, struct, sys

LISTEN = int(sys.argv[1]) if len(sys.argv) > 1 else 5433
TARGET = int(sys.argv[2]) if len(sys.argv) > 2 else 5432
OUT = open(sys.argv[3] if len(sys.argv) > 3 else "/dev/stdout", "w")


def dump(buf: bytes) -> None:
    i = 0
    while i + 5 <= len(buf):
        t = buf[i : i + 1]
        (ln,) = struct.unpack("!I", buf[i + 1 : i + 5])
        body = buf[i + 5 : i + 4 + ln]
        if t == b"P":
            name, _, rest = body.partition(b"\x00")
            sql, _, _ = rest.partition(b"\x00")
            print(f"--- Parse {name.decode() or '(unnamed)'}\n{sql.decode(errors='replace')}\n", file=OUT, flush=True)
        elif t == b"Q":
            print(f"--- Query\n{body.rstrip(chr(0).encode()).decode(errors='replace')}\n", file=OUT, flush=True)
        i += 1 + ln


async def pipe(reader, writer, log: bool):
    try:
        while data := await reader.read(65536):
            if log:
                dump(data)
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def handle(cr, cw):
    sr, sw = await asyncio.open_connection("127.0.0.1", TARGET)
    await asyncio.gather(pipe(cr, sw, True), pipe(sr, cw, False))


async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", LISTEN)
    async with server:
        await server.serve_forever()


asyncio.run(main())
