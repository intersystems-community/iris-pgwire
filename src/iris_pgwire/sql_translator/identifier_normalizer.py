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

from iris_pgwire.schema_mapper import IRIS_SCHEMA


class IdentifierNormalizer:
    """
    Normalizes SQL identifier case for IRIS compatibility.

    Implements the contract defined in:
    specs/021-postgresql-compatible-sql/contracts/sql_translator_interface.py
    """

    def __init__(self):
        """Initialize the identifier normalizer with compiled regex patterns"""
        # Pattern to match identifiers (both quoted and unquoted), including schema dots
        # Matches: "QuotedIdentifier", UnquotedIdentifier, schema.table, schema.table.column
        # Improved version: handles whitespace around dots and ensures single-unit matching
        self._identifier_pattern = re.compile(
            r'((?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_]*|%s)(?:\s*\.\s*(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_]*))*)'
        )

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
            "%s",
        }

        self._data_types = {
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
            "VECTOR",
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

        # Feature 036: Pre-normalization transformations (before chunking)

        # 1. Strip GENERATED ALWAYS AS ... STORED column definitions
        if "GENERATED ALWAYS AS" in sql.upper():
            sql = re.sub(
                r"(?i),?\s*[\w\"]+\s+[\w\"]+(?:\s*\([^)]*\))?\s+GENERATED\s+ALWAYS\s+AS\s*\(.*?\)\s*STORED",
                "",
                sql,
                flags=re.DOTALL,
            )
            # Log warning
            import logging

            from .logging_config import DDL_SKIP_FORMAT

            logger = logging.getLogger("iris_pgwire.sql_translator.normalizer")
            logger.warning(DDL_SKIP_FORMAT.format("GENERATED column"))

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

        # Feature 036: Post-normalization stripping (safer after identifiers are handled)
        if "USING" in normalized_sql.upper():
            normalized_sql = re.sub(r"(?i)\s+USING\s+btree\b", "", normalized_sql)
            # Log warning
            import logging

            from .logging_config import DDL_SKIP_FORMAT

            logger = logging.getLogger("iris_pgwire.sql_translator.normalizer")
            logger.warning(DDL_SKIP_FORMAT.format("USING btree"))

        if "WITH" in normalized_sql.upper() and "FILLFACTOR" in normalized_sql.upper():
            normalized_sql = re.sub(
                r"(?i)\s+WITH\s*\(\s*fillfactor\s*=\s*\d+\s*\)", "", normalized_sql
            )
            # Log warning
            import logging

            from .logging_config import DDL_SKIP_FORMAT

            logger = logging.getLogger("iris_pgwire.sql_translator.normalizer")
            logger.warning(DDL_SKIP_FORMAT.format("WITH (fillfactor)"))

        if "::" in normalized_sql:
            # Strip cast syntax
            normalized_sql = re.sub(
                r"(?i)(\?|(?:\$\d+)|'(?:[^']|'')*'|\d+|[\w\.]+)::(?:\"[^\"]+\"|[\w.]+)(?:\s*\([^)]*\))?",
                r"\1",
                normalized_sql,
            )
            # Log warning
            import logging

            from .logging_config import DDL_SKIP_FORMAT

            logger = logging.getLogger("iris_pgwire.sql_translator.normalizer")
            logger.warning(DDL_SKIP_FORMAT.format("Cast syntax"))

        return normalized_sql, identifier_count

    def _normalize_chunk(self, chunk: str, current_count: int) -> tuple[str, int]:
        """Normalize identifiers in a SQL chunk (excluding string literals)"""
        identifier_count = current_count

        # CRITICAL FIX: Detect CREATE TABLE context to preserve lowercase column names
        # PostgreSQL clients expect lowercase column names, but IRIS needs uppercase table names
        # Pattern: CREATE TABLE table_name (column_definitions)
        create_table_pattern = re.compile(
            r"(CREATE\s+(?:TEMPORARY\s+|TEMP\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?)"
            r"(\S+)"  # Table name (will be uppercased)
            r"(\s*\()"  # Opening paren
            r"(.*)"  # Column definitions (will handle nested parens manually)
            r"(\))",  # Closing paren
            re.IGNORECASE | re.DOTALL,
        )

        # Check if this chunk contains CREATE TABLE
        create_match = create_table_pattern.search(chunk)

        if create_match:
            # Process CREATE TABLE specially to preserve column name case
            before_create = chunk[: create_match.start()]
            create_prefix = create_match.group(1).upper()  # CREATE TABLE keywords
            table_name_raw = create_match.group(2)
            # Handle qualified names (schema.table) or quoted names
            if "." in table_name_raw:
                parts = []
                for part in table_name_raw.split("."):
                    part = part.strip()
                    if part.startswith('"') and part.endswith('"'):
                        parts.append(part)  # Quoted: preserve case
                    elif part.upper() == IRIS_SCHEMA.upper():
                        parts.append(IRIS_SCHEMA)  # Fix casing for IRIS
                    else:
                        parts.append(part.upper())  # Unquoted: uppercase
                table_name = ".".join(parts)
            elif table_name_raw.startswith('"') and table_name_raw.endswith('"'):
                table_name = table_name_raw  # Quoted: preserve exact case
            else:
                table_name = table_name_raw.upper()  # Unquoted: uppercase for IRIS
            opening_paren = create_match.group(3)

            # CRITICAL FIX: Find the matching closing paren for the table definition
            # The regex group(4) now has everything until the END of the chunk
            # because we changed [^)]+ to .*
            full_content = create_match.group(4)
            column_defs = ""
            closing_paren = ")"
            after_create = ""

            paren_depth = 1  # We already matched the opening paren
            found_end = False
            for i, char in enumerate(full_content):
                if char == "(":
                    paren_depth += 1
                elif char == ")":
                    paren_depth -= 1

                if paren_depth == 0:
                    column_defs = full_content[:i]
                    after_create = full_content[i + 1 :]
                    found_end = True
                    break

            if not found_end:
                # Fallback: This is a partial CREATE TABLE (split by literal or incomplete)
                # Just do normal identifier normalization on the whole chunk to avoid discarding data.
                return self._normalize_identifiers_in_chunk(chunk, current_count)

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

            full_id = match.group(1)

            for sp_start, sp_end in savepoint_ranges:
                # If this identifier overlaps with a savepoint identifier range
                if match_start >= sp_start and match_end <= sp_end:
                    # Preserve original case for SAVEPOINT identifiers
                    identifier_count += 1
                    return full_id

            if full_id in self._sql_keywords:
                return full_id

            # Not a SAVEPOINT identifier - normalize parts
            if "." in full_id:
                parts = []
                for part in full_id.split("."):
                    part = part.strip()
                    if part.startswith('"') and part.endswith('"'):
                        identifier_count += 1
                        parts.append(part)
                    else:
                        upper = part.upper()
                        if upper in self._sql_keywords:
                            parts.append(upper)
                        elif upper == IRIS_SCHEMA.upper():
                            identifier_count += 1
                            parts.append(IRIS_SCHEMA)
                        else:
                            identifier_count += 1
                            parts.append(upper)
                return ".".join(parts)

            # Simple identifier
            if full_id.startswith('"') and full_id.endswith('"'):
                identifier_count += 1
                return full_id

            upper = full_id.upper()
            if upper in self._sql_keywords:
                return upper
            elif upper == IRIS_SCHEMA.upper():
                identifier_count += 1
                return IRIS_SCHEMA
            else:
                identifier_count += 1
                return upper

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

            full_id = match.group(1)

            if full_id in self._sql_keywords:
                return full_id

            # Handle qualified types/defaults
            if "." in full_id:
                parts = []
                for part in full_id.split("."):
                    part = part.strip()
                    if part.startswith('"') and part.endswith('"'):
                        identifier_count += 1
                        parts.append(part)
                    else:
                        upper = part.upper()
                        if upper in self._sql_keywords or upper in self._data_types:
                            parts.append(upper)
                        else:
                            # Preservation of lowercase column names happens at level above
                            # But here we are in a part of a qualified name.
                            # Usually schemas and tables in qualified names are uppercased for IRIS
                            # unless quoted.
                            identifier_count += 1
                            parts.append(upper)
                return ".".join(parts)

            if full_id.startswith('"') and full_id.endswith('"'):
                # Quoted identifier - preserve exact case
                identifier_count += 1
                return full_id

            # Check if it's a SQL keyword or data type
            upper = full_id.upper()
            if upper in self._sql_keywords or upper in self._data_types:
                # SQL keyword or data type - uppercase
                return upper
            else:
                # Column name - preserve lowercase, count as identifier
                identifier_count += 1
                return full_id.lower()

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
