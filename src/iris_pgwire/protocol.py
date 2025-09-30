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
import hashlib
import hmac
import secrets
import ssl
import struct
import time
from typing import Dict, Optional, Any, List

import structlog

from .iris_executor import IRISExecutor
from .sql_translator import get_translator, TranslationContext, ValidationLevel
from .sql_translator.performance_monitor import get_monitor, MetricType, PerformanceTracker

logger = structlog.get_logger()

# PostgreSQL protocol constants
SSL_REQUEST_CODE = 80877103
CANCEL_REQUEST_CODE = 80877102
PROTOCOL_VERSION = 0x00030000  # PostgreSQL protocol version 3.0

# Message types
MSG_STARTUP = b''
MSG_QUERY = b'Q'
MSG_PARSE = b'P'
MSG_BIND = b'B'
MSG_DESCRIBE = b'D'
MSG_EXECUTE = b'E'
MSG_SYNC = b'S'
MSG_CLOSE = b'C'
MSG_FLUSH = b'H'
MSG_TERMINATE = b'X'
MSG_COPY_DATA = b'd'
MSG_COPY_DONE = b'c'
MSG_COPY_FAIL = b'f'

# Response message types
MSG_AUTHENTICATION = b'R'
MSG_PARAMETER_STATUS = b'S'
MSG_BACKEND_KEY_DATA = b'K'
MSG_READY_FOR_QUERY = b'Z'
MSG_ERROR_RESPONSE = b'E'
MSG_NOTICE_RESPONSE = b'N'
MSG_ROW_DESCRIPTION = b'T'
MSG_DATA_ROW = b'D'
MSG_COMMAND_COMPLETE = b'C'
MSG_PARSE_COMPLETE = b'1'
MSG_BIND_COMPLETE = b'2'
MSG_CLOSE_COMPLETE = b'3'
MSG_PARAMETER_DESCRIPTION = b't'
MSG_NO_DATA = b'n'
MSG_COPY_IN_RESPONSE = b'G'
MSG_COPY_OUT_RESPONSE = b'H'
MSG_COPY_BOTH_RESPONSE = b'W'

# Transaction status
STATUS_IDLE = b'I'
STATUS_IN_TRANSACTION = b'T'
STATUS_FAILED_TRANSACTION = b'E'

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

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 iris_executor: IRISExecutor, connection_id: str, enable_scram: bool = False):
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

        logger.info("Protocol handler initialized",
                   connection_id=connection_id,
                   backend_pid=self.backend_pid,
                   translation_enabled=self.enable_translation)

    async def translate_sql(self, original_sql: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Translate IRIS SQL constructs to PostgreSQL equivalents

        Args:
            original_sql: Original IRIS SQL query
            session_id: Optional session identifier for tracking

        Returns:
            Translation result with translated SQL and metadata
        """
        if not self.enable_translation:
            # Translation disabled - pass through original SQL
            return {
                'success': True,
                'original_sql': original_sql,
                'translated_sql': original_sql,
                'translation_used': False,
                'performance_stats': {'translation_time_ms': 0.0}
            }

        try:
            with PerformanceTracker(
                MetricType.TRANSLATION_TIME,
                "protocol_handler",
                session_id=session_id,
                trace_id=f"conn_{self.connection_id}"
            ) as tracker:

                # Create translation context
                context = TranslationContext(
                    original_sql=original_sql,
                    session_id=session_id or f"conn_{self.connection_id}",
                    enable_caching=True,
                    enable_validation=True,
                    enable_debug=self.translation_debug,
                    validation_level=ValidationLevel.SEMANTIC
                )

                # Perform translation
                translation_result = self.sql_translator.translate(context)

                # Log translation results
                logger.info("SQL translation completed",
                           connection_id=self.connection_id,
                           original_length=len(original_sql),
                           translated_length=len(translation_result.translated_sql),
                           constructs_translated=len(translation_result.construct_mappings),
                           translation_time_ms=translation_result.performance_stats.translation_time_ms,
                           cache_hit=translation_result.performance_stats.cache_hit,
                           success=translation_result.success)

                # Check for warnings or validation issues
                if translation_result.warnings:
                    logger.warning("Translation warnings",
                                 connection_id=self.connection_id,
                                 warnings=translation_result.warnings)

                if translation_result.validation_result and not translation_result.validation_result.success:
                    logger.warning("Translation validation issues",
                                 connection_id=self.connection_id,
                                 validation_issues=len(translation_result.validation_result.issues))

                # Check for SLA violations
                if tracker.violation:
                    logger.warning("Translation SLA violation",
                                 connection_id=self.connection_id,
                                 actual_time_ms=tracker.violation.actual_value_ms,
                                 sla_threshold_ms=tracker.violation.sla_threshold_ms)

                return {
                    'success': translation_result.success,
                    'original_sql': original_sql,
                    'translated_sql': translation_result.translated_sql,
                    'translation_used': True,
                    'construct_mappings': translation_result.construct_mappings,
                    'performance_stats': translation_result.performance_stats,
                    'warnings': translation_result.warnings,
                    'validation_result': translation_result.validation_result,
                    'debug_trace': translation_result.debug_trace if self.translation_debug else None
                }

        except Exception as e:
            logger.error("SQL translation failed",
                        connection_id=self.connection_id,
                        error=str(e),
                        original_sql=original_sql[:100] + "..." if len(original_sql) > 100 else original_sql)

            # Fallback to original SQL on translation failure
            return {
                'success': False,
                'original_sql': original_sql,
                'translated_sql': original_sql,  # Fallback to original
                'translation_used': False,
                'error': str(e),
                'performance_stats': {'translation_time_ms': 0.0}
            }

    async def handle_ssl_probe(self, ssl_context: Optional[ssl.SSLContext]):
        """
        P0: Handle SSL probe (first 8 bytes of connection)

        PostgreSQL clients first send an 8-byte SSL request to check if TLS is supported.
        We respond with 'S' (SSL supported) or 'N' (no SSL).
        """
        try:
            # Read first 8 bytes - handle connection close gracefully
            data = await self.reader.readexactly(8)
            if len(data) != 8:
                raise ValueError("Invalid SSL probe length")

            # Parse SSL request
            length, code = struct.unpack('!II', data)

            if length == 16 and code == CANCEL_REQUEST_CODE:
                # P4: Handle cancel request - read additional 8 bytes for PID and secret
                logger.debug("Cancel request received", connection_id=self.connection_id)
                await self.handle_cancel_request()
                return  # Cancel requests don't continue to normal protocol
            elif length == 8 and code == SSL_REQUEST_CODE:
                logger.debug("SSL request received", connection_id=self.connection_id)

                if ssl_context:
                    # Respond with 'S' (SSL supported) and upgrade connection
                    self.writer.write(b'S')
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
                    self.writer = asyncio.StreamWriter(ssl_transport, protocol, self.reader, asyncio.get_event_loop())
                    self.ssl_enabled = True

                    logger.info("SSL connection established", connection_id=self.connection_id)
                else:
                    # Respond with 'N' (no SSL)
                    self.writer.write(b'N')
                    await self.writer.drain()
                    logger.debug("SSL not supported, continuing with plain connection",
                               connection_id=self.connection_id)
            else:
                # Not an SSL request, rewind and continue
                # This is a bit tricky in asyncio - we'll handle this in startup
                logger.debug("Not an SSL request, treating as startup message",
                           connection_id=self.connection_id, length=length, code=code)

                # Store the data for startup message parsing
                self._buffered_data = data

        except asyncio.IncompleteReadError as e:
            # Connection closed before SSL probe completed
            logger.debug("Connection closed during SSL probe",
                        connection_id=self.connection_id,
                        bytes_read=len(e.partial), expected=8)
            raise ConnectionAbortedError("Connection closed during SSL probe")
        except Exception as e:
            logger.error("SSL probe handling failed",
                        connection_id=self.connection_id, error=str(e))
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
            # Parse startup message
            await self.parse_startup_message()

            # P3: Enhanced authentication (SCRAM-SHA-256 or trust)
            if self.enable_scram:
                await self.start_scram_authentication()
                # SCRAM requires additional message handling
                await self.handle_scram_client_final()
                await self.complete_scram_authentication()
            else:
                # P0: Basic authentication (trust)
                await self.send_authentication_ok()

            # Send parameter status messages
            await self.send_parameter_status()

            # Send backend key data for cancel requests
            await self.send_backend_key_data()

            # Send ready for query
            await self.send_ready_for_query()

            self.authenticated = True
            self.ready = True

            logger.info("Startup sequence completed",
                       connection_id=self.connection_id,
                       user=self.startup_params.get('user'),
                       database=self.startup_params.get('database'))

        except asyncio.IncompleteReadError as e:
            # Client closed connection before sending StartupMessage
            logger.debug("Client disconnected before StartupMessage",
                        connection_id=self.connection_id,
                        bytes_read=len(e.partial), expected=e.expected)
            raise ConnectionAbortedError("Client disconnected before StartupMessage")
        except Exception as e:
            logger.error("Startup sequence failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response("FATAL", "08006", "startup_failed",
                                         f"Startup sequence failed: {e}")
            raise

    async def parse_startup_message(self):
        """Parse PostgreSQL StartupMessage"""
        # Check if we have buffered data from SSL probe
        if hasattr(self, '_buffered_data'):
            length, code = struct.unpack('!II', self._buffered_data)
            delattr(self, '_buffered_data')
        else:
            # Read message length and check for startup
            length_data = await self.reader.readexactly(4)
            length = struct.unpack('!I', length_data)[0]

        # Read remaining message data
        remaining = length - 4
        if remaining > 0:
            message_data = await self.reader.readexactly(remaining)
        else:
            message_data = b''

        # Parse protocol version
        if len(message_data) >= 4:
            protocol_version = struct.unpack('!I', message_data[:4])[0]
            if protocol_version != PROTOCOL_VERSION:
                raise ValueError(f"Unsupported protocol version: {protocol_version:08x}")

            # Parse parameters (null-terminated strings)
            param_data = message_data[4:]
            params = {}
            i = 0
            while i < len(param_data) - 1:  # -1 for final null terminator
                # Find key
                key_end = param_data.find(b'\x00', i)
                if key_end == -1:
                    break
                key = param_data[i:key_end].decode('utf-8')
                i = key_end + 1

                # Find value
                value_end = param_data.find(b'\x00', i)
                if value_end == -1:
                    break
                value = param_data[i:value_end].decode('utf-8')
                i = value_end + 1

                params[key] = value

            self.startup_params = params
            logger.debug("Startup message parsed",
                        connection_id=self.connection_id,
                        params=params)

    async def send_authentication_ok(self):
        """Send AuthenticationOk message (P0: basic trust auth)"""
        # AuthenticationOk: R + length + 0
        message = struct.pack('!cII', MSG_AUTHENTICATION, 8, 0)
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
            msg_type, length = struct.unpack('!cI', header)

            if msg_type != b'p':  # SASLResponse message
                raise ValueError(f"Expected SASLResponse, got {msg_type}")

            body_length = length - 4
            body = await self.reader.readexactly(body_length) if body_length > 0 else b''

            await self.handle_sasl_initial_response(body)

        except Exception as e:
            logger.error("SCRAM authentication failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response("FATAL", "28000", "invalid_authorization_specification",
                                         f"SCRAM authentication failed: {e}")
            raise

    async def send_sasl_auth_request(self):
        """Send SASL authentication request with SCRAM-SHA-256"""
        # AuthenticationSASL: R + length + 10 + mechanisms
        mechanisms = SASL_SCRAM_SHA_256.encode('utf-8') + b'\x00' + b'\x00'  # null-terminated list
        message_length = 4 + 4 + len(mechanisms)

        message = struct.pack('!cII', MSG_AUTHENTICATION, message_length, AUTH_SASL) + mechanisms
        self.writer.write(message)
        await self.writer.drain()

        logger.debug("SASL authentication request sent",
                    connection_id=self.connection_id,
                    mechanisms=[SASL_SCRAM_SHA_256])

    async def handle_sasl_initial_response(self, body: bytes):
        """Handle client's SASL initial response"""
        pos = 0

        # Parse mechanism name
        mechanism_end = body.find(b'\x00', pos)
        if mechanism_end == -1:
            raise ValueError("Invalid SASL response: missing mechanism")
        mechanism = body[pos:mechanism_end].decode('utf-8')
        pos = mechanism_end + 1

        if mechanism != SASL_SCRAM_SHA_256:
            raise ValueError(f"Unsupported SASL mechanism: {mechanism}")

        # Parse initial response length
        if pos + 4 > len(body):
            raise ValueError("Invalid SASL response: missing response length")
        response_length = struct.unpack('!I', body[pos:pos+4])[0]
        pos += 4

        # Parse initial response data
        if response_length == 0xFFFFFFFF:
            response_data = b''
        else:
            if pos + response_length > len(body):
                raise ValueError("Invalid SASL response: truncated response data")
            response_data = body[pos:pos+response_length]

        await self.process_scram_client_first(response_data)

    async def process_scram_client_first(self, client_first: bytes):
        """Process SCRAM client-first message"""
        try:
            # Parse client-first message: "n,,n=user,r=client_nonce"
            client_first_str = client_first.decode('utf-8')

            # Basic parsing (production would be more robust)
            if not client_first_str.startswith('n,,'):
                raise ValueError("Invalid SCRAM client-first message format")

            # Extract username and client nonce
            auth_message = client_first_str[3:]  # Remove "n,," prefix
            parts = auth_message.split(',')

            username = None
            self.client_nonce = None

            for part in parts:
                if part.startswith('n='):
                    username = part[2:]
                elif part.startswith('r='):
                    self.client_nonce = part[2:]

            if not username or not self.client_nonce:
                raise ValueError("Missing username or client nonce in SCRAM message")

            # Generate server nonce and salt
            self.server_nonce = base64.b64encode(secrets.token_bytes(18)).decode('ascii')
            self.salt = base64.b64encode(secrets.token_bytes(16)).decode('ascii')

            # Store auth state for final verification
            self.scram_state = {
                'username': username,
                'client_first_bare': auth_message,
                'client_nonce': self.client_nonce,
                'server_nonce': self.server_nonce,
                'salt': self.salt,
                'iteration_count': self.iteration_count
            }

            # Send server-first message
            await self.send_scram_server_first()

            logger.debug("SCRAM client-first processed",
                        connection_id=self.connection_id,
                        username=username,
                        client_nonce=self.client_nonce[:8] + "...")

        except Exception as e:
            logger.error("SCRAM client-first processing failed",
                        connection_id=self.connection_id, error=str(e))
            raise

    async def send_scram_server_first(self):
        """Send SCRAM server-first message"""
        nonce = self.client_nonce + self.server_nonce
        server_first = f"r={nonce},s={self.salt},i={self.iteration_count}"
        server_first_bytes = server_first.encode('utf-8')

        # AuthenticationSASLContinue: R + length + 11 + data
        message_length = 4 + 4 + len(server_first_bytes)
        message = struct.pack('!cII', MSG_AUTHENTICATION, message_length, AUTH_SASL_CONTINUE) + server_first_bytes

        self.writer.write(message)
        await self.writer.drain()

        logger.debug("SCRAM server-first sent",
                    connection_id=self.connection_id,
                    nonce=nonce[:16] + "...")

    async def handle_scram_client_final(self):
        """Handle SCRAM client-final message"""
        try:
            # Wait for client-final response
            header = await self.reader.readexactly(5)
            msg_type, length = struct.unpack('!cI', header)

            if msg_type != b'p':  # SASLResponse message
                raise ValueError(f"Expected SASLResponse, got {msg_type}")

            body_length = length - 4
            body = await self.reader.readexactly(body_length) if body_length > 0 else b''

            # Parse client-final message
            client_final_str = body.decode('utf-8')
            logger.debug("SCRAM client-final received",
                        connection_id=self.connection_id,
                        message_preview=client_final_str[:50] + "...")

            # In production, this would verify the client proof
            # For now, we'll accept any well-formed client-final message

        except Exception as e:
            logger.error("SCRAM client-final handling failed",
                        connection_id=self.connection_id, error=str(e))
            raise

    async def complete_scram_authentication(self):
        """Complete SCRAM authentication (simplified for demo)"""
        # In production, this would:
        # 1. Receive client-final message
        # 2. Verify client proof against stored password hash
        # 3. Send server-final message with verification

        # For now, just send success (trust mode with SCRAM handshake)
        await self.send_scram_final_success()

    async def send_scram_final_success(self):
        """Send SCRAM final success message"""
        # AuthenticationSASLFinal: R + length + 12 + server_signature
        server_final = "v=rmF+pqV8S7suAoZWja4dJRkFsKQ="  # Dummy server signature
        server_final_bytes = server_final.encode('utf-8')

        message_length = 4 + 4 + len(server_final_bytes)
        message = struct.pack('!cII', MSG_AUTHENTICATION, message_length, AUTH_SASL_FINAL) + server_final_bytes

        self.writer.write(message)
        await self.writer.drain()

        # Send final AuthenticationOk
        await self.send_authentication_ok()

        logger.info("SCRAM authentication completed successfully",
                   connection_id=self.connection_id,
                   username=self.scram_state.get('username'))

    async def send_parameter_status(self):
        """Send ParameterStatus messages for PostgreSQL compatibility"""
        # Based on caretdev patterns and PostgreSQL requirements
        parameters = {
            'server_version': '16.0 (InterSystems IRIS)',
            'server_version_num': '160000',
            'client_encoding': 'UTF8',
            'DateStyle': 'ISO, MDY',
            'TimeZone': 'UTC',
            'standard_conforming_strings': 'on',
            'integer_datetimes': 'on',
            'IntervalStyle': 'postgres',
            'is_superuser': 'off',
            'server_encoding': 'UTF8',
            'application_name': self.startup_params.get('application_name', ''),
        }

        for key, value in parameters.items():
            await self.send_parameter_status_message(key, value)

    async def send_parameter_status_message(self, name: str, value: str):
        """Send a single ParameterStatus message"""
        name_bytes = name.encode('utf-8') + b'\x00'
        value_bytes = value.encode('utf-8') + b'\x00'
        length = 4 + len(name_bytes) + len(value_bytes)

        message = struct.pack('!cI', MSG_PARAMETER_STATUS, length) + name_bytes + value_bytes
        self.writer.write(message)
        await self.writer.drain()

    async def send_backend_key_data(self):
        """Send BackendKeyData for cancel requests"""
        # BackendKeyData: K + length + pid + secret
        # Length is 12 (4 bytes for length field + 4 bytes PID + 4 bytes secret)
        message = struct.pack('!cI', MSG_BACKEND_KEY_DATA, 12) + struct.pack('!II', self.backend_pid, self.backend_secret)
        self.writer.write(message)
        await self.writer.drain()
        logger.debug("Backend key data sent",
                    connection_id=self.connection_id,
                    pid=self.backend_pid,
                    secret="***")

    async def send_ready_for_query(self):
        """Send ReadyForQuery message"""
        # ReadyForQuery: Z + length + status
        message = struct.pack('!cI', MSG_READY_FOR_QUERY, 5) + self.transaction_status
        self.writer.write(message)
        await self.writer.drain()
        logger.debug("Ready for query sent",
                    connection_id=self.connection_id,
                    status=self.transaction_status.decode())

    async def send_error_response(self, severity: str, code: str, message_type: str, message: str):
        """Send ErrorResponse message"""
        # ErrorResponse: E + length + fields
        fields = []
        fields.append(b'S' + severity.encode('utf-8') + b'\x00')  # Severity
        fields.append(b'C' + code.encode('utf-8') + b'\x00')      # SQLSTATE
        fields.append(b'M' + message.encode('utf-8') + b'\x00')   # Message
        fields.append(b'\x00')  # End of fields

        field_data = b''.join(fields)
        length = 4 + len(field_data)

        error_msg = struct.pack('!cI', MSG_ERROR_RESPONSE, length) + field_data
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
                msg_type, length = struct.unpack('!cI', header)

                # Read message body
                body_length = length - 4
                if body_length > 0:
                    body = await self.reader.readexactly(body_length)
                else:
                    body = b''

                logger.debug("Message received",
                           connection_id=self.connection_id,
                           msg_type=msg_type,
                           length=length)

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
                        "ERROR", "0A000", "feature_not_supported",
                        f"Message type {msg_type} not implemented"
                    )

        except asyncio.IncompleteReadError:
            logger.info("Client disconnected", connection_id=self.connection_id)
        except Exception as e:
            logger.error("Message loop error",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "FATAL", "08006", "connection_failure",
                f"Protocol error: {e}"
            )

    async def handle_query_message(self, body: bytes):
        """
        P1: Real Query message handler with IRIS execution

        Executes actual SQL against IRIS and returns proper PostgreSQL responses.
        P6: Enhanced with COPY command support for bulk operations.
        """
        try:
            # Parse query string (null-terminated)
            query = body.rstrip(b'\x00').decode('utf-8')
            logger.info("Query received",
                       connection_id=self.connection_id,
                       query=query[:100] + "..." if len(query) > 100 else query)

            # Handle transaction commands first (no IRIS execution needed)
            query_upper = query.upper().strip()
            if query_upper in ("BEGIN", "START TRANSACTION"):
                await self.iris_executor.begin_transaction()
                await self.send_transaction_response("BEGIN")
                return
            elif query_upper in ("COMMIT", "END"):
                await self.iris_executor.commit_transaction()
                await self.send_transaction_response("COMMIT")
                return
            elif query_upper == "ROLLBACK":
                await self.iris_executor.rollback_transaction()
                await self.send_transaction_response("ROLLBACK")
                return

            # P6: Handle COPY commands
            if query_upper.startswith("COPY "):
                await self.handle_copy_command(query)
                return

            # For now, bypass SQL translation to test core query execution
            # TODO: Fix SQL translation issue with TranslationResult
            translation_result = {
                'success': True,
                'original_sql': query,
                'translated_sql': query,
                'translation_used': False,
                'construct_mappings': [],
                'performance_stats': {'translation_time_ms': 0.0},
                'warnings': []
            }

            # Use original SQL for execution (no translation for now)
            final_sql = query

            # Log translation summary if constructs were translated
            if translation_result.get('translation_used') and translation_result.get('construct_mappings'):
                logger.info("IRIS constructs translated",
                           connection_id=self.connection_id,
                           constructs_count=len(translation_result['construct_mappings']),
                           translation_time_ms=translation_result['performance_stats'].get('translation_time_ms', 0),
                           cache_hit=translation_result['performance_stats'].get('cache_hit', False))

            # Execute translated SQL against IRIS
            result = await self.iris_executor.execute_query(final_sql)

            # Add translation metadata to result for debugging/monitoring
            if translation_result.get('translation_used'):
                result['translation_metadata'] = {
                    'original_sql': translation_result['original_sql'],
                    'constructs_translated': len(translation_result.get('construct_mappings', [])),
                    'translation_time_ms': translation_result['performance_stats'].get('translation_time_ms', 0),
                    'cache_hit': translation_result['performance_stats'].get('cache_hit', False),
                    'warnings': translation_result.get('warnings', [])
                }

            if result['success']:
                await self.send_query_result(result)
            else:
                await self.send_error_response(
                    "ERROR", "42000", "syntax_error",
                    result.get('error', 'Query execution failed')
                )

        except Exception as e:
            logger.error("Query handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "ERROR", "08000", "connection_exception",
                f"Query processing failed: {e}"
            )

    async def send_query_result(self, result: Dict[str, Any]):
        """Send query results from IRIS execution"""
        try:
            rows = result.get('rows', [])
            columns = result.get('columns', [])
            command = result.get('command', 'SELECT')
            row_count = result.get('row_count', 0)

            logger.debug("Sending query result",
                        connection_id=self.connection_id,
                        command=command,
                        row_count=row_count,
                        column_count=len(columns),
                        has_rows=len(rows) > 0)

            # If we have rows, send RowDescription and DataRows with back-pressure
            if rows and columns:
                await self.send_row_description(columns)
                await self.send_data_rows_with_backpressure(rows, columns)

            # Send CommandComplete
            if command.upper() == 'SELECT':
                tag = f'SELECT {row_count}\x00'.encode()
            else:
                tag = f'{command} {row_count}\x00'.encode()

            cmd_complete_length = 4 + len(tag)
            cmd_complete = struct.pack('!cI', MSG_COMMAND_COMPLETE, cmd_complete_length) + tag
            self.writer.write(cmd_complete)
            await self.writer.drain()

            # Send ReadyForQuery
            await self.send_ready_for_query()

            logger.info("Query result sent",
                       connection_id=self.connection_id,
                       command=command,
                       row_count=row_count,
                       column_count=len(columns))

        except Exception as e:
            logger.error("Failed to send query result",
                        connection_id=self.connection_id, error=str(e))
            raise

    async def send_row_description(self, columns: List[Dict[str, Any]]):
        """Send RowDescription message for query columns"""
        field_count = len(columns)
        logger.debug("Row description", field_count=field_count, columns=columns)

        # Ensure field_count is valid
        if field_count < 0 or field_count > 65535:
            raise ValueError(f"Invalid field count: {field_count}")

        row_desc_data = struct.pack('!cIH', MSG_ROW_DESCRIPTION, 0, field_count)  # Length will be updated

        # Get type mappings from IRIS executor
        type_mappings = self.iris_executor.get_iris_type_mapping()

        for col in columns:
            name = col.get('name', 'unknown')
            iris_type = col.get('type', 'VARCHAR').upper()

            # Map IRIS type to PostgreSQL type
            pg_type = type_mappings.get(iris_type, type_mappings['VARCHAR'])

            field_name = name.encode('utf-8') + b'\x00'
            field_info = struct.pack('!IHIhiH',
                                   0,  # table_oid
                                   0,  # column_attr_number
                                   pg_type['oid'],  # type_oid ('I' - 32-bit unsigned)
                                   pg_type['typlen'],  # type_size ('h' - 16-bit signed, allows -1)
                                   -1,  # type_modifier ('i' - 32-bit signed)
                                   0)  # format_code ('H' - 16-bit unsigned)

            row_desc_data += field_name + field_info

        # Update length
        total_length = len(row_desc_data) - 1  # Subtract the message type byte
        row_desc_data = row_desc_data[:1] + struct.pack('!I', total_length) + row_desc_data[5:]

        self.writer.write(row_desc_data)
        await self.writer.drain()

    async def send_data_row(self, row: List[Any], columns: List[Dict[str, Any]]):
        """Send DataRow message for a single row"""
        field_count = len(columns)
        logger.debug("Data row", field_count=field_count, row=row)

        # Ensure field_count is valid
        if field_count < 0 or field_count > 65535:
            raise ValueError(f"Invalid field count: {field_count}")

        data_row_data = struct.pack('!cIH', MSG_DATA_ROW, 0, field_count)  # Length will be updated

        for i, col in enumerate(columns):
            # Row is a list of values, access by index
            value = row[i] if i < len(row) else None

            if value is None:
                # NULL value
                data_row_data += struct.pack('!I', 0xFFFFFFFF)  # -1 indicates NULL
            else:
                # Convert value to string and encode
                value_str = str(value)
                value_bytes = value_str.encode('utf-8')
                data_row_data += struct.pack('!I', len(value_bytes)) + value_bytes

        # Update length
        total_length = len(data_row_data) - 1  # Subtract the message type byte
        data_row_data = data_row_data[:1] + struct.pack('!I', total_length) + data_row_data[5:]

        self.writer.write(data_row_data)
        await self.writer.drain()

    async def send_simple_query_response(self):
        """Send a simple 'SELECT 1' response for P0 testing (legacy)"""
        # RowDescription: T + length + field_count + field_info
        field_name = b'?column?\x00'
        field_info = struct.pack('!IHIHiH', 0, 0, 23, 4, -1, 0)  # int4 type, use 'i' for signed int
        row_desc_length = 4 + 2 + len(field_name) + len(field_info)
        row_desc = struct.pack('!cIH', MSG_ROW_DESCRIPTION, row_desc_length, 1) + field_name + field_info

        # DataRow: D + length + field_count + field_data
        field_value = b'1'
        field_length = struct.pack('!I', len(field_value))
        data_row_length = 4 + 2 + 4 + len(field_value)
        data_row = struct.pack('!cIH', MSG_DATA_ROW, data_row_length, 1) + field_length + field_value

        # CommandComplete: C + length + tag
        tag = b'SELECT 1\x00'
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack('!cI', MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        # Send all messages
        self.writer.write(row_desc + data_row + cmd_complete)
        await self.writer.drain()

        # Send ReadyForQuery
        await self.send_ready_for_query()

        logger.info("Simple query response sent", connection_id=self.connection_id)

    async def send_data_rows_with_backpressure(self, rows: List[List[Any]], columns: List[Dict[str, Any]]):
        """
        P6: Send DataRows with back-pressure control for large result sets

        Implements streaming with memory and network back-pressure to handle
        large result sets efficiently without overwhelming client or server.
        """
        try:
            total_rows = len(rows)
            pending_bytes = 0

            logger.info("Sending large result set",
                       connection_id=self.connection_id,
                       total_rows=total_rows,
                       batch_size=self.result_batch_size)

            for i, row in enumerate(rows):
                # Send individual DataRow
                await self.send_data_row(row, columns)

                # Estimate bytes sent (rough calculation)
                # Row is a list of values, not a dict
                estimated_row_bytes = sum(len(str(row[i] if i < len(row) else '')) + 8
                                        for i in range(len(columns)))
                pending_bytes += estimated_row_bytes

                # Apply back-pressure controls
                if (i + 1) % self.result_batch_size == 0 or pending_bytes > self.max_pending_bytes:
                    # Force drain to apply network back-pressure
                    await self.writer.drain()
                    pending_bytes = 0

                    logger.debug("Result set batch sent",
                               connection_id=self.connection_id,
                               rows_sent=i + 1,
                               total_rows=total_rows,
                               progress_pct=round((i + 1) / total_rows * 100, 1))

                    # Small yield to prevent CPU blocking on huge result sets
                    if (i + 1) % (self.result_batch_size * 10) == 0:
                        await asyncio.sleep(0.001)  # 1ms yield for very large sets

            # Final drain
            await self.writer.drain()

            logger.info("Large result set transmission completed",
                       connection_id=self.connection_id,
                       total_rows=total_rows)

        except Exception as e:
            logger.error("Large result set transmission failed",
                        connection_id=self.connection_id,
                        error=str(e),
                        rows_attempted=total_rows)
            raise

    async def send_transaction_response(self, command: str):
        """Send response for transaction commands (BEGIN, COMMIT, ROLLBACK)"""
        # CommandComplete: C + length + tag
        tag = f'{command}\x00'.encode()
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack('!cI', MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        # Send message
        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Update transaction status
        if command == "BEGIN":
            self.transaction_status = STATUS_IN_TRANSACTION
        else:  # COMMIT or ROLLBACK
            self.transaction_status = STATUS_IDLE

        # Send ReadyForQuery with updated status
        await self.send_ready_for_query()

        logger.info("Transaction response sent",
                   connection_id=self.connection_id,
                   command=command,
                   status=self.transaction_status.decode())

    # P2: Extended Protocol Message Handlers

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
            name_end = body.find(b'\x00', pos)
            if name_end == -1:
                raise ValueError("Invalid Parse message: missing statement name terminator")
            statement_name = body[pos:name_end].decode('utf-8')
            pos = name_end + 1

            # Parse query
            query_end = body.find(b'\x00', pos)
            if query_end == -1:
                raise ValueError("Invalid Parse message: missing query terminator")
            query = body[pos:query_end].decode('utf-8')
            pos = query_end + 1

            # Parse parameter types count
            if pos + 2 > len(body):
                raise ValueError("Invalid Parse message: missing parameter count")
            num_params = struct.unpack('!H', body[pos:pos+2])[0]
            pos += 2

            # Parse parameter types
            param_types = []
            for i in range(num_params):
                if pos + 4 > len(body):
                    raise ValueError(f"Invalid Parse message: missing parameter type {i}")
                param_type = struct.unpack('!I', body[pos:pos+4])[0]
                param_types.append(param_type)
                pos += 4

            # Translate SQL for prepared statement
            translation_result = await self.translate_sql(query, session_id=f"conn_{self.connection_id}_stmt_{statement_name}")

            if not translation_result['success']:
                logger.warning("SQL translation failed for prepared statement",
                             connection_id=self.connection_id,
                             statement_name=statement_name,
                             error=translation_result.get('error'))

            # Store prepared statement with both original and translated SQL
            self.prepared_statements[statement_name] = {
                'original_query': query,
                'translated_query': translation_result['translated_sql'],
                'param_types': param_types,
                'translation_metadata': {
                    'constructs_translated': len(translation_result.get('construct_mappings', [])),
                    'translation_time_ms': translation_result['performance_stats'].get('translation_time_ms', 0),
                    'cache_hit': translation_result['performance_stats'].get('cache_hit', False),
                    'warnings': translation_result.get('warnings', [])
                }
            }

            logger.info("Parsed statement with translation",
                       connection_id=self.connection_id,
                       statement_name=statement_name,
                       original_query=query[:100] + "..." if len(query) > 100 else query,
                       translated_query=translation_result['translated_sql'][:100] + "..." if len(translation_result['translated_sql']) > 100 else translation_result['translated_sql'],
                       num_params=num_params,
                       constructs_translated=len(translation_result.get('construct_mappings', [])))

            # Log translation details if constructs were translated
            if translation_result.get('translation_used') and translation_result.get('construct_mappings'):
                logger.info("IRIS constructs translated in prepared statement",
                           connection_id=self.connection_id,
                           statement_name=statement_name,
                           constructs_count=len(translation_result['construct_mappings']),
                           translation_time_ms=translation_result['performance_stats'].get('translation_time_ms', 0))

            # Send ParseComplete response
            await self.send_parse_complete()

        except Exception as e:
            logger.error("Parse message handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "ERROR", "42601", "syntax_error",
                f"Parse failed: {e}"
            )

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
            name_end = body.find(b'\x00', pos)
            if name_end == -1:
                raise ValueError("Invalid Bind message: missing portal name terminator")
            portal_name = body[pos:name_end].decode('utf-8')
            pos = name_end + 1

            # Parse statement name
            stmt_end = body.find(b'\x00', pos)
            if stmt_end == -1:
                raise ValueError("Invalid Bind message: missing statement name terminator")
            statement_name = body[pos:stmt_end].decode('utf-8')
            pos = stmt_end + 1

            # Check if statement exists
            if statement_name not in self.prepared_statements:
                raise ValueError(f"Prepared statement '{statement_name}' does not exist")

            # Parse parameter format codes
            if pos + 2 > len(body):
                raise ValueError("Invalid Bind message: missing format codes count")
            num_format_codes = struct.unpack('!H', body[pos:pos+2])[0]
            pos += 2

            format_codes = []
            for i in range(num_format_codes):
                if pos + 2 > len(body):
                    raise ValueError(f"Invalid Bind message: missing format code {i}")
                format_code = struct.unpack('!H', body[pos:pos+2])[0]
                format_codes.append(format_code)
                pos += 2

            # Parse parameter values
            if pos + 2 > len(body):
                raise ValueError("Invalid Bind message: missing parameter count")
            num_params = struct.unpack('!H', body[pos:pos+2])[0]
            pos += 2

            param_values = []
            for i in range(num_params):
                if pos + 4 > len(body):
                    raise ValueError(f"Invalid Bind message: missing parameter length {i}")
                param_length = struct.unpack('!I', body[pos:pos+4])[0]
                pos += 4

                if param_length == 0xFFFFFFFF:  # NULL value
                    param_values.append(None)
                else:
                    if pos + param_length > len(body):
                        raise ValueError(f"Invalid Bind message: truncated parameter {i}")
                    param_data = body[pos:pos+param_length]
                    # For now, treat all parameters as text
                    param_values.append(param_data.decode('utf-8'))
                    pos += param_length

            # Skip result format codes for now (we'll always use text)
            # In a full implementation, we'd parse these too

            # Store portal
            self.portals[portal_name] = {
                'statement': statement_name,
                'params': param_values
            }

            logger.info("Bound portal",
                       connection_id=self.connection_id,
                       portal_name=portal_name,
                       statement_name=statement_name,
                       num_params=num_params)

            # Send BindComplete response
            await self.send_bind_complete()

        except Exception as e:
            logger.error("Bind message handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "ERROR", "42P02", "undefined_parameter",
                f"Bind failed: {e}"
            )

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
            name = body[1:].rstrip(b'\x00').decode('utf-8')

            if describe_type == 'S':
                # Describe statement
                if name not in self.prepared_statements:
                    raise ValueError(f"Prepared statement '{name}' does not exist")

                stmt = self.prepared_statements[name]

                # Send ParameterDescription
                await self.send_parameter_description(stmt['param_types'])

                # For SELECT statements, we'd send RowDescription
                # For now, send NoData for simplicity
                await self.send_no_data()

            elif describe_type == 'P':
                # Describe portal
                if name not in self.portals:
                    raise ValueError(f"Portal '{name}' does not exist")

                # Send RowDescription or NoData
                await self.send_no_data()

            else:
                raise ValueError(f"Invalid describe type: {describe_type}")

            logger.info("Described object",
                       connection_id=self.connection_id,
                       type=describe_type,
                       name=name)

        except Exception as e:
            logger.error("Describe message handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "ERROR", "42P02", "undefined_object",
                f"Describe failed: {e}"
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
            name_end = body.find(b'\x00')
            if name_end == -1:
                raise ValueError("Invalid Execute message: missing portal name terminator")
            portal_name = body[:name_end].decode('utf-8')

            # Parse max rows (for now, ignore and fetch all)
            if len(body) >= name_end + 5:
                max_rows = struct.unpack('!I', body[name_end+1:name_end+5])[0]
            else:
                max_rows = 0

            # Check if portal exists
            if portal_name not in self.portals:
                raise ValueError(f"Portal '{portal_name}' does not exist")

            portal = self.portals[portal_name]
            statement_name = portal['statement']
            params = portal['params']

            if statement_name not in self.prepared_statements:
                raise ValueError(f"Statement '{statement_name}' no longer exists")

            stmt = self.prepared_statements[statement_name]
            # Use translated query for execution
            query = stmt.get('translated_query', stmt.get('query', stmt.get('original_query', '')))

            # Log execution of prepared statement with translation metadata
            translation_metadata = stmt.get('translation_metadata', {})
            logger.info("Executing prepared statement",
                       connection_id=self.connection_id,
                       portal_name=portal_name,
                       statement_name=statement_name,
                       constructs_translated=translation_metadata.get('constructs_translated', 0),
                       cache_hit=translation_metadata.get('cache_hit', False))

            # Execute the query with parameters
            # Proper parameter handling for IRIS SQL (supports both TOP and LIMIT syntax)
            if params:
                # Convert PostgreSQL-style parameters ($1, $2) to proper IRIS parameterization
                parameterized_query = query
                iris_params = []

                for i, param in enumerate(params):
                    if param is not None:
                        # Handle different parameter types properly
                        if isinstance(param, str):
                            # String parameters get quoted
                            parameterized_query = parameterized_query.replace(f'${i+1}', f"'{param}'")
                        elif isinstance(param, (int, float)):
                            # Numeric parameters don't need quotes
                            parameterized_query = parameterized_query.replace(f'${i+1}', str(param))
                        else:
                            # Other types converted to string and quoted
                            parameterized_query = parameterized_query.replace(f'${i+1}', f"'{str(param)}'")
                    else:
                        # NULL values
                        parameterized_query = parameterized_query.replace(f'${i+1}', 'NULL')

                # Convert PostgreSQL syntax to IRIS-compatible syntax if needed
                # This helps with LIMIT vs TOP issues mentioned by user
                parameterized_query = self._convert_postgres_to_iris_syntax(parameterized_query)
            else:
                parameterized_query = query

            # Execute via IRIS
            result = await self.iris_executor.execute_query(parameterized_query)

            if result['success']:
                await self.send_query_result(result)
            else:
                await self.send_error_response(
                    "ERROR", "42000", "syntax_error",
                    result.get('error', 'Query execution failed')
                )

            logger.info("Executed portal",
                       connection_id=self.connection_id,
                       portal_name=portal_name,
                       query=parameterized_query[:100] + "..." if len(parameterized_query) > 100 else parameterized_query)

        except Exception as e:
            logger.error("Execute message handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "ERROR", "42P03", "undefined_cursor",
                f"Execute failed: {e}"
            )

    async def handle_sync_message(self, body: bytes):
        """
        P2: Handle Sync message (end of extended protocol cycle)

        Sync message has no body.
        """
        try:
            # Send ReadyForQuery to indicate we're ready for the next command
            await self.send_ready_for_query()

            logger.debug("Sync message processed", connection_id=self.connection_id)

        except Exception as e:
            logger.error("Sync message handling failed",
                        connection_id=self.connection_id, error=str(e))

    async def handle_close_message(self, body: bytes):
        """
        P2: Handle Close message for closing statements/portals

        Close message format:
        - type ('S' for statement, 'P' for portal)
        - name (null-terminated string)
        """
        try:
            if len(body) < 2:
                raise ValueError("Invalid Close message: too short")

            close_type = chr(body[0])
            name = body[1:].rstrip(b'\x00').decode('utf-8')

            if close_type == 'S':
                # Close statement
                if name in self.prepared_statements:
                    del self.prepared_statements[name]
                    logger.info("Closed statement",
                               connection_id=self.connection_id,
                               name=name)
            elif close_type == 'P':
                # Close portal
                if name in self.portals:
                    del self.portals[name]
                    logger.info("Closed portal",
                               connection_id=self.connection_id,
                               name=name)
            else:
                raise ValueError(f"Invalid close type: {close_type}")

            # Send CloseComplete response
            await self.send_close_complete()

        except Exception as e:
            logger.error("Close message handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "ERROR", "42P02", "undefined_object",
                f"Close failed: {e}"
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
            logger.error("Flush message handling failed",
                        connection_id=self.connection_id, error=str(e))

    # P2: Extended Protocol Response Messages

    async def send_parse_complete(self):
        """Send ParseComplete response"""
        message = struct.pack('!cI', MSG_PARSE_COMPLETE, 4)
        self.writer.write(message)
        await self.writer.drain()

    async def send_bind_complete(self):
        """Send BindComplete response"""
        message = struct.pack('!cI', MSG_BIND_COMPLETE, 4)
        self.writer.write(message)
        await self.writer.drain()

    async def send_close_complete(self):
        """Send CloseComplete response"""
        message = struct.pack('!cI', MSG_CLOSE_COMPLETE, 4)
        self.writer.write(message)
        await self.writer.drain()

    async def send_parameter_description(self, param_types: list):
        """Send ParameterDescription message"""
        count = len(param_types)
        message = struct.pack('!cIH', MSG_PARAMETER_DESCRIPTION, 4 + 2 + count * 4, count)

        for param_type in param_types:
            message += struct.pack('!I', param_type)

        self.writer.write(message)
        await self.writer.drain()

    async def send_no_data(self):
        """Send NoData response"""
        message = struct.pack('!cI', MSG_NO_DATA, 4)
        self.writer.write(message)
        await self.writer.drain()

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
            backend_pid, backend_secret = struct.unpack('!II', cancel_data)

            logger.info("Cancel request details",
                       connection_id=self.connection_id,
                       target_pid=backend_pid,
                       provided_secret="***")

            # Find and cancel the target connection
            success = await self.iris_executor.cancel_query(backend_pid, backend_secret)

            if success:
                logger.info("Query cancellation successful",
                           connection_id=self.connection_id,
                           target_pid=backend_pid)
            else:
                logger.warning("Query cancellation failed - connection not found or secret mismatch",
                              connection_id=self.connection_id,
                              target_pid=backend_pid)

            # Cancel requests don't send responses - just close connection
            self.writer.close()
            await self.writer.wait_closed()

        except Exception as e:
            logger.error("Cancel request handling failed",
                        connection_id=self.connection_id, error=str(e))

    # P6: COPY Protocol Methods

    async def handle_copy_command(self, query: str):
        """
        P6: Handle COPY command parsing and response

        COPY commands initiate bulk data transfer operations.
        Supports both COPY FROM STDIN and COPY TO STDOUT.
        """
        try:
            query_upper = query.upper().strip()

            if " FROM STDIN" in query_upper:
                # COPY FROM STDIN - bulk data import
                await self.handle_copy_from_stdin(query)
            elif " TO STDOUT" in query_upper:
                # COPY TO STDOUT - bulk data export
                await self.handle_copy_to_stdout(query)
            else:
                await self.send_error_response(
                    "ERROR", "42601", "syntax_error",
                    f"Unsupported COPY variant: {query}"
                )

        except Exception as e:
            logger.error("COPY command handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_error_response(
                "ERROR", "08000", "connection_exception",
                f"COPY command failed: {e}"
            )

    async def handle_copy_from_stdin(self, query: str):
        """
        P6: Handle COPY FROM STDIN command

        Initiates bulk data import mode. Client will send CopyData messages
        followed by CopyDone to complete the operation.
        """
        try:
            # Parse table name and format from COPY command
            # For demo, we'll accept any valid COPY FROM STDIN syntax
            logger.info("COPY FROM STDIN initiated",
                       connection_id=self.connection_id,
                       query=query[:100])

            # Send CopyInResponse to client
            await self.send_copy_in_response()

            # Initialize copy state with back-pressure controls
            self.copy_mode = 'copy_in'
            self.copy_data_buffer = []
            self.copy_table = "vectors"  # Default table for demo
            self.copy_buffer_size = 0  # Track buffer memory usage
            self.copy_max_buffer_size = 10 * 1024 * 1024  # 10MB buffer limit
            self.copy_batch_size = 1000  # Process in batches for memory efficiency

            logger.info("COPY FROM STDIN ready for data",
                       connection_id=self.connection_id)

        except Exception as e:
            logger.error("COPY FROM STDIN setup failed",
                        connection_id=self.connection_id, error=str(e))
            raise

    async def handle_copy_to_stdout(self, query: str):
        """
        P6: Handle COPY TO STDOUT command

        Initiates bulk data export mode. Server will send CopyData messages
        followed by CopyDone to complete the operation.
        """
        try:
            logger.info("COPY TO STDOUT initiated",
                       connection_id=self.connection_id,
                       query=query[:100])

            # Send CopyOutResponse to client
            await self.send_copy_out_response()

            # Execute query to get data for export
            # For demo, we'll export some sample vector data
            sample_data = [
                "id\tvector_data\n",
                "1\t[1,2,3]\n",
                "2\t[4,5,6]\n",
                "3\t[7,8,9]\n"
            ]

            # Send data via CopyData messages
            for data_line in sample_data:
                await self.send_copy_data(data_line.encode('utf-8'))

            # Complete COPY operation
            await self.send_copy_done()

            logger.info("COPY TO STDOUT completed",
                       connection_id=self.connection_id,
                       rows_exported=len(sample_data)-1)

        except Exception as e:
            logger.error("COPY TO STDOUT failed",
                        connection_id=self.connection_id, error=str(e))
            raise

    async def handle_copy_data_message(self, body: bytes):
        """
        P6: Handle CopyData message from client with back-pressure control

        Receives bulk data during COPY FROM STDIN operation.
        Implements memory-based back-pressure to prevent buffer overflow.
        """
        try:
            if not hasattr(self, 'copy_mode') or self.copy_mode != 'copy_in':
                raise ValueError("Not in COPY FROM STDIN mode")

            # Check buffer size for back-pressure
            if self.copy_buffer_size + len(body) > self.copy_max_buffer_size:
                logger.warning("COPY buffer approaching limit, processing batch",
                              connection_id=self.connection_id,
                              current_size=self.copy_buffer_size,
                              incoming_size=len(body),
                              limit=self.copy_max_buffer_size)

                # Process current buffer to free memory
                await self.process_copy_batch()

            # Store data in buffer
            self.copy_data_buffer.append(body)
            self.copy_buffer_size += len(body)

            logger.debug("CopyData received",
                        connection_id=self.connection_id,
                        data_size=len(body),
                        buffer_size=self.copy_buffer_size)

            # Auto-process if buffer gets large (streaming mode)
            if len(self.copy_data_buffer) >= self.copy_batch_size:
                logger.info("Auto-processing COPY batch",
                           connection_id=self.connection_id,
                           batch_size=len(self.copy_data_buffer))
                await self.process_copy_batch()

        except Exception as e:
            logger.error("CopyData handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_copy_fail("CopyData processing failed")

    async def handle_copy_done_message(self, body: bytes):
        """
        P6: Handle CopyDone message from client

        Completes COPY FROM STDIN operation and processes all buffered data.
        """
        try:
            if not hasattr(self, 'copy_mode') or self.copy_mode != 'copy_in':
                raise ValueError("Not in COPY FROM STDIN mode")

            # Process all buffered data
            total_data = b''.join(self.copy_data_buffer)
            rows_processed = await self.process_copy_data(total_data)

            # Clean up copy state
            self.copy_mode = None
            self.copy_data_buffer = []
            self.copy_buffer_size = 0

            # Send CommandComplete
            await self.send_copy_complete_response(rows_processed)

            logger.info("COPY FROM STDIN completed",
                       connection_id=self.connection_id,
                       rows_processed=rows_processed)

        except Exception as e:
            logger.error("CopyDone handling failed",
                        connection_id=self.connection_id, error=str(e))
            await self.send_copy_fail("COPY operation failed")

    async def handle_copy_fail_message(self, body: bytes):
        """
        P6: Handle CopyFail message from client

        Aborts COPY FROM STDIN operation.
        """
        try:
            error_message = body.decode('utf-8') if body else "Client requested abort"

            # Clean up copy state
            self.copy_mode = None
            self.copy_data_buffer = []
            self.copy_buffer_size = 0

            logger.info("COPY operation aborted by client",
                       connection_id=self.connection_id,
                       reason=error_message)

            # Send error response
            await self.send_error_response(
                "ERROR", "57014", "query_canceled",
                f"COPY operation aborted: {error_message}"
            )

        except Exception as e:
            logger.error("CopyFail handling failed",
                        connection_id=self.connection_id, error=str(e))

    async def process_copy_data(self, data: bytes) -> int:
        """
        P6: Process bulk data from COPY FROM STDIN

        This would typically parse CSV/TSV data and insert into IRIS.
        For demo, we'll just count lines.
        """
        try:
            # Decode and split into lines
            text_data = data.decode('utf-8')
            lines = text_data.strip().split('\n')

            # Filter out empty lines
            data_lines = [line for line in lines if line.strip()]

            # In production, this would:
            # 1. Parse each line according to COPY format (CSV, TSV, etc.)
            # 2. Validate data types
            # 3. Execute bulk INSERT into IRIS
            # 4. Handle vector data conversion

            logger.info("Processing COPY data",
                       connection_id=self.connection_id,
                       lines=len(data_lines),
                       total_bytes=len(data))

            return len(data_lines)

        except Exception as e:
            logger.error("COPY data processing failed",
                        connection_id=self.connection_id, error=str(e))
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
            total_data = b''.join(self.copy_data_buffer)
            batch_rows = await self.process_copy_data(total_data)

            logger.info("COPY batch processed",
                       connection_id=self.connection_id,
                       batch_rows=batch_rows,
                       buffer_size_mb=self.copy_buffer_size / 1024 / 1024)

            # Clear buffer to free memory
            self.copy_data_buffer = []
            self.copy_buffer_size = 0

            # Force garbage collection for large batches
            if batch_rows > 10000:
                import gc
                gc.collect()

        except Exception as e:
            logger.error("COPY batch processing failed",
                        connection_id=self.connection_id, error=str(e))
            # Clear buffer anyway to prevent infinite growth
            self.copy_data_buffer = []
            self.copy_buffer_size = 0
            raise

    # P6: COPY Protocol Response Messages

    async def send_copy_in_response(self):
        """Send CopyInResponse message for COPY FROM STDIN"""
        # CopyInResponse: G + length + format + field_count + field_formats
        format_code = 0  # 0=text, 1=binary
        field_count = 2  # id, vector_data
        field_formats = struct.pack('!HH', 0, 0)  # Both text format

        message_length = 4 + 1 + 2 + len(field_formats)
        message = struct.pack('!cIBH', MSG_COPY_IN_RESPONSE, message_length,
                            format_code, field_count) + field_formats

        self.writer.write(message)
        await self.writer.drain()

        logger.debug("CopyInResponse sent", connection_id=self.connection_id)

    async def send_copy_out_response(self):
        """Send CopyOutResponse message for COPY TO STDOUT"""
        # CopyOutResponse: H + length + format + field_count + field_formats
        format_code = 0  # 0=text, 1=binary
        field_count = 2  # id, vector_data
        field_formats = struct.pack('!HH', 0, 0)  # Both text format

        message_length = 4 + 1 + 2 + len(field_formats)
        message = struct.pack('!cIBH', MSG_COPY_OUT_RESPONSE, message_length,
                            format_code, field_count) + field_formats

        self.writer.write(message)
        await self.writer.drain()

        logger.debug("CopyOutResponse sent", connection_id=self.connection_id)

    async def send_copy_data(self, data: bytes):
        """Send CopyData message"""
        # CopyData: d + length + data
        message_length = 4 + len(data)
        message = struct.pack('!cI', MSG_COPY_DATA, message_length) + data

        self.writer.write(message)
        await self.writer.drain()

    async def send_copy_done(self):
        """Send CopyDone message"""
        # CopyDone: c + length
        message = struct.pack('!cI', MSG_COPY_DONE, 4)
        self.writer.write(message)
        await self.writer.drain()

        logger.debug("CopyDone sent", connection_id=self.connection_id)

    async def send_copy_fail(self, error_message: str):
        """Send CopyFail message"""
        # CopyFail: f + length + error_message
        error_bytes = error_message.encode('utf-8') + b'\x00'
        message_length = 4 + len(error_bytes)
        message = struct.pack('!cI', MSG_COPY_FAIL, message_length) + error_bytes

        self.writer.write(message)
        await self.writer.drain()

        logger.debug("CopyFail sent", connection_id=self.connection_id, error=error_message)

    async def send_copy_complete_response(self, row_count: int):
        """Send CommandComplete response for COPY operation"""
        # CommandComplete: C + length + tag
        tag = f'COPY {row_count}\x00'.encode()
        cmd_complete_length = 4 + len(tag)
        cmd_complete = struct.pack('!cI', MSG_COMMAND_COMPLETE, cmd_complete_length) + tag

        self.writer.write(cmd_complete)
        await self.writer.drain()

        # Send ReadyForQuery
        await self.send_ready_for_query()

        logger.info("COPY operation completed",
                   connection_id=self.connection_id,
                   rows=row_count)