"""
Contract Tests for Translation Cache Invalidation API

Tests the /cache/invalidate endpoint contract compliance against the OpenAPI specification.
These tests MUST FAIL until the implementation is complete (TDD requirement).

Contract specification: /specs/004-iris-sql-constructs/contracts/translation_api.yaml
"""

import pytest

# These imports will fail until implementation exists - expected in TDD
try:
    from iris_pgwire.sql_translator import SQLTranslator
    from iris_pgwire.sql_translator.cache import TranslationCache

    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

pytestmark = pytest.mark.contract


@pytest.fixture
def cache():
    """Translation cache instance for testing"""
    if not CACHE_AVAILABLE:
        pytest.skip("Cache module not implemented yet")
    return TranslationCache()


@pytest.fixture
def populated_cache(cache):
    """Cache with sample entries for invalidation testing"""
    if not CACHE_AVAILABLE:
        pytest.skip("Cache module not implemented yet")

    # Populate cache with test entries
    test_queries = [
        "SELECT %SYSTEM.Version.GetNumber()",
        "SELECT TOP 10 * FROM users",
        "SELECT %SQLUPPER(name) FROM users",
        "INSERT INTO logs VALUES (1, 'test')",
        "UPDATE users SET status = 'active'",
    ]

    for sql in test_queries:
        # Mock cache entry creation
        cache.put(sql, f"translated_{sql}", {})

    return cache


class TestCacheInvalidateContract:
    """Test cache invalidation request/response structure matches OpenAPI schema"""

    def test_invalidate_all_entries(self, populated_cache):
        """Test invalidating all cache entries"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # This will fail until invalidate() method is implemented
        initial_stats = populated_cache.get_stats()
        initial_count = getattr(initial_stats, "total_entries", initial_stats.get("total_entries"))
        assert initial_count > 0, "Cache should have entries before invalidation"

        # Invalidate all entries (no pattern provided)
        result = populated_cache.invalidate()

        # Verify response structure matches contract
        assert "invalidated_count" in result or hasattr(
            result, "invalidated_count"
        ), "Response should include invalidated_count"

        invalidated_count = result.get(
            "invalidated_count", getattr(result, "invalidated_count", None)
        )
        assert isinstance(invalidated_count, int), "invalidated_count should be integer"
        assert (
            invalidated_count == initial_count
        ), f"Should invalidate all {initial_count} entries, got {invalidated_count}"

        # Verify cache is now empty
        final_stats = populated_cache.get_stats()
        final_count = getattr(final_stats, "total_entries", final_stats.get("total_entries"))
        assert final_count == 0, "Cache should be empty after invalidating all entries"

    def test_invalidate_with_pattern(self, populated_cache):
        """Test invalidating cache entries matching a pattern"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        initial_stats = populated_cache.get_stats()
        initial_count = getattr(initial_stats, "total_entries", initial_stats.get("total_entries"))

        # Invalidate only SELECT queries
        result = populated_cache.invalidate(pattern="SELECT%")

        # Verify response structure
        invalidated_count = result.get(
            "invalidated_count", getattr(result, "invalidated_count", None)
        )
        assert isinstance(invalidated_count, int), "invalidated_count should be integer"
        assert invalidated_count >= 3, "Should invalidate at least 3 SELECT queries"
        assert invalidated_count < initial_count, "Should not invalidate all entries"

        # Verify remaining entries
        final_stats = populated_cache.get_stats()
        final_count = getattr(final_stats, "total_entries", final_stats.get("total_entries"))
        expected_remaining = initial_count - invalidated_count
        assert (
            final_count == expected_remaining
        ), f"Should have {expected_remaining} entries remaining, got {final_count}"

    def test_invalidate_nonexistent_pattern(self, populated_cache):
        """Test invalidating with pattern that matches no entries"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        initial_stats = populated_cache.get_stats()
        initial_count = getattr(initial_stats, "total_entries", initial_stats.get("total_entries"))

        # Use pattern that won't match any cached queries
        result = populated_cache.invalidate(pattern="DELETE%")

        # Should return 0 invalidated count
        invalidated_count = result.get(
            "invalidated_count", getattr(result, "invalidated_count", None)
        )
        assert invalidated_count == 0, "Should invalidate 0 entries for non-matching pattern"

        # Cache should remain unchanged
        final_stats = populated_cache.get_stats()
        final_count = getattr(final_stats, "total_entries", final_stats.get("total_entries"))
        assert final_count == initial_count, "Cache size should be unchanged"

    def test_invalidate_empty_cache(self, cache):
        """Test invalidating an empty cache"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # Ensure cache is empty
        stats = cache.get_stats()
        entry_count = getattr(stats, "total_entries", stats.get("total_entries"))
        assert entry_count == 0, "Cache should be empty for this test"

        # Invalidate empty cache
        result = cache.invalidate()

        # Should return 0 invalidated count
        invalidated_count = result.get(
            "invalidated_count", getattr(result, "invalidated_count", None)
        )
        assert invalidated_count == 0, "Should invalidate 0 entries from empty cache"


class TestCacheInvalidateEndpoint:
    """Test cache invalidation endpoint behavior"""

    def test_invalidate_request_without_pattern(self, populated_cache):
        """Test /cache/invalidate POST without pattern (invalidate all)"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # Simulate endpoint request without pattern

        result = populated_cache.invalidate()  # No pattern = invalidate all

        # Verify response matches OpenAPI schema
        assert isinstance(result, dict), "Response should be a dictionary"
        assert "invalidated_count" in result, "Response should include invalidated_count"
        assert isinstance(result["invalidated_count"], int), "invalidated_count should be integer"

    def test_invalidate_request_with_pattern(self, populated_cache):
        """Test /cache/invalidate POST with pattern"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # Simulate endpoint request with pattern
        request_body = {"pattern": "SELECT%"}

        result = populated_cache.invalidate(pattern=request_body["pattern"])

        # Verify response structure
        assert isinstance(result, dict), "Response should be a dictionary"
        assert "invalidated_count" in result, "Response should include invalidated_count"
        assert result["invalidated_count"] >= 0, "invalidated_count should be non-negative"

    def test_invalidate_pattern_validation(self, cache):
        """Test pattern validation for invalidation requests"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # Test various pattern formats
        valid_patterns = [
            "SELECT%",
            "INSERT%",
            "%SYSTEM%",
            "UPDATE users%",
            "",  # Empty pattern should be valid (no filtering)
        ]

        for pattern in valid_patterns:
            try:
                result = cache.invalidate(pattern=pattern)
                assert "invalidated_count" in result or hasattr(
                    result, "invalidated_count"
                ), f"Pattern '{pattern}' should be valid"
            except Exception as e:
                pytest.fail(f"Valid pattern '{pattern}' raised exception: {e}")


class TestCacheInvalidateIntegration:
    """Integration tests for cache invalidation with translator"""

    def test_invalidate_affects_translation_behavior(self):
        """Test that cache invalidation affects subsequent translation behavior"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        from iris_pgwire.sql_translator import SQLTranslator, TranslationRequest

        translator = SQLTranslator()
        request = TranslationRequest(original_sql="SELECT %SYSTEM.Version.GetNumber()")

        # First translation - cache miss
        result1 = translator.translate(request)
        assert not result1.performance_stats.cache_hit, "First call should be cache miss"

        # Second translation - cache hit
        result2 = translator.translate(request)
        assert result2.performance_stats.cache_hit, "Second call should be cache hit"

        # Invalidate cache
        invalidate_result = translator.cache.invalidate()
        assert invalidate_result["invalidated_count"] >= 1, "Should invalidate cached entry"

        # Third translation - cache miss again
        result3 = translator.translate(request)
        assert (
            not result3.performance_stats.cache_hit
        ), "Translation after invalidation should be cache miss"

    def test_selective_invalidation_preserves_other_entries(self):
        """Test that pattern-based invalidation preserves non-matching entries"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        from iris_pgwire.sql_translator import SQLTranslator, TranslationRequest

        translator = SQLTranslator()

        # Cache multiple different query types
        select_request = TranslationRequest(original_sql="SELECT %SYSTEM.Version.GetNumber()")
        insert_request = TranslationRequest(original_sql="INSERT INTO logs VALUES (1, 'test')")

        # Execute both to populate cache
        translator.translate(select_request)
        translator.translate(insert_request)

        # Verify both are cached
        result1 = translator.translate(select_request)
        result2 = translator.translate(insert_request)
        assert result1.performance_stats.cache_hit, "SELECT should be cached"
        assert result2.performance_stats.cache_hit, "INSERT should be cached"

        # Invalidate only SELECT queries
        invalidate_result = translator.cache.invalidate(pattern="SELECT%")
        assert invalidate_result["invalidated_count"] >= 1, "Should invalidate SELECT queries"

        # Verify selective invalidation
        result3 = translator.translate(select_request)
        result4 = translator.translate(insert_request)

        assert (
            not result3.performance_stats.cache_hit
        ), "SELECT should be cache miss after invalidation"
        assert result4.performance_stats.cache_hit, "INSERT should still be cached"

    def test_cache_invalidation_performance(self, populated_cache):
        """Test that cache invalidation completes within reasonable time"""
        if not CACHE_AVAILABLE:
            pytest.skip("Implementation not available yet")

        import time

        # Measure invalidation performance
        start_time = time.perf_counter()
        result = populated_cache.invalidate()
        invalidation_time_ms = (time.perf_counter() - start_time) * 1000

        # Should complete quickly even with many entries
        assert (
            invalidation_time_ms < 100.0
        ), f"Cache invalidation took {invalidation_time_ms}ms, should be < 100ms"

        # Verify all entries were invalidated
        invalidated_count = result.get(
            "invalidated_count", getattr(result, "invalidated_count", None)
        )
        assert invalidated_count > 0, "Should have invalidated some entries"


# TDD Validation: These tests should fail until implementation exists
def test_cache_invalidate_tdd_validation():
    """Verify cache invalidation tests fail appropriately before implementation"""
    if CACHE_AVAILABLE:
        # If this passes, implementation already exists
        pytest.fail(
            "TDD violation: Cache invalidation implementation exists before tests were written"
        )
    else:
        # Expected state: tests exist, implementation doesn't
        assert True, "TDD compliant: Cache invalidation tests written before implementation"
