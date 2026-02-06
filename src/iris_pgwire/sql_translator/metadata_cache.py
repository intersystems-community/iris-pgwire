"""Metadata cache for IRIS PGWire gateway.

Stores column metadata for PGWire translation helpers so we can avoid
re-querying INFORMATION_SCHEMA.COLUMNS too frequently.

The cache is keyed by (schema, table) and expires entries after a configurable
TTL (default 5 minutes).
"""

import time
import threading
from typing import Any, Dict, Tuple

try:
    import structlog

    logger = structlog.get_logger()
except ImportError:  # pragma: no cover - structlog may not be installed everywhere
    import logging

    logger = logging.getLogger(__name__)


ColumnMetadata = Dict[str, Dict[str, Any]]


class MetadataCache:
    """Cache column metadata from INFORMATION_SCHEMA.COLUMNS."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        """Initialize the cache.

        Args:
            ttl_seconds: Time-to-live for cache entries in seconds.
        """
        self._ttl = max(1, ttl_seconds)
        self._cache: Dict[Tuple[str, str], Tuple[float, ColumnMetadata]] = {}
        self._lock = threading.RLock()

    async def get_column_metadata(self, schema: str, table: str, executor) -> ColumnMetadata:
        """Return metadata for the requested schema/table, querying IRIS if needed."""
        schema_key = self._normalize_identifier(schema)
        table_key = self._normalize_identifier(table)

        if not schema_key or not table_key:
            return {}

        cache_key = (schema_key, table_key)
        now = time.monotonic()

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry:
                cached_at, metadata = entry
                if now - cached_at < self._ttl:
                    return metadata
                # Expired entry
                self._cache.pop(cache_key, None)

        metadata: ColumnMetadata = {}
        try:
            query = """
                SELECT COLUMN_NAME, COLUMN_DEFAULT, IS_NULLABLE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE UPPER(TABLE_SCHEMA) = UPPER(?)
                AND UPPER(TABLE_NAME) = UPPER(?)
                ORDER BY ORDINAL_POSITION
            """
            params = [schema_key, table_key]
            result = await executor.execute_query(query, params)
            rows = result.get("rows") or []

            for row in rows:
                if not row:
                    continue
                raw_name = row[0]
                if not raw_name:
                    continue
                column_name = str(raw_name).upper()
                metadata[column_name] = {
                    "column_default": row[1],
                    "is_nullable": row[2],
                }

            cached_at = time.monotonic()
            with self._lock:
                self._cache[cache_key] = (cached_at, metadata)

            return metadata
        except Exception as exc:  # pragma: no cover - best-effort cache
            logger.warning(
                "Failed to load column metadata",
                schema=schema_key,
                table=table_key,
                error=str(exc),
            )
            return {}

    def clear(self) -> None:
        """Evict all cached metadata."""
        with self._lock:
            self._cache.clear()

    @staticmethod
    def _normalize_identifier(value: str | None) -> str:
        """Trim quotes/spaces and normalize to uppercase."""
        if not value:
            return ""

        value = value.strip()
        value = value.strip('"').strip("'")
        return value.upper()
