import asyncio
import re
import threading
from typing import Any

import structlog

from .metadata_cache import ColumnMetadata, MetadataCache

logger = structlog.get_logger()


class _AsyncCoroutineRunner:
    """Runs async coroutines on a dedicated background loop."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()


class DefaultValuesTranslator:
    """Rewrites INSERT statements that rely on DEFAULT literals."""

    _INSERT_PATTERN = re.compile(
        r"^\s*INSERT\s+INTO\s+"  # INSERT INTO
        r"(?P<table>(?:(?:\"[^\"]+\"|\w+)(?:\s*\.\s*(?:\"[^\"]+\"|\w+))?))"
        r"(?:\s*\((?P<columns>[^)]*)\))?\s*VALUES\s*",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(
        self, metadata_cache: MetadataCache | None = None, executor: Any | None = None
    ) -> None:
        self.metadata_cache = metadata_cache
        self.executor = executor
        self._async_runner: _AsyncCoroutineRunner | None = None

    def translate(self, sql: str, executor: Any | None = None) -> str:
        effective_executor = executor or self.executor
        if self.metadata_cache and effective_executor:
            rewritten = self._try_smart_translate(sql, effective_executor)
            if rewritten is not None:
                return rewritten
        return self._legacy_translate(sql)

    def _try_smart_translate(self, sql: str, executor: Any) -> str | None:
        match = self._INSERT_PATTERN.match(sql)
        if not match:
            return None

        table_identifier = match.group("table")
        columns_text = match.group("columns")
        values_start = match.end()
        values_section = self._extract_values_section(sql, values_start)
        if not values_section:
            return None

        values_text, values_end = values_section
        tuples = self._parse_value_tuples(values_text)
        if not tuples:
            return None

        parsed_rows = [self._split_sql_expressions(t[1:-1]) for t in tuples]
        if not parsed_rows or any(not row for row in parsed_rows):
            return None

        schema, table = self._parse_schema_table(table_identifier)
        if not schema or not table:
            return None

        metadata = self._get_column_metadata(schema, table, executor)
        if not metadata:
            return None

        prefix = sql[: match.start()]
        suffix = sql[values_end:]

        try:
            if columns_text:
                columns = [col.strip() for col in self._split_sql_expressions(columns_text)]
                rewritten = self._rewrite_with_column_list(
                    table_identifier, columns, parsed_rows, metadata
                )
            else:
                rewritten = self._rewrite_without_column_list(
                    table_identifier, parsed_rows, metadata
                )
        except ValueError:
            raise

        if not rewritten:
            return None

        return f"{prefix}{rewritten}{suffix}"

    def _rewrite_with_column_list(
        self,
        table_identifier: str,
        columns: list[str],
        rows: list[list[str]],
        metadata: ColumnMetadata,
    ) -> str | None:
        if any(len(row) != len(columns) for row in rows):
            return None

        column_infos: list[dict[str, Any]] = []
        for idx, column in enumerate(columns):
            normalized = self._normalize_identifier(column)
            default_flags = [self._value_is_default(row[idx]) for row in rows]
            meta = metadata.get(normalized)
            column_infos.append(
                {
                    "name": column,
                    "normalized": normalized,
                    "meta": meta,
                    "default_flags": default_flags,
                }
            )

        for info in column_infos:
            if any(info["default_flags"]) and info["meta"] is None:
                logger.warning(
                    "Missing metadata for column with DEFAULT",
                    column=info["name"],
                    table=table_identifier,
                )
                return None

        remove_indices: set[int] = set()
        for idx, info in enumerate(column_infos):
            if not info["meta"]:
                continue
            default_expr = info["meta"].get("column_default")
            if default_expr is not None and all(info["default_flags"]):
                remove_indices.add(idx)

        remaining_columns = [
            info["name"] for idx, info in enumerate(column_infos) if idx not in remove_indices
        ]

        replaced_rows: list[list[str]] = []
        for row_idx, row in enumerate(rows):
            new_row: list[str] = []
            for col_idx, value in enumerate(row):
                if col_idx in remove_indices:
                    continue
                info = column_infos[col_idx]
                if info["default_flags"][row_idx]:
                    replacement = self._resolve_default(info["meta"], info["name"])
                    new_row.append(replacement)
                else:
                    new_row.append(value)
            replaced_rows.append(new_row)

        if not remaining_columns:
            if len(rows) == 1:
                return f"INSERT INTO {table_identifier} DEFAULT VALUES"
            logger.warning(
                "Cannot rewrite multi-row INSERT when all columns drop to DEFAULT",
                table=table_identifier,
            )
            return None

        values_section = self._compose_values_section(replaced_rows)
        return self._build_standard_insert(table_identifier, remaining_columns, values_section)

    def _rewrite_without_column_list(
        self,
        table_identifier: str,
        rows: list[list[str]],
        metadata: ColumnMetadata,
    ) -> str | None:
        metadata_items = list(metadata.items())
        if not metadata_items:
            return None

        if any(len(row) != len(metadata_items) for row in rows):
            return None

        replaced_rows: list[list[str]] = []
        for row in rows:
            new_row: list[str] = []
            for idx, value in enumerate(row):
                if self._value_is_default(value):
                    column_name, column_meta = metadata_items[idx]
                    replacement = self._resolve_default(column_meta, column_name)
                    new_row.append(replacement)
                else:
                    new_row.append(value)
            replaced_rows.append(new_row)
        values_section = self._compose_values_section(replaced_rows)
        return self._build_standard_insert(table_identifier, [], values_section)

    def _get_column_metadata(self, schema: str, table: str, executor: Any) -> ColumnMetadata:
        if not self.metadata_cache or not executor:
            return {}

        try:
            runner = self._ensure_runner()
            return runner.run(self.metadata_cache.get_column_metadata(schema, table, executor))
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning(
                "Failed to load metadata",
                schema=schema,
                table=table,
                error=str(exc),
            )
            return {}

    def _compose_values_section(self, rows: list[list[str]]) -> str:
        values: list[str] = []
        for row in rows:
            values.append(f"({', '.join(row)})")
        return ", ".join(values)

    def _value_is_default(self, value: str) -> bool:
        return value.strip().upper() == "DEFAULT"

    def _resolve_default(self, meta: dict[str, Any] | None, column: str) -> str:
        if meta is None:
            raise ValueError(f"No metadata available for column {column}")

        default_expr = meta.get("column_default")
        if default_expr is not None:
            return str(default_expr)

        if self._is_nullable(meta):
            return "NULL"

        raise ValueError(f"Column {column} is NOT NULL and has no DEFAULT")

    def _is_nullable(self, meta: dict[str, Any]) -> bool:
        nullable = meta.get("is_nullable")
        if nullable is None:
            return True
        return str(nullable).strip().upper() != "NO"

    def _build_standard_insert(
        self, table_identifier: str, columns: list[str], values_section: str
    ) -> str:
        columns_clause = f" ({', '.join(columns)})" if columns else ""
        return f"INSERT INTO {table_identifier}{columns_clause} VALUES {values_section}"

    def _extract_values_section(self, sql: str, start_idx: int) -> tuple[str, int] | None:
        idx = start_idx
        length = len(sql)
        while idx < length and sql[idx].isspace():
            idx += 1

        if idx >= length or sql[idx] != "(":
            return None

        depth = 0
        in_single = False
        in_double = False
        i = idx

        while i < length:
            char = sql[i]
            if char == "'" and not in_double:
                if in_single and i + 1 < length and sql[i + 1] == "'":
                    i += 1
                else:
                    in_single = not in_single
            elif char == '"' and not in_single:
                if in_double and i + 1 < length and sql[i + 1] == '"':
                    i += 1
                else:
                    in_double = not in_double
            elif char == "(" and not in_single and not in_double:
                depth += 1
            elif char == ")" and not in_single and not in_double:
                depth -= 1
                if depth == 0:
                    i += 1
                    j = i
                    while j < length and sql[j].isspace():
                        j += 1
                    if j < length and sql[j] == ",":
                        i = j + 1
                        while i < length and sql[i].isspace():
                            i += 1
                        continue
                    return sql[idx:i], i
            i += 1

        return None

    def _parse_value_tuples(self, values_section: str) -> list[str]:
        tuples: list[str] = []
        idx = 0
        length = len(values_section)
        while idx < length:
            while idx < length and values_section[idx].isspace():
                idx += 1
            if idx >= length or values_section[idx] != "(":
                break

            depth = 0
            in_single = False
            in_double = False
            start = idx
            i = idx

            while i < length:
                char = values_section[i]
                if char == "'" and not in_double:
                    if in_single and i + 1 < length and values_section[i + 1] == "'":
                        i += 1
                    else:
                        in_single = not in_single
                elif char == '"' and not in_single:
                    if in_double and i + 1 < length and values_section[i + 1] == '"':
                        i += 1
                    else:
                        in_double = not in_double
                elif char == "(" and not in_single and not in_double:
                    depth += 1
                elif char == ")" and not in_single and not in_double:
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            tuples.append(values_section[start:i])
            while i < length and values_section[i].isspace():
                i += 1
            if i < length and values_section[i] == ",":
                i += 1
            idx = i

        return tuples

    def _split_sql_expressions(self, text: str) -> list[str]:
        expressions: list[str] = []
        start = 0
        depth = 0
        in_single = False
        in_double = False
        idx = 0
        length = len(text)

        while idx < length:
            char = text[idx]
            if char == "'" and not in_double:
                if in_single and idx + 1 < length and text[idx + 1] == "'":
                    idx += 1
                else:
                    in_single = not in_single
            elif char == '"' and not in_single:
                if in_double and idx + 1 < length and text[idx + 1] == '"':
                    idx += 1
                else:
                    in_double = not in_double
            elif char == "(" and not in_single and not in_double:
                depth += 1
            elif char == ")" and not in_single and not in_double:
                depth -= 1
            elif char == "," and not in_single and not in_double and depth == 0:
                expressions.append(text[start:idx].strip())
                start = idx + 1
            idx += 1

        if start <= length:
            expressions.append(text[start:].strip())

        return [expr for expr in expressions if expr]

    def _normalize_identifier(self, identifier: str | None) -> str:
        if not identifier:
            return ""
        identifier = identifier.strip()
        if identifier.startswith('"') and identifier.endswith('"'):
            identifier = identifier[1:-1]
        if identifier.startswith("'") and identifier.endswith("'"):
            identifier = identifier[1:-1]
        return identifier.upper()

    def _parse_schema_table(self, identifier: str) -> tuple[str | None, str | None]:
        parts: list[str] = []
        current = ""
        in_quotes = False
        for char in identifier:
            if char == '"':
                in_quotes = not in_quotes
                current += char
            elif char == "." and not in_quotes:
                parts.append(current.strip())
                current = ""
            else:
                current += char
        if current:
            parts.append(current.strip())

        if len(parts) == 2:
            return self._strip_quotes(parts[0]), self._strip_quotes(parts[1])

        if parts:
            return None, self._strip_quotes(parts[-1])
        return None, None

    def _strip_quotes(self, value: str | None) -> str | None:
        if not value:
            return value
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            return value[1:-1]
        return value

    def _ensure_runner(self) -> _AsyncCoroutineRunner:
        if self._async_runner is None:
            self._async_runner = _AsyncCoroutineRunner()
        return self._async_runner

    def _legacy_translate(self, sql: str) -> str:
        pattern = r"^\s*INSERT\s+INTO\s+([\w\.\"]+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)"
        match = re.search(pattern, sql, re.IGNORECASE | re.DOTALL)
        if not match:
            return sql

        table_part = match.group(1)
        cols_part = match.group(2)
        vals_part = match.group(3)

        cols = [c.strip() for c in cols_part.split(",")]
        vals = [v.strip() for v in vals_part.split(",")]

        if len(cols) != len(vals):
            return sql

        new_cols: list[str] = []
        new_vals: list[str] = []
        has_default = False

        for col, val in zip(cols, vals, strict=False):
            if val.upper() == "DEFAULT":
                has_default = True
                continue
            new_cols.append(col)
            new_vals.append(val)

        if not has_default:
            return sql

        if not new_cols:
            return f"INSERT INTO {table_part} DEFAULT VALUES"

        return f"INSERT INTO {table_part} ({', '.join(new_cols)}) VALUES ({', '.join(new_vals)})"
