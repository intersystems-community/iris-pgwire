"""A cap on how many rows an executor fetches, for callers that need a result's shape only.

Describe has to answer with a statement's columns, and the executors learn columns by running the
statement, so Describe used to fetch every row and throw them away (0.9 s per 100,000 rows on the
embedded backend, measured 2026-11-14), before the Execute that follows ran the statement again.

The cap is a ContextVar, so it reaches the executors' worker threads (asyncio.to_thread copies the
context, and the embedded executor runs its worker in a copied one) without being threaded through
every signature between the protocol and the fetch.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

T = TypeVar("T")

_LIMIT: ContextVar[int | None] = ContextVar("pgwire_row_limit", default=None)


@contextmanager
def at_most(rows: int) -> Iterator[None]:
    """Within this block, executors fetch at most `rows` rows of a result."""
    token = _LIMIT.set(rows)
    try:
        yield
    finally:
        _LIMIT.reset(token)


def current() -> int | None:
    """The cap in force, or None when every row is wanted."""
    return _LIMIT.get()


def limited(rows: Iterable[T]) -> Iterable[T]:
    """`rows`, stopped after the cap in force."""
    limit = _LIMIT.get()
    return rows if limit is None else itertools.islice(rows, limit)
