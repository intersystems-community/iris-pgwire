"""In the in-IRIS deployment, sessions share one transaction. Pinned, not endorsed.

Deployed inside IRIS (the embedded backend, `BACKEND_TYPE=embedded`), every wire
session is served by a thread of the *same* IRIS process, and an IRIS transaction
belongs to the process rather than the thread. So the isolation a PostgreSQL
client assumes between connections does not exist there: one client's COMMIT
commits another client's uncommitted work, and the other client's ROLLBACK then
has nothing left to undo.

Measured inside `iris-pgwire-db` (IRIS 2026.1 CE) with two threads of one
embedded process:

    thread A  START TRANSACTION; INSERT (id 1)
    thread B  SELECT COUNT(*)  -> 1          (it sees A's uncommitted row)
    thread B  COMMIT           -> A's row is now committed
    thread A  ROLLBACK         -> no effect
    afterwards SELECT COUNT(*) -> 1          (PostgreSQL would say 0)

What is wrong is the SCOPE of the transaction, not the ability to express one.
Measured separately, single-threaded on the same path:

    START TRANSACTION; INSERT; ROLLBACK -> COUNT(*) = 0   (PostgreSQL: 0)
    START TRANSACTION; INSERT; COMMIT   -> COUNT(*) = 1   (PostgreSQL: 1)

So an application driving the embedded path from one thread gets correct
transaction semantics; only concurrency breaks it. Pinned below, because
"the embedded path cannot do transactions" is the wrong summary and would send
someone to fix the wrong thing.

This is asserted through `docker exec ... irispython` rather than through the wire
because it is a property of the backend's process model, and because the embedded
backend cannot be imported from CPython on the host. It does not skip itself: the
container is a requirement of this suite, and a skipped pin is indistinguishable
from a passing one.

The DBAPI backend is unaffected — each session gets its own IRIS connection, and
tests/protocol/test_isolation_e2e.py's TestCrossSessionIsolation pins that.
"""

from __future__ import annotations

import subprocess
import textwrap

import pytest

# docker-compose.yml names the project's one IRIS container. Crossing projects'
# containers is forbidden, so this is written rather than discovered.
IRIS_CONTAINER = "iris-pgwire-db"
IRISPYTHON = "/usr/irissys/bin/irispython"

PROBE = textwrap.dedent("""
    import threading
    import iris


    def q(sql):
        result = iris.sql.exec(sql)
        return list(result) if result is not None else None


    try:
        q("DROP TABLE SQLUser.PgwireTxShare")
    except Exception:
        pass

    q("CREATE TABLE SQLUser.PgwireTxShare (id INT PRIMARY KEY, v INT)")
    q("START TRANSACTION")
    q("INSERT INTO SQLUser.PgwireTxShare (id, v) VALUES (1, 1)")

    seen = {}


    def other_session():
        seen["count"] = q("SELECT COUNT(*) FROM SQLUser.PgwireTxShare")[0][0]
        q("COMMIT")


    thread = threading.Thread(target=other_session)
    thread.start()
    thread.join()

    q("ROLLBACK")
    final = q("SELECT COUNT(*) FROM SQLUser.PgwireTxShare")[0][0]
    q("DROP TABLE SQLUser.PgwireTxShare")

    print("OTHER_SAW", seen["count"])
    print("AFTER_ROLLBACK", final)
    """)


SINGLE_THREAD_PROBE = textwrap.dedent("""
    import iris


    def q(sql):
        result = iris.sql.exec(sql)
        return list(result) if result is not None else None


    def count():
        return q("SELECT COUNT(*) FROM SQLUser.PgwireTxExpress")[0][0]


    try:
        q("DROP TABLE SQLUser.PgwireTxExpress")
    except Exception:
        pass

    q("CREATE TABLE SQLUser.PgwireTxExpress (id INT PRIMARY KEY, v INT)")

    q("START TRANSACTION")
    q("INSERT INTO SQLUser.PgwireTxExpress (id, v) VALUES (1, 1)")
    inside = count()
    q("ROLLBACK")
    after_rollback = count()

    q("START TRANSACTION")
    q("INSERT INTO SQLUser.PgwireTxExpress (id, v) VALUES (2, 2)")
    q("COMMIT")
    after_commit = count()

    q("DROP TABLE SQLUser.PgwireTxExpress")

    print("INSIDE", inside)
    print("AFTER_ROLLBACK", after_rollback)
    print("AFTER_COMMIT", after_commit)
    """)


def _run(script: str, keys: tuple[str, ...]) -> dict[str, int]:
    completed = subprocess.run(
        ["docker", "exec", "-i", IRIS_CONTAINER, IRISPYTHON, "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, (
        f"the embedded probe did not run (is {IRIS_CONTAINER} up? "
        f"`docker compose up -d`): {completed.stderr.strip()}"
    )
    values = {}
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in keys:
            values[parts[0]] = int(parts[1])
    assert set(values) == set(keys), (
        f"the probe produced no verdict; stdout was:\n{completed.stdout}\n"
        f"stderr was:\n{completed.stderr}"
    )
    return values


def _run_probe() -> dict[str, int]:
    return _run(PROBE, ("OTHER_SAW", "AFTER_ROLLBACK"))


@pytest.mark.pinned_limitation
@pytest.mark.requires_docker
@pytest.mark.integration
class TestSessionsShareOneTransactionInIris:
    def test_one_sessions_commit_commits_anothers_work(self):
        """The row survives a ROLLBACK by the session that inserted it.

        On PostgreSQL the count afterwards is 0: the insert belonged to the
        transaction that rolled back, and no other connection could have committed
        it. A different answer here means the backend gained per-session
        transactions and KNOWN_LIMITATIONS.md needs updating.
        """
        values = _run_probe()
        assert values["AFTER_ROLLBACK"] == 1, (
            "the insert was undone, so the two sessions had separate "
            "transactions — the documented limitation has changed"
        )

    def test_the_other_session_sees_uncommitted_work(self):
        """Not the same finding: IRIS defaults to READ UNCOMMITTED anyway.

        Pinned separately so the two cannot be confused — this one would also be
        true of two genuinely separate IRIS connections at the default level, and
        it is the COMMIT above that shows they are not separate.
        """
        values = _run_probe()
        assert values["OTHER_SAW"] == 1


@pytest.mark.requires_docker
@pytest.mark.integration
class TestTheEmbeddedPathCanExpressATransaction:
    """The other half of the finding, and not a limitation — hence no pin marker.

    Held here so the limitation above cannot be read as "the embedded path does
    not do transactions". It does; what it cannot do is confine one to the
    session that opened it. Someone who mixes the two goes looking for a missing
    transaction implementation instead of for a process-scoped one.
    """

    def test_a_single_threaded_rollback_and_commit_behave(self):
        values = _run(SINGLE_THREAD_PROBE, ("INSIDE", "AFTER_ROLLBACK", "AFTER_COMMIT"))
        assert values["INSIDE"] == 1, "the insert was not visible to its own transaction"
        assert values["AFTER_ROLLBACK"] == 0, (
            "ROLLBACK did not undo the insert, so the embedded path cannot express "
            "an explicit transaction even single-threaded — a stronger limitation "
            "than the one documented, and KNOWN_LIMITATIONS.md understates it"
        )
        assert values["AFTER_COMMIT"] == 1, "COMMIT did not persist the insert"
