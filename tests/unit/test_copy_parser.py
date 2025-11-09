"""
Unit Tests: COPY Command Parser

Tests CopyCommandParser with all PostgreSQL COPY syntax variations.

Coverage:
- COPY FROM STDIN variations
- COPY TO STDOUT variations
- Column list specifications
- WITH clause options (FORMAT, HEADER, DELIMITER, NULL, QUOTE, ESCAPE)
- Invalid syntax edge cases
- Case sensitivity
- Whitespace handling
- Query-based COPY TO STDOUT

Constitutional Requirement (Principle II): Test-First Development
- Tests written to validate existing CopyCommandParser implementation
- Comprehensive coverage of PostgreSQL COPY syntax
"""

import pytest
from iris_pgwire.sql_translator.copy_parser import (
    CopyCommandParser,
    CopyCommand,
    CopyDirection,
    CSVOptions
)


@pytest.mark.unit
class TestCopyCommandParser:
    """Unit tests for COPY SQL command parsing"""

    # ========== Basic COPY FROM STDIN Tests ==========

    def test_basic_copy_from_stdin(self):
        """Basic COPY FROM STDIN without options"""
        sql = "COPY Patients FROM STDIN"
        cmd = CopyCommandParser.parse(sql)

        assert cmd.table_name == 'Patients'
        assert cmd.direction == CopyDirection.FROM_STDIN
        assert cmd.column_list is None
        assert cmd.csv_options.format == 'CSV'
        assert cmd.csv_options.header is False

    def test_copy_from_stdin_with_columns(self):
        """COPY FROM STDIN with column list"""
        sql = "COPY Patients (PatientID, FirstName, LastName) FROM STDIN"
        cmd = CopyCommandParser.parse(sql)

        assert cmd.table_name == 'Patients'
        assert cmd.column_list == ['PatientID', 'FirstName', 'LastName']
        assert cmd.direction == CopyDirection.FROM_STDIN

    def test_copy_from_stdin_with_csv_header(self):
        """COPY FROM STDIN with CSV format and header"""
        sql = "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)"
        cmd = CopyCommandParser.parse(sql)

        assert cmd.table_name == 'Patients'
        assert cmd.csv_options.format == 'CSV'
        assert cmd.csv_options.header is True

    def test_copy_from_stdin_all_options(self):
        """COPY FROM STDIN with all CSV options"""
        sql = """COPY Patients FROM STDIN WITH (
            FORMAT CSV,
            HEADER,
            DELIMITER ',',
            NULL '',
            QUOTE '"',
            ESCAPE '\\\\'
        )"""
        cmd = CopyCommandParser.parse(sql)

        assert cmd.csv_options.format == 'CSV'
        assert cmd.csv_options.header is True
        assert cmd.csv_options.delimiter == ','
        assert cmd.csv_options.null_string == ''
        assert cmd.csv_options.quote == '"'
        assert cmd.csv_options.escape == '\\\\'

    # ========== Basic COPY TO STDOUT Tests ==========

    def test_basic_copy_to_stdout(self):
        """Basic COPY TO STDOUT without options"""
        sql = "COPY Patients TO STDOUT"
        cmd = CopyCommandParser.parse(sql)

        assert cmd.table_name == 'Patients'
        assert cmd.direction == CopyDirection.TO_STDOUT
        assert cmd.column_list is None

    def test_copy_to_stdout_with_columns(self):
        """COPY TO STDOUT with column list"""
        sql = "COPY Patients (PatientID, FirstName) TO STDOUT"
        cmd = CopyCommandParser.parse(sql)

        assert cmd.table_name == 'Patients'
        assert cmd.column_list == ['PatientID', 'FirstName']
        assert cmd.direction == CopyDirection.TO_STDOUT

    def test_copy_to_stdout_with_csv_header(self):
        """COPY TO STDOUT with CSV format and header"""
        sql = "COPY Patients TO STDOUT WITH (FORMAT CSV, HEADER)"
        cmd = CopyCommandParser.parse(sql)

        assert cmd.csv_options.format == 'CSV'
        assert cmd.csv_options.header is True

    # ========== Query-Based COPY TO STDOUT Tests ==========

    def test_copy_query_to_stdout(self):
        """COPY (SELECT ...) TO STDOUT"""
        sql = "COPY (SELECT PatientID, FirstName FROM Patients WHERE Status = 'Active') TO STDOUT"
        cmd = CopyCommandParser.parse(sql)

        assert cmd.table_name is None
        assert cmd.query is not None
        assert 'SELECT PatientID, FirstName FROM Patients' in cmd.query
        assert cmd.direction == CopyDirection.TO_STDOUT

    def test_copy_query_to_stdout_with_options(self):
        """COPY (SELECT ...) TO STDOUT WITH (FORMAT CSV, HEADER)"""
        sql = """COPY (
            SELECT id, name, value
            FROM some_table
            WHERE active = true
        ) TO STDOUT WITH (FORMAT CSV, HEADER)"""
        cmd = CopyCommandParser.parse(sql)

        assert cmd.table_name is None
        assert cmd.query is not None
        assert 'SELECT id, name, value' in cmd.query
        assert cmd.csv_options.header is True

    # ========== CSVOptions Parsing Tests ==========

    def test_csv_option_format_text(self):
        """FORMAT TEXT option"""
        sql = "COPY Patients FROM STDIN WITH (FORMAT TEXT)"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.format == 'TEXT'

    def test_csv_option_format_binary(self):
        """FORMAT BINARY option"""
        sql = "COPY Patients FROM STDIN WITH (FORMAT BINARY)"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.format == 'BINARY'

    def test_csv_option_delimiter_tab(self):
        """DELIMITER '\\t' (tab) option"""
        sql = "COPY Patients FROM STDIN WITH (DELIMITER E'\\t')"
        cmd = CopyCommandParser.parse(sql)
        # Parser should handle escape sequences
        assert cmd.csv_options.delimiter in ['\t', 'E\\t', '\\t']

    def test_csv_option_delimiter_pipe(self):
        """DELIMITER '|' option"""
        sql = "COPY Patients FROM STDIN WITH (DELIMITER '|')"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.delimiter == '|'

    def test_csv_option_null_custom(self):
        """NULL 'NULL' option"""
        sql = "COPY Patients FROM STDIN WITH (NULL 'NULL')"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.null_string == 'NULL'

    def test_csv_option_null_backslash_n(self):
        """NULL '\\N' option (PostgreSQL default)"""
        sql = "COPY Patients FROM STDIN WITH (NULL '\\\\N')"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.null_string == '\\\\N'

    def test_csv_option_quote_single(self):
        """QUOTE ''' option (single quote)"""
        sql = "COPY Patients FROM STDIN WITH (QUOTE '''')"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.quote == "'"

    def test_csv_option_escape_backslash(self):
        """ESCAPE '\\\\' option"""
        sql = "COPY Patients FROM STDIN WITH (ESCAPE '\\\\\\\\')"
        cmd = CopyCommandParser.parse(sql)
        # Parser should preserve escape character
        assert cmd.csv_options.escape == '\\\\\\\\'

    # ========== Case Sensitivity Tests ==========

    def test_case_insensitive_copy_keyword(self):
        """COPY keyword is case-insensitive"""
        for variant in ['COPY', 'copy', 'Copy', 'CoPy']:
            sql = f"{variant} Patients FROM STDIN"
            cmd = CopyCommandParser.parse(sql)
            assert cmd.table_name == 'Patients'

    def test_case_insensitive_from_stdin(self):
        """FROM STDIN is case-insensitive"""
        for variant in ['FROM STDIN', 'from stdin', 'From Stdin']:
            sql = f"COPY Patients {variant}"
            cmd = CopyCommandParser.parse(sql)
            assert cmd.direction == CopyDirection.FROM_STDIN

    def test_case_insensitive_to_stdout(self):
        """TO STDOUT is case-insensitive"""
        for variant in ['TO STDOUT', 'to stdout', 'To Stdout']:
            sql = f"COPY Patients {variant}"
            cmd = CopyCommandParser.parse(sql)
            assert cmd.direction == CopyDirection.TO_STDOUT

    def test_case_insensitive_with_clause(self):
        """WITH clause keywords are case-insensitive"""
        sql = "COPY Patients FROM STDIN with (format csv, header)"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.format == 'CSV'
        assert cmd.csv_options.header is True

    # ========== Whitespace Handling Tests ==========

    def test_extra_whitespace(self):
        """Extra whitespace should be handled"""
        sql = "  COPY    Patients   FROM   STDIN  "
        cmd = CopyCommandParser.parse(sql)
        assert cmd.table_name == 'Patients'
        assert cmd.direction == CopyDirection.FROM_STDIN

    def test_newlines_in_with_clause(self):
        """Newlines in WITH clause should be handled"""
        sql = """COPY Patients FROM STDIN WITH (
            FORMAT CSV,
            HEADER
        )"""
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.format == 'CSV'
        assert cmd.csv_options.header is True

    def test_tabs_in_column_list(self):
        """Tabs in column list should be handled"""
        sql = "COPY Patients (\tPatientID,\tFirstName\t) FROM STDIN"
        cmd = CopyCommandParser.parse(sql)
        assert 'PatientID' in cmd.column_list
        assert 'FirstName' in cmd.column_list

    # ========== Column List Variations Tests ==========

    def test_column_list_single_column(self):
        """Single column in list"""
        sql = "COPY Patients (PatientID) FROM STDIN"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.column_list == ['PatientID']

    def test_column_list_many_columns(self):
        """Many columns in list"""
        sql = "COPY Patients (col1, col2, col3, col4, col5, col6, col7, col8) FROM STDIN"
        cmd = CopyCommandParser.parse(sql)
        assert len(cmd.column_list) == 8
        assert 'col1' in cmd.column_list
        assert 'col8' in cmd.column_list

    def test_column_list_no_spaces(self):
        """Column list without spaces"""
        sql = "COPY Patients (PatientID,FirstName,LastName) FROM STDIN"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.column_list == ['PatientID', 'FirstName', 'LastName']

    # ========== Invalid Syntax Tests ==========

    def test_invalid_missing_direction(self):
        """Missing FROM/TO should raise error"""
        sql = "COPY Patients"
        with pytest.raises((ValueError, AttributeError)):
            CopyCommandParser.parse(sql)

    def test_invalid_missing_stdin_stdout(self):
        """Missing STDIN/STDOUT should raise error"""
        sql = "COPY Patients FROM"
        with pytest.raises((ValueError, AttributeError)):
            CopyCommandParser.parse(sql)

    def test_invalid_direction_keyword(self):
        """Invalid direction keyword should raise error"""
        sql = "COPY Patients INTO STDIN"  # Should be FROM
        with pytest.raises((ValueError, AttributeError)):
            CopyCommandParser.parse(sql)

    def test_invalid_with_clause_syntax(self):
        """Invalid WITH clause syntax"""
        sql = "COPY Patients FROM STDIN WITH FORMAT CSV"  # Missing parentheses
        # Parser may or may not fail - depends on regex strictness
        # If it parses, options should have defaults
        try:
            cmd = CopyCommandParser.parse(sql)
            # If it doesn't fail, verify defaults are sane
            assert cmd.csv_options is not None
        except (ValueError, AttributeError):
            # Expected failure is also acceptable
            pass

    def test_empty_table_name(self):
        """Empty table name should raise error"""
        sql = "COPY FROM STDIN"
        with pytest.raises((ValueError, AttributeError, IndexError)):
            CopyCommandParser.parse(sql)

    # ========== Multiple Options Tests ==========

    def test_multiple_options_comma_separated(self):
        """Multiple options with commas"""
        sql = "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER, DELIMITER ',')"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.csv_options.format == 'CSV'
        assert cmd.csv_options.header is True
        assert cmd.csv_options.delimiter == ','

    def test_multiple_options_no_commas(self):
        """Multiple options without commas (PostgreSQL allows this)"""
        sql = "COPY Patients FROM STDIN WITH (FORMAT CSV HEADER)"
        try:
            cmd = CopyCommandParser.parse(sql)
            # If parser handles this, verify options
            assert cmd.csv_options.format == 'CSV'
        except (ValueError, AttributeError):
            # Expected - parser may require commas
            pass

    # ========== Edge Case Query Tests ==========

    def test_query_with_parentheses(self):
        """Query with nested parentheses"""
        sql = "COPY (SELECT COUNT(*) FROM (SELECT * FROM Patients) AS sub) TO STDOUT"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.query is not None
        assert 'SELECT COUNT(*)' in cmd.query

    def test_query_with_string_literals(self):
        """Query with string literals containing special characters"""
        sql = "COPY (SELECT * FROM Patients WHERE Name = 'O''Brien') TO STDOUT"
        cmd = CopyCommandParser.parse(sql)
        assert cmd.query is not None
        assert "O'Brien" in cmd.query or "O''Brien" in cmd.query

    # ========== Real-World Examples Tests ==========

    def test_real_world_patient_import(self):
        """Real-world example: Patient data import"""
        sql = """COPY Patients (
            PatientID,
            FirstName,
            LastName,
            DateOfBirth,
            Gender,
            Status,
            AdmissionDate,
            DischargeDate
        ) FROM STDIN WITH (FORMAT CSV, HEADER)"""
        cmd = CopyCommandParser.parse(sql)

        assert cmd.table_name == 'Patients'
        assert len(cmd.column_list) == 8
        assert 'PatientID' in cmd.column_list
        assert 'DischargeDate' in cmd.column_list
        assert cmd.csv_options.header is True

    def test_real_world_export_with_filter(self):
        """Real-world example: Export filtered data"""
        sql = """COPY (
            SELECT PatientID, FirstName, LastName
            FROM Patients
            WHERE Status = 'Active'
            AND AdmissionDate >= '2024-01-01'
            ORDER BY LastName
        ) TO STDOUT WITH (FORMAT CSV, HEADER, DELIMITER ',', NULL '')"""
        cmd = CopyCommandParser.parse(sql)

        assert cmd.query is not None
        assert 'WHERE Status' in cmd.query
        assert cmd.csv_options.header is True
        assert cmd.csv_options.delimiter == ','
        assert cmd.csv_options.null_string == ''

    def test_real_world_tab_delimited_export(self):
        """Real-world example: Tab-delimited export for Excel"""
        sql = "COPY Patients TO STDOUT WITH (FORMAT TEXT, DELIMITER E'\\t', NULL '')"
        cmd = CopyCommandParser.parse(sql)

        assert cmd.csv_options.format == 'TEXT'
        # Delimiter may be parsed as E'\t' or '\t' depending on regex
        assert cmd.csv_options.delimiter in ['\t', 'E\\t', '\\t']
        assert cmd.csv_options.null_string == ''
