"""
Coverage-boost tests for catalog emulator classes and installer paths.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest

# ============================================================================
# pg_namespace.py
# ============================================================================
from iris_pgwire.catalog.pg_namespace import PgNamespace, PgNamespaceEmulator


class TestPgNamespaceEmulator:
    def setup_method(self):
        self.emu = PgNamespaceEmulator()

    def test_static_namespaces_present(self):
        nss = self.emu.get_all()
        names = [n.nspname for n in nss]
        assert "pg_catalog" in names
        assert "public" in names
        assert "information_schema" in names

    def test_get_all_as_rows(self):
        rows = self.emu.get_all_as_rows()
        assert len(rows) == 3
        assert all(len(r) == 4 for r in rows)

    def test_get_by_name_found(self):
        ns = self.emu.get_by_name("public")
        assert ns is not None
        assert ns.oid == 2200

    def test_get_by_name_missing(self):
        ns = self.emu.get_by_name("nonexistent")
        assert ns is None

    def test_get_by_oid_found(self):
        ns = self.emu.get_by_oid(11)
        assert ns is not None
        assert ns.nspname == "pg_catalog"

    def test_get_by_oid_missing(self):
        ns = self.emu.get_by_oid(99999)
        assert ns is None

    def test_add_namespace(self):
        ns = PgNamespace(oid=50000, nspname="myschema", nspowner=10, nspacl=None)
        self.emu.add_namespace(ns)
        assert self.emu.get_by_name("myschema") is not None
        assert len(self.emu.get_all()) == 4

    def test_add_namespace_duplicate_by_oid(self):
        ns = PgNamespace(oid=2200, nspname="duplicate_public", nspowner=10, nspacl=None)
        self.emu.add_namespace(ns)
        # Should not be added — oid 2200 already exists
        assert len(self.emu.get_all()) == 3

    def test_add_namespace_duplicate_by_name(self):
        ns = PgNamespace(oid=99998, nspname="public", nspowner=10, nspacl=None)
        self.emu.add_namespace(ns)
        # Should not be added — name 'public' already exists
        assert len(self.emu.get_all()) == 3

    def test_get_column_definitions(self):
        from iris_pgwire.catalog.pg_namespace import PgNamespaceEmulator
        cols = PgNamespaceEmulator.get_column_definitions()
        assert len(cols) == 4
        names = [c["name"] for c in cols]
        assert "oid" in names and "nspname" in names


# ============================================================================
# pg_attribute.py
# ============================================================================
from iris_pgwire.catalog.pg_attribute import PgAttributeEmulator
from iris_pgwire.catalog.oid_generator import OIDGenerator


class TestPgAttributeEmulator:
    def setup_method(self):
        self.emu = PgAttributeEmulator(OIDGenerator())

    def test_from_iris_column_varchar(self):
        a = self.emu.from_iris_column("users", "email", "VARCHAR(255)", 2, "NO", None)
        assert a.attname == "email"
        assert a.atttypid == 1043  # varchar
        assert a.atttypmod == 259  # 255 + 4
        assert a.attnotnull is True
        assert a.atthasdef is False

    def test_from_iris_column_integer(self):
        a = self.emu.from_iris_column("users", "id", "INTEGER", 1, "NO", "1")
        assert a.atttypid == 23
        assert a.atthasdef is True
        assert a.atttypmod == -1

    def test_from_iris_column_nullable(self):
        a = self.emu.from_iris_column("t", "name", "VARCHAR(100)", 1, "YES", None)
        assert a.attnotnull is False

    def test_from_iris_column_unknown_type(self):
        a = self.emu.from_iris_column("t", "data", "JSONB", 1, "YES", None)
        assert a.atttypid == 25  # default to text

    def test_from_iris_column_char(self):
        a = self.emu.from_iris_column("t", "code", "CHAR(10)", 1, "NO", None)
        assert a.atttypid == 1042  # bpchar
        assert a.atttypmod == 14  # 10 + 4

    def test_from_iris_column_bad_modifier(self):
        # Malformed modifier should not raise
        a = self.emu.from_iris_column("t", "x", "VARCHAR(abc)", 1, "NO", None)
        assert a.atttypmod == -1

    def test_add_attribute_and_get_all(self):
        a = self.emu.from_iris_column("users", "id", "INTEGER", 1, "NO", None)
        self.emu.add_attribute(a)
        assert len(self.emu.get_all()) == 1

    def test_get_all_as_rows(self):
        a = self.emu.from_iris_column("users", "id", "INTEGER", 1, "NO", None)
        self.emu.add_attribute(a)
        rows = self.emu.get_all_as_rows()
        assert len(rows) == 1
        assert isinstance(rows[0], tuple)

    def test_get_by_table_oid(self):
        a = self.emu.from_iris_column("users", "id", "INTEGER", 1, "NO", None)
        self.emu.add_attribute(a)
        results = self.emu.get_by_table_oid(a.attrelid)
        assert len(results) == 1

    def test_get_by_table_oid_sorted(self):
        a2 = self.emu.from_iris_column("users", "email", "VARCHAR(100)", 2, "YES", None)
        a1 = self.emu.from_iris_column("users", "id", "INTEGER", 1, "NO", None)
        self.emu.add_attribute(a2)
        self.emu.add_attribute(a1)
        results = self.emu.get_by_table_oid(a1.attrelid)
        assert results[0].attnum < results[1].attnum

    def test_get_by_table_oid_missing(self):
        assert self.emu.get_by_table_oid(99999) == []

    def test_get_by_table_oid_as_rows(self):
        a = self.emu.from_iris_column("t", "col", "INTEGER", 1, "NO", None)
        self.emu.add_attribute(a)
        rows = self.emu.get_by_table_oid_as_rows(a.attrelid)
        assert len(rows) == 1
        assert isinstance(rows[0], tuple)


# ============================================================================
# pg_index.py
# ============================================================================
from iris_pgwire.catalog.pg_index import PgIndexEmulator


class TestPgIndexEmulator:
    def setup_method(self):
        self.emu = PgIndexEmulator(OIDGenerator())

    def test_from_primary_key(self):
        cls, idx = self.emu.from_primary_key("users", "pk_users", [1])
        assert idx.indisprimary is True
        assert idx.indisunique is True
        assert idx.indkey == [1]
        assert cls.relkind == "i"

    def test_from_unique_constraint(self):
        cls, idx = self.emu.from_unique_constraint("users", "uq_email", [2])
        assert idx.indisprimary is False
        assert idx.indisunique is True
        assert idx.indkey == [2]

    def test_add_index_and_get_all(self):
        cls, idx = self.emu.from_primary_key("users", "pk_users", [1])
        self.emu.add_index(cls, idx)
        assert len(self.emu.get_all_indexes()) == 1
        assert len(self.emu.get_all_index_classes()) == 1

    def test_get_all_as_rows(self):
        cls, idx = self.emu.from_primary_key("t", "pk_t", [1])
        self.emu.add_index(cls, idx)
        rows = self.emu.get_all_as_rows()
        assert len(rows) == 1
        assert isinstance(rows[0], tuple)

    def test_get_by_table_oid(self):
        cls, idx = self.emu.from_primary_key("t", "pk_t", [1])
        self.emu.add_index(cls, idx)
        results = self.emu.get_by_table_oid(idx.indrelid)
        assert len(results) == 1
        assert results[0].indisprimary is True

    def test_get_by_table_oid_missing(self):
        assert self.emu.get_by_table_oid(99999) == []

    def test_get_by_table_oid_as_rows(self):
        cls, idx = self.emu.from_primary_key("t", "pk_t", [1, 2])
        self.emu.add_index(cls, idx)
        rows = self.emu.get_by_table_oid_as_rows(idx.indrelid)
        assert len(rows) == 1

    def test_multi_column_index(self):
        cls, idx = self.emu.from_primary_key("t", "pk_composite", [1, 2, 3])
        assert idx.indnatts == 3
        assert len(idx.indkey) == 3
        assert len(idx.indcollation) == 3


# ============================================================================
# function_installer.py async paths
# ============================================================================
from iris_pgwire.catalog.function_installer import CatalogFunctionInstaller, CatalogFunctionInstallError


class TestCatalogFunctionInstaller:
    def _make_installer(self, success=True, error_msg=None):
        executor = MagicMock()
        if success:
            executor.execute_query = AsyncMock(return_value={"success": True})
        elif error_msg:
            executor.execute_query = AsyncMock(side_effect=RuntimeError(error_msg))
        else:
            executor.execute_query = AsyncMock(return_value={"success": False, "error": "DDL failed"})
        return CatalogFunctionInstaller(executor)

    @pytest.mark.asyncio
    async def test_install_success(self):
        installer = self._make_installer(success=True)
        installed = await installer.install(session_id="test")
        assert len(installed) > 0
        assert all("PGWire." in name for name in installed)

    @pytest.mark.asyncio
    async def test_install_one_executor_exception(self):
        from iris_pgwire.catalog.functions import CATALOG_FUNCTIONS
        executor = MagicMock()
        executor.execute_query = AsyncMock(side_effect=RuntimeError("connection refused"))
        installer = CatalogFunctionInstaller(executor)
        with pytest.raises((CatalogFunctionInstallError, RuntimeError)):
            await installer._install_one(CATALOG_FUNCTIONS[0], session_id="test")

    @pytest.mark.asyncio
    async def test_install_failure_result(self):
        installer = self._make_installer(success=False)
        with pytest.raises(CatalogFunctionInstallError, match="DDL failed"):
            await installer.install(session_id="test")

    @pytest.mark.asyncio
    async def test_verify(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(return_value={"success": True})
        installer = CatalogFunctionInstaller(executor)
        status = await installer.verify(session_id="test")
        assert isinstance(status, dict)
        assert any("PG_OID" in k for k in status)

    @pytest.mark.asyncio
    async def test_verify_with_exception(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(side_effect=RuntimeError("probe failed"))
        installer = CatalogFunctionInstaller(executor)
        status = await installer.verify(session_id="test")
        assert all(v is False for v in status.values())


# ============================================================================
# views/installer.py async paths
# ============================================================================
from iris_pgwire.catalog.views.installer import CatalogViewInstaller, CatalogViewInstallError


class TestCatalogViewInstaller:
    @pytest.mark.asyncio
    async def test_install_success(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(return_value={"success": True})
        installer = CatalogViewInstaller(executor)
        installed = await installer.install(session_id="test")
        assert len(installed) > 0

    @pytest.mark.asyncio
    async def test_install_failure_raises(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(return_value={"success": False, "error": "view error"})
        installer = CatalogViewInstaller(executor)
        with pytest.raises(CatalogViewInstallError):
            await installer.install(session_id="test")

    @pytest.mark.asyncio
    async def test_install_exception_raises(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(side_effect=RuntimeError("boom"))
        installer = CatalogViewInstaller(executor)
        with pytest.raises(CatalogViewInstallError):
            await installer.install(session_id="test")

    @pytest.mark.asyncio
    async def test_execute_tolerate_failure(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(side_effect=RuntimeError("tolerated"))
        installer = CatalogViewInstaller(executor)
        result = await installer._execute("SELECT 1", session_id="test", tolerate_failure=True)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_intolerant_raises(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(side_effect=RuntimeError("fatal"))
        installer = CatalogViewInstaller(executor)
        with pytest.raises(CatalogViewInstallError):
            await installer._execute("SELECT 1", session_id="test", tolerate_failure=False)

    @pytest.mark.asyncio
    async def test_verify(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(return_value={"success": True})
        installer = CatalogViewInstaller(executor)
        status = await installer.verify(session_id="test")
        assert isinstance(status, dict)
        assert len(status) > 0

    @pytest.mark.asyncio
    async def test_verify_exception(self):
        executor = MagicMock()
        executor.execute_query = AsyncMock(side_effect=RuntimeError("probe"))
        installer = CatalogViewInstaller(executor)
        status = await installer.verify(session_id="test")
        assert all(v is False for v in status.values())
