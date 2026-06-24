"""
Unit tests for iris_pgwire/quality/__init__.py.

The module does conditional imports of four validator classes and one
combined validator. We verify that each name is exposed in __all__,
that the imports succeed (or degrade gracefully to None), and that
__all__ is declared correctly.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_quality_init(available: dict[str, bool]) -> ModuleType:
    """
    Reload quality/__init__.py with selective import failures.

    `available` maps short submodule name (e.g. "package_metadata_validator")
    to True (importable) / False (raises ImportError).
    """
    submodules = [
        "package_metadata_validator",
        "code_quality_validator",
        "security_validator",
        "documentation_validator",
        "validator",
    ]

    # Remove stale cache
    for key in list(sys.modules.keys()):
        if "iris_pgwire.quality" in key:
            del sys.modules[key]

    patches: dict[str, ModuleType | None] = {}
    for sub in submodules:
        full_name = f"iris_pgwire.quality.{sub}"
        if available.get(sub, True):
            fake = MagicMock()
            # Provide the expected class attribute
            cls_name_map = {
                "package_metadata_validator": "PackageMetadataValidator",
                "code_quality_validator": "CodeQualityValidator",
                "security_validator": "SecurityValidator",
                "documentation_validator": "DocumentationValidator",
                "validator": "PackageQualityValidator",
            }
            setattr(fake, cls_name_map[sub], MagicMock())
            patches[full_name] = fake
        else:
            patches[full_name] = None  # None triggers ImportError

    import importlib
    original = {}
    for full_name, mod in patches.items():
        original[full_name] = sys.modules.get(full_name, _SENTINEL)
        sys.modules[full_name] = mod  # type: ignore

    try:
        import iris_pgwire.quality as quality_pkg
        importlib.reload(quality_pkg)
        return quality_pkg
    finally:
        # Restore
        for full_name, old in original.items():
            if old is _SENTINEL:
                sys.modules.pop(full_name, None)
            else:
                sys.modules[full_name] = old  # type: ignore


_SENTINEL = object()


# ---------------------------------------------------------------------------
# Tests: all modules available
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_quality_modules():
    """Save and restore iris_pgwire.quality sys.modules entries after each test."""
    saved = {k: v for k, v in sys.modules.items() if "iris_pgwire.quality" in k}
    yield
    for k in list(sys.modules.keys()):
        if "iris_pgwire.quality" in k:
            del sys.modules[k]
    sys.modules.update(saved)


class TestQualityInitAllAvailable:
    def setup_method(self):
        import importlib

        # Clean cache
        for key in list(sys.modules.keys()):
            if "iris_pgwire.quality" in key:
                del sys.modules[key]

        import iris_pgwire.quality as q
        importlib.reload(q)
        self.mod = q

    def test_all_exports_declared(self):
        expected = {
            "PackageMetadataValidator",
            "CodeQualityValidator",
            "SecurityValidator",
            "DocumentationValidator",
            "PackageQualityValidator",
        }
        assert set(self.mod.__all__) == expected

    def test_package_metadata_validator_importable(self):
        # If real submodule works, value is not None; may be a MagicMock in CI
        # Just assert the name is in the module namespace
        assert hasattr(self.mod, "PackageMetadataValidator")

    def test_code_quality_validator_importable(self):
        assert hasattr(self.mod, "CodeQualityValidator")

    def test_security_validator_importable(self):
        assert hasattr(self.mod, "SecurityValidator")

    def test_documentation_validator_importable(self):
        assert hasattr(self.mod, "DocumentationValidator")

    def test_package_quality_validator_importable(self):
        assert hasattr(self.mod, "PackageQualityValidator")


# ---------------------------------------------------------------------------
# Tests: graceful degradation when submodules are unavailable
# ---------------------------------------------------------------------------


class TestQualityInitDegradation:
    """When a submodule is absent the name should fall back to None."""

    def _get_all_unavailable(self):
        return _reload_quality_init(
            {
                "package_metadata_validator": False,
                "code_quality_validator": False,
                "security_validator": False,
                "documentation_validator": False,
                "validator": False,
            }
        )

    def test_all_none_when_all_unavailable(self):
        q = self._get_all_unavailable()
        assert q.PackageMetadataValidator is None
        assert q.CodeQualityValidator is None
        assert q.SecurityValidator is None
        assert q.DocumentationValidator is None
        assert q.PackageQualityValidator is None

    def test_partial_availability(self):
        """Only security_validator unavailable — others should be non-None."""
        q = _reload_quality_init({"security_validator": False})
        assert q.SecurityValidator is None
        # The others should be non-None (real or mocked)
        assert q.PackageMetadataValidator is not None
        assert q.CodeQualityValidator is not None
        assert q.DocumentationValidator is not None
        assert q.PackageQualityValidator is not None

    def test_all_declared_in_all_even_when_none(self):
        q = self._get_all_unavailable()
        expected = {
            "PackageMetadataValidator",
            "CodeQualityValidator",
            "SecurityValidator",
            "DocumentationValidator",
            "PackageQualityValidator",
        }
        assert set(q.__all__) == expected
