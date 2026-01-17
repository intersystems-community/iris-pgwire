import pytest
from iris_pgwire.conversions.ddl_splitter import DdlSplitter


class TestAlterTableTranslationFixes:
    @pytest.fixture
    def splitter(self):
        return DdlSplitter()

    def test_translate_set_data_type(self, splitter):
        """FR-005: Translate SET DATA TYPE to ALTER COLUMN syntax"""
        sql = "ALTER TABLE t1 ALTER COLUMN c1 SET DATA TYPE VARCHAR(100);"
        # Expected translation for IRIS: ALTER TABLE t1 ALTER COLUMN c1 VARCHAR(100)
        translated = splitter.translate_alter_table(sql)
        assert "SET DATA TYPE" not in translated.upper()
        assert "ALTER COLUMN C1 VARCHAR(100)" in translated.upper()

    def test_translate_drop_not_null(self, splitter):
        """FR-005: Translate DROP NOT NULL to NULL"""
        sql = "ALTER TABLE t1 ALTER COLUMN c1 DROP NOT NULL;"
        # Expected: ALTER TABLE t1 ALTER COLUMN c1 NULL
        translated = splitter.translate_alter_table(sql)
        assert "DROP NOT NULL" not in translated.upper()
        assert "ALTER COLUMN C1 NULL" in translated.upper()
