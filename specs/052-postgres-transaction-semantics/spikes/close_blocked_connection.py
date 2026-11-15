"""Spike R9 (spec 052 T064): can another thread stop a DBAPI call blocked on a lock?

Plain intersystems-irispython, no PGWire. Usage: python close_blocked_connection.py [host] [port]
A holds a row. B inserts a row of its own, then blocks updating A's row (lock timeout 30 s).
After 1 s the main thread calls B's connection.close(). Measured: how long close() takes, when
and how B's blocked call returns, whether B's insert was rolled back and its lock released (seen
from a third connection C), and whether IRIS still lists B's process.
"""

import sys
import threading
import time

import iris

HOST, PORT = (sys.argv[1], int(sys.argv[2])) if len(sys.argv) > 2 else ("127.0.0.1", 2992)


def conn():
    c = iris.connect(HOST, PORT, "USER", "_SYSTEM", "SYS")
    c.setAutoCommit(False)
    return c


def processes(cur):
    cur.execute("SELECT COUNT(*) FROM %SYS.ProcessQuery WHERE ClientExecutableName IS NOT NULL")
    return cur.fetchone()[0]


holder, b, c = conn(), conn(), conn()
h, cb, cc = holder.cursor(), b.cursor(), c.cursor()
for s in (
    "DROP TABLE IF EXISTS spk_cb",
    "CREATE TABLE spk_cb (id INT PRIMARY KEY, n INT)",
    "INSERT INTO spk_cb VALUES (1, 0)",
):
    h.execute(s)
holder.commit()
try:
    before = processes(cc)
except Exception as e:  # noqa: BLE001 - a spike: report and go on
    before = f"n/a ({str(e)[:60]})"

h.execute("UPDATE spk_cb SET n = n WHERE id = 1")
cb.execute("SET OPTION LOCK_TIMEOUT = 30")
cb.execute("INSERT INTO spk_cb VALUES (2, 0)")
outcome = {}


def blocked():
    t = time.monotonic()
    try:
        cb.execute("UPDATE spk_cb SET n = 5 WHERE id = 1")
        outcome["result"] = "completed?!"
    except Exception as e:  # noqa: BLE001
        outcome["result"] = f"{type(e).__name__}: {str(e)[:120]}"
    outcome["returned_after"] = round(time.monotonic() - t, 2)


worker = threading.Thread(target=blocked)
worker.start()
time.sleep(1.0)
t = time.monotonic()
try:
    b.close()
    outcome["close"] = f"returned in {time.monotonic() - t:.2f}s"
except Exception as e:  # noqa: BLE001
    outcome["close"] = (
        f"raised after {time.monotonic() - t:.2f}s: {type(e).__name__}: {str(e)[:100]}"
    )
worker.join(timeout=40)
outcome["worker_alive_after_40s"] = worker.is_alive()
print(outcome)

holder.rollback()  # free row 1
time.sleep(0.5)
cc.execute("SELECT COUNT(*) FROM spk_cb WHERE id = 2")
print("B's insert still there (seen from C):", cc.fetchone()[0])
cc.execute("SET OPTION LOCK_TIMEOUT = 2")
try:
    cc.execute("UPDATE spk_cb SET n = 7 WHERE id = 2")
    print("row 2 lock free from C: yes (rowcount", cc.rowcount, ")")
except Exception as e:  # noqa: BLE001
    print("row 2 lock from C:", str(e)[:100])
c.rollback()
try:
    print("client processes before/after:", before, processes(cc))
except Exception as e:  # noqa: BLE001
    print("process count n/a:", str(e)[:80])
h.execute("DROP TABLE spk_cb")
holder.commit()
