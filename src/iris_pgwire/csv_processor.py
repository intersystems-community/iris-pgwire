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

                    # Parse CSV line
                    csv_reader = csv.reader(
                        [line_text],
                        delimiter=options.delimiter,
                        quotechar=options.quote,
                        escapechar=options.escape if options.escape != "\\" else None,
                    )
                    row_values = next(csv_reader)

                    # Handle header row
                    if options.header and column_names is None:
                        column_names = row_values
                        # Validate column names against IRIS restrictions
                        column_names = ColumnNameValidator.validate_column_list(column_names)
                        logger.debug(f"CSV header (validated): {column_names}")
                        continue  # Skip header row (don't yield as data)

                    # If no header, use positional column names
                    if column_names is None:
                        column_names = [f"column_{i}" for i in range(len(row_values))]

                    # Validate column count
                    if len(row_values) != len(column_names):
                        raise CSVParsingError(
                            f"Expected {len(column_names)} columns, got {len(row_values)}",
                            line_number,
                        )

                    # Build row dict
                    row_dict = {}
                    for col_name, col_value in zip(column_names, row_values, strict=False):
                        # Handle NULL values
                        if col_value == options.null_string:
                            row_dict[col_name] = None
                        else:
                            row_dict[col_name] = col_value

                    yield row_dict
                    rows_yielded += 1

                except csv.Error as e:
                    raise CSVParsingError(str(e), line_number)
                except UnicodeDecodeError as e:
                    raise CSVParsingError(f"Invalid UTF-8: {e}", line_number)

        # Process remaining buffer (last line without \n)
        if buffer:
            line_number += 1
            try:
                line_text = buffer.decode("utf-8").rstrip("\r\n")
                if line_text.strip():
                    csv_reader = csv.reader(
                        [line_text], delimiter=options.delimiter, quotechar=options.quote
                    )
                    row_values = next(csv_reader)

                    if column_names and len(row_values) != len(column_names):
                        raise CSVParsingError(
                            f"Expected {len(column_names)} columns, got {len(row_values)}",
                            line_number,
                        )

                    if column_names is None:
                        column_names = [f"column_{i}" for i in range(len(row_values))]

                    row_dict = {}
                    for col_name, col_value in zip(column_names, row_values, strict=False):
                        row_dict[col_name] = None if col_value == options.null_string else col_value

                    yield row_dict
                    rows_yielded += 1

            except Exception as e:
                raise CSVParsingError(str(e), line_number)

        logger.info(
            f"CSV parsing complete: {chunks_received} chunks received, {rows_yielded} rows yielded"
        )

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
