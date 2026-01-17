"""
Unit tests for centralized conversion utilities.
"""

import datetime

import pytest

from iris_pgwire.conversions.date_horolog import (
    EPOCH_OFFSET,
    date_to_horolog,
    horolog_to_date,
    horolog_to_pg,
    pg_to_horolog,
)


def test_horolog_to_pg():
    # 2025-11-13 is 67522 in Horolog
    # 2025-11-13 is 9448 in PG (days since 2000-01-01)
    assert horolog_to_pg(67522) == 9448
    assert horolog_to_pg(58074) == 0  # 2000-01-01


def test_pg_to_horolog():
    assert pg_to_horolog(9448) == 67522
    assert pg_to_horolog(0) == 58074


def test_date_to_horolog():
    dt = datetime.date(2025, 11, 13)
    assert date_to_horolog(dt) == 67522

    dt_now = datetime.datetime(2025, 11, 13, 12, 0, 0)
    assert date_to_horolog(dt_now) == 67522


def test_horolog_to_date():
    assert horolog_to_date(67522) == datetime.date(2025, 11, 13)
    assert horolog_to_date(0) == datetime.date(1840, 12, 31)


def test_epoch_offset():
    # Verify the calculated EPOCH_OFFSET matches expectation
    # 2000-01-01 minus 1840-12-31
    expected = (datetime.date(2000, 1, 1) - datetime.date(1840, 12, 31)).days
    assert EPOCH_OFFSET == expected
