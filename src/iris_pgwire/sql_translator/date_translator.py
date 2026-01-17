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
        self._date_literal_pattern = re.compile(r"'(\d{4}-\d{2}-\d{2})'")
        self._timestamp_literal_pattern = re.compile(
            r"'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?:Z|[+-]\d{2}:?\d{2})?'"
        )
        self._comment_pattern = re.compile(r"--.*$", re.MULTILINE)

    def translate(self, sql: str) -> tuple[str, int]:
        """
        Translate DATE and TIMESTAMP literals in SQL.
        """
        change_count = 0
        comments = []

        def save_comment(match):
            comments.append(match.group(0))
            return f"__COMMENT_{len(comments) - 1}__"

        sql_no_comments = self._comment_pattern.sub(save_comment, sql)

        def replace_timestamp(match):
            nonlocal change_count
            date_val = match.group(1)
            time_val = match.group(2)
            change_count += 1
            return f"'{date_val} {time_val}'"

        # Step 1: Normalize TIMESTAMP literals
        sql_translated = self._timestamp_literal_pattern.sub(replace_timestamp, sql_no_comments)

        def replace_date(match):
            nonlocal change_count
            date_value = match.group(1)
            if self.is_valid_date_literal(f"'{date_value}'"):
                change_count += 1
                return f"TO_DATE('{date_value}', 'YYYY-MM-DD')"
            return match.group(0)

        # Step 2: Translate DATE literals
        translated_sql = self._date_literal_pattern.sub(replace_date, sql_translated)

        for i, comment in enumerate(comments):
            translated_sql = translated_sql.replace(f"__COMMENT_{i}__", comment)

        return translated_sql, change_count

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
