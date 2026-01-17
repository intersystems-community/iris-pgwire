import pytest

from iris_pgwire.sql_translator.config import TranslationConfig, ValidationConfig
from iris_pgwire.sql_translator.enum_registry import EnumTypeRegistry
from iris_pgwire.sql_translator.statement_filter import StatementFilter


def test_fillfactor_skip_default():
    registry = EnumTypeRegistry()
    config = TranslationConfig()
    sf = StatementFilter(enum_registry=registry, config=config)
    sql = "ALTER TABLE t1 SET (fillfactor = 90)"
    result = sf.check(sql)
    assert result.should_skip is True  # Skipped


def test_fillfactor_strict_mode():
    registry = EnumTypeRegistry()
    config = TranslationConfig(validation=ValidationConfig(strict_ddl=True))
    sf = StatementFilter(enum_registry=registry, config=config)
    sql = "ALTER TABLE t1 SET (fillfactor = 90)"
    with pytest.raises(Exception):
        sf.check(sql)
