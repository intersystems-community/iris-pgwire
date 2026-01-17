import re

import pytest

from iris_pgwire.sql_translator.validator import SemanticValidator, ValidationContext


def test_check_constraint_skip():
    validator = SemanticValidator()
    sql = "ALTER TABLE t1 ADD CONSTRAINT c1 CHECK (col1 > 0)"
    context = ValidationContext(original_sql=sql, translated_sql=sql, construct_mappings=[])
    result = validator.validate_query_equivalence(context)
    assert result.success is True
