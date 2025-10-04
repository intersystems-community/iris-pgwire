"""
PostgreSQL + psycopg3 query executor (T017).

Executes queries via psycopg3 against native PostgreSQL with pgvector.
"""

import psycopg
from typing import Any, Optional


class PostgresExecutor:
    """Execute queries against PostgreSQL with pgvector extension."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5433,
        database: str = "benchmark",
        username: str = "postgres",
        password: str = "postgres"
    ):
        """
        Initialize PostgreSQL executor.

        Args:
            host: PostgreSQL host
            port: PostgreSQL port (default 5433 for benchmark container)
            database: Database name
            username: PostgreSQL username
            password: PostgreSQL password
        """
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.connection: Optional[psycopg.Connection] = None

    def connect(self):
        """Establish connection to PostgreSQL."""
        if self.connection is None:
            self.connection = psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.username,
                password=self.password,
                connect_timeout=10
            )

    def execute(self, query: str) -> Any:
        """
        Execute SQL query.

        Args:
            query: SQL query string (with pgvector operators)

        Returns:
            Query results

        Raises:
            ConnectionError: If connection fails
        """
        if self.connection is None:
            self.connect()

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query)

                # Check if query returns results (cursor.description is None for non-SELECT)
                if cursor.description is None:
                    # Query doesn't return results (e.g., INSERT, UPDATE, DDL)
                    return []

                try:
                    return cursor.fetchall()
                except (psycopg.ProgrammingError, psycopg.errors.InternalError):
                    # Query returned no rows or internal error on fetch
                    return []
        except Exception as e:
            # Re-raise without printing (error logging handled by runner if needed)
            raise

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
