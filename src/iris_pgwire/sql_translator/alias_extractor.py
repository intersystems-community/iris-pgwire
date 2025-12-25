"""
SQL Alias Extractor for Column Name Preservation

Parses SELECT queries to extract column aliases (AS expressions) for PostgreSQL
wire protocol RowDescription messages.

IRIS embedded Python's iris.sql.exec() doesn't expose column metadata, forcing
fallback to generic names (column1, column2). This extractor recovers the
original AS aliases from the SQL text.

Constitutional Requirements:
- Part of < 5ms normalization overhead requirement (FR-011)
- Preserve PostgreSQL semantic compatibility
"""

import re

import structlog

logger = structlog.get_logger()


class AliasExtractor:
    """
    Extract column aliases from SELECT queries for RowDescription messages.

    Handles:
    - Simple aliases: SELECT expr AS alias
    - Implicit aliases: SELECT column_name (use column_name as alias)
    - String literals: SELECT 'value' AS alias
    - Functions: SELECT COUNT(*) AS total
    - Schema-qualified: SELECT table.column AS alias
    """

    def __init__(self):
        """Initialize alias extractor with regex patterns"""
        # Pattern to match SELECT clause (everything between SELECT and FROM/WHERE/GROUP/ORDER/LIMIT/UNION)
        # CRITICAL FIX: Make whitespace optional before end-of-string anchor ($) to handle queries without FROM
        # UNION FIX: Stop at UNION keyword to only extract columns from first SELECT in UNION queries
        self._select_clause_pattern = re.compile(
            r"SELECT\s+(.*?)(?:\s+(?:FROM|WHERE|GROUP|ORDER|LIMIT|UNION)|$)",
            re.IGNORECASE | re.DOTALL,
        )

        # Pattern to match AS alias: expr AS alias_name
        # Captures expression and alias name
        self._as_alias_pattern = re.compile(r"(.+?)\s+AS\s+(\w+)", re.IGNORECASE)

        # Pattern to match string literals for exclusion
        self._string_literal_pattern = re.compile(r"'(?:[^']|'')*'")

    def extract_column_aliases(self, sql: str) -> list[str]:
        """
        Extract column aliases from SELECT query.

        Args:
            sql: SELECT query string

        Returns:
            List of column names/aliases in order
            Empty list if not a SELECT query or parsing fails

        Examples:
            >>> extract_column_aliases("SELECT 1 AS num, 'hello' AS text")
            ['num', 'text']

            >>> extract_column_aliases("SELECT id, name FROM users")
            ['id', 'name']

            >>> extract_column_aliases("SELECT COUNT(*) AS total FROM users")
            ['total']
        """
        try:
            # Extract SELECT clause
            select_match = self._select_clause_pattern.search(sql)
            if not select_match:
                logger.debug("No SELECT clause found", sql_preview=sql[:100])
                return []

            select_clause = select_match.group(1).strip()

            # Split by commas (but not commas inside parentheses or strings)
            columns = self._split_select_columns(select_clause)

            aliases = []
            for col_expr in columns:
                alias = self._extract_single_alias(col_expr.strip())
                aliases.append(alias)

            logger.debug(
                "Extracted column aliases",
                sql_preview=sql[:100],
                alias_count=len(aliases),
                aliases=aliases,
            )

            return aliases

        except Exception as e:
            logger.warning("Failed to extract column aliases", error=str(e), sql_preview=sql[:100])
            return []

    def _split_select_columns(self, select_clause: str) -> list[str]:
        """
        Split SELECT clause by commas, respecting parentheses and string literals.

        This is the tricky part - we need to split by commas but NOT commas inside:
        - Function calls: COUNT(*)
        - Nested expressions: CASE WHEN ... END
        - String literals: 'hello, world'

        Args:
            select_clause: SELECT clause text (without SELECT keyword)

        Returns:
            List of column expressions
        """
        columns = []
        current_column = ""
        paren_depth = 0
        in_string = False
        i = 0

        while i < len(select_clause):
            char = select_clause[i]

            # Track string literals
            if char == "'" and (i == 0 or select_clause[i - 1] != "\\"):
                in_string = not in_string
                current_column += char
                i += 1
                continue

            # Skip if inside string literal
            if in_string:
                current_column += char
                i += 1
                continue

            # Track parentheses depth
            if char == "(":
                paren_depth += 1
                current_column += char
                i += 1
                continue
            elif char == ")":
                paren_depth -= 1
                current_column += char
                i += 1
                continue

            # Split on commas ONLY at paren_depth == 0
            if char == "," and paren_depth == 0:
                if current_column.strip():
                    columns.append(current_column.strip())
                current_column = ""
                i += 1
                continue

            # Accumulate current column
            current_column += char
            i += 1

        # Add final column
        if current_column.strip():
            columns.append(current_column.strip())

        return columns

    def _extract_single_alias(self, column_expr: str) -> str:
        """
        Extract alias from a single column expression.

        Rules:
        1. If "AS alias" present, use alias (take LAST occurrence for CAST support)
        2. Otherwise, use rightmost identifier (e.g., "table.column" → "column")
        3. For expressions (e.g., "COUNT(*)"), generate generic "column1", "column2"

        Args:
            column_expr: Single column expression

        Returns:
            Column alias or name
        """
        # Check for explicit AS alias
        # CRITICAL FIX: For expressions like "CAST(? AS INTEGER) AS num",
        # we need to match the LAST "AS" keyword, not the first.
        # Use findall() and take the last match.
        as_matches = self._as_alias_pattern.findall(column_expr)
        if as_matches:
            # as_matches is a list of tuples: [(expr1, alias1), (expr2, alias2), ...]
            # Take the LAST match (the rightmost "AS" in the expression)
            return as_matches[-1][1]  # Return alias name from last match

        # No AS clause - extract implicit name
        # Remove string literals first
        without_strings = self._string_literal_pattern.sub("", column_expr)

        # Extract rightmost identifier
        # CRITICAL FIX: Handle quoted identifiers from Prisma
        # Prisma sends columns like: "public"."test_users"."id"
        # We need to extract "id" not "public"
        # Pattern matches: optional quote, word chars, optional quote, end
        implicit_alias_pattern = re.compile(r'"?(\w+)"?\s*$')
        implicit_match = implicit_alias_pattern.search(without_strings)

        if implicit_match:
            return implicit_match.group(1)

        # Fallback: Try to find last quoted identifier in dot-separated path
        # For "schema"."table"."column", extract "column"
        quoted_identifier_pattern = re.compile(r'"(\w+)"')
        quoted_matches = quoted_identifier_pattern.findall(without_strings)
        if quoted_matches:
            return quoted_matches[-1]  # Return last quoted identifier

        # Fallback: return first identifier found
        identifier_pattern = re.compile(r"(\w+)")
        identifier_match = identifier_pattern.search(without_strings)
        if identifier_match:
            return identifier_match.group(1)

        # Ultimate fallback: generic name (should rarely reach here)
        return "column"
