"""Constraint translation helpers for DDL statements."""

from __future__ import annotations

from .ddl_parser import ConstraintDefinition, ConstraintType


class ConstraintTranslator:
    """Translates PostgreSQL constraint definitions to IRIS equivalents."""

    def translate_constraint(self, constraint: ConstraintDefinition) -> str:
        cols = ", ".join(self._quote_column(column) for column in constraint.columns)
        if not cols:
            return ""
        if constraint.constraint_type is ConstraintType.PRIMARY_KEY:
            return f"PRIMARY KEY ({cols})"
        if constraint.constraint_type is ConstraintType.UNIQUE:
            return f"UNIQUE ({cols})"
        return ""

    def _quote_column(self, column: str) -> str:
        if not column:
            return ""
        value = column.strip()
        if value.startswith('"') and value.endswith('"'):
            return value
        return f'"{value}"'


__all__ = ["ConstraintTranslator"]
