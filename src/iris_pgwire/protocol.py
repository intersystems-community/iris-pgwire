"""
PostgreSQL Wire Protocol Implementation - P0 Foundation

Implements the core PostgreSQL v3 protocol messages for IRIS backend.
Based on specification: https://www.postgresql.org/docs/current/protocol.html

P0 Implementation:
- SSL probe handling
- StartupMessage parsing
- Authentication (basic)
- ParameterStatus emission
- BackendKeyData generation
- ReadyForQuery state
"""

import asyncio
import base64
import re
import secrets
import ssl
import struct
import time
from typing import Any

import structlog

from .bulk_executor import BulkExecutor
from .copy_handler import CopyHandler
from .csv_processor import CSVParsingError, CSVProcessor
from .iris_executor import IRISExecutor
from .sql_translator import PerformanceStats, TranslationContext, ValidationLevel, get_translator
from .sql_translator.copy_parser import CopyCommandParser, CopyDirection
from .sql_translator.performance_monitor import MetricType, PerformanceTracker, get_monitor

logger = structlog.get_logger()


# PostgreSQL protocol constants
SSL_REQUEST_CODE = 80877103

GSSENC_REQUEST_CODE = 80877104  # GSSAPI encryption request (0x04d21630)
CANCEL_REQUEST_CODE = 80877102
PROTOCOL_VERSION = 0x00030000  # PostgreSQL protocol version 3.0

# Message types
MSG_STARTUP = b""
MSG_QUERY = b"Q"
MSG_PARSE = b"P"
MSG_BIND = b"B"
MSG_DESCRIBE = b"D"
MSG_EXECUTE = b"E"
MSG_SYNC = b"S"
MSG_CLOSE = b"C"
MSG_FLUSH = b"H"
MSG_TERMINATE = b"X"
MSG_COPY_DATA = b"d"
MSG_COPY_DONE = b"c"
MSG_COPY_FAIL = b"f"

# Response message types
MSG_AUTHENTICATION = b"R"
MSG_PARAMETER_STATUS = b"S"
MSG_BACKEND_KEY_DATA = b"K"
MSG_READY_FOR_QUERY = b"Z"
MSG_ERROR_RESPONSE = b"E"
MSG_NOTICE_RESPONSE = b"N"
MSG_ROW_DESCRIPTION = b"T"
MSG_DATA_ROW = b"D"
MSG_COMMAND_COMPLETE = b"C"
MSG_PARSE_COMPLETE = b"1"
MSG_BIND_COMPLETE = b"2"
MSG_CLOSE_COMPLETE = b"3"
MSG_PARAMETER_DESCRIPTION = b"t"
MSG_NO_DATA = b"n"
MSG_COPY_IN_RESPONSE = b"G"
MSG_COPY_OUT_RESPONSE = b"H"
MSG_COPY_BOTH_RESPONSE = b"W"

# Transaction status
STATUS_IDLE = b"I"
STATUS_IN_TRANSACTION = b"T"
STATUS_FAILED_TRANSACTION = b"E"

# Authentication types
AUTH_OK = 0
AUTH_CLEARTEXT_PASSWORD = 3
AUTH_MD5_PASSWORD = 5
AUTH_SASL = 10
AUTH_SASL_CONTINUE = 11
AUTH_SASL_FINAL = 12

# SASL mechanisms
SASL_SCRAM_SHA_256 = "SCRAM-SHA-256"


class PGWireProtocol:
    """
    PostgreSQL Wire Protocol Handler

    Manages the PostgreSQL v3 protocol communication for a single client connection.
    Implements P0 foundation functionality with IRIS backend integration.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        iris_executor: IRISExecutor,
        connection_id: str,
        enable_scram: bool = False,
    ):
        self.reader = reader
        self.writer = writer
        self.iris_executor = iris_executor
        self.connection_id = connection_id

        # Session state
        self.startup_params = {}
        self.transaction_status = STATUS_IDLE
        self.backend_pid = secrets.randbelow(32768) + 1000  # PostgreSQL-like PID
        self.backend_secret = secrets.randbelow(2**32)
        self.ssl_enabled = False

        # Protocol state
        self.authenticated = False
        self.ready = False

        # P3: Authentication state
        self.enable_scram = enable_scram
        self.auth_method = AUTH_SASL if enable_scram else AUTH_OK
        self.scram_state = {}  # SCRAM authentication state
        self.client_nonce = None
        self.server_nonce = None
        self.salt = None
        self.iteration_count = 4096

        # Feature 024: Authentication Bridge integration
        try:
            from iris_pgwire.auth import AuthenticationSelector, OAuthBridge, WalletCredentials

            self.auth_selector = AuthenticationSelector(
                oauth_enabled=True,
                kerberos_enabled=False,  # GSSAPI not yet wired
                wallet_enabled=True,
            )
            self.oauth_bridge = OAuthBridge()
            self.wallet_credentials = WalletCredentials()
            self.auth_bridge_available = True
            logger.debug(
                "Authentication bridge initialized",
                connection_id=connection_id,
                oauth_enabled=True,
                wallet_enabled=True,
            )
        except ImportError as e:
            # Authentication bridge not available - fallback to trust mode
            self.auth_bridge_available = False
            logger.warning(
                "Authentication bridge not available - using trust mode",
                connection_id=connection_id,
                error=str(e),
            )

        # P2: Extended Protocol state
        self.prepared_statements = {}  # name -> {'query': str, 'param_types': list}
        self.portals = {}  # name -> {'statement': str, 'params': list}

        # P6: Back-pressure controls for large result sets
        self.result_batch_size = 1000  # Rows per DataRow batch
        self.max_pending_bytes = 5 * 1024 * 1024  # 5MB write buffer limit

        # SQL Translation Integration
        self.sql_translator = get_translator()
        self.performance_monitor = get_monitor()
        self.enable_translation = True  # Enable IRIS SQL translation
        self.translation_debug = False  # Enable translation debug mode

        # P6: COPY Protocol Integration
        self.csv_processor = CSVProcessor()
        self.bulk_executor = BulkExecutor(self.iris_executor)
        self.copy_handler = CopyHandler(self.csv_processor, self.bulk_executor)
        self.copy_state = None  # Track ongoing COPY operation state

        # Batch execution buffering (collapses repeated Bind/Execute into execute_many)
        self.batch_sql = None
        self.batch_params = []
        self.batch_statement_name = None
        self.batch_portal_name = None
        self.batch_max_rows = 0

        logger.info(
            "Protocol handler initialized",
            connection_id=connection_id,
            backend_pid=self.backend_pid,
            translation_enabled=self.enable_translation,
        )

    async def translate_sql(
        self, original_sql: str, session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Translate PostgreSQL SQL constructs to IRIS equivalents using centralized pipeline.
        """
        if not self.enable_translation:
            return {
                "success": True,
                "original_sql": original_sql,
                "translated_sql": original_sql,
                "translation_used": False,
                "performance_stats": PerformanceStats(0.0, False, 0, 0),
            }

        try:
            with PerformanceTracker(
                MetricType.TRANSLATION_TIME,
                "protocol_handler",
                session_id=session_id,
                trace_id=f"conn_{self.connection_id}",
            ) as tracker:
                final_sql, _, result = self.iris_executor.sql_pipeline.process(
                    original_sql, session_id=session_id
                )

                return {
                    "success": True,
                    "original_sql": original_sql,
                    "translated_sql": final_sql,
                    "was_skipped": result.was_skipped,
                    "skip_reason": result.skip_reason,
                    "command_tag": result.command_tag,
                    "translation_used": True,
                    "performance_stats": result.performance_stats,
                    "construct_mappings": [],
                    "warnings": [],
                    "validation_result": None,
                }

        except Exception as e:
            logger.error(
                "SQL translation failed",
                connection_id=self.connection_id,
                error=str(e),
                original_sql=(
                    original_sql[:100] + "..." if len(original_sql) > 100 else original_sql
                ),
            )

            return {
                "success": False,
                "original_sql": original_sql,
                "translated_sql": original_sql,  # Fallback to original
                "translation_used": False,
                "error": str(e),
                "performance_stats": PerformanceStats(0.0, False, 0, 0),
            }

    def translate_postgres_parameters(self, sql: str) -> str:
        """
        Translate PostgreSQL parameter placeholders and type casts to IRIS syntax.
        Delegates to SQLTranslator for consistency across query paths.
        """
        return self.iris_executor.sql_translator.translate_postgres_parameters(sql)

    def infer_parameter_oids_from_casts(self, translated_sql: str, param_count: int) -> list:
        """
        Infer PostgreSQL type OIDs from CAST(? AS type) expressions in translated SQL.

        After translate_postgres_parameters() converts $1::int to CAST(? AS INTEGER),
        this function extracts the IRIS types and maps them back to PostgreSQL OIDs.

        Args:
            translated_sql: SQL after PostgreSQL→IRIS translation (contains CAST(? AS type))
            param_count: Number of parameters (? placeholders)

        Returns:
            List of PostgreSQL type OIDs for each parameter
        """
        sql_upper = translated_sql.upper()

        # PRISMA/ORM CATALOG QUERY FIX (Feature 031):
        # Prisma introspection sends queries with multiple ANY($n) patterns but expects
        # fewer parameters than the query suggests. Our catalog interceptions handle
        # these queries without needing actual parameters, so we return the expected
        # parameter count that ORMs actually send.
        #
        # Pattern: Prisma column info query - has 2 ANY patterns but sends only 1 param
        # Query: SELECT ... FROM information_schema.columns ... WHERE namespace = ANY($1) AND table_name = ANY($2)
        # Prisma sends: 1 param (namespace array)
        if (
            ("INFO.TABLE_NAME" in sql_upper or "INFORMATION_SCHEMA" in sql_upper)
            and ("INFO.COLUMN_NAME" in sql_upper or "COLUMN_NAME" in sql_upper)
            and "FORMAT_TYPE" in sql_upper
        ):
            logger.info(
                "Prisma column info query detected - returning 1 param (namespace only)",
                connection_id=self.connection_id,
                detected_placeholders=param_count,
                sql_preview=translated_sql[:150],
            )
            return [1009]  # Single text[] for namespace filter

        # Pattern: Prisma pg_class query - table introspection with namespace filter
        # Query: SELECT ... FROM pg_class ... WHERE namespace.nspname = ANY($1)
        if "PG_CLASS" in sql_upper and "PG_NAMESPACE" in sql_upper:
            any_count = sql_upper.count("ANY(?)")
            if any_count >= 1:
                logger.info(
                    "Prisma pg_class query detected - returning 1 param (namespace only)",
                    connection_id=self.connection_id,
                    any_patterns_found=any_count,
                    sql_preview=translated_sql[:150],
                )
                return [1009]  # Single text[] for namespace filter

        # Pattern: Prisma pg_namespace query - simple namespace lookup
        if "PG_NAMESPACE" in sql_upper and "NSPNAME" in sql_upper:
            any_count = sql_upper.count("ANY(?)")
            if any_count >= 1:
                logger.info(
                    "Prisma pg_namespace query detected - returning 1 param",
                    connection_id=self.connection_id,
                    any_patterns_found=any_count,
                    sql_preview=translated_sql[:150],
                )
                return [1009]  # Single text[] for namespace filter

        # Map IRIS types to PostgreSQL OIDs
        iris_to_pg_oid = {
            "INTEGER": 23,  # int4
            "BIGINT": 20,  # int8
            "SMALLINT": 21,  # int2
            "VARCHAR": 1043,  # varchar
            "TEXT": 25,  # text
            "DOUBLE": 701,  # float8
            "FLOAT": 700,  # float4
            "BIT": 16,  # bool
            "BOOLEAN": 16,  # bool
            "DATE": 1082,  # date
            "TIME": 1083,  # time
            "TIMESTAMP": 1114,  # timestamp
            "NUMERIC": 1700,  # numeric
            "DECIMAL": 1700,  # numeric
        }

        # Extract CAST(? AS type) patterns in order
        param_oids = []
        pattern = r"CAST\(\?\s+AS\s+(\w+)(?:\([^)]*\))?\)"

        for match in re.finditer(pattern, translated_sql, re.IGNORECASE):
            iris_type = match.group(1).upper()
            pg_oid = iris_to_pg_oid.get(iris_type, 705)  # Default to UNKNOWN if type not recognized
            param_oids.append(pg_oid)

        # PRISMA FIX: Detect ANY(?) pattern for array parameters
        # Prisma sends queries like "WHERE nspname = ANY($1)" expecting text[] (OID 1009)
        # If we have remaining parameters and query contains ANY(?), use text[] OID
        any_pattern = r"=\s*ANY\s*\(\s*\?\s*\)"
        any_matches = list(re.finditer(any_pattern, translated_sql, re.IGNORECASE))

        # If we found fewer CAST expressions than parameters, check for ANY() patterns
        any_index = 0
        while len(param_oids) < param_count:
            # If this parameter position has an ANY() pattern, use text[] (1009)
            if any_index < len(any_matches):
                param_oids.append(1009)  # text[] for array parameters
                any_index += 1
            else:
                param_oids.append(705)  # Default to UNKNOWN

        return param_oids[:param_count]  # Ensure we don't return more OIDs than parameters

    async def handle_ssl_probe(self, ssl_context: ssl.SSLContext | None):
        """
        P0: Handle SSL/GSSAPI probe (first 8 bytes of connection)

        PostgreSQL clients may send multiple probe requests before the actual StartupMessage:
        1. GSSENCRequest (80877104) - GSSAPI encryption negotiation
        2. SSLRequest (80877103) - SSL/TLS negotiation
        3. CancelRequest (80877102) - Query cancellation

        We loop until we get a non-probe request (the actual StartupMessage).
        """
        try:
            while True:
                # Read first 8 bytes - handle connection close gracefully
                data = await self.reader.readexactly(8)
                if len(data) != 8:
                    raise ValueError("Invalid probe length")

                # Parse request
                length, code = struct.unpack("!II", data)

                if length == 16 and code == CANCEL_REQUEST_CODE:
                    # P4: Handle cancel request - read additional 8 bytes for PID and secret
                    logger.debug("Cancel request received", connection_id=self.connection_id)
                    await self.handle_cancel_request()
                    return  # Cancel requests don't continue to normal protocol

                elif length == 8 and code == GSSENC_REQUEST_CODE:
                    # GSSAPI encryption request (code 80877104 = 0x04d21630)
                    # Respond with 'N' to indicate GSSAPI encryption is not supported
                    # Client will then send another probe or StartupMessage
                    logger.debug(
                        "GSSENCRequest received, responding with 'N' (not supported)",
                        connection_id=self.connection_id,
                    )
                    self.writer.write(b"N")
                    await self.writer.drain()
                    continue  # Loop to read next message

                elif length == 8 and code == SSL_REQUEST_CODE:
                    logger.debug("SSL request received", connection_id=self.connection_id)

                    if ssl_context:
                        # Respond with 'S' (SSL supported) and upgrade connection
                        self.writer.write(b"S")
                        await self.writer.drain()

                        # Upgrade to TLS
                        transport = self.writer.transport
                        protocol = transport.get_protocol()
                        await asyncio.sleep(0.1)  # Allow response to be sent

                        # Create SSL transport
                        ssl_transport = await asyncio.get_event_loop().start_tls(
                            transport, protocol, ssl_context, server_side=True
                        )

                        # Update reader/writer for SSL
                        self.writer = asyncio.StreamWriter(
                            ssl_transport, protocol, self.reader, asyncio.get_event_loop()
                        )
                        self.ssl_enabled = True

                        logger.info("SSL connection established", connection_id=self.connection_id)
                        break  # SSL upgraded, exit loop - client will send StartupMessage
                    else:
                        # Respond with 'N' (no SSL)
                        self.writer.write(b"N")
                        await self.writer.drain()
                        logger.debug(
                            "SSL not supported, continuing with plain connection",
                            connection_id=self.connection_id,
                        )
                        continue  # Loop to read next message

                else:
                    # Not a probe request - this is the StartupMessage
                    logger.debug(
                        "Not a probe request, treating as startup message",
                        connection_id=self.connection_id,
                        length=length,
                        code=code,
                    )

                    # Store the data for startup message parsing
                    self._buffered_data = data
                    break  # Exit loop - startup message will be parsed next

        except asyncio.IncompleteReadError as e:
            # Connection closed before probe completed
            logger.debug(
                "Connection closed during probe",
                connection_id=self.connection_id,
                bytes_read=len(e.partial),
                expected=8,
            )
            raise ConnectionAbortedError("Connection closed during probe")
        except Exception as e:
            logger.error("Probe handling failed", connection_id=self.connection_id, error=str(e))
            raise

    async def handle_startup_sequence(self):
        """
        P0: Handle startup sequence after SSL negotiation

        1. Parse StartupMessage
        2. Send authentication request (basic for P0)
        3. Send ParameterStatus messages
        4. Send BackendKeyData
        5. Send ReadyForQuery
        """
        try:
            # STEP 1: Parse startup message
            logger.info(
                "🔍 HANDSHAKE STEP 1: About to parse StartupMessage",
                connection_id=self.connection_id,
            )
            await self.parse_startup_message()
            logger.info(
                "✅ HANDSHAKE STEP 1: StartupMessage parsed successfully",
                connection_id=self.connection_id,
                params=self.startup_params,
            )

            # STEP 2: Authentication
            logger.info(
                "🔍 HANDSHAKE STEP 2: About to send authentication",
                connection_id=self.connection_id,
                scram_enabled=self.enable_scram,
            )
            if self.enable_scram:
                await self.start_scram_authentication()
                # SCRAM requires additional message handling
                await self.handle_scram_client_final()
                await self.complete_scram_authentication()
            else:
                # P0: Basic authentication (trust)
                await self.send_authentication_ok()
            logger.info(
                "✅ HANDSHAKE STEP 2: Authentication sent", connection_id=self.connection_id
            )

            # STEP 3: Send parameter status messages
            logger.info(
                "🔍 HANDSHAKE STEP 3: About to send ParameterStatus",
                connection_id=self.connection_id,
            )
            await self.send_parameter_status()
            logger.info(
                "✅ HANDSHAKE STEP 3: ParameterStatus sent", connection_id=self.connection_id
            )

            # STEP 4: Send backend key data for cancel requests
            logger.info(
                "🔍 HANDSHAKE STEP 4: About to send BackendKeyData",
                connection_id=self.connection_id,
            )
            await self.send_backend_key_data()
            logger.info(
                "✅ HANDSHAKE STEP 4: BackendKeyData sent", connection_id=self.connection_id
            )

            # STEP 5: Send ready for query
            logger.info(
                "🔍 HANDSHAKE STEP 5: About to send ReadyForQuery", connection_id=self.connection_id
            )
            await self.send_ready_for_query()
            logger.info("✅ HANDSHAKE STEP 5: ReadyForQuery sent", connection_id=self.connection_id)

            self.authenticated = True
            self.ready = True

            logger.info(
                "🎉 Startup sequence completed successfully",
                connection_id=self.connection_id,
                user=self.startup_params.get("user"),
                database=self.startup_params.get("database"),
            )

        except asyncio.IncompleteReadError as e:
            # Client closed connection before sending StartupMessage
            logger.error(
                "❌ Client disconnected during handshake (IncompleteReadError)",
                connection_id=self.connection_id,
                bytes_read=len(e.partial),
                expected=e.expected,
            )
            raise ConnectionAbortedError("Client disconnected before StartupMessage")
        except Exception as e:
            logger.error(
                "❌ Startup sequence failed",
                connection_id=self.connection_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            import traceback

            logger.error("Stack trace:", traceback=traceback.format_exc())
            await self.send_error_response(
                "FATAL", "08006", "startup_failed", f"Startup sequence failed: {e}"
            )
            raise

    async def parse_startup_message(self):
        """Parse PostgreSQL StartupMessage"""
        logger.info(
            "🔍 parse_startup_message: Starting to parse StartupMessage",
            connection_id=self.connection_id,
            has_buffered_data=hasattr(self, "_buffered_data"),
        )

        # Check if we have buffered data from SSL probe
        already_read = b""
        if hasattr(self, "_buffered_data"):
            logger.info(
                "📦 Using buffered data from SSL probe",
                connection_id=self.connection_id,
                buffered_size=len(self._buffered_data),
            )
            # The buffered data contains first 8 bytes of StartupMessage:
            # Bytes 0-3: message length (total size of message including length field)
            # Bytes 4-7: protocol version (part of message payload)
            length = struct.unpack("!I", self._buffered_data[:4])[0]
            # Keep bytes 4-7 (protocol version) as already-read payload
            already_read = self._buffered_data[4:]
            logger.info(
                "📦 Buffered data correctly parsed",
                connection_id=self.connection_id,
                message_length=length,
                already_read_bytes=len(already_read),
            )
            delattr(self, "_buffered_data")
        else:
            # Read message length and check for startup
            logger.info("🔍 About to read 4-byte message length", connection_id=self.connection_id)
            length_data = await self.reader.readexactly(4)
            length = struct.unpack("!I", length_data)[0]
            logger.info("📏 Message length read", connection_id=self.connection_id, length=length)

        # Read remaining message data
        # Length includes the length field itself (4 bytes), so remaining = length - 4
        remaining = length - 4
        logger.info(
            "🔍 About to read remaining message data",
            connection_id=self.connection_id,
            remaining_bytes=remaining,
            already_have_bytes=len(already_read),
        )

        # If we already have some bytes from buffered_data, use them
        if already_read:
            # We already have 4 bytes (protocol version) from buffered SSL probe read
            bytes_needed = remaining - len(already_read)
            if bytes_needed > 0:
                logger.info(
                    "📦 Reading additional bytes",
                    connection_id=self.connection_id,
                    bytes_needed=bytes_needed,
                )
                additional_data = await self.reader.readexactly(bytes_needed)
                message_data = already_read + additional_data
            else:
                # We already have all the data we need
                message_data = already_read[:remaining]
            logger.info(
                "📦 Message data assembled from buffered + new reads",
                connection_id=self.connection_id,
                total_bytes=len(message_data),
            )
        else:
            # Normal path - read all remaining bytes
            if remaining > 0:
                message_data = await self.reader.readexactly(remaining)
                logger.info(
                    "📦 Message data read successfully",
                    connection_id=self.connection_id,
                    bytes_read=len(message_data),
                )
            else:
                message_data = b""
                logger.warning(
                    "⚠️ No message data to read (remaining=0)", connection_id=self.connection_id
                )

        # Parse protocol version
        if len(message_data) >= 4:
            protocol_version = struct.unpack("!I", message_data[:4])[0]
            logger.info(
                "🔍 Protocol version parsed",
                connection_id=self.connection_id,
                protocol_version=f"{protocol_version:08x}",
                expected=f"{PROTOCOL_VERSION:08x}",
            )
            if protocol_version != PROTOCOL_VERSION:
                raise ValueError(f"Unsupported protocol version: {protocol_version:08x}")

            # Parse parameters (null-terminated strings)
            param_data = message_data[4:]
            logger.info(
                "🔍 About to parse parameters",
                connection_id=self.connection_id,
                param_data_size=len(param_data),
            )
            params = {}
            i = 0
            while i < len(param_data) - 1:  # -1 for final null terminator
                # Find key
                key_end = param_data.find(b"\x00", i)
                if key_end == -1:
                    break
                key = param_data[i:key_end].decode("utf-8")
                i = key_end + 1

                # Find value
                value_end = param_data.find(b"\x00", i)
                if value_end == -1:
                    break
                value = param_data[i:value_end].decode("utf-8")
                i = value_end + 1

                params[key] = value
                logger.debug(f"📝 Parameter: {key}={value}", connection_id=self.connection_id)

            self.startup_params = params
            logger.info(
                "✅ All parameters parsed successfully",
                connection_id=self.connection_id,
                params=params,
            )

            # Feature 034: Register session namespace with executor
            requested_db = params.get("database")
            if requested_db:
                self.iris_executor.set_session_namespace(self.connection_id, requested_db)

            logger.debug("Startup message parsed", connection_id=self.connection_id, params=params)

    async def send_authentication_ok(self):
        """Send AuthenticationOk message (P0: basic trust auth)"""
        # AuthenticationOk: R + length + 0
        message = struct.pack("!cII", MSG_AUTHENTICATION, 8, 0)
        self.writer.write(message)
        await self.writer.drain()
        logger.debug("Authentication OK sent", connection_id=self.connection_id)

    # P3: SCRAM-SHA-256 Authentication Methods

    async def start_scram_authentication(self):
        """P3: Start SCRAM-SHA-256 authentication sequence"""
        try:
            # Send SASL authentication request with supported mechanisms
            await self.send_sasl_auth_request()

            # Wait for client's SASL initial response
            header = await self.reader.readexactly(5)
            msg_type, length = struct.unpack("!cI", header)

            if msg_type != b"p":  # SASLResponse message
                raise ValueError(f"Expected SASLResponse, got {msg_type}")

            body_length = length - 4
            body = await self.reader.readexactly(body_length) if body_length > 0 else b""

            await self.handle_sasl_initial_response(body)

        except Exception as e:
            logger.error(
                "SCRAM authentication failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response(
                "FATAL",
                "28000",
                "invalid_authorization_specification",
                f"SCRAM authentication failed: {e}",
            )
            raise

    async def send_sasl_auth_request(self):
        """Send SASL authentication request with SCRAM-SHA-256"""
        # AuthenticationSASL: R + length + 10 + mechanisms
        mechanisms = SASL_SCRAM_SHA_256.encode("utf-8") + b"\x00" + b"\x00"  # null-terminated list
        message_length = 4 + 4 + len(mechanisms)

        message = struct.pack("!cII", MSG_AUTHENTICATION, message_length, AUTH_SASL) + mechanisms
        self.writer.write(message)
        await self.writer.drain()

        logger.debug(
            "SASL authentication request sent",
            connection_id=self.connection_id,
            mechanisms=[SASL_SCRAM_SHA_256],
        )

    async def handle_sasl_initial_response(self, body: bytes):
        """Handle client's SASL initial response"""
        pos = 0

        # Parse mechanism name
        mechanism_end = body.find(b"\x00", pos)
        if mechanism_end == -1:
            raise ValueError("Invalid SASL response: missing mechanism")
        mechanism = body[pos:mechanism_end].decode("utf-8")
        pos = mechanism_end + 1

        if mechanism != SASL_SCRAM_SHA_256:
            raise ValueError(f"Unsupported SASL mechanism: {mechanism}")

        # Parse initial response length
        if pos + 4 > len(body):
            raise ValueError("Invalid SASL response: missing response length")
        response_length = struct.unpack("!I", body[pos : pos + 4])[0]
        pos += 4

        # Parse initial response data
        if response_length == 0xFFFFFFFF:
            response_data = b""
        else:
            if pos + response_length > len(body):
                raise ValueError("Invalid SASL response: truncated response data")
            response_data = body[pos : pos + response_length]

        await self.process_scram_client_first(response_data)

    async def process_scram_client_first(self, client_first: bytes):
        """Process SCRAM client-first message"""
        try:
            # Parse client-first message: "n,,n=user,r=client_nonce"
            client_first_str = client_first.decode("utf-8")

            # Basic parsing (production would be more robust)
            if not client_first_str.startswith("n,,"):
                raise ValueError("Invalid SCRAM client-first message format")

            # Extract username and client nonce
            auth_message = client_first_str[3:]  # Remove "n,," prefix
            parts = auth_message.split(",")

            username = None
            self.client_nonce = None

            for part in parts:
                if part.startswith("n="):
                    username = part[2:]
                elif part.startswith("r="):
                    self.client_nonce = part[2:]

            if not username or not self.client_nonce:
                raise ValueError("Missing username or client nonce in SCRAM message")

            # Generate server nonce and salt
            self.server_nonce = base64.b64encode(secrets.token_bytes(18)).decode("ascii")
            self.salt = base64.b64encode(secrets.token_bytes(16)).decode("ascii")

            # Store auth state for final verification
            self.scram_state = {
                "username": username,
                "client_first_bare": auth_message,
                "client_nonce": self.client_nonce,
                "server_nonce": self.server_nonce,
                "salt": self.salt,
                "iteration_count": self.iteration_count,
            }

            # Send server-first message
            await self.send_scram_server_first()

            logger.debug(
                "SCRAM client-first processed",
                connection_id=self.connection_id,
                username=username,
                client_nonce=self.client_nonce[:8] + "...",
            )

        except Exception as e:
            logger.error(
                "SCRAM client-first processing failed",
                connection_id=self.connection_id,
                error=str(e),
            )
            raise

    async def send_scram_server_first(self):
        """Send SCRAM server-first message"""
        nonce = self.client_nonce + self.server_nonce
        server_first = f"r={nonce},s={self.salt},i={self.iteration_count}"
        server_first_bytes = server_first.encode("utf-8")

        # AuthenticationSASLContinue: R + length + 11 + data
        message_length = 4 + 4 + len(server_first_bytes)
        message = (
            struct.pack("!cII", MSG_AUTHENTICATION, message_length, AUTH_SASL_CONTINUE)
            + server_first_bytes
        )

        self.writer.write(message)
        await self.writer.drain()

        logger.debug(
            "SCRAM server-first sent", connection_id=self.connection_id, nonce=nonce[:16] + "..."
        )

    async def handle_scram_client_final(self):
        """Handle SCRAM client-final message"""
        try:
            # Wait for client-final response
            header = await self.reader.readexactly(5)
            msg_type, length = struct.unpack("!cI", header)

            if msg_type != b"p":  # SASLResponse message
                raise ValueError(f"Expected SASLResponse, got {msg_type}")

            body_length = length - 4
            body = await self.reader.readexactly(body_length) if body_length > 0 else b""

            # Parse client-final message
            client_final_str = body.decode("utf-8")
            logger.debug(
                "SCRAM client-final received",
                connection_id=self.connection_id,
                message_preview=client_final_str[:50] + "...",
            )

            # In production, this would verify the client proof
            # For now, we'll accept any well-formed client-final message

        except Exception as e:
            logger.error(
                "SCRAM client-final handling failed", connection_id=self.connection_id, error=str(e)
            )
            raise

    async def complete_scram_authentication(self):
        """
        Complete SCRAM authentication with OAuth/Wallet integration (Feature 024).

        Authentication Flow:
        1. Extract username and password from SCRAM client-final
        2. Select authentication method (OAuth vs password)
        3. Try Wallet password retrieval first (if enabled)
        4. Fallback to OAuth token exchange or password authentication
        5. Send SCRAM final success on authentication success
        """
        try:
            # Parse client-final message to extract password
            # In real SCRAM, this would verify the client proof
            # For Feature 024, we'll extract credentials and authenticate via OAuth/Wallet

            username = self.scram_state.get("username")
            if not username:
                raise ValueError("Username not found in SCRAM state")

            # Feature 024: Authentication bridge integration
            if self.auth_bridge_available:
                try:
                    # Select authentication method
                    connection_context = {
                        "auth_method": "password",  # SCRAM is password-based
                        "username": username,
                        "database": self.startup_params.get("database", "USER"),
                        "oauth_available": True,
                    }

                    auth_method = await self.auth_selector.select_authentication_method(
                        connection_context
                    )

                    logger.info(
                        "Authentication method selected",
                        connection_id=self.connection_id,
                        username=username,
                        method=auth_method,
                    )

                    # Try Wallet password retrieval first (if applicable)
                    password = None
                    should_try_wallet = await self.auth_selector.should_try_wallet_first(
                        auth_method, username
                    )

                    if should_try_wallet:
                        try:
                            password = await self.wallet_credentials.get_password_from_wallet(
                                username
                            )
                            logger.info(
                                "Password retrieved from Wallet",
                                connection_id=self.connection_id,
                                username=username,
                            )
                        except Exception as wallet_error:
                            logger.info(
                                "Wallet password retrieval failed - will use SCRAM password",
                                connection_id=self.connection_id,
                                username=username,
                                error=str(wallet_error),
                            )
                            # Password remains None - will extract from SCRAM client-final

                    # If no wallet password, extract from SCRAM client-final
                    if password is None:
                        # TODO: Implement proper SCRAM client-final parsing to extract password
                        # For now, use a placeholder (trust mode)
                        password = "placeholder_password"
                        logger.warning(
                            "SCRAM client-final password extraction not yet implemented",
                            connection_id=self.connection_id,
                            username=username,
                        )

                    # Authenticate based on selected method
                    if auth_method == "oauth":
                        # OAuth token exchange
                        token = await self.oauth_bridge.exchange_password_for_token(
                            username, password
                        )
                        logger.info(
                            "OAuth authentication successful",
                            connection_id=self.connection_id,
                            username=username,
                            expires_in=token.expires_in,
                        )

                        # Store token in session for future requests
                        self.scram_state["oauth_token"] = token

                    elif auth_method == "password":
                        # Direct password authentication (fallback)
                        # Verify password against IRIS %Service_Login
                        logger.info(
                            "Password authentication (fallback)",
                            connection_id=self.connection_id,
                            username=username,
                        )
                        # TODO: Implement actual password verification
                        # For now, accept in trust mode

                    else:
                        raise ValueError(f"Unsupported authentication method: {auth_method}")

                    # Authentication successful - send SCRAM final success
                    await self.send_scram_final_success()

                except Exception as auth_error:
                    logger.error(
                        "Authentication failed",
                        connection_id=self.connection_id,
                        username=username,
                        error=str(auth_error),
                    )
                    raise ValueError(f"Authentication failed: {auth_error}")

            else:
                # Authentication bridge not available - use trust mode
                logger.warning(
                    "Using trust mode authentication (bridge unavailable)",
                    connection_id=self.connection_id,
                    username=username,
                )
                await self.send_scram_final_success()

        except Exception as e:
            logger.error(
                "SCRAM authentication completion failed",
                connection_id=self.connection_id,
                error=str(e),
            )
            raise

    async def send_scram_final_success(self):
        """Send SCRAM final success message"""
        # AuthenticationSASLFinal: R + length + 12 + server_signature
        server_final = "v=rmF+pqV8S7suAoZWja4dJRkFsKQ="  # Dummy server signature
        server_final_bytes = server_final.encode("utf-8")

        message_length = 4 + 4 + len(server_final_bytes)
        message = (
            struct.pack("!cII", MSG_AUTHENTICATION, message_length, AUTH_SASL_FINAL)
            + server_final_bytes
        )

        self.writer.write(message)
        await self.writer.drain()

        # Send final AuthenticationOk
        await self.send_authentication_ok()

        logger.info(
            "SCRAM authentication completed successfully",
            connection_id=self.connection_id,
            username=self.scram_state.get("username"),
        )

    async def send_parameter_status(self):
        """Send ParameterStatus messages for PostgreSQL compatibility"""
        # Based on caretdev patterns and PostgreSQL requirements
        parameters = {
            "server_version": "16.0 (InterSystems IRIS)",
            "server_version_num": "160000",
            "client_encoding": "UTF8",
            "DateStyle": "ISO, MDY",
            "TimeZone": "UTC",
            "standard_conforming_strings": "on",
            "integer_datetimes": "on",
            "IntervalStyle": "postgres",
            "is_superuser": "off",
            "server_encoding": "UTF8",
            "application_name": self.startup_params.get("application_name", ""),
        }

        for key, value in parameters.items():
            await self.send_parameter_status_message(key, value)

    async def send_parameter_status_message(self, name: str, value: str):
        """Send a single ParameterStatus message"""
        name_bytes = name.encode("utf-8") + b"\x00"
        value_bytes = value.encode("utf-8") + b"\x00"
        length = 4 + len(name_bytes) + len(value_bytes)

        message = struct.pack("!cI", MSG_PARAMETER_STATUS, length) + name_bytes + value_bytes
        self.writer.write(message)
        await self.writer.drain()

    async def send_backend_key_data(self):
        """Send BackendKeyData for cancel requests"""
        # BackendKeyData: K + length + pid + secret
        # Length is 12 (4 bytes for length field + 4 bytes PID + 4 bytes secret)
        message = struct.pack("!cI", MSG_BACKEND_KEY_DATA, 12) + struct.pack(
            "!II", self.backend_pid, self.backend_secret
        )
        self.writer.write(message)
        await self.writer.drain()
        logger.debug(
            "Backend key data sent",
            connection_id=self.connection_id,
            pid=self.backend_pid,
            secret="***",
        )

    async def send_ready_for_query(self):
        """Send ReadyForQuery message"""
        # ReadyForQuery: Z + length + status
        message = struct.pack("!cI", MSG_READY_FOR_QUERY, 5) + self.transaction_status
        self.writer.write(message)
        await self.writer.drain()
        logger.debug(
            "Ready for query sent",
            connection_id=self.connection_id,
            status=self.transaction_status.decode(),
        )

    async def send_error_response(self, severity: str, code: str, message_type: str, message: str):
        """Send ErrorResponse message"""
        # ErrorResponse: E + length + fields
        fields = []
        fields.append(b"S" + severity.encode("utf-8") + b"\x00")  # Severity
        fields.append(b"C" + code.encode("utf-8") + b"\x00")  # SQLSTATE
        fields.append(b"M" + message.encode("utf-8") + b"\x00")  # Message
        fields.append(b"\x00")  # End of fields

        field_data = b"".join(fields)
        length = 4 + len(field_data)

        error_msg = struct.pack("!cI", MSG_ERROR_RESPONSE, length) + field_data
        self.writer.write(error_msg)
        await self.writer.drain()

    async def message_loop(self):
        """
        Main message processing loop (P0: basic structure)

        For P0, we handle basic Query messages. Full extended protocol
        will be implemented in P2.
        """
        logger.info("Entering message loop", connection_id=self.connection_id)

        try:
            while True:
                # Read message type and length
                header = await self.reader.readexactly(5)
                msg_type, length = struct.unpack("!cI", header)

                # Read message body
                body_length = length - 4
                if body_length > 0:
                    body = await self.reader.readexactly(body_length)
                else:
                    body = b""

                logger.debug(
                    "Message received",
                    connection_id=self.connection_id,
                    msg_type=msg_type,
                    length=length,
                )

                # Handle message based on type
                if msg_type == MSG_QUERY:
                    # P1: Simple Query Protocol
                    await self.handle_query_message(body)
                elif msg_type == MSG_PARSE:
                    # P2: Extended Protocol - Parse
                    await self.handle_parse_message(body)
                elif msg_type == MSG_BIND:
                    # P2: Extended Protocol - Bind
                    await self.handle_bind_message(body)
                elif msg_type == MSG_DESCRIBE:
                    # P2: Extended Protocol - Describe
                    await self.handle_describe_message(body)
                elif msg_type == MSG_EXECUTE:
                    # P2: Extended Protocol - Execute
                    await self.handle_execute_message(body)
                elif msg_type == MSG_SYNC:
                    # P2: Extended Protocol - Sync
                    await self.handle_sync_message(body)
                elif msg_type == MSG_CLOSE:
                    # P2: Extended Protocol - Close
                    await self.handle_close_message(body)
                elif msg_type == MSG_FLUSH:
                    # P2: Extended Protocol - Flush
                    await self.handle_flush_message(body)
                elif msg_type == MSG_COPY_DATA:
                    # P6: COPY Protocol - Data
                    await self.handle_copy_data_message(body)
                elif msg_type == MSG_COPY_DONE:
                    # P6: COPY Protocol - Done
                    await self.handle_copy_done_message(body)
                elif msg_type == MSG_COPY_FAIL:
                    # P6: COPY Protocol - Fail
                    await self.handle_copy_fail_message(body)
                elif msg_type == MSG_TERMINATE:
                    logger.info("Client terminated connection", connection_id=self.connection_id)
                    break
                else:
                    # Unknown messages get error response
                    await self.send_error_response(
                        "ERROR",
                        "0A000",
                        "feature_not_supported",
                        f"Message type {msg_type} not implemented",
                    )

        except asyncio.IncompleteReadError:
            logger.info("Client disconnected", connection_id=self.connection_id)
        except Exception as e:
            logger.error("Message loop error", connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "FATAL", "08006", "connection_failure", f"Protocol error: {e}"
            )
        finally:
            # Ensure pinned session connection is returned to pool
            self.iris_executor.close_session(self.connection_id)

    async def handle_query_message(self, body: bytes):
        """
        P1: Real Query message handler with IRIS execution

        Executes actual SQL against IRIS and returns proper PostgreSQL responses.
        P6: Enhanced with COPY command support for bulk operations.

        CRITICAL (.NET Npgsql compatibility): Simple Query protocol can contain
        multiple statements separated by semicolons. Each statement must be
        processed independently with its own result set. ReadyForQuery is sent
        only after the LAST statement completes.
        """
        try:
            # Ensure any buffered DML is flushed before starting a new Simple Query
            await self.flush_batch()

            # Parse query string (null-terminated)
            query = body.rstrip(b"\x00").decode("utf-8")
            logger.info(
                "Query received",
                connection_id=self.connection_id,
                query=query[:100] + "..." if len(query) > 100 else query,
            )

            # CRITICAL: Translate PostgreSQL syntax (:: type casts, $1 parameters if present)
            # This enables Simple Query protocol to work with PostgreSQL-specific syntax
            query = self.translate_postgres_parameters(query)

            # CRITICAL (.NET Npgsql Fix): Split multiple statements by semicolons
            # Npgsql sends: "SELECT version();\n\nSELECT ... FROM pg_catalog..."
            # We must process EACH statement and return results for ALL of them
            statements = self._split_query_statements(query)

            if len(statements) > 1:
                logger.info(
                    "Multiple statements detected in Simple Query",
                    connection_id=self.connection_id,
                    statement_count=len(statements),
                )

            # Process each statement, sending ReadyForQuery only after the last one
            for i, statement in enumerate(statements):
                is_last_statement = i == len(statements) - 1
                await self._handle_single_statement(statement, send_ready=is_last_statement)

            return  # All statements processed

        except Exception as e:
            logger.error("Query handling failed", connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "ERROR", "08000", "connection_exception", f"Query processing failed: {e}"
            )
            # CRITICAL: Send ReadyForQuery after exception in Simple Query Protocol
            await self.send_ready_for_query()

    def _split_query_statements(self, query: str) -> list:
        """
        Split a query string into individual statements by semicolons.
        Uses DdlSplitter for comment-aware and quote-aware splitting.

        Returns:
            List of non-empty SQL statements
        """
        from .conversions import DdlSplitter

        splitter = DdlSplitter()
        return splitter.split(query)

    async def _handle_single_statement(self, query: str, send_ready: bool = True):
        """
        Handle a single SQL statement (extracted from multi-statement query).

        Args:
            query: Single SQL statement (no trailing semicolon)
            send_ready: If True, send ReadyForQuery after processing
        """
        try:
            # DEBUGGING: Log full SQL for CREATE TABLE statements
            if query.upper().strip().startswith("CREATE TABLE"):
                logger.warning(f"FULL CREATE TABLE SQL (length={len(query)}): {query}")

            # Handle transaction commands first (no IRIS execution needed)
            query_upper = query.upper().strip()
            if query_upper in ("BEGIN", "START TRANSACTION"):
                await self.iris_executor.begin_transaction(session_id=self.connection_id)
                await self.send_transaction_response("BEGIN", send_ready=send_ready)
                return
            elif query_upper in ("COMMIT", "END"):
                await self.iris_executor.commit_transaction(session_id=self.connection_id)
                await self.send_transaction_response("COMMIT", send_ready=send_ready)
                return
            elif query_upper == "ROLLBACK":
                await self.iris_executor.rollback_transaction(session_id=self.connection_id)
                await self.send_transaction_response("ROLLBACK", send_ready=send_ready)
                return

            # Handle DEALLOCATE commands (PostgreSQL prepared statement cleanup)
            # IRIS doesn't support DEALLOCATE, so we silently succeed
            if query_upper.startswith("DEALLOCATE"):
                await self.send_deallocate_response(query_upper, send_ready=send_ready)
                return

            # Handle PostgreSQL SET commands (runtime parameter configuration)
            # IRIS uses different SET syntax (requires OPTION keyword),
            # so we intercept PostgreSQL-specific SET commands and silently succeed
            if query_upper.startswith("SET ") or query_upper.startswith("RESET "):
                await self.handle_set_command(query_upper, send_ready=send_ready)
                return

            # Handle PostgreSQL UNLISTEN and CLOSE ALL commands
            # IRIS doesn't support these, so we silently succeed
            if query_upper.startswith("UNLISTEN") or query_upper.startswith("CLOSE ALL"):
                await self.send_postgresql_command_response(query_upper, send_ready=send_ready)
                return

            # P6: Handle COPY commands
            if query_upper.startswith("COPY "):
                await self.handle_copy_command(query)
                return

            # REMOVED: Protocol-level pg_catalog interception (2025-11-14)
            # - Moved to iris_executor.py where we can return FAKE pg_type data instead of empty results
            # - Npgsql needs pg_type OID mappings to build type registry during connection bootstrap
            # - asyncpg needs pg_type for OID 0 (unspecified) parameter type resolution
            # - iris_executor.py now returns 16 standard PostgreSQL types for pg_type queries
            # - pg_enum still returns empty (IRIS has no enum types)
            # See iris_executor.py lines 989-1053 for implementation

            # Perform SQL translation
            translation_result = await self.translate_sql(query)
            final_sql = translation_result["translated_sql"]

            # CRITICAL FIX: Ensure queries have semicolons for IRIS compatibility
            # IRIS SQL parser requires semicolons to distinguish string literals from parameters
            # Without semicolon: SELECT 'text' → IRIS treats 'text' as parameter (HostVar_1)
            # With semicolon: SELECT 'text'; → IRIS treats 'text' as string literal
            if not final_sql.rstrip().endswith(";"):
                final_sql = final_sql.rstrip() + ";"
                logger.debug(
                    "Added semicolon for IRIS compatibility",
                    connection_id=self.connection_id,
                    sql_preview=final_sql[:100],
                )

            # Log translation summary if constructs were translated
            if translation_result.get("translation_used") and translation_result.get(
                "construct_mappings"
            ):
                perf_stats = translation_result.get("performance_stats")
                logger.info(
                    "IRIS constructs translated",
                    connection_id=self.connection_id,
                    constructs_count=len(translation_result["construct_mappings"]),
                    translation_time_ms=perf_stats.translation_time_ms if perf_stats else 0,
                    cache_hit=perf_stats.cache_hit if perf_stats else False,
                )

            # Execute translated SQL against IRIS
            result = await self.iris_executor.execute_query(
                final_sql, session_id=self.connection_id
            )

            # Add translation metadata to result for debugging/monitoring
            if translation_result.get("translation_used"):
                perf_stats = translation_result.get("performance_stats")
                result["translation_metadata"] = {
                    "original_sql": translation_result["original_sql"],
                    "constructs_translated": len(translation_result.get("construct_mappings", [])),
                    "translation_time_ms": perf_stats.translation_time_ms if perf_stats else 0,
                    "cache_hit": perf_stats.cache_hit if perf_stats else False,
                    "warnings": translation_result.get("warnings", []),
                }

            if result["success"]:
                await self.send_query_result(result, send_ready=send_ready)
            else:
                await self.send_error_response(
                    "ERROR", "42000", "syntax_error", result.get("error", "Query execution failed")
                )
                # CRITICAL: Send ReadyForQuery after error (only if last statement)
                if send_ready:
                    await self.send_ready_for_query()

        except Exception as e:
            logger.error(
                "Single statement handling failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response(
                "ERROR", "08000", "connection_exception", f"Statement processing failed: {e}"
            )
            # CRITICAL: Send ReadyForQuery after exception (only if last statement)
            if send_ready:
                await self.send_ready_for_query()

    async def send_query_result(
        self,
        result: dict[str, Any],
        send_ready: bool = True,
        send_row_description: bool = True,
        result_formats: list[int] = None,
    ):
        """
        Send query results from IRIS execution.

        Args:
            result: Query result dictionary from IRIS executor
            send_ready: If True, send ReadyForQuery (Simple Query Protocol).
                       If False, omit ReadyForQuery (Extended Protocol - Sync will send it)
            send_row_description: If True, send RowDescription before DataRows.
                                 If False, skip RowDescription (already sent in Describe for Extended Protocol)
            result_formats: Format codes from Bind message (0=text, 1=binary).
                           Passed to send_row_description to ensure format_code matches DataRow encoding.
        """
        try:
            rows = result.get("rows", [])
            columns = result.get("columns", [])
            # CRITICAL: Use command_tag (from iris_executor) with fallback to command
            command = result.get("command_tag", result.get("command", "SELECT"))
            row_count = result.get("row_count", 0)

            logger.info(
                "Sending query result - DETAILED DEBUG",
                connection_id=self.connection_id,
                command=command,
                row_count=row_count,
                column_count=len(columns),
                has_rows=len(rows) > 0,
                rows_is_truthy=bool(rows),
                columns_is_truthy=bool(columns),
                send_ready=send_ready,
                rows_sample=rows[:1] if rows else None,
                columns_sample=columns[:3] if columns else None,
            )

            # Send RowDescription for SELECT queries (ALWAYS, even if empty result set)
            # PostgreSQL protocol requires RowDescription for all SELECT queries
            if columns and send_row_description:
                logger.info(
                    "🔵 STEP 1: About to send RowDescription",
                    connection_id=self.connection_id,
                    column_count=len(columns),
                    row_count=len(rows),
                    result_formats=result_formats,
                )
                await self.send_row_description(columns, result_formats=result_formats, rows=rows)
                logger.info("🔵 STEP 2: RowDescription sent", connection_id=self.connection_id)
            elif columns and not send_row_description:
                logger.info(
                    "🔵 STEP 1 (SKIPPED): RowDescription already sent by Describe",
                    connection_id=self.connection_id,
                    column_count=len(columns),
                )

            # Send DataRows if we have any rows
            if rows and columns:
                logger.info(
                    "🔵 STEP 2: About to send DataRows",
                    connection_id=self.connection_id,
                    row_count=len(rows),
                )
                await self.send_data_rows_with_backpressure(rows, columns)
                logger.info("🔵 STEP 3: DataRows sent", connection_id=self.connection_id)

            # Send CommandComplete
            if command.upper() == "SELECT":
                tag = f"SELECT {row_count}\x00".encode()
            else:
                tag = f"{command} {row_count}\x00".encode()

            cmd_complete_length = 4 + len(tag)
            cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag
            logger.info(
                "🔵 STEP 4: About to send CommandComplete",
                connection_id=self.connection_id,
                tag=tag.decode("utf-8", errors="replace").rstrip("\x00"),
            )
            self.writer.write(cmd_complete)
            await self.writer.drain()
            logger.info(
                "🔵 STEP 5: CommandComplete sent and drained", connection_id=self.connection_id
            )

            # CRITICAL: For Extended Protocol, give time for Sync message to arrive
            # Without this, rapid return to message loop can miss the Sync message
            if not send_ready:
                import asyncio

                await asyncio.sleep(0.001)  # 1ms grace period for Sync to arrive

            # Send ReadyForQuery ONLY for Simple Query Protocol
            # Extended Protocol (Parse/Bind/Execute/Sync) will send it in Sync handler
            if send_ready:
                await self.send_ready_for_query()

            logger.info(
                "Query result sent",
                connection_id=self.connection_id,
                command=command,
                row_count=row_count,
                column_count=len(columns),
            )

        except Exception as e:
            logger.error(
                "Failed to send query result", connection_id=self.connection_id, error=str(e)
            )
            raise

    async def send_row_description(
        self,
        columns: list[dict[str, Any]],
        result_formats: list[int] = None,
        rows: list[list[Any]] = None,
    ):
        """Send RowDescription message for query columns

        Args:
            columns: List of column metadata dictionaries
            result_formats: Optional list of format codes from Bind message
                           0 = text format, 1 = binary format
                           If None or empty, defaults to text format (0) for all columns
            rows: Optional sample data rows to ensure field count consistency
        """
        field_count = len(columns)

        if rows and len(rows) > 0:
            actual_count = len(rows[0])
            if field_count != actual_count:
                logger.warning(
                    "🔴 Column count mismatch in RowDescription",
                    description_count=field_count,
                    actual_data_count=actual_count,
                    connection_id=self.connection_id,
                )
                field_count = actual_count

        logger.info(
            "🔴 SEND_ROW_DESCRIPTION CALLED",
            field_count=field_count,
            columns=columns[:2],
            result_formats=result_formats,
        )

        # Ensure field_count is valid
        if field_count < 0 or field_count > 65535:
            raise ValueError(f"Invalid field count: {field_count}")

        row_desc_data = struct.pack(
            "!cIH", MSG_ROW_DESCRIPTION, 0, field_count
        )  # Length will be updated

        # Get type mappings from IRIS executor (fallback if columns don't have OID info)
        type_mappings = self.iris_executor.get_iris_type_mapping()

        # Normalize result_formats for easier access
        if result_formats is None:
            result_formats = []

        for i in range(field_count):
            if i < len(columns):
                col = columns[i]
            else:
                # Padding for mismatch - ensure protocol consistency even if metadata is missing
                col = {
                    "name": f"column{i + 1}",
                    "type_oid": 25,
                    "type_size": -1,
                    "type_modifier": -1,
                }

            name = col.get("name", "unknown")
            # CRITICAL: Lowercase column names for PostgreSQL compatibility
            # PostgreSQL clients expect lowercase unless explicitly quoted
            if isinstance(name, str):
                name = name.lower()

            # CRITICAL FIX: Use type_oid, type_size, type_modifier if already present
            # (IRIS executor may have already done the type mapping)
            if "type_oid" in col:
                # Use pre-computed PostgreSQL type info from executor
                type_oid = col["type_oid"]
                # Handle None values from executor - struct.pack requires integers
                type_size = col.get("type_size") or -1
                type_modifier = col.get("type_modifier") or -1

                logger.info(
                    "🟢 Using pre-computed type info from executor",
                    name=name,
                    type_oid=type_oid,
                    type_size=type_size,
                )
            else:
                # Fallback: Map IRIS type to PostgreSQL type
                iris_type = col.get("type", "VARCHAR").upper()
                pg_type = type_mappings.get(iris_type, type_mappings["VARCHAR"])

                type_oid = pg_type["oid"]
                type_size = pg_type["typlen"]
                type_modifier = -1

                logger.warning(
                    "⚠️ Falling back to type mapping",
                    name=name,
                    iris_type=iris_type,
                    mapped_oid=type_oid,
                )

            # CRITICAL FIX: Determine format_code from result_formats (from Bind message)
            # PostgreSQL protocol: format_code MUST match the format used in DataRow
            # 0 = text format, 1 = binary format
            if not result_formats:
                # No format codes specified - default to text (0) for all columns
                format_code = 0
            elif len(result_formats) == 1:
                # Single format code applies to all columns
                format_code = result_formats[0]
            elif i < len(result_formats):
                # Per-column format code
                format_code = result_formats[i]
            else:
                # Fallback to text if not enough format codes
                format_code = 0

            logger.info(
                "🔵 Format code determined",
                column_index=i,
                column_name=name,
                format_code=format_code,
                format_type="binary" if format_code == 1 else "text",
            )

            field_name = name.encode("utf-8") + b"\x00"
            field_info = struct.pack(
                "!IHIhiH",
                0,  # table_oid
                0,  # column_attr_number
                type_oid,  # type_oid ('I' - 32-bit unsigned)
                type_size,  # type_size ('h' - 16-bit signed, allows -1)
                type_modifier,  # type_modifier ('i' - 32-bit signed)
                format_code,
            )  # format_code ('H' - 16-bit unsigned)

            logger.info(
                "🔵 Field info packed",
                name=name,
                field_name_length=len(field_name),
                field_info_length=len(field_info),
                field_info_hex=field_info.hex(),
            )

            row_desc_data += field_name + field_info

        # Update length
        total_length = len(row_desc_data) - 1  # Subtract the message type byte
        row_desc_data = row_desc_data[:1] + struct.pack("!I", total_length) + row_desc_data[5:]

        logger.info(
            "📤 Sending RowDescription message",
            total_message_length=len(row_desc_data),
            message_hex_preview=row_desc_data[:30].hex(),
            field_count=field_count,
        )

        logger.info(
            "📤 STEP A: Writing RowDescription to stream",
            connection_id=self.connection_id,
            bytes_to_write=len(row_desc_data),
        )
        self.writer.write(row_desc_data)
        logger.info(
            "📤 STEP B: RowDescription written, about to drain", connection_id=self.connection_id
        )
        await self.writer.drain()
        logger.info(
            "📤 STEP C: RowDescription drained - message sent to client",
            connection_id=self.connection_id,
        )

    async def send_data_row(self, row: list[Any], columns: list[dict[str, Any]]):
        """Send DataRow message for a single row"""
        field_count = len(columns)
        logger.debug("Data row", field_count=field_count, row=row)

        # Ensure field_count is valid
        if field_count < 0 or field_count > 65535:
            raise ValueError(f"Invalid field count: {field_count}")

        data_row_data = struct.pack("!cIH", MSG_DATA_ROW, 0, field_count)  # Length will be updated

        for i, col in enumerate(columns):
            # Row is a list of values, access by index
            value = row[i] if i < len(row) else None

            # DEBUG: Log value being sent for each column
            col_name = col.get("name", "unknown")
            logger.info(
                f"📦 DataRow column {i}: name='{col_name}' value='{value}' type={type(value).__name__}"
            )

            if value is None:
                # NULL value
                data_row_data += struct.pack("!I", 0xFFFFFFFF)  # -1 indicates NULL
            else:
                # Determine format code for this column
                # If result_formats is empty, default to text (0)
                # If single format, apply to all columns
                # If per-column formats, use specific format for this column
                result_formats = getattr(self, "_current_result_formats", [])
                if not result_formats:
                    format_code = 0  # Default to text
                elif len(result_formats) == 1:
                    format_code = result_formats[0]  # Single format for all columns
                elif i < len(result_formats):
                    format_code = result_formats[i]  # Per-column format
                else:
                    format_code = 0  # Fallback to text

                if format_code == 0:
                    # Text format - use PostgreSQL text conventions
                    type_oid = col.get("type_oid", 25)

                    # Special handling for boolean - PostgreSQL uses 't'/'f', not 'True'/'False' or '1'/'0'
                    if type_oid == 16:  # BOOL
                        if value in (1, "1", True, "t", "true", "TRUE"):
                            value_str = "t"
                        elif value in (0, "0", False, "f", "false", "FALSE"):
                            value_str = "f"
                        else:
                            value_str = "t" if value else "f"
                    else:
                        value_str = str(value)

                    value_bytes = value_str.encode("utf-8")
                    data_row_data += struct.pack("!I", len(value_bytes)) + value_bytes
                elif format_code == 1:
                    # Binary format - encode based on PostgreSQL type OID
                    type_oid = col.get("type_oid", 25)  # Default to TEXT (25)

                    try:
                        if type_oid == 23:  # INT4
                            binary_data = struct.pack("!i", int(value))
                        elif type_oid == 21:  # INT2 (smallint)
                            binary_data = struct.pack("!h", int(value))
                        elif type_oid == 20:  # INT8 (bigint)
                            binary_data = struct.pack("!q", int(value))
                        elif type_oid == 700:  # FLOAT4
                            binary_data = struct.pack("!f", float(value))
                        elif type_oid == 701:  # FLOAT8 (double)
                            binary_data = struct.pack("!d", float(value))
                        elif type_oid == 26:  # OID (4-byte unsigned int)
                            binary_data = struct.pack("!I", int(value))
                        elif type_oid == 19:  # NAME (63-byte string, encode as text)
                            binary_data = str(value).encode("utf-8")
                        elif type_oid == 16:  # BOOL
                            binary_data = struct.pack("!?", bool(value))
                        elif type_oid == 1082:  # DATE
                            # PostgreSQL DATE binary format: 4-byte signed integer (days since 2000-01-01)
                            # Value should already be converted from IRIS format in iris_executor.py
                            binary_data = struct.pack("!i", int(value))
                        elif type_oid == 1114:  # TIMESTAMP (without timezone)
                            # PostgreSQL TIMESTAMP binary format: 8-byte signed integer (microseconds since 2000-01-01 00:00:00)
                            # IRIS returns timestamps as strings like '2025-11-14 20:57:57'
                            import datetime

                            # Parse IRIS timestamp string
                            if isinstance(value, str):
                                timestamp_obj = datetime.datetime.strptime(
                                    value, "%Y-%m-%d %H:%M:%S"
                                )
                            elif isinstance(value, datetime.datetime):
                                timestamp_obj = value
                            else:
                                raise ValueError(f"Unexpected timestamp value type: {type(value)}")

                            # PostgreSQL J2000 epoch: 2000-01-01 00:00:00
                            PG_EPOCH = datetime.datetime(2000, 1, 1, 0, 0, 0)

                            # Calculate microseconds since J2000 epoch
                            delta = timestamp_obj - PG_EPOCH
                            microseconds = int(delta.total_seconds() * 1_000_000)

                            # Pack as 8-byte signed integer
                            binary_data = struct.pack("!q", microseconds)
                        elif type_oid == 1700:  # NUMERIC/DECIMAL
                            # PostgreSQL NUMERIC binary format:
                            # https://github.com/postgres/postgres/blob/master/src/backend/utils/adt/numeric.c
                            # struct NumericData {
                            #     int16 ndigits;  // number of base-10000 digits
                            #     int16 weight;   // weight of first digit (10000^weight)
                            #     int16 sign;     // 0x0000=positive, 0x4000=negative, 0xC000=NaN
                            #     int16 dscale;   // display scale (digits after decimal point)
                            #     int16 digits[]; // base-10000 digits
                            # }
                            from decimal import Decimal

                            if isinstance(value, Decimal):
                                # Convert Decimal to PostgreSQL binary NUMERIC format
                                dec_str = str(value)
                                is_negative = dec_str.startswith("-")
                                dec_str = dec_str.lstrip("-")

                                # Split into integer and fractional parts
                                if "." in dec_str:
                                    int_part, frac_part = dec_str.split(".")
                                    dscale = len(frac_part)
                                else:
                                    int_part = dec_str
                                    frac_part = ""
                                    dscale = 0

                                # PostgreSQL NUMERIC splits digits at decimal point
                                # Integer part: pad left, fractional part: pad right
                                # Example: 3.14 → int_part='3' frac_part='14'
                                #   int groups: ['0003'] → [3]
                                #   frac groups: ['1400'] → [1400]
                                #   combined: [3, 1400] with weight=0

                                # Process integer part (pad on LEFT to make groups of 4)
                                if int_part == "0" or not int_part:
                                    int_groups = []
                                    int_weight = -1
                                else:
                                    int_padding = (4 - len(int_part) % 4) % 4
                                    int_padded = "0" * int_padding + int_part
                                    int_groups = []
                                    for i in range(0, len(int_padded), 4):
                                        int_groups.append(int(int_padded[i : i + 4]))
                                    # Remove leading zeros
                                    while int_groups and int_groups[0] == 0:
                                        int_groups.pop(0)
                                    int_weight = len(int_groups) - 1

                                # Process fractional part (pad on RIGHT to make groups of 4)
                                if frac_part:
                                    frac_padding = (4 - len(frac_part) % 4) % 4
                                    frac_padded = frac_part + "0" * frac_padding
                                    frac_groups = []
                                    for i in range(0, len(frac_padded), 4):
                                        frac_groups.append(int(frac_padded[i : i + 4]))
                                    # Remove trailing zeros
                                    while frac_groups and frac_groups[-1] == 0:
                                        frac_groups.pop()
                                else:
                                    frac_groups = []

                                # Combine integer and fractional parts
                                digits_10000 = int_groups + frac_groups
                                weight = int_weight if int_groups else -len(frac_groups)

                                ndigits = len(digits_10000)
                                sign = 0x4000 if is_negative else 0x0000

                                # Pack into PostgreSQL binary format
                                binary_data = struct.pack("!hhhh", ndigits, weight, sign, dscale)
                                for digit in digits_10000:
                                    binary_data += struct.pack("!H", digit)
                            else:
                                # Fallback for non-Decimal values
                                binary_data = str(value).encode("utf-8")
                        else:
                            # Fallback to text for unknown types
                            binary_data = str(value).encode("utf-8")

                        data_row_data += struct.pack("!I", len(binary_data)) + binary_data

                        logger.debug(
                            "Binary encoded column",
                            column_index=i,
                            type_oid=type_oid,
                            value=value,
                            binary_length=len(binary_data),
                        )

                    except (ValueError, struct.error) as e:
                        # If binary encoding fails, fallback to text
                        logger.warning(
                            "Binary encoding failed, falling back to text",
                            column_index=i,
                            type_oid=type_oid,
                            value=value,
                            error=str(e),
                        )
                        value_str = str(value)
                        value_bytes = value_str.encode("utf-8")
                        data_row_data += struct.pack("!I", len(value_bytes)) + value_bytes
                else:
                    # Unknown format code - default to text
                    logger.warning(
                        "Unknown format code, defaulting to text",
                        format_code=format_code,
                        column_index=i,
                    )
                    value_str = str(value)
                    value_bytes = value_str.encode("utf-8")
                    data_row_data += struct.pack("!I", len(value_bytes)) + value_bytes

        # Update length
        total_length = len(data_row_data) - 1  # Subtract the message type byte
        data_row_data = data_row_data[:1] + struct.pack("!I", total_length) + data_row_data[5:]

        # DEBUG: Hex dump of DataRow message (first 200 bytes)
        hex_preview = data_row_data[:200].hex()
        logger.info(f"🔍 DataRow hex dump (first 200 bytes): {hex_preview}")
        logger.info("🔍 DataRow message structure:")
        logger.info(f"   - Message type: {data_row_data[0:1].hex()} ('D')")
        logger.info(f"   - Total length: {struct.unpack('!I', data_row_data[1:5])[0]} bytes")
        logger.info(f"   - Field count: {struct.unpack('!H', data_row_data[5:7])[0]}")

        self.writer.write(data_row_data)
        await self.writer.drain()

    async def send_simple_query_response(self):
        """Send a simple 'SELECT 1' response for P0 testing (legacy)"""
        # RowDescription: T + length + field_count + field_info
        field_name = b"?column?\x00"
        field_info = struct.pack("!IHIHiH", 0, 0, 23, 4, -1, 0)  # int4 type, use 'i' for signed int
        row_desc_length = 4 + 2 + len(field_name) + len(field_info)
        row_desc = (
            struct.pack("!cIH", MSG_ROW_DESCRIPTION, row_desc_length, 1) + field_name + field_info
        )

        # DataRow: D + length + field_count + field_data
        field_value = b"1"
        field_length = struct.pack("!I", len(field_value))
        data_row_length = 4 + 2 + 4 + len(field_value)
        data_row = (
            struct.pack("!cIH", MSG_DATA_ROW, data_row_length, 1) + field_length + field_value
        )

        # CommandComplete: C + length + tag
        tag = b"SELECT 1\x00"
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        # Send all messages
        self.writer.write(row_desc + data_row + cmd_complete)
        await self.writer.drain()

        # Send ReadyForQuery
        await self.send_ready_for_query()

        logger.info("Simple query response sent", connection_id=self.connection_id)

    async def send_data_rows_with_backpressure(
        self, rows: list[list[Any]], columns: list[dict[str, Any]]
    ):
        """
        P6: Send DataRows with back-pressure control for large result sets

        Implements streaming with memory and network back-pressure to handle
        large result sets efficiently without overwhelming client or server.
        """
        try:
            total_rows = len(rows)
            pending_bytes = 0

            logger.info(
                "Sending large result set",
                connection_id=self.connection_id,
                total_rows=total_rows,
                batch_size=self.result_batch_size,
            )

            for i, row in enumerate(rows):
                # Send individual DataRow
                await self.send_data_row(row, columns)

                # Estimate bytes sent (rough calculation)
                # Row is a list of values, not a dict
                estimated_row_bytes = sum(
                    len(str(row[i] if i < len(row) else "")) + 8 for i in range(len(columns))
                )
                pending_bytes += estimated_row_bytes

                # Apply back-pressure controls
                if (i + 1) % self.result_batch_size == 0 or pending_bytes > self.max_pending_bytes:
                    # Force drain to apply network back-pressure
                    await self.writer.drain()
                    pending_bytes = 0

                    logger.debug(
                        "Result set batch sent",
                        connection_id=self.connection_id,
                        rows_sent=i + 1,
                        total_rows=total_rows,
                        progress_pct=round((i + 1) / total_rows * 100, 1),
                    )

                    # Small yield to prevent CPU blocking on huge result sets
                    if (i + 1) % (self.result_batch_size * 10) == 0:
                        await asyncio.sleep(0.001)  # 1ms yield for very large sets

            # Final drain
            await self.writer.drain()

            logger.info(
                "Large result set transmission completed",
                connection_id=self.connection_id,
                total_rows=total_rows,
            )

        except Exception as e:
            logger.error(
                "Large result set transmission failed",
                connection_id=self.connection_id,
                error=str(e),
                rows_attempted=total_rows,
            )
            raise

    async def send_transaction_response(self, command: str, send_ready: bool = True):
        """Send response for transaction commands (BEGIN, COMMIT, ROLLBACK)

        Args:
            command: Transaction command (BEGIN, COMMIT, ROLLBACK)
            send_ready: If True, send ReadyForQuery after response
        """
        # CommandComplete: C + length + tag
        tag = f"{command}\x00".encode()
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        # Send message
        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Update transaction status
        if command == "BEGIN":
            self.transaction_status = STATUS_IN_TRANSACTION
        else:  # COMMIT or ROLLBACK
            self.transaction_status = STATUS_IDLE

        # Send ReadyForQuery with updated status (only if requested)
        if send_ready:
            await self.send_ready_for_query()

        logger.info(
            "Transaction response sent",
            connection_id=self.connection_id,
            command=command,
            status=self.transaction_status.decode(),
        )

    async def send_deallocate_response(self, command: str, send_ready: bool = True):
        """Send response for DEALLOCATE commands (PostgreSQL prepared statement cleanup)

        IRIS doesn't support DEALLOCATE, so we silently succeed.
        This prevents psycopg from failing during connection cleanup.

        Args:
            command: DEALLOCATE command string
            send_ready: If True, send ReadyForQuery after response
        """
        # CommandComplete: C + length + tag
        # Use "DEALLOCATE 0" to indicate success (0 statements deallocated)
        tag = b"DEALLOCATE 0\x00"
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        # Send message
        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Send ReadyForQuery (only if requested)
        if send_ready:
            await self.send_ready_for_query()

        logger.debug(
            "DEALLOCATE response sent (silently succeeded)",
            connection_id=self.connection_id,
            command=command,
        )

    async def handle_set_command(self, command: str, send_ready: bool = True):
        """Handle PostgreSQL SET and RESET commands

        PostgreSQL clients send SET commands to configure runtime parameters.
        IRIS uses different syntax (SET OPTION parameter = value) vs PostgreSQL (SET parameter = value).

        We intercept common PostgreSQL SET/RESET commands and silently succeed to maintain compatibility.

        Common PostgreSQL SET commands from drivers:
        - SET EXTRA_FLOAT_DIGITS = X (JDBC driver initialization - CRITICAL blocker)
        - SET application_name = 'X' (driver identification)
        - SET client_encoding = 'X' (character encoding)
        - SET DateStyle = 'X' (date format preference)
        - SET TimeZone = 'X' (timezone configuration)
        - RESET ALL (asyncpg connection reset)
        - RESET parameter (reset specific parameter)
        """
        try:
            # Parse SET/RESET command to extract parameter name
            # Format: "SET parameter = value" or "SET parameter TO value" or "RESET parameter" or "RESET ALL"
            command_clean = command.strip()

            # DEBUG: Log the incoming command
            logger.warning(
                f"🔍 DEBUG handle_set_command called with: '{command_clean}' (length={len(command_clean)})",
                connection_id=self.connection_id,
            )

            # Extract parameter name (everything between SET/RESET and = or TO)
            import re

            # Try SET pattern first
            match = re.match(r"SET\s+(\w+)(?:\s+(?:=|TO)\s+(.+))?", command_clean, re.IGNORECASE)
            logger.warning(f"🔍 DEBUG SET pattern match: {match}", connection_id=self.connection_id)

            # If no SET match, try RESET pattern
            if not match:
                match = re.match(r"RESET\s+(\w+|\*)", command_clean, re.IGNORECASE)
                logger.warning(
                    f"🔍 DEBUG RESET pattern match: {match}", connection_id=self.connection_id
                )
                if match:
                    # RESET command - treat as setting to default
                    param_name = match.group(1)
                    param_value = "DEFAULT"
                    logger.warning(
                        f"🔍 DEBUG RESET matched: param_name='{param_name}', param_value='{param_value}'",
                        connection_id=self.connection_id,
                    )
                else:
                    param_name = None
                    param_value = None
                    logger.warning(
                        "🔍 DEBUG No match for RESET pattern!", connection_id=self.connection_id
                    )
            else:
                # SET command
                param_name = match.group(1)
                param_value = match.group(2) if match.group(2) else None
                logger.warning(
                    f"🔍 DEBUG SET matched: param_name='{param_name}', param_value='{param_value}'",
                    connection_id=self.connection_id,
                )

            if param_name:
                logger.info(
                    "PostgreSQL SET/RESET command intercepted",
                    connection_id=self.connection_id,
                    parameter=param_name,
                    value=(
                        param_value[:50] if param_value and len(param_value) > 50 else param_value
                    ),
                )

                # Send success response for all SET/RESET commands
                # PostgreSQL clients expect success for runtime parameter configuration
                await self.send_set_response(param_name, param_value, send_ready=send_ready)
            else:
                # Malformed SET/RESET command - send error
                await self.send_error_response(
                    "ERROR",
                    "42601",
                    "syntax_error",
                    f"Invalid SET/RESET command syntax: {command_clean}",
                )
                if send_ready:
                    await self.send_ready_for_query()

        except Exception as e:
            logger.error(
                "SET command handling failed",
                connection_id=self.connection_id,
                error=str(e),
                command=command,
            )
            await self.send_error_response(
                "ERROR", "08000", "connection_exception", f"SET command processing failed: {e}"
            )
            if send_ready:
                await self.send_ready_for_query()

    async def send_set_response(
        self, param_name: str, param_value: str = None, send_ready: bool = True
    ):
        """Send response for SET commands (PostgreSQL runtime parameter configuration)

        IRIS uses different SET syntax, so we silently succeed for PostgreSQL SET commands.
        This is critical for JDBC driver compatibility (sends SET EXTRA_FLOAT_DIGITS during connection init).

        Args:
            param_name: Parameter name
            param_value: Parameter value
            send_ready: If True, send ReadyForQuery after response
        """
        # CommandComplete: C + length + tag
        # Use "SET" to indicate success
        tag = b"SET\x00"
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        # Send message
        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Send ReadyForQuery (only if requested)
        if send_ready:
            await self.send_ready_for_query()

        logger.debug(
            "SET response sent (silently succeeded)",
            connection_id=self.connection_id,
            parameter=param_name,
            value=param_value,
        )

    async def send_postgresql_command_response(self, command: str, send_ready: bool = True):
        """Send response for PostgreSQL-specific commands not supported by IRIS

        Commands handled:
        - UNLISTEN * (asyncpg connection reset)
        - CLOSE ALL (asyncpg connection reset)
        - RESET ALL (asyncpg connection reset, already handled by handle_set_command)

        Args:
            command: PostgreSQL command string
            send_ready: If True, send ReadyForQuery after response
        """
        # Extract command type for response tag
        command_type = command.split()[0].upper()

        # CommandComplete: C + length + tag
        tag = f"{command_type}\x00".encode()
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        # Send message
        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Send ReadyForQuery (only if requested)
        if send_ready:
            await self.send_ready_for_query()

        logger.debug(
            "PostgreSQL command response sent (silently succeeded)",
            connection_id=self.connection_id,
            command=command_type,
        )

    async def send_set_response_extended_protocol(self):
        """Send response for SET commands in Extended Protocol (Parse/Bind/Execute/Sync)

        CRITICAL: Extended Protocol does NOT send ReadyForQuery in Execute handler.
        The Sync message handler will send ReadyForQuery after all Execute messages.

        This is essential for JDBC driver compatibility (SET EXTRA_FLOAT_DIGITS during connection init).
        """
        # Send CommandComplete: C + length + tag
        tag = b"SET\x00"
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        self.writer.write(cmd_complete)
        await self.writer.drain()

        # DO NOT send ReadyForQuery here - Extended Protocol sends it in Sync handler

        logger.debug(
            "SET response sent (Extended Protocol, no ReadyForQuery)",
            connection_id=self.connection_id,
        )

    async def send_transaction_response_extended_protocol(self, command: str):
        """Send response for transaction commands in Extended Protocol (Parse/Bind/Execute/Sync)

        CRITICAL: Extended Protocol does NOT send ReadyForQuery in Execute handler.
        The Sync message handler will send ReadyForQuery after all Execute messages.

        This fixes JDBC transaction tests by handling BEGIN/COMMIT/ROLLBACK via Extended Protocol.
        """
        # Send CommandComplete: C + length + tag
        tag = f"{command}\x00".encode()
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Update transaction status
        if command == "BEGIN":
            self.transaction_status = STATUS_IN_TRANSACTION
        else:  # COMMIT or ROLLBACK
            self.transaction_status = STATUS_IDLE

        # DO NOT send ReadyForQuery here - Extended Protocol sends it in Sync handler

        logger.debug(
            "Transaction response sent (Extended Protocol, no ReadyForQuery)",
            connection_id=self.connection_id,
            command=command,
            status=self.transaction_status.decode(),
        )

    async def send_empty_pg_catalog_result(self, send_ready: bool = True):
        """Send empty result set for pg_type/pg_catalog queries

        This method intercepts asyncpg's type introspection queries to prevent
        infinite recursion. When asyncpg sees OID 0 (unspecified) in ParameterDescription,
        it queries pg_type catalog using prepared statements, which causes recursion.

        By returning an empty result set, we break the recursion loop and allow
        asyncpg to fall back to its default type handling (which uses binary encoding).

        Args:
            send_ready: If True, send ReadyForQuery after response

        Protocol Response Sequence:
        1. RowDescription (T) with 0 fields
        2. CommandComplete (C) with "SELECT 0"
        3. ReadyForQuery (Z) - only if send_ready=True
        """
        # Send RowDescription with 0 fields (indicates empty result set)
        row_desc_data = struct.pack("!cIH", MSG_ROW_DESCRIPTION, 4 + 2, 0)  # 0 fields
        self.writer.write(row_desc_data)
        await self.writer.drain()

        # Send CommandComplete: SELECT 0 (no rows returned)
        tag = b"SELECT 0\x00"
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag
        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Send ReadyForQuery (only if requested)
        if send_ready:
            await self.send_ready_for_query()

        logger.info(
            "Sent empty pg_catalog result to prevent recursion", connection_id=self.connection_id
        )

    # P2: Extended Protocol Message Handlers

    async def flush_batch(self):
        """
        Execute any buffered parameters using executemany() for high performance.
        This collapses a sequence of Bind/Execute messages into one IRIS call.
        """
        if not self.batch_params:
            return

        params_to_exec = self.batch_params
        sql_to_exec = self.batch_sql

        # Clear batch state
        self.batch_sql = None
        self.batch_params = []
        self.batch_statement_name = None
        self.batch_portal_name = None
        self.batch_max_rows = 0

        logger.debug(
            "🚀 FLUSHING BATCH",
            connection_id=self.connection_id,
            batch_size=len(params_to_exec),
            sql_preview=sql_to_exec[:100] if sql_to_exec else "None",
        )

        try:
            if not sql_to_exec:
                return

            await self.iris_executor.execute_many(
                sql_to_exec, params_to_exec, session_id=self.connection_id
            )
        except Exception as e:
            logger.error("Batch flush failed", connection_id=self.connection_id, error=str(e))
            await self.send_error_response("ERROR", "XX000", "internal_error", f"Batch failed: {e}")

    async def handle_parse_message(self, body: bytes):
        """
        P2: Handle Parse message for prepared statements

        Parse message format:
        - statement_name (null-terminated string)
        - query (null-terminated string)
        - num_param_types (Int16)
        - param_types (Int32 array)
        """
        try:
            pos = 0

            # Parse statement name
            name_end = body.find(b"\x00", pos)
            if name_end == -1:
                raise ValueError("Invalid Parse message: missing statement name terminator")
            statement_name = body[pos:name_end].decode("utf-8")
            pos = name_end + 1

            # Parse query
            query_end = body.find(b"\x00", pos)
            if query_end == -1:
                raise ValueError("Invalid Parse message: missing query terminator")
            query = body[pos:query_end].decode("utf-8")
            pos = query_end + 1

            # CRITICAL: Translate PostgreSQL $1, $2, $3 parameters to IRIS ? syntax
            # This must happen BEFORE translation to avoid IRIS SQL errors with $1 syntax
            query = self.translate_postgres_parameters(query)

            # Handle empty queries (JDBC connection validation)
            # JDBC driver sends empty Parse/Bind/Execute after SET commands for connection validation
            if not query or query.strip() == "":
                logger.info(
                    "Empty query in Parse phase - JDBC connection validation",
                    connection_id=self.connection_id,
                    statement_name=statement_name,
                )

                # Store empty prepared statement marker
                self.prepared_statements[statement_name] = {
                    "original_query": "",
                    "translated_query": "",
                    "param_types": [],
                    "translation_metadata": {
                        "constructs_translated": 0,
                        "translation_time_ms": 0.0,
                        "cache_hit": False,
                        "warnings": [],
                        "is_empty_query": True,  # Marker for Execute phase
                    },
                }

                # Send ParseComplete response
                await self.send_parse_complete()
                return

            # CRITICAL: Intercept pg_type/pg_catalog queries in Extended Protocol
            # asyncpg uses prepared statements to query pg_type for type introspection,
            # which causes infinite recursion when we send OID 0 in ParameterDescription.
            # Solution: Mark these queries and return empty results in Execute phase.
            query_upper = query.upper().strip().rstrip(";")
            if "pg_type" in query_upper or "pg_catalog" in query_upper:
                logger.info(
                    "Intercepting pg_type/pg_catalog query in Parse phase",
                    connection_id=self.connection_id,
                    statement_name=statement_name,
                    query_preview=query[:100],
                )

                # Store a marker prepared statement (will return empty result in Execute)
                self.prepared_statements[statement_name] = {
                    "original_query": query,
                    "translated_query": query,
                    "param_types": [],
                    "translation_metadata": {
                        "constructs_translated": 0,
                        "translation_time_ms": 0.0,
                        "cache_hit": False,
                        "warnings": [],
                        "is_pg_catalog_query": True,  # Marker for Execute phase
                    },
                }

                # Send ParseComplete response
                await self.send_parse_complete()
                return

            # Handle PostgreSQL SET commands in Parse phase
            # JDBC driver uses Extended Protocol, so we must intercept SET during Parse
            # to prevent translation failures and empty query storage
            query_upper = query.upper().strip().rstrip(";")
            if query_upper.startswith("SET "):
                logger.info(
                    "PostgreSQL SET command intercepted in Parse phase",
                    connection_id=self.connection_id,
                    statement_name=statement_name,
                    query=query[:100],
                )

                # Store a marker prepared statement (will be handled in Execute)
                self.prepared_statements[statement_name] = {
                    "original_query": query,
                    "translated_query": query,  # Keep as-is for Execute handler
                    "param_types": [],
                    "translation_metadata": {
                        "constructs_translated": 0,
                        "translation_time_ms": 0.0,
                        "cache_hit": False,
                        "warnings": [],
                        "is_set_command": True,  # Marker for Execute phase
                    },
                }

                # Send ParseComplete response
                await self.send_parse_complete()
                return

            # Handle PostgreSQL transaction commands in Parse phase (Feature 022)
            # JDBC driver uses Extended Protocol for transactions (setAutoCommit(false) → BEGIN)
            # CRITICAL: Must intercept BEGIN/COMMIT/ROLLBACK during Parse, not Execute
            if query_upper in ("BEGIN", "START TRANSACTION", "BEGIN WORK", "BEGIN TRANSACTION"):
                logger.info(
                    "PostgreSQL transaction command intercepted in Parse phase",
                    connection_id=self.connection_id,
                    statement_name=statement_name,
                    command="BEGIN",
                )

                # Store a marker prepared statement (will be handled in Execute)
                self.prepared_statements[statement_name] = {
                    "original_query": query,
                    "translated_query": query,
                    "param_types": [],
                    "translation_metadata": {
                        "constructs_translated": 0,
                        "translation_time_ms": 0.0,
                        "cache_hit": False,
                        "warnings": [],
                        "is_transaction_command": True,
                        "transaction_type": "BEGIN",
                    },
                }

                # Send ParseComplete response
                await self.send_parse_complete()
                return

            if query_upper in ("COMMIT", "COMMIT WORK", "COMMIT TRANSACTION", "END"):
                logger.info(
                    "PostgreSQL transaction command intercepted in Parse phase",
                    connection_id=self.connection_id,
                    statement_name=statement_name,
                    command="COMMIT",
                )

                # Store a marker prepared statement (will be handled in Execute)
                self.prepared_statements[statement_name] = {
                    "original_query": query,
                    "translated_query": query,
                    "param_types": [],
                    "translation_metadata": {
                        "constructs_translated": 0,
                        "translation_time_ms": 0.0,
                        "cache_hit": False,
                        "warnings": [],
                        "is_transaction_command": True,
                        "transaction_type": "COMMIT",
                    },
                }

                # Send ParseComplete response
                await self.send_parse_complete()
                return

            if query_upper in ("ROLLBACK", "ROLLBACK WORK", "ROLLBACK TRANSACTION"):
                logger.info(
                    "PostgreSQL transaction command intercepted in Parse phase",
                    connection_id=self.connection_id,
                    statement_name=statement_name,
                    command="ROLLBACK",
                )

                # Store a marker prepared statement (will be handled in Execute)
                self.prepared_statements[statement_name] = {
                    "original_query": query,
                    "translated_query": query,
                    "param_types": [],
                    "translation_metadata": {
                        "constructs_translated": 0,
                        "translation_time_ms": 0.0,
                        "cache_hit": False,
                        "warnings": [],
                        "is_transaction_command": True,
                        "transaction_type": "ROLLBACK",
                    },
                }

                # Send ParseComplete response
                await self.send_parse_complete()
                return

            # Parse parameter types count
            if pos + 2 > len(body):
                raise ValueError("Invalid Parse message: missing parameter count")
            num_params = struct.unpack("!H", body[pos : pos + 2])[0]
            pos += 2

            # Parse parameter types
            param_types = []
            for i in range(num_params):
                if pos + 4 > len(body):
                    raise ValueError(f"Invalid Parse message: missing parameter type {i}")
                param_type = struct.unpack("!I", body[pos : pos + 4])[0]
                param_types.append(param_type)
                pos += 4

            # Translate SQL for prepared statement FIRST
            # We need the translated SQL to infer parameter types from CAST() expressions
            translation_result = await self.translate_sql(
                query, session_id=f"conn_{self.connection_id}_stmt_{statement_name}"
            )

            # CRITICAL FIX (Feature 031 - Prisma Support):
            # Infer parameter types when:
            # 1. Client sends 0 parameter types (asyncpg behavior), OR
            # 2. Client sends parameters with OID 0 (unspecified) - Prisma's Rust driver does this
            # Without proper OIDs, Prisma fails with "Couldn't serialize value into `unknown`"
            needs_inference = "?" in translation_result["translated_sql"] and (
                num_params == 0 or all(pt == 0 for pt in param_types)
            )
            if needs_inference:
                inferred_param_count = translation_result["translated_sql"].count("?")
                logger.info(
                    "Inferring parameter count from query placeholders",
                    connection_id=self.connection_id,
                    query_preview=query[:100],
                    inferred_count=inferred_param_count,
                )

                # NEW: Infer parameter OIDs from CAST(? AS type) expressions
                # If query has explicit type casts (e.g., $1::int becomes CAST(? AS INTEGER)),
                # we can determine the correct PostgreSQL OID (e.g., 23 for INTEGER)
                param_types = self.infer_parameter_oids_from_casts(
                    translation_result["translated_sql"], inferred_param_count
                )

                logger.info(
                    "Inferred parameter types from CAST expressions",
                    connection_id=self.connection_id,
                    param_types=[f"OID {oid}" for oid in param_types],
                    translated_query=translation_result["translated_sql"][:150],
                )

            if not translation_result["success"]:
                logger.warning(
                    "SQL translation failed for prepared statement",
                    connection_id=self.connection_id,
                    statement_name=statement_name,
                    error=translation_result.get("error"),
                )

            # Store prepared statement with both original and translated SQL
            perf_stats = translation_result.get("performance_stats")
            self.prepared_statements[statement_name] = {
                "original_query": query,
                "translated_query": translation_result["translated_sql"],
                "param_types": param_types,
                "translation_metadata": {
                    "constructs_translated": len(translation_result.get("construct_mappings", [])),
                    "translation_time_ms": perf_stats.translation_time_ms if perf_stats else 0,
                    "cache_hit": perf_stats.cache_hit if perf_stats else False,
                    "warnings": translation_result.get("warnings", []),
                },
            }

            logger.info(
                "Parsed statement with translation",
                connection_id=self.connection_id,
                statement_name=statement_name,
                original_query=query[:100] + "..." if len(query) > 100 else query,
                translated_query=(
                    translation_result["translated_sql"][:100] + "..."
                    if len(translation_result["translated_sql"]) > 100
                    else translation_result["translated_sql"]
                ),
                num_params=num_params,
                constructs_translated=len(translation_result.get("construct_mappings", [])),
            )

            # Log translation details if constructs were translated
            if translation_result.get("translation_used") and translation_result.get(
                "construct_mappings"
            ):
                perf_stats = translation_result.get("performance_stats")
                logger.info(
                    "IRIS constructs translated in prepared statement",
                    connection_id=self.connection_id,
                    statement_name=statement_name,
                    constructs_count=len(translation_result["construct_mappings"]),
                    translation_time_ms=perf_stats.translation_time_ms if perf_stats else 0,
                )

            # Send ParseComplete response
            await self.send_parse_complete()

        except Exception as e:
            logger.error(
                "Parse message handling failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response("ERROR", "42601", "syntax_error", f"Parse failed: {e}")

    async def handle_bind_message(self, body: bytes):
        """
        P2: Handle Bind message for parameter binding

        Bind message format:
        - portal_name (null-terminated string)
        - statement_name (null-terminated string)
        - num_param_format_codes (Int16)
        - param_format_codes (Int16 array)
        - num_param_values (Int16)
        - param_values (length + data for each)
        - num_result_format_codes (Int16)
        - result_format_codes (Int16 array)
        """
        try:
            pos = 0

            # Parse portal name
            name_end = body.find(b"\x00", pos)
            if name_end == -1:
                raise ValueError("Invalid Bind message: missing portal name terminator")
            portal_name = body[pos:name_end].decode("utf-8")
            pos = name_end + 1

            # Parse statement name
            stmt_end = body.find(b"\x00", pos)
            if stmt_end == -1:
                raise ValueError("Invalid Bind message: missing statement name terminator")
            statement_name = body[pos:stmt_end].decode("utf-8")
            pos = stmt_end + 1

            # Check if statement exists
            if statement_name not in self.prepared_statements:
                raise ValueError(f"Prepared statement '{statement_name}' does not exist")

            # Get parameter types from prepared statement for binary decoding
            stmt = self.prepared_statements[statement_name]
            param_types = stmt.get("param_types", [])

            # Parse parameter format codes
            if pos + 2 > len(body):
                raise ValueError("Invalid Bind message: missing format codes count")
            num_format_codes = struct.unpack("!H", body[pos : pos + 2])[0]
            pos += 2

            format_codes = []
            for i in range(num_format_codes):
                if pos + 2 > len(body):
                    raise ValueError(f"Invalid Bind message: missing format code {i}")
                format_code = struct.unpack("!H", body[pos : pos + 2])[0]
                format_codes.append(format_code)
                pos += 2

            # Parse parameter values
            if pos + 2 > len(body):
                raise ValueError("Invalid Bind message: missing parameter count")
            num_params = struct.unpack("!H", body[pos : pos + 2])[0]
            pos += 2

            param_values = []
            for i in range(num_params):
                if pos + 4 > len(body):
                    raise ValueError(f"Invalid Bind message: missing parameter length {i}")
                param_length = struct.unpack("!I", body[pos : pos + 4])[0]
                pos += 4

                if param_length == 0xFFFFFFFF:  # NULL value
                    param_values.append(None)
                else:
                    if pos + param_length > len(body):
                        raise ValueError(f"Invalid Bind message: truncated parameter {i}")
                    param_data = body[pos : pos + param_length]

                    # Determine format: use format_codes[i] if available, else format_codes[0], else text (0)
                    if format_codes:
                        format_code = format_codes[i] if i < len(format_codes) else format_codes[0]
                    else:
                        format_code = 0  # Default to text

                    if format_code == 0:
                        text_value = param_data.decode("utf-8")
                        try:
                            if "." not in text_value and "e" not in text_value.lower():
                                param_values.append(int(text_value))
                            else:
                                param_values.append(float(text_value))
                        except (ValueError, TypeError):
                            param_values.append(text_value)
                    elif format_code == 1:
                        # Binary format - decode based on parameter type OID
                        # Get parameter type OID from prepared statement (0 if not available)
                        param_type_oid = param_types[i] if i < len(param_types) else 0
                        decoded_param = self._decode_binary_parameter(param_data, i, param_type_oid)
                        param_values.append(decoded_param)
                    else:
                        raise ValueError(f"Unknown format code {format_code} for parameter {i}")

                    pos += param_length

            # Parse result format codes (CRITICAL for asyncpg binary format support)
            # Format: num_result_format_codes (Int16) + result_format_codes (Int16 array)
            # If num=0: all text; if num=1: single format for all columns; if num=N: per-column formats
            result_formats = []
            if pos + 2 <= len(body):
                num_result_formats = struct.unpack("!H", body[pos : pos + 2])[0]
                pos += 2

                if num_result_formats > 0:
                    for i in range(num_result_formats):
                        if pos + 2 <= len(body):
                            format_code = struct.unpack("!H", body[pos : pos + 2])[0]
                            result_formats.append(format_code)
                            pos += 2
                        else:
                            logger.warning(
                                "Truncated result format codes",
                                connection_id=self.connection_id,
                                expected=num_result_formats,
                                got=i,
                            )
                            break

                logger.info(
                    "Parsed result format codes",
                    connection_id=self.connection_id,
                    portal_name=portal_name,
                    num_formats=num_result_formats,
                    formats=result_formats,
                )
            else:
                # No format codes specified - default to text (0)
                logger.debug(
                    "No result format codes in Bind message - defaulting to text",
                    connection_id=self.connection_id,
                )

            # Store portal with result format codes
            self.portals[portal_name] = {
                "statement": statement_name,
                "params": param_values,
                "result_formats": result_formats,  # Store for use in send_data_row
            }

            # Batch Execution Interception
            if self.batch_statement_name != statement_name:
                await self.flush_batch()
                self.batch_statement_name = statement_name

            self.batch_portal_name = portal_name

            logger.debug(
                "Bound portal",
                connection_id=self.connection_id,
                portal_name=portal_name,
                statement_name=statement_name,
                num_params=num_params,
            )

            # Send BindComplete response
            await self.send_bind_complete()

        except Exception as e:
            logger.error(
                "Bind message handling failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response(
                "ERROR", "42P02", "undefined_parameter", f"Bind failed: {e}"
            )

    def _build_metadata_dummy_params(self, query: str, param_count: int) -> list[Any]:
        if param_count <= 0:
            return []

        dummy_params = [None] * param_count
        limit_indexes, offset_indexes = self._find_limit_offset_param_indexes(query)

        for idx in limit_indexes:
            if 1 <= idx <= param_count:
                dummy_params[idx - 1] = 1

        for idx in offset_indexes:
            if 1 <= idx <= param_count:
                dummy_params[idx - 1] = 0

        return dummy_params

    def _find_limit_offset_param_indexes(self, query: str) -> tuple[set[int], set[int]]:
        def placeholder_index_for_pos(pos: int) -> int:
            return query[:pos].count("?") + 1

        limit_indexes: set[int] = set()
        offset_indexes: set[int] = set()

        for match in re.finditer(r"\bLIMIT\s+\?\s+OFFSET\s+\?", query, re.IGNORECASE):
            local = match.group(0)
            first_q = local.find("?")
            second_q = local.find("?", first_q + 1)
            if first_q != -1:
                limit_indexes.add(placeholder_index_for_pos(match.start() + first_q))
            if second_q != -1:
                offset_indexes.add(placeholder_index_for_pos(match.start() + second_q))

        for match in re.finditer(r"\bLIMIT\s+\?\s*,\s*\?", query, re.IGNORECASE):
            local = match.group(0)
            first_q = local.find("?")
            second_q = local.find("?", first_q + 1)
            if first_q != -1:
                offset_indexes.add(placeholder_index_for_pos(match.start() + first_q))
            if second_q != -1:
                limit_indexes.add(placeholder_index_for_pos(match.start() + second_q))

        for match in re.finditer(r"\bLIMIT\s+\?", query, re.IGNORECASE):
            local = match.group(0)
            first_q = local.find("?")
            if first_q != -1:
                idx = placeholder_index_for_pos(match.start() + first_q)
                if idx not in offset_indexes:
                    limit_indexes.add(idx)

        for match in re.finditer(r"\bOFFSET\s+\?", query, re.IGNORECASE):
            local = match.group(0)
            first_q = local.find("?")
            if first_q != -1:
                idx = placeholder_index_for_pos(match.start() + first_q)
                if idx not in limit_indexes:
                    offset_indexes.add(idx)

        return limit_indexes, offset_indexes

    async def handle_describe_message(self, body: bytes):
        """
        P2: Handle Describe message for statement/portal description

        Describe message format:
        - type ('S' for statement, 'P' for portal)
        - name (null-terminated string)
        """
        try:
            if len(body) < 2:
                raise ValueError("Invalid Describe message: too short")

            describe_type = chr(body[0])
            name = body[1:].rstrip(b"\x00").decode("utf-8")

            if describe_type == "S":
                # Describe statement
                if name not in self.prepared_statements:
                    raise ValueError(f"Prepared statement '{name}' does not exist")

                stmt = self.prepared_statements[name]

                # Send ParameterDescription with parameter type OIDs
                await self.send_parameter_description(stmt["param_types"])

                # For SELECT/SHOW statements, send RowDescription with column metadata
                # For DDL/DML statements, send NoData
                query = stmt.get("translated_query", stmt.get("query", ""))
                query_upper = query.strip().upper()

                logger.info(
                    "🔍 Describe Statement: Checking query type",
                    connection_id=self.connection_id,
                    statement_name=name,
                    query_preview=query[:100],
                    is_select=self.iris_executor.sql_parser.is_select_statement(query),
                    is_show=self.iris_executor.sql_parser.is_show_statement(query),
                )

                # Check if query has RETURNING clause (INSERT/UPDATE/DELETE with RETURNING)
                has_returning = self.iris_executor.has_returning_clause(query)

                if (
                    self.iris_executor.sql_parser.is_select_statement(query)
                    or self.iris_executor.sql_parser.is_show_statement(query)
                    or has_returning
                ):
                    # Execute metadata discovery to get column information
                    # Use LIMIT 0 pattern to avoid fetching actual data
                    # For RETURNING queries, we'll send synthetic column metadata based on RETURNING columns
                    try:
                        # Special handling for RETURNING queries - extract columns from RETURNING clause
                        if has_returning and not self.iris_executor.sql_parser.is_select_statement(
                            query
                        ):
                            import re

                            # Extract RETURNING columns from query
                            # Format: RETURNING "schema"."table"."col1", "schema"."table"."col2", ...
                            returning_match = re.search(
                                r"\bRETURNING\s+(.+)$", query, re.IGNORECASE | re.DOTALL
                            )
                            if returning_match:
                                returning_clause = (
                                    returning_match.group(1).strip().rstrip(";")
                                )  # Remove trailing semicolon
                                logger.info(
                                    "🔍 DEBUG: RETURNING clause parsed",
                                    connection_id=self.connection_id,
                                    returning_clause=returning_clause[:200],
                                    returning_clause_len=len(returning_clause),
                                )
                                raw_cols = [c.strip() for c in returning_clause.split(",")]
                                logger.info(
                                    "🔍 DEBUG: Raw columns from split",
                                    connection_id=self.connection_id,
                                    raw_cols_count=len(raw_cols),
                                    raw_cols=[c[:50] for c in raw_cols],
                                )
                                returning_columns = []
                                for col in raw_cols:
                                    # Extract column name (last part after dots)
                                    col_match = re.search(r'"?(\w+)"?\s*$', col)
                                    if col_match:
                                        col_name = col_match.group(1)
                                        if col_name.lower() in (
                                            "created_at",
                                            "updated_at",
                                            "deleted_at",
                                        ):
                                            type_oid = 20
                                        else:
                                            type_oid = 25
                                        returning_columns.append(
                                            {
                                                "name": col_name,
                                                "type_oid": type_oid,
                                                "type_size": -1,
                                                "type_modifier": -1,
                                                "format_code": 0,
                                            }
                                        )

                                logger.info(
                                    "🔍 Describe: Sending synthetic RowDescription for RETURNING",
                                    connection_id=self.connection_id,
                                    columns=[c["name"] for c in returning_columns],
                                )
                                await self.send_row_description(returning_columns)
                                logger.info(
                                    "Described object",
                                    connection_id=self.connection_id,
                                    name=name,
                                    type="S",
                                )
                                return
                            else:
                                logger.warning(
                                    "Could not parse RETURNING clause, falling back to NoData",
                                    connection_id=self.connection_id,
                                    query_preview=query[:100],
                                )
                                await self.send_no_data()
                                logger.info(
                                    "Described object",
                                    connection_id=self.connection_id,
                                    name=name,
                                    type="S",
                                )
                                return

                        logger.info(
                            "🔍 Describe Statement: Executing metadata discovery",
                            connection_id=self.connection_id,
                            query=query[:150],
                        )

                        # Execute the query to discover column metadata
                        # NOTE: We're not using LIMIT 0 wrapper because IRIS may not support it
                        # Instead, we'll execute the full query but only need the metadata

                        # CRITICAL: If statement has parameters, supply dummy values for metadata discovery
                        param_count = (
                            stmt["param_types"]
                            if isinstance(stmt.get("param_types"), int)
                            else len(stmt.get("param_types", []))
                        )
                        if param_count == 0 and "?" in query:
                            param_count = query.count("?")

                        dummy_params = self._build_metadata_dummy_params(
                            query=query,
                            param_count=param_count,
                        )

                        logger.info(
                            "🔍 Describe Statement: Using dummy parameters for metadata",
                            connection_id=self.connection_id,
                            param_count=param_count,
                        )

                        result = await self.iris_executor.execute_query(
                            query, params=dummy_params, session_id=self.connection_id
                        )

                        if result.get("success") and result.get("columns"):
                            await self.send_row_description(result["columns"])
                            # CRITICAL: Mark that RowDescription was sent in Describe phase (text format)
                            # Execute phase must use text format in DataRow to match RowDescription
                            stmt["row_description_sent_in_describe"] = True
                            logger.info(
                                "✅ Sent RowDescription for statement Describe",
                                connection_id=self.connection_id,
                                statement_name=name,
                                column_count=len(result["columns"]),
                                columns=[c["name"] for c in result["columns"]],
                            )
                        else:
                            logger.warning(
                                "Metadata discovery returned no columns",
                                connection_id=self.connection_id,
                                result_keys=list(result.keys()) if result else None,
                            )
                            await self.send_no_data()

                    except Exception as e:
                        logger.warning(
                            "Failed to get column metadata for statement Describe",
                            connection_id=self.connection_id,
                            statement_name=name,
                            error=str(e),
                        )
                        # Fall back to NoData on error
                        await self.send_no_data()
                else:
                    # Non-SELECT queries (DDL/DML) return NoData
                    logger.info(
                        "🔍 Describe Statement: Non-SELECT query, sending NoData",
                        connection_id=self.connection_id,
                        query_type=query_upper.split()[0] if query_upper else "UNKNOWN",
                    )
                    await self.send_no_data()

            elif describe_type == "P":
                # Describe portal
                if name not in self.portals:
                    raise ValueError(f"Portal '{name}' does not exist")

                portal = self.portals[name]
                statement_name = portal["statement"]

                if statement_name in self.prepared_statements:
                    stmt = self.prepared_statements[statement_name]
                    query = stmt.get("translated_query", stmt.get("query", ""))
                    query_upper = query.strip().upper()

                    # Batch Execution Interception:
                    # Short-circuit Describe portal for DML statements.
                    # DML portals (without RETURNING) don't have RowDescription.
                    is_dml = self.iris_executor.sql_parser.is_dml_statement(query)
                    has_returning = self.iris_executor.has_returning_clause(query)
                    if is_dml and not has_returning:
                        logger.info(
                            "Describe portal: DML statement (no row metadata)", portal_name=name
                        )
                        await self.send_no_data()
                        return

                    # Metadata discovery for SELECT/SHOW/RETURNING
                    if (
                        self.iris_executor.sql_parser.is_select_statement(query)
                        or self.iris_executor.sql_parser.is_show_statement(query)
                        or has_returning
                    ):
                        try:
                            # CRITICAL FIX: For DML with RETURNING, use synthetic metadata
                            # instead of executing the query (which would cause duplicate execution)
                            if has_returning and not self.iris_executor.sql_parser.is_select_statement(query):
                                import re
                                # Extract RETURNING columns from query
                                returning_match = re.search(
                                    r"\bRETURNING\s+(.+)$", query, re.IGNORECASE | re.DOTALL
                                )
                                if returning_match:
                                    returning_clause = returning_match.group(1).strip().rstrip(";")
                                    raw_cols = [c.strip() for c in returning_clause.split(",")]
                                    returning_columns = []
                                    for col in raw_cols:
                                        # Extract column name (last part after dots)
                                        col_match = re.search(r'"?(\w+)"?\s*$', col)
                                        if col_match:
                                            col_name = col_match.group(1)
                                            if col_name.lower() in ("created_at", "updated_at", "deleted_at"):
                                                type_oid = 20  # BIGINT for timestamps
                                            else:
                                                type_oid = 25  # TEXT for others
                                            returning_columns.append({
                                                "name": col_name,
                                                "type_oid": type_oid,
                                                "type_size": -1,
                                                "type_modifier": -1,
                                                "format_code": 0,
                                            })
                                    
                                    if returning_columns:
                                        logger.info(
                                            "🔍 Describe Portal: Sending synthetic RowDescription for RETURNING",
                                            connection_id=self.connection_id,
                                            portal_name=name,
                                            columns=[c["name"] for c in returning_columns],
                                        )
                                        result_formats = portal.get("result_formats", [])
                                        await self.send_row_description(returning_columns, result_formats)
                                        return
                                    
                                    logger.info(
                                        "🔍 Describe Portal: RETURNING * detected, sending NoData",
                                        connection_id=self.connection_id,
                                        portal_name=name,
                                    )
                                    portal["needs_row_description"] = True
                                    await self.send_no_data()
                                    return
                                else:
                                    logger.warning(
                                        "Could not parse RETURNING clause in portal Describe",
                                        connection_id=self.connection_id,
                                        portal_name=name,
                                    )
                                    await self.send_no_data()
                                    return
                            
                            # For SELECT/SHOW queries, execute to get metadata
                            result = await self.iris_executor.execute_query(
                                query,
                                params=portal.get("params", []),
                                session_id=self.connection_id,
                            )
                            if result.get("success") and result.get("columns"):
                                result_formats = portal.get("result_formats", [])
                                await self.send_row_description(result["columns"], result_formats)
                            else:
                                await self.send_no_data()
                        except Exception as e:
                            logger.warning(f"Metadata discovery failed for portal {name}: {e}")
                            await self.send_no_data()
                    else:
                        await self.send_no_data()
                else:
                    await self.send_no_data()

            else:
                raise ValueError(f"Invalid describe type: {describe_type}")

            logger.info(
                "Described object", connection_id=self.connection_id, type=describe_type, name=name
            )

        except Exception as e:
            logger.error(
                "Describe message handling failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response(
                "ERROR", "42P02", "undefined_object", f"Describe failed: {e}"
            )

    async def handle_execute_message(self, body: bytes):
        """
        P2: Handle Execute message for portal execution

        Execute message format:
        - portal_name (null-terminated string)
        - max_rows (Int32)
        """
        try:
            # Parse portal name
            name_end = body.find(b"\x00")
            if name_end == -1:
                raise ValueError("Invalid Execute message: missing portal name terminator")
            portal_name = body[:name_end].decode("utf-8")

            # Parse max rows (for now, ignore and fetch all)
            if len(body) >= name_end + 5:
                struct.unpack("!I", body[name_end + 1 : name_end + 5])[0]
            else:
                pass

            # Check if portal exists
            if portal_name not in self.portals:
                raise ValueError(f"Portal '{portal_name}' does not exist")

            portal = self.portals[portal_name]
            statement_name = portal["statement"]
            params = portal["params"]
            result_formats = portal.get("result_formats", [])  # Get result format codes from Bind

            if statement_name not in self.prepared_statements:
                raise ValueError(f"Statement '{statement_name}' no longer exists")

            stmt = self.prepared_statements[statement_name]

            # Use result formats from Bind - this is what the client requested
            # Binary encoding is supported for common types (INT4, INT8, TEXT, etc.)
            self._current_result_formats = result_formats
            logger.info(
                "Execute: Using result formats from portal",
                connection_id=self.connection_id,
                portal_name=portal_name,
                result_formats=result_formats,
            )

            # Use translated query for execution
            query = stmt.get("translated_query", stmt.get("query", stmt.get("original_query", "")))

            # Log execution of prepared statement with translation metadata
            translation_metadata = stmt.get("translation_metadata", {})
            logger.info(
                "Executing prepared statement",
                connection_id=self.connection_id,
                portal_name=portal_name,
                statement_name=statement_name,
                constructs_translated=translation_metadata.get("constructs_translated", 0),
                cache_hit=translation_metadata.get("cache_hit", False),
            )

            # Handle empty queries (JDBC connection validation)
            # JDBC driver sends empty Parse/Bind/Execute after SET commands
            is_empty_query = translation_metadata.get("is_empty_query", False)
            if is_empty_query or not query or query.strip() == "":
                logger.info(
                    "Empty query in Execute phase - sending CommandComplete",
                    connection_id=self.connection_id,
                    portal_name=portal_name,
                )
                # For empty queries, just send CommandComplete (no NoData, no RowDescription)
                # JDBC driver expects this for connection validation
                tag = b"SELECT 0\x00"
                cmd_complete_length = 4 + len(tag)
                cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag
                self.writer.write(cmd_complete)
                await self.writer.drain()
                return

            # Handle PostgreSQL SET commands in Extended Protocol
            # JDBC driver uses Extended Protocol for SET commands during connection init
            # Check both the marker from Parse phase and the query itself
            is_set_command = translation_metadata.get("is_set_command", False)
            query_upper = query.upper().strip().rstrip(";")
            if is_set_command or query_upper.startswith("SET "):
                logger.info(
                    "PostgreSQL SET command intercepted in Execute phase",
                    connection_id=self.connection_id,
                    query=query[:100] if query else "(empty after Parse interception)",
                )
                # Send success response for SET commands
                await self.send_set_response_extended_protocol()
                return

            # Handle PostgreSQL transaction commands in Extended Protocol (Feature 022)
            # JDBC driver uses Extended Protocol for transactions (setAutoCommit(false) → BEGIN)
            # Check marker from Parse phase
            is_transaction_command = translation_metadata.get("is_transaction_command", False)
            if is_transaction_command:
                transaction_type = translation_metadata.get("transaction_type")
                logger.info(
                    "PostgreSQL transaction command intercepted in Execute phase",
                    connection_id=self.connection_id,
                    transaction_type=transaction_type,
                )

                if transaction_type == "BEGIN":
                    await self.iris_executor.begin_transaction(session_id=self.connection_id)
                    await self.send_transaction_response_extended_protocol("BEGIN")
                elif transaction_type == "COMMIT":
                    await self.iris_executor.commit_transaction(session_id=self.connection_id)
                    await self.send_transaction_response_extended_protocol("COMMIT")
                elif transaction_type == "ROLLBACK":
                    await self.iris_executor.rollback_transaction(session_id=self.connection_id)
                    await self.send_transaction_response_extended_protocol("ROLLBACK")
                return

            # CRITICAL: Handle pg_type/pg_catalog queries in Extended Protocol
            # asyncpg queries pg_type using prepared statements when it sees OID 0,
            # which would cause infinite recursion. We intercept in Parse phase and
            # return empty results here in Execute phase to break the loop.
            is_pg_catalog_query = translation_metadata.get("is_pg_catalog_query", False)
            if is_pg_catalog_query:
                logger.info(
                    "pg_type/pg_catalog query intercepted in Execute phase",
                    connection_id=self.connection_id,
                    portal_name=portal_name,
                    query_preview=query[:100] if query else "(empty)",
                )
                # Return empty result set
                # Note: Describe phase already sent NoData for this query
                # We just need to send CommandComplete here
                tag = b"SELECT 0\x00"
                cmd_complete_length = 4 + len(tag)
                cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag
                self.writer.write(cmd_complete)
                await self.writer.drain()
                logger.info(
                    "Sent empty result for pg_catalog query", connection_id=self.connection_id
                )
                return

            # Execute the query with parameters
            # IMPORTANT: Pass parameters separately to enable vector query optimizer
            # The optimizer needs to transform vector parameters BEFORE IRIS execution
            # Interpolating here would create large SQL literals that exceed IRIS limits

            # NOTE: PostgreSQL $1, $2 parameters were already translated to IRIS ? syntax
            # in handle_parse_message(), so query already has correct parameter placeholders

            # Batch Execution Interception (Fast Insert Breakthrough)
            # Intercept INSERT/UPDATE/DELETE (DML) without RETURNING for protocol-level batching.
            # Standard PostgreSQL clients (psycopg3) send Sync every 5 rows, which is slow.
            # We buffer parameters and send synthetic CommandComplete to keep client pipe full.
            is_dml = self.iris_executor.sql_parser.is_dml_statement(query)
            has_returning = self.iris_executor.sql_parser.has_returning_clause(query)

            if is_dml and not has_returning:
                # Store SQL if first row in batch
                if not self.batch_params:
                    self.batch_sql = query

                # Buffer parameters
                self.batch_params.append(params if params else [])

                # Send synthetic CommandComplete immediately to client
                # This tricks the client into sending the next row immediately.
                query_upper = query.strip().upper()
                tag = f"{query_upper.split()[0]} 0 1\x00".encode()
                msg_len = 4 + len(tag)
                self.writer.write(struct.pack("!cI", MSG_COMMAND_COMPLETE, msg_len) + tag)
                await self.writer.drain()

                logger.debug(
                    "Buffered DML row (Fast Path)",
                    connection_id=self.connection_id,
                    buffer_size=len(self.batch_params),
                )
                return

            # Execute via IRIS with parameters (vector optimizer will transform if needed)
            # Ensure any buffered DML is flushed before executing a non-batch query
            # This ensures visibility of previous buffered inserts for the current query
            await self.flush_batch()

            # DEBUG: Verify executor instance
            # logger.warning(f"DEBUG: Using iris_executor at {id(self.iris_executor)}")

            result = await self.iris_executor.execute_query(
                query, params=params if params else None, session_id=self.connection_id
            )

            if result["success"]:
                # Extended Protocol: Don't send ReadyForQuery here - Sync handler will send it
                # Check if Describe sent NoData for RETURNING * - if so, we need to send RowDescription
                needs_row_desc = portal.get("needs_row_description", False) if portal else False
                await self.send_query_result(result, send_ready=False, send_row_description=needs_row_desc)
            else:
                await self.send_error_response(
                    "ERROR", "42000", "syntax_error", result.get("error", "Query execution failed")
                )

            logger.info(
                "Executed portal",
                connection_id=self.connection_id,
                portal_name=portal_name,
                query=query[:100] + "..." if len(query) > 100 else query,
            )

        except Exception as e:
            logger.error(
                "Execute message handling failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response(
                "ERROR", "42P03", "undefined_cursor", f"Execute failed: {e}"
            )

    async def handle_sync_message(self, body: bytes):
        """
        P2: Handle Sync message (end of extended protocol cycle)

        Sync message has no body.
        """
        try:
            # CRITICAL: Always flush batch on Sync if not empty.
            # PostgreSQL protocol expects visibility after Sync.
            if self.batch_params:
                logger.info(
                    "🔄 Sync: Flushing batch for visibility",
                    connection_id=self.connection_id,
                    size=len(self.batch_params),
                )
                await self.flush_batch()

            # ALWAYS send ReadyForQuery to keep the client pipeline moving.
            await self.send_ready_for_query()

        except Exception as e:
            logger.error(
                "Sync message handling failed", connection_id=self.connection_id, error=str(e)
            )

    async def handle_close_message(self, body: bytes):
        """
        P2: Handle Close message for closing statements/portals

        Close message format:
        - type ('S' for statement, 'P' for portal)
        - name (null-terminated string)
        """
        try:
            # Ensure any buffered DML is flushed before closing
            await self.flush_batch()

            if len(body) < 2:
                raise ValueError("Invalid Close message: too short")

            close_type = chr(body[0])
            name = body[1:].rstrip(b"\x00").decode("utf-8")

            if close_type == "S":
                # Close statement
                if name in self.prepared_statements:
                    del self.prepared_statements[name]
                    logger.info("Closed statement", connection_id=self.connection_id, name=name)
            elif close_type == "P":
                # Close portal
                if name in self.portals:
                    del self.portals[name]
                    logger.info("Closed portal", connection_id=self.connection_id, name=name)
            else:
                raise ValueError(f"Invalid close type: {close_type}")

            # Send CloseComplete response
            await self.send_close_complete()

        except Exception as e:
            logger.error(
                "Close message handling failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response(
                "ERROR", "42P02", "undefined_object", f"Close failed: {e}"
            )

    async def handle_flush_message(self, body: bytes):
        """
        P2: Handle Flush message (flush output buffer)

        Flush message has no body.
        """
        try:
            # Ensure all pending output is sent
            await self.writer.drain()
            logger.debug("Flush message processed", connection_id=self.connection_id)

        except Exception as e:
            logger.error(
                "Flush message handling failed", connection_id=self.connection_id, error=str(e)
            )

    # P2: Extended Protocol Response Messages

    async def send_parse_complete(self):
        """Send ParseComplete response"""
        message = struct.pack("!cI", MSG_PARSE_COMPLETE, 4)
        self.writer.write(message)
        await self.writer.drain()

    async def send_bind_complete(self):
        """Send BindComplete response"""
        message = struct.pack("!cI", MSG_BIND_COMPLETE, 4)
        self.writer.write(message)
        await self.writer.drain()

    async def send_close_complete(self):
        """Send CloseComplete response"""
        message = struct.pack("!cI", MSG_CLOSE_COMPLETE, 4)
        self.writer.write(message)
        await self.writer.drain()

    async def send_parameter_description(self, param_types: list):
        """Send ParameterDescription message

        CRITICAL: asyncpg has specific behavior based on parameter type OIDs:
        - OID 0 (unspecified): Causes infinite recursion (introspects pg_type)
        - OID 25 (TEXT): Forces text encoding, rejects non-string values
        - OID 705 (UNKNOWN): Also forces text encoding
        - OID 23 (INT4): Allows binary encoding but only for integers

        The only way to support mixed types is to send OID 0 BUT avoid
        the recursion. We'll send UNKNOWN (705) which doesn't trigger recursion,
        and handle type conversion on the server side when we receive TEXT format.
        """
        count = len(param_types)

        # DEBUG: Log what we're actually sending
        logger.info(
            "🔍 DEBUG: Sending ParameterDescription",
            connection_id=self.connection_id,
            param_count=count,
            param_types=param_types,
            param_oids=[f"OID {pt}" for pt in param_types],
        )

        message = struct.pack("!cIH", MSG_PARAMETER_DESCRIPTION, 4 + 2 + count * 4, count)

        for param_type in param_types:
            # Send OID as-is - don't try to fix it here
            # The fix is in Bind handler to convert TEXT-encoded values properly
            effective_type = param_type
            message += struct.pack("!I", effective_type)

        self.writer.write(message)
        await self.writer.drain()

    async def send_no_data(self):
        """Send NoData response"""
        # DEBUGGING: Track when NoData is sent (should NOT be sent for SHOW queries!)
        import traceback

        caller_info = "".join(traceback.format_stack()[-3:-1])
        logger.warning(
            "📛 SEND_NO_DATA CALLED", connection_id=self.connection_id, caller=caller_info
        )

        message = struct.pack("!cI", MSG_NO_DATA, 4)
        self.writer.write(message)
        await self.writer.drain()

        logger.info("📛 NoData message sent", connection_id=self.connection_id)

    def _convert_postgres_to_iris_syntax(self, query: str) -> str:
        """
        Convert PostgreSQL-specific syntax to IRIS-compatible syntax

        This addresses the user's concern about LIMIT vs TOP parametrization issues
        in xDBC clients. PostgreSQL wire protocol parametrization works better.
        """
        # Handle LIMIT conversion (PostgreSQL LIMIT to IRIS TOP if needed)
        # Note: Modern IRIS supports LIMIT syntax, so this may not be needed
        # but we keep it for compatibility with older IRIS versions

        # For now, return as-is since modern IRIS supports LIMIT
        # In future, could add conversions like:
        # - LIMIT n -> TOP n
        # - OFFSET handling
        # - PostgreSQL-specific functions to IRIS equivalents

        return query

    def _decode_binary_parameter(self, data: bytes, param_index: int, param_type_oid: int = 0):
        """
        Decode binary-format parameter from PostgreSQL wire protocol.

        PostgreSQL binary format for arrays (vectors):
        - Int32: number of dimensions (ndim)
        - Int32: has_null flag (0 = no nulls)
        - Int32: element type OID
        - For each dimension:
          - Int32: dimension size
          - Int32: lower bound (usually 1)
        - For each element:
          - Int32: element length (-1 for NULL)
          - bytes: element data (if not NULL)

        For simple types:
        - int2 (OID 21): 2-byte signed integer (big-endian)
        - int4 (OID 23): 4-byte signed integer (big-endian)
        - int8 (OID 20): 8-byte signed integer (big-endian)
        - float4 (OID 700): 4-byte IEEE 754 float
        - float8 (OID 701): 8-byte IEEE 754 double

        Args:
            data: Binary parameter data
            param_index: Parameter index (for logging)
            param_type_oid: PostgreSQL type OID from prepared statement (0 if unknown)

        Returns:
            Typed value (int, float, str, or list) suitable for IRIS parameter binding
        """
        try:
            if len(data) < 12:
                # Not an array, might be a simple type
                # Decode based on parameter type OID OR data length
                if param_type_oid == 21 and len(data) == 2:  # int2 (smallint)
                    value = struct.unpack("!h", data)[0]  # Big-endian signed short
                    return value  # Return actual int, not string
                elif param_type_oid == 23 and len(data) == 4:  # int4
                    value = struct.unpack("!i", data)[0]  # Big-endian signed int
                    return value  # Return actual int, not string
                elif param_type_oid == 20 and len(data) == 8:  # int8 (bigint)
                    value = struct.unpack("!q", data)[0]  # Big-endian signed long
                    return value  # Return actual int, not string
                elif param_type_oid == 700 and len(data) == 4:  # float4 explicit
                    value = struct.unpack("!f", data)[0]  # Big-endian float
                    return value  # Return actual float, not string
                elif param_type_oid == 701 and len(data) == 8:  # float8 explicit
                    value = struct.unpack("!d", data)[0]  # Big-endian double
                    return value  # Return actual float, not string
                elif param_type_oid == 16 and len(data) == 1:  # bool
                    # PostgreSQL boolean binary format: 1 byte (0x00 = False, 0x01 = True)
                    value = data[0] != 0
                    # Convert to IRIS BIT representation (1 or 0)
                    return 1 if value else 0
                elif param_type_oid == 1082 and len(data) == 4:  # DATE
                    # PostgreSQL DATE binary format: 4-byte signed integer (days since 2000-01-01)
                    # IRIS expects dates as ISO 8601 strings (YYYY-MM-DD)
                    import datetime

                    pg_days = struct.unpack("!i", data)[0]
                    PG_EPOCH = datetime.date(2000, 1, 1)
                    date_obj = PG_EPOCH + datetime.timedelta(days=pg_days)
                    return date_obj.strftime("%Y-%m-%d")  # Convert to ISO string for IRIS
                elif param_type_oid == 1114 and len(data) == 8:  # TIMESTAMP (without timezone)
                    # PostgreSQL TIMESTAMP binary format: 8-byte signed integer (microseconds since 2000-01-01)
                    # IRIS expects timestamps as ISO 8601 strings (YYYY-MM-DD HH:MM:SS.ffffff)
                    import datetime

                    pg_microseconds = struct.unpack("!q", data)[0]
                    PG_EPOCH = datetime.datetime(2000, 1, 1, 0, 0, 0)
                    timestamp_obj = PG_EPOCH + datetime.timedelta(microseconds=pg_microseconds)
                    return timestamp_obj.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )  # Convert to ISO string for IRIS
                elif param_type_oid == 1184 and len(data) == 8:  # TIMESTAMPTZ (with timezone)
                    # Same as TIMESTAMP but with timezone - PostgreSQL stores as UTC microseconds
                    import datetime

                    pg_microseconds = struct.unpack("!q", data)[0]
                    PG_EPOCH = datetime.datetime(2000, 1, 1, 0, 0, 0)
                    timestamp_obj = PG_EPOCH + datetime.timedelta(microseconds=pg_microseconds)
                    return timestamp_obj.strftime(
                        "%Y-%m-%d %H:%M:%S.%f"
                    )  # Convert to ISO string for IRIS
                # Fallback: Infer type from data length when OID not specified
                elif len(data) == 1:
                    # Could be boolean - treat as boolean
                    value = data[0] != 0
                    return 1 if value else 0
                elif len(data) == 2:
                    # Assume int2 (smallint)
                    value = struct.unpack("!h", data)[0]
                    return value
                elif len(data) == 4:
                    # Assume int4 (psycopg may not specify OID for integers)
                    value = struct.unpack("!i", data)[0]
                    return value
                elif len(data) == 8:
                    # Assume int8 (prefer int over float for 8-byte values)
                    value = struct.unpack("!q", data)[0]
                    return value
                else:
                    # Unknown format, return as text
                    return data.decode("utf-8", errors="replace")

            # Parse array header
            pos = 0
            ndim = struct.unpack("!I", data[pos : pos + 4])[0]
            pos += 4
            struct.unpack("!I", data[pos : pos + 4])[0]
            pos += 4
            element_oid = struct.unpack("!I", data[pos : pos + 4])[0]
            pos += 4

            if ndim == 0:
                # Empty array
                return "[]"

            # Parse dimension info
            dimensions = []
            for _ in range(ndim):
                if pos + 8 > len(data):
                    raise ValueError(f"Truncated dimension info for parameter {param_index}")
                dim_size = struct.unpack("!I", data[pos : pos + 4])[0]
                pos += 4
                struct.unpack("!I", data[pos : pos + 4])[0]
                pos += 4
                dimensions.append(dim_size)

            # Parse elements
            total_elements = 1
            for dim in dimensions:
                total_elements *= dim

            elements = []
            for i in range(total_elements):
                if pos + 4 > len(data):
                    raise ValueError(
                        f"Truncated element length for parameter {param_index}, element {i}"
                    )
                elem_len = struct.unpack("!I", data[pos : pos + 4])[0]
                pos += 4

                if elem_len == 0xFFFFFFFF:
                    # NULL element
                    elements.append("NULL")
                else:
                    if pos + elem_len > len(data):
                        raise ValueError(
                            f"Truncated element data for parameter {param_index}, element {i}"
                        )
                    elem_data = data[pos : pos + elem_len]
                    pos += elem_len

                    # Decode based on element OID
                    if element_oid == 700:  # float4
                        value = struct.unpack("!f", elem_data)[0]
                        elements.append(str(value))
                    elif element_oid == 701:  # float8 (double)
                        value = struct.unpack("!d", elem_data)[0]
                        elements.append(str(value))
                    elif element_oid == 23:  # int4
                        value = struct.unpack("!i", elem_data)[0]
                        elements.append(str(value))
                    elif element_oid == 20:  # int8 (bigint)
                        value = struct.unpack("!q", elem_data)[0]
                        elements.append(str(value))
                    else:
                        # Unknown type, try as text
                        elements.append(elem_data.decode("utf-8", errors="replace"))

            # Format as IRIS vector: [v1,v2,v3,...]
            vector_text = "[" + ",".join(elements) + "]"

            logger.debug(
                "Decoded binary vector parameter",
                param_index=param_index,
                dimensions=dimensions,
                element_count=len(elements),
                element_oid=element_oid,
                vector_length=len(vector_text),
            )

            return vector_text

        except Exception as e:
            logger.error(
                "Binary parameter decode failed",
                param_index=param_index,
                error=str(e),
                data_length=len(data),
            )
            # Fallback: try to decode as text
            return data.decode("utf-8", errors="replace")

    # P4: Query Cancellation Methods

    async def handle_cancel_request(self):
        """
        P4: Handle PostgreSQL cancel request

        Cancel request format:
        - Length: 16 bytes total
        - Code: CANCEL_REQUEST_CODE (80877102)
        - PID: 4 bytes (backend_pid from BackendKeyData)
        - Secret: 4 bytes (backend_secret from BackendKeyData)
        """
        try:
            # Read additional 8 bytes for PID and secret (we already read first 8)
            cancel_data = await self.reader.readexactly(8)
            backend_pid, backend_secret = struct.unpack("!II", cancel_data)

            logger.info(
                "Cancel request details",
                connection_id=self.connection_id,
                target_pid=backend_pid,
                provided_secret="***",
            )

            # Find and cancel the target connection
            success = await self.iris_executor.cancel_query(backend_pid, backend_secret)

            if success:
                logger.info(
                    "Query cancellation successful",
                    connection_id=self.connection_id,
                    target_pid=backend_pid,
                )
            else:
                logger.warning(
                    "Query cancellation failed - connection not found or secret mismatch",
                    connection_id=self.connection_id,
                    target_pid=backend_pid,
                )

            # Cancel requests don't send responses - just close connection
            self.writer.close()
            await self.writer.wait_closed()

        except Exception as e:
            logger.error(
                "Cancel request handling failed", connection_id=self.connection_id, error=str(e)
            )

    # P6: COPY Protocol Methods

    async def handle_copy_command(self, query: str):
        """
        P6: Handle COPY command parsing and execution (T017 Implementation)

        Uses CopyCommandParser to parse SQL and CopyHandler for execution.
        Implements proper PostgreSQL wire protocol message flow.
        """
        try:
            # Parse COPY command using CopyCommandParser (T012-T013)
            command = CopyCommandParser.parse(query)

            logger.info(
                "COPY command parsed",
                connection_id=self.connection_id,
                table=command.table_name,
                direction=command.direction.value,
                columns=command.column_list,
                csv_format=command.csv_options.format,
            )

            if command.direction == CopyDirection.FROM_STDIN:
                # COPY FROM STDIN - bulk data import
                await self.handle_copy_from_stdin_v2(command)
            elif command.direction == CopyDirection.TO_STDOUT:
                # COPY TO STDOUT - bulk data export
                await self.handle_copy_to_stdout_v2(command)
            else:
                await self.send_error_response(
                    "ERROR",
                    "42601",
                    "syntax_error",
                    f"Unsupported COPY direction: {command.direction}",
                )

        except CSVParsingError as e:
            # CSV parsing errors include line numbers (FR-007)
            logger.error(
                "CSV parsing failed",
                connection_id=self.connection_id,
                error=str(e),
                line_number=e.line_number,
            )
            await self.send_error_response("ERROR", "22P04", "bad_copy_file_format", str(e))
            # Send ReadyForQuery after error
            await self.send_ready_for_query()

        except ValueError as e:
            # Parse errors (invalid COPY syntax)
            logger.error(
                "COPY command parse failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response(
                "ERROR", "42601", "syntax_error", f"Invalid COPY command: {e}"
            )
            await self.send_ready_for_query()

        except Exception as e:
            logger.error(
                "COPY command handling failed", connection_id=self.connection_id, error=str(e)
            )
            await self.send_error_response(
                "ERROR", "08000", "connection_exception", f"COPY command failed: {e}"
            )
            await self.send_ready_for_query()

    async def handle_copy_from_stdin_v2(self, command):
        """
        P6: Handle COPY FROM STDIN with CopyHandler integration (T017)

        Protocol Flow:
        1. Send CopyInResponse to client
        2. Collect CopyData messages via async iterator
        3. Execute CopyHandler.handle_copy_from_stdin()
        4. Wait for CopyDone message
        5. Send CommandComplete and ReadyForQuery
        """
        try:
            # Determine column count for CopyInResponse
            if command.column_list:
                column_count = len(command.column_list)
            else:
                # Get column count from table metadata
                column_count = len(await self.bulk_executor.get_table_columns(command.table_name))

            # Send CopyInResponse message (T014)
            copy_in_response = self.copy_handler.build_copy_in_response(column_count)
            self.writer.write(copy_in_response)
            await self.writer.drain()

            logger.info(
                "CopyInResponse sent, awaiting CopyData messages",
                connection_id=self.connection_id,
                table=command.table_name,
                column_count=column_count,
            )

            # Collect CopyData messages as async iterator
            async def csv_stream():
                """Async iterator yielding CSV bytes from CopyData messages"""
                while True:
                    # Read next message
                    header = await self.reader.readexactly(5)
                    msg_type, length = struct.unpack("!cI", header)

                    body_length = length - 4
                    if body_length > 0:
                        body = await self.reader.readexactly(body_length)
                    else:
                        body = b""

                    if msg_type == MSG_COPY_DATA:
                        # Yield CSV data payload
                        yield body
                    elif msg_type == MSG_COPY_DONE:
                        # End of stream
                        logger.info("CopyDone received", connection_id=self.connection_id)
                        break
                    elif msg_type == MSG_COPY_FAIL:
                        # Client aborted
                        error_msg = body.decode("utf-8") if body else "Client aborted"
                        raise RuntimeError(f"COPY aborted by client: {error_msg}")
                    else:
                        raise ValueError(f"Unexpected message type during COPY: {msg_type}")

            # Execute COPY FROM STDIN via CopyHandler (T015, T018, T020)
            row_count = await self.copy_handler.handle_copy_from_stdin(command, csv_stream())

            # Send CommandComplete with row count
            tag = f"COPY {row_count}\x00".encode()
            cmd_complete_length = 4 + len(tag)
            cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag
            self.writer.write(cmd_complete)
            await self.writer.drain()

            # Send ReadyForQuery
            await self.send_ready_for_query()

            logger.info(
                "COPY FROM STDIN completed successfully",
                connection_id=self.connection_id,
                table=command.table_name,
                rows_inserted=row_count,
            )

        except Exception as e:
            logger.error("COPY FROM STDIN failed", connection_id=self.connection_id, error=str(e))
            raise

    async def handle_copy_to_stdout_v2(self, command):
        """
        P6: Handle COPY TO STDOUT with CopyHandler integration (T017)

        Protocol Flow:
        1. Send CopyOutResponse to client
        2. Execute query via CopyHandler.handle_copy_to_stdout()
        3. Stream CopyData messages to client
        4. Send CopyDone
        5. Send CommandComplete and ReadyForQuery
        """
        try:
            # Determine column count for CopyOutResponse
            if command.column_list:
                column_count = len(command.column_list)
            elif command.table_name:
                # Get column count from table metadata
                column_count = len(await self.bulk_executor.get_table_columns(command.table_name))
            else:
                # Query-based COPY - default to unknown
                column_count = 0  # Will be determined by query execution

            # Send CopyOutResponse message (T014)
            copy_out_response = self.copy_handler.build_copy_out_response(column_count)
            self.writer.write(copy_out_response)
            await self.writer.drain()

            logger.info(
                "CopyOutResponse sent, starting data export",
                connection_id=self.connection_id,
                table=command.table_name,
                query=command.query[:100] if command.query else None,
            )

            # Execute COPY TO STDOUT via CopyHandler (T016, T019, T021)
            row_count = 0
            async for csv_chunk in self.copy_handler.handle_copy_to_stdout(command):
                # Send CopyData message (T016)
                copy_data = self.copy_handler.build_copy_data(csv_chunk)
                self.writer.write(copy_data)
                await self.writer.drain()

                # Approximate row count
                row_count += csv_chunk.count(b"\n")

            # Send CopyDone message
            copy_done = self.copy_handler.build_copy_done()
            self.writer.write(copy_done)
            await self.writer.drain()

            logger.info("CopyDone sent", connection_id=self.connection_id)

            # Send CommandComplete with row count
            tag = f"COPY {row_count}\x00".encode()
            cmd_complete_length = 4 + len(tag)
            cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag
            self.writer.write(cmd_complete)
            await self.writer.drain()

            # Send ReadyForQuery
            await self.send_ready_for_query()

            logger.info(
                "COPY TO STDOUT completed successfully",
                connection_id=self.connection_id,
                rows_exported=row_count,
            )

        except Exception as e:
            logger.error("COPY TO STDOUT failed", connection_id=self.connection_id, error=str(e))
            raise

    async def handle_copy_from_stdin(self, query: str):
        """
        P6: Handle COPY FROM STDIN command

        Initiates bulk data import mode. Client will send CopyData messages
        followed by CopyDone to complete the operation.
        """
        try:
            # Parse table name and columns from COPY command
            # Example: "COPY table_name (col1, col2) FROM STDIN"
            # or: "COPY table_name FROM STDIN"
            import re

            # Match COPY table_name or COPY table_name (columns)
            match = re.match(
                r"COPY\s+(\w+)(?:\s*\(([^)]+)\))?\s+FROM\s+STDIN", query, re.IGNORECASE
            )

            if match:
                table_name = match.group(1)
                columns_str = match.group(2)
                columns = [c.strip() for c in columns_str.split(",")] if columns_str else None
            else:
                # Fallback - use default
                table_name = "benchmark_vectors"
                columns = None

            logger.info(
                "COPY FROM STDIN initiated",
                connection_id=self.connection_id,
                query=query[:100],
                table=table_name,
                columns=columns,
            )

            # Send CopyInResponse to client
            await self.send_copy_in_response()

            # Initialize copy state with back-pressure controls
            self.copy_mode = "copy_in"
            self.copy_data_buffer = []
            self.copy_table = table_name
            self.copy_columns = columns
            self.copy_buffer_size = 0  # Track buffer memory usage
            self.copy_max_buffer_size = 10 * 1024 * 1024  # 10MB buffer limit
            self.copy_batch_size = 1000  # Process in batches for memory efficiency

            logger.info(
                "COPY FROM STDIN ready for data",
                connection_id=self.connection_id,
                table=table_name,
                columns=columns,
            )

        except Exception as e:
            logger.error(
                "COPY FROM STDIN setup failed", connection_id=self.connection_id, error=str(e)
            )
            raise

    async def handle_copy_to_stdout(self, query: str):
        """
        P6: Handle COPY TO STDOUT command

        Initiates bulk data export mode. Server will send CopyData messages
        followed by CopyDone to complete the operation.
        """
        try:
            logger.info(
                "COPY TO STDOUT initiated", connection_id=self.connection_id, query=query[:100]
            )

            # Send CopyOutResponse to client
            await self.send_copy_out_response()

            # Execute query to get data for export
            # For demo, we'll export some sample vector data
            sample_data = ["id\tvector_data\n", "1\t[1,2,3]\n", "2\t[4,5,6]\n", "3\t[7,8,9]\n"]

            # Send data via CopyData messages
            for data_line in sample_data:
                await self.send_copy_data(data_line.encode("utf-8"))

            # Complete COPY operation
            await self.send_copy_done()

            logger.info(
                "COPY TO STDOUT completed",
                connection_id=self.connection_id,
                rows_exported=len(sample_data) - 1,
            )

        except Exception as e:
            logger.error("COPY TO STDOUT failed", connection_id=self.connection_id, error=str(e))
            raise

    async def handle_copy_data_message(self, body: bytes):
        """
        P6: Handle CopyData message from client with back-pressure control

        Receives bulk data during COPY FROM STDIN operation.
        Implements memory-based back-pressure to prevent buffer overflow.
        """
        try:
            if not hasattr(self, "copy_mode") or self.copy_mode != "copy_in":
                raise ValueError("Not in COPY FROM STDIN mode")

            # Check buffer size for back-pressure
            if self.copy_buffer_size + len(body) > self.copy_max_buffer_size:
                logger.warning(
                    "COPY buffer approaching limit, processing batch",
                    connection_id=self.connection_id,
                    current_size=self.copy_buffer_size,
                    incoming_size=len(body),
                    limit=self.copy_max_buffer_size,
                )

                # Process current buffer to free memory
                await self.process_copy_batch()

            # Store data in buffer
            self.copy_data_buffer.append(body)
            self.copy_buffer_size += len(body)

            logger.debug(
                "CopyData received",
                connection_id=self.connection_id,
                data_size=len(body),
                buffer_size=self.copy_buffer_size,
            )

            # Auto-process if buffer gets large (streaming mode)
            if len(self.copy_data_buffer) >= self.copy_batch_size:
                logger.info(
                    "Auto-processing COPY batch",
                    connection_id=self.connection_id,
                    batch_size=len(self.copy_data_buffer),
                )
                await self.process_copy_batch()

        except Exception as e:
            logger.error("CopyData handling failed", connection_id=self.connection_id, error=str(e))
            await self.send_copy_fail("CopyData processing failed")

    async def handle_copy_done_message(self, body: bytes):
        """
        P6: Handle CopyDone message from client

        Completes COPY FROM STDIN operation and processes all buffered data.
        """
        try:
            if not hasattr(self, "copy_mode") or self.copy_mode != "copy_in":
                raise ValueError("Not in COPY FROM STDIN mode")

            # Process all buffered data
            total_data = b"".join(self.copy_data_buffer)
            rows_processed = await self.process_copy_data(total_data)

            # Clean up copy state
            self.copy_mode = None
            self.copy_data_buffer = []
            self.copy_buffer_size = 0

            # Send CommandComplete
            await self.send_copy_complete_response(rows_processed)

            logger.info(
                "COPY FROM STDIN completed",
                connection_id=self.connection_id,
                rows_processed=rows_processed,
            )

        except Exception as e:
            logger.error("CopyDone handling failed", connection_id=self.connection_id, error=str(e))
            await self.send_copy_fail("COPY operation failed")

    async def handle_copy_fail_message(self, body: bytes):
        """
        P6: Handle CopyFail message from client

        Aborts COPY FROM STDIN operation.
        """
        try:
            error_message = body.decode("utf-8") if body else "Client requested abort"

            # Clean up copy state
            self.copy_mode = None
            self.copy_data_buffer = []
            self.copy_buffer_size = 0

            logger.info(
                "COPY operation aborted by client",
                connection_id=self.connection_id,
                reason=error_message,
            )

            # Send error response
            await self.send_error_response(
                "ERROR", "57014", "query_canceled", f"COPY operation aborted: {error_message}"
            )

        except Exception as e:
            logger.error("CopyFail handling failed", connection_id=self.connection_id, error=str(e))

    async def process_copy_data(self, data: bytes) -> int:
        """
        P6: Process bulk data from COPY FROM STDIN using IRIS LOAD DATA

        Writes data to temp file and uses IRIS LOAD DATA for efficient bulk insert.
        This is MUCH faster than individual INSERTs.
        """
        try:
            import os
            import tempfile

            # Parse COPY command metadata
            table_name = getattr(self, "copy_table", "benchmark_vectors")
            columns = getattr(self, "copy_columns", None)

            # Write data to temporary file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmpfile:
                tmpfile.write(data.decode("utf-8"))
                tmp_path = tmpfile.name

            try:
                # Build LOAD DATA command
                # IRIS LOAD DATA syntax: LOAD DATA FROM FILE 'path' INTO table (columns)
                if columns:
                    column_list = ", ".join(columns)
                    load_sql = f"LOAD DATA FROM FILE '{tmp_path}' INTO {table_name} ({column_list})"
                else:
                    load_sql = f"LOAD DATA FROM FILE '{tmp_path}' INTO {table_name}"

                logger.info(
                    "Executing LOAD DATA",
                    connection_id=self.connection_id,
                    table=table_name,
                    temp_file=tmp_path,
                    data_bytes=len(data),
                )

                # Execute LOAD DATA via IRIS
                result = await self.iris_executor.execute_query(load_sql)

                if not result.get("success", False):
                    error = result.get("error", "Unknown error")
                    logger.error("LOAD DATA failed", connection_id=self.connection_id, error=error)
                    raise RuntimeError(f"LOAD DATA failed: {error}")

                # Count lines for reporting
                line_count = data.decode("utf-8").count("\n")

                logger.info(
                    "LOAD DATA completed successfully",
                    connection_id=self.connection_id,
                    rows_loaded=line_count,
                )

                return line_count

            finally:
                # Clean up temp file
                try:
                    os.unlink(tmp_path)
                except:
                    pass

        except Exception as e:
            logger.error(
                "COPY data processing failed", connection_id=self.connection_id, error=str(e)
            )
            raise

    async def process_copy_batch(self):
        """
        P6: Process and flush current COPY buffer to control memory usage

        Implements streaming processing for back-pressure management.
        Processes batches immediately to prevent memory overflow.
        """
        try:
            if not self.copy_data_buffer:
                return

            # Process current buffer data
            total_data = b"".join(self.copy_data_buffer)
            batch_rows = await self.process_copy_data(total_data)

            logger.info(
                "COPY batch processed",
                connection_id=self.connection_id,
                batch_rows=batch_rows,
                buffer_size_mb=self.copy_buffer_size / 1024 / 1024,
            )

            # Clear buffer to free memory
            self.copy_data_buffer = []
            self.copy_buffer_size = 0

            # Force garbage collection for large batches
            if batch_rows > 10000:
                import gc

                gc.collect()

        except Exception as e:
            logger.error(
                "COPY batch processing failed", connection_id=self.connection_id, error=str(e)
            )
            # Clear buffer anyway to prevent infinite growth
            self.copy_data_buffer = []
            self.copy_buffer_size = 0
            raise

    # P6: COPY Protocol Response Messages

    async def send_copy_in_response(self):
        """Send CopyInResponse message for COPY FROM STDIN"""
        # CopyInResponse: G + length + format + field_count + field_formats
        format_code = 0  # 0=text, 1=binary

        # Use actual column count if specified, otherwise default to 2
        columns = getattr(self, "copy_columns", None)
        field_count = len(columns) if columns else 2

        # All fields in text format (0)
        field_formats = struct.pack(f"!{'H' * field_count}", *([0] * field_count))

        message_length = 4 + 1 + 2 + len(field_formats)
        message = (
            struct.pack("!cIBH", MSG_COPY_IN_RESPONSE, message_length, format_code, field_count)
            + field_formats
        )

        self.writer.write(message)
        await self.writer.drain()

        logger.debug(
            "CopyInResponse sent", connection_id=self.connection_id, field_count=field_count
        )

    async def send_copy_out_response(self):
        """Send CopyOutResponse message for COPY TO STDOUT"""
        # CopyOutResponse: H + length + format + field_count + field_formats
        format_code = 0  # 0=text, 1=binary
        field_count = 2  # id, vector_data
        field_formats = struct.pack("!HH", 0, 0)  # Both text format

        message_length = 4 + 1 + 2 + len(field_formats)
        message = (
            struct.pack("!cIBH", MSG_COPY_OUT_RESPONSE, message_length, format_code, field_count)
            + field_formats
        )

        self.writer.write(message)
        await self.writer.drain()

        logger.debug("CopyOutResponse sent", connection_id=self.connection_id)

    async def send_copy_data(self, data: bytes):
        """Send CopyData message"""
        # CopyData: d + length + data
        message_length = 4 + len(data)
        message = struct.pack("!cI", MSG_COPY_DATA, message_length) + data

        self.writer.write(message)
        await self.writer.drain()

    async def send_copy_done(self):
        """Send CopyDone message"""
        # CopyDone: c + length
        message = struct.pack("!cI", MSG_COPY_DONE, 4)
        self.writer.write(message)
        await self.writer.drain()

        logger.debug("CopyDone sent", connection_id=self.connection_id)

    async def send_copy_fail(self, error_message: str):
        """Send CopyFail message"""
        # CopyFail: f + length + error_message
        error_bytes = error_message.encode("utf-8") + b"\x00"
        message_length = 4 + len(error_bytes)
        message = struct.pack("!cI", MSG_COPY_FAIL, message_length) + error_bytes

        self.writer.write(message)
        await self.writer.drain()

        logger.debug("CopyFail sent", connection_id=self.connection_id, error=error_message)

    async def send_copy_complete_response(self, row_count: int):
        """Send CommandComplete response for COPY operation"""
        # CommandComplete: C + length + tag
        tag = f"COPY {row_count}\x00".encode()
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack("!cI", MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Send ReadyForQuery
        await self.send_ready_for_query()

        logger.info("COPY operation completed", connection_id=self.connection_id, rows=row_count)
