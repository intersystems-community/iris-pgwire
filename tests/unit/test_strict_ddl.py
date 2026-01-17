import pytest

from iris_pgwire.sql_translator.config import TranslationConfig, ValidationConfig


def test_strict_ddl_flag_default():
    config = TranslationConfig()
    assert config.validation.strict_ddl is False


def test_strict_ddl_flag_custom():
    v_config = ValidationConfig(strict_ddl=True)
    config = TranslationConfig(validation=v_config)
    assert config.validation.strict_ddl is True
