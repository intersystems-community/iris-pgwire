import struct
from typing import List, Optional


class ProtocolError(Exception):
    pass


class StrictProtocolValidator:
    def __init__(self):
        self.current_field_count: int | None = None
        self.messages: list[str] = []

    def validate(self, raw_bytes: bytes) -> None:
        offset = 0
        while offset < len(raw_bytes):
            if offset + 5 > len(raw_bytes):
                raise ProtocolError(f"Truncated message header at offset {offset}")

            msg_type = chr(raw_bytes[offset])
            msg_len = struct.unpack(">I", raw_bytes[offset + 1 : offset + 5])[0]

            if offset + 1 + msg_len > len(raw_bytes):
                raise ProtocolError(
                    f"Message length {msg_len} exceeds remaining bytes at offset {offset}"
                )

            msg_payload = raw_bytes[offset + 5 : offset + 1 + msg_len]

            if msg_type == "T":
                self._handle_row_description(msg_payload)
            elif msg_type == "D":
                self._handle_data_row(msg_payload)

            offset += 1 + msg_len

    def _handle_row_description(self, payload: bytes) -> None:
        if len(payload) < 2:
            raise ProtocolError("RowDescription too short")

        num_fields = struct.unpack(">H", payload[0:2])[0]
        offset = 2

        for i in range(num_fields):
            null_pos = payload.find(b"\x00", offset)
            if null_pos == -1:
                raise ProtocolError(f"Field {i} name not null-terminated")

            offset = null_pos + 1

            if offset + 18 > len(payload):
                raise ProtocolError(f"Field {i} description truncated")

            offset += 18

        if offset != len(payload):
            raise ProtocolError("RowDescription length mismatch")

        self.current_field_count = num_fields

    def _handle_data_row(self, payload: bytes) -> None:
        if self.current_field_count is None:
            raise ProtocolError("DataRow received before RowDescription")

        if len(payload) < 2:
            raise ProtocolError("DataRow too short")

        num_cols = struct.unpack(">H", payload[0:2])[0]
        if num_cols != self.current_field_count:
            raise ProtocolError(
                f"Field count mismatch: expected {self.current_field_count}, got {num_cols}"
            )

        offset = 2
        for i in range(num_cols):
            if offset + 4 > len(payload):
                raise ProtocolError(f"Column {i} length field truncated")

            col_len = struct.unpack(">i", payload[offset : offset + 4])[0]
            offset += 4

            if col_len == -1:
                continue

            if col_len < 0:
                raise ProtocolError(f"Column {i} invalid length {col_len}")

            if offset + col_len > len(payload):
                raise ProtocolError(f"Column {i} data truncated")

            offset += col_len

        if offset != len(payload):
            raise ProtocolError("DataRow length mismatch")
