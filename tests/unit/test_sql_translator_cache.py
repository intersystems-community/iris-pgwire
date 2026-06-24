"""
Unit tests for iris_pgwire.sql_translator.cache

Targets uncovered branches to push coverage from 79% → ≥85%.
No live IRIS connection required.
"""

import time

import pytest

from iris_pgwire.sql_translator.cache import (
    CacheKeyGenerator,
    CacheMetrics,
    TranslationCache,
    cache_translation,
    generate_cache_key,
    get_cache,
    get_cached_translation,
)
from iris_pgwire.sql_translator.models import PerformanceStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _perf_stats(**kwargs) -> PerformanceStats:
    defaults = dict(translation_time_ms=1.0, cache_hit=False, constructs_detected=0, constructs_translated=0)
    defaults.update(kwargs)
    return PerformanceStats(**defaults)


def _put(cache: TranslationCache, key: str, sql: str = "SELECT 1", original: str = "SELECT 1") -> None:
    cache.put(key, sql, [], _perf_stats(), original_sql=original)


# ---------------------------------------------------------------------------
# CacheMetrics
# ---------------------------------------------------------------------------


class TestCacheMetrics:
    def test_hit_rate_zero_lookups(self):
        m = CacheMetrics()
        assert m.hit_rate == 0.0

    def test_hit_rate_calculated(self):
        m = CacheMetrics(hits=3, total_lookups=10)
        assert m.hit_rate == pytest.approx(0.3)

    def test_average_lookup_zero_lookups(self):
        m = CacheMetrics()
        assert m.average_lookup_ms == 0.0

    def test_average_lookup_calculated(self):
        m = CacheMetrics(total_lookups=4, total_lookup_time_ms=8.0)
        assert m.average_lookup_ms == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# TranslationCache — get / put basics
# ---------------------------------------------------------------------------


class TestTranslationCacheBasic:
    @pytest.fixture
    def cache(self):
        return TranslationCache(max_size=100, default_ttl_seconds=3600)

    def test_get_missing_returns_none(self, cache):
        assert cache.get("nonexistent_key") is None

    def test_put_then_get(self, cache):
        _put(cache, "k1", "SELECT 1", original="SELECT 1")
        entry = cache.get("k1")
        assert entry is not None
        assert entry.translated_sql == "SELECT 1"

    def test_get_updates_access_count(self, cache):
        _put(cache, "k1")
        entry1 = cache.get("k1")
        assert entry1 is not None
        count_after_first_get = entry1.access_count
        cache.get("k1")
        entry2 = cache.get("k1")
        assert entry2 is not None
        assert entry2.access_count > count_after_first_get

    def test_put_with_custom_ttl(self, cache):
        cache.put("k_ttl", "SELECT 2", [], _perf_stats(), ttl_seconds=7200, original_sql="SELECT 2")
        entry = cache.get("k_ttl")
        assert entry is not None
        assert entry.ttl_seconds == 7200

    def test_put_defaults_ttl_when_none(self, cache):
        cache.put("k_def", "SELECT 3", [], _perf_stats(), ttl_seconds=None, original_sql="SELECT 3")
        entry = cache.get("k_def")
        assert entry is not None
        assert entry.ttl_seconds == 3600

    def test_put_uses_cache_key_as_original_when_none(self, cache):
        cache.put("my_key", "SELECT 4", [], _perf_stats(), original_sql=None)
        entry = cache.get("my_key")
        assert entry is not None
        assert entry.original_sql == "my_key"

    def test_overwrite_existing_key(self, cache):
        _put(cache, "k", "SELECT 1")
        cache.put("k", "SELECT 999", [], _perf_stats(), original_sql="SELECT 999")
        entry = cache.get("k")
        assert entry.translated_sql == "SELECT 999"

    def test_miss_increments_miss_counter(self, cache):
        cache.get("no_such_key")
        info = cache.get_cache_info()
        assert info["metrics"]["misses"] == 1

    def test_hit_increments_hit_counter(self, cache):
        _put(cache, "k_hit")
        cache.get("k_hit")
        info = cache.get_cache_info()
        assert info["metrics"]["hits"] == 1


# ---------------------------------------------------------------------------
# TranslationCache — TTL expiry
# ---------------------------------------------------------------------------


class TestTranslationCacheTTL:
    def test_expired_entry_returns_none(self):
        cache = TranslationCache(max_size=10, default_ttl_seconds=1)
        cache.put("expiring", "SELECT 1", [], _perf_stats(), ttl_seconds=1, original_sql="SELECT 1")
        # Patch the created_at to be in the past
        entry = cache._cache["expiring"]
        from datetime import UTC, datetime, timedelta
        entry.created_at = datetime.now(UTC) - timedelta(seconds=5)

        result = cache.get("expiring")
        assert result is None

    def test_cleanup_expired_removes_expired_entries(self):
        cache = TranslationCache(max_size=10, default_ttl_seconds=3600)
        cache.put("old", "SELECT 1", [], _perf_stats(), ttl_seconds=1, original_sql="SELECT 1")
        cache.put("new", "SELECT 2", [], _perf_stats(), ttl_seconds=3600, original_sql="SELECT 2")

        # Expire the "old" entry
        from datetime import UTC, datetime, timedelta
        cache._cache["old"].created_at = datetime.now(UTC) - timedelta(seconds=10)

        removed = cache.cleanup_expired()
        assert removed == 1
        assert cache.get("old") is None
        assert cache.get("new") is not None

    def test_cleanup_no_expired_returns_zero(self):
        cache = TranslationCache(max_size=10)
        _put(cache, "fresh")
        assert cache.cleanup_expired() == 0


# ---------------------------------------------------------------------------
# TranslationCache — LRU eviction
# ---------------------------------------------------------------------------


class TestTranslationCacheLRU:
    def test_eviction_when_over_capacity(self):
        cache = TranslationCache(max_size=3)
        for i in range(4):
            cache.put(f"k{i}", f"SELECT {i}", [], _perf_stats(), original_sql=f"SELECT {i}")

        assert len(cache._cache) == 3
        info = cache.get_cache_info()
        assert info["metrics"]["evictions"] == 1

    def test_lru_evicts_least_recently_used(self):
        cache = TranslationCache(max_size=3)
        _put(cache, "k0", "SELECT 0", "SELECT 0")
        _put(cache, "k1", "SELECT 1", "SELECT 1")
        _put(cache, "k2", "SELECT 2", "SELECT 2")

        # Access k0 to make it recently used
        cache.get("k0")

        # Add k3 — k1 should be evicted (LRU)
        _put(cache, "k3", "SELECT 3", "SELECT 3")

        assert cache.get("k0") is not None
        assert cache.get("k1") is None
        assert cache.get("k3") is not None


# ---------------------------------------------------------------------------
# TranslationCache — invalidate
# ---------------------------------------------------------------------------


class TestTranslationCacheInvalidate:
    @pytest.fixture
    def cache(self):
        c = TranslationCache(max_size=100)
        for i in range(5):
            c.put(f"k{i}", f"SELECT {i}", [], _perf_stats(), original_sql=f"SELECT {i}")
        return c

    def test_invalidate_all_when_no_pattern(self, cache):
        result = cache.invalidate(pattern=None)
        assert result.invalidated_count == 5
        assert cache.get_stats().total_entries == 0

    def test_invalidate_with_prefix_pattern(self, cache):
        # All keys have original_sql = "SELECT N" — match "SELECT%"
        result = cache.invalidate(pattern="SELECT%")
        assert result.invalidated_count == 5

    def test_invalidate_with_suffix_pattern(self, cache):
        # Match only "SELECT 0"
        result = cache.invalidate(pattern="%0")
        assert result.invalidated_count == 1

    def test_invalidate_with_contains_pattern(self, cache):
        result = cache.invalidate(pattern="SELECT")
        assert result.invalidated_count == 5

    def test_invalidate_no_match(self, cache):
        result = cache.invalidate(pattern="NONSENSE%")
        assert result.invalidated_count == 0

    def test_invalidate_updates_metrics(self, cache):
        cache.invalidate(pattern=None)
        info = cache.get_cache_info()
        assert info["metrics"]["invalidations"] == 5


# ---------------------------------------------------------------------------
# TranslationCache — _matches_pattern edge cases
# ---------------------------------------------------------------------------


class TestMatchesPattern:
    @pytest.fixture
    def cache(self):
        return TranslationCache()

    def test_empty_pattern_matches_all(self, cache):
        assert cache._matches_pattern("SELECT 1", "") is True

    def test_prefix_pattern(self, cache):
        assert cache._matches_pattern("SELECT foo", "SELECT%") is True
        assert cache._matches_pattern("INSERT foo", "SELECT%") is False

    def test_suffix_pattern(self, cache):
        assert cache._matches_pattern("FROM users", "%users") is True
        assert cache._matches_pattern("FROM admins", "%users") is False

    def test_middle_wildcard_pattern(self, cache):
        assert cache._matches_pattern("SELECT col FROM tbl", "SELECT%tbl") is True

    def test_exact_match_pattern(self, cache):
        assert cache._matches_pattern("SELECT foo", "foo") is True
        assert cache._matches_pattern("SELECT bar", "foo") is False

    def test_case_insensitive(self, cache):
        assert cache._matches_pattern("select 1", "SELECT%") is True


# ---------------------------------------------------------------------------
# TranslationCache — clear
# ---------------------------------------------------------------------------


class TestTranslationCacheClear:
    def test_clear_returns_count(self):
        cache = TranslationCache(max_size=10)
        for i in range(3):
            _put(cache, f"k{i}")
        assert cache.clear() == 3

    def test_clear_empties_cache(self):
        cache = TranslationCache(max_size=10)
        _put(cache, "k1")
        cache.clear()
        assert cache.get("k1") is None
        assert cache.get_stats().total_entries == 0


# ---------------------------------------------------------------------------
# TranslationCache — get_stats
# ---------------------------------------------------------------------------


class TestTranslationCacheStats:
    def test_stats_empty_cache(self):
        cache = TranslationCache()
        stats = cache.get_stats()
        assert stats.total_entries == 0
        assert stats.hit_rate == 0.0
        assert stats.memory_usage_mb >= 0.0

    def test_stats_after_puts(self):
        cache = TranslationCache()
        for i in range(3):
            _put(cache, f"k{i}")
        stats = cache.get_stats()
        assert stats.total_entries == 3

    def test_oldest_entry_age_non_zero_after_put(self):
        cache = TranslationCache()
        _put(cache, "k1")
        stats = cache.get_stats()
        assert stats.oldest_entry_age_minutes >= 0


# ---------------------------------------------------------------------------
# TranslationCache — get_entry_details
# ---------------------------------------------------------------------------


class TestGetEntryDetails:
    @pytest.fixture
    def cache(self):
        c = TranslationCache()
        c.put("detail_key", "SELECT 42", [], _perf_stats(), original_sql="SELECT 42")
        return c

    def test_missing_key_returns_none(self, cache):
        assert cache.get_entry_details("no_such_key") is None

    def test_returns_expected_fields(self, cache):
        details = cache.get_entry_details("detail_key")
        assert details is not None
        assert details["cache_key"] == "detail_key"
        assert details["translated_sql_length"] == len("SELECT 42")
        assert details["construct_mappings_count"] == 0
        assert "performance_stats" in details
        assert "created_at" in details


# ---------------------------------------------------------------------------
# TranslationCache — get_cache_info
# ---------------------------------------------------------------------------


class TestGetCacheInfo:
    def test_info_structure(self):
        cache = TranslationCache(max_size=50, default_ttl_seconds=900)
        info = cache.get_cache_info()
        assert info["max_size"] == 50
        assert info["default_ttl_seconds"] == 900
        assert "metrics" in info
        assert "constitutional_compliance" in info
        assert "sample_keys" in info

    def test_sample_keys_limited_to_10(self):
        cache = TranslationCache(max_size=20)
        for i in range(15):
            _put(cache, f"key_{i}")
        info = cache.get_cache_info()
        assert len(info["sample_keys"]) <= 10


# ---------------------------------------------------------------------------
# CacheKeyGenerator
# ---------------------------------------------------------------------------


class TestCacheKeyGenerator:
    def test_same_sql_same_key(self):
        k1 = CacheKeyGenerator.generate_key("SELECT 1")
        k2 = CacheKeyGenerator.generate_key("SELECT 1")
        assert k1 == k2

    def test_different_sql_different_key(self):
        k1 = CacheKeyGenerator.generate_key("SELECT 1")
        k2 = CacheKeyGenerator.generate_key("SELECT 2")
        assert k1 != k2

    def test_parameters_change_key(self):
        k1 = CacheKeyGenerator.generate_key("SELECT $1", parameters={"1": "foo"})
        k2 = CacheKeyGenerator.generate_key("SELECT $1", parameters={"1": "bar"})
        assert k1 != k2

    def test_session_context_changes_key(self):
        k1 = CacheKeyGenerator.generate_key("SELECT 1", session_context={"schema": "A"})
        k2 = CacheKeyGenerator.generate_key("SELECT 1", session_context={"schema": "B"})
        assert k1 != k2

    def test_normalize_sql_strips_comments(self):
        sql_with_comment = "SELECT 1 -- inline comment\n"
        normalized = CacheKeyGenerator.normalize_sql(sql_with_comment)
        assert "--" not in normalized

    def test_normalize_sql_strips_block_comments(self):
        sql = "/* block */ SELECT 1"
        normalized = CacheKeyGenerator.normalize_sql(sql)
        assert "/*" not in normalized

    def test_normalize_sql_collapses_whitespace(self):
        sql = "SELECT   1   FROM   t"
        normalized = CacheKeyGenerator.normalize_sql(sql)
        assert "  " not in normalized

    def test_normalize_sql_strips_leading_trailing(self):
        sql = "  SELECT 1  "
        assert CacheKeyGenerator.normalize_sql(sql) == "SELECT 1"

    def test_generate_key_returns_hex_string(self):
        key = CacheKeyGenerator.generate_key("SELECT 1")
        assert len(key) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in key)

    def test_list_parameters_handled(self):
        """Non-dict parameters fall back to str() representation."""
        k = CacheKeyGenerator.generate_key("SELECT 1", parameters=["a", "b"])
        assert isinstance(k, str)

    def test_list_context_handled(self):
        k = CacheKeyGenerator.generate_key("SELECT 1", session_context=["x"])
        assert isinstance(k, str)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    def test_generate_cache_key_returns_string(self):
        key = generate_cache_key("SELECT 1")
        assert isinstance(key, str) and len(key) > 0

    def test_get_cached_translation_miss(self):
        assert get_cached_translation("totally_unknown_key_xyz") is None

    def test_cache_translation_then_retrieve(self):
        key = generate_cache_key("SELECT module_test")
        cache_translation(key, "SELECT module_test", [])
        entry = get_cached_translation(key)
        assert entry is not None
        assert entry.translated_sql == "SELECT module_test"

    def test_get_cache_returns_instance(self):
        assert isinstance(get_cache(), TranslationCache)
