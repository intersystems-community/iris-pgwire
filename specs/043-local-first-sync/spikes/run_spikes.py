#!/usr/bin/env python3
"""Phase 0 spike driver for the local-first sync change feed.

Runs ObjectScript probes inside IRIS via `iris session` and reports a verdict per
spike. See README.md for what each spike proves and what its failure kills.

No third-party dependencies -- transport is `docker exec` (or a local `iris
session` when IRIS_SESSION is set), matching the compose healthcheck.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SPIKE_DIR = Path(__file__).parent
CONTAINER = os.environ.get("IRIS_CONTAINER", "iris-pgwire-db")
USE_SESSION = bool(os.environ.get("IRIS_SESSION"))
KEEP = bool(os.environ.get("SPIKE_KEEP"))
ROWS = os.environ.get("SPIKE_ROWS", "1000")

VERDICT_RE = re.compile(r"^(Q\d) VERDICT: (PASS|FAIL|INCONCLUSIVE)\b", re.MULTILINE)


def run_objectscript(code: str, namespace: str = "USER", timeout: int = 300) -> str:
    """Execute ObjectScript in IRIS, returning combined stdout/stderr.

    The code is fed on stdin to an `iris session` terminal. A trailing HALT is
    appended so the session exits rather than dropping to an interactive prompt.
    """
    script = code.rstrip() + "\n HALT\n"

    if USE_SESSION:
        cmd = ["iris", "session", "IRIS", "-U", namespace]
    else:
        cmd = ["docker", "exec", "-i", CONTAINER, "iris", "session", "IRIS", "-U", namespace]

    try:
        proc = subprocess.run(
            cmd,
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return f"SPIKE_DRIVER_ERROR: transport not available ({exc})"
    except subprocess.TimeoutExpired:
        return f"SPIKE_DRIVER_ERROR: timed out after {timeout}s"

    return (proc.stdout or "") + (proc.stderr or "")


def load(name: str) -> str:
    """Read a probe file and substitute driver-controlled parameters."""
    text = (SPIKE_DIR / name).read_text()
    return text.replace("%%ROWS%%", ROWS).replace("%%KEEP%%", "1" if KEEP else "0")


def preamble() -> None:
    print("=" * 72)
    print("Phase 0 spikes -- local-first sync change feed")
    print("=" * 72)
    transport = "iris session (local)" if USE_SESSION else f"docker exec {CONTAINER}"
    print(f"Transport : {transport}")
    out = run_objectscript(' write "IRIS_VERSION:",$ZV,!', namespace="%SYS", timeout=60)
    version = next(
        (ln.split("IRIS_VERSION:", 1)[1].strip() for ln in out.splitlines() if "IRIS_VERSION:" in ln),
        None,
    )
    if version:
        print(f"IRIS      : {version}")
    else:
        print("IRIS      : UNREACHABLE -- check the container is running and named correctly")
        print()
        print(out.strip()[:800])
        sys.exit(2)
    print(f"Rows (Q3) : {ROWS}")
    print(f"Teardown  : {'skipped (SPIKE_KEEP set)' if KEEP else 'enabled'}")
    print()


SPIKES = {
    "q1": ("q1_journal_resume.cos", "%SYS", "Q1 -- resumable journal tailing"),
    "q2": ("q2_storage_resolution.cos", "USER", "Q2 -- global resolution for DDL tables"),
    "q3": ("q3_trigger_overhead.cos", "USER", "Q3 -- outbox trigger write-path cost"),
}


def main(argv: list[str]) -> int:
    requested = [a.lower() for a in argv[1:]] or list(SPIKES)
    unknown = [r for r in requested if r not in SPIKES]
    if unknown:
        print(f"Unknown spike(s): {', '.join(unknown)}. Choose from: {', '.join(SPIKES)}")
        return 2

    preamble()

    verdicts: dict[str, str] = {}
    for key in requested:
        filename, namespace, title = SPIKES[key]
        print("-" * 72)
        print(title)
        print("-" * 72)
        output = run_objectscript(load(filename), namespace=namespace)
        print(output.strip())
        print()

        found = VERDICT_RE.search(output)
        if found:
            verdicts[key] = found.group(2)
        elif "SPIKE_DRIVER_ERROR" in output:
            verdicts[key] = "INCONCLUSIVE"
        else:
            verdicts[key] = "INCONCLUSIVE"
            print(f"({key.upper()} emitted no verdict line -- treating as INCONCLUSIVE)")
            print()

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for key in requested:
        print(f"  {key.upper()}: {verdicts[key]}")
    print()
    print("Record these in specs/043-local-first-sync/research.md (section 7 + risk register),")
    print("noting the IRIS version printed above.")

    if any(v == "FAIL" for v in verdicts.values()):
        return 1
    if any(v == "INCONCLUSIVE" for v in verdicts.values()):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
