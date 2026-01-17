import pytest
from iris_pgwire.sql_translator.date_translator import DATETranslator


class TestTimestampNormalizationFixes:
    @pytest.fixture
    def translator(self):
        return DATETranslator()

    def test_normalize_iso8601_timestamp_with_z(self, translator):
        """FR-004: Strip Z from timestamps"""
        sql = "VALUES ('2024-01-16T12:34:56Z');"
        # The goal is IRIS-compatible format
        translated, count = translator.translate(sql)
        assert "2024-01-16 12:34:56" in translated
        assert "'2024-01-16 12:34:56'" in translated

    def test_normalize_iso8601_timestamp_with_offset(self, translator):
        """FR-004: Strip offset from timestamps"""
        sql = "WHERE ts > '2024-01-16T12:34:56+05:00'"
        translated, count = translator.translate(sql)
        assert "2024-01-16 12:34:56" in translated
        assert "+05:00" not in translated
