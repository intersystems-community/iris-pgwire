# Quickstart Guide: PostgreSQL Transaction Verb Compatibility

**Feature**: 022-postgresql-transaction-verb
**Date**: 2025-11-08
**Audience**: Developers implementing or testing transaction verb translation

## Overview

This guide provides executable examples for validating PostgreSQL transaction verb translation. Examples progress from simple unit tests to E2E integration with real PostgreSQL clients.

## Prerequisites

- **IRIS PGWire Server**: Running on `localhost:5432` (Docker container `iris-pgwire-db`)
- **PostgreSQL Clients**: `psql` and `psycopg` installed
- **Python 3.11+**: For running tests and SQLAlchemy examples
- **Docker Network**: `iris-pgwire-network` for container communication

## Quick Validation (30 seconds)

### Test 1: Basic BEGIN Translation

```bash
# Using psql client - should translate BEGIN → START TRANSACTION
echo "BEGIN; SELECT 1; COMMIT;" | docker run --rm -i --network iris-pgwire-network \
    postgres:16-alpine psql -h iris-pgwire-db -p 5432 -U test_user -d USER

# Expected output: No errors, query executes successfully
# Server internally translates: BEGIN → START TRANSACTION
```

**What This Tests**: FR-001 (BEGIN → START TRANSACTION translation)

### Test 2: BEGIN with Isolation Level

```bash
# Test modifier preservation
docker run --rm --network iris-pgwire-network postgres:16-alpine psql \
    -h iris-pgwire-db -p 5432 -U test_user -d USER \
    -c "BEGIN ISOLATION LEVEL READ COMMITTED; SELECT 1; COMMIT;"

# Expected: Successful execution with isolation level preserved
# Server translates: BEGIN ISOLATION LEVEL READ COMMITTED →
#                   START TRANSACTION ISOLATION LEVEL READ COMMITTED
```

**What This Tests**: FR-005 (Modifier preservation)

### Test 3: String Literal Preservation

```bash
# Verify BEGIN inside string literals is NOT translated
docker run --rm --network iris-pgwire-network postgres:16-alpine psql \
    -h iris-pgwire-db -p 5432 -U test_user -d USER \
    -c "SELECT 'Transaction: BEGIN and COMMIT' as transaction_info;"

# Expected: Query returns "Transaction: BEGIN and COMMIT"
# Server does NOT translate string literal content
```

**What This Tests**: FR-006 (String literal exclusion)

## Developer Testing Workflow

### Unit Tests (TDD - Write These First)

```python
# tests/unit/test_transaction_translator.py
import pytest
from src.iris_pgwire.sql_translator.transaction_translator import TransactionTranslator


class TestTransactionTranslator:
    """Unit tests for transaction verb translation (TDD - write first, implement second)"""

    def setup_method(self):
        self.translator = TransactionTranslator()

    def test_begin_translates_to_start_transaction(self):
        """FR-001: BEGIN → START TRANSACTION"""
        result = self.translator.translate_transaction_command("BEGIN")
        assert result == "START TRANSACTION"

    def test_begin_transaction_translates(self):
        """FR-002: BEGIN TRANSACTION → START TRANSACTION"""
        result = self.translator.translate_transaction_command("BEGIN TRANSACTION")
        assert result == "START TRANSACTION"

    def test_commit_unchanged(self):
        """FR-003: COMMIT passes through unchanged"""
        result = self.translator.translate_transaction_command("COMMIT")
        assert result == "COMMIT"

    def test_rollback_unchanged(self):
        """FR-004: ROLLBACK passes through unchanged"""
        result = self.translator.translate_transaction_command("ROLLBACK")
        assert result == "ROLLBACK"

    def test_begin_with_isolation_level(self):
        """FR-005: Preserve transaction modifiers"""
        result = self.translator.translate_transaction_command(
            "BEGIN ISOLATION LEVEL READ COMMITTED"
        )
        assert result == "START TRANSACTION ISOLATION LEVEL READ COMMITTED"

    def test_string_literal_unchanged(self):
        """FR-006: Do NOT translate inside string literals"""
        result = self.translator.translate_transaction_command("SELECT 'BEGIN'")
        assert result == "SELECT 'BEGIN'"

    def test_case_insensitive_matching(self):
        """FR-009: Case-insensitive matching"""
        assert self.translator.translate_transaction_command("begin") == "START TRANSACTION"
        assert self.translator.translate_transaction_command("Begin") == "START TRANSACTION"
        assert self.translator.translate_transaction_command("BEGIN") == "START TRANSACTION"

    def test_translation_performance(self):
        """PR-001: Translation overhead <0.1ms"""
        import time

        sql = "BEGIN ISOLATION LEVEL READ COMMITTED"
        start = time.perf_counter()
        self.translator.translate_transaction_command(sql)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 0.1, f"Translation took {elapsed_ms:.3f}ms (SLA: 0.1ms)"
```

**Run Unit Tests**:
```bash
# These tests MUST fail initially (no implementation exists)
pytest tests/unit/test_transaction_translator.py -v

# Expected output: All tests FAIL with "No module named 'transaction_translator'"
# This proves TDD approach - tests written first
```

### Contract Tests (TDD - Interface Validation)

```python
# tests/contract/test_transaction_translator_contract.py
import pytest
from specs.022.contracts.transaction_translator_interface import (
    TransactionTranslatorInterface,
    CommandType,
    assert_translation_equals,
    assert_translation_performance
)
from src.iris_pgwire.sql_translator.transaction_translator import TransactionTranslator


class TestTransactionTranslatorContract:
    """Contract tests against interface (TDD - write first)"""

    def setup_method(self):
        # This MUST fail initially (TransactionTranslator doesn't exist)
        self.translator = TransactionTranslator()

    def test_implements_interface(self):
        """Verify translator implements TransactionTranslatorInterface"""
        assert isinstance(self.translator, TransactionTranslatorInterface)

    def test_begin_translation_contract(self):
        """Contract: BEGIN → START TRANSACTION"""
        assert_translation_equals(self.translator, "BEGIN", "START TRANSACTION")

    def test_performance_contract(self):
        """Contract: Translation <0.1ms"""
        elapsed_ms = assert_translation_performance(
            self.translator,
            "BEGIN ISOLATION LEVEL READ COMMITTED",
            max_time_ms=0.1
        )
        print(f"Translation took {elapsed_ms:.3f}ms (SLA: 0.1ms)")
```

**Run Contract Tests**:
```bash
# These tests MUST fail initially
pytest tests/contract/test_transaction_translator_contract.py -v

# Expected: FAIL - TransactionTranslator class not found
```

### Integration Tests (E2E with Real Clients)

```python
# tests/integration/test_transaction_e2e.py
import pytest
import psycopg
from sqlalchemy import create_engine, text


class TestTransactionE2E:
    """E2E tests with real PostgreSQL clients (TR-002, TR-003)"""

    @pytest.fixture
    def psycopg_connection(self):
        """Real psycopg connection to IRIS via PGWire"""
        conn = psycopg.connect(
            "host=localhost port=5432 user=test_user dbname=USER"
        )
        yield conn
        conn.close()

    def test_psycopg_begin_commit(self, psycopg_connection):
        """TR-003: psycopg transaction with BEGIN/COMMIT"""
        conn = psycopg_connection

        # Execute transaction
        with conn.cursor() as cur:
            # Server translates BEGIN → START TRANSACTION
            cur.execute("BEGIN")

            # Create test table
            cur.execute("CREATE TABLE IF NOT EXISTS test_txn (id INT, data VARCHAR(50))")

            # Insert data
            cur.execute("INSERT INTO test_txn VALUES (1, 'test data')")

            # Server receives COMMIT unchanged
            cur.execute("COMMIT")

            # Verify data persisted
            cur.execute("SELECT COUNT(*) FROM test_txn WHERE id = 1")
            count = cur.fetchone()[0]
            assert count == 1

    def test_sqlalchemy_context_manager(self):
        """TR-003: SQLAlchemy with connection.begin() context manager"""
        engine = create_engine("iris+psycopg://localhost:5432/USER")

        with engine.connect() as conn:
            # Context manager sends BEGIN (translated to START TRANSACTION)
            with conn.begin():
                conn.execute(text("CREATE TABLE IF NOT EXISTS test_sqlalchemy (id INT)"))
                conn.execute(text("INSERT INTO test_sqlalchemy VALUES (1)"))
            # Context exit sends COMMIT

            # Verify transaction committed
            result = conn.execute(text("SELECT COUNT(*) FROM test_sqlalchemy"))
            count = result.scalar()
            assert count == 1

    def test_rollback_on_error(self, psycopg_connection):
        """Verify ROLLBACK works after error"""
        conn = psycopg_connection

        with conn.cursor() as cur:
            cur.execute("BEGIN")

            # Create table
            cur.execute("CREATE TABLE IF NOT EXISTS test_rollback (id INT PRIMARY KEY)")

            # Insert data
            cur.execute("INSERT INTO test_rollback VALUES (1)")

            try:
                # Duplicate key error
                cur.execute("INSERT INTO test_rollback VALUES (1)")
            except psycopg.Error:
                # Rollback transaction
                cur.execute("ROLLBACK")

            # Verify table is empty (rollback succeeded)
            cur.execute("SELECT COUNT(*) FROM test_rollback")
            count = cur.fetchone()[0]
            assert count == 0
```

**Run E2E Tests**:
```bash
# Requires running IRIS PGWire server
docker ps | grep iris-pgwire-db  # Verify server running

# Run E2E tests
pytest tests/integration/test_transaction_e2e.py -v

# Expected: Tests PASS when implementation complete
```

## Manual Testing with psql

### Scenario 1: Basic Transaction Workflow

```bash
# Connect to server
docker run --rm -it --network iris-pgwire-network postgres:16-alpine psql \
    -h iris-pgwire-db -p 5432 -U test_user -d USER

# Execute transaction
psql> BEGIN;
      -- Server translates to: START TRANSACTION
psql> CREATE TABLE test_manual (id INT, name VARCHAR(50));
psql> INSERT INTO test_manual VALUES (1, 'Alice');
psql> INSERT INTO test_manual VALUES (2, 'Bob');
psql> COMMIT;

# Verify data persisted
psql> SELECT * FROM test_manual;
 id | name
----+-------
  1 | Alice
  2 | Bob
(2 rows)
```

### Scenario 2: Rollback on Error

```bash
psql> BEGIN;
psql> INSERT INTO test_manual VALUES (3, 'Charlie');
psql> SELECT * FROM test_manual;  # Shows 3 rows

# Simulate error scenario
psql> ROLLBACK;

psql> SELECT * FROM test_manual;  # Shows only 2 rows (rollback worked)
 id | name
----+-------
  1 | Alice
  2 | Bob
(2 rows)
```

### Scenario 3: Isolation Level Modifiers

```bash
psql> BEGIN ISOLATION LEVEL READ COMMITTED;
      -- Server translates to: START TRANSACTION ISOLATION LEVEL READ COMMITTED
psql> INSERT INTO test_manual VALUES (4, 'David');
psql> COMMIT;

# Verify isolation level was honored (data committed)
psql> SELECT * FROM test_manual WHERE id = 4;
 id | name
----+-------
  4 | David
(1 row)
```

## Performance Validation

### Measure Translation Overhead

```python
# scripts/measure_translation_performance.py
import time
from src.iris_pgwire.sql_translator.transaction_translator import TransactionTranslator


def measure_translation_performance(iterations=10000):
    """PR-001: Verify translation <0.1ms per command"""
    translator = TransactionTranslator()

    test_cases = [
        "BEGIN",
        "BEGIN TRANSACTION",
        "BEGIN ISOLATION LEVEL READ COMMITTED",
        "COMMIT",
        "ROLLBACK",
        "SELECT 'BEGIN'"  # Not a transaction command
    ]

    for sql in test_cases:
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            translator.translate_transaction_command(sql)
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

        avg_ms = sum(times) / len(times)
        max_ms = max(times)
        min_ms = min(times)

        print(f"\nSQL: {sql}")
        print(f"  Avg: {avg_ms:.4f}ms")
        print(f"  Min: {min_ms:.4f}ms")
        print(f"  Max: {max_ms:.4f}ms")
        print(f"  SLA: {'✅ PASS' if avg_ms < 0.1 else '❌ FAIL'} (target <0.1ms)")


if __name__ == "__main__":
    measure_translation_performance()
```

**Expected Output**:
```
SQL: BEGIN
  Avg: 0.0012ms
  Min: 0.0010ms
  Max: 0.0089ms
  SLA: ✅ PASS (target <0.1ms)

SQL: BEGIN ISOLATION LEVEL READ COMMITTED
  Avg: 0.0025ms
  Min: 0.0021ms
  Max: 0.0095ms
  SLA: ✅ PASS (target <0.1ms)
```

## Debugging Common Issues

### Issue 1: Translation Not Applied

**Symptom**: `BEGIN` command fails with IRIS error

**Debug**:
```bash
# Check Docker container uptime (stale code?)
docker ps | grep iris-pgwire-db

# If uptime > time since code change, restart container
docker restart iris-pgwire-db
sleep 3

# Verify translation is active
docker logs iris-pgwire-db | grep -i "transaction.*translation"
```

### Issue 2: String Literal Incorrectly Translated

**Symptom**: Query like `SELECT 'BEGIN'` returns `SELECT 'START TRANSACTION'`

**Debug**:
```python
# Test string literal detection
translator = TransactionTranslator()
result = translator.translate_transaction_command("SELECT 'BEGIN'")
assert result == "SELECT 'BEGIN'", f"String literal translated: {result}"

# Check regex pattern
# String detection regex should match quoted strings before BEGIN pattern
```

### Issue 3: Performance SLA Violation

**Symptom**: Translation taking >0.1ms

**Debug**:
```python
# Check if regex is being recompiled on each call
import re

class TransactionTranslator:
    # ❌ BAD: Compiles regex on each call
    def translate(self, sql):
        pattern = re.compile(r'BEGIN', re.IGNORECASE)  # Slow!
        return pattern.sub('START TRANSACTION', sql)

    # ✅ GOOD: Compile regex once at class level
    BEGIN_PATTERN = re.compile(r'BEGIN', re.IGNORECASE)  # Fast!

    def translate(self, sql):
        return self.BEGIN_PATTERN.sub('START TRANSACTION', sql)
```

## Next Steps

1. **Implement TransactionTranslator**: Follow TDD - make unit tests pass
2. **Integrate with iris_executor.py**: Add translation at 3 execution points
3. **Run E2E Tests**: Validate with real psql and psycopg clients
4. **Performance Validation**: Ensure <0.1ms translation overhead
5. **Update CLAUDE.md**: Document implementation patterns

## References

- **Specification**: `specs/022-postgresql-transaction-verb/spec.md`
- **Implementation Plan**: `specs/022-postgresql-transaction-verb/plan.md`
- **Contract Interface**: `specs/022-postgresql-transaction-verb/contracts/transaction_translator_interface.py`
- **Data Model**: `specs/022-postgresql-transaction-verb/data-model.md`

---

**Status**: Quickstart guide complete - ready for implementation (Phase 2 tasks)
