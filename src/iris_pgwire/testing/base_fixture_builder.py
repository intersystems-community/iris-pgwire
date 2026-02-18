"""
Build and restore base DAT fixtures for tests.

Creates schema + base rows from examples and benchmarks to seed test namespaces.
"""

from __future__ import annotations

import csv
import json
import random
import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from iris_devtester.config import IRISConfig
from iris_devtester.connections import get_connection
from iris_devtester.fixtures.creator import FixtureCreator


def ensure_base_fixture(
    *,
    container,
    fixture_root: Path,
    fixture_id: str = "base",
    patients_limit: int = 10,
    labresults_limit: int = 10,
    vector_rows: int = 10,
) -> Path:
    """
    Ensure the base DAT fixture exists, creating it if needed.
    """
    fixture_dir = fixture_root / fixture_id
    manifest = fixture_dir / "manifest.json"

    if manifest.exists():
        return fixture_dir

    fixture_dir.parent.mkdir(parents=True, exist_ok=True)

    return create_base_fixture(
        container=container,
        fixture_dir=fixture_dir,
        fixture_id=fixture_id,
        patients_limit=patients_limit,
        labresults_limit=labresults_limit,
        vector_rows=vector_rows,
    )


def restore_fixture(
    *,
    container,
    fixture_dir: Path,
    target_namespace: str,
    validate: bool = True,
) -> None:
    """
    Restore a fixture into a target namespace using iris-devtester's FixtureLoader.

    The fixture must be in the current iris-devtester format (globals.gof + manifest.json).
    Legacy fixtures with only IRIS.DAT are not supported.
    """
    from iris_devtester.fixtures.loader import FixtureLoader

    loader = FixtureLoader(container=container)
    loader.load_fixture(
        fixture_path=str(fixture_dir),
        target_namespace=target_namespace,
        validate_checksum=False,
    )


def create_base_fixture(
    *,
    container,
    fixture_dir: Path,
    fixture_id: str,
    patients_limit: int,
    labresults_limit: int,
    vector_rows: int,
) -> Path:
    """Create the base fixture from example and benchmark datasets."""
    repo_root = Path(__file__).resolve().parents[3]
    schema_sql = (
        repo_root / "examples" / "superset-iris-healthcare" / "data" / "init-healthcare-schema.sql"
    )
    patients_csv = (
        repo_root / "examples" / "superset-iris-healthcare" / "data" / "patients-data.csv"
    )
    labresults_sql = (
        repo_root / "examples" / "superset-iris-healthcare" / "data" / "labresults-data.sql"
    )

    if not schema_sql.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_sql}")
    if not patients_csv.exists():
        raise FileNotFoundError(f"Patients CSV not found: {patients_csv}")
    if not labresults_sql.exists():
        raise FileNotFoundError(f"Lab results SQL not found: {labresults_sql}")

    if fixture_dir.exists():
        raise FileExistsError(f"Fixture directory already exists: {fixture_dir}")

    namespace = container.get_test_namespace(prefix="FIXTURE")
    config = container.get_config()
    conn = get_connection(
        IRISConfig(
            host=config.host,
            port=config.port,
            namespace=namespace,
            username=config.username,
            password=config.password,
            container_name=container.get_container_name(),
        )
    )

    try:
        cursor = conn.cursor()
        _execute_sql_file(cursor, schema_sql)
        _load_patients(cursor, patients_csv, limit=patients_limit)
        _load_lab_results(cursor, labresults_sql, limit=labresults_limit)
        _create_benchmark_vectors(cursor, rows=vector_rows)
        conn.commit()
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        conn.close()

    try:
        creator = FixtureCreator(
            connection_config=IRISConfig(
                host=config.host,
                port=config.port,
                namespace=namespace,
                username=config.username,
                password=config.password,
                container_name=container.get_container_name(),
            ),
            container=container,
        )

        creator.create_fixture(
            fixture_id=fixture_id,
            namespace=namespace,
            output_dir=str(fixture_dir),
            description=(
                "Base schema + rows from examples/superset-iris-healthcare and benchmarks"
            ),
            version="1.0.0",
            features={
                "patients_rows": patients_limit,
                "labresults_rows": labresults_limit,
                "benchmark_vector_rows": vector_rows,
            },
        )
    finally:
        try:
            container.delete_namespace(namespace)
        except Exception:
            pass
    return fixture_dir


def _execute_sql_file(cursor, sql_path: Path) -> None:
    statements = _split_sql_statements(sql_path.read_text())
    for stmt in statements:
        cursor.execute(stmt)


def _split_sql_statements(sql_text: str) -> list[str]:
    cleaned_lines: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


def _load_patients(cursor, csv_path: Path, limit: int) -> None:
    insert_sql = (
        "INSERT INTO Patients "
        "(PatientID, FirstName, LastName, DateOfBirth, Gender, Status, AdmissionDate, DischargeDate) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )

    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            if idx >= limit:
                break
            values = (
                int(row["PatientID"]),
                row["FirstName"],
                row["LastName"],
                row["DateOfBirth"],
                row["Gender"],
                row["Status"],
                row["AdmissionDate"],
                _none_if_empty(row.get("DischargeDate")),
            )
            cursor.execute(insert_sql, values)


def _load_lab_results(cursor, sql_path: Path, limit: int) -> None:
    tuples = _extract_sql_tuples(sql_path.read_text())
    insert_sql = (
        "INSERT INTO LabResults "
        "(ResultID, PatientID, TestName, TestDate, Result, Unit, ReferenceRange, Status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )

    for idx, raw_tuple in enumerate(tuples):
        if idx >= limit:
            break
        values = _parse_sql_tuple(raw_tuple)
        cursor.execute(insert_sql, values)


def _extract_sql_tuples(sql_text: str) -> list[str]:
    cleaned_lines: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    if "VALUES" in cleaned:
        cleaned = cleaned.split("VALUES", 1)[1]
    matches = re.findall(r"\((.*?)\)", cleaned, flags=re.DOTALL)
    return [match.strip() for match in matches if match.strip()]


def _parse_sql_tuple(raw_tuple: str) -> Sequence[object]:
    reader = csv.reader([raw_tuple], delimiter=",", quotechar="'", skipinitialspace=True)
    row = next(reader)
    return tuple(_coerce_sql_value(value) for value in row)


def _coerce_sql_value(value: str) -> object:
    upper = value.upper()
    if upper == "NULL":
        return None
    if _is_int(value):
        return int(value)
    if _is_float(value):
        return float(value)
    return value


def _is_int(value: str) -> bool:
    return re.fullmatch(r"-?\d+", value.strip()) is not None


def _is_float(value: str) -> bool:
    return re.fullmatch(r"-?\d+\.\d+", value.strip()) is not None


def _none_if_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _create_benchmark_vectors(cursor, rows: int) -> None:
    cursor.execute("DROP TABLE IF EXISTS benchmark_vectors")
    cursor.execute(
        """
        CREATE TABLE benchmark_vectors (
            id INT PRIMARY KEY,
            embedding VECTOR(DOUBLE, 1024),
            embedding_128 VECTOR(DOUBLE, 128),
            embedding_256 VECTOR(DOUBLE, 256),
            embedding_512 VECTOR(DOUBLE, 512),
            embedding_1024 VECTOR(DOUBLE, 1024)
        )
        """
    )

    vectors_by_dim = _generate_vectors_by_dim(rows, [128, 256, 512, 1024])
    insert_sql = (
        "INSERT INTO benchmark_vectors "
        "(id, embedding, embedding_128, embedding_256, embedding_512, embedding_1024) "
        "VALUES (?, TO_VECTOR(?), TO_VECTOR(?), TO_VECTOR(?), TO_VECTOR(?), TO_VECTOR(?))"
    )

    for row_id in range(rows):
        vec_128 = vectors_by_dim[128][row_id]
        vec_256 = vectors_by_dim[256][row_id]
        vec_512 = vectors_by_dim[512][row_id]
        vec_1024 = vectors_by_dim[1024][row_id]
        cursor.execute(
            insert_sql,
            (
                row_id,
                vec_1024,
                vec_128,
                vec_256,
                vec_512,
                vec_1024,
            ),
        )


def _generate_vectors_by_dim(rows: int, dims: Iterable[int]) -> dict[int, list[str]]:
    vectors: dict[int, list[str]] = {}
    for dim in dims:
        random.seed(42)
        vectors[dim] = []
        for _ in range(rows):
            vec = [random.random() for _ in range(dim)]
            vec_text = "[" + ",".join(str(v) for v in vec) + "]"
            vectors[dim].append(vec_text)
    return vectors
