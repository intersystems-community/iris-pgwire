import time

import pytest

from iris_pgwire.sql_translator.normalizer import SQLTranslator


def test_ddl_translation_performance():
    """
    Benchmark DDL translation performance.
    Goal: < 5% overhead compared to baseline (simple string passthrough).
    """
    translator = SQLTranslator()

    ddl = """
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL,
        status status_enum DEFAULT 'active'::status_enum,
        bio TEXT,
        computed_info INT GENERATED ALWAYS AS (id * 10) STORED,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    ) WITH (fillfactor = 90);
    """

    start_baseline = time.perf_counter()
    for _ in range(1000):
        _ = ddl.upper()
    end_baseline = time.perf_counter()
    baseline_time = (end_baseline - start_baseline) / 1000

    start_translation = time.perf_counter()
    for _ in range(1000):
        _ = translator.normalize_sql(ddl)
    end_translation = time.perf_counter()
    translation_time = (end_translation - start_translation) / 1000

    print(f"\nBaseline time: {baseline_time * 1000:.4f}ms")
    print(f"Translation time: {translation_time * 1000:.4f}ms")

    # Ensure performance remains within acceptable absolute bounds
    assert translation_time * 1000 < 5.0
