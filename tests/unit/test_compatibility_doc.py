"""Spec 052 US8: the compatibility page says only what the isolation suite measures (FR-029, SC-009).

Every row of the page's tables names a suite check as `suite/key`, and the key must appear in that
suite module's source, so a row cannot be written without a check or outlive the one behind it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "POSTGRES_APP_COMPATIBILITY.md"
SUITE = ROOT / "tests" / "e2e" / "isolation"
CHECK = re.compile(r"`([a-z_]+)/([a-z0-9_/-]+)`")


def _table_rows(text: str) -> list[str]:
    rows = [line for line in text.splitlines() if line.startswith("|")]
    header_or_rule = re.compile(r"\|[\s|:-]+\||\|\s*(Behaviour|What|Client)\b.*")
    return [r for r in rows if not header_or_rule.fullmatch(r)]


def test_the_page_exists_and_is_linked_from_known_limitations():
    assert PAGE.exists()
    assert "docs/POSTGRES_APP_COMPATIBILITY.md" in (ROOT / "KNOWN_LIMITATIONS.md").read_text()


def test_every_row_names_a_check_that_exists():
    rows = _table_rows(PAGE.read_text())
    assert rows, "the page has no table rows"
    for row in rows:
        checks = CHECK.findall(row)
        assert checks, f"row names no suite check: {row}"
        for suite, key in checks:
            module = SUITE / f"test_{suite}.py"
            assert module.exists(), f"no suite module {module.name}: {row}"
            # The first path segment of the key is the literal the check passes to expect.check
            # (keys with a parameter are written as f-strings: f"rollback_recovers/{protocol}").
            stem = key.split("/")[0]
            source = module.read_text()
            assert re.search(
                r'f?"' + re.escape(stem) + r'[/"]', source
            ), f"check {suite}/{key} not found in {module.name}: {row}"
