"""Budget for the small per-statement protocol messages (constitution V, spec 052 SC-008).

NoData goes out for every INSERT, UPDATE and DELETE on the extended protocol. Until 2.1.0 it
formatted the whole call stack for a debug log line on each call: 0.9 ms per statement in 2.0.1,
2.1 ms in 2.1.0 where the stack is deeper (measured with cProfile on the SC-008 benchmark).
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from iris_pgwire.protocol import PGWireProtocol

_CALLS = 2000
_BUDGET_US_PER_CALL = 50


def _protocol() -> PGWireProtocol:
    protocol = object.__new__(PGWireProtocol)
    protocol.connection_id = "budget"
    protocol.writer = MagicMock(drain=AsyncMock())
    return protocol


async def _deep(depth: int, fn):
    """Call `fn` from `depth` frames down, as the message loop does."""
    if depth == 0:
        return await fn()
    return await _deep(depth - 1, fn)


def test_no_data_is_the_five_byte_message():
    protocol = _protocol()
    asyncio.run(protocol.send_no_data())
    protocol.writer.write.assert_called_once_with(b"n\x00\x00\x00\x04")


def test_no_data_stays_within_its_budget_deep_in_the_stack():
    protocol = _protocol()

    async def many():
        for _ in range(_CALLS):
            await _deep(40, protocol.send_no_data)

    started = time.perf_counter()
    asyncio.run(many())
    per_call_us = (time.perf_counter() - started) / _CALLS * 1e6
    assert per_call_us < _BUDGET_US_PER_CALL, f"{per_call_us:.0f} us per NoData"


def test_an_extended_protocol_result_does_not_wait():
    """send_query_result slept 1 ms after every extended-protocol result "for Sync to arrive"
    (the message loop reads a buffered stream, so nothing can be missed): 1.3 ms per UPDATE in
    the SC-008 benchmark, more than IRIS took to run it."""
    protocol = _protocol()
    protocol.transaction_status = b"I"
    result = {"success": True, "rows": [], "columns": [], "row_count": 1, "command_tag": "UPDATE"}

    async def many():
        for _ in range(200):
            await protocol.send_query_result(result, send_ready=False)

    started = time.perf_counter()
    asyncio.run(many())
    per_call_us = (time.perf_counter() - started) / 200 * 1e6
    assert per_call_us < 300, f"{per_call_us:.0f} us per result"
    sent = b"".join(c.args[0] for c in protocol.writer.write.call_args_list)
    assert sent.endswith(b"C\x00\x00\x00\x0dUPDATE 1\x00")
