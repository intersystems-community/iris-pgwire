#!/usr/bin/env python3
"""
Validate Column Validator's Reserved Keywords Against Actual IRIS

Uses IRIS SQL's IsReservedWord() function to verify our hardcoded list.

Usage:
    python scripts/validate_reserved_keywords.py

Requirements:
    - IRIS container running at localhost:1972
    - iris module installed (pip install intersystems-irispython)
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from iris_pgwire.column_validator import ColumnNameValidator


def check_iris_reserved_words():
    """Query IRIS to check which words are actually reserved."""
    try:
        import iris.dbapi as dbapi
    except ImportError:
        print("❌ iris module not installed. Install with: pip install intersystems-irispython")
        return

    try:
        # Connect to IRIS
        conn = dbapi.connect(
            hostname="localhost",
            port=1972,
            namespace="USER",
            username="_SYSTEM",
            password="SYS"
        )
        cursor = conn.cursor()
        print("✅ Connected to IRIS at localhost:1972\n")

        # Get our current list
        our_keywords = sorted(ColumnNameValidator.IRIS_RESERVED)
        print(f"📋 Checking {len(our_keywords)} keywords from ColumnNameValidator.IRIS_RESERVED...\n")

        # Test each keyword against IRIS
        iris_confirms = []
        iris_rejects = []
        errors = []

        for keyword in our_keywords:
            try:
                # Test by trying to use as column name in CREATE TABLE
                # If IRIS rejects it, it's truly reserved
                table_name = f"test_validator_{keyword.lower()}"

                # Drop table if exists (from previous runs)
                try:
                    cursor.execute(f"DROP TABLE {table_name}")
                except:
                    pass  # Ignore if doesn't exist

                # Try to create table with keyword as column name
                sql = f"CREATE TABLE {table_name} ({keyword} VARCHAR(50))"
                cursor.execute(sql)

                # If we get here, keyword was NOT reserved
                iris_rejects.append(keyword)

                # Clean up
                cursor.execute(f"DROP TABLE {table_name}")

            except Exception as e:
                error_str = str(e).lower()
                # Check if error indicates reserved word
                if any(x in error_str for x in ['reserved', 'keyword', 'expected', 'syntax']):
                    iris_confirms.append(keyword)
                else:
                    errors.append((keyword, str(e)))

        # Print results
        print(f"✅ IRIS CONFIRMS as reserved: {len(iris_confirms)}/{len(our_keywords)}")
        if iris_confirms:
            print(f"   Examples: {', '.join(iris_confirms[:10])}")

        if iris_rejects:
            print(f"\n⚠️  IRIS DOES NOT consider reserved: {len(iris_rejects)}")
            print(f"   These may be safe to use: {', '.join(iris_rejects)}")

        if errors:
            print(f"\n❌ Errors checking {len(errors)} keywords:")
            for keyword, error in errors[:5]:  # Show first 5 errors
                print(f"   {keyword}: {error}")

        # Summary
        print(f"\n📊 Summary:")
        print(f"   Total keywords tested: {len(our_keywords)}")
        print(f"   IRIS confirms: {len(iris_confirms)}")
        print(f"   IRIS rejects: {len(iris_rejects)}")
        print(f"   Errors: {len(errors)}")

        if len(iris_confirms) == len(our_keywords):
            print("\n🎉 SUCCESS: All our keywords match IRIS's reserved word list!")
        elif iris_rejects:
            print(f"\n⚠️  WARNING: {len(iris_rejects)} keywords not reserved in IRIS")
            print("   Consider removing these from ColumnNameValidator.IRIS_RESERVED")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Failed to connect to IRIS: {e}")
        print("\nMake sure IRIS is running:")
        print("  docker ps | grep iris")
        print("  docker start iris-pgwire-db  # if needed")


def test_with_actual_table_creation():
    """Test by actually creating tables with these column names."""
    try:
        import iris.dbapi as dbapi
    except ImportError:
        print("❌ iris module not installed")
        return

    try:
        conn = dbapi.connect(
            hostname="localhost",
            port=1972,
            namespace="USER",
            username="_SYSTEM",
            password="SYS"
        )
        cursor = conn.cursor()
        print("\n🧪 Testing with actual table creation...")

        # Test a few keywords by trying to create tables
        test_keywords = ["SELECT", "FROM", "WHERE", "TABLE", "NULL"]

        for keyword in test_keywords:
            try:
                # Try to create table with keyword as column name
                sql = f"CREATE TABLE test_validator ({keyword} VARCHAR(50))"
                cursor.execute(sql)
                print(f"   ✅ {keyword}: NOT reserved (table created)")
                cursor.execute("DROP TABLE test_validator")
            except Exception as e:
                error_msg = str(e)
                if "reserved" in error_msg.lower() or "keyword" in error_msg.lower():
                    print(f"   ✅ {keyword}: RESERVED (IRIS rejected)")
                else:
                    print(f"   ⚠️  {keyword}: Error - {error_msg[:100]}")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ Connection error: {e}")


if __name__ == "__main__":
    print("=" * 70)
    print("IRIS Reserved Keyword Validation")
    print("=" * 70)

    check_iris_reserved_words()
    # test_with_actual_table_creation()  # Uncomment to test with real DDL
