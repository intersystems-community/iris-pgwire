"""
Infrastructure Tests for IRIS PostgreSQL Wire Protocol

These tests validate that the basic infrastructure components work correctly:
- IRIS container setup and connectivity
- IRIS SQL execution without wire protocol
- Database connection reliability

This test suite must pass before proceeding to wire protocol tests.
"""

import pytest
import asyncio
import docker
from iris_pgwire.iris_executor import IRISExecutor


class TestIRISInfrastructure:
    """Test IRIS container and connectivity infrastructure"""

    @pytest.fixture(scope="class")
    def iris_config(self):
        """Standard IRIS configuration for testing"""
        return {
            'host': 'localhost',
            'port': 1972,
            'username': '_SYSTEM',
            'password': 'SYS',
            'namespace': 'USER'
        }

    @pytest.fixture(scope="class")
    def docker_client(self):
        """Docker client for container management"""
        return docker.from_env()

    def test_iris_container_exists(self, docker_client):
        """Test that IRIS container exists and is running"""
        containers = docker_client.containers.list(filters={"name": "iris-pgwire-db"})
        assert len(containers) == 1, "IRIS container iris-pgwire-db should be running"

        container = containers[0]
        assert container.status == "running", f"IRIS container status: {container.status}"

    def test_iris_container_health(self, docker_client):
        """Test that IRIS container is healthy"""
        container = docker_client.containers.get("iris-pgwire-db")
        health = container.attrs['State']['Health']['Status']
        assert health == "healthy", f"IRIS container health: {health}"

    def test_iris_ports_accessible(self):
        """Test that IRIS ports are accessible"""
        import socket

        # Test SuperServer port (1972)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            result = sock.connect_ex(('localhost', 1972))
            assert result == 0, "IRIS SuperServer port 1972 should be accessible"

        # Test Management Portal port (52773)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            result = sock.connect_ex(('localhost', 52773))
            assert result == 0, "IRIS Management Portal port 52773 should be accessible"

    @pytest.mark.asyncio
    async def test_iris_executor_creation(self, iris_config):
        """Test IRIS executor can be created"""
        executor = IRISExecutor(iris_config)
        assert executor is not None
        assert executor.iris_config == iris_config
        assert not executor.embedded_mode  # Should use external connection

    @pytest.mark.asyncio
    async def test_iris_basic_sql_execution(self, iris_config):
        """Test basic SQL execution through IRIS executor"""
        executor = IRISExecutor(iris_config)

        # Test simple SELECT
        result = await executor.execute_query('SELECT 42 as test_value')
        assert result['success'], f"SQL execution failed: {result['error']}"
        assert len(result['rows']) == 1
        assert result['rows'][0] == [42]

        # Test command tag
        assert result['command_tag'] == 'SELECT'

    @pytest.mark.asyncio
    async def test_iris_string_query(self, iris_config):
        """Test string literal queries"""
        executor = IRISExecutor(iris_config)

        result = await executor.execute_query("SELECT 'hello world' as greeting")
        assert result['success'], f"String query failed: {result['error']}"
        assert len(result['rows']) == 1
        assert result['rows'][0] == ['hello world']

    @pytest.mark.asyncio
    async def test_iris_multiple_columns(self, iris_config):
        """Test queries with multiple columns"""
        executor = IRISExecutor(iris_config)

        result = await executor.execute_query("SELECT 1 as num, 'text' as str, 42.5 as float_val")
        assert result['success'], f"Multi-column query failed: {result['error']}"
        assert len(result['rows']) == 1
        assert len(result['rows'][0]) == 3

        # Check column metadata
        assert len(result['columns']) == 3
        assert result['columns'][0]['name'] == 'num'
        assert result['columns'][1]['name'] == 'str'
        assert result['columns'][2]['name'] == 'float_val'

    @pytest.mark.asyncio
    async def test_iris_performance_tracking(self, iris_config):
        """Test that performance tracking works"""
        executor = IRISExecutor(iris_config)

        result = await executor.execute_query('SELECT 1')
        assert result['success']

        # Check execution metadata
        metadata = result['execution_metadata']
        assert 'execution_time_ms' in metadata
        assert metadata['execution_time_ms'] > 0
        assert metadata['embedded_mode'] is False
        assert 'session_id' in metadata
        assert 'sql_length' in metadata

    @pytest.mark.asyncio
    async def test_iris_error_handling(self, iris_config):
        """Test error handling for invalid SQL"""
        executor = IRISExecutor(iris_config)

        # Test invalid SQL
        result = await executor.execute_query('INVALID SQL SYNTAX')
        assert not result['success']
        assert 'error' in result
        assert len(result['error']) > 0
        assert result['command_tag'] == 'ERROR'

    @pytest.mark.asyncio
    async def test_iris_concurrent_execution(self, iris_config):
        """Test concurrent SQL execution"""
        executor = IRISExecutor(iris_config)

        # Execute multiple queries concurrently
        tasks = [
            executor.execute_query(f'SELECT {i} as value')
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # All should succeed
        for i, result in enumerate(results):
            assert result['success'], f"Query {i} failed: {result['error']}"
            assert result['rows'][0] == [i]

    @pytest.mark.asyncio
    async def test_iris_namespace_access(self, iris_config):
        """Test that we can access the USER namespace"""
        executor = IRISExecutor(iris_config)

        # Test a simple query that validates namespace access
        result = await executor.execute_query("SELECT 'USER namespace test' as namespace_test")
        assert result['success'], f"Namespace query failed: {result['error']}"
        assert len(result['rows']) == 1
        assert result['rows'][0][0] == 'USER namespace test'


class TestIRISPasswordConfiguration:
    """Test that IRIS password configuration is correct"""

    def test_password_expiry_disabled(self):
        """Test that password expiry was disabled during container startup"""
        docker_client = docker.from_env()
        container = docker_client.containers.get("iris-pgwire-db")

        # Check container logs for the password unexpiry command
        logs = container.logs().decode('utf-8')
        assert "##class(Security.Users).UnExpireUserPasswords" in logs, \
            "Password expiry disable command should appear in container logs"
        assert "...executed command iris session iris -U%SYS" in logs, \
            "Password command should have executed successfully"

    @pytest.mark.asyncio
    async def test_no_password_change_required(self):
        """Test that IRIS connection works without password change"""
        iris_config = {
            'host': 'localhost',
            'port': 1972,
            'username': '_SYSTEM',
            'password': 'SYS',
            'namespace': 'USER'
        }

        executor = IRISExecutor(iris_config)
        result = await executor.execute_query('SELECT 1')

        # Should not get password change error
        if not result['success']:
            assert "Password change required" not in result['error'], \
                "Password expiry should be disabled"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])