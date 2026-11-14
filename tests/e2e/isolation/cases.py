"""Hermitage's test cases, and the rule that turns one run's trace into a verdict.

The scripts are Hermitage's PostgreSQL scripts (https://github.com/ept/hermitage, postgres.md),
copied statement for statement. Each session opens with ``begin; set transaction isolation level
<level>`` exactly as Hermitage's do; the runner adds those two statements, because the suite plays
every case at more than one level.

Two kinds of expectation live here, and neither comes from IRIS:

* ``published_rows`` and ``published_blocks`` are what postgres.md prints for PostgreSQL at the
  step. The suite checks the live PostgreSQL 16 run against them, which is what makes the
  reference server a reference.
* ``postgres_read_committed`` is the verdict Hermitage's README table gives PostgreSQL "read
  committed" for the anomaly. G2-item and G2 have no read committed script in postgres.md; the
  repeatable read script is played instead, and README's "—" for read committed is the answer.

The verdict rule (``verdict_for``) is the only interpretation added on top. A case's ``anomaly``
predicate says whether the trace shows the anomaly; it is written from the anomaly's definition
in Hermitage's README and mysql.md, which prints the anomalous outputs at "read uncommitted".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

# A 40001 that arrives after this long is IRIS's lock timeout (10 s by default), not a conflict
# detected on the spot.
TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Outcome:
    """What one statement did: rows (None if it returned none or failed), or an error."""

    rows: list[tuple] | None
    sqlstate: str | None
    message: str | None
    elapsed: float
    status: str | None = None  # the command tag, e.g. "COMMIT" or "ROLLBACK"
    rowcount: int | None = None
    # time.monotonic() when the statement was sent and when its answer arrived, so a read can be
    # placed before or after another session's COMMIT.
    started: float = 0.0
    finished: float = 0.0

    @property
    def ok(self) -> bool:
        return self.sqlstate is None


@dataclass(frozen=True)
class StepResult:
    outcome: Outcome
    blocked: bool  # still running when the runner moved on to the next step


@dataclass(frozen=True)
class Step:
    session: str
    sql: str
    label: str | None = None
    published_rows: list[tuple] | None = None
    published_blocks: bool = False


Trace = Mapping[str, StepResult]


@dataclass(frozen=True)
class Case:
    name: str
    title: str
    sessions: tuple[str, ...]
    steps: tuple[Step, ...]
    postgres_read_committed: str  # "prevented" or "anomaly", from Hermitage's README table
    anomaly: Callable[[Trace], bool]


def _rows(trace: Trace, label: str) -> set[tuple]:
    result = trace.get(label)
    if result is None or not result.outcome.ok or result.outcome.rows is None:
        return set()
    return {tuple(r) for r in result.outcome.rows}


def _dirty(trace: Trace, read: str, value: tuple, writer_end: str) -> bool:
    """`read` returned `value` before the writer's COMMIT or ABORT (`writer_end`) was sent.

    A lock-based READ COMMITTED returns the writer's value too, but only once the writer has
    committed and released the row; that is a committed read, and the order tells them apart.
    """
    if value not in _rows(trace, read):
        return False
    end = trace.get(writer_end)
    if end is None or not end.outcome.ok:
        return True
    return trace[read].outcome.finished < end.outcome.started


def _succeeded(trace: Trace, *labels: str) -> bool:
    """Every step ran without error, and no COMMIT among them was turned into a ROLLBACK."""
    for label in labels:
        result = trace.get(label)
        if result is None or not result.outcome.ok:
            return False
        if result.outcome.status == "ROLLBACK":
            return False
    return True


def _g0(trace: Trace) -> bool:
    final = trace.get("final")
    if final is None or not final.outcome.ok:
        return False
    return _rows(trace, "final") not in ({(1, 12), (2, 22)}, {(1, 11), (2, 21)})


ALL_ROWS = [(1, 10), (2, 20)]

# Hermitage writes `value % 3 = 0`. PGWire does not translate `%` (IRIS reports SQLCODE -14, which
# reaches the client as 08000), so both targets are given the same predicate as `mod()`. The
# meaning is identical; the deviation is recorded in the investigation's Results section.
MOD3 = "select * from test where mod(value, 3) = 0"

CASES: dict[str, Case] = {
    case.name: case
    for case in (
        Case(
            "G0",
            "Write Cycles (dirty writes)",
            ("T1", "T2"),
            (
                Step("T1", "update test set value = 11 where id = 1"),
                Step("T2", "update test set value = 12 where id = 1", published_blocks=True),
                Step("T1", "update test set value = 21 where id = 2"),
                Step("T1", "commit"),
                Step("T1", "select * from test", "t1_read", [(1, 11), (2, 21)]),
                Step("T2", "update test set value = 22 where id = 2"),
                Step("T2", "commit"),
                Step("T1", "select * from test", "final", [(1, 12), (2, 22)]),
            ),
            "prevented",
            _g0,
        ),
        Case(
            "G1a",
            "Aborted Reads (dirty reads, cascaded aborts)",
            ("T1", "T2"),
            (
                Step("T1", "update test set value = 101 where id = 1"),
                Step("T2", "select * from test", "t2_read_1", ALL_ROWS),
                Step("T1", "abort"),
                Step("T2", "select * from test", "t2_read_2", ALL_ROWS),
                Step("T2", "commit"),
            ),
            "prevented",
            lambda t: (1, 101) in _rows(t, "t2_read_1") | _rows(t, "t2_read_2"),
        ),
        Case(
            "G1b",
            "Intermediate Reads (dirty reads)",
            ("T1", "T2"),
            (
                Step("T1", "update test set value = 101 where id = 1"),
                Step("T2", "select * from test", "t2_read_1", ALL_ROWS),
                Step("T1", "update test set value = 11 where id = 1"),
                Step("T1", "commit"),
                Step("T2", "select * from test", "t2_read_2", [(1, 11), (2, 20)]),
                Step("T2", "commit"),
            ),
            "prevented",
            lambda t: (1, 101) in _rows(t, "t2_read_1") | _rows(t, "t2_read_2"),
        ),
        Case(
            "G1c",
            "Circular Information Flow (dirty reads)",
            ("T1", "T2"),
            (
                Step("T1", "update test set value = 11 where id = 1"),
                Step("T2", "update test set value = 22 where id = 2"),
                Step("T1", "select * from test where id = 2", "t1_read", [(2, 20)]),
                Step("T2", "select * from test where id = 1", "t2_read", [(1, 10)]),
                Step("T1", "commit", "t1_commit"),
                Step("T2", "commit", "t2_commit"),
            ),
            "prevented",
            lambda t: _dirty(t, "t1_read", (2, 22), "t2_commit")
            and _dirty(t, "t2_read", (1, 11), "t1_commit"),
        ),
        Case(
            "OTV",
            "Observed Transaction Vanishes",
            ("T1", "T2", "T3"),
            (
                Step("T1", "update test set value = 11 where id = 1"),
                Step("T1", "update test set value = 19 where id = 2"),
                Step("T2", "update test set value = 12 where id = 1", published_blocks=True),
                Step("T1", "commit"),
                Step("T3", "select * from test where id = 1", "t3_read_1", [(1, 11)]),
                Step("T2", "update test set value = 18 where id = 2"),
                Step("T3", "select * from test where id = 2", "t3_read_2", [(2, 19)]),
                Step("T2", "commit", "t2_commit"),
                Step("T3", "select * from test where id = 2", "t3_read_3", [(2, 18)]),
                Step("T3", "select * from test where id = 1", "t3_read_4", [(1, 12)]),
                Step("T3", "commit"),
            ),
            "prevented",
            # mysql.md, "read uncommitted": T3 sees T2's writes before T2 commits.
            lambda t: _dirty(t, "t3_read_1", (1, 12), "t2_commit")
            or _dirty(t, "t3_read_2", (2, 18), "t2_commit"),
        ),
        Case(
            "PMP",
            "Predicate-Many-Preceders",
            ("T1", "T2"),
            (
                Step("T1", "select * from test where value = 30", "t1_read_1", []),
                Step("T2", "insert into test (id, value) values(3, 30)"),
                Step("T2", "commit"),
                Step("T1", MOD3, "t1_read_2", [(3, 30)]),
                Step("T1", "commit"),
            ),
            "anomaly",
            lambda t: (3, 30) in _rows(t, "t1_read_2"),
        ),
        Case(
            "PMP-write",
            "Predicate-Many-Preceders, write predicate",
            ("T1", "T2"),
            (
                Step("T1", "update test set value = value + 10"),
                Step("T2", "delete from test where value = 20", "t2_delete", published_blocks=True),
                Step("T1", "commit"),
                Step("T2", "select * from test where value = 20", "t2_read", [(1, 20)]),
                Step("T2", "commit"),
            ),
            "anomaly",
            lambda t: (1, 20) in _rows(t, "t2_read"),
        ),
        Case(
            "P4",
            "Lost Update",
            ("T1", "T2"),
            (
                Step("T1", "select * from test where id = 1", "t1_read", [(1, 10)]),
                Step("T2", "select * from test where id = 1", "t2_read", [(1, 10)]),
                Step("T1", "update test set value = 11 where id = 1", "t1_update"),
                Step(
                    "T2",
                    "update test set value = 11 where id = 1",
                    "t2_update",
                    published_blocks=True,
                ),
                Step("T1", "commit", "t1_commit"),
                Step("T2", "commit", "t2_commit"),
            ),
            "anomaly",
            lambda t: _succeeded(t, "t1_update", "t2_update", "t1_commit", "t2_commit"),
        ),
        Case(
            "G-single",
            "Single Anti-dependency Cycles (read skew)",
            ("T1", "T2"),
            (
                Step("T1", "select * from test where id = 1", "t1_read_1", [(1, 10)]),
                Step("T2", "select * from test where id = 1"),
                Step("T2", "select * from test where id = 2"),
                Step("T2", "update test set value = 12 where id = 1"),
                Step("T2", "update test set value = 18 where id = 2"),
                Step("T2", "commit"),
                Step("T1", "select * from test where id = 2", "t1_read_2", [(2, 18)]),
                Step("T1", "commit"),
            ),
            "anomaly",
            lambda t: (1, 10) in _rows(t, "t1_read_1") and (2, 18) in _rows(t, "t1_read_2"),
        ),
        Case(
            "G2-item",
            "Item Anti-dependency Cycles (write skew on disjoint read)",
            ("T1", "T2"),
            (
                Step("T1", "select * from test where id in (1,2)", "t1_read", ALL_ROWS),
                Step("T2", "select * from test where id in (1,2)", "t2_read", ALL_ROWS),
                Step("T1", "update test set value = 11 where id = 1", "t1_update"),
                Step("T2", "update test set value = 21 where id = 2", "t2_update"),
                Step("T1", "commit", "t1_commit"),
                Step("T2", "commit", "t2_commit"),
            ),
            "anomaly",
            lambda t: _succeeded(t, "t1_update", "t2_update", "t1_commit", "t2_commit"),
        ),
        Case(
            "G2",
            "Anti-Dependency Cycles (write skew on predicate read)",
            ("T1", "T2"),
            (
                Step("T1", MOD3, "t1_read", []),
                Step("T2", MOD3, "t2_read", []),
                Step("T1", "insert into test (id, value) values(3, 30)", "t1_insert"),
                Step("T2", "insert into test (id, value) values(4, 42)", "t2_insert"),
                Step("T1", "commit", "t1_commit"),
                Step("T2", "commit", "t2_commit"),
                Step("T1", MOD3, "final", [(3, 30), (4, 42)]),
            ),
            "anomaly",
            lambda t: _succeeded(t, "t1_insert", "t2_insert", "t1_commit", "t2_commit"),
        ),
    )
}

RETRYABLE = {"40001", "40P01", "55P03"}


def verdict_for(case_name: str, trace: Trace) -> str:
    """One run's verdict: anomaly, prevented, prevented-by-timeout, prevented-by-error, error:X.

    The anomaly is checked first: an anomaly seen before some later step failed still happened.
    A run with no anomaly and no error prevented it. A run with no anomaly whose only errors are
    retryable conflicts prevented it by refusing work; "by timeout" when one of them took IRIS's
    lock timeout to arrive. Any other error means the script did not run as written, and the
    verdict names the SQLSTATE so the cause is visible in the table.
    """
    if CASES[case_name].anomaly(trace):
        return "anomaly"
    errors = [r.outcome for r in trace.values() if not r.outcome.ok]
    if not errors:
        return "prevented"
    other = [e for e in errors if e.sqlstate not in RETRYABLE]
    if other:
        return f"error:{other[0].sqlstate}"
    if any(e.elapsed >= TIMEOUT_SECONDS for e in errors):
        return "prevented-by-timeout"
    return "prevented-by-error"
