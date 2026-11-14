"""Text-format DataRows (psql, JDBC, psycopg default) for 100k bench-shaped rows: old vs new."""
import sys, time, asyncio
sys.argv = ["x"]
src = open("/tmp/pgwire-enc/enc_bench.py").read().split("fmt = ExportFormat")[0]
exec(src)
from unittest.mock import MagicMock
from iris_pgwire.row_encoding import data_row_encoder
from iris_pgwire.protocol import PGWireProtocol
writer = MagicMock(); out = []
writer.write = out.append
p = PGWireProtocol.__new__(PGWireProtocol); p.writer = writer; p._current_result_formats = [0]
async def old():
    for r in data: await p.send_data_row(r, cols)
best = 9e9
for _ in range(3):
    out.clear(); t = time.perf_counter(); asyncio.run(old()); best = min(best, time.perf_counter() - t)
old_bytes = b"".join(out)
print(f"old send_data_row, text: {best:.3f}s")
enc = data_row_encoder(OIDS, [0]); best = 9e9
for _ in range(3):
    t = time.perf_counter(); new = b"".join(map(enc, data)); best = min(best, time.perf_counter() - t)
print(f"data_row_encoder, text:  {best:.3f}s, identical: {new == old_bytes}")
import cProfile, pstats
cProfile.run("b''.join(map(enc, data))", "/tmp/pgwire-enc/text.prof")
pstats.Stats("/tmp/pgwire-enc/text.prof").sort_stats("tottime").print_stats(6)
