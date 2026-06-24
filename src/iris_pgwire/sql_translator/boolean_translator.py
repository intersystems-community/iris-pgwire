"""
Boolean Translator - boolean literal normalization to 0/1 (Feature 035)

Translates PostgreSQL boolean literals to IRIS-compatible numeric values:
- true → 1
- false → 0

Context Safety:
- Must NOT modify string literals ('true' remains 'true')
- Must NOT modify comments (-- true or /* false */)

Constitutional Requirements:
- < 1ms overhead per statement
- Case-insensitive matching
- Word boundary protection
"""

import re


class BooleanTranslator:
    """
    Translates PostgreSQL boolean literals to IRIS-compatible values.

    PostgreSQL uses `true` and `false` keywords for boolean defaults.
    IRIS uses BIT type which expects 0/1 for defaults.

    Translation:
    - true → 1
    - false → 0

    Safety:
    - String literals protected ('true' not modified)
    - Comments protected (-- true, /* false */)
    - Word boundaries respected (truetype not modified)
    """

    # Pattern to match DEFAULT true/false (case-insensitive, with word boundaries)
    # Group 1 captures the prefix up to DEFAULT, group 2 captures the boolean keyword
    _BOOL_PATTERN = re.compile(r"\b(true|false)\b", re.IGNORECASE)
    _DEFAULT_BOOL_PATTERN = re.compile(r"\bDEFAULT\s+(true|false)\b", re.IGNORECASE)

    def translate(self, sql: str) -> tuple[str, int]:
        """
        Translate DEFAULT true/false boolean literals to DEFAULT 1/0.

        Only translates boolean values that appear after the DEFAULT keyword.
        Standalone true/false in WHERE/SET/VALUES clauses are not modified.

        Args:
            sql: SQL statement potentially containing boolean defaults

        Returns:
            Tuple of (translated_sql, translation_count)
        """
        if not sql:
            return sql, 0

        lower_sql = sql.lower()
        if "true" not in lower_sql and "false" not in lower_sql:
            return sql, 0

        # Find protected regions (strings and comments)
        protected_regions = self._find_protected_regions(sql)

        # Track translations
        count = 0
        result = []
        last_end = 0

        for match in self._DEFAULT_BOOL_PATTERN.finditer(sql):
            bool_start = match.start(1)  # start of the true/false group
            bool_end = match.end(1)

            # Check if the boolean value is inside a protected region
            if self._is_in_protected_region(bool_start, protected_regions):
                continue

            # Add text before the boolean value (includes 'DEFAULT ')
            result.append(sql[last_end:bool_start])

            # Translate the boolean value
            bool_value = match.group(1).lower()
            result.append("1" if bool_value == "true" else "0")

            count += 1
            last_end = bool_end

        # Add remaining text
        result.append(sql[last_end:])

        return "".join(result), count

    def _find_protected_regions(self, sql: str) -> list[tuple[int, int]]:
        """
        Find regions that should not be modified (strings and comments).

        Returns:
            List of (start, end) tuples for protected regions
        """
        regions = []
        i = 0
        n = len(sql)

        while i < n:
            # Check for single-quoted string
            if sql[i] == "'":
                start = i
                i += 1
                while i < n:
                    if sql[i] == "'" and i + 1 < n and sql[i + 1] == "'":
                        # Escaped quote, skip both
                        i += 2
                    elif sql[i] == "'":
                        # End of string
                        i += 1
                        break
                    else:
                        i += 1
                regions.append((start, i))
                continue

            # Check for line comment
            if sql[i : i + 2] == "--":
                start = i
                # Find end of line
                newline = sql.find("\n", i)
                if newline == -1:
                    i = n
                else:
                    i = newline + 1
                regions.append((start, i))
                continue

            # Check for block comment
            if sql[i : i + 2] == "/*":
                start = i
                # Find end of block comment
                end = sql.find("*/", i + 2)
                if end == -1:
                    i = n
                else:
                    i = end + 2
                regions.append((start, i))
                continue

            i += 1

        return regions

    def _is_in_protected_region(self, pos: int, regions: list[tuple[int, int]]) -> bool:
        """Check if a position is inside any protected region."""
        for start, end in regions:
            if start <= pos < end:
                return True
        return False
