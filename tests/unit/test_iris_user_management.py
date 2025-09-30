"""
Unit Tests for IRIS User Management Integration

Tests user synchronization between IRIS and PGWire authentication systems
with comprehensive coverage of sync modes and user operations.
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List

from iris_pgwire.iris_user_management import (
    IRISUserManager,
    PGWireUserSynchronizer,
    IRISUserInfo,
    PGWireUserInfo,
    UserSyncResult,
    UserSyncMode,
    UserRole
)


class TestIRISUserInfo:
    """Test IRIS user information data structure"""

    def test_iris_user_info_creation(self):
        """Test IRISUserInfo creation and defaults"""
        user_info = IRISUserInfo(
            username="testuser",
            enabled=True,
            roles=["ReadRole", "WriteRole"],
            namespace_access=["USER", "SAMPLES"]
        )

        assert user_info.username == "testuser"
        assert user_info.enabled is True
        assert user_info.roles == ["ReadRole", "WriteRole"]
        assert user_info.namespace_access == ["USER", "SAMPLES"]
        assert user_info.last_login is None
        assert user_info.created_date is None
        assert isinstance(user_info.metadata, dict)

    def test_iris_user_info_with_metadata(self):
        """Test IRISUserInfo with custom metadata"""
        metadata = {"department": "IT", "employee_id": "12345"}
        user_info = IRISUserInfo(
            username="employee",
            enabled=True,
            roles=["EmployeeRole"],
            namespace_access=["CORP"],
            metadata=metadata
        )

        assert user_info.metadata == metadata


class TestPGWireUserInfo:
    """Test PGWire user information data structure"""

    def test_pgwire_user_info_creation(self):
        """Test PGWireUserInfo creation and defaults"""
        user_info = PGWireUserInfo(
            username="pguser",
            has_scram_credentials=True,
            role=UserRole.READ_WRITE,
            enabled=True
        )

        assert user_info.username == "pguser"
        assert user_info.has_scram_credentials is True
        assert user_info.role == UserRole.READ_WRITE
        assert user_info.enabled is True
        assert user_info.last_auth is None
        assert isinstance(user_info.metadata, dict)


class TestUserRole:
    """Test user role enumeration"""

    def test_user_role_values(self):
        """Test user role enumeration values"""
        roles = [UserRole.ADMIN, UserRole.READ_WRITE, UserRole.READ_ONLY, UserRole.GUEST]

        for role in roles:
            assert isinstance(role.value, str)
            assert len(role.value) > 0

    def test_user_role_hierarchy(self):
        """Test implicit user role hierarchy"""
        # Admin should have highest privileges
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.READ_WRITE.value == "read_write"
        assert UserRole.READ_ONLY.value == "read_only"
        assert UserRole.GUEST.value == "guest"


class TestUserSyncMode:
    """Test user synchronization mode enumeration"""

    def test_sync_mode_values(self):
        """Test sync mode enumeration values"""
        modes = [
            UserSyncMode.BIDIRECTIONAL,
            UserSyncMode.IRIS_TO_PGWIRE,
            UserSyncMode.PGWIRE_TO_IRIS,
            UserSyncMode.READ_ONLY
        ]

        for mode in modes:
            assert isinstance(mode.value, str)
            assert len(mode.value) > 0


class TestIRISUserManager:
    """Test suite for IRIS user manager"""

    def setup_method(self):
        """Setup IRIS user manager for each test"""
        self.iris_config = {
            'host': 'localhost',
            'port': '1972',
            'namespace': 'USER',
            'system_user': '_SYSTEM',
            'system_password': 'SYS'
        }
        self.iris_provider = MagicMock()
        self.user_manager = IRISUserManager(self.iris_config, self.iris_provider)

    @pytest.mark.asyncio
    async def test_get_iris_users_success(self):
        """Test successful retrieval of IRIS users"""
        # Mock IRIS database response
        mock_results = [
            ("user1", 1, "ReadRole,WriteRole", "USER,SAMPLES", "2024-01-15", "2024-01-01"),
            ("user2", 0, "AdminRole", "USER", "2024-01-14", "2024-01-02"),
            ("user3", 1, "", "USER", None, "2024-01-03")
        ]

        with patch('iris.createConnection') as mock_create_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = mock_results
            mock_conn.cursor.return_value = mock_cursor
            mock_create_conn.return_value = mock_conn

            users = await self.user_manager.get_iris_users()

            assert len(users) == 3

            # Check first user
            user1 = users[0]
            assert user1.username == "user1"
            assert user1.enabled is True
            assert user1.roles == ["ReadRole", "WriteRole"]
            assert user1.namespace_access == ["USER", "SAMPLES"]

            # Check disabled user
            user2 = users[1]
            assert user2.username == "user2"
            assert user2.enabled is False
            assert user2.roles == ["AdminRole"]

            # Check user with no roles
            user3 = users[2]
            assert user3.username == "user3"
            assert user3.roles == []

    @pytest.mark.asyncio
    async def test_get_iris_users_with_namespace_filter(self):
        """Test IRIS user retrieval with namespace filter"""
        with patch('iris.createConnection') as mock_create_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_conn.cursor.return_value = mock_cursor
            mock_create_conn.return_value = mock_conn

            await self.user_manager.get_iris_users(namespace="SAMPLES")

            # Verify namespace filter was applied
            mock_cursor.execute.assert_called_once()
            call_args = mock_cursor.execute.call_args[0]
            assert "NameSpace LIKE ?" in call_args[0]
            assert call_args[1] == ["%SAMPLES%"]

    @pytest.mark.asyncio
    async def test_get_iris_user_cached(self):
        """Test getting user from cache"""
        # Pre-populate cache
        cached_user = IRISUserInfo(
            username="cached_user",
            enabled=True,
            roles=["TestRole"],
            namespace_access=["USER"]
        )
        self.user_manager._user_cache["cached_user"] = cached_user

        user = await self.user_manager.get_iris_user("cached_user")

        assert user is cached_user
        assert user.username == "cached_user"

    @pytest.mark.asyncio
    async def test_create_iris_user_success(self):
        """Test successful IRIS user creation"""
        with patch('iris.createConnection') as mock_create_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = [0]  # User doesn't exist
            mock_conn.cursor.return_value = mock_cursor
            mock_create_conn.return_value = mock_conn

            success, message = await self.user_manager.create_iris_user(
                "newuser", "password123", ["TestRole"], ["USER"]
            )

            assert success is True
            assert "successfully" in message.lower()

            # Verify user creation query was executed
            assert mock_cursor.execute.call_count == 2  # Check + Insert

    @pytest.mark.asyncio
    async def test_create_iris_user_already_exists(self):
        """Test IRIS user creation when user already exists"""
        with patch('iris.createConnection') as mock_create_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = [1]  # User exists
            mock_conn.cursor.return_value = mock_cursor
            mock_create_conn.return_value = mock_conn

            success, message = await self.user_manager.create_iris_user(
                "existinguser", "password123"
            )

            assert success is False
            assert "already exists" in message

    @pytest.mark.asyncio
    async def test_create_iris_user_read_only_mode(self):
        """Test IRIS user creation in read-only mode"""
        self.user_manager.set_sync_mode(UserSyncMode.READ_ONLY)

        success, message = await self.user_manager.create_iris_user(
            "newuser", "password123"
        )

        assert success is False
        assert "read-only mode" in message

    @pytest.mark.asyncio
    async def test_update_iris_user_password(self):
        """Test IRIS user password update"""
        with patch('iris.createConnection') as mock_create_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_create_conn.return_value = mock_conn

            success, message = await self.user_manager.update_iris_user_password(
                "testuser", "newpassword123"
            )

            assert success is True
            assert "successfully" in message.lower()

            # Verify password update query
            mock_cursor.execute.assert_called_once()
            call_args = mock_cursor.execute.call_args[0]
            assert "UPDATE Security.Users SET Password" in call_args[0]
            assert call_args[1] == ["newpassword123", "testuser"]

    @pytest.mark.asyncio
    async def test_disable_iris_user(self):
        """Test IRIS user disable"""
        with patch('iris.createConnection') as mock_create_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_create_conn.return_value = mock_conn

            success, message = await self.user_manager.disable_iris_user("testuser")

            assert success is True
            assert "successfully" in message.lower()

            # Verify disable query
            mock_cursor.execute.assert_called_once()
            call_args = mock_cursor.execute.call_args[0]
            assert "UPDATE Security.Users SET Enabled = 0" in call_args[0]
            assert call_args[1] == ["testuser"]

    def test_map_iris_role_to_pgwire(self):
        """Test IRIS role mapping to PGWire roles"""
        # Test admin role mapping
        admin_roles = ["%All", "CustomRole"]
        assert self.user_manager.map_iris_role_to_pgwire(admin_roles) == UserRole.ADMIN

        # Test write role mapping
        write_roles = ["%Developer", "ReadRole"]
        assert self.user_manager.map_iris_role_to_pgwire(write_roles) == UserRole.READ_WRITE

        # Test read role mapping
        read_roles = ["%DB_USER"]
        assert self.user_manager.map_iris_role_to_pgwire(read_roles) == UserRole.READ_ONLY

        # Test guest role mapping (no recognized roles)
        guest_roles = ["UnknownRole"]
        assert self.user_manager.map_iris_role_to_pgwire(guest_roles) == UserRole.GUEST

        # Test empty roles
        empty_roles = []
        assert self.user_manager.map_iris_role_to_pgwire(empty_roles) == UserRole.GUEST

    def test_sync_mode_management(self):
        """Test sync mode management"""
        assert self.user_manager.sync_mode == UserSyncMode.IRIS_TO_PGWIRE  # Default

        self.user_manager.set_sync_mode(UserSyncMode.BIDIRECTIONAL)
        assert self.user_manager.sync_mode == UserSyncMode.BIDIRECTIONAL

        self.user_manager.set_sync_mode(UserSyncMode.READ_ONLY)
        assert self.user_manager.sync_mode == UserSyncMode.READ_ONLY

    def test_cache_management(self):
        """Test user cache management"""
        # Test cache stats
        stats = self.user_manager.get_cache_stats()
        assert "cached_users" in stats
        assert "cache_ttl_seconds" in stats
        assert "sync_mode" in stats
        assert stats["cached_users"] == 0

        # Add user to cache
        user = IRISUserInfo(
            username="cached_user",
            enabled=True,
            roles=["TestRole"],
            namespace_access=["USER"]
        )
        self.user_manager._user_cache["cached_user"] = user

        stats = self.user_manager.get_cache_stats()
        assert stats["cached_users"] == 1

        # Clear cache
        self.user_manager.clear_cache()
        stats = self.user_manager.get_cache_stats()
        assert stats["cached_users"] == 0

    @pytest.mark.asyncio
    async def test_constitutional_compliance_sla(self):
        """Test constitutional compliance SLA requirement"""
        with patch('iris.createConnection') as mock_create_conn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_conn.cursor.return_value = mock_cursor
            mock_create_conn.return_value = mock_conn

            start_time = time.perf_counter()
            users = await self.user_manager.get_iris_users()
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Should complete under constitutional 5ms SLA
            assert elapsed_ms < 5.0, f"IRIS user query exceeded SLA: {elapsed_ms}ms"


class TestPGWireUserSynchronizer:
    """Test suite for PGWire user synchronizer"""

    def setup_method(self):
        """Setup synchronizer for each test"""
        iris_config = {
            'host': 'localhost',
            'port': '1972',
            'namespace': 'USER'
        }
        self.iris_provider = MagicMock()
        self.auth_provider = MagicMock()
        self.iris_manager = IRISUserManager(iris_config, self.iris_provider)
        self.synchronizer = PGWireUserSynchronizer(self.iris_manager, self.auth_provider)

    def test_get_pgwire_users(self):
        """Test retrieval of PGWire users from credential cache"""
        # Mock credential cache
        mock_credentials = {
            "user1": MagicMock(),
            "user2": MagicMock(),
            "user3": MagicMock()
        }
        self.auth_provider._credential_cache = mock_credentials

        users = self.synchronizer._get_pgwire_users()

        assert len(users) == 3
        usernames = {user.username for user in users}
        assert usernames == {"user1", "user2", "user3"}

        for user in users:
            assert user.has_scram_credentials is True
            assert user.enabled is True
            assert user.role == UserRole.READ_WRITE

    def test_get_pgwire_users_no_cache(self):
        """Test PGWire user retrieval when no credential cache exists"""
        # No credential cache attribute
        users = self.synchronizer._get_pgwire_users()
        assert len(users) == 0

    @pytest.mark.asyncio
    async def test_sync_users_read_only_mode(self):
        """Test user sync in read-only mode"""
        self.iris_manager.set_sync_mode(UserSyncMode.READ_ONLY)

        # Mock IRIS operations to avoid actual connections
        self.iris_manager.get_iris_users = AsyncMock(return_value=[])

        result = await self.synchronizer.sync_users()

        assert result.success is True
        assert result.users_synced == 0
        assert result.sla_compliant is True

    @pytest.mark.asyncio
    async def test_sync_iris_to_pgwire(self):
        """Test synchronization from IRIS to PGWire"""
        # Mock IRIS users
        iris_users = [
            IRISUserInfo("iris_user1", True, ["ReadRole"], ["USER"]),
            IRISUserInfo("iris_user2", True, ["WriteRole"], ["USER"]),
            IRISUserInfo("shared_user", True, ["ReadRole"], ["USER"])
        ]

        # Mock PGWire users
        pgwire_users = [
            PGWireUserInfo("pgwire_user1", True, UserRole.READ_WRITE, True),
            PGWireUserInfo("shared_user", True, UserRole.READ_WRITE, True)
        ]

        # Mock successful credential registration
        self.auth_provider.register_user_credentials.return_value = True

        result = await self.synchronizer._sync_iris_to_pgwire(iris_users, pgwire_users, dry_run=False)

        assert result.success is True
        assert result.users_created == 2  # iris_user1 and iris_user2
        assert result.users_synced == 3   # All IRIS users processed

        # Verify credential registration calls
        assert self.auth_provider.register_user_credentials.call_count == 2

    @pytest.mark.asyncio
    async def test_sync_iris_to_pgwire_dry_run(self):
        """Test IRIS to PGWire sync in dry-run mode"""
        iris_users = [
            IRISUserInfo("new_iris_user", True, ["ReadRole"], ["USER"])
        ]
        pgwire_users = []

        result = await self.synchronizer._sync_iris_to_pgwire(iris_users, pgwire_users, dry_run=True)

        assert result.success is True
        assert result.users_created == 1
        assert result.users_synced == 1

        # Verify no actual operations were performed
        self.auth_provider.register_user_credentials.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_pgwire_to_iris(self):
        """Test synchronization from PGWire to IRIS"""
        iris_users = [
            IRISUserInfo("shared_user", True, ["ReadRole"], ["USER"])
        ]

        pgwire_users = [
            PGWireUserInfo("pgwire_user1", True, UserRole.READ_WRITE, True),
            PGWireUserInfo("pgwire_user2", True, UserRole.READ_ONLY, True),
            PGWireUserInfo("shared_user", True, UserRole.READ_WRITE, True)
        ]

        # Mock successful IRIS user creation
        async def mock_create_user(username, password, roles=None, namespaces=None):
            return True, "User created successfully"

        self.iris_manager.create_iris_user = AsyncMock(side_effect=mock_create_user)

        result = await self.synchronizer._sync_pgwire_to_iris(iris_users, pgwire_users, dry_run=False)

        assert result.success is True
        assert result.users_created == 2  # pgwire_user1 and pgwire_user2
        assert result.users_synced == 3   # All PGWire users processed

        # Verify IRIS user creation calls
        assert self.iris_manager.create_iris_user.call_count == 2

    @pytest.mark.asyncio
    async def test_sync_bidirectional(self):
        """Test bidirectional synchronization"""
        iris_users = [IRISUserInfo("iris_only", True, ["ReadRole"], ["USER"])]
        pgwire_users = [PGWireUserInfo("pgwire_only", True, UserRole.READ_WRITE, True)]

        # Mock successful operations
        self.auth_provider.register_user_credentials.return_value = True
        self.iris_manager.create_iris_user = AsyncMock(return_value=(True, "Success"))

        result = await self.synchronizer._sync_bidirectional(iris_users, pgwire_users, dry_run=False)

        assert result.success is True
        assert result.users_created == 2  # One in each direction
        assert result.users_synced == 2   # Both users processed

    @pytest.mark.asyncio
    async def test_sync_with_errors(self):
        """Test sync handling with errors"""
        iris_users = [IRISUserInfo("error_user", True, ["ReadRole"], ["USER"])]
        pgwire_users = []

        # Mock failed credential registration
        self.auth_provider.register_user_credentials.return_value = False

        result = await self.synchronizer._sync_iris_to_pgwire(iris_users, pgwire_users, dry_run=False)

        assert result.success is True  # Continues despite errors
        assert result.users_created == 0
        assert len(result.errors) == 1
        assert "Failed to create PGWire user" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_user_consistency(self):
        """Test user consistency validation"""
        # Mock IRIS users
        iris_users = [
            IRISUserInfo("user1", True, ["ReadRole"], ["USER"]),
            IRISUserInfo("user2", True, ["WriteRole"], ["USER"]),
            IRISUserInfo("shared_user", True, ["ReadRole"], ["USER"])
        ]

        # Mock PGWire users
        pgwire_users = [
            PGWireUserInfo("user3", True, UserRole.READ_WRITE, True),
            PGWireUserInfo("user4", True, UserRole.READ_ONLY, True),
            PGWireUserInfo("shared_user", True, UserRole.READ_WRITE, True)
        ]

        self.iris_manager.get_iris_users = AsyncMock(return_value=iris_users)
        self.synchronizer._get_pgwire_users = MagicMock(return_value=pgwire_users)

        consistency = await self.synchronizer.validate_user_consistency()

        assert consistency['total_iris_users'] == 3
        assert consistency['total_pgwire_users'] == 3
        assert consistency['users_in_both'] == 1  # shared_user
        assert set(consistency['only_in_iris']) == {"user1", "user2"}
        assert set(consistency['only_in_pgwire']) == {"user3", "user4"}
        assert consistency['consistency_score'] == 1/5  # 1 shared out of 5 total unique

    def test_sync_stats(self):
        """Test synchronization statistics"""
        stats = self.synchronizer.get_sync_stats()

        assert 'last_sync' in stats
        assert 'total_syncs' in stats
        assert 'last_sync_duration_ms' in stats
        assert stats['total_syncs'] == 0

    @pytest.mark.asyncio
    async def test_constitutional_compliance_sync(self):
        """Test constitutional compliance for sync operations"""
        # Mock quick operations
        self.iris_manager.get_iris_users = AsyncMock(return_value=[])
        self.synchronizer._get_pgwire_users = MagicMock(return_value=[])

        start_time = time.perf_counter()
        result = await self.synchronizer.sync_users()
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete under constitutional 5ms SLA
        assert elapsed_ms < 5.0, f"User sync exceeded SLA: {elapsed_ms}ms"
        assert result.sla_compliant is True


class TestUserSyncResult:
    """Test user sync result data structure"""

    def test_user_sync_result_creation(self):
        """Test UserSyncResult creation and defaults"""
        result = UserSyncResult(success=True, users_synced=5)

        assert result.success is True
        assert result.users_synced == 5
        assert result.users_created == 0
        assert result.users_updated == 0
        assert result.users_disabled == 0
        assert isinstance(result.errors, list)
        assert len(result.errors) == 0
        assert result.sync_time_ms == 0.0
        assert result.sla_compliant is True

    def test_user_sync_result_with_errors(self):
        """Test UserSyncResult with errors"""
        errors = ["Error 1", "Error 2"]
        result = UserSyncResult(
            success=False,
            users_synced=3,
            users_created=1,
            errors=errors,
            sync_time_ms=10.5,
            sla_compliant=False
        )

        assert result.success is False
        assert result.users_synced == 3
        assert result.users_created == 1
        assert result.errors == errors
        assert result.sync_time_ms == 10.5
        assert result.sla_compliant is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])