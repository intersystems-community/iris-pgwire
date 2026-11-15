"""SC-008: per-statement latency through PGWire for a session that uses none of spec 052's features.

Starts one PGWire server (DBAPI backend) from a given source tree, runs a fixed workload with
psycopg, and prints the median and p95 per statement kind as JSON. Run it once per tree and
setting, alternating, against the same IRIS:

    python benchmarks/spec052_statement_overhead.py --src /tmp/pgwire-201/src --iris-port 2993
    python benchmarks/spec052_statement_overhead.py --src src --iris-port 2993 \
        --env PGWIRE_DEFAULT_ISOLATION="read uncommitted"

The workload: SELECT by primary key, single-row INSERT, UPDATE by primary key (each its own
autocommit statement over the extended protocol), and a BEGIN / 3 statements / COMMIT block.
No locking clause, ON CONFLICT, savepoint, timeout or cancel.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]


def _wait_for(port: int, proc: subprocess.Popen, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited with {proc.returncode}")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"nothing listening on {port} after {seconds}s")


def _timed(samples: list[float], fn) -> None:
    started = time.perf_counter()
    fn()
    samples.append((time.perf_counter() - started) * 1000)


def _summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[int(len(ordered) * 0.95) - 1], 3),
    }


def workload(dsn: str, iterations: int, warmup: int) -> dict:
    table = f"sc008_{os.getpid()}"
    samples: dict[str, list[float]] = {"select": [], "insert": [], "update": [], "txn_block": []}
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f"drop table if exists {table}")
        conn.execute(f"create table {table} (id int primary key, n int, label varchar(40))")
        for i in range(1, 101):
            conn.execute(f"insert into {table} values (%s, %s, %s)", (i, 0, f"row {i}"))
        next_id = 1000
        for step in range(warmup + iterations):
            key = step % 100 + 1
            run = samples if step >= warmup else {kind: [] for kind in samples}
            _timed(
                run["select"],
                lambda: conn.execute(
                    f"select id, n, label from {table} where id = %s", (key,)
                ).fetchall(),
            )
            next_id += 1
            _timed(
                run["insert"],
                lambda: conn.execute(
                    f"insert into {table} values (%s, %s, %s)", (next_id, 1, "new")
                ),
            )
            _timed(
                run["update"],
                lambda: conn.execute(f"update {table} set n = n + 1 where id = %s", (key,)),
            )

            def block():
                with conn.transaction():
                    conn.execute(f"select n from {table} where id = %s", (key,)).fetchall()
                    conn.execute(f"update {table} set n = n + 1 where id = %s", (key,))
                    conn.execute(f"update {table} set label = %s where id = %s", ("b", key))

            _timed(run["txn_block"], block)
        conn.execute(f"drop table {table}")
    return {kind: _summary(values) for kind, values in samples.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--src", required=True, help="the tree's src/ directory")
    parser.add_argument("--iris-port", type=int, required=True)
    parser.add_argument("--port", type=int, default=5452)
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--env", action="append", default=[], help="NAME=value for the server")
    args = parser.parse_args()
    src = Path(args.src).resolve()
    server = src.parent / "tests" / "e2e" / "_auth_server.py"
    env = {**os.environ, "PYTHONPATH": str(src), "IRIS_PORT": str(args.iris_port)}
    env.update(item.split("=", 1) for item in args.env)
    dsn = f"host=127.0.0.1 port={args.port} user=_SYSTEM password=SYS dbname=USER sslmode=disable"
    with open(ROOT / "build" / f"sc008-server-{args.port}.log", "w") as log:
        proc = subprocess.Popen(
            [sys.executable, str(server), str(args.port), "trust", "dbapi"],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for(args.port, proc)
            result = workload(dsn, args.iterations, args.warmup)
        finally:
            proc.terminate()
            proc.wait(timeout=30)
    print(json.dumps({"src": str(src), "env": args.env, "results": result}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
