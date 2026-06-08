import pytest

from iris_pgwire.vector_optimizer import VectorQueryOptimizer, optimize_vector_query


@pytest.fixture
def opt():
    return VectorQueryOptimizer()


# ---------------------------------------------------------------------------
# HNSW DDL translation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql, expected_fragment",
    [
        (
            "CREATE INDEX idx_vec ON docs USING hnsw (embedding vector_cosine_ops)",
            "AS HNSW(Distance=Cosine)",
        ),
        (
            "CREATE INDEX idx_ip ON vecs USING hnsw (v vector_ip_ops)",
            "AS HNSW(Distance=DotProduct)",
        ),
        (
            "CREATE INDEX IF NOT EXISTS idx_c ON t USING hnsw (col vector_cosine_ops) WITH (m=16, ef_construction=64)",
            "AS HNSW(Distance=Cosine, M=16, efConstruction=64)",
        ),
    ],
)
def test_hnsw_ddl_translation(opt, sql, expected_fragment):
    result = opt._translate_hnsw_index_ddl(sql)
    assert expected_fragment in result


@pytest.mark.unit
def test_hnsw_ddl_l2_raises(opt):
    sql = "CREATE INDEX idx_l2 ON t USING hnsw (col vector_l2_ops)"
    with pytest.raises(NotImplementedError, match="L2"):
        opt._translate_hnsw_index_ddl(sql)


@pytest.mark.unit
def test_hnsw_ddl_no_match_passthrough(opt):
    sql = "CREATE TABLE foo (id INT)"
    assert opt._translate_hnsw_index_ddl(sql) == sql


@pytest.mark.unit
def test_hnsw_ddl_wired_through_optimizer(opt):
    sql = "CREATE INDEX idx ON t USING hnsw (col vector_cosine_ops)"
    result, _ = opt.optimize_query(sql)
    assert "HNSW" in result
    assert "USING hnsw" not in result


# ---------------------------------------------------------------------------
# JSON operator translation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql, expected",
    [
        ("SELECT col->>'key' FROM t", "JSON_VALUE(col, '$.key')"),
        ("SELECT col->'key' FROM t", "JSON_QUERY(col, '$.key')"),
        ("SELECT col->'a'->>'b' FROM t", "JSON_VALUE(col, '$.a.b')"),
    ],
)
def test_json_operator_translation(opt, sql, expected):
    result = opt._translate_nested_json_operators(sql)
    assert expected in result


@pytest.mark.unit
def test_json_operator_no_arrow_passthrough(opt):
    sql = "SELECT id FROM t WHERE x = 1"
    assert opt._translate_nested_json_operators(sql) == sql


@pytest.mark.unit
def test_json_operator_wired_through_optimizer(opt):
    sql = "SELECT meta->>'name' FROM docs"
    result, _ = opt.optimize_query(sql)
    assert "JSON_VALUE" in result
    assert "->>" not in result


# ---------------------------------------------------------------------------
# is_duplicate_object_error
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "msg",
    [
        "SQLCODE: <-5016>",
        "SQLCODE: <-5019>",
        "SQLCODE: <-5002>",
        "error 5016 occurred",
        "error 5019",
        "error 5002",
    ],
)
def test_is_duplicate_object_error_true(msg):
    assert VectorQueryOptimizer.is_duplicate_object_error(msg) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "msg",
    [
        "SQLCODE: <-1>",
        "some other error",
        "",
        "SQLCODE: <-5000>",
    ],
)
def test_is_duplicate_object_error_false(msg):
    assert VectorQueryOptimizer.is_duplicate_object_error(msg) is False


# ---------------------------------------------------------------------------
# sql_has_if_not_exists
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE IF NOT EXISTS foo (id INT)",
        "create table if not exists foo (id INT)",
        "CREATE INDEX IF NOT EXISTS idx ON foo (col) USING hnsw",
    ],
)
def test_sql_has_if_not_exists_true(sql):
    assert VectorQueryOptimizer.sql_has_if_not_exists(sql) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE foo (id INT)",
        "SELECT * FROM foo",
        "",
    ],
)
def test_sql_has_if_not_exists_false(sql):
    assert VectorQueryOptimizer.sql_has_if_not_exists(sql) is False
