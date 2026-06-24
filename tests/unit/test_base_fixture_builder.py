"""
Unit tests for testing/base_fixture_builder.py

All IRIS / iris_devtester / filesystem dependencies are mocked so tests
run without a live IRIS container or the example data files on disk.
"""

from __future__ import annotations

import csv
import io
import json
import re
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, call, patch, mock_open

import pytest

# ---------------------------------------------------------------------------
# Import the module under test.  iris_devtester is not installed in the test
# environment, so mock it at the package level before importing.
# ---------------------------------------------------------------------------

import sys
from types import ModuleType


def _make_devtester_mocks():
    """Build a minimal fake iris_devtester package tree."""
    pkg = ModuleType("iris_devtester")
    config_mod = ModuleType("iris_devtester.config")
    connections_mod = ModuleType("iris_devtester.connections")
    fixtures_mod = ModuleType("iris_devtester.fixtures")
    creator_mod = ModuleType("iris_devtester.fixtures.creator")
    loader_mod = ModuleType("iris_devtester.fixtures.loader")

    class IRISConfig:  # noqa: D401
        def __init__(self, **kw):
            self.__dict__.update(kw)

    config_mod.IRISConfig = IRISConfig
    connections_mod.get_connection = MagicMock()
    creator_mod.FixtureCreator = MagicMock()
    loader_mod.FixtureLoader = MagicMock()

    pkg.config = config_mod
    pkg.connections = connections_mod
    pkg.fixtures = fixtures_mod
    fixtures_mod.creator = creator_mod
    fixtures_mod.loader = loader_mod

    for name, mod in [
        ("iris_devtester", pkg),
        ("iris_devtester.config", config_mod),
        ("iris_devtester.connections", connections_mod),
        ("iris_devtester.fixtures", fixtures_mod),
        ("iris_devtester.fixtures.creator", creator_mod),
        ("iris_devtester.fixtures.loader", loader_mod),
    ]:
        sys.modules[name] = mod

    return pkg, config_mod, connections_mod, creator_mod, loader_mod


_pkg, _config_mod, _connections_mod, _creator_mod, _loader_mod = _make_devtester_mocks()

# Now we can safely import the module under test
from iris_pgwire.testing.base_fixture_builder import (  # noqa: E402
    _coerce_sql_value,
    _create_benchmark_vectors,
    _execute_sql_file,
    _extract_sql_tuples,
    _generate_vectors_by_dim,
    _is_float,
    _is_int,
    _load_lab_results,
    _load_patients,
    _none_if_empty,
    _parse_sql_tuple,
    _split_sql_statements,
    create_base_fixture,
    ensure_base_fixture,
    restore_fixture,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_container(namespace="TEST", host="localhost", port=1972, username="u", password="p", name="c"):
    c = MagicMock()
    c.get_test_namespace.return_value = namespace
    cfg = MagicMock()
    cfg.host = host
    cfg.port = port
    cfg.username = username
    cfg.password = password
    c.get_config.return_value = cfg
    c.get_container_name.return_value = name
    return c


# ---------------------------------------------------------------------------
# _is_int
# ---------------------------------------------------------------------------


class TestIsInt:
    @pytest.mark.parametrize("v", ["0", "123", "-42", "  7  "])
    def test_valid_integers(self, v):
        assert _is_int(v)

    @pytest.mark.parametrize("v", ["3.14", "abc", "", "1e5", "1.0"])
    def test_invalid_integers(self, v):
        assert not _is_int(v)


# ---------------------------------------------------------------------------
# _is_float
# ---------------------------------------------------------------------------


class TestIsFloat:
    @pytest.mark.parametrize("v", ["3.14", "-0.5", "  1.0  "])
    def test_valid_floats(self, v):
        assert _is_float(v)

    @pytest.mark.parametrize("v", ["123", "abc", "1e5", ""])
    def test_invalid_floats(self, v):
        assert not _is_float(v)


# ---------------------------------------------------------------------------
# _none_if_empty
# ---------------------------------------------------------------------------


class TestNoneIfEmpty:
    def test_none_input(self):
        assert _none_if_empty(None) is None

    def test_empty_string(self):
        assert _none_if_empty("") is None

    def test_whitespace_only(self):
        assert _none_if_empty("   ") is None

    def test_non_empty_string(self):
        assert _none_if_empty("hello") == "hello"

    def test_strips_surrounding_whitespace(self):
        # The function returns the stripped value, not the original
        assert _none_if_empty("  val  ") == "val"


# ---------------------------------------------------------------------------
# _coerce_sql_value
# ---------------------------------------------------------------------------


class TestCoerceSqlValue:
    def test_null_returns_none(self):
        assert _coerce_sql_value("NULL") is None
        assert _coerce_sql_value("null") is None

    def test_integer_string(self):
        result = _coerce_sql_value("42")
        assert result == 42
        assert isinstance(result, int)

    def test_negative_integer(self):
        assert _coerce_sql_value("-5") == -5

    def test_float_string(self):
        result = _coerce_sql_value("3.14")
        assert abs(result - 3.14) < 1e-9
        assert isinstance(result, float)

    def test_plain_string_passthrough(self):
        assert _coerce_sql_value("hello") == "hello"

    def test_date_string_passthrough(self):
        assert _coerce_sql_value("2023-01-01") == "2023-01-01"


# ---------------------------------------------------------------------------
# _split_sql_statements
# ---------------------------------------------------------------------------


class TestSplitSqlStatements:
    def test_basic_split(self):
        sql = "SELECT 1; SELECT 2;"
        stmts = _split_sql_statements(sql)
        assert stmts == ["SELECT 1", "SELECT 2"]

    def test_comments_removed(self):
        sql = "-- comment\nSELECT 1;"
        stmts = _split_sql_statements(sql)
        assert stmts == ["SELECT 1"]

    def test_empty_lines_ignored(self):
        sql = "\n\nSELECT 1;\n\nSELECT 2;\n"
        stmts = _split_sql_statements(sql)
        assert len(stmts) == 2

    def test_trailing_semicolon_stripped_from_statement(self):
        sql = "INSERT INTO foo VALUES (1);"
        stmts = _split_sql_statements(sql)
        assert stmts == ["INSERT INTO foo VALUES (1)"]

    def test_no_statements(self):
        assert _split_sql_statements("-- just a comment\n") == []

    def test_multiline_statement(self):
        sql = "CREATE TABLE\nfoo (id INT);"
        stmts = _split_sql_statements(sql)
        assert len(stmts) == 1
        assert "CREATE TABLE" in stmts[0]


# ---------------------------------------------------------------------------
# _extract_sql_tuples
# ---------------------------------------------------------------------------


class TestExtractSqlTuples:
    def test_basic_extract(self):
        sql = "INSERT INTO t VALUES (1, 'a'), (2, 'b')"
        tuples = _extract_sql_tuples(sql)
        assert tuples == ["1, 'a'", "2, 'b'"]

    def test_comments_stripped(self):
        sql = "-- header\nINSERT INTO t VALUES (1, 'x')"
        tuples = _extract_sql_tuples(sql)
        assert len(tuples) == 1

    def test_empty_sql(self):
        assert _extract_sql_tuples("") == []

    def test_no_values_keyword(self):
        # No VALUES → re scans entire string for parens
        sql = "(a, b) (c, d)"
        tuples = _extract_sql_tuples(sql)
        assert len(tuples) == 2

    def test_multiline_values(self):
        sql = "INSERT INTO t VALUES\n(1, 'hello'),\n(2, 'world')"
        tuples = _extract_sql_tuples(sql)
        assert len(tuples) == 2


# ---------------------------------------------------------------------------
# _parse_sql_tuple
# ---------------------------------------------------------------------------


class TestParseSqlTuple:
    def test_simple_integers(self):
        result = _parse_sql_tuple("1, 2, 3")
        assert result == (1, 2, 3)

    def test_quoted_strings(self):
        result = _parse_sql_tuple("1, 'Alice', 'Smith'")
        assert result[1] == "Alice"
        assert result[2] == "Smith"

    def test_null_value(self):
        result = _parse_sql_tuple("1, NULL")
        assert result[1] is None

    def test_float_value(self):
        result = _parse_sql_tuple("1, 3.14")
        assert isinstance(result[1], float)


# ---------------------------------------------------------------------------
# _execute_sql_file
# ---------------------------------------------------------------------------


class TestExecuteSqlFile:
    def test_executes_each_statement(self, tmp_path):
        sql_file = tmp_path / "schema.sql"
        sql_file.write_text("CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);")
        cursor = MagicMock()
        _execute_sql_file(cursor, sql_file)
        assert cursor.execute.call_count == 2

    def test_skips_comments(self, tmp_path):
        sql_file = tmp_path / "schema.sql"
        sql_file.write_text("-- comment\nCREATE TABLE a (id INT);")
        cursor = MagicMock()
        _execute_sql_file(cursor, sql_file)
        cursor.execute.assert_called_once()


# ---------------------------------------------------------------------------
# _load_patients
# ---------------------------------------------------------------------------


class TestLoadPatients:
    def _write_patients_csv(self, tmp_path, rows=5):
        p = tmp_path / "patients.csv"
        with p.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "PatientID", "FirstName", "LastName", "DateOfBirth",
                    "Gender", "Status", "AdmissionDate", "DischargeDate",
                ],
            )
            writer.writeheader()
            for i in range(rows):
                writer.writerow({
                    "PatientID": str(i + 1),
                    "FirstName": f"First{i}",
                    "LastName": f"Last{i}",
                    "DateOfBirth": "1980-01-01",
                    "Gender": "M",
                    "Status": "Active",
                    "AdmissionDate": "2023-01-01",
                    "DischargeDate": "",
                })
        return p

    def test_respects_limit(self, tmp_path):
        p = self._write_patients_csv(tmp_path, rows=5)
        cursor = MagicMock()
        _load_patients(cursor, p, limit=3)
        assert cursor.execute.call_count == 3

    def test_loads_all_rows_when_limit_exceeds_data(self, tmp_path):
        p = self._write_patients_csv(tmp_path, rows=2)
        cursor = MagicMock()
        _load_patients(cursor, p, limit=100)
        assert cursor.execute.call_count == 2

    def test_empty_discharge_date_becomes_none(self, tmp_path):
        p = self._write_patients_csv(tmp_path, rows=1)
        cursor = MagicMock()
        _load_patients(cursor, p, limit=1)
        args = cursor.execute.call_args[0][1]
        assert args[-1] is None  # DischargeDate

    def test_patient_id_is_int(self, tmp_path):
        p = self._write_patients_csv(tmp_path, rows=1)
        cursor = MagicMock()
        _load_patients(cursor, p, limit=1)
        args = cursor.execute.call_args[0][1]
        assert isinstance(args[0], int)


# ---------------------------------------------------------------------------
# _load_lab_results
# ---------------------------------------------------------------------------


class TestLoadLabResults:
    def _write_lab_sql(self, tmp_path):
        p = tmp_path / "lab.sql"
        p.write_text(
            "INSERT INTO LabResults VALUES\n"
            "(1, 101, 'CBC', '2023-01-01', 5.0, 'g/dL', '4-6', 'Normal'),\n"
            "(2, 102, 'BMP', '2023-01-02', 3.5, 'mmol/L', '3-5', 'Normal');\n"
        )
        return p

    def test_respects_limit(self, tmp_path):
        p = self._write_lab_sql(tmp_path)
        cursor = MagicMock()
        _load_lab_results(cursor, p, limit=1)
        assert cursor.execute.call_count == 1

    def test_loads_all_when_limit_exceeds(self, tmp_path):
        p = self._write_lab_sql(tmp_path)
        cursor = MagicMock()
        _load_lab_results(cursor, p, limit=100)
        assert cursor.execute.call_count == 2


# ---------------------------------------------------------------------------
# _generate_vectors_by_dim
# ---------------------------------------------------------------------------


class TestGenerateVectorsByDim:
    def test_returns_correct_dims(self):
        result = _generate_vectors_by_dim(rows=3, dims=[128, 256])
        assert set(result.keys()) == {128, 256}

    def test_correct_number_of_rows(self):
        result = _generate_vectors_by_dim(rows=5, dims=[64])
        assert len(result[64]) == 5

    def test_vector_format_is_bracket_csv(self):
        result = _generate_vectors_by_dim(rows=1, dims=[4])
        vec = result[4][0]
        assert vec.startswith("[")
        assert vec.endswith("]")
        inner = vec[1:-1].split(",")
        assert len(inner) == 4

    def test_deterministic_with_seed(self):
        r1 = _generate_vectors_by_dim(rows=2, dims=[8])
        r2 = _generate_vectors_by_dim(rows=2, dims=[8])
        assert r1[8][0] == r2[8][0]


# ---------------------------------------------------------------------------
# _create_benchmark_vectors
# ---------------------------------------------------------------------------


class TestCreateBenchmarkVectors:
    def test_calls_create_table(self):
        cursor = MagicMock()
        _create_benchmark_vectors(cursor, rows=2)
        drop_call = cursor.execute.call_args_list[0]
        assert "DROP TABLE" in drop_call[0][0].upper()
        create_call = cursor.execute.call_args_list[1]
        assert "CREATE TABLE" in create_call[0][0].upper()

    def test_inserts_correct_number_of_rows(self):
        cursor = MagicMock()
        _create_benchmark_vectors(cursor, rows=3)
        # calls: DROP + CREATE + 3 inserts = 5
        assert cursor.execute.call_count == 5

    def test_zero_rows(self):
        cursor = MagicMock()
        _create_benchmark_vectors(cursor, rows=0)
        # DROP + CREATE only
        assert cursor.execute.call_count == 2


# ---------------------------------------------------------------------------
# ensure_base_fixture
# ---------------------------------------------------------------------------


class TestEnsureBaseFixture:
    def test_returns_existing_dir_when_manifest_present(self, tmp_path):
        fixture_id = "base"
        fixture_dir = tmp_path / fixture_id
        fixture_dir.mkdir()
        manifest = fixture_dir / "manifest.json"
        manifest.write_text("{}")

        result = ensure_base_fixture(
            container=MagicMock(),
            fixture_root=tmp_path,
            fixture_id=fixture_id,
        )
        assert result == fixture_dir

    def test_calls_create_when_manifest_missing(self, tmp_path):
        container = _make_container()
        with patch(
            "iris_pgwire.testing.base_fixture_builder.create_base_fixture"
        ) as mock_create:
            mock_create.return_value = tmp_path / "base"
            ensure_base_fixture(
                container=container,
                fixture_root=tmp_path,
                fixture_id="base",
            )
        mock_create.assert_called_once()

    def test_creates_parent_dirs(self, tmp_path):
        nested_root = tmp_path / "a" / "b"
        container = _make_container()

        with patch(
            "iris_pgwire.testing.base_fixture_builder.create_base_fixture"
        ) as mock_create:
            mock_create.return_value = nested_root / "base"
            ensure_base_fixture(
                container=container,
                fixture_root=nested_root,
                fixture_id="base",
            )
        # Parent dirs should have been created before calling create_base_fixture
        assert nested_root.exists()


# ---------------------------------------------------------------------------
# restore_fixture
# ---------------------------------------------------------------------------


class TestRestoreFixture:
    def test_calls_fixture_loader(self, tmp_path):
        mock_loader_instance = MagicMock()
        mock_loader_cls = MagicMock(return_value=mock_loader_instance)

        with patch.dict(
            sys.modules,
            {"iris_devtester.fixtures.loader": MagicMock(FixtureLoader=mock_loader_cls)},
        ):
            # Re-import needed because restore_fixture does a local import
            from iris_pgwire.testing import base_fixture_builder as _mod
            orig = sys.modules.get("iris_devtester.fixtures.loader")
            fake_mod = MagicMock()
            fake_mod.FixtureLoader = mock_loader_cls
            sys.modules["iris_devtester.fixtures.loader"] = fake_mod

            try:
                container = _make_container()
                _mod.restore_fixture(
                    container=container,
                    fixture_dir=tmp_path,
                    target_namespace="TEST",
                )
            finally:
                if orig is not None:
                    sys.modules["iris_devtester.fixtures.loader"] = orig

        mock_loader_instance.load_fixture.assert_called_once()

    def test_passes_correct_args(self, tmp_path):
        mock_loader_instance = MagicMock()
        mock_loader_cls = MagicMock(return_value=mock_loader_instance)

        from iris_pgwire.testing import base_fixture_builder as _mod
        fake_mod = MagicMock()
        fake_mod.FixtureLoader = mock_loader_cls
        sys.modules["iris_devtester.fixtures.loader"] = fake_mod

        container = _make_container()
        _mod.restore_fixture(
            container=container,
            fixture_dir=tmp_path,
            target_namespace="MYNS",
        )

        _, kwargs = mock_loader_instance.load_fixture.call_args
        assert kwargs["target_namespace"] == "MYNS"
        assert kwargs["validate_checksum"] is False


# ---------------------------------------------------------------------------
# create_base_fixture — error paths
# ---------------------------------------------------------------------------


class TestCreateBaseFixtureErrors:
    """Test FileNotFoundError / FileExistsError branches without touching IRIS."""

    def _patch_repo_root_files(self, schema=True, patients=True, labresults=True):
        """Return a context manager that controls Path.exists() for the three data files."""
        call_count = {"n": 0}
        existence = [schema, patients, labresults]

        def fake_exists(self_path):
            idx = call_count["n"]
            call_count["n"] += 1
            if idx < len(existence):
                return existence[idx]
            return True

        return patch.object(Path, "exists", fake_exists)

    def test_raises_when_schema_missing(self, tmp_path):
        with self._patch_repo_root_files(schema=False):
            with pytest.raises(FileNotFoundError, match="Schema"):
                create_base_fixture(
                    container=_make_container(),
                    fixture_dir=tmp_path / "new_fixture",
                    fixture_id="base",
                    patients_limit=5,
                    labresults_limit=5,
                    vector_rows=5,
                )

    def test_raises_when_patients_missing(self, tmp_path):
        with self._patch_repo_root_files(schema=True, patients=False):
            with pytest.raises(FileNotFoundError, match="Patients"):
                create_base_fixture(
                    container=_make_container(),
                    fixture_dir=tmp_path / "new_fixture",
                    fixture_id="base",
                    patients_limit=5,
                    labresults_limit=5,
                    vector_rows=5,
                )

    def test_raises_when_labresults_missing(self, tmp_path):
        with self._patch_repo_root_files(schema=True, patients=True, labresults=False):
            with pytest.raises(FileNotFoundError, match="Lab results"):
                create_base_fixture(
                    container=_make_container(),
                    fixture_dir=tmp_path / "new_fixture",
                    fixture_id="base",
                    patients_limit=5,
                    labresults_limit=5,
                    vector_rows=5,
                )

    def test_raises_when_fixture_dir_exists(self, tmp_path):
        existing_dir = tmp_path / "already_exists"
        existing_dir.mkdir()

        with self._patch_repo_root_files(schema=True, patients=True, labresults=True):
            with pytest.raises(FileExistsError):
                create_base_fixture(
                    container=_make_container(),
                    fixture_dir=existing_dir,
                    fixture_id="base",
                    patients_limit=5,
                    labresults_limit=5,
                    vector_rows=5,
                )


# ---------------------------------------------------------------------------
# create_base_fixture — happy path (mocked IRIS + real file helpers)
# ---------------------------------------------------------------------------


class TestCreateBaseFixtureHappyPath:
    """Cover lines 105-164: the IRIS-connected execution path."""

    def _make_data_files(self, tmp_path):
        """Create minimal but valid example data files."""
        schema_sql = tmp_path / "init-healthcare-schema.sql"
        schema_sql.write_text("CREATE TABLE Patients (PatientID INT);\n")

        patients_csv = tmp_path / "patients-data.csv"
        with patients_csv.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "PatientID", "FirstName", "LastName", "DateOfBirth",
                    "Gender", "Status", "AdmissionDate", "DischargeDate",
                ],
            )
            writer.writeheader()
            writer.writerow({
                "PatientID": "1", "FirstName": "Alice", "LastName": "Smith",
                "DateOfBirth": "1980-01-01", "Gender": "F", "Status": "Active",
                "AdmissionDate": "2023-01-01", "DischargeDate": "",
            })

        labresults_sql = tmp_path / "labresults-data.sql"
        labresults_sql.write_text(
            "INSERT INTO LabResults VALUES (1, 1, 'CBC', '2023-01-01', 5.0, 'g', '4-6', 'Normal');\n"
        )
        return schema_sql, patients_csv, labresults_sql

    def _patch_data_paths(self, schema_sql, patients_csv, labresults_sql):
        """Patch the three Path objects resolved inside create_base_fixture."""
        import iris_pgwire.testing.base_fixture_builder as mod

        original_init = Path.__init__

        def patched_truediv(self_path, other):
            result = object.__new__(Path)
            # use the real __truediv__ logic
            real = type(self_path)(str(self_path)) / other
            return real

        # We'll patch at a higher level: intercept the resolved repo-relative paths
        # by monkey-patching the three specific paths inside the function.
        return patch.multiple(
            "iris_pgwire.testing.base_fixture_builder",
        )

    def test_happy_path_returns_fixture_dir(self, tmp_path):
        """Full create_base_fixture run with all IRIS calls mocked out."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        schema_sql, patients_csv, labresults_sql = self._make_data_files(data_dir)

        fixture_dir = tmp_path / "fixture" / "base"
        container = _make_container()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_creator_instance = MagicMock()
        mock_creator_cls = MagicMock(return_value=mock_creator_instance)

        # Patch the three resolved file paths so they point to our temp files,
        # and also patch get_connection + FixtureCreator.
        with (
            patch(
                "iris_pgwire.testing.base_fixture_builder.get_connection",
                return_value=mock_conn,
            ),
            patch(
                "iris_pgwire.testing.base_fixture_builder.FixtureCreator",
                mock_creator_cls,
            ),
            patch(
                "iris_pgwire.testing.base_fixture_builder._execute_sql_file"
            ) as mock_exec_sql,
            patch(
                "iris_pgwire.testing.base_fixture_builder._load_patients"
            ) as mock_load_patients,
            patch(
                "iris_pgwire.testing.base_fixture_builder._load_lab_results"
            ) as mock_load_lab,
            patch(
                "iris_pgwire.testing.base_fixture_builder._create_benchmark_vectors"
            ) as mock_vectors,
            # Patch Path.exists to return True for data files, False for fixture_dir
            patch.object(
                Path,
                "exists",
                lambda self_p: (
                    True if str(self_p).endswith(".sql") or str(self_p).endswith(".csv")
                    else False
                ),
            ),
        ):
            result = create_base_fixture(
                container=container,
                fixture_dir=fixture_dir,
                fixture_id="base",
                patients_limit=5,
                labresults_limit=5,
                vector_rows=5,
            )

        assert result == fixture_dir
        mock_exec_sql.assert_called_once()
        mock_load_patients.assert_called_once()
        mock_load_lab.assert_called_once()
        mock_vectors.assert_called_once()
        mock_conn.commit.assert_called_once()
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()
        mock_creator_instance.create_fixture.assert_called_once()
        container.delete_namespace.assert_called_once()

    def test_cursor_close_exception_swallowed(self, tmp_path):
        """cursor.close() raising should not propagate."""
        fixture_dir = tmp_path / "fixture" / "base"
        container = _make_container()

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.close.side_effect = RuntimeError("cursor close failed")
        mock_conn.cursor.return_value = mock_cursor
        mock_creator_instance = MagicMock()
        mock_creator_cls = MagicMock(return_value=mock_creator_instance)

        with (
            patch("iris_pgwire.testing.base_fixture_builder.get_connection", return_value=mock_conn),
            patch("iris_pgwire.testing.base_fixture_builder.FixtureCreator", mock_creator_cls),
            patch("iris_pgwire.testing.base_fixture_builder._execute_sql_file"),
            patch("iris_pgwire.testing.base_fixture_builder._load_patients"),
            patch("iris_pgwire.testing.base_fixture_builder._load_lab_results"),
            patch("iris_pgwire.testing.base_fixture_builder._create_benchmark_vectors"),
            patch.object(Path, "exists", lambda p: (
                True if str(p).endswith(".sql") or str(p).endswith(".csv") else False
            )),
        ):
            # Should not raise even though cursor.close() throws
            result = create_base_fixture(
                container=container,
                fixture_dir=fixture_dir,
                fixture_id="base",
                patients_limit=1,
                labresults_limit=1,
                vector_rows=1,
            )
        assert result == fixture_dir

    def test_delete_namespace_exception_swallowed(self, tmp_path):
        """container.delete_namespace() raising should not propagate."""
        fixture_dir = tmp_path / "fixture" / "base"
        container = _make_container()
        container.delete_namespace.side_effect = RuntimeError("delete failed")

        mock_conn = MagicMock()
        mock_creator_instance = MagicMock()
        mock_creator_cls = MagicMock(return_value=mock_creator_instance)

        with (
            patch("iris_pgwire.testing.base_fixture_builder.get_connection", return_value=mock_conn),
            patch("iris_pgwire.testing.base_fixture_builder.FixtureCreator", mock_creator_cls),
            patch("iris_pgwire.testing.base_fixture_builder._execute_sql_file"),
            patch("iris_pgwire.testing.base_fixture_builder._load_patients"),
            patch("iris_pgwire.testing.base_fixture_builder._load_lab_results"),
            patch("iris_pgwire.testing.base_fixture_builder._create_benchmark_vectors"),
            patch.object(Path, "exists", lambda p: (
                True if str(p).endswith(".sql") or str(p).endswith(".csv") else False
            )),
        ):
            result = create_base_fixture(
                container=container,
                fixture_dir=fixture_dir,
                fixture_id="base",
                patients_limit=1,
                labresults_limit=1,
                vector_rows=1,
            )
        assert result == fixture_dir
