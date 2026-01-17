"""
Utilities for building IRIS-compatible JSONPath strings from PostgreSQL JSON operators.
"""

import re
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class JsonPathBuilder:
    """Build IRIS JSONPath from PostgreSQL JSON operators."""

    base_column: str
    path_segments: list[str] = field(default_factory=list)
    return_type: Literal["json", "text"] = "text"

    def add_key(self, key: str) -> None:
        """Add a key segment to the path."""
        # Remove single quotes if present
        clean_key = key.strip("'")
        self.path_segments.append(f".{clean_key}")

    def add_index(self, index: int) -> None:
        """Add an array index segment to the path."""
        self.path_segments.append(f"[{index}]")

    def build(self) -> str:
        """
        Build the IRIS SQL expression.

        Returns:
            IRIS SQL string (e.g., "JSON_VALUE(col, '$.a.b.c')")
        """
        path = "$" + "".join(self.path_segments)
        function = "JSON_VALUE" if self.return_type == "text" else "JSON_QUERY"
        return f"{function}({self.base_column}, '{path}')"

    @classmethod
    def parse(cls, sql: str) -> tuple[str, "JsonPathBuilder"]:
        """
        Parse a PostgreSQL JSON access expression.

        Example: data->'user'->'profile'->>'name' or data['user']['name']

        Args:
            sql: SQL snippet starting with JSON access

        Returns:
            Tuple of (remaining_sql, builder)
        """
        # Match base column followed by operators
        # Pattern: identifier followed by ->, ->>, or [
        match = re.match(r"(\w+)(->>?|\[).*", sql)
        if not match:
            raise ValueError(f"Invalid JSON access expression: {sql}")

        base_column = match.group(1)
        # Find where the JSON access ends (first space or other SQL token)
        # This is a simplification; a real parser would be better.
        # For regex purposes, we'll match until we don't find any more operators.

        builder = cls(base_column=base_column)

        # Current position in sql string after base_column
        pos = len(base_column)
        remaining = sql[pos:]

        while remaining:
            # Check for ->> (returns text)
            text_match = re.match(r"->>'?(\w+)'?", remaining)
            if text_match:
                key_or_index = text_match.group(1)
                if key_or_index.isdigit():
                    builder.add_index(int(key_or_index))
                else:
                    builder.add_key(key_or_index)
                builder.return_type = "text"
                remaining = remaining[len(text_match.group(0)) :].strip()
                break  # ->> must be the last operator in a chain for JSON_VALUE

            # Check for -> (returns json)
            json_match = re.match(r"->'?(\w+)'?", remaining)
            if json_match:
                key_or_index = json_match.group(1)
                if key_or_index.isdigit():
                    builder.add_index(int(key_or_index))
                else:
                    builder.add_key(key_or_index)
                builder.return_type = "json"
                remaining = remaining[len(json_match.group(0)) :].strip()
                continue

            # Check for bracket notation [key] or [index]
            bracket_match = re.match(r"\[['\"]?(\w+)['\"]?\]", remaining)
            if bracket_match:
                key_or_index = bracket_match.group(1)
                if key_or_index.isdigit():
                    builder.add_index(int(key_or_index))
                else:
                    builder.add_key(key_or_index)
                builder.return_type = "json"  # brackets in PG return json-like
                remaining = remaining[len(bracket_match.group(0)) :].strip()
                continue

            break

        return remaining, builder
