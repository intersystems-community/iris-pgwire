"""
Test Container Management Agentic Skill Integration.
Validates FR-003, FR-004, FR-005.
"""

import socket

import pytest
from iris_devtester import IRISContainer


def test_container_lifecycle():
    """
    Test that IRISContainer can start, verify health, and stop.
    This effectively tests the /container skill logic.
    """
    with IRISContainer.community() as iris:
        # Verify container is running
        assert iris.get_wrapped_container().status == "running"

        # Verify port mapping
        host = iris.get_container_host_ip()
        port = iris.get_exposed_port(1972)
        assert host in ["localhost", "127.0.0.1", "0.0.0.0"] or host.startswith("172.")
        assert int(port) > 0

        # Verify health check (port accessible)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            # Use 'localhost' for host if it's 0.0.0.0
            connect_host = "localhost" if host == "0.0.0.0" else host
            result = sock.connect_ex((connect_host, int(port)))
            assert result == 0, f"IRIS port {port} should be accessible"


def test_container_fixture(iris_container, iris_config):
    """
    Test that the pytest fixture uses iris-devtester correctly.
    """
    assert iris_container is not None

    # Verify we can connect to the port from config
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        result = sock.connect_ex((iris_config["host"], iris_config["port"]))
        assert result == 0
