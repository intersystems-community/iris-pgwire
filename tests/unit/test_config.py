"""Unit tests for config.py DDLTranslationConfig."""

from __future__ import annotations

import pytest

from iris_pgwire.config import DDLTranslationConfig


class TestDDLTranslationConfigDefaults:
    """Tests for DDLTranslationConfig default values."""

    def test_default_strict_mode_is_true(self):
        cfg = DDLTranslationConfig()
        assert cfg.strict_mode is True

    def test_default_auto_quote_reserved_words_is_true(self):
        cfg = DDLTranslationConfig()
        assert cfg.auto_quote_reserved_words is True

    def test_default_validate_precision_is_true(self):
        cfg = DDLTranslationConfig()
        assert cfg.validate_precision is True

    def test_default_lock_timeout_seconds_is_30(self):
        cfg = DDLTranslationConfig()
        assert cfg.lock_timeout_seconds == 30

    def test_default_fail_fast_is_false(self):
        cfg = DDLTranslationConfig()
        assert cfg.fail_fast is False


class TestDDLTranslationConfigCustomValues:
    """Tests for DDLTranslationConfig with non-default values."""

    def test_custom_strict_mode(self):
        cfg = DDLTranslationConfig(strict_mode=False)
        assert cfg.strict_mode is False

    def test_custom_lock_timeout(self):
        cfg = DDLTranslationConfig(lock_timeout_seconds=60)
        assert cfg.lock_timeout_seconds == 60

    def test_custom_fail_fast(self):
        cfg = DDLTranslationConfig(fail_fast=True)
        assert cfg.fail_fast is True

    def test_is_frozen(self):
        cfg = DDLTranslationConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.strict_mode = False  # type: ignore[misc]
