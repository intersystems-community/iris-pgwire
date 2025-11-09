#!/usr/bin/env python3
"""
Test iris-devtester connection to existing iris-pgwire-db container.

This script tests if we can use iris-devtester's connection management
to connect to the running iris-pgwire-db container instead of creating
a new container.
"""

import sys
import os

# Add iris-devtester to path
sys.path.insert(0, "/Users/tdyar/ws/iris-devtester")

try:
    from iris_devtester.connections import get_connection
    from iris_devtester.config import IRISConfig
    print("✓ iris-devtester imported successfully")
except ImportError as e:
    print(f"❌ Failed to import iris-devtester: {e}")
    print("   Make sure iris-devtester is installed:")
    print("   pip install -e ../iris-devtester")
    sys.exit(1)

def test_auto_discovery_connection():
    """Test auto-discovery connection (simplest approach)."""

    print("\n" + "="*60)
    print("TEST 1: Auto-discovery Connection")
    print("="*60)

    try:
        print("\nAttempting auto-discovery connection...")
        dbapi_conn = get_connection()
        print("✓ Auto-discovery connection successful!")

        # Test query
        cursor = dbapi_conn.cursor()
        cursor.execute("SELECT $ZVERSION")
        version = cursor.fetchone()[0]
        print(f"✓ IRIS Version: {version}")

        # Check namespace
        cursor.execute("SELECT $NAMESPACE")
        namespace = cursor.fetchone()[0]
        print(f"✓ Current Namespace: {namespace}")

        cursor.close()
        dbapi_conn.close()

        print("✅ Auto-discovery connection test PASSED")
        return True

    except Exception as e:
        print(f"❌ Auto-discovery failed: {e}")
        print("   Trying explicit configuration...")
        return False

def test_explicit_config_connection():
    """Test explicit configuration connection."""

    print("\n" + "="*60)
    print("TEST 2: Explicit Configuration Connection")
    print("="*60)

    # Connection parameters from docker-compose.yml
    print("\nConnection parameters:")
    print("  Host: localhost")
    print("  Port: 1972")
    print("  Namespace: USER")
    print("  Username: _SYSTEM")

    try:
        # Create IRISConfig with explicit parameters
        print("\nCreating IRISConfig...")
        config = IRISConfig(
            host="localhost",
            port=1972,
            namespace="USER",
            username="_SYSTEM",
            password="SYS"
        )
        print("✓ IRISConfig created")

        # Get DBAPI connection
        print("\nAttempting connection with explicit config...")
        dbapi_conn = get_connection(config)
        print("✓ DBAPI connection established")

        # Test query
        cursor = dbapi_conn.cursor()
        cursor.execute("SELECT $ZVERSION")
        version = cursor.fetchone()[0]
        print(f"✓ IRIS Version: {version}")

        # Check namespace
        cursor.execute("SELECT $NAMESPACE")
        namespace = cursor.fetchone()[0]
        print(f"✓ Current Namespace: {namespace}")

        # Check if Patients table exists
        cursor.execute("""
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME = 'Patients'
        """)
        table_exists = cursor.fetchone()[0]
        print(f"✓ Patients table exists: {bool(table_exists)}")

        cursor.close()
        dbapi_conn.close()

        print("✅ Explicit configuration connection test PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Explicit configuration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n" + "="*60)
    print("Testing iris-devtester connection to iris-pgwire-db")
    print("="*60)

    # Try auto-discovery first (simplest)
    auto_success = test_auto_discovery_connection()

    # If auto-discovery fails, try explicit config
    if not auto_success:
        explicit_success = test_explicit_config_connection()
    else:
        explicit_success = False  # No need to try explicit if auto worked

    # Overall result
    print("\n" + "="*60)
    if auto_success or explicit_success:
        print("✅ SUCCESS: iris-devtester can connect to iris-pgwire-db!")
        if auto_success:
            print("   Method: Auto-discovery (recommended)")
        else:
            print("   Method: Explicit configuration")
        print("="*60)
        sys.exit(0)
    else:
        print("❌ FAILURE: Both connection methods failed")
        print("="*60)
        sys.exit(1)
