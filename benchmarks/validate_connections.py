"""
Connection validation script for 3-way benchmark (T009).

Per FR-006: Abort with clear error if any connection fails.
Validates all three database methods before benchmark execution.
"""

import sys
from typing import Dict, Optional
import psycopg


def validate_iris_pgwire(host: str = "localhost", port: int = 5432, database: str = "USER") -> Optional[str]:
    """
    Validate IRIS + PGWire connection.

    Args:
        host: PGWire server host
        port: PGWire server port (default 5432)
        database: IRIS namespace

    Returns:
        None if successful, error message if failed
    """
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=database,
            connect_timeout=10
        )
        conn.close()
        return None
    except Exception as e:
        return f"IRIS + PGWire connection failed: {e}"


def validate_postgresql_psycopg3(
    host: str = "localhost",
    port: int = 5433,
    database: str = "benchmark",
    username: str = "postgres",
    password: str = "postgres"
) -> Optional[str]:
    """
    Validate PostgreSQL + psycopg3 connection.

    Args:
        host: PostgreSQL host
        port: PostgreSQL port (default 5433 for benchmark container)
        database: Database name
        username: PostgreSQL username
        password: PostgreSQL password

    Returns:
        None if successful, error message if failed
    """
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=database,
            user=username,
            password=password,
            connect_timeout=10
        )
        # Verify pgvector extension
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            if not cur.fetchone():
                return "pgvector extension not installed in PostgreSQL"
        conn.close()
        return None
    except Exception as e:
        return f"PostgreSQL + psycopg3 connection failed: {e}"


def validate_iris_dbapi(
    host: str = None,
    port: int = None,
    namespace: str = "USER",
    username: str = "_SYSTEM",
    password: str = "SYS"
) -> Optional[str]:
    """
    Validate IRIS + DBAPI connection using intersystems-irispython package.

    Args:
        host: IRIS host (defaults to IRIS_HOST env var or localhost)
        port: IRIS SuperServer port (defaults to IRIS_PORT env var or 1972)
        namespace: IRIS namespace
        username: IRIS username
        password: IRIS password

    Returns:
        None if successful, error message if failed
    """
    try:
        # Import IRIS DBAPI from intersystems-irispython package
        import iris
        import os

        # Get connection params from environment if not provided
        if host is None:
            host = os.environ.get("IRIS_HOST", "localhost")
        if port is None:
            port = int(os.environ.get("IRIS_PORT", "1972"))

        # Verify iris.connect is available (not iris.sql.exec for embedded Python)
        if not hasattr(iris, "connect"):
            return "IRIS DBAPI connection failed: iris.connect() not available. " \
                   "Install intersystems-irispython package."

        # Create DBAPI connection
        connection = iris.connect(
            hostname=host,
            port=port,
            namespace=namespace,
            username=username,
            password=password
        )

        # Test the connection with a simple query
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()

        # Close resources before checking result
        cursor.close()
        connection.close()

        # DataRow objects are always truthy, so we just check if we got one
        if result is None:
            return "IRIS DBAPI connection test failed: no result from SELECT 1"

        return None

    except ImportError:
        return "intersystems-irispython package not available. Install with: uv pip install intersystems-irispython"
    except AttributeError as e:
        return f"IRIS DBAPI not properly configured: {e}"
    except Exception as e:
        return f"IRIS + DBAPI connection failed: {e}"


def validate_all_connections() -> Dict[str, Optional[str]]:
    """
    Validate all three database connections.

    Returns:
        Dictionary mapping method name to error message (None if successful)
    """
    return {
        "iris_pgwire": validate_iris_pgwire(),
        "postgresql_psycopg3": validate_postgresql_psycopg3(),
        "iris_dbapi": validate_iris_dbapi(),
    }


def main():
    """
    CLI entry point for connection validation.

    Per FR-006: Abort with clear error if any connection fails.
    """
    print("Validating database connections...")
    print()

    results = validate_all_connections()
    failures = {method: error for method, error in results.items() if error is not None}

    if not failures:
        print("✅ IRIS + PGWire connection successful (localhost:5432)")
        print("✅ PostgreSQL + psycopg3 connection successful (localhost:5433)")
        print("✅ IRIS + DBAPI connection successful (localhost:1972)")
        print()
        print("All three database methods ready for benchmarking.")
        return 0
    else:
        print("❌ Connection validation failed:")
        print()
        for method, error in failures.items():
            print(f"  {method}: {error}")
        print()
        print("Fix connection issues before running benchmark.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
