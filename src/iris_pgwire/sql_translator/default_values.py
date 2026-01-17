import re

import structlog

logger = structlog.get_logger()


class DefaultValuesTranslator:
    """
    Translates INSERT statements containing DEFAULT in VALUES clause for IRIS compatibility.
    IRIS does not support DEFAULT as a value in the VALUES list.
    """

    def translate(self, sql: str) -> str:
        """
        Rewrite INSERT INTO ... (cols) VALUES (...) where some values are DEFAULT.
        Example: INSERT INTO t (a, b) VALUES (1, DEFAULT) -> INSERT INTO t (a) VALUES (1)
        """
        # Match INSERT INTO table (cols) VALUES (vals)
        # This regex is simplified and might need refinement for complex cases
        pattern = r"^\s*INSERT\s+INTO\s+([\w\.\"]+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)"
        match = re.search(pattern, sql, re.IGNORECASE | re.DOTALL)

        if not match:
            return sql

        table_part = match.group(1)
        cols_part = match.group(2)
        vals_part = match.group(3)

        cols = [c.strip() for c in cols_part.split(",")]
        # Values split needs to be careful of commas in strings/parens
        # For now, a simple split for the most common case
        vals = [v.strip() for v in vals_part.split(",")]

        if len(cols) != len(vals):
            return sql  # Should not happen in valid SQL

        new_cols = []
        new_vals = []
        has_default = False

        for col, val in zip(cols, vals, strict=False):
            if val.upper() == "DEFAULT":
                has_default = True
                continue
            new_cols.append(col)
            new_vals.append(val)

        if not has_default:
            return sql

        if not new_cols:
            # All columns were DEFAULT - use DEFAULT VALUES syntax
            return f"INSERT INTO {table_part} DEFAULT VALUES"

        return f"INSERT INTO {table_part} ({', '.join(new_cols)}) VALUES ({', '.join(new_vals)})"
