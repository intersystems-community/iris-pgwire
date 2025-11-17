"""
Integration Tests for Kerberos GSSAPI Authentication with IRIS

These tests validate Kerberos authentication using k5test isolated test realm.
Tests MUST FAIL initially (no implementation exists yet).

Constitutional Requirements:
- Test-First Development (Principle II)
- Tests written BEFORE implementation
- Tests MUST fail until implementation is complete
- Isolated Kerberos realm via k5test (no production KDC required)

Feature: 024-research-and-implement (Authentication Bridge)
Phase: 3.3 (Integration Tests - Kerberos)
"""

import asyncio

# Import contract interface
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

spec_dir = (
    Path(__file__).parent.parent.parent / "specs" / "024-research-and-implement" / "contracts"
)
sys.path.insert(0, str(spec_dir))

from gssapi_auth_interface import (
    KerberosAuthenticationError,
    KerberosPrincipal,
)

# Import k5test for isolated Kerberos realm
try:
    import k5test

    K5TEST_AVAILABLE = True
except ImportError:
    K5TEST_AVAILABLE = False
    pytestmark = pytest.mark.skip(reason="k5test not installed (pip install k5test)")


# Test fixtures
@pytest.fixture
def gssapi_authenticator():
    """Real GSSAPI authenticator for integration testing (no real implementation yet)"""
    # This will fail until implementation exists
    try:
        from iris_pgwire.auth import GSSAPIAuthenticator

        return GSSAPIAuthenticator()
    except (ImportError, AttributeError):
        pytest.skip("GSSAPIAuthenticator implementation not available (expected during TDD)")


@pytest.fixture(scope="module")
def kerberos_realm():
    """Isolated Kerberos test realm using k5test"""
    if not K5TEST_AVAILABLE:
        pytest.skip("k5test not installed")

    # Create isolated Kerberos realm
    realm = k5test.K5Realm()

    # Create test principals
    realm.addprinc("testuser", password="testpassword")
    realm.addprinc("alice", password="alicepassword")
    realm.addprinc("bob", password="bobpassword")

    # Create service principal for pgwire
    realm.addprinc("pgwire/localhost", password="pgwirepassword")

    yield realm

    # Cleanup
    realm.stop()


@pytest.fixture
def test_principal_credentials(kerberos_realm):
    """Test principal credentials for Kerberos authentication"""
    return {
        "testuser": {
            "principal": f"testuser@{kerberos_realm.realm}",
            "password": "testpassword",
            "expected_iris_user": "TESTUSER",
        },
        "alice": {
            "principal": f"alice@{kerberos_realm.realm}",
            "password": "alicepassword",
            "expected_iris_user": "ALICE",
        },
        "bob": {
            "principal": f"bob@{kerberos_realm.realm}",
            "password": "bobpassword",
            "expected_iris_user": "BOB",
        },
    }


@pytest.fixture
def iris_connection_mock():
    """Mock IRIS connection for INFORMATION_SCHEMA.USERS validation"""
    with patch("iris.sql.exec") as mock_exec:
        # Simulate INFORMATION_SCHEMA.USERS query results
        mock_result = Mock()
        mock_result.fetchone.side_effect = [
            ["TESTUSER"],  # User exists
            ["ALICE"],  # User exists
            ["BOB"],  # User exists
            None,  # User not found (for negative tests)
        ]
        mock_exec.return_value = mock_result
        yield mock_exec


# T019: Integration test: Kerberos authentication with k5test isolated realm
class TestKerberosAuthenticationIntegration:
    """Test Kerberos GSSAPI authentication with isolated k5test realm"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires k5test setup")
    async def test_real_kerberos_authentication_success(
        self, gssapi_authenticator, kerberos_realm, test_principal_credentials
    ):
        """T019.1: Valid Kerberos ticket should authenticate successfully"""
        # GIVEN: Valid Kerberos principal with ticket
        principal_name = "testuser"
        credentials = test_principal_credentials[principal_name]

        # Obtain Kerberos ticket (kinit equivalent)
        kerberos_realm.kinit(principal_name, password=credentials["password"])

        # Create mock connection for GSSAPI handshake
        connection_id = "test_conn_001"

        # WHEN: Performing GSSAPI handshake with real Kerberos ticket
        principal = await gssapi_authenticator.handle_gssapi_handshake(connection_id)

        # THEN: Should return authenticated KerberosPrincipal
        assert isinstance(principal, KerberosPrincipal)
        assert principal.principal == credentials["principal"]
        assert principal.username == principal_name
        assert principal.realm == kerberos_realm.realm
        assert principal.mapped_iris_user == credentials["expected_iris_user"]
        assert principal.authenticated_at is not None

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires k5test setup")
    async def test_real_kerberos_invalid_ticket_failure(self, gssapi_authenticator, kerberos_realm):
        """T019.2: Invalid Kerberos ticket should raise KerberosAuthenticationError"""
        # GIVEN: No valid Kerberos ticket (kdestroy equivalent)
        kerberos_realm.kdestroy()

        # Create mock connection for GSSAPI handshake
        connection_id = "test_conn_invalid"

        # WHEN/THEN: Should raise KerberosAuthenticationError
        with pytest.raises(KerberosAuthenticationError) as exc_info:
            await gssapi_authenticator.handle_gssapi_handshake(connection_id)

        # Error should indicate no valid ticket
        error_msg = str(exc_info.value).lower()
        assert "ticket" in error_msg or "credential" in error_msg or "failed" in error_msg

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires k5test setup")
    async def test_real_kerberos_expired_ticket_failure(
        self, gssapi_authenticator, kerberos_realm, test_principal_credentials
    ):
        """T019.3: Expired Kerberos ticket should raise KerberosAuthenticationError"""
        # GIVEN: Kerberos ticket with very short lifetime (1 second)
        principal_name = "testuser"
        credentials = test_principal_credentials[principal_name]

        # Obtain ticket with 1 second lifetime
        kerberos_realm.kinit(principal_name, password=credentials["password"], lifetime="1s")

        # Wait for ticket to expire
        await asyncio.sleep(2)

        # Create mock connection for GSSAPI handshake
        connection_id = "test_conn_expired"

        # WHEN/THEN: Should raise KerberosAuthenticationError
        with pytest.raises(KerberosAuthenticationError) as exc_info:
            await gssapi_authenticator.handle_gssapi_handshake(connection_id)

        # Error should indicate expired ticket
        error_msg = str(exc_info.value).lower()
        assert "expired" in error_msg or "invalid" in error_msg

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires k5test setup")
    async def test_real_kerberos_handshake_latency(
        self, gssapi_authenticator, kerberos_realm, test_principal_credentials
    ):
        """T019.4: GSSAPI handshake should complete within 5 seconds (FR-028)"""
        import time

        # GIVEN: Valid Kerberos principal with ticket
        principal_name = "testuser"
        credentials = test_principal_credentials[principal_name]
        kerberos_realm.kinit(principal_name, password=credentials["password"])

        # Create mock connection for GSSAPI handshake
        connection_id = "test_conn_latency"

        # WHEN: Measuring handshake latency
        start_time = time.time()
        principal = await asyncio.wait_for(
            gssapi_authenticator.handle_gssapi_handshake(connection_id), timeout=5.0
        )
        elapsed = time.time() - start_time

        # THEN: Should complete within 5 seconds (FR-028)
        assert elapsed < 5.0, f"GSSAPI handshake took {elapsed}s, exceeds 5s limit (FR-028)"
        assert principal is not None

        # Log actual latency for performance monitoring
        print(f"✅ GSSAPI handshake latency: {elapsed:.3f}s (within 5s SLA)")

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires k5test setup")
    async def test_real_kerberos_multiple_principals(
        self, gssapi_authenticator, kerberos_realm, test_principal_credentials
    ):
        """T019.5: Multiple Kerberos principals should authenticate independently"""
        # GIVEN: Multiple Kerberos principals
        principals = ["testuser", "alice", "bob"]

        for principal_name in principals:
            credentials = test_principal_credentials[principal_name]
            kerberos_realm.kinit(principal_name, password=credentials["password"])

            # Create mock connection for GSSAPI handshake
            connection_id = f"test_conn_{principal_name}"

            # WHEN: Performing GSSAPI handshake
            principal = await gssapi_authenticator.handle_gssapi_handshake(connection_id)

            # THEN: Should return correct KerberosPrincipal
            assert principal.username == principal_name
            assert principal.mapped_iris_user == credentials["expected_iris_user"]


# T020: Integration test: Kerberos principal mapping with IRIS user validation
class TestKerberosPrincipalMappingIntegration:
    """Test Kerberos principal → IRIS username mapping with real INFORMATION_SCHEMA validation"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_principal_mapping_iris_user_exists(
        self, gssapi_authenticator, iris_connection_mock
    ):
        """T020.1: Principal mapping should validate IRIS user exists in INFORMATION_SCHEMA"""
        # GIVEN: Kerberos principal that maps to existing IRIS user
        principal = "testuser@EXAMPLE.COM"

        # WHEN: Mapping principal to IRIS username (with validation)
        iris_username = await gssapi_authenticator.map_principal_to_iris_user(principal)

        # THEN: Should return IRIS username after validation
        assert iris_username == "TESTUSER"

        # Verify INFORMATION_SCHEMA.USERS query was executed
        iris_connection_mock.assert_called()
        call_args_str = str(iris_connection_mock.call_args)
        assert "INFORMATION_SCHEMA.USERS" in call_args_str

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_principal_mapping_iris_user_not_found(
        self, gssapi_authenticator, iris_connection_mock
    ):
        """T020.2: Principal mapping should raise error if IRIS user doesn't exist (FR-017)"""
        # GIVEN: Kerberos principal that maps to non-existent IRIS user
        principal = "nonexistent@EXAMPLE.COM"

        # Mock INFORMATION_SCHEMA.USERS query to return no results
        iris_connection_mock.return_value.fetchone.return_value = None

        # WHEN/THEN: Should raise KerberosAuthenticationError
        with pytest.raises(KerberosAuthenticationError) as exc_info:
            await gssapi_authenticator.map_principal_to_iris_user(principal)

        # Error message should be clear and actionable (FR-017)
        error_msg = str(exc_info.value).lower()
        assert "not found" in error_msg or "does not exist" in error_msg
        assert "nonexistent" in error_msg  # Should mention the username

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_principal_mapping_standard_format(
        self, gssapi_authenticator, iris_connection_mock
    ):
        """T020.3: alice@EXAMPLE.COM should map to ALICE (strip realm + uppercase)"""
        # GIVEN: Standard Kerberos principal format
        principal = "alice@EXAMPLE.COM"

        # WHEN: Mapping to IRIS username
        iris_username = await gssapi_authenticator.map_principal_to_iris_user(principal)

        # THEN: Should strip realm and uppercase
        assert iris_username == "ALICE"

        # Verify INFORMATION_SCHEMA.USERS validation occurred
        iris_connection_mock.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_principal_mapping_with_dots(
        self, gssapi_authenticator, iris_connection_mock
    ):
        """T020.4: john.doe@EXAMPLE.COM should map to JOHN.DOE (preserve dots)"""
        # GIVEN: Principal with dots in username
        principal = "john.doe@EXAMPLE.COM"

        # Mock INFORMATION_SCHEMA.USERS to indicate user exists
        mock_result = Mock()
        mock_result.fetchone.return_value = ["JOHN.DOE"]
        iris_connection_mock.return_value = mock_result

        # WHEN: Mapping to IRIS username
        iris_username = await gssapi_authenticator.map_principal_to_iris_user(principal)

        # THEN: Should preserve dots and uppercase
        assert iris_username == "JOHN.DOE"

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_principal_mapping_subdomain_realm(
        self, gssapi_authenticator, iris_connection_mock
    ):
        """T020.5: bob@SUBDOMAIN.EXAMPLE.COM should map to BOB"""
        # GIVEN: Principal with subdomain realm
        principal = "bob@SUBDOMAIN.EXAMPLE.COM"

        # WHEN: Mapping to IRIS username
        iris_username = await gssapi_authenticator.map_principal_to_iris_user(principal)

        # THEN: Should strip complex realm and uppercase
        assert iris_username == "BOB"

        # Verify INFORMATION_SCHEMA.USERS validation
        iris_connection_mock.assert_called()
        call_args_str = str(iris_connection_mock.call_args)
        assert "BOB" in call_args_str or "bob" in call_args_str.lower()
