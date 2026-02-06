from unittest.mock import MagicMock

import pytest

from iris_pgwire.protocol import PGWireProtocol
from iris_pgwire.sql_translator.models import PerformanceStats, TranslationResult
from iris_pgwire.sql_translator.normalizer import SQLTranslator
from iris_pgwire.sql_translator.pipeline import SQLPipeline


def test_translator_result_structure():
    translator = SQLTranslator()
    sql = "SELECT * FROM public.test"
    result = translator.normalize_sql_with_result(sql)

    assert isinstance(result, TranslationResult)
    assert hasattr(result, "translated_sql")
    assert hasattr(result, "performance_stats")
    assert isinstance(result.performance_stats, PerformanceStats)

    assert hasattr(result.performance_stats, "translation_time_ms")
    assert hasattr(result.performance_stats, "cache_hit")
    assert isinstance(result.performance_stats.cache_hit, bool)


def test_pipeline_propagation():
    pipeline = SQLPipeline()
    sql = "SELECT * FROM public.test"
    final_sql, params, result = pipeline.process(sql)

    assert isinstance(result, TranslationResult)
    assert final_sql == result.translated_sql
    assert isinstance(result.performance_stats, PerformanceStats)


@pytest.mark.asyncio
async def test_protocol_translation_dictionary_mapping():
    mock_executor = MagicMock()
    mock_executor.sql_pipeline = SQLPipeline()

    mock_reader = MagicMock()
    mock_writer = MagicMock()

    protocol = PGWireProtocol(mock_reader, mock_writer, mock_executor, "test_conn")
    sql = "SELECT * FROM public.test"

    translation_dict = await protocol.translate_sql(sql)

    assert translation_dict["success"] is True
    assert "performance_stats" in translation_dict

    perf_stats = translation_dict["performance_stats"]
    assert isinstance(perf_stats, PerformanceStats)
    assert hasattr(perf_stats, "translation_time_ms")
    assert hasattr(perf_stats, "cache_hit")


@pytest.mark.asyncio
async def test_translate_sql_exception_fallback():
    mock_executor = MagicMock()
    mock_executor.sql_pipeline.process.side_effect = Exception("Translation crash")

    mock_reader = MagicMock()
    mock_writer = MagicMock()

    protocol = PGWireProtocol(mock_reader, mock_writer, mock_executor, "test_conn")

    result = await protocol.translate_sql("SELECT 1")

    assert result["success"] is False
    assert isinstance(result["performance_stats"], PerformanceStats)
    assert result["performance_stats"].cache_hit is False


@pytest.mark.asyncio
async def test_translate_sql_disabled_fallback():
    mock_executor = MagicMock()

    mock_reader = MagicMock()
    mock_writer = MagicMock()

    protocol = PGWireProtocol(mock_reader, mock_writer, mock_executor, "test_conn")
    protocol.enable_translation = False

    result = await protocol.translate_sql("SELECT 1")

    assert result["success"] is True
    assert result["translation_used"] is False
    assert isinstance(result["performance_stats"], PerformanceStats)
    assert result["performance_stats"].cache_hit is False


def test_performance_stats_defaults():
    stats = PerformanceStats(
        translation_time_ms=1.5, cache_hit=True, constructs_detected=5, constructs_translated=5
    )
    assert stats.translation_time_ms == 1.5
    assert stats.cache_hit is True
    assert stats.translation_time_ms == 1.5
