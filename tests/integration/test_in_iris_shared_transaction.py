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

PROBE = textwrap.dedent(
    """
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
    """
)


def _run_probe() -> dict[str, int]:
    completed = subprocess.run(
        ["docker", "exec", "-i", IRIS_CONTAINER, IRISPYTHON, "-"],
        input=PROBE,
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
        if len(parts) == 2 and parts[0] in ("OTHER_SAW", "AFTER_ROLLBACK"):
            values[parts[0]] = int(parts[1])
    assert set(values) == {"OTHER_SAW", "AFTER_ROLLBACK"}, (
        f"the probe produced no verdict; stdout was:\n{completed.stdout}\n"
        f"stderr was:\n{completed.stderr}"
    )
    return values


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
