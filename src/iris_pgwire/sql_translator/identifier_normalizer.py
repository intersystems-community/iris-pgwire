"""
Identifier Normalizer for PostgreSQL-Compatible SQL (Feature 021)

Normalizes SQL identifiers for IRIS case sensitivity compatibility:
- Unquoted identifiers → UPPERCASE (IRIS standard)
- Quoted identifiers → Preserve exact case (SQL standard)

Constitutional Requirements:
- Part of < 5ms normalization overhead requirement
- Preserve PostgreSQL semantic compatibility
"""

import re


class IdentifierNormalizer:
    """
    Normalizes SQL identifier case for IRIS compatibility.

    Implements the contract defined in:
    specs/021-postgresql-compatible-sql/contracts/sql_translator_interface.py
    """

    def __init__(self):
        """Initialize the identifier normalizer with compiled regex patterns"""
        # Pattern to match identifiers (both quoted and unquoted)
        # Matches: table names, column names, aliases, schema-qualified identifiers
        # Handles: "QuotedIdentifier", UnquotedIdentifier, schema.table, schema.table.column

        # Pattern explanation:
        # 1. Quoted identifier: "([^"]+)" - anything between double quotes
        # 2. Unquoted identifier: \b[a-zA-Z_][a-zA-Z0-9_]*\b - valid SQL identifier
        # This pattern captures identifiers but needs context awareness to avoid keywords

        self._identifier_pattern = re.compile(r'"([^"]+)"|(\b[a-zA-Z_][a-zA-Z0-9_]*\b)')

        # SQL keywords that should NOT be uppercased in context
        # (They're already uppercase in normalized form, but this helps with selective normalization)
        self._sql_keywords = {
            "SELECT",
            "FROM",
            "WHERE",
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "DROP",
            "TABLE",
            "INDEX",
            "VIEW",
            "INTO",
            "VALUES",
            "SET",
            "JOIN",
            "LEFT",
            "RIGHT",
            "INNER",
            "OUTER",
            "ON",
            "AND",
            "OR",
            "NOT",
            "NULL",
            "AS",
            "ORDER",
            "BY",
            "GROUP",
            "HAVING",
            "LIMIT",
            "OFFSET",
            "UNION",
            "INTERSECT",
            "EXCEPT",
            "PRIMARY",
            "KEY",
            "FOREIGN",
            "REFERENCES",
            "CONSTRAINT",
            "UNIQUE",
            "CHECK",
            "DEFAULT",
            "AUTO_INCREMENT",
            "SERIAL",
            "VARCHAR",
            "INT",
            "INTEGER",
            "BIGINT",
            "SMALLINT",
            "DECIMAL",
            "NUMERIC",
            "FLOAT",
            "DOUBLE",
            "DATE",
            "TIME",
            "TIMESTAMP",
            "BOOLEAN",
            "BOOL",
            "TEXT",
            "CHAR",
            "CASCADE",
            "RESTRICT",
            "NO",
            "ACTION",
            "BEGIN",
            "COMMIT",
            "ROLLBACK",
            "TRANSACTION",
            "CASE",
            "WHEN",
            "THEN",
            "ELSE",
            "END",
            "IF",
            "EXISTS",
            "IN",
            "BETWEEN",
            "LIKE",
            "IS",
            "DISTINCT",
            "ALL",
            "ANY",
            "SOME",
            "TRUE",
            "FALSE",
            "UNKNOWN",
            "CAST",
            "EXTRACT",
            "SUBSTRING",
            "POSITION",
            "TRIM",
            "UPPER",
            "LOWER",
            "COALESCE",
            "NULLIF",
            "GREATEST",
            "LEAST",
        }

    def normalize(self, sql: str) -> tuple[str, int]:
        """
        Normalize identifiers in SQL.

        Args:
            sql: Original SQL statement

        Returns:
            Tuple of (normalized_sql, identifier_count)

        Rules:
            - Unquoted identifiers → UPPERCASE
            - Quoted identifiers → Preserve exact case
            - Schema-qualified (schema.table.column) → Normalize each part
            - String literals (single-quoted) → SKIP (preserve as-is)
        """
        identifier_count = 0

        # CRITICAL FIX: Exclude string literals from normalization
        # Split SQL by string literals (single-quoted strings)
        # Pattern: Match string literals with escaped quotes support
        string_literal_pattern = re.compile(r"'(?:[^']|'')*'")

        # Find all string literals and their positions
        string_literals = []
        for match in string_literal_pattern.finditer(sql):
            string_literals.append((match.start(), match.end(), match.group(0)))

        # Process SQL in chunks, skipping string literal regions
        normalized_sql = ""
        last_pos = 0

        for start, end, literal in string_literals:
            # Process SQL before this string literal
            chunk_before = sql[last_pos:start]
            normalized_chunk = self._normalize_chunk(chunk_before, identifier_count)
            normalized_sql += normalized_chunk[0]
            identifier_count = normalized_chunk[1]

            # Append string literal as-is (no normalization)
            normalized_sql += literal
            last_pos = end

        # Process remaining SQL after last string literal
        chunk_after = sql[last_pos:]
        normalized_chunk = self._normalize_chunk(chunk_after, identifier_count)
        normalized_sql += normalized_chunk[0]
        identifier_count = normalized_chunk[1]

        return normalized_sql, identifier_count

    def _normalize_chunk(self, chunk: str, current_count: int) -> tuple[str, int]:
        """Normalize identifiers in a SQL chunk (excluding string literals)"""
        identifier_count = current_count

        # CRITICAL FIX: Detect CREATE TABLE context to preserve lowercase column names
        # PostgreSQL clients expect lowercase column names, but IRIS needs uppercase table names
        # Pattern: CREATE TABLE table_name (column_definitions)
        import re

        create_table_pattern = re.compile(
            r"(CREATE\s+(?:TEMPORARY\s+|TEMP\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)"
            r"(\S+)"  # Table name (will be uppercased)
            r"(\s*\()"  # Opening paren
            r"([^)]+)"  # Column definitions (will preserve lowercase)
            r"(\))",  # Closing paren
            re.IGNORECASE | re.DOTALL,
        )

        # Check if this chunk contains CREATE TABLE
        create_match = create_table_pattern.search(chunk)

        if create_match:
            # Process CREATE TABLE specially to preserve column name case
            before_create = chunk[: create_match.start()]
            create_prefix = create_match.group(1).upper()  # CREATE TABLE keywords
            table_name = create_match.group(2).upper()  # Uppercase table name
            opening_paren = create_match.group(3)
            column_defs = create_match.group(4)  # Preserve case in column definitions
            closing_paren = create_match.group(5)
            after_create = chunk[create_match.end() :]

            # Normalize the before/after parts normally
            before_normalized = self._normalize_identifiers_in_chunk(
                before_create, identifier_count
            )
            identifier_count = before_normalized[1]

            # For column definitions, only uppercase SQL keywords, preserve column names
            column_normalized = self._normalize_column_definitions(column_defs, identifier_count)
            identifier_count = column_normalized[1]

            # Normalize the after part
            after_normalized = self._normalize_identifiers_in_chunk(after_create, identifier_count)
            identifier_count = after_normalized[1]

            normalized_chunk = (
                before_normalized[0]
                + create_prefix
                + table_name
                + opening_paren
                + column_normalized[0]
                + closing_paren
                + after_normalized[0]
            )

            return normalized_chunk, identifier_count
        else:
            # No CREATE TABLE - use original logic
            return self._normalize_identifiers_in_chunk(chunk, identifier_count)

    def _normalize_identifiers_in_chunk(self, chunk: str, current_count: int) -> tuple[str, int]:
        """Normalize identifiers in a SQL chunk (original logic for non-CREATE-TABLE)"""
        identifier_count = current_count

        # CRITICAL FIX (2025-11-14): Detect SAVEPOINT context to preserve identifier case
        # IRIS requires exact case matching for SAVEPOINT names
        # Pattern: SAVEPOINT name, ROLLBACK TO [SAVEPOINT] name, RELEASE [SAVEPOINT] name
        savepoint_pattern = re.compile(
            r"\b(SAVEPOINT|ROLLBACK\s+TO(?:\s+SAVEPOINT)?|RELEASE(?:\s+SAVEPOINT)?)\s+(\S+)",
            re.IGNORECASE,
        )

        # Find all SAVEPOINT-related identifiers and their positions
        savepoint_ranges = []
        for match in savepoint_pattern.finditer(chunk):
            # Store the range of the savepoint identifier (group 2)
            identifier_start = match.start(2)
            identifier_end = match.end(2)
            savepoint_ranges.append((identifier_start, identifier_end))

        def replace_identifier(match):
            nonlocal identifier_count

            # Check if this identifier is within a SAVEPOINT context
            match_start = match.start()
            match_end = match.end()

            for sp_start, sp_end in savepoint_ranges:
                # If this identifier overlaps with a savepoint identifier range
                if match_start >= sp_start and match_end <= sp_end:
                    # Preserve original case for SAVEPOINT identifiers
                    quoted = match.group(1)
                    unquoted = match.group(2)

                    if quoted is not None:
                        identifier_count += 1
                        return f'"{quoted}"'  # Preserve quoted
                    elif unquoted is not None:
                        identifier_count += 1
                        return unquoted  # Preserve original case!

                    return match.group(0)

            # Not a SAVEPOINT identifier - use original logic
            quoted = match.group(1)
            unquoted = match.group(2)

            if quoted is not None:
                # Quoted identifier - preserve exact case
                identifier_count += 1
                return f'"{quoted}"'  # Return as-is
            elif unquoted is not None:
                # Unquoted identifier - check if it's a keyword
                if unquoted.upper() in self._sql_keywords:
                    # SQL keyword - uppercase but don't count as user identifier
                    return unquoted.upper()
                else:
                    # User identifier - uppercase and count
                    identifier_count += 1
                    return unquoted.upper()

            return match.group(0)  # Shouldn't reach here

        normalized_chunk = self._identifier_pattern.sub(replace_identifier, chunk)

        return normalized_chunk, identifier_count

    def _normalize_column_definitions(
        self, column_defs: str, current_count: int
    ) -> tuple[str, int]:
        """
        Normalize column definitions in CREATE TABLE, preserving lowercase column names.

        Only uppercases SQL keywords and type names, preserves column names as lowercase.
        """
        identifier_count = current_count

        def replace_in_column_def(match):
            nonlocal identifier_count

            quoted = match.group(1)
            unquoted = match.group(2)

            if quoted is not None:
                # Quoted identifier - preserve exact case
                identifier_count += 1
                return f'"{quoted}"'
            elif unquoted is not None:
                # Check if it's a SQL keyword or data type
                upper = unquoted.upper()
                if upper in self._sql_keywords or upper in {
                    "INT",
                    "INTEGER",
                    "BIGINT",
                    "SMALLINT",
                    "TINYINT",
                    "VARCHAR",
                    "CHAR",
                    "TEXT",
                    "LONGVARCHAR",
                    "DOUBLE",
                    "FLOAT",
                    "NUMERIC",
                    "DECIMAL",
                    "DATE",
                    "TIME",
                    "TIMESTAMP",
                    "BIT",
                    "BOOLEAN",
                    "BOOL",
                    "VARBINARY",
                    "BINARY",
                    "LONGVARBINARY",
                    "PRIMARY",
                    "KEY",
                    "FOREIGN",
                    "REFERENCES",
                    "NOT",
                    "NULL",
                    "DEFAULT",
                    "AUTO_INCREMENT",
                    "UNIQUE",
                    "CHECK",
                    "CONSTRAINT",
                }:
                    # SQL keyword or data type - uppercase
                    return upper
                else:
                    # Column name - preserve lowercase, count as identifier
                    identifier_count += 1
                    return unquoted.lower()

            return match.group(0)

        normalized = self._identifier_pattern.sub(replace_in_column_def, column_defs)
        return normalized, identifier_count

    def is_quoted(self, identifier: str) -> bool:
        """
        Check if an identifier is delimited with double quotes.

        Args:
            identifier: SQL identifier (may include quotes)

        Returns:
            True if identifier is quoted (e.g., '"FirstName"')
        """
        return identifier.startswith('"') and identifier.endswith('"')
