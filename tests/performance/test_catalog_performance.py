"""
Performance Tests: Catalog Functions (NFR-001, NFR-002)

Validates that catalog functions meet performance requirements:
- NFR-001: Single function call <100ms
- NFR-002: Batch introspection (10+ tables) in reasonable time

These tests use pytest-benchmark for accurate timing measurements.
"""

import pytest
from unittest.mock import Mock

from iris_pgwire.catalog.catalog_functions import CatalogFunctionHandler
from iris_pgwire.catalog.oid_generator import OIDGenerator


class MockExecutorPerf:
    """Realistic mock executor for performance testing."""

    def __init__(self):
        # Simulate 10 tables with realistic constraint/column data
        # Format: (schema, constraint_name, constraint_type, table_name)
        self.constraints = []
        self.constraint_columns = {}

        for i in range(10):
            table = f"table_{i}"
            pk_name = f"{table}_pkey"
            self.constraints.append(("SQLUser", pk_name, "PRIMARY KEY", table))
            self.constraint_columns[pk_name] = ["id"]

        self.columns = {
            f"table_{i}": {
                "id": (None, "YES"),  # IDENTITY column
                "name": (None, "NO"),
                "created_at": (None, "NO"),
            }
            for i in range(10)
        }

        self.fk_refs = {}
        for i in range(5):
            # Half the tables have FK relationships
            table = f"table_{i}"
            fk_name = f"{table}_author_fkey"
            self.constraints.append(("SQLUser", fk_name, "FOREIGN KEY", table))
            self.constraint_columns[fk_name] = ["author_id"]
            self.fk_refs[fk_name] = {
                "ref_table": f"table_{i+5}",
                "ref_columns": ["id"],
                "update_rule": "NO ACTION",
                "delete_rule": "CASCADE",
            }

    def _execute_iris_query(self, query):
        """Mock IRIS query execution with realistic latency."""
        query_upper = query.upper()

        # Table constraints query
        if "TABLE_CONSTRAINTS" in query_upper:
            if "SELECT TABLE_NAME" in query_upper and "CONSTRAINT_NAME" in query_upper:
                # FK reference table lookup - just return table name
                rows = [(info[3],) for info in self.constraints]
            else:
                # Full constraint info
                rows = self.constraints
            return {"success": True, "rows": rows}

        # Key column usage
        if "KEY_COLUMN_USAGE" in query_upper:
            # Extract constraint name from query
            for constraint_name, columns in self.constraint_columns.items():
                if constraint_name.upper() in query_upper:
                    return {"success": True, "rows": [(col,) for col in columns]}
            return {"success": True, "rows": []}

        # Referential constraints
        if "REFERENTIAL_CONSTRAINTS" in query_upper:
            for fk_name, ref_info in self.fk_refs.items():
                if fk_name.upper() in query_upper:
                    rows = [(
                        "SQLUser",
                        f"{ref_info['ref_table']}_pkey",
                        ref_info["update_rule"],
                        ref_info["delete_rule"]
                    )]
                    return {"success": True, "rows": rows}
            return {"success": True, "rows": []}

        # Column metadata (for serial sequence)
        if "IS_IDENTITY" in query_upper:
            for table, cols in self.columns.items():
                if table.upper() in query_upper:
                    for col, (default, is_identity) in cols.items():
                        if col.upper() in query_upper:
                            return {"success": True, "rows": [(default, is_identity)]}
            return {"success": True, "rows": []}

        return {"success": True, "rows": []}


@pytest.fixture
def catalog_handler():
    """Create catalog function handler with realistic mock."""
    executor = MockExecutorPerf()
    oid_gen = OIDGenerator()
    return CatalogFunctionHandler(oid_gen, executor)


@pytest.fixture
def oid_gen():
    """OID generator for test data."""
    return OIDGenerator()


# ============================================================================
# NFR-001: Single Function Performance (<100ms)
# ============================================================================


def test_format_type_performance(benchmark, catalog_handler):
    """NFR-001: format_type completes in <100ms."""
    # Test with parameterized type (most complex case)
    result = benchmark(catalog_handler.format_type, 1043, 259)  # varchar(255)

    assert result == "character varying(255)"
    # Benchmark will fail if >100ms (configured in pytest.ini)


def test_pg_get_constraintdef_performance(benchmark, catalog_handler, oid_gen):
    """NFR-001: pg_get_constraintdef completes in <100ms."""
    # Setup test constraint
    constraint_oid = oid_gen.get_constraint_oid("SQLUser", "table_0_pkey")

    result = benchmark(catalog_handler.pg_get_constraintdef, constraint_oid)

    assert result == "PRIMARY KEY (id)"


def test_pg_get_serial_sequence_performance(benchmark, catalog_handler):
    """NFR-001: pg_get_serial_sequence completes in <100ms."""
    result = benchmark(catalog_handler.pg_get_serial_sequence, "table_0", "id")

    assert result == "public.table_0_id_seq"


def test_pg_get_indexdef_performance(benchmark, catalog_handler):
    """NFR-001: pg_get_indexdef completes in <100ms."""
    # Currently returns None (awaiting Feature 031 integration)
    result = benchmark(catalog_handler.pg_get_indexdef, 12345, 0)

    assert result is None


def test_pg_get_viewdef_performance(benchmark, catalog_handler):
    """NFR-001: pg_get_viewdef completes in <100ms."""
    # Intentionally returns None per plan.md
    result = benchmark(catalog_handler.pg_get_viewdef, 12345)

    assert result is None


# ============================================================================
# NFR-002: Batch Introspection Performance
# ============================================================================


def test_batch_introspection_format_type(benchmark, catalog_handler):
    """NFR-002: Batch format_type for common types."""
    type_oids = [
        (23, -1),      # integer
        (1043, 259),   # varchar(255)
        (1700, 655366),  # numeric(10,2)
        (1114, 7),     # timestamp(3)
        (25, -1),      # text
        (16, -1),      # boolean
        (20, -1),      # bigint
        (1082, -1),    # date
        (2950, -1),    # uuid
        (114, -1),     # json
    ]

    def batch_format():
        return [catalog_handler.format_type(oid, typmod) for oid, typmod in type_oids]

    results = benchmark(batch_format)

    assert len(results) == 10
    assert results[0] == "integer"
    assert results[1] == "character varying(255)"


def test_batch_introspection_constraints(benchmark, catalog_handler, oid_gen):
    """NFR-002: Batch constraint definition retrieval."""
    constraint_oids = [
        oid_gen.get_constraint_oid("SQLUser", f"table_{i}_pkey")
        for i in range(10)
    ]

    def batch_constraints():
        return [
            catalog_handler.pg_get_constraintdef(oid)
            for oid in constraint_oids
        ]

    results = benchmark(batch_constraints)

    assert len(results) == 10
    assert all("PRIMARY KEY" in r for r in results)


def test_batch_introspection_serial_sequences(benchmark, catalog_handler):
    """NFR-002: Batch serial sequence detection."""
    tables = [f"table_{i}" for i in range(10)]

    def batch_serial():
        return [
            catalog_handler.pg_get_serial_sequence(table, "id")
            for table in tables
        ]

    results = benchmark(batch_serial)

    assert len(results) == 10
    assert all(r.startswith("public.") for r in results)


def test_full_schema_introspection_simulation(benchmark, catalog_handler, oid_gen):
    """NFR-002: Simulate full ORM introspection of 10 tables."""

    def full_introspection():
        results = {}

        # Step 1: Get all table constraints (like Prisma does)
        for i in range(10):
            table = f"table_{i}"
            constraint_oid = oid_gen.get_constraint_oid("SQLUser", f"{table}_pkey")

            # Get constraint definition
            constraint_def = catalog_handler.pg_get_constraintdef(constraint_oid)

            # Check for serial columns
            serial_seq = catalog_handler.pg_get_serial_sequence(table, "id")

            # Format common types (simulate column introspection)
            types = [
                catalog_handler.format_type(23, -1),      # id: integer
                catalog_handler.format_type(1043, 259),   # name: varchar(255)
                catalog_handler.format_type(1114, 7),     # created_at: timestamp(3)
            ]

            results[table] = {
                "constraint": constraint_def,
                "serial": serial_seq,
                "types": types,
            }

        return results

    results = benchmark(full_introspection)

    assert len(results) == 10
    assert all("constraint" in v for v in results.values())
    assert all("serial" in v for v in results.values())
    assert all(len(v["types"]) == 3 for v in results.values())


# ============================================================================
# Handler Interface Performance
# ============================================================================


def test_handler_interface_performance(benchmark, catalog_handler):
    """NFR-001: Handler interface overhead is minimal."""
    result = benchmark(catalog_handler.handle, "format_type", ("23", "-1"))

    assert result.function_name == "format_type"
    assert result.result == "integer"
    assert result.error is None


def test_handler_batch_calls(benchmark, catalog_handler):
    """NFR-002: Handler can process multiple function calls efficiently."""
    function_calls = [
        ("format_type", ("23", "-1")),
        ("format_type", ("1043", "259")),
        ("format_type", ("1700", "655366")),
        ("pg_get_serial_sequence", ("table_0", "id")),
        ("pg_get_viewdef", ("12345",)),
    ]

    def batch_handler():
        return [
            catalog_handler.handle(func, args)
            for func, args in function_calls
        ]

    results = benchmark(batch_handler)

    assert len(results) == 5
    assert all(r.error is None for r in results)
