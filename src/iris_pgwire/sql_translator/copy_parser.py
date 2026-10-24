"""
COPY SQL Command Parser

Parses PostgreSQL COPY commands and extracts table name, column list, direction,
and CSV options.

Syntax (PostgreSQL's: the WITH before an option list is optional, and the ADBC driver omits it):
    COPY table_name [(column_list)] FROM STDIN [[WITH] (options)]
    COPY table_name [(column_list)] TO STDOUT [[WITH] (options)]
    COPY (query) TO STDOUT [[WITH] (options)]
    ... and the legacy keywords BINARY and CSV [HEADER] after STDIN/STDOUT.

Constitutional Requirement:
- Translation overhead <5ms (performance standard)
- Protocol Fidelity: Exact PostgreSQL COPY syntax support
"""

import re
from dataclasses import dataclass
from enum import Enum


class CopyDirection(str, Enum):
    """COPY operation direction."""

    FROM_STDIN = "FROM_STDIN"
    TO_STDOUT = "TO_STDOUT"


@dataclass
class CSVOptions:
    """
    PostgreSQL CSV format options.

    Defaults match PostgreSQL standard CSV behavior.
    """

    format: str = "CSV"
    delimiter: str = ","
    null_string: str = "\\N"
    header: bool = False
    quote: str = '"'
    escape: str = "\\"
    # The option names the statement actually gave. The fields above hold defaults that predate
    # this and suit COPY FROM; a COPY TO has to know what was asked for, because PostgreSQL's
    # defaults are different (text format, tab delimiter, \\N for NULL).
    explicit: frozenset = frozenset()

    @staticmethod
    def _unescape_string(s: str) -> str:
        """
        Unescape PostgreSQL escape sequences.

        Handles: \\t (tab), \\n (newline), \\r (carriage return), \\\\ (backslash)
        """
        # Handle common PostgreSQL escape sequences
        escape_map = {
            "\\t": "\t",
            "\\n": "\n",
            "\\r": "\r",
            "\\\\": "\\",
        }

        result = s
        for escaped, unescaped in escape_map.items():
            result = result.replace(escaped, unescaped)

        return result

    @classmethod
    def from_with_clause(cls, with_clause: str) -> "CSVOptions":
        """
        Parse WITH (...) clause to extract CSV options.

        Example: "FORMAT CSV, DELIMITER ',', HEADER, NULL ''"
        """
        options = cls()

        if not with_clause:
            return options

        explicit: set[str] = set()

        # Parse options (case-insensitive)
        with_clause_upper = with_clause.upper()

        # FORMAT option
        if "FORMAT" in with_clause_upper:
            format_match = re.search(r"FORMAT\s+(\w+)", with_clause_upper)
            if format_match:
                options.format = format_match.group(1)
                explicit.add("format")

        # DELIMITER option (handle E'...' escape sequences)
        delimiter_match = re.search(r"DELIMITER\s+(E)?'([^']*)'", with_clause, re.IGNORECASE)
        if delimiter_match:
            has_e_prefix = delimiter_match.group(1) is not None
            value = delimiter_match.group(2)
            options.delimiter = cls._unescape_string(value) if has_e_prefix else value
            explicit.add("delimiter")

        # NULL option (handle E'...' escape sequences)
        null_match = re.search(r"NULL\s+(E)?'([^']*)'", with_clause, re.IGNORECASE)
        if null_match:
            has_e_prefix = null_match.group(1) is not None
            value = null_match.group(2)
            options.null_string = cls._unescape_string(value) if has_e_prefix else value
            explicit.add("null")

        # HEADER option: a bare flag, or HEADER true/false/on/off
        header_match = re.search(r"\bHEADER\b(?:\s+(TRUE|FALSE|ON|OFF|1|0|MATCH)\b)?", with_clause_upper)
        if header_match:
            options.header = header_match.group(1) not in ("FALSE", "OFF", "0")
            explicit.add("header")

        # QUOTE option (handle doubled single quotes '')
        quote_match = re.search(r"QUOTE\s+'((?:''|[^'])*)'", with_clause, re.IGNORECASE)
        if quote_match:
            # Replace '' with ' (SQL standard escape)
            options.quote = quote_match.group(1).replace("''", "'")
            explicit.add("quote")

        # ESCAPE option (handle E'...' escape sequences)
        escape_match = re.search(r"ESCAPE\s+(E)?'([^']*)'", with_clause, re.IGNORECASE)
        if escape_match:
            has_e_prefix = escape_match.group(1) is not None
            value = escape_match.group(2)
            options.escape = cls._unescape_string(value) if has_e_prefix else value
            explicit.add("escape")

        options.explicit = frozenset(explicit)
        return options

    @classmethod
    def from_statement_tail(cls, tail: str) -> "CSVOptions":
        """Parse what follows STDIN or STDOUT: `[WITH] (options)`, or the legacy keywords.

        PostgreSQL makes the WITH optional before a parenthesised list, and the ADBC driver
        writes `COPY (...) TO STDOUT (FORMAT binary)` with none. Legacy `BINARY` and `CSV [HEADER]`
        are accepted too.
        """
        text = (tail or "").strip()
        text = re.sub(r"^WITH\b\s*", "", text, flags=re.IGNORECASE)
        listed = ""
        if text.startswith("("):
            end = text.find(")")
            listed, text = text[1:end] if end > 0 else text[1:], (text[end + 1 :] if end > 0 else "")
        options = cls.from_with_clause(listed)
        explicit = set(options.explicit)
        for word in text.upper().replace(",", " ").split():
            if word == "BINARY":
                options.format = "BINARY"
                explicit.add("format")
            elif word == "CSV":
                options.format = "CSV"
                explicit.add("format")
            elif word == "HEADER":
                options.header = True
                explicit.add("header")
        options.explicit = frozenset(explicit)
        return options


@dataclass
class CopyCommand:
    """
    Parsed COPY SQL command.

    Attributes:
        table_name: Target table name (or None for query-based COPY TO)
        column_list: List of column names (None = all columns)
        direction: FROM_STDIN or TO_STDOUT
        csv_options: Parsed CSV format options
        query: SELECT query for COPY (query) TO STDOUT (None for table-based COPY)
    """

    table_name: str | None
    column_list: list[str] | None
    direction: CopyDirection
    csv_options: CSVOptions
    query: str | None = None


class CopyCommandParser:
    """
    Parser for PostgreSQL COPY commands.

    Supports:
    - COPY table_name FROM STDIN
    - COPY table_name TO STDOUT
    - COPY table_name (col1, col2) FROM STDIN
    - COPY (SELECT ...) TO STDOUT
    - WITH (FORMAT CSV, HEADER, DELIMITER ',', ...)
    """

    # Regex patterns
    # Group 3 is everything after STDIN/STDOUT; CSVOptions.from_statement_tail reads it.
    COPY_FROM_STDIN_PATTERN = re.compile(
        r"COPY\s+(\w+)(?:\s*\(([^)]+)\))?\s+FROM\s+STDIN\b(.*)$", re.IGNORECASE | re.DOTALL
    )

    COPY_TO_STDOUT_PATTERN = re.compile(
        r"COPY\s+(\w+)(?:\s*\(([^)]+)\))?\s+TO\s+STDOUT\b(.*)$", re.IGNORECASE | re.DOTALL
    )

    COPY_QUERY_TO_STDOUT_PATTERN = re.compile(
        r"COPY\s*\((.+)\)\s+TO\s+STDOUT\b(.*)$", re.IGNORECASE | re.DOTALL
    )

    @staticmethod
    def is_copy_command(sql: str) -> bool:
        """Check if SQL is a COPY command."""
        return sql.strip().upper().startswith("COPY")

    @staticmethod
    def parse(sql: str) -> CopyCommand:
        """
        Parse COPY SQL command.

        Args:
            sql: COPY SQL statement

        Returns:
            CopyCommand with parsed components

        Raises:
            ValueError: If SQL is not a valid COPY command
        """
        sql = sql.strip()

        # Try COPY FROM STDIN
        match = CopyCommandParser.COPY_FROM_STDIN_PATTERN.match(sql)
        if match:
            table_name = match.group(1)
            column_list_str = match.group(2)
            with_clause = match.group(3)

            column_list = None
            if column_list_str:
                column_list = [col.strip() for col in column_list_str.split(",")]

            csv_options = CSVOptions.from_statement_tail(with_clause or "")

            return CopyCommand(
                table_name=table_name,
                column_list=column_list,
                direction=CopyDirection.FROM_STDIN,
                csv_options=csv_options,
            )

        # Try COPY TO STDOUT (table-based)
        match = CopyCommandParser.COPY_TO_STDOUT_PATTERN.match(sql)
        if match:
            table_name = match.group(1)
            column_list_str = match.group(2)
            with_clause = match.group(3)

            column_list = None
            if column_list_str:
                column_list = [col.strip() for col in column_list_str.split(",")]

            csv_options = CSVOptions.from_statement_tail(with_clause or "")

            return CopyCommand(
                table_name=table_name,
                column_list=column_list,
                direction=CopyDirection.TO_STDOUT,
                csv_options=csv_options,
            )

        # Try COPY (query) TO STDOUT
        match = CopyCommandParser.COPY_QUERY_TO_STDOUT_PATTERN.match(sql)
        if match:
            query = match.group(1).strip()
            with_clause = match.group(2)

            csv_options = CSVOptions.from_statement_tail(with_clause or "")

            return CopyCommand(
                table_name=None,
                column_list=None,
                direction=CopyDirection.TO_STDOUT,
                csv_options=csv_options,
                query=query,
            )

        # Invalid COPY command
        raise ValueError(f"Invalid COPY command syntax: {sql[:100]}")


# Convenience function for direct usage
def parse_copy_command(sql: str) -> CopyCommand:
    """Parse COPY SQL command (convenience wrapper)."""
    return CopyCommandParser.parse(sql)
