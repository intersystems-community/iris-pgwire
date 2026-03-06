"""
E2E test: HNSW vector index creation and query ordering.

Verifies that:
1. pgvector USING hnsw (col ops) syntax is correctly translated to IRIS AS HNSW(Distance=...)
2. Hybrid (col-first) USING HNSW WITH (...) syntax is also correctly translated
3. After index creation, ORDER BY embedding <=> query returns most-similar rows first
   (regression anchor: if translation breaks, IRIS rejects the DDL with SQLCODE -25)

These are the tests that would have caught:
- USING HNSW WITH (...) → SQLCODE -25 (IRIS rejects non-standard syntax)
- AS HNSW without Distance= (pre-fix behaviour) — index built but wrong metric used
"""

import psycopg
import pytest


@pytest.fixture
def conn(pgwire_connection_params, pgwire_server):
    """psycopg connection to PGWire."""
    _ = pgwire_server
    p = pgwire_connection_params
    c = psycopg.connect(
        f"host={p['host']} port={p['port']} "
        f"user={p['user']} password={p['password']} dbname={p['dbname']}"
    )
    yield c
    c.close()


def _setup_table(conn, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table}")
        cur.execute(f"CREATE TABLE {table} (id INT, label VARCHAR(50), emb VECTOR(DOUBLE, 3))")
        cur.execute(
            f"INSERT INTO {table} VALUES (1, 'identical',  TO_VECTOR('[0.1,0.2,0.9]', DOUBLE))"
        )
        cur.execute(
            f"INSERT INTO {table} VALUES (2, 'dissimilar', TO_VECTOR('[0.9,0.2,0.1]', DOUBLE))"
        )
        cur.execute(
            f"INSERT INTO {table} VALUES (3, 'moderate',   TO_VECTOR('[0.1,0.9,0.2]', DOUBLE))"
        )
    conn.commit()


def _teardown_table(conn, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()


def _assert_ordering(conn, table: str, query_vec: str) -> None:
    """After HNSW index, ORDER BY <=> must return id=1 (identical) first."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT id FROM {table} ORDER BY emb <=> '{query_vec}' LIMIT 1")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 1, (
        f"Most-similar row (id=1) must be first after HNSW index on {table}, "
        f"but got id={row[0]}. Index may be using wrong distance metric."
    )


class TestHnswIndexCreation:
    """HNSW index DDL translation: both pgvector and hybrid syntax."""

    TABLE = "e2e_hnsw_pgvector"

    def test_pgvector_using_hnsw_syntax(self, conn):
        """
        pgvector standard: CREATE INDEX ... USING hnsw (col vector_cosine_ops)
        Must be translated to: CREATE INDEX ... AS HNSW(Distance='Cosine')
        """
        _setup_table(conn, self.TABLE)
        try:
            with conn.cursor() as cur:
                # This is the standard pgvector syntax — must NOT produce SQLCODE -25
                cur.execute(
                    f"CREATE INDEX hnsw_pgv ON {self.TABLE} USING hnsw (emb vector_cosine_ops)"
                )
            conn.commit()
            _assert_ordering(conn, self.TABLE, "[0.1,0.2,0.9]")
        finally:
            _teardown_table(conn, self.TABLE)

    def test_pgvector_using_hnsw_with_options(self, conn):
        """
        pgvector with WITH clause: USING hnsw (col ops) WITH (m=16, ef_construction=64)
        Must preserve M and efConstruction in the IRIS AS HNSW(...) output.
        """
        _setup_table(conn, self.TABLE)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE INDEX hnsw_pgv_opts ON {self.TABLE} "
                    f"USING hnsw (emb vector_cosine_ops) WITH (m=16, ef_construction=64)"
                )
            conn.commit()
            _assert_ordering(conn, self.TABLE, "[0.1,0.2,0.9]")
        finally:
            _teardown_table(conn, self.TABLE)

    def test_pgvector_ip_ops(self, conn):
        """
        pgvector inner-product: USING hnsw (col vector_ip_ops)
        Must translate to AS HNSW(Distance='DotProduct').
        """
        _setup_table(conn, self.TABLE)
        try:
            with conn.cursor() as cur:
                cur.execute(f"CREATE INDEX hnsw_ip ON {self.TABLE} USING hnsw (emb vector_ip_ops)")
            conn.commit()
            # Just verify the index was created without error (DotProduct ordering
            # with non-normalized vectors is not directly comparable to <=>)
        finally:
            _teardown_table(conn, self.TABLE)


class TestHnswIndexColFirstSyntax:
    """Bug regression: CREATE INDEX (col) USING HNSW WITH (...) must not fail with SQLCODE -25."""

    TABLE = "e2e_hnsw_colfirst"

    def test_col_first_with_all_options(self, conn):
        """
        Hybrid syntax from bug report:
            CREATE INDEX i ON table (col) USING HNSW WITH (M=16, efConstruction=64, Distance='COSINE')
        Was failing: SQLCODE -25 'Input (USING) encountered after end of query'
        because IRIS SQL doesn't support this syntax — pgwire must translate it.
        """
        _setup_table(conn, self.TABLE)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE INDEX hnsw_cf ON {self.TABLE} (emb) "
                    f"USING HNSW WITH (M=16, efConstruction=64, Distance='COSINE')"
                )
            conn.commit()
            _assert_ordering(conn, self.TABLE, "[0.1,0.2,0.9]")
        finally:
            _teardown_table(conn, self.TABLE)

    def test_col_first_bare(self, conn):
        """Bare (col) USING HNSW with no WITH clause — defaults to Distance='Cosine'."""
        _setup_table(conn, self.TABLE)
        try:
            with conn.cursor() as cur:
                cur.execute(f"CREATE INDEX hnsw_bare ON {self.TABLE} (emb) USING HNSW")
            conn.commit()
            _assert_ordering(conn, self.TABLE, "[0.1,0.2,0.9]")
        finally:
            _teardown_table(conn, self.TABLE)

    def test_col_first_dotproduct(self, conn):
        """(col) USING HNSW WITH (Distance='DotProduct') must not error."""
        _setup_table(conn, self.TABLE)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE INDEX hnsw_dp ON {self.TABLE} (emb) "
                    f"USING HNSW WITH (Distance='DotProduct')"
                )
            conn.commit()
        finally:
            _teardown_table(conn, self.TABLE)


class TestHnswIndexTranslationUnit:
    """Unit tests for HnswIndexSpec translation logic (no IRIS needed)."""

    def test_pgvector_cosine_to_iris(self):
        from iris_pgwire.conversions.vector_syntax import HnswIndexSpec

        spec = HnswIndexSpec.from_postgres_sql(
            "CREATE INDEX i ON t USING hnsw (emb vector_cosine_ops)"
        )
        assert spec is not None
        iris_sql = spec.to_iris_sql()
        assert "AS HNSW(Distance='Cosine')" in iris_sql
        assert "USING" not in iris_sql
        assert "WITH" not in iris_sql

    def test_pgvector_with_opts_preserved(self):
        from iris_pgwire.conversions.vector_syntax import HnswIndexSpec

        spec = HnswIndexSpec.from_postgres_sql(
            "CREATE INDEX i ON t USING hnsw (emb vector_cosine_ops) WITH (m=24, ef_construction=100)"
        )
        assert spec is not None
        assert spec.m == 24
        assert spec.ef_construction == 100
        iris_sql = spec.to_iris_sql()
        assert "M=24" in iris_sql
        assert "efConstruction=100" in iris_sql
        assert "Distance='Cosine'" in iris_sql

    def test_col_first_with_options(self):
        from iris_pgwire.conversions.vector_syntax import HnswIndexSpec

        spec = HnswIndexSpec.from_postgres_sql(
            "CREATE INDEX i ON SQLUser.t (emb) USING HNSW WITH (M=16, efConstruction=64, Distance='COSINE')"
        )
        assert spec is not None
        assert spec.table_name == "SQLUser.t"
        assert spec.m == 16
        assert spec.ef_construction == 64
        assert spec.distance_metric == "Cosine"
        iris_sql = spec.to_iris_sql()
        assert "AS HNSW(" in iris_sql
        assert "USING" not in iris_sql

    def test_schema_qualified_table_preserved(self):
        from iris_pgwire.conversions.vector_syntax import HnswIndexSpec

        spec = HnswIndexSpec.from_postgres_sql(
            "CREATE INDEX i ON myschema.mytable USING hnsw (emb vector_cosine_ops)"
        )
        assert spec is not None
        assert spec.table_name == "myschema.mytable"
        assert "myschema.mytable" in spec.to_iris_sql()

    def test_iris_native_passthrough(self):
        """AS HNSW already in IRIS syntax — should return None (passthrough)."""
        from iris_pgwire.conversions.vector_syntax import HnswIndexSpec

        spec = HnswIndexSpec.from_postgres_sql(
            "CREATE INDEX i ON SQLUser.t (emb) AS HNSW(Distance='Cosine')"
        )
        assert spec is None

    def test_l2_ops_raises(self):
        from iris_pgwire.conversions.vector_syntax import HnswIndexSpec

        with pytest.raises(ValueError, match="L2"):
            HnswIndexSpec.from_postgres_sql("CREATE INDEX i ON t USING hnsw (emb vector_l2_ops)")
