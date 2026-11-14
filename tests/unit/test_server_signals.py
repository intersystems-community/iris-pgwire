"""The server stops cleanly on SIGTERM, as a supervisor expects.

Measured 2026-10-17: SIGTERM did not stop a running pgwire server; only SIGKILL did. `main()`
caught KeyboardInterrupt and nothing else, so `docker stop` waited out its grace period, and the IPM
package's `IrisPGWire.Service.Stop()` (which sends SIGTERM, then waits) reported failure. IPM's
Deactivate phase calls Stop() with CheckStatus, so uninstalling the package failed too.

These tests send real signals to the test process. The server is a stand-in, so no IRIS is needed:
what is under test is the signal handling around it.
"""

from __future__ import annotations

import asyncio
import os
import signal

import pytest

from iris_pgwire.server import serve_until_signalled


class StandInServer:
    """Serves until stopped, like PGWireServer.start(); records the stop."""

    def __init__(self, fail_on_start: Exception | None = None):
        self.stopped = False
        self._closed = asyncio.Event()
        self.fail_on_start = fail_on_start

    async def start(self):
        if self.fail_on_start:
            raise self.fail_on_start
        await self._closed.wait()

    async def stop(self):
        self.stopped = True
        self._closed.set()


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT], ids=["SIGTERM", "SIGINT"])
async def test_a_stop_signal_stops_the_server_and_returns(signum):
    server = StandInServer()
    asyncio.get_running_loop().call_later(0.1, os.kill, os.getpid(), signum)
    await asyncio.wait_for(serve_until_signalled(server), timeout=5)
    assert server.stopped


async def test_the_handlers_are_removed_afterwards():
    """Leaving them installed would swallow the next SIGTERM aimed at whatever runs next."""
    before = signal.getsignal(signal.SIGTERM)
    server = StandInServer()
    asyncio.get_running_loop().call_later(0.1, os.kill, os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(serve_until_signalled(server), timeout=5)
    assert signal.getsignal(signal.SIGTERM) == before


async def test_a_startup_failure_is_raised_not_swallowed():
    server = StandInServer(fail_on_start=RuntimeError("cannot reach IRIS"))
    with pytest.raises(RuntimeError, match="cannot reach IRIS"):
        await asyncio.wait_for(serve_until_signalled(server), timeout=5)


async def test_a_server_that_returns_on_its_own_is_not_waited_on():
    class ReturnsAtOnce(StandInServer):
        async def start(self):
            return None

    server = ReturnsAtOnce()
    await asyncio.wait_for(serve_until_signalled(server), timeout=5)
