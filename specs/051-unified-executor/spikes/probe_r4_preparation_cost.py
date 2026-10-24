"""Phase 0 probe R4 for feature 051: what does preparation cost, per path?

Constitution Principle V requires a measurement, not "probably fast enough",
for anything on the query path, against a 5 ms budget. Feature 051 unifies three
preparation implementations into one, and unifying them means the survivor runs
every step that any path ran. R4 asks what that costs before the design commits
to it, and whether the double ``SQLRefiner.refine`` (normalizer.py:258 and
pipeline.py:61) is measurable or merely untidy.

The three implementations, by line:

  embedded inline   iris_executor.py:1206-1270   6 rewrites + transaction xlate
  _prepare_sql      iris_executor.py:848-948     normalize, params, VECTOR,
                                                 ReturningPlan, semicolon, schema
  DBAPI inline      dbapi_executor.py:242-281    the SAME 6 rewrites, verbatim,
                                                 + placeholders + ReturningPlan,
                                                 and NO vector optimization

Run with the repository venv (pure translation functions; no IRIS needed):

    .venv/bin/python probe_r4_preparation_cost.py
"""

from __future__ import annotations

import statistics
import time

BUDGET_MS = 5.0
REPS = 200

CORPUS = {
    "plain_select": "SELECT id, name FROM users WHERE status = $1 ORDER BY id",
    "wide_select": "SELECT " + ", ".join(f"t.col{i}" for i in range(30)) + " FROM orders t WHERE t.status = $1",
    "vector_order_by": (
        "SELECT id, embedding FROM docs ORDER BY embedding <=> $1 LIMIT $2"
    ),
    "array_any": "SELECT id FROM t WHERE id = ANY($1)",
    "boolean_projection": "SELECT (a AND b = 1) AS flag, c FROM t",
    "pg_function": "SELECT obj_description(c.oid) FROM pg_class c",
    "bool_literal": "SELECT 1 FROM pg_class WHERE relispartition = 'f'",
    "returning": "INSERT INTO t (a) VALUES ($1) RETURNING id",
    "transaction": "BEGIN ISOLATION LEVEL READ COMMITTED",
}


def bench(fn, reps=REPS):
    """Return (median_ms, p95_ms) for fn over reps calls."""
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95)]


def main():
    from iris_pgwire.sql_translator.array_literal import rewrite_array_literals
    from iris_pgwire.sql_translator.array_params import (
        encode_inlist_params,
        expand_array_literals,
        has_array_param,
        rewrite_any_col_to_instr,
        rewrite_any_to_inlist,
    )
    from iris_pgwire.sql_translator.boolean_expr import (
        has_boolean_literal_comparison,
        has_boolean_projection,
        rewrite_boolean_literal_comparisons,
        rewrite_boolean_projections,
    )
    from iris_pgwire.sql_translator.pg_functions import (
        has_pg_function_call,
        rewrite_pg_function_calls,
    )
    from iris_pgwire.vector_optimizer import optimize_vector_query

    def six_rewrites(sql, params=None):
        """The block duplicated verbatim at iris_executor.py:1230-1266 and
        dbapi_executor.py:242-278. One function here; two copies in src."""
        sql = rewrite_array_literals(sql)
        if has_array_param(sql):
            sql = expand_array_literals(rewrite_any_to_inlist(sql))
            params = encode_inlist_params(sql, params)
        sql = rewrite_any_col_to_instr(sql)
        if has_boolean_projection(sql):
            sql = rewrite_boolean_projections(sql)
        if has_pg_function_call(sql):
            sql = rewrite_pg_function_calls(sql)
        if has_boolean_literal_comparison(sql):
            sql = rewrite_boolean_literal_comparisons(sql)
        return sql, params

    print("=== R4.1 the six duplicated rewrites, per statement ===")
    print(f"{'statement':22} {'median ms':>10} {'p95 ms':>9} {'% budget':>9}")
    for name, sql in CORPUS.items():
        med, p95 = bench(lambda s=sql: six_rewrites(s, [1, 2]))
        print(f"{name:22} {med:10.4f} {p95:9.4f} {100 * med / BUDGET_MS:8.1f}%")

    print("\n=== R4.2 optimize_vector_query: the step DBAPI never runs ===")
    print(f"{'statement':22} {'median ms':>10} {'p95 ms':>9} {'% budget':>9}")
    for name, sql in CORPUS.items():
        med, p95 = bench(lambda s=sql: optimize_vector_query(s, [1, 2]))
        print(f"{name:22} {med:10.4f} {p95:9.4f} {100 * med / BUDGET_MS:8.1f}%")

    print("\n=== R4.3 what optimize_vector_query DOES to the vector statement ===")
    sql = CORPUS["vector_order_by"]
    new_sql, new_params = optimize_vector_query(sql, [[0.1, 0.2], 5])
    print(f"  in  sql:    {sql}")
    print(f"  out sql:    {new_sql}")
    print(f"  in  params: {[type(p).__name__ for p in [[0.1, 0.2], 5]]}")
    print(f"  out params: {new_params!r}")
    print("  NOTE: if the SQL still says LIMIT $2 while params has one fewer entry,")
    print("        that is the parameter-renumbering defect (task T028).")

    print("\n=== R4.4 the normalizer, and the double SQLRefiner.refine ===")
    try:
        from iris_pgwire.sql_translator.normalizer import SQLNormalizer

        norm = SQLNormalizer()
        print(f"{'statement':22} {'median ms':>10} {'p95 ms':>9} {'% budget':>9}")
        for name, sql in CORPUS.items():
            med, p95 = bench(lambda s=sql: norm.normalize(s), reps=100)
            print(f"{name:22} {med:10.4f} {p95:9.4f} {100 * med / BUDGET_MS:8.1f}%")
    except Exception as e:  # noqa: BLE001
        print(f"  normalizer bench unavailable: {type(e).__name__}: {e}")

    try:
        from iris_pgwire.sql_translator.refiner import SQLRefiner

        refiner = SQLRefiner()
        print("\n  SQLRefiner.refine cost alone (it runs TWICE per statement:")
        print("  normalizer.py:258 then pipeline.py:61):")
        for name in ("wide_select", "boolean_projection"):
            med, p95 = bench(lambda s=CORPUS[name]: refiner.refine(s), reps=200)
            print(
                f"    {name:22} once {med:.4f} ms  twice {2 * med:.4f} ms "
                f"({100 * 2 * med / BUDGET_MS:.1f}% of budget)"
            )
    except Exception as e:  # noqa: BLE001
        print(f"  refiner bench unavailable: {type(e).__name__}: {e}")

    print("\n=== R4.5 combined: one unified preparation running every step ===")
    print(f"{'statement':22} {'median ms':>10} {'% budget':>9}")
    for name, sql in CORPUS.items():
        def unified(s=sql):
            out, params = six_rewrites(s, [1, 2])
            return optimize_vector_query(out, params)

        med, _ = bench(unified)
        print(f"{name:22} {med:10.4f} {100 * med / BUDGET_MS:8.1f}%")


if __name__ == "__main__":
    main()
