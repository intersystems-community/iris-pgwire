"""
Unit Tests: CSV Processor Edge Cases

Tests CSVProcessor parsing and generation with comprehensive edge case coverage.

Coverage:
- Empty CSV files
- Single row CSV
- Special characters (quotes, commas, newlines)
- NULL value handling
- CSVOptions variations (delimiter, quote, escape)
- Unicode/UTF-8 edge cases
- Malformed CSV (missing quotes, extra columns)
- Header handling variations
- Large field values
- Whitespace handling

Constitutional Requirement (Principle II): Test-First Development
- Tests written BEFORE implementation (but implementation already exists)
- Validates existing CSVProcessor implementation
"""

import pytest
from iris_pgwire.csv_processor import CSVProcessor, CSVParsingError
from iris_pgwire.sql_translator.copy_parser import CSVOptions


@pytest.mark.unit
@pytest.mark.asyncio
class TestCSVProcessorEdgeCases:
    """Edge case tests for CSV parsing and generation"""

    # ========== Empty and Single Row Tests ==========

    async def test_parse_empty_csv(self):
        """Empty CSV should yield no rows"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=False)

        async def empty_stream():
            if False:
                yield

        rows = [row async for row in processor.parse_csv_rows(empty_stream(), options)]
        assert rows == []

    async def test_parse_single_row_no_header(self):
        """Single row without header should yield one row"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=False)

        async def csv_stream():
            yield b"1,John,Smith\n"

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['column_0'] == '1'
        assert rows[0]['column_1'] == 'John'
        assert rows[0]['column_2'] == 'Smith'

    async def test_parse_single_row_with_header(self):
        """Single row with header should yield zero data rows"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b"ID,FirstName,LastName\n"

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 0  # Header only, no data

    async def test_parse_header_plus_one_row(self):
        """Header + one data row should yield one row"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b"ID,FirstName,LastName\n"
            yield b"1,John,Smith\n"

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['ID'] == '1'
        assert rows[0]['FirstName'] == 'John'
        assert rows[0]['LastName'] == 'Smith'

    # ========== Special Characters Tests ==========

    async def test_parse_quoted_commas(self):
        """Commas inside quotes should be preserved"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b'Name,Address\n'
            yield b'"Smith, John","123 Main St, Apt 4"\n'

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['Name'] == 'Smith, John'
        assert rows[0]['Address'] == '123 Main St, Apt 4'

    async def test_parse_quoted_newlines_limitation(self):
        """KNOWN LIMITATION: Newlines inside quotes cause column count mismatch

        The CSV processor uses line-by-line processing (split on \\n), so multi-line
        quoted fields are not supported. This is a documented limitation for memory
        efficiency (streaming without buffering entire fields).

        PostgreSQL COPY protocol itself doesn't commonly use multi-line fields,
        so this limitation is acceptable for the bulk data use case.
        """
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            # Multi-line quoted field - will be split across lines
            yield b'Name,Description\n'
            yield b'"John Smith","Line 1\nLine 2\nLine 3"\n'

        # Expect CSVParsingError due to column count mismatch
        with pytest.raises(CSVParsingError) as exc_info:
            rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]

        assert exc_info.value.line_number > 0
        assert 'Expected 2 columns' in str(exc_info.value)

    async def test_parse_escaped_quotes(self):
        """Escaped quotes should be handled correctly"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True, quote='"')

        async def csv_stream():
            yield b'Name,Quote\n'
            yield b'"John Smith","He said ""Hello"""\n'

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['Name'] == 'John Smith'
        # Python csv module unescapes "" to "
        assert '"' in rows[0]['Quote']

    async def test_parse_unicode_characters(self):
        """Unicode characters should be preserved"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            # UTF-8 encoded unicode: café, 日本語, émojis
            yield "Name,City,Emoji\n".encode('utf-8')
            yield "François,São Paulo,🎉\n".encode('utf-8')

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['Name'] == 'François'
        assert rows[0]['City'] == 'São Paulo'
        assert rows[0]['Emoji'] == '🎉'

    # ========== NULL Value Handling Tests ==========

    async def test_parse_null_values_default(self):
        """Default NULL string ('') should be converted to None"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True, null_string='')

        async def csv_stream():
            yield b'ID,Name,Age\n'
            yield b'1,John,\n'  # Empty string for Age

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['ID'] == '1'
        assert rows[0]['Name'] == 'John'
        assert rows[0]['Age'] is None  # Empty string → NULL

    async def test_parse_null_values_custom(self):
        """Custom NULL string ('NULL') should be converted to None"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True, null_string='NULL')

        async def csv_stream():
            yield b'ID,Name,Age\n'
            yield b'1,John,NULL\n'

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['Age'] is None

    async def test_generate_null_values(self):
        """None values should be converted to NULL string"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True, null_string='NULL')

        async def result_rows():
            yield (1, 'John', None)  # None value for third column

        chunks = [chunk async for chunk in processor.generate_csv_rows(
            result_rows(), ['ID', 'Name', 'Age'], options
        )]

        csv_output = b''.join(chunks).decode('utf-8')
        assert 'ID,Name,Age' in csv_output
        assert '1,John,NULL' in csv_output

    # ========== CSVOptions Variations Tests ==========

    async def test_parse_custom_delimiter(self):
        """Custom delimiter (tab) should work correctly"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True, delimiter='\t')

        async def csv_stream():
            yield b'ID\tName\tAge\n'
            yield b'1\tJohn\t30\n'

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['ID'] == '1'
        assert rows[0]['Name'] == 'John'
        assert rows[0]['Age'] == '30'

    async def test_parse_custom_quote_char(self):
        """Custom quote character (single quote) should work"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True, quote="'")

        async def csv_stream():
            yield b"Name,City\n"
            yield b"'Smith, John','New York'\n"

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert rows[0]['Name'] == 'Smith, John'
        assert rows[0]['City'] == 'New York'

    async def test_generate_custom_delimiter(self):
        """CSV generation should use custom delimiter"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True, delimiter='|')

        async def result_rows():
            yield (1, 'John', 30)

        chunks = [chunk async for chunk in processor.generate_csv_rows(
            result_rows(), ['ID', 'Name', 'Age'], options
        )]

        csv_output = b''.join(chunks).decode('utf-8')
        assert 'ID|Name|Age' in csv_output
        assert '1|John|30' in csv_output

    # ========== Malformed CSV Tests ==========

    async def test_parse_column_count_mismatch(self):
        """Mismatched column count should raise CSVParsingError with line number"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b'ID,Name,Age\n'
            yield b'1,John,30\n'  # Valid
            yield b'2,Mary\n'     # Missing Age column

        with pytest.raises(CSVParsingError) as exc_info:
            rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]

        assert exc_info.value.line_number == 3
        assert 'Expected 3 columns' in str(exc_info.value)

    async def test_parse_unclosed_quote(self):
        """Unclosed quote should raise CSVParsingError"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b'Name,City\n'
            yield b'"John Smith,New York\n'  # Missing closing quote

        with pytest.raises(CSVParsingError) as exc_info:
            rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]

        # Python csv module will detect this as an error
        assert exc_info.value.line_number > 0

    async def test_parse_invalid_utf8(self):
        """Invalid UTF-8 should raise CSVParsingError"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b'Name,City\n'
            yield b'John,\xff\xfe\n'  # Invalid UTF-8 bytes

        with pytest.raises(CSVParsingError) as exc_info:
            rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]

        assert 'UTF-8' in str(exc_info.value) or 'decode' in str(exc_info.value).lower()

    # ========== Large Field Tests ==========

    async def test_parse_large_field_value(self):
        """Large field values (>1KB) should be handled correctly"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        large_text = 'A' * 10000  # 10KB field
        async def csv_stream():
            yield b'ID,LargeText\n'
            yield f'1,"{large_text}"\n'.encode('utf-8')

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        assert len(rows[0]['LargeText']) == 10000
        assert rows[0]['LargeText'] == large_text

    async def test_generate_large_field_value(self):
        """Large field values should be generated correctly"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        large_text = 'B' * 10000
        async def result_rows():
            yield (1, large_text)

        chunks = [chunk async for chunk in processor.generate_csv_rows(
            result_rows(), ['ID', 'LargeText'], options
        )]

        csv_output = b''.join(chunks).decode('utf-8')
        assert large_text in csv_output

    # ========== Whitespace Handling Tests ==========

    async def test_parse_trailing_whitespace(self):
        """Trailing whitespace should be preserved inside fields"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b'Name,City\n'
            yield b'John  ,  New York\n'  # Trailing/leading spaces

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 1
        # CSV parser preserves whitespace
        assert rows[0]['Name'] == 'John  '
        assert rows[0]['City'] == '  New York'

    async def test_parse_empty_lines(self):
        """Empty lines should be skipped"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b'ID,Name\n'
            yield b'\n'  # Empty line
            yield b'1,John\n'
            yield b'\n'  # Another empty line
            yield b'2,Mary\n'

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 2
        assert rows[0]['ID'] == '1'
        assert rows[1]['ID'] == '2'

    # ========== Batching Tests ==========

    async def test_parse_large_csv_batching(self):
        """Large CSV should be processed in batches without memory issues"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        # Generate 10,000 rows
        async def csv_stream():
            yield b'ID,Name,Value\n'
            for i in range(10000):
                yield f'{i},Name{i},Value{i}\n'.encode('utf-8')

        row_count = 0
        async for row in processor.parse_csv_rows(csv_stream(), options):
            row_count += 1
            # Validate some rows
            if row_count == 1:
                assert row['ID'] == '0'
            if row_count == 5000:
                assert row['ID'] == '4999'

        assert row_count == 10000

    async def test_generate_large_csv_batching(self):
        """Large CSV generation should use batching (8KB chunks)"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        # Generate 10,000 rows
        async def result_rows():
            for i in range(10000):
                yield (i, f'Name{i}', f'Value{i}')

        chunks = []
        async for chunk in processor.generate_csv_rows(
            result_rows(), ['ID', 'Name', 'Value'], options
        ):
            chunks.append(chunk)

        # Should produce multiple chunks (not one giant chunk)
        assert len(chunks) > 10  # At least 10 chunks for 10K rows

        # Verify total output
        csv_output = b''.join(chunks).decode('utf-8')
        lines = csv_output.strip().split('\n')
        assert len(lines) == 10001  # Header + 10000 data rows

    # ========== Mixed Line Endings Tests ==========

    async def test_parse_crlf_line_endings(self):
        """Windows-style CRLF line endings should work"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b'ID,Name\r\n'
            yield b'1,John\r\n'
            yield b'2,Mary\r\n'

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 2
        assert rows[0]['Name'] == 'John'
        assert rows[1]['Name'] == 'Mary'

    async def test_parse_mixed_line_endings(self):
        """Mixed LF and CRLF line endings should work"""
        processor = CSVProcessor()
        options = CSVOptions(format='CSV', header=True)

        async def csv_stream():
            yield b'ID,Name\n'      # LF
            yield b'1,John\r\n'     # CRLF
            yield b'2,Mary\n'       # LF

        rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]
        assert len(rows) == 2
