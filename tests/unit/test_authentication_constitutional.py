"""
Constitutional Compliance Tests for Authentication
Tests authentication flows against constitutional requirements (<5ms SLA)
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock

from iris_pgwire.auth import (
    PostgreSQLAuthenticator,
    AuthenticationMethod,
    AuthenticationResult,
    IRISAuthenticationProvider,
    SCRAMAuthenticator
)
from iris_pgwire.constitutional import get_governor
from iris_pgwire.performance_monitor import get_monitor


class TestAuthenticationConstitutionalCompliance:
    """Test authentication constitutional compliance"""

    @pytest.fixture
    def mock_iris_config(self):
        return {
            'host': 'localhost',
            'port': '1972',
            'namespace': 'USER',
            'system_user': '_SYSTEM',
            'system_password': 'SYS'
        }

    @pytest.fixture
    def authenticator(self, mock_iris_config):
        return PostgreSQLAuthenticator(
            auth_method=AuthenticationMethod.SCRAM_SHA_256,
            iris_config=mock_iris_config
        )

    @pytest.fixture
    def trust_authenticator(self, mock_iris_config):
        return PostgreSQLAuthenticator(
            auth_method=AuthenticationMethod.TRUST,
            iris_config=mock_iris_config
        )

    @pytest.mark.asyncio
    async def test_authentication_sla_compliance_trust(self, trust_authenticator):
        """Test trust authentication meets <5ms SLA"""
        start_time = time.perf_counter()

        result = await trust_authenticator.authenticate(
            connection_id="test-conn-1",
            username="testuser"
        )

        end_time = time.perf_counter()
        actual_time = (end_time - start_time) * 1000

        assert result.success
        assert result.sla_compliant
        assert result.auth_time_ms < 5.0
        assert actual_time < 5.0  # Verify actual measurement

    @pytest.mark.asyncio
    async def test_authentication_constitutional_monitoring(self, trust_authenticator):
        """Test constitutional monitoring integration"""
        monitor = get_monitor()
        governor = get_governor()

        # Clear any existing stats
        monitor.reset_stats()

        result = await trust_authenticator.authenticate(
            connection_id="test-conn-2",
            username="testuser"
        )

        assert result.success
        assert result.sla_compliant

        # Verify monitoring recorded the operation
        stats = monitor.get_stats()
        assert stats.total_translations > 0  # Monitor should record auth operations

    @pytest.mark.asyncio
    async def test_authentication_sla_violation_logging(self, authenticator):
        """Test SLA violation triggers constitutional compliance check"""
        with patch('iris_pgwire.auth.asyncio.to_thread') as mock_thread:
            # Mock slow IRIS authentication (>5ms)
            async def slow_iris_auth():
                await asyncio.sleep(0.006)  # 6ms delay
                return True, "session_123"

            mock_thread.return_value = slow_iris_auth()

            with patch('iris_pgwire.auth.get_governor') as mock_governor:
                mock_gov = Mock()
                mock_governor.return_value = mock_gov

                result = await authenticator.authenticate(
                    connection_id="test-conn-3",
                    username="testuser",
                    auth_data=b"test-auth-data"
                )

                # Verify SLA violation was detected
                assert not result.sla_compliant
                assert result.auth_time_ms > 5.0

                # Verify constitutional compliance check was triggered
                mock_gov.check_compliance.assert_called_once()

    @pytest.mark.asyncio
    async def test_iris_authentication_constitutional_compliance(self, mock_iris_config):
        """Test IRIS authentication provider constitutional compliance"""
        provider = IRISAuthenticationProvider(mock_iris_config)

        with patch('iris_pgwire.auth.asyncio.to_thread') as mock_thread:
            # Mock fast IRIS authentication
            async def fast_iris_auth():
                return True, "session_456"

            mock_thread.return_value = fast_iris_auth()

            start_time = time.perf_counter()
            success, session_id = await provider.validate_iris_user("testuser", "testpass")
            end_time = time.perf_counter()

            actual_time = (end_time - start_time) * 1000

            assert success
            assert session_id == "session_456"
            assert actual_time < 5.0  # Should meet SLA

    @pytest.mark.asyncio
    async def test_scram_authenticator_constitutional_compliance(self, mock_iris_config):
        """Test SCRAM authenticator constitutional compliance"""
        provider = IRISAuthenticationProvider(mock_iris_config)
        scram_auth = SCRAMAuthenticator(provider)

        # Test that SCRAM operations are fast enough
        start_time = time.perf_counter()

        # Test nonce generation (should be very fast)
        nonce = scram_auth.generate_server_nonce()
        assert len(nonce) > 0

        # Test client message parsing (should be very fast)
        client_message = "n,,n=testuser,r=clientnonce123"
        username, client_nonce, gs2_header = scram_auth.parse_client_first_message(client_message)

        end_time = time.perf_counter()
        operation_time = (end_time - start_time) * 1000

        assert username == "testuser"
        assert client_nonce == "clientnonce123"
        assert operation_time < 1.0  # SCRAM operations should be sub-millisecond

    @pytest.mark.asyncio
    async def test_concurrent_authentication_constitutional_compliance(self, trust_authenticator):
        """Test constitutional compliance under concurrent authentication load"""
        monitor = get_monitor()
        monitor.reset_stats()

        # Simulate concurrent authentication requests
        tasks = []
        for i in range(10):
            task = trust_authenticator.authenticate(
                connection_id=f"test-conn-{i}",
                username=f"user{i}"
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks)

        # All should succeed and meet SLA
        for result in results:
            assert result.success
            assert result.sla_compliant
            assert result.auth_time_ms < 5.0

        # Verify all operations were monitored
        stats = monitor.get_stats()
        assert stats.total_translations >= 10

    @pytest.mark.asyncio
    async def test_authentication_error_constitutional_compliance(self, authenticator):
        """Test constitutional compliance even during authentication errors"""
        with patch('iris_pgwire.auth.asyncio.to_thread') as mock_thread:
            # Mock IRIS authentication failure
            async def failing_iris_auth():
                raise Exception("IRIS connection failed")

            mock_thread.return_value = failing_iris_auth()

            start_time = time.perf_counter()
            result = await authenticator.authenticate(
                connection_id="test-conn-error",
                username="testuser",
                auth_data=b"test-auth-data"
            )
            end_time = time.perf_counter()

            actual_time = (end_time - start_time) * 1000

            # Even failed authentication should meet timing constraints
            assert not result.success
            assert result.auth_time_ms < 50.0  # Should fail fast
            assert actual_time < 50.0

    def test_constitutional_governance_authentication_requirements(self):
        """Test that constitutional governance includes authentication requirements"""
        governor = get_governor()
        requirements = governor.requirements

        # Verify authentication-related constitutional requirements exist
        assert 'sla_compliance' in requirements
        assert requirements['sla_compliance'].threshold_value == 5.0
        assert requirements['sla_compliance'].unit == 'milliseconds'

        # Verify production readiness requirements
        assert 'error_rate' in requirements
        assert 'availability' in requirements

    def test_constitutional_compliance_check_authentication(self):
        """Test constitutional compliance check includes authentication metrics"""
        governor = get_governor()
        monitor = get_monitor()

        # Simulate some authentication operations
        monitor.record_operation("postgresql_authentication", 2.5, True)
        monitor.record_operation("postgresql_authentication", 3.1, True)
        monitor.record_operation("iris_authentication", 1.8, True)

        # Check compliance
        compliance_results = governor.check_compliance()

        # Verify SLA compliance is checked
        assert 'sla_compliance' in compliance_results
        sla_status = compliance_results['sla_compliance']
        assert sla_status.compliant  # Should be compliant with fast operations
        assert sla_status.current_value < 5.0

    def test_constitutional_report_includes_authentication(self):
        """Test constitutional report includes authentication compliance"""
        governor = get_governor()
        monitor = get_monitor()

        # Simulate authentication operations
        monitor.record_operation("postgresql_authentication", 2.0, True)
        monitor.record_operation("iris_authentication", 3.0, True)

        # Generate report
        report = governor.generate_constitutional_report()

        # Verify report structure
        assert 'constitutional_governance' in report
        assert 'compliance_by_principle' in report
        assert 'summary' in report

        # Verify production readiness principle includes authentication SLA
        production_readiness = report['compliance_by_principle'].get('production_readiness', [])
        sla_requirements = [req for req in production_readiness if req['requirement_id'] == 'sla_compliance']
        assert len(sla_requirements) > 0

        sla_req = sla_requirements[0]
        assert sla_req['threshold'] == 5.0
        assert sla_req['unit'] == 'milliseconds'

    @pytest.mark.asyncio
    async def test_authentication_performance_benchmark(self, trust_authenticator):
        """Benchmark authentication performance for constitutional compliance"""
        # Warm up
        for _ in range(5):
            await trust_authenticator.authenticate("warmup", "user")

        # Benchmark 100 authentication operations
        times = []
        for i in range(100):
            start_time = time.perf_counter()
            result = await trust_authenticator.authenticate(f"bench-{i}", f"user{i}")
            end_time = time.perf_counter()

            operation_time = (end_time - start_time) * 1000
            times.append(operation_time)

            assert result.success
            assert result.sla_compliant

        # Statistical analysis
        avg_time = sum(times) / len(times)
        max_time = max(times)
        p95_time = sorted(times)[94]  # 95th percentile

        # Constitutional requirements
        assert avg_time < 2.0, f"Average time {avg_time:.2f}ms exceeds 2ms target"
        assert p95_time < 5.0, f"P95 time {p95_time:.2f}ms exceeds 5ms constitutional SLA"
        assert max_time < 10.0, f"Max time {max_time:.2f}ms exceeds 10ms absolute limit"

        print(f"Authentication Performance Benchmark:")
        print(f"  Average: {avg_time:.2f}ms")
        print(f"  P95: {p95_time:.2f}ms")
        print(f"  Max: {max_time:.2f}ms")
        print(f"  Constitutional SLA Compliance: ✅")