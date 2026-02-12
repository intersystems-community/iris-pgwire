"""Index validation helpers for DDL translation."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ddl_parser import IndexDefinition


class IndexValidator:
    """Ensures CREATE INDEX statements only use supported features."""

    _SIMPLE_COLUMN_PATTERN = re.compile(
        r'^(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*)(?:\.(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*))*$'
    )

    def validate_index(self, definition: "IndexDefinition", original_sql: str) -> None:
        if definition.where_clause:
            self._raise_error(
                "IRIS does not support partial indexes",
                "Remove WHERE clause or create index on full table.",
                original_sql,
            )
        if definition.include_columns:
            self._raise_error(
                "IRIS does not support INCLUDE columns",
                "Create separate index or remove INCLUDE clause.",
                original_sql,
            )
        for column in definition.columns:
            if not self._is_simple_column(column):
                self._raise_error(
                    "IRIS does not support expression indexes",
                    "Create index on column directly.",
                    original_sql,
                )

    def _is_simple_column(self, column: str) -> bool:
        column = column.strip()
        if not column:
            return False
        return bool(self._SIMPLE_COLUMN_PATTERN.match(column))

    def _raise_error(self, message: str, suggested_fix: str, original_sql: str) -> None:
        from .ddl_translator import DDLTranslationError

        raise DDLTranslationError("UNSUPPORTED_INDEX_FEATURE", message, suggested_fix, original_sql)
