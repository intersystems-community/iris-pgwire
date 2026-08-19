"""Re-entrancy guard for catalog query handling.

Lives in its own module because two things need it and importing it from
`catalog_router` creates a cycle: the router imports the view registry, and the
view installer needs the guard.

Some handlers answer a catalog query by issuing their own SQL through the
executor — `_build_pg_class_response` asks IRIS for `INFORMATION_SCHEMA.TABLES`.
That inner query re-enters the router, which would intercept it and return zero
rows, leaving the handler with nothing to report. The view installer has the
same problem in a sharper form: its `CREATE VIEW pg_catalog.pg_class AS ...` was
handed to the pg_class handler, which answered it with a synthetic success — so
installation reported success while creating nothing.

A ContextVar rather than a flag, so the guard is scoped to the asyncio task and
one session's internal query cannot suppress interception for a concurrent one.
"""

from __future__ import annotations

import contextvars

_IN_CATALOG_HANDLER: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "iris_pgwire_in_catalog_handler", default=False
)

__all__ = ["_IN_CATALOG_HANDLER"]
