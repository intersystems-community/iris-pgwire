"""Spike R8 (spec 052 T063): the scope of IRIS's `SET OPTION LOCK_TIMEOUT`.

Plain intersystems-irispython, no PGWire. Usage: python lock_timeout_scope.py [host] [port]
Questions: does it change only the connection that sets it; does it survive COMMIT, a SQL
ROLLBACK and the driver's rollback(); which call reads the server default and the process value.
"""

import sys
import time

import iris

HOST, PORT = (sys.argv[1], int(sys.argv[2])) if len(sys.argv) > 2 else ("127.0.0.1", 2992)


def conn():
    c = iris.connect(HOST, PORT, "USER", "_SYSTEM", "SYS")
    c.setAutoCommit(False)
    return c


def option(cur, name):
    cur.execute(f"SELECT %SYSTEM_SQL.Util_GetOption('{name}')")
    return cur.fetchone()[0]


def wait_for_lock(cur, label):
    """Seconds until a write to the held row fails, and the SQLCODE."""
    t = time.monotonic()
    try:
        cur.execute("UPDATE spk_lt SET n = n WHERE id = 1")
        return f"{label}: no error?!"
    except Exception as e:
        code = "-110" if "-110" in str(e) else str(e)[:60]
        return f"{label}: {time.monotonic() - t:.2f}s {code}"


holder, a, b = conn(), conn(), conn()
h, ca, cb = holder.cursor(), a.cursor(), b.cursor()
for s in (
    "DROP TABLE IF EXISTS spk_lt",
    "CREATE TABLE spk_lt (id INT PRIMARY KEY, n INT)",
    "INSERT INTO spk_lt VALUES (1, 0)",
):
    h.execute(s)
holder.commit()
print(
    "server default LockTimeout:",
    option(ca, "LockTimeout"),
    "process:",
    option(ca, "ProcessLockTimeout"),
)

h.execute("UPDATE spk_lt SET n = n WHERE id = 1")  # holder keeps the row locked throughout
ca.execute("SET OPTION LOCK_TIMEOUT = 2")
print(
    "after A sets 2: A process =",
    option(ca, "ProcessLockTimeout"),
    "B process =",
    option(cb, "ProcessLockTimeout"),
)
print(wait_for_lock(ca, "A (set 2)"))
a.rollback()
print(wait_for_lock(cb, "B (untouched)"))
b.rollback()

ca.execute("SET OPTION LOCK_TIMEOUT = 2")
a.commit()
print("after COMMIT:", option(ca, "ProcessLockTimeout"), wait_for_lock(ca, "A"))
a.rollback()
ca.execute("ROLLBACK")
print("after SQL ROLLBACK:", option(ca, "ProcessLockTimeout"))
a.rollback()
print("after driver rollback():", option(ca, "ProcessLockTimeout"))
ca.execute("SET OPTION LOCK_TIMEOUT = 10")
print("restored with SET OPTION LOCK_TIMEOUT = 10:", option(ca, "ProcessLockTimeout"))
holder.rollback()
h.execute("DROP TABLE spk_lt")
holder.commit()
