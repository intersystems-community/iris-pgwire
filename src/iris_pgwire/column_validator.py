"""
Column Name Validator for IRIS Compatibility

Validates PostgreSQL column names against IRIS restrictions:
- No dots in column names (IRIS doesn't support qualified names in DDL)
- Reserved keywords require special handling
- Case-sensitive storage (can cause PostgreSQL incompatibilities)
- Special characters beyond alphanumeric + underscore

Constitutional Requirement (Principle I - Protocol Fidelity):
- PostgreSQL allows dots in quoted identifiers: "user.name"
- IRIS rejects dots even when quoted: ERROR
- We MUST validate early and provide clear error messages
"""

import re


class ColumnNameValidator:
    """Validate and sanitize column names for IRIS compatibility."""

    # IRIS SQL reserved keywords (common subset)
    # Full list: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_reservedwords
    #
    # VALIDATED: 2025-11-09 against actual IRIS 2025.1 using CREATE TABLE tests
    # Result: 63/70 keywords confirmed as reserved by IRIS
    # Note: 7 keywords (INDEX, KEY, LIMIT, OFFSET, ORDER, UNKNOWN, VIEW) are technically
    # allowed by IRIS as column names, but we reject them to avoid confusion since they
    # are SQL keywords that could cause issues in queries.
    IRIS_RESERVED = {
        "SELECT",
        "FROM",
        "WHERE",
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "DROP",
        "ALTER",
        "TABLE",
        "INDEX",
        "VIEW",
        "AS",
        "AND",
        "OR",
        "NOT",
        "NULL",
        "IS",
        "IN",
        "BETWEEN",
        "LIKE",
        "ORDER",
        "BY",
        "GROUP",
        "HAVING",
        "UNION",
        "JOIN",
        "LEFT",
        "RIGHT",
        "INNER",
        "OUTER",
        "ON",
        "USING",
        "DISTINCT",
        "ALL",
        "ANY",
        "SOME",
        "EXISTS",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "TRANSACTION",
        "GRANT",
        "REVOKE",
        "PRIMARY",
        "FOREIGN",
        "KEY",
        "REFERENCES",
        "UNIQUE",
        "CHECK",
        "DEFAULT",
        "VALUES",
        "SET",
        "INTO",
        "LIMIT",
        "OFFSET",
        "FETCH",
        "FIRST",
        "LAST",
        "TRUE",
        "FALSE",
        "UNKNOWN",
        "CURRENT_DATE",
        "CURRENT_TIME",
        "CURRENT_TIMESTAMP",
    }

    @staticmethod
    def validate_column_name(name: str) -> tuple[bool, str]:
        """
        Validate a single column name for IRIS compatibility.

        Args:
            name: Column name to validate

        Returns:
            (is_valid, error_message): Tuple of validation result
                - is_valid: True if name is compatible
                - error_message: Empty string if valid, error description if invalid
        """
        # Check for empty name
        if not name or not name.strip():
            return False, "Column name cannot be empty"

        # Check for dots (PostgreSQL qualified names not supported in IRIS DDL)
        if "." in name:
            return False, (
                f"Column name '{name}' contains dot (.) which IRIS does not support.\n"
                f"    Hint: Replace dots with underscores (e.g., 'user_name' instead of 'user.name')"
            )

        # Check for reserved keywords
        if name.upper() in ColumnNameValidator.IRIS_RESERVED:
            return False, (
                f"Column name '{name}' is an IRIS reserved keyword.\n"
                f"    Hint: Use a different name or add prefix/suffix (e.g., '{name}_col')"
            )

        # Check for invalid characters (IRIS allows alphanumeric + underscore)
        # PostgreSQL allows more characters in quoted identifiers, but IRIS is stricter
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            return False, (
                f"Column name '{name}' contains invalid characters.\n"
                f"    IRIS allows: letters, digits, underscore (must start with letter or underscore)\n"
                f"    Hint: Use only alphanumeric characters and underscores"
            )

        # Check for excessive length (IRIS has limits)
        if len(name) > 128:
            return False, (
                f"Column name '{name}' exceeds maximum length of 128 characters.\n"
                f"    Current length: {len(name)} characters"
            )

        return True, ""

    @staticmethod
    def validate_column_list(columns: list[str]) -> list[str]:
        """
        Validate list of column names, raising error on first invalid name.

        Args:
            columns: List of column names to validate

        Returns:
            list[str]: Same column list if all valid

        Raises:
            ValueError: If any column name is invalid
        """
        for col in columns:
            is_valid, error = ColumnNameValidator.validate_column_name(col)
            if not is_valid:
                raise ValueError(
                    f"COPY failed: Invalid column name in CSV header\n\n"
                    f"{error}\n\n"
                    f"IRIS naming restrictions:\n"
                    f"  ✓ Alphanumeric + underscore only\n"
                    f"  ✓ Must start with letter or underscore\n"
                    f"  ✗ No dots (.) in names\n"
                    f"  ✗ No reserved keywords (SELECT, FROM, WHERE, etc.)\n"
                    f"  ✗ No special characters (@, #, $, %, etc.)\n\n"
                    f"All columns in CSV: {columns}"
                )

        return columns

    @staticmethod
    def sanitize_column_name(name: str) -> str:
        """
        Attempt to sanitize a column name to make it IRIS-compatible.

        This is a best-effort conversion that:
        - Replaces dots with underscores
        - Removes invalid characters
        - Adds prefix if starts with digit
        - Adds suffix if reserved keyword

        WARNING: This changes the column name! Use with caution.

        Args:
            name: Original column name

        Returns:
            str: Sanitized column name
        """
        # Replace dots with underscores
        sanitized = name.replace(".", "_")

        # Remove invalid characters
        sanitized = re.sub(r"[^A-Za-z0-9_]", "_", sanitized)

        # Ensure starts with letter or underscore
        if sanitized and sanitized[0].isdigit():
            sanitized = f"col_{sanitized}"

        # Handle reserved keywords
        if sanitized.upper() in ColumnNameValidator.IRIS_RESERVED:
            sanitized = f"{sanitized}_col"

        # Truncate if too long
        if len(sanitized) > 128:
            sanitized = sanitized[:128]

        return sanitized
