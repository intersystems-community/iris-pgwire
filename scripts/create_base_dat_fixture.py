#!/usr/bin/env python3
"""Create base DAT fixture for tests using iris-devtester."""

import sys
from pathlib import Path

from iris_devtester import IRISContainer

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from iris_pgwire.testing.base_fixture_builder import ensure_base_fixture


def main() -> int:
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "dat"

    with IRISContainer.community() as iris:
        path = ensure_base_fixture(container=iris, fixture_root=fixture_root)

    print(f"Base fixture ready: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
