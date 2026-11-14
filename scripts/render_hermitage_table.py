#!/usr/bin/env python3
"""Render the Hermitage-style table from the isolation suite's results.

    python scripts/render_hermitage_table.py [results.jsonl]

The suite (``make isolation``) appends one JSON record per Hermitage run to the results file
(default ``build/isolation-results.jsonl``). This script groups them by target, level and case
and prints one Markdown row per target and level, in the column order of Hermitage's README.

Cells: ✓ prevented, — anomaly, "✓ (timeout)" prevented only because a lock wait timed out,
"✓ (error)" prevented by a fast retryable error, "flaky" when runs of the same case disagree,
"err X" when the script could not run as written. Each row ends with how many runs it summarises.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

COLUMNS = ["G0", "G1a", "G1b", "G1c", "OTV", "PMP", "PMP-write", "P4", "G-single", "G2-item", "G2"]

_SYMBOL = {
    "prevented": "✓",
    "anomaly": "—",
    "prevented-by-timeout": "✓ (timeout)",
    "prevented-by-error": "✓ (error)",
}


def cell(verdicts: set[str]) -> str:
    if not verdicts:
        return ""
    if len(verdicts) > 1:
        return "flaky"
    (verdict,) = verdicts
    if verdict.startswith("error:"):
        return f"err {verdict.split(':', 1)[1]}"
    return _SYMBOL.get(verdict, verdict)


def render(records: list[dict]) -> str:
    verdicts: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    runs: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for record in records:
        if record.get("suite") != "hermitage":
            continue
        key = (record["target"], record["level"])
        verdicts[key][record["case"]].add(record["verdict"])
        runs[key][record["case"]] += 1

    header = ["Target", "Level", *COLUMNS, "Runs"]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for key in sorted(verdicts):
        counts = set(runs[key].values())
        per_case = (
            f"({min(counts)} runs)" if len(counts) == 1 else f"({min(counts)}-{max(counts)} runs)"
        )
        cells = [cell(verdicts[key].get(name, set())) for name in COLUMNS]
        lines.append("| " + " | ".join([key[0], key[1], *cells, per_case]) + " |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "build/isolation-results.jsonl")
    if not path.exists():
        print(f"no results at {path}; run `make isolation` first", file=sys.stderr)
        return 1
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    print(render(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
