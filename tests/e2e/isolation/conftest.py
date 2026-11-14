"""The isolation suite: every case against PGWire and against PostgreSQL 16.

Run it with ``make isolation``, in its own pytest process (two-session tests are contaminated by
other suites in the same process; see tests/protocol/test_isolation_e2e.py). Targets:

    ISOLATION_PGWIRE_DSN    a running PGWire server        (default 127.0.0.1:5442, _SYSTEM, USER)
    ISOLATION_POSTGRES_DSN  the reference PostgreSQL 16    (default 127.0.0.1:55433, iris-pgwire-pgref)
    ISOLATION_RESULTS       JSONL file the runs append to  (default build/isolation-results.jsonl)
    ISOLATION_REPEATS       runs per Hermitage case and level (default 5)

``ISOLATION_SUITE=1`` turns the suite on; ``make isolation`` sets it. Without it every test here
skips, so a plain ``pytest`` does not start two-session work against servers it did not ask for.
That skip is for CI portability. With it set, an unreachable target is an error, not a skip.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import psycopg
import pytest

from .harness import Target

ROOT = Path(__file__).resolve().parents[3]

PGWIRE_DSN = os.environ.get(
    "ISOLATION_PGWIRE_DSN",
    "host=127.0.0.1 port=5442 user=_SYSTEM password=SYS dbname=USER sslmode=disable",
)
POSTGRES_DSN = os.environ.get(
    "ISOLATION_POSTGRES_DSN",
    "host=127.0.0.1 port=55433 user=postgres password=pgref dbname=postgres sslmode=disable",
)
RESULTS = Path(os.environ.get("ISOLATION_RESULTS", ROOT / "build" / "isolation-results.jsonl"))
ENABLED = os.environ.get("ISOLATION_SUITE") == "1"
# Checks that need a server started with non-default settings carry one of these markers, and run
# only when `ISOLATION_MARK` names it (the make target that starts that server sets it). In the
# default run they skip by design, so the release gate is all three targets together.
SERVER_MARKS = {"permissive": "isolation-permissive", "default_isolation": "isolation-read-uncommitted"}
SERVER_MARK = os.environ.get("ISOLATION_MARK", "")

TARGETS = {
    "postgres": Target("postgres", POSTGRES_DSN, reference=True),
    "pgwire": Target("pgwire", PGWIRE_DSN, reference=False),
}


# Tests that leave a pooled IRIS connection unusable or holding a transaction, which is part of
# what they measure: the abandoned transactions of H3, the undelivered cancel, and the
# upsert-vs-delete race (the DBAPI driver's "<LIST ERROR>" desync stays on the connection).
# They run last, in this order, so no other check inherits their damage. `make isolation` also disables
# pytest-randomly, which would otherwise shuffle them back in.
RUN_LAST = ("test_h3_", "test_cancel_", "test_upsert_racing_a_delete")


def _order(item) -> tuple[int, str]:
    for rank, prefix in enumerate(RUN_LAST, start=1):
        if item.name.startswith(prefix):
            return rank, item.nodeid
    return 0, item.nodeid


def pytest_collection_modifyitems(config, items):
    here = Path(__file__).parent
    mine = [i for i in items if Path(str(i.fspath)).is_relative_to(here)]
    if mine:
        items[:] = [i for i in items if i not in mine] + sorted(mine, key=_order)
    skip = pytest.mark.skip(
        reason="set ISOLATION_SUITE=1 (make isolation) to run the isolation suite"
    )
    for item in items:
        if Path(str(item.fspath)).is_relative_to(here):
            item.add_marker(pytest.mark.isolation)
            if not ENABLED:
                item.add_marker(skip)
                continue
            for mark, target in SERVER_MARKS.items():
                if item.get_closest_marker(mark) and SERVER_MARK != mark:
                    item.add_marker(
                        pytest.mark.skip(reason=f"needs its own server: runs under make {target}")
                    )


@pytest.fixture(scope="session")
def reachable():
    """Fail loudly, once, if a target is down: a skipped isolation test reads as a pass."""
    for target in TARGETS.values():
        with psycopg.connect(target.dsn, autocommit=True, connect_timeout=10) as conn:
            conn.execute("select 1").fetchone()
    return True


@pytest.fixture(params=list(TARGETS), ids=list(TARGETS))
def target(request, reachable) -> Target:
    return TARGETS[request.param]


@pytest.fixture(scope="session")
def record():
    RESULTS.parent.mkdir(parents=True, exist_ok=True)

    def _record(**fields) -> None:
        fields.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%S"))
        with RESULTS.open("a") as f:
            f.write(json.dumps(fields, default=str) + "\n")

    return _record


class Expectations:
    """Record each observation and hold it to PostgreSQL's answer, or to IRIS's pin.

    Mismatches are collected, not raised, so one test reports every check it made; call
    ``done()`` last. ``postgres`` is PostgreSQL's documented answer: the reference run asserts it
    against the live server, which is what keeps a hand-written answer honest.
    """

    def __init__(self, target: Target, record, suite: str):
        self.target, self.record, self.suite = target, record, suite
        self.mismatches: list[str] = []

    def check(self, key: str, observed, postgres, **detail) -> None:
        from .known_differences import PINS, AnyOf

        observed = json.loads(json.dumps(observed, default=str))
        postgres = json.loads(json.dumps(postgres, default=str))
        pinned = PINS.get((self.suite, key))
        expected = postgres if self.target.reference or pinned is None else pinned
        if isinstance(expected, AnyOf):
            matched = any(observed == json.loads(json.dumps(o)) for o in expected.options)
            pinned = list(expected.options)
            expected = observed if matched else pinned
        self.record(
            suite=self.suite,
            target=self.target.name,
            key=key,
            observed=observed,
            postgres=postgres,
            pinned=pinned,
            **detail,
        )
        if observed != expected:
            label = "PostgreSQL's answer" if expected == postgres else "the pinned IRIS outcome"
            self.mismatches.append(
                f"[{self.target.name}] {self.suite}/{key}: observed {observed!r}, "
                f"expected {label} {expected!r}"
            )

    def done(self) -> None:
        assert not self.mismatches, "\n".join(self.mismatches)


@pytest.fixture
def expect(target, record, request):
    suite = request.module.__name__.rsplit(".", 1)[-1].removeprefix("test_")
    return Expectations(target, record, suite)
