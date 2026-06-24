"""
IRIS + PGWire query executor (T016).

Executes queries via psycopg3 to PGWire server.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import psycopg


@dataclass
class QueryResult:
    """Result of a query execution via PGWireExecutor."""

    status: str  # "SUCCESS", "ERROR", "TIMEOUT"
    elapsed_time_ms: float = 0.0
    row_count: int = 0
    rows: list = field(default_factory=list)
    error_message: str | None = None


class PGWireExecutor:
    """Execute queries against IRIS via PostgreSQL wire protocol."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "USER",
        timeout_seconds: int = 30,
    ):
        """
        Initialize PGWire executor.

        Args:
            host: PGWire server host
            port: PGWire server port (default 5432)
            database: IRIS namespace
            timeout_seconds: Query timeout in seconds
        """
        self.host = host
        self.port = port
        self.database = database
        self.timeout_seconds = timeout_seconds
        self.connection: psycopg.Connection | None = None

    def connect(self):
        """Establish connection to PGWire server."""
        if self.connection is None:
            self.connection = psycopg.connect(
                host=self.host, port=self.port, dbname=self.database, connect_timeout=10
            )

    def execute(self, query: str) -> Any:
        """
        Execute SQL query.

        Args:
            query: SQL query string

        Returns:
            Query results

        Raises:
            ConnectionError: If connection fails
        """
        if self.connection is None:
            self.connect()

        cursor = self.connection.cursor()
        try:
            cursor.execute(query)

            # Check if query returns results (cursor.description is None for non-SELECT)
            if cursor.description is None:
                cursor.close()
                return []

            results = cursor.fetchall()
            cursor.close()
            return results
        except Exception:
            cursor.close()
            raise

    def execute_with_timeout(self, query: str) -> QueryResult:
        """Execute SQL query with timeout protection.

        Args:
            query: SQL query string

        Returns:
            QueryResult with status ("SUCCESS", "ERROR", "TIMEOUT"), elapsed_time_ms,
            row_count, rows, and error_message
        """
        start = time.perf_counter()
        try:
            self.connect()
            cursor = self.connection.cursor()
            try:
                cursor.execute(query)
                rows = []
                if cursor.description is not None:
                    rows = cursor.fetchall()
                cursor.close()
                elapsed_ms = (time.perf_counter() - start) * 1000
                if elapsed_ms > self.timeout_seconds * 1000:
                    return QueryResult(
                        status="TIMEOUT",
                        elapsed_time_ms=elapsed_ms,
                        error_message=f"Query exceeded {self.timeout_seconds}s timeout",
                    )
                return QueryResult(
                    status="SUCCESS",
                    elapsed_time_ms=elapsed_ms,
                    row_count=len(rows),
                    rows=rows,
                )
            except Exception as e:
                cursor.close()
                elapsed_ms = (time.perf_counter() - start) * 1000
                return QueryResult(
                    status="ERROR",
                    elapsed_time_ms=elapsed_ms,
                    error_message=str(e),
                )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return QueryResult(
                status="ERROR",
                elapsed_time_ms=elapsed_ms,
                error_message=str(e),
            )

    def close(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
