"""Unit tests for the isolation suite's verdicts and its table renderer.

The suite in tests/e2e/isolation plays Hermitage's two-session scripts against PGWire and
against PostgreSQL 16, then turns each run's trace into a verdict. These tests pin the verdict
rules on hand-built traces, so a wrong rule cannot hide behind a live database that happens to
agree with it. The traces use the values Hermitage's postgres.md prints for PostgreSQL, and the
values MySQL's "read uncommitted" prints in mysql.md for the anomaly side.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from tests.e2e.isolation.cases import CASES, Outcome, StepResult, verdict_for

ROOT = Path(__file__).resolve().parents[2]


def _render_module():
    spec = importlib.util.spec_from_file_location(
        "render_hermitage_table", ROOT / "scripts" / "render_hermitage_table.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ok(rows=None, elapsed=0.01, blocked=False, started=0.0, finished=0.0):
    outcome = Outcome(
        rows=rows, sqlstate=None, message=None, elapsed=elapsed, started=started, finished=finished
    )
    return StepResult(outcome, blocked)


def err(sqlstate, elapsed=10.0):
    return StepResult(Outcome(rows=None, sqlstate=sqlstate, message="x", elapsed=elapsed), True)


def trace_for(case_name, overrides):
    """Every labelled step succeeds with no rows, one second apart in script order.

    Overrides replace whole steps; an overridden step keeps the script-order time unless the
    override gives its own.
    """
    case = CASES[case_name]
    trace = {
        step.label: ok(started=float(i), finished=i + 0.5)
        for i, step in enumerate(case.steps)
        if step.label
    }
    for label, result in overrides.items():
        if result.outcome.started == 0.0 and label in trace:
            when = trace[label].outcome
            result = StepResult(
                replace(result.outcome, started=when.started, finished=when.finished),
                result.blocked,
            )
        trace[label] = result
    return trace


class TestDirtyReadVerdicts:
    def test_g1a_reading_the_aborted_value_is_the_anomaly(self):
        trace = trace_for("G1a", {"t2_read_1": ok([(1, 101), (2, 20)])})
        assert verdict_for("G1a", trace) == "anomaly"

    def test_g1a_postgres_output_is_prevented(self):
        rows = [(1, 10), (2, 20)]
        trace = trace_for("G1a", {"t2_read_1": ok(rows), "t2_read_2": ok(rows)})
        assert verdict_for("G1a", trace) == "prevented"

    def test_a_read_that_timed_out_prevented_it_by_timeout(self):
        trace = trace_for("G1a", {"t2_read_1": err("40001", elapsed=10.02)})
        assert verdict_for("G1a", trace) == "prevented-by-timeout"

    def test_a_fast_40001_is_not_a_timeout(self):
        trace = trace_for("G1a", {"t2_read_1": err("40001", elapsed=0.05)})
        assert verdict_for("G1a", trace) == "prevented-by-error"

    def test_an_unrelated_error_is_reported_as_an_error(self):
        trace = trace_for("G1a", {"t2_read_1": err("42601", elapsed=0.01)})
        assert verdict_for("G1a", trace) == "error:42601"

    def test_g1c_needs_both_halves_of_the_cycle(self):
        one_half = trace_for("G1c", {"t1_read": ok([(2, 22)]), "t2_read": ok([(1, 10)])})
        cycle = trace_for("G1c", {"t1_read": ok([(2, 22)]), "t2_read": ok([(1, 11)])})
        assert verdict_for("G1c", one_half) == "prevented"
        assert verdict_for("G1c", cycle) == "anomaly"

    def test_otv_as_mysql_read_uncommitted_prints_it(self):
        # mysql.md, "read uncommitted": T3 sees 1 => 12 before T2 has committed.
        trace = trace_for("OTV", {"t3_read_1": ok([(1, 12)]), "t3_read_2": ok([(2, 18)])})
        assert verdict_for("OTV", trace) == "anomaly"

    def test_otv_value_read_after_the_writer_committed_is_not_dirty(self):
        # IRIS at READ COMMITTED: the read waits on T2's lock and returns 18 once T2 commits.
        trace = trace_for(
            "OTV",
            {
                "t3_read_1": err("40001", elapsed=10.0),
                "t3_read_2": ok([(2, 18)], started=20.0, finished=21.0, blocked=True),
                "t2_commit": ok(started=21.0, finished=21.0),
            },
        )
        assert verdict_for("OTV", trace) == "prevented-by-timeout"

    def test_otv_value_read_before_the_writer_committed_is_dirty(self):
        trace = trace_for(
            "OTV",
            {
                "t3_read_2": ok([(2, 18)], started=20.0, finished=20.1),
                "t2_commit": ok(started=21.0, finished=21.0),
            },
        )
        assert verdict_for("OTV", trace) == "anomaly"

    def test_g1c_half_read_after_commit_does_not_close_the_cycle(self):
        trace = trace_for(
            "G1c",
            {
                "t1_read": ok([(2, 22)], started=1.0, finished=1.1),
                "t2_read": ok([(1, 11)], started=1.2, finished=12.0),
                "t1_commit": ok(started=11.0, finished=11.0),
                "t2_commit": ok(started=13.0, finished=13.0),
            },
        )
        assert verdict_for("G1c", trace) == "prevented"

    def test_otv_as_postgres_prints_it(self):
        trace = trace_for("OTV", {"t3_read_1": ok([(1, 11)]), "t3_read_2": ok([(2, 19)])})
        assert verdict_for("OTV", trace) == "prevented"


class TestWriteVerdicts:
    def test_g0_mixed_final_state_is_the_anomaly(self):
        trace = trace_for("G0", {"final": ok([(1, 12), (2, 21)])})
        assert verdict_for("G0", trace) == "anomaly"

    def test_g0_postgres_final_state_is_prevented(self):
        trace = trace_for("G0", {"final": ok([(1, 12), (2, 22)])})
        assert verdict_for("G0", trace) == "prevented"

    def test_p4_both_commits_succeeding_is_the_lost_update(self):
        trace = trace_for("P4", {})
        assert verdict_for("P4", trace) == "anomaly"

    def test_p4_second_writer_failing_prevents_it(self):
        trace = trace_for("P4", {"t2_update": err("40001", elapsed=10.0)})
        assert verdict_for("P4", trace) == "prevented-by-timeout"

    def test_g2_item_both_commits_is_write_skew(self):
        assert verdict_for("G2-item", trace_for("G2-item", {})) == "anomaly"


class TestPredicateVerdicts:
    def test_pmp_seeing_the_new_row_is_the_anomaly(self):
        trace = trace_for("PMP", {"t1_read_2": ok([(3, 30)])})
        assert verdict_for("PMP", trace) == "anomaly"

    def test_pmp_write_postgres_output_is_the_anomaly(self):
        trace = trace_for("PMP-write", {"t2_read": ok([(1, 20)])})
        assert verdict_for("PMP-write", trace) == "anomaly"

    def test_g_single_read_skew(self):
        trace = trace_for("G-single", {"t1_read_1": ok([(1, 10)]), "t1_read_2": ok([(2, 18)])})
        assert verdict_for("G-single", trace) == "anomaly"


class TestPublishedExpectations:
    """The cases carry postgres.md's printed outputs; spot-check they were copied right."""

    def test_g0_published_final_state(self):
        final = next(s for s in CASES["G0"].steps if s.label == "final")
        assert final.published_rows == [(1, 12), (2, 22)]

    def test_g0_second_update_blocks_in_postgres(self):
        blocked = [s for s in CASES["G0"].steps if s.published_blocks]
        assert [s.sql for s in blocked] == ["update test set value = 12 where id = 1"]

    def test_every_case_has_the_readme_verdict_for_read_committed(self):
        readme = {
            "G0": "prevented",
            "G1a": "prevented",
            "G1b": "prevented",
            "G1c": "prevented",
            "OTV": "prevented",
            "PMP": "anomaly",
            "PMP-write": "anomaly",
            "P4": "anomaly",
            "G-single": "anomaly",
            "G2-item": "anomaly",
            "G2": "anomaly",
        }
        assert {name: case.postgres_read_committed for name, case in CASES.items()} == readme


class TestRenderer:
    def records(self):
        return [
            {
                "suite": "hermitage",
                "target": "postgres",
                "level": "read committed",
                "case": "G1a",
                "verdict": "prevented",
            },
            {
                "suite": "hermitage",
                "target": "pgwire",
                "level": "read committed",
                "case": "G1a",
                "verdict": "prevented-by-timeout",
            },
            {
                "suite": "hermitage",
                "target": "pgwire",
                "level": "read committed",
                "case": "G1a",
                "verdict": "anomaly",
            },
            {
                "suite": "hermitage",
                "target": "pgwire",
                "level": "read uncommitted",
                "case": "G1a",
                "verdict": "anomaly",
            },
            {
                "suite": "hermitage",
                "target": "pgwire",
                "level": "read uncommitted",
                "case": "G1a",
                "verdict": "anomaly",
            },
        ]

    def test_cells(self):
        render = _render_module()
        assert render.cell({"prevented"}) == "✓"
        assert render.cell({"anomaly"}) == "—"
        assert render.cell({"prevented-by-timeout"}) == "✓ (timeout)"
        assert render.cell({"anomaly", "prevented-by-timeout"}) == "flaky"

    def test_table_has_one_row_per_target_and_level(self):
        table = _render_module().render(self.records())
        lines = table.splitlines()
        assert lines[0].startswith("| Target")
        body = [line for line in lines[2:] if line.strip()]
        assert len(body) == 3
        pgwire_rc = next(line for line in body if "pgwire" in line and "read committed" in line)
        assert "flaky" in pgwire_rc

    def test_run_counts_are_shown(self):
        table = _render_module().render(self.records())
        pgwire_ru = next(
            line for line in table.splitlines() if "pgwire" in line and "read uncommitted" in line
        )
        assert "(2 runs)" in pgwire_ru

    @pytest.mark.parametrize("missing", ["G0", "G2"])
    def test_an_unrun_case_is_blank(self, missing):
        lines = _render_module().render(self.records()).splitlines()
        header = [c.strip() for c in lines[0].strip("|").split("|")]
        row = next(line for line in lines if "pgwire" in line and "read uncommitted" in line)
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert cells[header.index(missing)] == ""
        assert cells[header.index("G1a")] == "—"
