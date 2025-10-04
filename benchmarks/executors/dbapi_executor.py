"""
IRIS + DBAPI query executor (T018).

Executes queries via intersystems-irispython DBAPI.
Pattern from: /Users/tdyar/ws/rag-templates/common/iris_connection_manager.py
"""

from typing import Any, Optional


class DbapiExecutor:
    """Execute queries against IRIS via DBAPI (intersystems-irispython)."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 1972,
        namespace: str = "USER",
        username: str = "_SYSTEM",
        password: str = "SYS"
    ):
        """
        Initialize IRIS DBAPI executor.

        Args:
            host: IRIS host
            port: IRIS SuperServer port (default 1972)
            namespace: IRIS namespace
            username: IRIS username
            password: IRIS password
        """
        self.host = host
        self.port = port
        self.namespace = namespace
        self.username = username
        self.password = password
        self.connection: Optional[Any] = None

    def connect(self):
        """Establish DBAPI connection to IRIS."""
        if self.connection is None:
            import iris

            # DBAPI connection pattern from rag-templates
            self.connection = iris.connect(
                hostname=self.host,
                port=self.port,
                namespace=self.namespace,
                username=self.username,
                password=self.password
            )

    def execute(self, query: str) -> Any:
        """
        Execute SQL query using IRIS DBAPI.

        Args:
            query: SQL query string (IRIS SQL dialect)

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
            results = cursor.fetchall()
            cursor.close()
            return results
        except Exception as e:
            cursor.close()
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
