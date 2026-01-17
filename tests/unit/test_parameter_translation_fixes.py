import pytest

from iris_pgwire.protocol import PGWireProtocol


class TestParameterTranslationFixes:
    def test_translate_postgres_parameters_before_normalization(self):
        """FR-002: Translate $n to ? across all paths"""
        from unittest.mock import MagicMock

        class MockProtocol(PGWireProtocol):
            def __init__(self):
                self.connection_id = 1
                self.iris_executor = MagicMock()
                # Mock sql_translator which is usually inside iris_executor
                from iris_pgwire.sql_translator.normalizer import SQLTranslator

                self.iris_executor.sql_translator = SQLTranslator()

        proto = MockProtocol()
        sql = "SELECT * FROM users WHERE id = $1 AND name = $2"
        translated = proto.translate_postgres_parameters(sql)
        assert translated == "SELECT * FROM users WHERE id = ? AND name = ?"

    def test_translate_type_casts(self):
        """FR-002: Type casts in prepared statements"""
        from unittest.mock import MagicMock

        class MockProtocol(PGWireProtocol):
            def __init__(self):
                self.connection_id = 1
                self.iris_executor = MagicMock()
                from iris_pgwire.sql_translator.normalizer import SQLTranslator

                self.iris_executor.sql_translator = SQLTranslator()

        proto = MockProtocol()
        sql = "SELECT '123'::int, $1::text"
        translated = proto.translate_postgres_parameters(sql)
        assert "CAST('123' AS INTEGER)" in translated
        assert "CAST(? AS VARCHAR)" in translated
