"""
DATE Translator for PostgreSQL-Compatible SQL (Feature 021)

Translates PostgreSQL ISO-8601 DATE literals to IRIS TO_DATE() format:
- 'YYYY-MM-DD' → TO_DATE('YYYY-MM-DD', 'YYYY-MM-DD')

Constitutional Requirements:
- Part of < 5ms normalization overhead requirement
- Avoid false positives (comments, partial strings)
"""

import re


class DATETranslator:
    """
    Translates DATE literals for IRIS compatibility.

    Implements the contract defined in:
    specs/021-postgresql-compatible-sql/contracts/sql_translator_interface.py
    """

    def __init__(self):
        """Initialize DATE translator with compiled regex patterns"""
        # Pattern: Match 'YYYY-MM-DD' DATE literals
        # Must be exact format (4 digits - 2 digits - 2 digits)
        # Must be whole string literal (not part of longer string)
        self._date_literal_pattern = re.compile(r"'(\d{4}-\d{2}-\d{2})'")

        # Comment pattern to skip -- comments
        self._comment_pattern = re.compile(r"--.*$", re.MULTILINE)

    def translate(self, sql: str) -> tuple[str, int]:
        """
        Translate DATE literals in SQL.

        Args:
            sql: Original SQL with PostgreSQL DATE literals

        Returns:
            Tuple of (translated_sql, date_literal_count)
        """
        date_count = 0

        # Remove comments temporarily to avoid translating dates in comments
        comments = []

        def save_comment(match):
            comments.append(match.group(0))
            return f"__COMMENT_{len(comments)-1}__"

        sql_no_comments = self._comment_pattern.sub(save_comment, sql)

        # Translate DATE literals
        def replace_date(match):
            nonlocal date_count
            date_value = match.group(1)

            # Basic validation: check if it looks like a valid date
            if self.is_valid_date_literal(f"'{date_value}'"):
                date_count += 1
                return f"TO_DATE('{date_value}', 'YYYY-MM-DD')"
            return match.group(0)

        translated_sql = self._date_literal_pattern.sub(replace_date, sql_no_comments)

        # Restore comments
        for i, comment in enumerate(comments):
            translated_sql = translated_sql.replace(f"__COMMENT_{i}__", comment)

        return translated_sql, date_count

    def is_valid_date_literal(self, literal: str) -> bool:
        """
        Validate that a string matches the 'YYYY-MM-DD' DATE literal pattern.

        Args:
            literal: String to validate (e.g., "'1985-03-15'")

        Returns:
            True if literal matches 'YYYY-MM-DD' pattern
        """
        match = re.match(r"^'(\d{4})-(\d{2})-(\d{2})'$", literal)
        if not match:
            return False

        year, month, day = match.groups()
        year_int = int(year)
        month_int = int(month)
        day_int = int(day)

        # Basic validation
        if year_int < 1000 or year_int > 9999:
            return False
        if month_int < 1 or month_int > 12:
            return False
        if day_int < 1 or day_int > 31:
            return False

        return True
