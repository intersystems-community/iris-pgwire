"""
Unit Tests: Column Name Validator for IRIS Compatibility

Tests column name validation against IRIS restrictions:
- No dots in column names
- No reserved keywords (SELECT, FROM, WHERE, etc.)
- Only alphanumeric + underscore
- Must start with letter or underscore
- Maximum 128 characters
"""

import pytest
from iris_pgwire.column_validator import ColumnNameValidator


class TestColumnNameValidator:
    """Unit tests for IRIS column name validation."""

    def test_valid_simple_column_name(self):
        """Valid: Simple alphanumeric column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("PatientID")
        assert is_valid is True
        assert error == ""

    def test_valid_with_underscores(self):
        """Valid: Column name with underscores."""
        is_valid, error = ColumnNameValidator.validate_column_name("first_name")
        assert is_valid is True
        assert error == ""

    def test_valid_starts_with_underscore(self):
        """Valid: Column name starting with underscore."""
        is_valid, error = ColumnNameValidator.validate_column_name("_internal_id")
        assert is_valid is True
        assert error == ""

    def test_valid_mixed_case(self):
        """Valid: Mixed case column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("DateOfBirth")
        assert is_valid is True
        assert error == ""

    def test_valid_with_numbers(self):
        """Valid: Column name with numbers (not starting)."""
        is_valid, error = ColumnNameValidator.validate_column_name("address_line1")
        assert is_valid is True
        assert error == ""

    def test_invalid_empty_name(self):
        """Invalid: Empty column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_invalid_whitespace_only(self):
        """Invalid: Whitespace-only column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("   ")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_invalid_dot_in_name(self):
        """Invalid: Column name with dot (PostgreSQL qualified name)."""
        is_valid, error = ColumnNameValidator.validate_column_name("user.name")
        assert is_valid is False
        assert "dot" in error.lower()
        assert "user_name" in error  # Should suggest underscore replacement

    def test_invalid_multiple_dots(self):
        """Invalid: Column name with multiple dots."""
        is_valid, error = ColumnNameValidator.validate_column_name("schema.table.column")
        assert is_valid is False
        assert "dot" in error.lower()

    def test_invalid_reserved_keyword_select(self):
        """Invalid: Reserved keyword SELECT."""
        is_valid, error = ColumnNameValidator.validate_column_name("SELECT")
        assert is_valid is False
        assert "reserved keyword" in error.lower()
        assert "SELECT_col" in error  # Should suggest alternative (preserves case)

    def test_invalid_reserved_keyword_from(self):
        """Invalid: Reserved keyword FROM."""
        is_valid, error = ColumnNameValidator.validate_column_name("FROM")
        assert is_valid is False
        assert "reserved keyword" in error.lower()

    def test_invalid_reserved_keyword_lowercase(self):
        """Invalid: Reserved keyword in lowercase."""
        is_valid, error = ColumnNameValidator.validate_column_name("where")
        assert is_valid is False
        assert "reserved keyword" in error.lower()

    def test_invalid_reserved_keyword_mixed_case(self):
        """Invalid: Reserved keyword in mixed case."""
        is_valid, error = ColumnNameValidator.validate_column_name("InSeRt")
        assert is_valid is False
        assert "reserved keyword" in error.lower()

    def test_invalid_starts_with_digit(self):
        """Invalid: Column name starting with digit."""
        is_valid, error = ColumnNameValidator.validate_column_name("123_column")
        assert is_valid is False
        assert "invalid characters" in error.lower()

    def test_invalid_special_character_at_sign(self):
        """Invalid: Column name with @ character."""
        is_valid, error = ColumnNameValidator.validate_column_name("user@domain")
        assert is_valid is False
        assert "invalid characters" in error.lower()

    def test_invalid_special_character_dollar(self):
        """Invalid: Column name with $ character."""
        is_valid, error = ColumnNameValidator.validate_column_name("$price")
        assert is_valid is False
        assert "invalid characters" in error.lower()

    def test_invalid_special_character_hash(self):
        """Invalid: Column name with # character."""
        is_valid, error = ColumnNameValidator.validate_column_name("column#1")
        assert is_valid is False
        assert "invalid characters" in error.lower()

    def test_invalid_hyphen(self):
        """Invalid: Column name with hyphen."""
        is_valid, error = ColumnNameValidator.validate_column_name("first-name")
        assert is_valid is False
        assert "invalid characters" in error.lower()

    def test_invalid_space(self):
        """Invalid: Column name with space."""
        is_valid, error = ColumnNameValidator.validate_column_name("first name")
        assert is_valid is False
        assert "invalid characters" in error.lower()

    def test_invalid_too_long(self):
        """Invalid: Column name exceeding 128 characters."""
        long_name = "a" * 129
        is_valid, error = ColumnNameValidator.validate_column_name(long_name)
        assert is_valid is False
        assert "128 characters" in error
        assert "129" in error  # Should show actual length

    def test_valid_exactly_128_characters(self):
        """Valid: Column name exactly 128 characters."""
        name_128 = "a" * 128
        is_valid, error = ColumnNameValidator.validate_column_name(name_128)
        assert is_valid is True
        assert error == ""

    def test_validate_column_list_all_valid(self):
        """Valid: List of all valid column names."""
        columns = ["PatientID", "FirstName", "LastName", "DateOfBirth"]
        result = ColumnNameValidator.validate_column_list(columns)
        assert result == columns  # Should return same list

    def test_validate_column_list_with_invalid_dot(self):
        """Invalid: List with column containing dot."""
        columns = ["PatientID", "user.name", "LastName"]
        with pytest.raises(ValueError) as exc_info:
            ColumnNameValidator.validate_column_list(columns)

        error_msg = str(exc_info.value)
        assert "COPY failed" in error_msg
        assert "user.name" in error_msg
        assert "dot" in error_msg.lower()
        assert "All columns in CSV:" in error_msg
        assert "PatientID" in error_msg  # Should show all columns

    def test_validate_column_list_with_reserved_keyword(self):
        """Invalid: List with reserved keyword."""
        columns = ["id", "SELECT", "name"]
        with pytest.raises(ValueError) as exc_info:
            ColumnNameValidator.validate_column_list(columns)

        error_msg = str(exc_info.value)
        assert "reserved keyword" in error_msg.lower()
        assert "SELECT" in error_msg

    def test_validate_column_list_shows_iris_restrictions(self):
        """Error message should show IRIS naming restrictions."""
        columns = ["invalid-name"]
        with pytest.raises(ValueError) as exc_info:
            ColumnNameValidator.validate_column_list(columns)

        error_msg = str(exc_info.value)
        assert "Alphanumeric + underscore only" in error_msg
        assert "No dots (.) in names" in error_msg
        assert "No reserved keywords" in error_msg
        assert "No special characters" in error_msg

    def test_sanitize_column_name_replaces_dots(self):
        """Sanitize: Dots replaced with underscores."""
        result = ColumnNameValidator.sanitize_column_name("user.name")
        assert result == "user_name"

    def test_sanitize_column_name_removes_special_chars(self):
        """Sanitize: Special characters replaced with underscores."""
        result = ColumnNameValidator.sanitize_column_name("first-name@email")
        assert result == "first_name_email"

    def test_sanitize_column_name_adds_prefix_if_starts_with_digit(self):
        """Sanitize: Adds prefix if starts with digit."""
        result = ColumnNameValidator.sanitize_column_name("123column")
        assert result == "col_123column"

    def test_sanitize_column_name_adds_suffix_if_reserved(self):
        """Sanitize: Adds suffix if reserved keyword."""
        result = ColumnNameValidator.sanitize_column_name("SELECT")
        assert result == "SELECT_col"

    def test_sanitize_column_name_truncates_if_too_long(self):
        """Sanitize: Truncates to 128 characters."""
        long_name = "a" * 150
        result = ColumnNameValidator.sanitize_column_name(long_name)
        assert len(result) == 128

    def test_sanitize_column_name_complex_case(self):
        """Sanitize: Complex case with multiple issues."""
        # Has dots, special chars, and might be too long
        result = ColumnNameValidator.sanitize_column_name("user.email@domain.com")
        assert result == "user_email_domain_com"
        # Should be valid after sanitization
        is_valid, error = ColumnNameValidator.validate_column_name(result)
        assert is_valid is True


class TestColumnValidatorIntegration:
    """Integration tests for column validator with CSV parsing."""

    def test_error_message_helpful_for_dots(self):
        """Error message for dots should be helpful."""
        is_valid, error = ColumnNameValidator.validate_column_name("user.name")
        assert "user_name" in error  # Should suggest replacement
        assert "Hint:" in error  # Should have hint

    def test_error_message_helpful_for_keywords(self):
        """Error message for keywords should be helpful."""
        is_valid, error = ColumnNameValidator.validate_column_name("SELECT")
        assert "SELECT_col" in error  # Should suggest alternative
        assert "Hint:" in error

    def test_error_message_shows_iris_rules(self):
        """Error message should explain IRIS rules."""
        is_valid, error = ColumnNameValidator.validate_column_name("invalid@name")
        assert "letters, digits, underscore" in error.lower()
        assert "alphanumeric" in error.lower()

    def test_validate_list_error_shows_context(self):
        """List validation error should show all columns for context."""
        columns = ["good_column", "bad.column", "another_good"]
        with pytest.raises(ValueError) as exc_info:
            ColumnNameValidator.validate_column_list(columns)

        error_msg = str(exc_info.value)
        # Should show ALL columns for debugging context
        assert "good_column" in error_msg
        assert "bad.column" in error_msg
        assert "another_good" in error_msg


# Edge Cases
class TestColumnValidatorEdgeCases:
    """Edge case tests for column validator."""

    def test_unicode_characters_rejected(self):
        """Invalid: Unicode characters in column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("naïve_column")
        assert is_valid is False
        assert "invalid characters" in error.lower()

    def test_emoji_rejected(self):
        """Invalid: Emoji in column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("user_😀")
        assert is_valid is False

    def test_tab_character_rejected(self):
        """Invalid: Tab character in column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("column\tname")
        assert is_valid is False

    def test_newline_character_rejected(self):
        """Invalid: Newline character in column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("column\nname")
        assert is_valid is False

    def test_leading_underscore_valid(self):
        """Valid: Leading underscore is allowed."""
        is_valid, error = ColumnNameValidator.validate_column_name("_column")
        assert is_valid is True

    def test_multiple_underscores_valid(self):
        """Valid: Multiple consecutive underscores."""
        is_valid, error = ColumnNameValidator.validate_column_name("column___name")
        assert is_valid is True

    def test_all_uppercase_valid(self):
        """Valid: All uppercase column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("PATIENTID")
        assert is_valid is True

    def test_all_lowercase_valid(self):
        """Valid: All lowercase column name."""
        is_valid, error = ColumnNameValidator.validate_column_name("patientid")
        assert is_valid is True
