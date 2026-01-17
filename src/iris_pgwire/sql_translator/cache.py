"""
Translation Cache Implementation

High-performance LRU/TTL cache for SQL translation results with constitutional
compliance monitoring and performance optimization.

Constitutional Compliance: Sub-millisecond cache operations supporting 5ms SLA.
"""

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .models import (
    CacheEntry,
    CacheStats,
    InvalidationResult,
    PerformanceStats,
    PerformanceTimer,
)


@dataclass
class CacheMetrics:
    """Real-time cache performance metrics"""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0
    total_lookups: int = 0
    total_lookup_time_ms: float = 0.0
    memory_usage_bytes: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate"""
        if self.total_lookups == 0:
            return 0.0
        return self.hits / self.total_lookups

    @property
    def average_lookup_ms(self) -> float:
        """Calculate average lookup time"""
        if self.total_lookups == 0:
            return 0.0
        return self.total_lookup_time_ms / self.total_lookups


class TranslationCache:
    """
    High-performance translation cache with LRU eviction and TTL expiration

    Features:
    - LRU (Least Recently Used) eviction policy
    - TTL (Time To Live) expiration
    - Thread-safe operations
    - Constitutional performance monitoring
    - Pattern-based invalidation
    """

    def __init__(self, max_size: int = 10000, default_ttl_seconds: int = 3600):
        """
        Initialize translation cache

        Args:
            max_size: Maximum number of cache entries
            default_ttl_seconds: Default TTL for cache entries (1 hour)
        """
        self.max_size = max_size
        self.default_ttl_seconds = default_ttl_seconds

        # Thread-safe cache storage using OrderedDict for LRU behavior
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()  # Reentrant lock for nested operations

        # Performance metrics
        self._metrics = CacheMetrics()
        self._start_time = datetime.now(UTC)

        # Constitutional monitoring
        self._sla_violations = 0
        self._max_lookup_time_ms = 0.0

    def get(self, cache_key: str) -> CacheEntry | None:
        """
        Get entry from cache

        Args:
            cache_key: Cache key to lookup

        Returns:
            Cache entry if found and not expired, None otherwise
        """
        with PerformanceTimer() as timer:
            with self._lock:
                self._metrics.total_lookups += 1

                if cache_key not in self._cache:
                    self._metrics.misses += 1
                    self._update_lookup_metrics(timer.elapsed_ms)
                    return None

                entry = self._cache[cache_key]

                # Check if entry has expired
                if entry.is_expired:
                    del self._cache[cache_key]
                    self._metrics.misses += 1
                    self._update_lookup_metrics(timer.elapsed_ms)
                    return None

                # Move to end (most recently used)
                self._cache.move_to_end(cache_key)
                entry.update_access()

                self._metrics.hits += 1
                self._update_lookup_metrics(timer.elapsed_ms)

                return entry

    def put(
        self,
        cache_key: str,
        translated_sql: str,
        construct_mappings: list,
        performance_stats: PerformanceStats | None = None,
        ttl_seconds: int | None = None,
        original_sql: str | None = None,
    ) -> None:
        """
        Put entry into cache

        Args:
            cache_key: Cache key
            translated_sql: Translated SQL result
            construct_mappings: List of construct mappings
            performance_stats: Performance statistics
            ttl_seconds: TTL override for this entry
            original_sql: Original SQL statement (required for pattern matching)
        """
        with PerformanceTimer() as timer:
            with self._lock:
                # Use provided TTL or default
                entry_ttl = ttl_seconds or self.default_ttl_seconds

                # Create cache entry
                entry = CacheEntry(
                    original_sql=original_sql or cache_key,
                    translated_sql=translated_sql,
                    construct_mappings=construct_mappings,
                    performance_stats=performance_stats or PerformanceStats(0.0, False, 0, 0),
                    ttl_seconds=entry_ttl,
                )

                # Add to cache
                self._cache[cache_key] = entry
                self._cache.move_to_end(cache_key)

                # Evict if over capacity
                self._evict_if_needed()

                # Update memory usage estimate
                self._update_memory_usage()

                # Constitutional check: cache operations should be fast
                if timer.elapsed_ms > 1.0:  # 1ms threshold for cache operations
                    self._sla_violations += 1

    def invalidate(self, pattern: str | None = None) -> InvalidationResult:
        """
        Invalidate cache entries

        Args:
            pattern: SQL pattern to match for selective invalidation.
                    If None, invalidates all entries.

        Returns:
            Result indicating number of entries invalidated
        """
        with PerformanceTimer():
            with self._lock:
                len(self._cache)

                if pattern is None:
                    # Invalidate all entries
                    invalidated_count = len(self._cache)
                    self._cache.clear()
                else:
                    # Selective invalidation based on pattern
                    keys_to_remove = []

                    for key, entry in self._cache.items():
                        if self._matches_pattern(entry.original_sql, pattern):
                            keys_to_remove.append(key)

                    for key in keys_to_remove:
                        del self._cache[key]

                    invalidated_count = len(keys_to_remove)

                self._metrics.invalidations += invalidated_count
                self._update_memory_usage()

                return InvalidationResult(invalidated_count=invalidated_count)

    def get_stats(self) -> CacheStats:
        """
        Get comprehensive cache statistics

        Returns:
            Cache statistics including performance metrics
        """
        with self._lock:
            # Calculate oldest entry age
            oldest_age_minutes = 0
            if self._cache:
                oldest_entry = min(self._cache.values(), key=lambda e: e.created_at)
                oldest_age_minutes = int(oldest_entry.age_minutes)

            # Estimate memory usage (simplified calculation)
            memory_usage_mb = self._estimate_memory_usage_mb()

            return CacheStats(
                total_entries=len(self._cache),
                hit_rate=self._metrics.hit_rate,
                average_lookup_ms=self._metrics.average_lookup_ms,
                memory_usage_mb=memory_usage_mb,
                oldest_entry_age_minutes=oldest_age_minutes,
            )

    def clear(self) -> int:
        """
        Clear all cache entries

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._update_memory_usage()
            return count

    def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache

        Returns:
            Number of expired entries removed
        """
        with self._lock:
            expired_keys = []

            for key, entry in self._cache.items():
                if entry.is_expired:
                    expired_keys.append(key)

            for key in expired_keys:
                del self._cache[key]

            self._update_memory_usage()
            return len(expired_keys)

    def get_cache_info(self) -> dict[str, Any]:
        """
        Get detailed cache information for debugging

        Returns:
            Dictionary with cache internals
        """
        with self._lock:
            return {
                "cache_size": len(self._cache),
                "max_size": self.max_size,
                "default_ttl_seconds": self.default_ttl_seconds,
                "metrics": {
                    "hits": self._metrics.hits,
                    "misses": self._metrics.misses,
                    "evictions": self._metrics.evictions,
                    "invalidations": self._metrics.invalidations,
                    "total_lookups": self._metrics.total_lookups,
                    "hit_rate": self._metrics.hit_rate,
                    "average_lookup_ms": self._metrics.average_lookup_ms,
                },
                "constitutional_compliance": {
                    "sla_violations": self._sla_violations,
                    "max_lookup_time_ms": self._max_lookup_time_ms,
                    "uptime_seconds": (
                        datetime.now(UTC) - self._start_time
                    ).total_seconds(),
                },
                "sample_keys": list(self._cache.keys())[:10],  # First 10 keys for debugging
            }

    def get_entry_details(self, cache_key: str) -> dict[str, Any] | None:
        """
        Get detailed information about a specific cache entry

        Args:
            cache_key: Cache key to inspect

        Returns:
            Entry details or None if not found
        """
        with self._lock:
            if cache_key not in self._cache:
                return None

            entry = self._cache[cache_key]
            return {
                "cache_key": cache_key,
                "created_at": entry.created_at.isoformat(),
                "last_accessed": entry.last_accessed.isoformat(),
                "access_count": entry.access_count,
                "ttl_seconds": entry.ttl_seconds,
                "age_minutes": entry.age_minutes,
                "is_expired": entry.is_expired,
                "translated_sql_length": len(entry.translated_sql),
                "construct_mappings_count": len(entry.construct_mappings),
                "performance_stats": {
                    "translation_time_ms": entry.performance_stats.translation_time_ms,
                    "cache_hit": entry.performance_stats.cache_hit,
                    "constructs_detected": entry.performance_stats.constructs_detected,
                    "constructs_translated": entry.performance_stats.constructs_translated,
                },
            }

    def _evict_if_needed(self) -> None:
        """Evict least recently used entries if cache is over capacity"""
        while len(self._cache) > self.max_size:
            # Remove least recently used (first item in OrderedDict)
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._metrics.evictions += 1

    def _matches_pattern(self, sql: str, pattern: str) -> bool:
        """
        Check if SQL matches invalidation pattern

        Args:
            sql: SQL statement to check
            pattern: Pattern to match against

        Returns:
            True if SQL matches pattern
        """
        if not pattern:
            return True

        # Simple pattern matching - could be enhanced with regex
        if pattern.endswith("%"):
            return sql.upper().startswith(pattern[:-1].upper())
        elif pattern.startswith("%"):
            return sql.upper().endswith(pattern[1:].upper())
        elif "%" in pattern:
            parts = pattern.upper().split("%")
            sql_upper = sql.upper()
            return sql_upper.startswith(parts[0]) and sql_upper.endswith(parts[-1])
        else:
            return pattern.upper() in sql.upper()

    def _update_lookup_metrics(self, lookup_time_ms: float) -> None:
        """Update lookup performance metrics"""
        self._metrics.total_lookup_time_ms += lookup_time_ms
        self._max_lookup_time_ms = max(self._max_lookup_time_ms, lookup_time_ms)

        # Constitutional monitoring: cache lookups should be very fast
        if lookup_time_ms > 0.5:  # 0.5ms threshold
            self._sla_violations += 1

    def _update_memory_usage(self) -> None:
        """Update memory usage estimate"""
        # Simplified memory estimation
        total_bytes = 0
        for entry in self._cache.values():
            # Estimate: original SQL + translated SQL + overhead
            total_bytes += (
                len(entry.original_sql.encode("utf-8"))
                + len(entry.translated_sql.encode("utf-8"))
                + len(entry.construct_mappings) * 200  # Rough estimate per mapping
                + 500  # Overhead per entry
            )

        self._metrics.memory_usage_bytes = total_bytes

    def _estimate_memory_usage_mb(self) -> float:
        """Estimate total memory usage in MB"""
        return self._metrics.memory_usage_bytes / (1024 * 1024)


class CacheKeyGenerator:
    """Generates consistent cache keys for translation requests"""

    @staticmethod
    def generate_key(
        original_sql: str, parameters: dict | None = None, session_context: dict | None = None
    ) -> str:
        """
        Generate cache key from SQL and context

        Args:
            original_sql: Original SQL statement
            parameters: Query parameters
            session_context: Session context

        Returns:
            Consistent cache key
        """
        # Normalize SQL for consistent caching
        normalized_sql = CacheKeyGenerator.normalize_sql(original_sql)

        # Create content for hashing
        content_parts = [normalized_sql]

        if parameters:
            # Sort parameters for consistent ordering
            sorted_params = (
                sorted(parameters.items()) if isinstance(parameters, dict) else str(parameters)
            )
            content_parts.append(str(sorted_params))

        if session_context:
            # Sort context for consistent ordering
            sorted_context = (
                sorted(session_context.items())
                if isinstance(session_context, dict)
                else str(session_context)
            )
            content_parts.append(str(sorted_context))

        # Generate hash
        content = "|||".join(content_parts)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def normalize_sql(sql: str) -> str:
        """
        Normalize SQL for consistent caching

        Args:
            sql: Original SQL statement

        Returns:
            Normalized SQL
        """
        # Remove extra whitespace and normalize case for keywords
        import re

        # Remove comments
        sql = re.sub(r"--.*?\n", "\n", sql)
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)

        # Normalize whitespace
        sql = re.sub(r"\s+", " ", sql)
        sql = sql.strip()

        return sql


# Global cache instance
_cache = TranslationCache()


def get_cache() -> TranslationCache:
    """Get the global cache instance"""
    return _cache


def generate_cache_key(
    original_sql: str, parameters: dict | None = None, session_context: dict | None = None
) -> str:
    """Generate cache key (convenience function)"""
    return CacheKeyGenerator.generate_key(original_sql, parameters, session_context)


def get_cached_translation(cache_key: str) -> CacheEntry | None:
    """Get cached translation (convenience function)"""
    return _cache.get(cache_key)


def cache_translation(
    cache_key: str,
    translated_sql: str,
    construct_mappings: list,
    performance_stats: PerformanceStats | None = None,
) -> None:
    """Cache translation result (convenience function)"""
    _cache.put(cache_key, translated_sql, construct_mappings, performance_stats)


# Export main components
__all__ = [
    "TranslationCache",
    "CacheKeyGenerator",
    "CacheMetrics",
    "get_cache",
    "generate_cache_key",
    "get_cached_translation",
    "cache_translation",
]
