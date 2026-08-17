"""Create the PGWire SQL functions in IRIS, idempotently.

Runs before the view installer, which cannot define a single view without them.

Before this existed the functions had to be loaded by hand with
`$SYSTEM.OBJ.Load`, and nothing in the codebase did it — so catalog views only
worked on an instance where someone had already done so, and a fresh one would
fail at startup. Installing them over SQL removes the manual step and works
identically on both backends, since `CREATE FUNCTION` needs only a connection
whereas loading a class file needs the source on the server's own filesystem.

Failures are raised, never swallowed, for the same reason the view installer
raises: a catalog that half-installs answers introspection with empty results,
which reads to a client as "this database has nothing in it" (spec FR-009).
"""

from __future__ import annotations

import structlog

from ..sql_translator.verbatim import verbatim_sql
from ._reentrancy import _IN_CATALOG_HANDLER
from .functions import CATALOG_FUNCTIONS, CATALOG_SCHEMA, CatalogFunction

logger = structlog.get_logger(__name__)


class CatalogFunctionInstallError(RuntimeError):
    """Raised when a PGWire SQL function cannot be created."""


class CatalogFunctionInstaller:
    """Install the ObjectScript-bodied SQL functions the catalog depends on."""

    def __init__(self, executor):
        self._executor = executor

    async def install(self, session_id: str | None = None) -> list[str]:
        """Create every function, replacing any existing definition.

        Returns the qualified names installed. Idempotent by construction —
        `CREATE OR REPLACE` converges rather than needing a DROP first.

        Routing is suppressed for the same reason the view installer suppresses
        it: these statements mention catalog names, and the router would answer
        them with a synthetic success while nothing was created.
        """
        installed: list[str] = []
        guard = _IN_CATALOG_HANDLER.set(True)
        try:
            # Verbatim: the bodies are ObjectScript, and the translation
            # pipeline uppercases identifiers. It turned $SYSTEM.Encryption into
            # %SYSTEM.ENCRYPTION (class names are case-sensitive) and cased the
            # declared parameter differently from its uses in the body. Both
            # installed cleanly and then failed on every call.
            with verbatim_sql():
                for function in CATALOG_FUNCTIONS:
                    await self._install_one(function, session_id)
                    installed.append(function.qualified_name)
        finally:
            _IN_CATALOG_HANDLER.reset(guard)

        logger.info("Catalog functions installed", schema=CATALOG_SCHEMA, functions=installed)
        return installed

    async def _install_one(self, function: CatalogFunction, session_id: str | None) -> None:
        try:
            result = await self._executor.execute_query(
                function.create_sql(), session_id=session_id
            )
        except Exception as exc:  # noqa: BLE001 — re-raised as an install error
            raise CatalogFunctionInstallError(
                f"Could not create {function.qualified_name} ({function.purpose}): {exc}"
            ) from exc

        if not result.get("success", False):
            raise CatalogFunctionInstallError(
                f"Could not create {function.qualified_name} ({function.purpose}): "
                f"{result.get('error')}. The catalog views depend on it, so startup is "
                "aborted rather than serving a catalog that answers with empty results."
            )

    async def verify(self, session_id: str | None = None) -> dict[str, bool]:
        """Report which functions are present and callable."""
        probes = {
            "PG_OID": f"SELECT {CATALOG_SCHEMA}.PG_OID('probe')",
            "PG_PUBLIC_SCHEMA": f"SELECT {CATALOG_SCHEMA}.PG_PUBLIC_SCHEMA()",
            "PG_ARRAY": f"SELECT {CATALOG_SCHEMA}.PG_ARRAY('0|')",
        }
        status: dict[str, bool] = {}
        guard = _IN_CATALOG_HANDLER.set(True)
        try:
            for name, probe in probes.items():
                qualified = f"{CATALOG_SCHEMA}.{name}"
                try:
                    result = await self._executor.execute_query(probe, session_id=session_id)
                    status[qualified] = bool(result.get("success", False))
                except Exception:  # noqa: BLE001 — absence is the answer, not an error
                    status[qualified] = False
        finally:
            _IN_CATALOG_HANDLER.reset(guard)
        return status
