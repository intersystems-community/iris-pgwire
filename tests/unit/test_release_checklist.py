"""Spec 052 US8 / FR-028: a release needs the isolation suite, all three targets, on a fresh server."""

from __future__ import annotations

from pathlib import Path

CHECKLIST = (Path(__file__).resolve().parents[2] / "docs" / "RELEASE_CHECKLIST.md").read_text()


def test_the_checklist_runs_the_isolation_suite_targets():
    for target in (
        "make isolation",
        "make isolation-permissive",
        "make isolation-read-uncommitted",
    ):
        assert f"`{target}`" in CHECKLIST, target


def test_the_checklist_regenerates_the_hermitage_table():
    assert "make isolation-table" in CHECKLIST


def test_the_checklist_requires_a_fresh_server_and_one_server_at_a_time():
    assert "fresh server" in CHECKLIST
    assert "5442" in CHECKLIST
