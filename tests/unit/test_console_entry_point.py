"""The installed `iris-pgwire` command must actually start the server.

`[project.scripts]` named `iris_pgwire.server:main`, which is `async def`.
A console script calls its target and discards the return value, so the
installed command built a coroutine, never awaited it, and exited 0:

    $ iris-pgwire --help
    <coroutine object main at 0x106680ac0>
    sys:0: RuntimeWarning: coroutine 'main' was never awaited

Measured against the 1.7.3 wheel in a clean venv, so this is what `pip install
iris-pgwire` gives today. `python -m iris_pgwire.server` was unaffected — it
goes through the `asyncio.run` under `__main__` — which is why the packaged
path could stay broken while every development run worked.

The entry point is read from `pyproject.toml` rather than from installed
metadata so this fails in a source checkout, before a release is built.
"""

from __future__ import annotations

import importlib
import inspect
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def declared_scripts() -> dict[str, str]:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["project"].get("scripts", {})


def test_a_console_script_is_declared():
    assert declared_scripts(), "no console script to check"


@pytest.mark.parametrize("name", sorted(declared_scripts()))
def test_the_target_resolves_and_is_not_a_coroutine_function(name):
    """A coroutine function here is a no-op command, not a startup failure."""
    module_path, _, attribute = declared_scripts()[name].partition(":")
    module = importlib.import_module(module_path)
    target = getattr(module, attribute, None)

    assert target is not None, f"{name} points at a missing attribute {attribute!r}"
    assert callable(target), f"{name} points at something that cannot be called"
    assert not inspect.iscoroutinefunction(target), (
        f"{name} points at an async function, so the installed command would "
        f"build a coroutine and exit without running the server"
    )
