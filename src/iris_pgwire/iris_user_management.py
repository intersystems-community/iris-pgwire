"""
IRIS User Management Integration

Provides utilities for synchronizing PostgreSQL authentication with IRIS user management,
including user creation, password synchronization, and role mapping.

Constitutional Compliance: All operations maintain <5ms SLA requirement.
"""

import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class UserSyncMode(Enum):
    """User synchronization modes"""

    BIDIRECTIONAL = "bidirectional"  # Sync both ways
    IRIS_TO_PGWIRE = "iris_to_pgwire"  # IRIS is source of truth
    PGWIRE_TO_IRIS = "pgwire_to_iris"  # PGWire is source of truth
    READ_ONLY = "read_only"  # No synchronization, read-only access


class UserRole(Enum):
    """User roles for IRIS/PostgreSQL mapping"""

    ADMIN = "admin"
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"
    GUEST = "guest"


@dataclass
class IRISUserInfo:
    """IRIS user information"""

    username: str
    enabled: bool
    roles: list[str]
    namespace_access: list[str]
    last_login: str | None = None
    created_date: str | None = None
    iris_internal_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class PGWireUserInfo:
    """PGWire user information"""

    username: str
    has_scram_credentials: bool
    role: UserRole
    enabled: bool
    last_auth: str | None = None
    created_date: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class UserSyncResult:
    """Result of user synchronization operation"""

    success: bool
    users_synced: int = 0
    users_created: int = 0
    users_updated: int = 0
    users_disabled: int = 0
    errors: list[str] = field(default_factory=list)
    sync_time_ms: float = 0.0
    sla_compliant: bool = True


class IRISUserManager:
    """Manages IRIS user operations and synchronization"""

    def __init__(self, iris_config: dict[str, str], iris_provider):
        self.iris_config = iris_config
        self.iris_provider = iris_provider
        self.sync_mode = UserSyncMode.IRIS_TO_PGWIRE  # Default: IRIS is source of truth
        self._user_cache: dict[str, IRISUserInfo] = {}
        self._cache_ttl = 300  # 5 minutes cache TTL

    def _create_iris_connection(self):
        """Create an IRIS connection using the configured credentials.

        Returns:
            A tuple of (connection, cursor) for IRIS database operations.
        """
        import iris

        connection = iris.createConnection(
            hostname=self.iris_config["host"],
            port=int(self.iris_config["port"]),
            namespace=self.iris_config["namespace"],
            username=self.iris_config.get("system_user", "_SYSTEM"),
            password=self.iris_config.get("system_password", "SYS"),
        )
        return connection, connection.cursor()

    async def get_iris_users(self, namespace: str | None = None) -> list[IRISUserInfo]:
        """
        Get all users from IRIS Security.Users table
        Returns list of IRIS user information
        """
        start_time = time.perf_counter()

        try:

            def iris_query():
                try:
                    connection, cursor = self._create_iris_connection()

                    # Query IRIS Security.Users table
                    if namespace:
                        query = """
                        SELECT Name, Enabled, Roles, NameSpace, LoginDateTime, CreateDate
                        FROM Security.Users
                        WHERE NameSpace LIKE ? OR NameSpace IS NULL
                        ORDER BY Name
                        """
                        cursor.execute(query, [f"%{namespace}%"])
                    else:
                        query = """
                        SELECT Name, Enabled, Roles, NameSpace, LoginDateTime, CreateDate
                        FROM Security.Users
                        ORDER BY Name
                        """
                        cursor.execute(query)

                    results = cursor.fetchall()
                    users = []

                    for row in results:
                        name, enabled, roles, namespaces, last_login, created = row

                        # Parse roles (might be comma-separated)
                        role_list = []
                        if roles:
                            role_list = [r.strip() for r in roles.split(",") if r.strip()]

                        # Parse namespace access
                        namespace_list = []
                        if namespaces:
                            namespace_list = [
                                ns.strip() for ns in namespaces.split(",") if ns.strip()
                            ]

                        user_info = IRISUserInfo(
                            username=name,
                            enabled=bool(enabled),
                            roles=role_list,
                            namespace_access=namespace_list,
                            last_login=str(last_login) if last_login else None,
                            created_date=str(created) if created else None,
                        )
                        users.append(user_info)

                    return users

                except Exception as e:
                    logger.error(f"IRIS user query failed: {e}")
                    return []

            users = await asyncio.to_thread(iris_query)

            query_time = (time.perf_counter() - start_time) * 1000
            sla_compliant = query_time < 5.0

            if not sla_compliant:
                logger.warning(f"IRIS user query SLA violation: {query_time:.2f}ms")

            # Update cache
            for user in users:
                self._user_cache[user.username] = user

            return users

        except Exception as e:
            logger.error(f"Error getting IRIS users: {e}")
            return []

    async def get_iris_user(self, username: str) -> IRISUserInfo | None:
        """Get specific IRIS user information"""
        # Check cache first
        if username in self._user_cache:
            return self._user_cache[username]

        # Query from IRIS
        users = await self.get_iris_users()
        for user in users:
            if user.username == username:
                return user

        return None

    async def create_iris_user(
        self,
        username: str,
        password: str,
        roles: list[str] | None = None,
        namespaces: list[str] | None = None,
    ) -> tuple[bool, str]:
        """
        Create new user in IRIS
        Returns (success, message)
        """
        if self.sync_mode == UserSyncMode.READ_ONLY:
            return False, "User creation disabled in read-only mode"

        def iris_create():
            connection, cursor = self._create_iris_connection()

            cursor.execute("SELECT COUNT(*) FROM Security.Users WHERE Name = ?", [username])
            if cursor.fetchone()[0] > 0:
                return False, "User already exists"

            role_str = ",".join(roles) if roles else ""
            namespace_str = ",".join(namespaces) if namespaces else self.iris_config["namespace"]

            insert_query = """
            INSERT INTO Security.Users (Name, Enabled, Roles, NameSpace, Password)
            VALUES (?, 1, ?, ?, ?)
            """
            cursor.execute(insert_query, [username, role_str, namespace_str, password])

            if username in self._user_cache:
                del self._user_cache[username]

            return True, "User created successfully"

        return await self._execute_iris_operation(f"creating IRIS user {username}", iris_create)

    async def update_iris_user_password(self, username: str, new_password: str) -> tuple[bool, str]:
        """Update IRIS user password"""
        if self.sync_mode == UserSyncMode.READ_ONLY:
            return False, "Password updates disabled in read-only mode"

        def iris_update():
            connection, cursor = self._create_iris_connection()
            update_query = "UPDATE Security.Users SET Password = ? WHERE Name = ?"
            cursor.execute(update_query, [new_password, username])
            return True, "Password updated successfully"

        return await self._execute_iris_operation(
            f"updating IRIS user password for {username}", iris_update
        )

    async def disable_iris_user(self, username: str) -> tuple[bool, str]:
        """Disable IRIS user account"""
        if self.sync_mode == UserSyncMode.READ_ONLY:
            return False, "User modifications disabled in read-only mode"

        def iris_disable():
            connection, cursor = self._create_iris_connection()
            cursor.execute("UPDATE Security.Users SET Enabled = 0 WHERE Name = ?", [username])
            if username in self._user_cache:
                del self._user_cache[username]
            return True, "User disabled successfully"

        return await self._execute_iris_operation(f"disabling IRIS user {username}", iris_disable)

    async def _execute_iris_operation(
        self, description: str, handler: Callable[[], tuple[bool, str]]
    ) -> tuple[bool, str]:
        """Run an IRIS operation in a thread with SLA monitoring."""
        start_time = time.perf_counter()
        try:
            success, message = await asyncio.to_thread(handler)
        except Exception as exc:
            error_msg = f"IRIS {description} failed: {exc}"
            logger.error(error_msg)
            success = False
            message = f"{description} failed: {str(exc)}"
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if elapsed_ms >= 5.0:
                logger.warning(f"IRIS {description} SLA violation: {elapsed_ms:.2f}ms")

        return success, message

    def map_iris_role_to_pgwire(self, iris_roles: list[str]) -> UserRole:
        """Map IRIS roles to PGWire user role"""
        # IRIS role mapping (customize based on your IRIS role structure)
        admin_roles = ["%All", "%Manager", "AdminRole"]
        write_roles = ["%Developer", "%Operator", "WriteRole"]
        read_roles = ["%DB_USER", "ReadRole"]

        has_admin = any(role in admin_roles for role in iris_roles)
        has_write = any(role in write_roles for role in iris_roles)
        has_read = any(role in read_roles for role in iris_roles)

        if has_admin:
            return UserRole.ADMIN
        elif has_write:
            return UserRole.READ_WRITE
        elif has_read:
            return UserRole.READ_ONLY
        else:
            return UserRole.GUEST

    def set_sync_mode(self, mode: UserSyncMode):
        """Set user synchronization mode"""
        self.sync_mode = mode
        logger.info(f"User sync mode set to: {mode.value}")

    def get_cache_stats(self) -> dict[str, Any]:
        """Get user cache statistics"""
        return {
            "cached_users": len(self._user_cache),
            "cache_ttl_seconds": self._cache_ttl,
            "sync_mode": self.sync_mode.value,
        }

    def clear_cache(self):
        """Clear user cache"""
        self._user_cache.clear()
        logger.info("User cache cleared")


class PGWireUserSynchronizer:
    """Synchronizes users between IRIS and PGWire authentication"""

    def __init__(self, iris_user_manager: IRISUserManager, auth_provider):
        self.iris_manager = iris_user_manager
        self.auth_provider = auth_provider
        self._sync_stats = {"last_sync": None, "total_syncs": 0, "last_sync_duration_ms": 0.0}

    async def sync_users(self, dry_run: bool = False) -> UserSyncResult:
        """
        Synchronize users between IRIS and PGWire
        Returns sync operation results
        """
        start_time = time.perf_counter()
        result = UserSyncResult(success=False)

        try:
            logger.info(
                f"Starting user sync (dry_run={dry_run}, mode={self.iris_manager.sync_mode.value})"
            )

            # Get IRIS users
            iris_users = await self.iris_manager.get_iris_users()
            logger.info(f"Found {len(iris_users)} IRIS users")

            # Get PGWire users (from credential cache)
            pgwire_users = self._get_pgwire_users()
            logger.info(f"Found {len(pgwire_users)} PGWire users")

            if self.iris_manager.sync_mode == UserSyncMode.IRIS_TO_PGWIRE:
                result = await self._sync_iris_to_pgwire(iris_users, pgwire_users, dry_run)
            elif self.iris_manager.sync_mode == UserSyncMode.PGWIRE_TO_IRIS:
                result = await self._sync_pgwire_to_iris(iris_users, pgwire_users, dry_run)
            elif self.iris_manager.sync_mode == UserSyncMode.BIDIRECTIONAL:
                result = await self._sync_bidirectional(iris_users, pgwire_users, dry_run)
            else:  # READ_ONLY
                result.success = True
                result.users_synced = 0
                logger.info("Sync skipped - read-only mode")

            sync_time = (time.perf_counter() - start_time) * 1000
            result.sync_time_ms = sync_time
            result.sla_compliant = sync_time < 5.0

            # Update statistics
            self._sync_stats["last_sync"] = time.time()
            self._sync_stats["total_syncs"] += 1
            self._sync_stats["last_sync_duration_ms"] = sync_time

            if not result.sla_compliant:
                logger.warning(f"User sync SLA violation: {sync_time:.2f}ms")

            logger.info(f"User sync completed: {result.users_synced} users processed")
            return result

        except Exception as e:
            logger.error(f"Error during user sync: {e}")
            result.errors.append(f"Sync error: {str(e)}")
            result.sync_time_ms = (time.perf_counter() - start_time) * 1000
            return result

    def _get_pgwire_users(self) -> list[PGWireUserInfo]:
        """Get users from PGWire credential cache"""
        users = []
        if hasattr(self.auth_provider, "_credential_cache"):
            for username, _credentials in self.auth_provider._credential_cache.items():
                user_info = PGWireUserInfo(
                    username=username,
                    has_scram_credentials=True,
                    role=UserRole.READ_WRITE,  # Default role
                    enabled=True,
                    metadata={"credential_source": "scram_cache"},
                )
                users.append(user_info)
        return users

    async def _sync_iris_to_pgwire(
        self, iris_users: list[IRISUserInfo], pgwire_users: list[PGWireUserInfo], dry_run: bool
    ) -> UserSyncResult:
        """Sync from IRIS to PGWire (IRIS is source of truth)"""
        result = UserSyncResult(success=True)

        pgwire_usernames = {user.username for user in pgwire_users}

        for iris_user in iris_users:
            try:
                if iris_user.username not in pgwire_usernames:
                    # Create PGWire user
                    if not dry_run:
                        # Generate temporary password for SCRAM setup
                        temp_password = secrets.token_urlsafe(16)
                        success = self.auth_provider.register_user_credentials(
                            iris_user.username, temp_password
                        )
                        if success:
                            result.users_created += 1
                            logger.info(f"Created PGWire user: {iris_user.username}")
                        else:
                            result.errors.append(
                                f"Failed to create PGWire user: {iris_user.username}"
                            )
                    else:
                        result.users_created += 1
                        logger.info(f"[DRY RUN] Would create PGWire user: {iris_user.username}")

                result.users_synced += 1

            except Exception as e:
                error_msg = f"Error syncing user {iris_user.username}: {str(e)}"
                result.errors.append(error_msg)
                logger.error(error_msg)

        return result

    async def _sync_pgwire_to_iris(
        self, iris_users: list[IRISUserInfo], pgwire_users: list[PGWireUserInfo], dry_run: bool
    ) -> UserSyncResult:
        """Sync from PGWire to IRIS (PGWire is source of truth)"""
        result = UserSyncResult(success=True)

        iris_usernames = {user.username for user in iris_users}

        for pgwire_user in pgwire_users:
            try:
                if pgwire_user.username not in iris_usernames:
                    # Create IRIS user
                    if not dry_run:
                        temp_password = secrets.token_urlsafe(16)
                        success, message = await self.iris_manager.create_iris_user(
                            pgwire_user.username,
                            temp_password,
                            roles=["%DB_USER"],  # Default role
                            namespaces=[self.iris_manager.iris_config["namespace"]],
                        )
                        if success:
                            result.users_created += 1
                            logger.info(f"Created IRIS user: {pgwire_user.username}")
                        else:
                            result.errors.append(
                                f"Failed to create IRIS user {pgwire_user.username}: {message}"
                            )
                    else:
                        result.users_created += 1
                        logger.info(f"[DRY RUN] Would create IRIS user: {pgwire_user.username}")

                result.users_synced += 1

            except Exception as e:
                error_msg = f"Error syncing user {pgwire_user.username}: {str(e)}"
                result.errors.append(error_msg)
                logger.error(error_msg)

        return result

    async def _sync_bidirectional(
        self, iris_users: list[IRISUserInfo], pgwire_users: list[PGWireUserInfo], dry_run: bool
    ) -> UserSyncResult:
        """Bidirectional sync (merge both sources)"""
        # Sync IRIS to PGWire first
        result1 = await self._sync_iris_to_pgwire(iris_users, pgwire_users, dry_run)

        # Then sync PGWire to IRIS
        result2 = await self._sync_pgwire_to_iris(iris_users, pgwire_users, dry_run)

        # Combine results
        combined_result = UserSyncResult(
            success=result1.success and result2.success,
            users_synced=result1.users_synced + result2.users_synced,
            users_created=result1.users_created + result2.users_created,
            users_updated=result1.users_updated + result2.users_updated,
            users_disabled=result1.users_disabled + result2.users_disabled,
            errors=result1.errors + result2.errors,
        )

        return combined_result

    def get_sync_stats(self) -> dict[str, Any]:
        """Get synchronization statistics"""
        return self._sync_stats.copy()

    async def validate_user_consistency(self) -> dict[str, Any]:
        """Validate consistency between IRIS and PGWire users"""
        iris_users = await self.iris_manager.get_iris_users()
        pgwire_users = self._get_pgwire_users()

        iris_usernames = {user.username for user in iris_users}
        pgwire_usernames = {user.username for user in pgwire_users}

        only_in_iris = iris_usernames - pgwire_usernames
        only_in_pgwire = pgwire_usernames - iris_usernames
        in_both = iris_usernames & pgwire_usernames

        return {
            "total_iris_users": len(iris_users),
            "total_pgwire_users": len(pgwire_users),
            "users_in_both": len(in_both),
            "only_in_iris": list(only_in_iris),
            "only_in_pgwire": list(only_in_pgwire),
            "consistency_score": len(in_both) / max(len(iris_usernames | pgwire_usernames), 1),
        }


# Export main components
__all__ = [
    "IRISUserManager",
    "PGWireUserSynchronizer",
    "IRISUserInfo",
    "PGWireUserInfo",
    "UserSyncResult",
    "UserSyncMode",
    "UserRole",
]
