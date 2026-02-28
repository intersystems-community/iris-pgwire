"""
CSV Processing for COPY Protocol

Implements CSV parsing and generation with batching for memory efficiency.

Constitutional Requirements:
- FR-006: <100MB memory for 1M rows (requires 1000-row batching)
- FR-007: Validate CSV format, report line numbers on error
"""

import csv
import io
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from .column_validator import ColumnNameValidator
from .sql_translator.copy_parser import CSVOptions

logger = logging.getLogger(__name__)


class CSVParsingError(Exception):
    """CSV parsing error with line number."""

    def __init__(self, message: str, line_number: int):
        self.message = message
        self.line_number = line_number
        super().__init__(f"CSV parse error at line {line_number}: {message}")


@dataclass
class CSVBatch:
    """Batch of CSV rows for memory-efficient processing."""

    rows: list[dict]
    batch_number: int
    total_bytes: int


class CSVProcessor:
    """
    CSV parsing and generation with batching.

    Batching Strategy:
    - Accumulate 1000 rows or 10MB before yielding batch
    - Prevents memory exhaustion for large datasets
    """

    # Constants
    BATCH_SIZE_ROWS = 1000
    BATCH_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

    async def parse_csv_rows(
        self, csv_stream: AsyncIterator[bytes], options: CSVOptions
    ) -> AsyncIterator[dict]:
        """
        Parse CSV bytes stream to row dicts with batching.

        Args:
            csv_stream: Async iterator of CSV bytes
            options: CSV format options (delimiter, quote, escape, header)

        Yields:
            Row dicts with column names as keys

        Raises:
            CSVParsingError: Malformed CSV with line number
        """
        logger.debug(f"Parsing CSV: header={options.header}, delimiter='{options.delimiter}'")

        # Accumulate bytes into buffer
        buffer = b""
        column_names = None
        line_number = 0
        rows_yielded = 0
        chunks_received = 0

        async for chunk in csv_stream:
            chunks_received += 1
            buffer += chunk
            logger.debug(
                f"CSV chunk #{chunks_received}: {len(chunk)} bytes, buffer now {len(buffer)} bytes"
            )

            # Process complete lines from buffer
            while b"\n" in buffer:
                # Extract one line
                line_end = buffer.index(b"\n") + 1
                line_bytes = buffer[:line_end]
                buffer = buffer[line_end:]

                line_number += 1

                try:
                    # Decode line
                    line_text = line_bytes.decode("utf-8").rstrip("\r\n")

                    if not line_text.strip():
                        continue  # Skip empty lines

                    csv_reader = csv.reader(
                        [line_text],
                        delimiter=options.delimiter,
                        quotechar=options.quote,
                        escapechar=options.escape if options.escape != "\\" else None,
                    )
                    row_values = next(csv_reader)

                    row_dict, column_names = self._process_row_values(
                        row_values, options, column_names, line_number
                    )

                    if row_dict is not None:
                        yield row_dict
                        rows_yielded += 1

                except csv.Error as e:
                    raise CSVParsingError(str(e), line_number)
                except UnicodeDecodeError as e:
                    raise CSVParsingError(f"Invalid UTF-8: {e}", line_number)

        # Process remaining buffer (last line without \n)
        if buffer:
            line_number += 1
            row_dict, column_names = self._process_remaining_buffer(
                buffer, column_names, line_number, options
            )
            if row_dict is not None:
                yield row_dict
                rows_yielded += 1

        logger.info(
            f"CSV parsing complete: {chunks_received} chunks received, {rows_yielded} rows yielded"
        )

    def _process_remaining_buffer(
        self,
        buffer: bytes,
        column_names: list[str] | None,
        line_number: int,
        options: CSVOptions,
    ) -> tuple[dict | None, list[str] | None]:
        """
        Process the trailing buffer content (last line without trailing newline).

        Args:
            buffer: Remaining bytes after main loop
            column_names: Current column names (may be None)
            line_number: Current line number for error reporting
            options: CSV format options

        Returns:
            Tuple of (row_dict or None, updated column_names)

        Raises:
            CSVParsingError: If the remaining buffer contains malformed CSV
        """
        try:
            line_text = buffer.decode("utf-8").rstrip("\r\n")
            if not line_text.strip():
                return None, column_names

            csv_reader = csv.reader(
                [line_text],
                delimiter=options.delimiter,
                quotechar=options.quote,
                escapechar=options.escape if options.escape != "\\" else None,
            )
            row_values = next(csv_reader)

            return self._process_row_values(row_values, options, column_names, line_number)

        except CSVParsingError:
            raise
        except Exception as e:
            raise CSVParsingError(str(e), line_number)

    def _process_row_values(
        self,
        row_values: list[str],
        options: CSVOptions,
        column_names: list[str] | None,
        line_number: int,
    ) -> tuple[dict | None, list[str] | None]:
        """Validate row values and build a row dict if applicable."""

        if options.header and column_names is None:
            column_names = ColumnNameValidator.validate_column_list(row_values)
            logger.debug(f"CSV header (validated): {column_names}")
            return None, column_names

        if column_names is None:
            column_names = [f"column_{i}" for i in range(len(row_values))]

        if len(row_values) != len(column_names):
            raise CSVParsingError(
                f"Expected {len(column_names)} columns, got {len(row_values)}",
                line_number,
            )

        row_dict = self._build_row_dict(column_names, row_values, options.null_string)
        return row_dict, column_names

    def _build_row_dict(
        self, column_names: list[str], row_values: list[str], null_string: str
    ) -> dict:
        """Build a dict from columns and values, applying NULL conversions."""

        row_dict: dict[str, str | None] = {}
        for col_name, col_value in zip(column_names, row_values, strict=False):
            row_dict[col_name] = None if col_value == null_string else col_value
        return row_dict

    async def generate_csv_rows(
        self, result_rows: AsyncIterator[tuple], column_names: list[str], options: CSVOptions
    ) -> AsyncIterator[bytes]:
        """
        Generate CSV bytes from result row tuples.

        Args:
            result_rows: Async iterator of row tuples
            column_names: Column names for header row
            options: CSV format options

        Yields:
            CSV data bytes (batched for efficiency)
        """
        logger.debug(f"Generating CSV: header={options.header}, columns={len(column_names)}")

        buffer = io.StringIO()
        csv_writer = csv.writer(
            buffer,
            delimiter=options.delimiter,
            quotechar=options.quote,
            escapechar=options.escape if options.escape != "\\" else None,
            quoting=csv.QUOTE_MINIMAL,
        )

        rows_generated = 0

        # Write header row if requested
        if options.header and column_names:
            csv_writer.writerow(column_names)
            rows_generated += 1

        # Write data rows
        batch_rows = 0
        async for row_tuple in result_rows:
            # Convert tuple to list, handle NULLs
            row_values = []
            for value in row_tuple:
                if value is None:
                    row_values.append(options.null_string)
                else:
                    row_values.append(str(value))

            csv_writer.writerow(row_values)
            rows_generated += 1
            batch_rows += 1

            # Yield batch when buffer reaches 8KB (or every 100 rows)
            if buffer.tell() >= 8192 or batch_rows >= 100:
                csv_bytes = buffer.getvalue().encode("utf-8")
                yield csv_bytes

                # Reset buffer
                buffer = io.StringIO()
                csv_writer = csv.writer(
                    buffer,
                    delimiter=options.delimiter,
                    quotechar=options.quote,
                    quoting=csv.QUOTE_MINIMAL,
                )
                batch_rows = 0

        # Yield remaining data
        if buffer.tell() > 0:
            csv_bytes = buffer.getvalue().encode("utf-8")
            yield csv_bytes

        logger.info(f"CSV generation complete: {rows_generated} rows generated")
