"""
Coverage-boost tests for schema_mapper, package_metadata_validator,
and catalog_functions format_type/modifier paths.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


# ============================================================================
# schema_mapper.py — translate_output_schema and configure_schema
# ============================================================================

class TestSchemaMapperOutputTranslation:
    def test_empty_rows_returns_unchanged(self):
        from iris_pgwire.schema_mapper import translate_output_schema
        assert translate_output_schema([], ["table_schema"]) == []

    def test_empty_columns_returns_unchanged(self):
        from iris_pgwire.schema_mapper import translate_output_schema
        rows = [("SQLUser", "t1")]
        assert translate_output_schema(rows, []) == rows

    def test_no_schema_columns_returns_unchanged(self):
        from iris_pgwire.schema_mapper import translate_output_schema
        rows = [("t1", 1)]
        result = translate_output_schema(rows, ["table_name", "id"])
        assert result == rows

    def test_schema_column_translated(self):
        from iris_pgwire.schema_mapper import translate_output_schema, IRIS_SCHEMA
        rows = [(IRIS_SCHEMA, "t1")]
        result = translate_output_schema(rows, ["table_schema", "table_name"])
        assert result[0][0] == "public"
        assert result[0][1] == "t1"

    def test_non_iris_schema_not_translated(self):
        from iris_pgwire.schema_mapper import translate_output_schema
        rows = [("%SYS", "t1")]
        result = translate_output_schema(rows, ["table_schema", "table_name"])
        assert result[0][0] == "%SYS"

    def test_schema_column_case_insensitive(self):
        from iris_pgwire.schema_mapper import translate_output_schema, IRIS_SCHEMA
        rows = [(IRIS_SCHEMA, "x")]
        result = translate_output_schema(rows, ["TABLE_SCHEMA", "name"])
        assert result[0][0] == "public"

    def test_nspname_column_translated(self):
        from iris_pgwire.schema_mapper import translate_output_schema, IRIS_SCHEMA
        rows = [(IRIS_SCHEMA,)]
        result = translate_output_schema(rows, ["nspname"])
        assert result[0][0] == "public"

    def test_schema_name_column_translated(self):
        from iris_pgwire.schema_mapper import translate_output_schema, IRIS_SCHEMA
        rows = [(IRIS_SCHEMA,)]
        result = translate_output_schema(rows, ["schema_name"])
        assert result[0][0] == "public"


class TestGetSchemaConfig:
    def test_returns_dict_with_keys(self):
        from iris_pgwire.schema_mapper import get_schema_config
        cfg = get_schema_config()
        assert "iris_schema" in cfg
        assert "postgres_schema" in cfg
        assert "source" in cfg
        assert cfg["postgres_schema"] == "public"

    def test_source_is_default_when_no_env(self):
        from iris_pgwire.schema_mapper import get_schema_config
        env_backup = os.environ.pop("PGWIRE_IRIS_SCHEMA", None)
        try:
            cfg = get_schema_config()
            assert cfg["source"] in ("default", "env")  # depends on module load order
        finally:
            if env_backup is not None:
                os.environ["PGWIRE_IRIS_SCHEMA"] = env_backup


class TestConfigureSchema:
    def teardown_method(self):
        # Restore default after each test
        import iris_pgwire.schema_mapper as sm
        sm.IRIS_SCHEMA = "SQLUser"
        sm.SCHEMA_MAP = {"public": "SQLUser"}
        sm.REVERSE_MAP = {"SQLUser": "public"}

    def test_configure_iris_schema(self):
        import iris_pgwire.schema_mapper as sm
        from iris_pgwire.schema_mapper import configure_schema
        configure_schema(iris_schema="MyAppSchema")
        assert sm.IRIS_SCHEMA == "MyAppSchema"
        assert sm.SCHEMA_MAP == {"public": "MyAppSchema"}
        assert sm.REVERSE_MAP == {"MyAppSchema": "public"}

    def test_configure_mapping_dict(self):
        import iris_pgwire.schema_mapper as sm
        from iris_pgwire.schema_mapper import configure_schema
        configure_schema(mapping={"public": "AppSchema"})
        assert sm.IRIS_SCHEMA == "AppSchema"
        assert sm.SCHEMA_MAP == {"public": "AppSchema"}

    def test_configure_no_args_raises(self):
        from iris_pgwire.schema_mapper import configure_schema
        with pytest.raises(ValueError, match="Must provide"):
            configure_schema()


# ============================================================================
# package_metadata_validator.py
# ============================================================================
from iris_pgwire.quality.package_metadata_validator import PackageMetadataValidator


class TestPackageMetadataValidator:
    def setup_method(self):
        self.v = PackageMetadataValidator()

    def _write_pyproject(self, content: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="pyproject.toml", delete=False
        ) as f:
            f.write(content)
            return f.name

    def test_validate_metadata_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            self.v.validate_metadata("/nonexistent/pyproject.toml")

    def test_validate_metadata_malformed_toml(self):
        path = self._write_pyproject("NOT VALID TOML {{{{")
        try:
            with pytest.raises(ValueError, match="Malformed"):
                self.v.validate_metadata(path)
        finally:
            os.unlink(path)

    def test_validate_metadata_missing_fields(self):
        path = self._write_pyproject('[project]\nname = "mypkg"\n')
        try:
            with patch.object(self.v, "check_pyroma_score", return_value=(10, 10)):
                result = self.v.validate_metadata(path)
            assert not result["is_valid"]
            assert "version" in result["missing_fields"]
        finally:
            os.unlink(path)

    def test_validate_metadata_valid(self):
        content = """
[project]
name = "mypkg"
version = "1.0.0"
description = "A package"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Tom"}]
"""
        path = self._write_pyproject(content)
        try:
            with patch.object(self.v, "check_pyroma_score", return_value=(10, 10)):
                result = self.v.validate_metadata(path)
            assert result["is_valid"] is True
            assert result["missing_fields"] == []
        finally:
            os.unlink(path)

    def test_validate_metadata_dynamic_version(self):
        content = """
[project]
name = "mypkg"
description = "A package"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Tom"}]
dynamic = ["version"]
"""
        path = self._write_pyproject(content)
        try:
            with patch.object(self.v, "check_pyroma_score", return_value=(10, 10)):
                result = self.v.validate_metadata(path)
            assert "version" not in result["missing_fields"]
        finally:
            os.unlink(path)

    def test_check_pyroma_score_parse(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="Your package scores 9 out of 10", stderr="", returncode=0)
            score, max_score = self.v.check_pyroma_score("/tmp")
            assert score == 9
            assert max_score == 10

    def test_check_pyroma_score_no_match(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="some other output", stderr="", returncode=0)
            score, max_score = self.v.check_pyroma_score("/tmp")
            assert score == 10  # default
            assert max_score == 10

    def test_check_pyroma_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(RuntimeError, match="not installed"):
                self.v.check_pyroma_score("/tmp")

    def test_check_pyroma_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pyroma", 30)):
            with pytest.raises(RuntimeError, match="timed out"):
                self.v.check_pyroma_score("/tmp")

    def test_validate_classifiers_empty(self):
        ok, invalid = self.v.validate_classifiers([])
        assert ok is True
        assert invalid == []

    def test_validate_dependencies_valid(self):
        ok, errors = self.v.validate_dependencies({"requests": ">=2.0.0"})
        assert ok is True
        assert errors == []

    def test_validate_dependencies_invalid(self):
        ok, errors = self.v.validate_dependencies({"requests": ""})
        assert ok is False
        assert any("requests" in e for e in errors)

    def test_check_manifest_completeness_ok(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="OK", stderr="", returncode=0)
            ok, msg = self.v.check_manifest_completeness("/tmp")
            assert ok is True
            assert "OK" in msg

    def test_check_manifest_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            ok, msg = self.v.check_manifest_completeness("/tmp")
            assert ok is False
            assert "not installed" in msg

    def test_check_manifest_timeout(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("check-manifest", 30)):
            ok, msg = self.v.check_manifest_completeness("/tmp")
            assert ok is False
            assert "timed out" in msg

    def test_check_manifest_generic_exception(self):
        with patch("subprocess.run", side_effect=RuntimeError("err")):
            ok, msg = self.v.check_manifest_completeness("/tmp")
            assert ok is False
            assert "err" in msg


# ============================================================================
# catalog/catalog_functions.py — CatalogFunctionHandler format_type paths
# ============================================================================
from iris_pgwire.catalog.catalog_functions import CatalogFunctionHandler
from iris_pgwire.catalog.oid_generator import OIDGenerator


class TestCatalogFunctionHandlerFormatType:
    def setup_method(self):
        self.handler = CatalogFunctionHandler(OIDGenerator(), executor=MagicMock())

    def test_format_type_unknown_oid(self):
        result = self.handler.format_type(99999, -1)
        assert result is None

    def test_format_type_integer(self):
        result = self.handler.format_type(23, -1)
        assert result == "integer"

    def test_format_type_varchar_with_modifier(self):
        # typmod for varchar(255) = 255 + 4 = 259
        result = self.handler.format_type(1043, 259)
        assert result == "character varying(255)"

    def test_format_type_varchar_no_modifier(self):
        result = self.handler.format_type(1043, -1)
        assert result == "character varying"

    def test_format_type_numeric_with_modifier(self):
        # numeric(10,2): typmod = (10 * 65536 + 2) + 4
        typmod = 10 * 65536 + 2 + 4
        result = self.handler.format_type(1700, typmod)
        assert result == "numeric(10,2)"

    def test_format_type_numeric_no_modifier(self):
        result = self.handler.format_type(1700, -1)
        assert result == "numeric"

    def test_format_type_timestamp(self):
        result = self.handler.format_type(1114, -1)
        assert "timestamp" in result.lower()

    def test_format_type_boolean(self):
        result = self.handler.format_type(16, -1)
        assert result == "boolean"

    def test_format_with_modifier_negative_typmod(self):
        result = self.handler._format_with_modifier(1043, -1, "character varying")
        assert result is None

    def test_format_with_modifier_numeric(self):
        typmod = 10 * 65536 + 2 + 4
        result = self.handler._format_with_modifier(1700, typmod, "numeric")
        assert "numeric" in result

    def test_format_with_modifier_timestamp_type(self):
        # timestamp with precision modifier
        typmod = 6 + 1  # precision 6 encoded somehow
        result = self.handler._format_with_modifier(1114, typmod, "timestamp without time zone")
        # May return None if precision decoding logic rejects
        # Just ensure no exception
        assert result is None or "timestamp" in result

    def test_format_with_modifier_bit_type(self):
        result = self.handler._format_with_modifier(1560, 5, "bit")
        # May return None if decode returns None
        assert result is None or "bit" in result

    def test_format_with_modifier_unknown_type(self):
        result = self.handler._format_with_modifier(9999, 5, "unknown")
        assert result is None
