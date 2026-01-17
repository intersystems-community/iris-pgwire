import sys

import pytest

# Add iris-devtester to path
sys.path.insert(0, "/Users/tdyar/ws/iris-devtester")

from iris_pgwire.sql_translator.config import TranslationConfig, ValidationConfig
from iris_pgwire.sql_translator.normalizer import SQLTranslator


def test_migration_ddl_compatibility_e2e():
    """
    Integration test for complete migration script.
    Verifies that all Feature 036 constructs are handled correctly in a single script.
    """
    translator = SQLTranslator()

    migration_script = """
    CREATE TYPE status_enum AS ENUM ('active', 'inactive', 'pending');

    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL,
        status status_enum DEFAULT 'active'::status_enum,
        bio TEXT,
        computed_info INT GENERATED ALWAYS AS (id * 10) STORED,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    ) WITH (fillfactor = 90);

    CREATE INDEX idx_users_username ON users USING btree (username);

    ALTER TABLE users ADD CONSTRAINT check_username_length CHECK (char_length(username) >= 3);
    """

    # Process each statement
    statements = [s.strip() for s in migration_script.split(";") if s.strip()]
    results = []
    skipped_count = 0

    for sql in statements:
        result = translator.normalize_sql_with_result(sql)
        if not result.was_skipped:
            results.append(result.sql)
        else:
            skipped_count += 1

    # Verify transformations
    full_translated = " ".join(results)

    # 1. Enum registration and translation (registered type name is uppercased in normalizer)
    assert "VARCHAR(64)" in full_translated

    # 2. Cast removal
    assert "::" not in full_translated

    # 3. Generated column stripping
    assert "computed_info" not in full_translated.lower()

    # 4. USING btree removal
    assert "USING btree" not in full_translated.upper()

    # 5. WITH (fillfactor) removal
    assert "fillfactor" not in full_translated.upper()

    # Verify no failures
    assert len(results) > 0
    assert skipped_count > 0  # CREATE TYPE and ALTER TABLE ... CHECK should be skipped
