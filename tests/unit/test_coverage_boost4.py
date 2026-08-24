"""
Coverage-boost tests for sql_translator/models.py pure dataclasses and utilities.
"""

import pytest
from iris_pgwire.sql_translator.models import (
    SourceLocation,
    ConstructMapping,
    PerformanceStats,
    TranslationRequest,
    FunctionMapping,
    TypeMapping,
    TranslationError,
    UnsupportedConstructError,
    CacheStats,
    InvalidationResult,
    PerformanceTimer,
    validate_sql_syntax,
    create_performance_stats,
    ConstructType,
    ErrorCode,
    FallbackStrategy,
)


class TestSourceLocation:
    def test_valid(self):
        loc = SourceLocation(line=1, column=1, length=5, original_text="hello")
        assert loc.line == 1

    def test_invalid_line(self):
        with pytest.raises(ValueError, match="Line"):
            SourceLocation(line=0, column=1, length=5)

    def test_invalid_column(self):
        with pytest.raises(ValueError, match="Column"):
            SourceLocation(line=1, column=0, length=5)

    def test_invalid_length(self):
        with pytest.raises(ValueError, match="Length"):
            SourceLocation(line=1, column=1, length=-1)


class TestConstructMapping:
    def _loc(self):
        return SourceLocation(line=1, column=1, length=3)

    def test_valid(self):
        m = ConstructMapping(
            construct_type=ConstructType.FUNCTION,
            original_syntax="now()",
            translated_syntax="GETDATE()",
            confidence=0.9,
            source_location=self._loc(),
        )
        assert m.confidence == 0.9

    def test_invalid_confidence_high(self):
        with pytest.raises(ValueError, match="Confidence"):
            ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax="now()",
                translated_syntax="GETDATE()",
                confidence=1.5,
                source_location=self._loc(),
            )

    def test_invalid_confidence_low(self):
        with pytest.raises(ValueError, match="Confidence"):
            ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax="now()",
                translated_syntax="GETDATE()",
                confidence=-0.1,
                source_location=self._loc(),
            )

    def test_empty_original_syntax(self):
        with pytest.raises(ValueError, match="Original syntax"):
            ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax="   ",
                translated_syntax="GETDATE()",
                confidence=1.0,
                source_location=self._loc(),
            )

    def test_empty_translated_syntax(self):
        with pytest.raises(ValueError, match="Translated syntax"):
            ConstructMapping(
                construct_type=ConstructType.FUNCTION,
                original_syntax="now()",
                translated_syntax="  ",
                confidence=1.0,
                source_location=self._loc(),
            )


class TestPerformanceStats:
    def test_valid(self):
        ps = PerformanceStats(
            translation_time_ms=1.0, cache_hit=False,
            constructs_detected=5, constructs_translated=5
        )
        assert ps.is_sla_compliant is True

    def test_sla_violation_logged(self):
        ps = PerformanceStats(
            translation_time_ms=10.0, cache_hit=False,
            constructs_detected=1, constructs_translated=1
        )
        assert ps.is_sla_compliant is False

    def test_negative_time_raises(self):
        with pytest.raises(ValueError, match="negative"):
            PerformanceStats(
                translation_time_ms=-1.0, cache_hit=False,
                constructs_detected=1, constructs_translated=1
            )

    def test_negative_detected_raises(self):
        with pytest.raises(ValueError, match="detected"):
            PerformanceStats(
                translation_time_ms=1.0, cache_hit=False,
                constructs_detected=-1, constructs_translated=0
            )

    def test_negative_translated_raises(self):
        with pytest.raises(ValueError, match="translated cannot be negative"):
            PerformanceStats(
                translation_time_ms=1.0, cache_hit=False,
                constructs_detected=1, constructs_translated=-1
            )

    def test_translated_exceeds_detected_raises(self):
        with pytest.raises(ValueError, match="Cannot translate more"):
            PerformanceStats(
                translation_time_ms=1.0, cache_hit=False,
                constructs_detected=2, constructs_translated=5
            )


class TestTranslationRequest:
    def test_valid(self):
        req = TranslationRequest(original_sql="SELECT 1")
        assert req.original_sql == "SELECT 1"

    def test_empty_sql_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            TranslationRequest(original_sql="   ")

    def test_negative_timeout_raises(self):
        with pytest.raises(ValueError, match="positive"):
            TranslationRequest(original_sql="SELECT 1", timeout_ms=0)

    def test_excessive_timeout_raises(self):
        with pytest.raises(ValueError, match="exceed 30"):
            TranslationRequest(original_sql="SELECT 1", timeout_ms=31000)

    def test_get_cache_key(self):
        req = TranslationRequest(original_sql="SELECT 1")
        key = req.get_cache_key()
        assert len(key) == 64  # SHA256 hex digest


class TestFunctionMapping:
    def test_valid(self):
        fm = FunctionMapping(iris_function="GETDATE", postgresql_function="NOW")
        assert fm.iris_function == "GETDATE"

    def test_empty_iris_function(self):
        with pytest.raises(ValueError, match="IRIS function"):
            FunctionMapping(iris_function="   ", postgresql_function="NOW")

    def test_empty_pg_function(self):
        with pytest.raises(ValueError, match="PostgreSQL function"):
            FunctionMapping(iris_function="GETDATE", postgresql_function="  ")

    def test_invalid_confidence(self):
        with pytest.raises(ValueError, match="Confidence"):
            FunctionMapping(iris_function="GETDATE", postgresql_function="NOW", confidence=2.0)

    def test_add_example(self):
        fm = FunctionMapping(iris_function="GETDATE", postgresql_function="NOW")
        fm.add_example("GETDATE()", "NOW()", "current timestamp")
        assert len(fm.examples) == 1
        assert fm.examples[0]["iris"] == "GETDATE()"


class TestTypeMapping:
    def test_valid(self):
        tm = TypeMapping(iris_type="VARCHAR", postgresql_type="character varying")
        assert tm.iris_type == "VARCHAR"

    def test_empty_iris_type(self):
        with pytest.raises(ValueError, match="IRIS type"):
            TypeMapping(iris_type="  ", postgresql_type="character varying")

    def test_empty_pg_type(self):
        with pytest.raises(ValueError, match="PostgreSQL type"):
            TypeMapping(iris_type="VARCHAR", postgresql_type="  ")

    def test_invalid_confidence(self):
        with pytest.raises(ValueError, match="Confidence"):
            TypeMapping(iris_type="VARCHAR", postgresql_type="varchar", confidence=-0.5)


class TestTranslationError:
    def test_to_dict_basic(self):
        err = TranslationError(
            error_code=ErrorCode.PARSE_ERROR,
            message="parse failed",
            original_sql="SELECT 1",
        )
        d = err.to_dict()
        assert d["message"] == "parse failed"
        assert d["original_sql"] == "SELECT 1"
        assert d["construct_type"] is None
        assert d["source_location"] is None
        assert d["fallback_strategy"] is None

    def test_to_dict_with_location(self):
        loc = SourceLocation(line=1, column=5, length=3)
        err = TranslationError(
            error_code=ErrorCode.PARSE_ERROR,
            message="err",
            source_location=loc,
            construct_type=ConstructType.FUNCTION,
            fallback_strategy=FallbackStrategy.PRESERVE,
        )
        d = err.to_dict()
        assert d["source_location"]["line"] == 1
        assert d["construct_type"] is not None
        assert d["fallback_strategy"] is not None


class TestUnsupportedConstructError:
    def test_message(self):
        err = UnsupportedConstructError(
            construct="LATERAL",
            construct_type=ConstructType.SYNTAX,
        )
        assert "LATERAL" in str(err)
        assert err.construct == "LATERAL"


class TestCacheStats:
    def test_valid(self):
        cs = CacheStats(
            total_entries=10, hit_rate=0.8,
            average_lookup_ms=0.5, memory_usage_mb=1.0,
            oldest_entry_age_minutes=60
        )
        assert cs.hit_rate == 0.8

    def test_negative_entries(self):
        with pytest.raises(ValueError, match="negative"):
            CacheStats(
                total_entries=-1, hit_rate=0.8,
                average_lookup_ms=0.5, memory_usage_mb=1.0,
                oldest_entry_age_minutes=60
            )

    def test_invalid_hit_rate(self):
        with pytest.raises(ValueError, match="Hit rate"):
            CacheStats(
                total_entries=10, hit_rate=1.5,
                average_lookup_ms=0.5, memory_usage_mb=1.0,
                oldest_entry_age_minutes=60
            )

    def test_negative_lookup_ms(self):
        with pytest.raises(ValueError, match="lookup"):
            CacheStats(
                total_entries=10, hit_rate=0.5,
                average_lookup_ms=-1.0, memory_usage_mb=1.0,
                oldest_entry_age_minutes=60
            )

    def test_negative_memory(self):
        with pytest.raises(ValueError, match="Memory"):
            CacheStats(
                total_entries=10, hit_rate=0.5,
                average_lookup_ms=0.5, memory_usage_mb=-1.0,
                oldest_entry_age_minutes=60
            )

    def test_negative_age(self):
        with pytest.raises(ValueError, match="age"):
            CacheStats(
                total_entries=10, hit_rate=0.5,
                average_lookup_ms=0.5, memory_usage_mb=1.0,
                oldest_entry_age_minutes=-1
            )


class TestInvalidationResult:
    def test_valid(self):
        r = InvalidationResult(invalidated_count=5)
        assert r.invalidated_count == 5

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="negative"):
            InvalidationResult(invalidated_count=-1)


class TestPerformanceTimer:
    def test_elapsed_ms(self):
        import time
        with PerformanceTimer() as t:
            time.sleep(0.01)
        assert t.elapsed_ms >= 5.0  # at least 5ms

    def test_elapsed_ms_before_exit(self):
        timer = PerformanceTimer()
        timer.__enter__()
        ms = timer.elapsed_ms
        assert ms >= 0
        timer.__exit__(None, None, None)


class TestValidateSqlSyntax:
    def test_empty_string(self):
        assert validate_sql_syntax("") is False
        assert validate_sql_syntax("   ") is False

    def test_valid_sql(self):
        assert validate_sql_syntax("SELECT id FROM users") is True

    def test_dangerous_pattern_comment(self):
        assert validate_sql_syntax("SELECT 1;--comment") is False

    def test_dangerous_xp(self):
        assert validate_sql_syntax("xp_cmdshell") is False

    def test_dangerous_exec(self):
        assert validate_sql_syntax("exec something") is False


class TestCreatePerformanceStats:
    def test_basic(self):
        timer = PerformanceTimer()
        timer.__enter__()
        timer.__exit__(None, None, None)
        stats = create_performance_stats(timer, cache_hit=True, detected=3, translated=3)
        assert stats.cache_hit is True
        assert stats.constructs_detected == 3
        assert stats.constructs_translated == 3
        assert stats.translation_time_ms >= 0
