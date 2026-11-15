"""Strict or permissive, for the statements spec 052 refuses (FR-025, FR-026).

Strict, the default, refuses with a PostgreSQL SQLSTATE a statement PGWire cannot run exactly on
IRIS: the locking clauses without an exact emulation, the ON CONFLICT forms IRIS's INSERT OR
UPDATE does not express. ``PGWIRE_TXN_COMPAT=permissive`` runs those as 2.0 did and logs one
warning per statement shape. The exact emulations (the abort rule, the savepoint stack) do not
depend on this setting.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import structlog

from .schema_mapper import IRIS_SCHEMA

logger = structlog.get_logger("iris_pgwire.compat")

MODES = ("strict", "permissive")
MAX_SHAPES = 1000

_LITERALS = re.compile(r"'(?:[^']|'')*'|\$\d+|\?|\b\d+(?:\.\d*)?\b")
_SPACE = re.compile(r"\s+")
_DDL_PREFIXES = ("CREATE", "DROP", "ALTER")


def statement_shape(sql: str) -> str:
    """The statement with literals and parameter markers replaced, whitespace collapsed.

    Quoted identifiers keep their text, so two tables stay two shapes; keywords and unquoted
    names are compared without case.
    """
    shape = _LITERALS.sub("?", sql)
    parts = re.split(r'("(?:[^"]|"")*")', shape)
    shape = "".join(p if p.startswith('"') else p.upper() for p in parts)
    return _SPACE.sub(" ", shape).strip()


class CompatMode:
    """The server's mode, and the shapes it has already warned about (oldest dropped)."""

    def __init__(self, mode: str = "strict", *, max_shapes: int = MAX_SHAPES):
        if mode not in MODES:
            raise ValueError(f"PGWIRE_TXN_COMPAT must be one of {', '.join(MODES)}, not {mode!r}")
        self.permissive = mode == "permissive"
        self._max = max_shapes
        self._seen: OrderedDict[str, None] = OrderedDict()

    def first_time(self, sql: str) -> bool:
        """True the first time this statement's shape is seen (so warn), False after."""
        shape = statement_shape(sql)
        if shape in self._seen:
            self._seen.move_to_end(shape)
            return False
        self._seen[shape] = None
        if len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return True

    def __len__(self) -> int:
        return len(self._seen)


class CompatMixin:
    """For executors: the server's mode, its warnings, and catalog answers cached until DDL.

    The host class must provide ``config`` (a ``BackendConfig``).
    """

    @property
    def compat(self) -> CompatMode:
        mode = getattr(self, "_compat_mode", None)
        if mode is None:
            mode = CompatMode(getattr(self.config, "txn_compat", "strict"))  # type: ignore[attr-defined]
            self._compat_mode = mode
        return mode

    @property
    def catalog_facts(self) -> dict:
        """Per-table catalog answers, keyed by (purpose, schema, table); dropped on any DDL."""
        facts = getattr(self, "_catalog_facts", None)
        if facts is None:
            facts = {}
            self._catalog_facts: dict = facts
        return facts

    def cached_table_fact(
        self,
        purpose: str,
        schema: str | None,
        table: str,
        read: Callable[[str, str], Any],
    ) -> Any:
        """``read(schema, table)``, cached until DDL; a None answer (no such table) is not cached.

        No schema, or `public`, means IRIS's default schema; both names are compared lower case.
        """
        if not schema or schema.lower() == "public":
            schema = IRIS_SCHEMA
        key = (purpose, schema.lower(), table.lower())
        fact = self.catalog_facts.get(key)
        if fact is None:
            fact = read(key[1], key[2])
            if fact is not None:
                self.catalog_facts[key] = fact
        return fact

    def note_ddl(self, sql: str) -> None:
        """Drop the cached catalog answers when a statement may have changed a table."""
        if self.catalog_facts and sql.lstrip()[:6].upper().startswith(_DDL_PREFIXES):
            self.catalog_facts.clear()

    def permissive_warning(self, sql: str, why: str | None) -> None:
        if self.compat.first_time(sql):
            logger.warning(
                "Permissive mode: running a statement strict mode refuses",
                reason=why,
                statement=sql[:300],
            )
