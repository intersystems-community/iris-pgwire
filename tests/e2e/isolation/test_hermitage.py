"""E1: Hermitage's anomaly cases at READ UNCOMMITTED and READ COMMITTED.

Each case runs ``ISOLATION_REPEATS`` times per level, alternating the order of the two levels
from one run to the next, because IRIS's READ COMMITTED has been seen to give different answers
to the same script. Every run's verdict and trace go to the results file, from which
``scripts/render_hermitage_table.py`` draws the table.

On PostgreSQL the test also checks each step against what postgres.md prints, so the reference
server is held to the published document. PostgreSQL runs READ UNCOMMITTED as READ COMMITTED,
so both levels expect README's read committed verdict.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from .cases import CASES, verdict_for
from .harness import open_sessions, play, run_statement, with_table
from .known_differences import HERMITAGE

LEVELS = ("read uncommitted", "read committed")
REPEATS = int(os.environ.get("ISOLATION_REPEATS", "5"))
TABLE = "hermitage_test"


def _setup(target) -> None:
    with target.connect() as conn:
        for sql in (
            f"drop table if exists {TABLE}",
            f"create table {TABLE} (id int primary key, value int)",
            f"insert into {TABLE} (id, value) values (1, 10)",
            f"insert into {TABLE} (id, value) values (2, 20)",
        ):
            outcome = run_statement(conn, sql)
            assert outcome.ok, f"setup failed on {target.name}: {sql}: {outcome.message}"


def play_case(target, case, level):
    _setup(target)
    sessions = open_sessions(target, case.sessions)
    try:
        opening = []
        for name in case.sessions:
            for sql in ("begin", f"set transaction isolation level {level}"):
                outcome = run_statement(sessions[name].conn, sql)
                assert outcome.ok, f"{name} could not open at {level}: {outcome.message}"
                opening.append(sql)
        steps = [replace(s, sql=with_table(s.sql, TABLE)) for s in case.steps]
        played = play(sessions, steps)
    finally:
        for session in sessions.values():
            session.close()
    trace = {}
    for index, p in enumerate(played):
        trace[p.step.label or f"#{index}"] = p.result
    return played, trace


def _trace_record(played):
    return [
        {
            "session": p.step.session,
            "sql": p.step.sql,
            "label": p.step.label,
            "blocked": p.result.blocked,
            "rows": p.result.outcome.rows,
            "sqlstate": p.result.outcome.sqlstate,
            "message": p.result.outcome.message,
            "status": p.result.outcome.status,
            "elapsed": round(p.result.outcome.elapsed, 3),
            "published_rows": p.step.published_rows,
            "published_blocks": p.step.published_blocks,
        }
        for p in played
    ]


def _check_against_postgres_md(played, case_name, level) -> list[str]:
    problems = []
    for p in played:
        outcome = p.result.outcome
        if not outcome.ok:
            problems.append(f"{p.step.sql!r} failed: {outcome.sqlstate} {outcome.message}")
        if p.step.published_rows is not None and sorted(outcome.rows or []) != sorted(
            p.step.published_rows
        ):
            problems.append(
                f"{p.step.sql!r}: postgres.md prints {p.step.published_rows}, got {outcome.rows}"
            )
        if p.step.published_blocks and not p.result.blocked:
            problems.append(f"{p.step.sql!r}: postgres.md says BLOCKS; it did not")
    return [f"{case_name} at {level}: {x}" for x in problems]


@pytest.mark.parametrize("case_name", list(CASES))
def test_hermitage_case(target, case_name, record):
    seen: dict[str, list[str]] = {level: [] for level in LEVELS}
    reference_problems: list[str] = []

    for run in range(REPEATS):
        order = LEVELS if run % 2 == 0 else tuple(reversed(LEVELS))
        for level in order:
            played, trace = play_case(target, CASES[case_name], level)
            verdict = verdict_for(case_name, trace)
            seen[level].append(verdict)
            record(
                suite="hermitage",
                target=target.name,
                level=level,
                case=case_name,
                run=run,
                verdict=verdict,
                steps=_trace_record(played),
            )
            if target.reference:
                reference_problems += _check_against_postgres_md(played, case_name, level)

    assert not reference_problems, "\n".join(reference_problems)

    mismatches = []
    for level in LEVELS:
        expected = {CASES[case_name].postgres_read_committed}
        if not target.reference:
            expected = HERMITAGE.get((case_name, level), expected)
        if set(seen[level]) != expected:
            mismatches.append(
                f"{case_name} at {level} on {target.name}: verdicts {seen[level]}, "
                f"expected {sorted(expected)}"
            )
    assert not mismatches, "\n".join(mismatches)
