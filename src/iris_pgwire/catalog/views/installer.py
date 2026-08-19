"""Create the pg_catalog views in IRIS, idempotently.

The server converges its own catalog at startup rather than relying on a
migration step, so a fresh container or a new namespace works with no manual
setup. Installation failures are raised, never swallowed: a half-installed
catalog would surface as "this database has no tables", which is exactly the
silent-empty-result failure mode this feature exists to remove (spec FR-009).
"""

from __future__ import annotations

import structlog

from .._reentrancy import _IN_CATALOG_HANDLER
from .definitions import CATALOG_SCHEMA, CATALOG_VIEWS, CatalogView

logger = structlog.get_logger(__name__)


class CatalogViewInstallError(RuntimeError):
    """Raised when a catalog view cannot be created."""


class CatalogViewInstaller:
    """Install and verify the emulated pg_catalog views."""

    def __init__(self, executor):
        self._executor = executor

    async def install(self, session_id: str | None = None) -> list[str]:
        """Create every catalog view, replacing any existing definition.

        Returns the qualified names installed. Idempotent: each view is dropped
        before being recreated, so a second run converges to the same state.

        Runs with catalog routing suppressed. Without that, the router sees
        "pg_class" in `CREATE VIEW pg_catalog.pg_class AS ...`, hands the DDL to
        the pg_class handler, and the handler answers it with a synthetic
        success — so installation reports success while no view is created.
        """
        installed: list[str] = []
        guard = _IN_CATALOG_HANDLER.set(True)
        try:
            for view in CATALOG_VIEWS:
                await self._install_one(view, session_id)
                installed.append(view.qualified_name)
        finally:
            _IN_CATALOG_HANDLER.reset(guard)

        logger.info(
            "Catalog views installed",
            schema=CATALOG_SCHEMA,
            views=installed,
        )
        return installed

    async def _install_one(self, view: CatalogView, session_id: str | None) -> None:
        """Drop then recreate one view, raising CatalogViewInstallError on CREATE failure."""
        # DROP is expected to fail the first time; only CREATE failure matters.
        await self._execute(view.drop_sql(), session_id, tolerate_failure=True)
        result = await self._execute(view.create_sql(), session_id, tolerate_failure=False)

        if not result.get("success", False):
            raise CatalogViewInstallError(
                f"Could not create {view.qualified_name}: {result.get('error')}. "
                "Catalog emulation would return empty results instead of errors, so "
                "startup is aborted rather than serving a half-installed catalog."
            )

    async def _execute(self, sql: str, session_id: str | None, *, tolerate_failure: bool) -> dict:
        """Run one DDL statement, optionally swallowing errors."""
        try:
            return await self._executor.execute_query(sql, session_id=session_id)
        except Exception as exc:  # noqa: BLE001 — re-raised below unless tolerated
            if tolerate_failure:
                logger.debug("Tolerated catalog DDL failure", sql=sql[:80], error=str(exc))
                return {"success": False, "error": str(exc)}
            raise CatalogViewInstallError(f"Failed executing {sql[:120]}: {exc}") from exc

    async def verify(self, session_id: str | None = None) -> dict[str, bool]:
        """Report which catalog views are currently present and queryable."""
        status: dict[str, bool] = {}
        guard = _IN_CATALOG_HANDLER.set(True)
        try:
            return await self._verify_all(session_id)
        finally:
            _IN_CATALOG_HANDLER.reset(guard)

    async def _verify_all(self, session_id: str | None) -> dict[str, bool]:
        status: dict[str, bool] = {}
        for view in CATALOG_VIEWS:
            probe = f"SELECT TOP 1 * FROM {view.qualified_name}"
            try:
                result = await self._executor.execute_query(probe, session_id=session_id)
                status[view.qualified_name] = bool(result.get("success", False))
            except Exception:  # noqa: BLE001 — absence is the answer, not an error
                status[view.qualified_name] = False
        return status
