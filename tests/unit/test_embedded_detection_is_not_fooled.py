"""`hasattr` cannot decide whether IRIS is embedded. Measured on both sides.

`_detect_iris_environment` asked `hasattr(iris, "sql") and hasattr(iris.sql,
"exec")`. On this host both answer True even though no IRIS is in the process,
so the executor takes the embedded branch — calling `iris.sql.exec` on a
`MagicMock`, which returns another `MagicMock` instead of raising. A wrong
execution path chosen silently.

Measured, host beside container (`python` on macOS vs `irispython` inside
`iris-pgwire-db`, IRIS 2026.1 CE):

    ============================  ==================  ========================
    probe                         host driver         embedded
    ============================  ==================  ========================
    hasattr(iris, "sql")          True                True
    "sql" in vars(iris)           False               True
    type(iris.sql)                MagicMock           iris.%SYS.Python.SQL
    type(iris.sql.exec)           MagicMock           builtin_function_or_method
    getattr(iris, "NOSUCH_XYZ")   MagicMock           iris.package
    ============================  ==================  ========================

The host's `iris` module carries a module-level `__getattr__` that logs a warning
and returns `MagicMock()` for anything it does not have, so `hasattr` is True
for every name. Embedded answers every name too, with an `iris.package`
placeholder.

Provenance, measured rather than assumed: the mock is **not** the stock
driver's. `iris_ep.py`, `_iris_ep/` and `iris_utils/` ship in
`iris-embedded-python-wrapper` (0.6.1 here, MIT), and
`_iris_ep._runtime_facade.install_unavailable_getattr` is what installs it.
Unpacked and imported in isolation, `intersystems-irispython` 5.3.2 and 5.4.0
contain no `MagicMock` at all and raise `AttributeError` for an unknown
attribute — but their `iris/__init__.py` does `from iris_ep import __getattr__`
`if os.path.exists(../iris_ep.py)`, so installing the wrapper alongside the
driver is enough. A machine with the driver alone does not behave this way.

Note that the `iris/__init__.py` actually on disk here is not that file: three
distributions claim the path and the wrapper installed last, so the installed
one begins `# Embedded Python wrapper for InterSystems IRIS` and opts in
unconditionally (`try: from iris_ep import __getattr__ / except ImportError:
pass`). Two routes to the same end state; the wheel's guarded one is quoted
above because it is what a driver-only install would run.

So on both sides `hasattr` is uninformative; only the two affirmative
properties below separate them:

  1. the real embedded module *declares* `sql` — it is in `vars(iris)`, where a
     name manufactured by `__getattr__` never lands;
  2. the real `iris.sql.exec` is not a test double.

Either alone is measured to be enough for today's two environments. Both are
asserted because each fails in a different direction: (1) breaks if a future
driver declares a real `sql` attribute, (2) breaks if a stand-in is assigned
directly, which is what our own test suite does.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from iris_pgwire.iris_executor import IRISExecutor

CONFIG = {
    "host": "localhost",
    "port": 1972,
    "namespace": "USER",
    "username": "SuperUser",
    "password": "SYS",
}


def detect_against(iris_module) -> bool:
    """Run detection against a given stand-in, without building an executor."""
    executor = IRISExecutor.__new__(IRISExecutor)
    executor.iris_config = dict(CONFIG)
    executor.embedded_mode = False
    result = executor._detect_iris_environment()
    assert result is executor.embedded_mode, "the return value and the flag disagree"
    return result


@pytest.fixture
def imported(monkeypatch):
    """Make `_import_iris` return a given stand-in."""

    def use(iris_module):
        monkeypatch.setattr(IRISExecutor, "_import_iris", lambda self: iris_module, raising=True)
        return detect_against(iris_module)

    return use


def _host_driver_shape() -> types.ModuleType:
    """This host's `iris` module, reproduced: a missing name becomes a MagicMock.

    Verbatim shape of `iris-embedded-python-wrapper`'s
    `_iris_ep._runtime_facade.install_unavailable_getattr`, which is what makes
    the host answer True.
    """
    module = types.ModuleType("iris")

    def __getattr__(name):
        if name.startswith("_"):
            raise AttributeError(name)
        return MagicMock()

    module.__getattr__ = __getattr__  # type: ignore[method-assign]
    return module


def _embedded_shape() -> types.ModuleType:
    """The measured embedded surface: `sql` declared, `exec` a real callable."""
    module = types.ModuleType("iris")
    module.sql = types.SimpleNamespace(exec=lambda statement, *args: iter(()))
    return module


class TestTheHostDriverIsNotMistakenForEmbedded:
    def test_a_module_that_manufactures_attributes_is_not_embedded(self, imported):
        """The bug, at the exact shape the installed driver has.

        `hasattr` is True for `sql` and for `sql.exec` here, so the old check
        said embedded. Taking that branch off-host calls `MagicMock.exec`,
        which answers every query with a `MagicMock` rather than failing.
        """
        module = _host_driver_shape()
        assert hasattr(module, "sql") and hasattr(module.sql, "exec"), (
            "this stand-in no longer reproduces the driver's surface, so the "
            "test below has stopped testing anything"
        )
        assert imported(module) is False

    def test_a_directly_assigned_test_double_is_not_embedded(self, imported):
        """The other direction: a double that *is* declared, and still a double."""
        module = types.ModuleType("iris")
        module.sql = MagicMock()
        assert "sql" in vars(module), "assigned, so declaration alone cannot reject it"
        assert imported(module) is False

    def test_no_iris_module_at_all_is_not_embedded(self, imported):
        assert imported(None) is False


class TestRealEmbeddedIsStillDetected:
    def test_a_declared_sql_with_a_real_exec_is_embedded(self, imported):
        assert imported(_embedded_shape()) is True

    def test_sql_declared_without_exec_is_not_embedded(self, imported):
        """An `iris.sql` that cannot execute is the external driver's shape."""
        module = types.ModuleType("iris")
        module.sql = types.SimpleNamespace()
        assert imported(module) is False
