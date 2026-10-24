"""Every spelling PostgreSQL accepts for BEGIN, COMMIT and ROLLBACK reaches the transaction code.

The ADBC PostgreSQL driver opens a transaction with `BEGIN TRANSACTION`. This server recognised
only the bare `BEGIN` and `START TRANSACTION`, so the driver's spelling was sent to IRIS as SQL:
the embedded backend happened to accept it (and so skipped the server's own transaction state), and
the DBAPI backend refused it with "SQL statement expected, BEGIN found", which made every statement
the driver ran fail with "Failed to begin transaction".

PostgreSQL: BEGIN [ WORK | TRANSACTION ], START TRANSACTION, COMMIT/END [ WORK | TRANSACTION ],
ROLLBACK/ABORT [ WORK | TRANSACTION ]. ABORT reports the ROLLBACK tag and END reports COMMIT.
"""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

from iris_pgwire.protocol import PGWireProtocol


class Wire:
    def __init__(self):
        self.out = bytearray()

    def write(self, data):
        self.out += data

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass

    def get_extra_info(self, name, default=None):
        return default


def protocol():
    executor = MagicMock()
    for name in ("begin_transaction", "commit_transaction", "rollback_transaction"):
        setattr(executor, name, AsyncMock())
    wire = Wire()
    return PGWireProtocol(asyncio.StreamReader(), wire, executor, "unit-txn"), wire, executor


def tag_sent(wire: Wire) -> str:
    data = bytes(wire.out)
    pos = 0
    while pos < len(data):
        kind = data[pos : pos + 1]
        (length,) = struct.unpack("!I", data[pos + 1 : pos + 5])
        if kind == b"C":
            return data[pos + 5 : pos + 1 + length].rstrip(b"\x00").decode()
        pos += 1 + length
    raise AssertionError("no CommandComplete was sent")


BEGINS = ["BEGIN", "BEGIN WORK", "BEGIN TRANSACTION", "START TRANSACTION"]
COMMITS = ["COMMIT", "COMMIT WORK", "COMMIT TRANSACTION", "END", "END WORK", "END TRANSACTION"]
ROLLBACKS = ["ROLLBACK", "ROLLBACK WORK", "ROLLBACK TRANSACTION", "ABORT", "ABORT WORK",
             "ABORT TRANSACTION"]  # fmt: skip


@pytest.mark.parametrize("sql", BEGINS)
async def test_every_spelling_of_begin_opens_a_transaction(sql):
    p, wire, executor = protocol()
    assert await p._maybe_handle_transaction_command(sql, send_ready=False) is True
    executor.begin_transaction.assert_awaited_once()
    assert tag_sent(wire) == "BEGIN"


@pytest.mark.parametrize("sql", COMMITS)
async def test_every_spelling_of_commit_commits(sql):
    p, wire, executor = protocol()
    assert await p._maybe_handle_transaction_command(sql, send_ready=False) is True
    executor.commit_transaction.assert_awaited_once()
    assert tag_sent(wire) == "COMMIT"


@pytest.mark.parametrize("sql", ROLLBACKS)
async def test_every_spelling_of_rollback_rolls_back(sql):
    p, wire, executor = protocol()
    assert await p._maybe_handle_transaction_command(sql, send_ready=False) is True
    executor.rollback_transaction.assert_awaited_once()
    assert tag_sent(wire) == "ROLLBACK"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "BEGINNING",
        "COMMIT PREPARED 'x'",
        "BEGIN ISOLATION LEVEL READ COMMITTED",  # handled by the isolation code, not here
        "ROLLBACK TO SAVEPOINT s",
        "END IF",
    ],
)
async def test_other_statements_are_not_swallowed(sql):
    p, wire, executor = protocol()
    assert await p._maybe_handle_transaction_command(sql, send_ready=False) is False
    executor.begin_transaction.assert_not_awaited()
    assert bytes(wire.out) == b""
