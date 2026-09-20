"""A stub for a missing dependency must not displace the real one.

tests/unit/test_base_fixture_builder.py installs a fake `iris_devtester`
package tree into `sys.modules` so it can import its module under test where
the real package is absent. Installed unconditionally, that stub outlives the
module that wanted it — collection happens before any test runs — and every
later consumer of the real package gets the fake. The container fixture in
tests/conftest.py is one: it needs `iris_devtester.IRISContainer`, does not
find it on the stub, and skips. A skipped test reads as a passing one, so the
isolation pins in tests/protocol/test_isolation_e2e.py and
tests/integration/test_in_iris_shared_transaction.py disappear from a
whole-suite run without anything announcing it.

This asserts the invariant rather than the mechanism: wherever the real
package is installed, it is the one in `sys.modules` by the time tests run.
Where it is genuinely absent the stub is still welcome, which is the
portability the stub was written for.
"""

from __future__ import annotations

import importlib.machinery
import sys

import pytest

# importlib.util.find_spec consults sys.modules first, which is the thing under
# suspicion here, so ask the filesystem finders directly.
REAL_IS_INSTALLED = importlib.machinery.PathFinder.find_spec("iris_devtester", None) is not None


@pytest.mark.unit
@pytest.mark.skipif(
    not REAL_IS_INSTALLED,
    reason="iris_devtester is genuinely absent here, so a stub standing in for it is correct",
)
def test_the_real_iris_devtester_is_the_one_in_sys_modules():
    module = sys.modules.get("iris_devtester")
    assert module is not None, "nothing imported iris_devtester, so there is nothing to check"
    assert getattr(module, "__file__", None) is not None, (
        "sys.modules['iris_devtester'] is a stub with no file — a test installed a fake "
        "package tree and left it there; every later consumer of the real package now "
        "silently skips"
    )


@pytest.mark.unit
@pytest.mark.skipif(
    not REAL_IS_INSTALLED,
    reason="iris_devtester is genuinely absent here, so a stub standing in for it is correct",
)
def test_iriscontainer_is_still_importable():
    """The specific name tests/conftest.py's container fixture needs.

    Pinned separately from the one above: a stub could grow a `__file__` and
    still be missing this, and it is this import failing that turns the
    container-backed pins into skips.
    """
    from iris_devtester import IRISContainer  # noqa: F401
