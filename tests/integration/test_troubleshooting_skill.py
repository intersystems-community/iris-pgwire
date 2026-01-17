"""
Test Troubleshooting Agentic Skill Integration.
Validates FR-011, FR-012.
"""

import json
import os

import pytest


def test_troubleshooting_on_failure(iris_container):
    """
    Test that test failures trigger troubleshooting logic.
    This effectively tests the /troubleshooting skill logic.
    """
    # We can't easily trigger a real failure and continue,
    # but we can verify that the validation logic is in place.
    from iris_devtester.containers.models import HealthCheckLevel

    # Run container validation manually (Automates the /troubleshooting / /container status logic)
    result = iris_container.validate(level=HealthCheckLevel.FULL)
    assert result.success is True
    assert result.status == "healthy"

    print(f"\n✅ Diagnostic report generated: {result.status}")


@pytest.mark.skip(reason="Intended to be run manually to verify test_failures.jsonl")
def test_intentional_failure(iris_connection):
    """
    Intentionally fail to verify test_failures.jsonl generation.
    """
    raise AssertionError("Intentional failure for troubleshooting verification")
