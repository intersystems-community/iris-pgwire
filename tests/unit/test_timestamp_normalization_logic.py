import datetime as dt

import pytest

from iris_pgwire.dbapi_executor import DBAPIExecutor
from iris_pgwire.models.backend_config import BackendConfig, BackendType


def test_timestamp_normalization_unit():
    """
    Unit test for timestamp normalization logic.
    Verifies that various ISO 8601 formats are correctly converted to IRIS format.
    """
    config = BackendConfig(
        backend_type=BackendType.DBAPI,
        iris_hostname="localhost",
        iris_port=1972,
        iris_username="_SYSTEM",
        iris_password="SYS",
        iris_namespace="USER",
    )
    executor = DBAPIExecutor(config)

    # Test cases: (input, expected)
    test_cases = [
        ("2026-01-29T21:27:38.111Z", "2026-01-29 21:27:38.111"),
        ("2026-01-29T21:27:38Z", "2026-01-29 21:27:38"),
        ("2026-01-29 21:27:38", "2026-01-29 21:27:38"),  # Already normalized
        ("2026-01-29T21:27:38.111+00:00", "2026-01-29 21:27:38.111"),
        ("2026-01-29T21:27:38.111-05:00", "2026-01-29 21:27:38.111"),
        (None, None),
        (123, 123),  # Non-string
        (["2026-01-29T21:27:38Z"], ["2026-01-29 21:27:38"]),  # List
    ]

    for input_val, expected in test_cases:
        if isinstance(input_val, list):
            result = executor._convert_params_for_iris(input_val)
        else:
            result = executor._convert_value_for_iris(input_val)
        assert result == expected, f"Failed for {input_val}: expected {expected}, got {result}"

    print("✅ Timestamp normalization unit tests passed")


def test_iris_executor_normalization_unit():
    """
    Verify IRISExecutor also has the normalization logic working.
    """
    from iris_pgwire.iris_executor import IRISExecutor

    executor = IRISExecutor(
        {
            "host": "localhost",
            "port": 1972,
            "username": "_SYSTEM",
            "password": "SYS",
            "namespace": "USER",
        }
    )

    # Test normalization through _normalize_parameters
    params = ["2026-01-29T21:27:38.111Z", 123]
    normalized = executor._normalize_parameters(params)

    assert normalized[0] == "2026-01-29 21:27:38.111"
    assert normalized[1] == 123

    print("✅ IRISExecutor normalization unit tests passed")


if __name__ == "__main__":
    test_timestamp_normalization_unit()
    test_iris_executor_normalization_unit()
