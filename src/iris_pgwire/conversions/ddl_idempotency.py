"""
Utilities for handling DDL idempotency and errors in InterSystems IRIS.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DdlResult:
    """Result of DDL statement execution."""

    success: bool
    skipped: bool = False  # True if object already existed
    object_name: str | None = None  # Name of created/skipped object
    object_type: str | None = None  # TABLE, INDEX, etc.
    command: str | None = None  # CREATE, DROP, etc.
    warning: str | None = None  # Message if skipped
    error: Exception | None = None  # Original error if failed


class DdlErrorHandler:
    """Handle DDL errors with idempotency support."""

    # IRIS/PostgreSQL error codes for duplicate objects
    # 42P07: duplicate_table
    # 42S01: base_table_or_view_already_exists (IRIS specific mapped to PG)
    # 42710: duplicate_object (often used for indexes)
    DUPLICATE_TABLE_CODES: set[str] = {"42P07", "42S01"}
    DUPLICATE_INDEX_CODES: set[str] = {"42P07", "42710"}

    def handle(self, sql: str, error: Exception) -> DdlResult:
        """
        Handle a DDL error and determine if it should be skipped due to idempotency.

        Args:
            sql: The DDL statement that failed
            error: The exception raised

        Returns:
            DdlResult indicating if the operation succeeded, was skipped, or failed
        """
        error_msg = str(error)

        if self._is_duplicate_error(error_msg):
            if self.has_if_not_exists(sql):
                obj_name = self.extract_object_name(sql)
                obj_type = self._extract_object_type(sql)

                logger.warning(
                    "Object already exists, skipping: %s '%s'",
                    obj_type or "object",
                    obj_name or "unknown",
                )

                return DdlResult(
                    success=True,
                    skipped=True,
                    object_name=obj_name,
                    object_type=obj_type,
                    command=obj_type,  # Usually TABLE or INDEX
                    warning=f"Object {obj_name} already exists",
                )

        return DdlResult(success=False, error=error)

    def has_if_not_exists(self, sql: str) -> bool:
        """Check if the SQL statement contains IF NOT EXISTS (or our translation marker)."""
        return bool(re.search(r"IF\s+NOT\s+EXISTS|/\*\s*IF_NOT_EXISTS\s*\*/", sql, re.IGNORECASE))

    def extract_object_name(self, sql: str) -> str | None:
        """Extract the name of the object being created."""
        # Clean up comments for name extraction
        clean_sql = re.sub(r"/\*.*?\*/", "", sql)

        # Match TABLE name
        table_match = re.search(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", clean_sql, re.IGNORECASE
        )
        if table_match:
            return table_match.group(1)

        # Match INDEX name
        index_match = re.search(
            r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            clean_sql,
            re.IGNORECASE,
        )
        if index_match:
            return index_match.group(1)

        return None

    def _extract_object_type(self, sql: str) -> str | None:
        """Extract the type of the object being created."""
        if re.search(r"CREATE\s+TABLE", sql, re.IGNORECASE):
            return "TABLE"
        if re.search(r"CREATE\s+(?:UNIQUE\s+)?INDEX", sql, re.IGNORECASE):
            return "INDEX"
        return None

    def _is_duplicate_error(self, error_msg: str) -> bool:
        """Check if the error message indicates a duplicate object."""
        # Common IRIS/PostgreSQL error patterns for duplicates
        patterns = [
            r"already\s+exists",
            r"Duplicate\s+table\s+name",
            r"Duplicate\s+index\s+name",
            r"SQLCODE\s*[:\s]\s*<?-?\d+>?",  # IRIS SQLCODEs often indicate duplicates
        ]
        return any(re.search(p, error_msg, re.IGNORECASE) for p in patterns)
