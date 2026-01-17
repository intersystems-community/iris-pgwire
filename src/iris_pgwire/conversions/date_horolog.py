"""
Centralized utilities for converting between IRIS Horolog and PostgreSQL date formats.
"""

import datetime
import logging

logger = logging.getLogger(__name__)

# IRIS Horolog base date: 1840-12-31
HOROLOG_BASE = datetime.date(1840, 12, 31)

# PostgreSQL J2000 epoch: 2000-01-01
PG_EPOCH = datetime.date(2000, 1, 1)

# Calculate offset between IRIS and PostgreSQL epochs
# Days from 1840-12-31 to 2000-01-01
EPOCH_OFFSET = (PG_EPOCH - HOROLOG_BASE).days


def horolog_to_pg(horolog_days: int) -> int:
    """
    Convert IRIS Horolog date to PostgreSQL date format.

    IRIS Horolog Format:
    - Stores dates as days since 1840-12-31 (base date)
    - Example: 67699 days = 2025-11-13

    PostgreSQL Date Format:
    - Stores dates as days since 2000-01-01 (J2000 epoch)
    - Example: 9448 days = 2025-11-13

    Args:
        horolog_days: IRIS Horolog date value (days since 1840-12-31)

    Returns:
        PostgreSQL date value (days since 2000-01-01)
    """
    pg_days = horolog_days - EPOCH_OFFSET
    return pg_days


def pg_to_horolog(pg_days: int) -> int:
    """
    Convert PostgreSQL date format to IRIS Horolog date.

    Args:
        pg_days: PostgreSQL date value (days since 2000-01-01)

    Returns:
        IRIS Horolog date value (days since 1840-12-31)
    """
    horolog_days = pg_days + EPOCH_OFFSET
    return horolog_days


def date_to_horolog(date_obj: datetime.date | datetime.datetime) -> int:
    """
    Convert a Python date or datetime object to IRIS Horolog days.

    Args:
        date_obj: Python date or datetime object

    Returns:
        IRIS Horolog days
    """
    if isinstance(date_obj, datetime.datetime):
        date_obj = date_obj.date()
    return (date_obj - HOROLOG_BASE).days


def horolog_to_date(horolog_days: int) -> datetime.date:
    """
    Convert IRIS Horolog days to a Python date object.

    Args:
        horolog_days: IRIS Horolog days

    Returns:
        Python date object
    """
    return HOROLOG_BASE + datetime.timedelta(days=horolog_days)
