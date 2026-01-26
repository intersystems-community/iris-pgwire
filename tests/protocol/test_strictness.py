import sys
import os
import asyncio
import struct
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from iris_pgwire.protocol import PGWireProtocol
from iris_pgwire.iris_executor import IRISExecutor
from tests.protocol.validator import StrictProtocolValidator, ProtocolError


class MockReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    async def readexactly(self, n: int) -> bytes:
        if self.offset + n > len(self.data):
            raise asyncio.IncompleteReadError(self.data[self.offset :], n)
        res = self.data[self.offset : self.offset + n]
        self.offset += n
        return res


class BytesCapturingWriter:
    def __init__(self):
        self.buffer = b""
        self.transport = MagicMock()

    def write(self, data: bytes):
        self.buffer += data

    async def drain(self):
        pass


@pytest.fixture
def iris_config():
    return {
        "host": "localhost",
        "port": 1972,
        "namespace": "USER",
        "username": "SuperUser",
        "password": "SYS",
    }


@pytest.mark.asyncio
async def test_reproduce_join_field_count_mismatch(iris_config):
    mock_iris = MagicMock()
    executor = IRISExecutor(mock_iris, iris_config)

    def side_effect(captured_sql, *args):
        sql_upper = captured_sql.upper()
        if "INFORMATION_SCHEMA.COLUMNS" in sql_upper:
            return [
                ("user", "id", "INTEGER"),
                ("user", "email", "VARCHAR"),
                ("user", "name", "VARCHAR"),
                ("permissions", "permission_type", "VARCHAR"),
            ]
        return []

    mock_iris.sql.exec.side_effect = side_effect

    reader = MockReader(b"")
    writer = BytesCapturingWriter()
    protocol = PGWireProtocol(reader, writer, executor, connection_id="test_conn")

    sql = 'SELECT u.id, u.email, u.name, p.permission_type FROM permissions p INNER JOIN "user" u ON p.user_id = u.id'

    validator = StrictProtocolValidator()

    with patch("sys.modules", {"iris": mock_iris}):
        protocol.prepared_statements["stmt1"] = {"query": sql, "param_types": []}

        await protocol.handle_describe_message(b"Sstmt1")
        await protocol.handle_bind_message(b"\x00portal1\x00stmt1\x00\x00\x00\x00\x00\x00")

        mock_execute_result = MagicMock()
        mock_execute_result.__iter__.return_value = iter(
            [(1, "test@example.com", "Test User", "ADMIN")]
        )
        mock_iris.sql.exec.side_effect = None
        mock_iris.sql.exec.return_value = mock_execute_result

        await protocol.handle_execute_message(b"portal1\x00\x00\x00\x00")

        validator.validate(writer.buffer)


@pytest.mark.asyncio
async def test_select_star_join_discovery_issue(iris_config):
    mock_iris = MagicMock()
    executor = IRISExecutor(mock_iris, iris_config)

    def side_effect(sql, *args):
        if "INFORMATION_SCHEMA.COLUMNS" in sql.upper():
            return [
                ("table_a", "id_a", "INTEGER"),
                ("table_b", "id_b", "INTEGER"),
                ("table_a", "val_a", "VARCHAR"),
            ]
        return []

    mock_iris.sql.exec.side_effect = side_effect

    reader = MockReader(b"")
    writer = BytesCapturingWriter()
    protocol = PGWireProtocol(reader, writer, executor, connection_id="test_conn")

    validator = StrictProtocolValidator()

    sql = "SELECT * FROM table_a JOIN table_b ON table_a.id_a = table_b.id_b"

    await protocol.handle_query_message(sql.encode("utf-8"))

    validator.validate(writer.buffer)


@pytest.mark.asyncio
async def test_duplicate_column_names_repro(iris_config):
    mock_iris = MagicMock()
    executor = IRISExecutor(mock_iris, iris_config)

    mock_results = MagicMock()
    mock_results.__iter__.return_value = iter([("Alice", "Alice")])
    mock_iris.sql.exec.return_value = mock_results

    reader = MockReader(b"")
    writer = BytesCapturingWriter()
    protocol = PGWireProtocol(reader, writer, executor, connection_id="test_conn")

    validator = StrictProtocolValidator()

    sql = "SELECT name, name FROM dups"
    await protocol.handle_query_message(sql.encode("utf-8"))

    validator.validate(writer.buffer)


@pytest.mark.asyncio
async def test_empty_join_result_repro(iris_config):
    mock_iris = MagicMock()
    executor = IRISExecutor(mock_iris, iris_config)

    mock_results = MagicMock()
    mock_results.__iter__.return_value = iter([])
    mock_iris.sql.exec.return_value = mock_results

    reader = MockReader(b"")
    writer = BytesCapturingWriter()
    protocol = PGWireProtocol(reader, writer, executor, connection_id="test_conn")

    validator = StrictProtocolValidator()

    sql = "SELECT * FROM table_a JOIN table_b ON 1=0"
    await protocol.handle_query_message(sql.encode("utf-8"))

    validator.validate(writer.buffer)
