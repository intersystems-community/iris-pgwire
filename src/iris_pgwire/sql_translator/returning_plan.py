"""Parse PostgreSQL RETURNING / ON CONFLICT clauses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Tuple

try:
    from structlog import get_logger

    logger = get_logger()
except ImportError:  # pragma: no cover - best effort logging
    import logging

    logger = logging.getLogger(__name__)

from .metadata_cache import MetadataCache


@dataclass(frozen=True)
class ReturningColumnMeta:
    raw_expression: str
    normalized_name: str
    alias: Optional[str]
    select_expression: str
    is_simple_identifier: bool


@dataclass
class ReturningPlan:
    original_sql: str
    operation: Optional[str]
    table: Optional[str]
    returning_clause: Optional[str]
    columns: Optional[list[str] | str]
    column_meta: Optional[list[ReturningColumnMeta]]
    where_clause: Optional[str]
    stripped_sql: str
    insert_columns: list[str]
    on_conflict_clause: Optional[str]
    conflict_action: Optional[str]
    conflict_set_clause: Optional[str]
    conflict_where_clause: Optional[str]
    conflict_target: Optional[str]
    conflict_target_columns: list[str]
    conflict_constraint: Optional[str]
    metadata_cache: Optional[MetadataCache]

    @property
    def has_returning(self) -> bool:
        return bool(self.columns)

    @property
    def select_list(self) -> str:
        if not self.column_meta:
            return "*"
        return ", ".join(col.select_expression for col in self.column_meta)

    @classmethod
    def from_sql(
        cls,
        sql: str,
        metadata_cache: Optional[MetadataCache] = None,
        executor: Any | None = None,
    ) -> "ReturningPlan":
        normalized_sql = sql.strip()
        returning_clause, returning_columns, returning_meta = cls._extract_returning(normalized_sql)
        conflict_clause, conflict_target, conflict_target_columns, conflict_constraint = (
            cls._extract_on_conflict(normalized_sql, returning_clause)
        )
        stripped_sql = cls._strip_clauses(normalized_sql, returning_clause, conflict_clause)
        operation = cls._extract_operation(normalized_sql)
        table = cls._extract_table(normalized_sql)
        where_clause = cls._extract_where(operation, normalized_sql, returning_clause)
        insert_columns = cls._extract_insert_columns(normalized_sql)
        conflict_action, conflict_set_clause, conflict_where_clause = cls._parse_conflict_action(
            conflict_clause
        )

        return cls(
            original_sql=sql,
            operation=operation,
            table=table,
            returning_clause=returning_clause,
            columns=returning_columns,
            column_meta=returning_meta,
            where_clause=where_clause,
            stripped_sql=stripped_sql,
            insert_columns=insert_columns,
            on_conflict_clause=conflict_clause,
            conflict_action=conflict_action,
            conflict_set_clause=conflict_set_clause,
            conflict_where_clause=conflict_where_clause,
            conflict_target=conflict_target,
            conflict_target_columns=conflict_target_columns,
            conflict_constraint=conflict_constraint,
            metadata_cache=metadata_cache,
        )

    @staticmethod
    def _extract_returning(
        sql: str,
    ) -> Tuple[Optional[str], Optional[list[str] | str], Optional[list[ReturningColumnMeta]]]:
        match = re.search(r"\bRETURNING\b", sql, re.IGNORECASE)
        if not match:
            return None, None, None

        start = match.end()
        end_match = re.search(r";", sql[start:])
        end = end_match.start() + start if end_match else len(sql)
        clause = sql[start:end].strip()
        if not clause:
            return clause, None, None

        if clause.strip() == "*":
            return clause, "*", None

        items = ReturningPlan._split_comma_separated(clause)
        columns: list[str] = []
        metas: list[ReturningColumnMeta] = []
        for raw in items:
            normalized, alias, select_expression, is_simple = ReturningPlan._describe_column(raw)
            columns.append(normalized)
            metas.append(
                ReturningColumnMeta(
                    raw_expression=raw,
                    normalized_name=normalized,
                    alias=alias,
                    select_expression=select_expression,
                    is_simple_identifier=is_simple,
                )
            )

        return clause, columns, metas

    @staticmethod
    def _extract_on_conflict(
        sql: str, returning_clause: Optional[str]
    ) -> Tuple[Optional[str], Optional[str], list[str], Optional[str]]:
        match = re.search(r"\bON\s+CONFLICT\b", sql, re.IGNORECASE)
        if not match:
            return None, None, [], None

        end = len(sql)
        if returning_clause:
            returning_pos = sql.lower().find("returning")
            if returning_pos != -1 and returning_pos > match.start():
                end = returning_pos

        clause = sql[match.start() : end].rstrip(";").strip()
        target_match = re.search(
            r"ON\s+CONFLICT\s+(?:ON\s+CONSTRAINT\s+(?P<constraint>[\w$]+)|\((?P<columns>[^)]+)\))",
            clause,
            re.IGNORECASE,
        )
        target = None
        columns: list[str] = []
        constraint = None

        if target_match:
            if target_match.group("columns"):
                target_raw = target_match.group("columns").strip()
                columns = [
                    ReturningPlan._normalize_identifier(name)
                    for name in ReturningPlan._split_comma_separated(target_raw)
                ]
                target = f"({target_raw})"
            elif target_match.group("constraint"):
                constraint = target_match.group("constraint")
                target = f"ON CONSTRAINT {constraint}"
        return clause, target, columns, constraint

    @staticmethod
    def _parse_conflict_action(
        clause: Optional[str],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        if not clause:
            return None, None, None
        do_nothing = re.search(r"\bDO\s+NOTHING\b", clause, re.IGNORECASE)
        if do_nothing:
            return "DO NOTHING", None, None

        set_match = re.search(r"\bDO\s+UPDATE\s+SET\b", clause, re.IGNORECASE)
        if not set_match:
            return None, None, None

        remainder = clause[set_match.end() :].strip()
        where_match = re.search(r"\bWHERE\b", remainder, re.IGNORECASE)
        set_clause = remainder if not where_match else remainder[: where_match.start()].strip()
        where_clause = remainder[where_match.end() :].strip() if where_match else None
        return (
            "DO UPDATE",
            set_clause.rstrip(";").strip() if set_clause else None,
            where_clause.rstrip(";").strip() if where_clause else None,
        )

    @staticmethod
    def _strip_clauses(
        sql: str, returning_clause: Optional[str], conflict_clause: Optional[str]
    ) -> str:
        stripped = sql
        if returning_clause:
            stripped = re.sub(
                r"\s+RETURNING\b.*", "", stripped, count=1, flags=re.IGNORECASE | re.DOTALL
            )
        if conflict_clause and conflict_clause in stripped:
            stripped = stripped.replace(conflict_clause, "", 1)
        return stripped.strip()

    @staticmethod
    def _extract_operation(sql: str) -> Optional[str]:
        cleaned = sql.strip().upper()
        if cleaned.startswith("INSERT"):
            return "INSERT"
        if cleaned.startswith("UPDATE"):
            return "UPDATE"
        if cleaned.startswith("DELETE"):
            return "DELETE"
        return None

    @staticmethod
    def _extract_table(sql: str) -> Optional[str]:
        match = re.search(
            r'(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:(?:"?\w+"?)\s*\.\s*)*"?(\w+)"?',
            sql,
            re.IGNORECASE,
        )
        if not match:
            return None
        return match.group(1).upper()

    @staticmethod
    def _extract_where(
        operation: Optional[str], sql: str, returning_clause: Optional[str]
    ) -> Optional[str]:
        if operation not in ("UPDATE", "DELETE"):
            return None
        end = len(sql)
        if returning_clause:
            returning_pos = sql.lower().find("returning")
            if returning_pos != -1:
                end = returning_pos
        where_match = re.search(r"\bWHERE\b", sql[:end], re.IGNORECASE)
        if not where_match:
            return None
        clause = sql[where_match.end() : end].strip()
        return clause.rstrip(";").strip()

    @staticmethod
    def _extract_insert_columns(sql: str) -> list[str]:
        match = re.search(r"INSERT\s+INTO\s+[^\s\(]+\s*\(\s*(?P<cols>[^)]+)\)", sql, re.IGNORECASE)
        if not match:
            return []
        cols = match.group("cols")
        return [
            ReturningPlan._normalize_identifier(part)
            for part in ReturningPlan._split_comma_separated(cols)
        ]

    @staticmethod
    def _split_comma_separated(text: str) -> list[str]:
        parts: list[str] = []
        buffer: list[str] = []
        depth = 0
        in_single = False
        in_double = False

        for char in text:
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif char == "(" and not in_single and not in_double:
                depth += 1
            elif char == ")" and not in_single and not in_double:
                depth = max(depth - 1, 0)
            if char == "," and depth == 0 and not in_single and not in_double:
                part = "".join(buffer).strip()
                if part:
                    parts.append(part)
                buffer = []
                continue
            buffer.append(char)

        final = "".join(buffer).strip()
        if final:
            parts.append(final)
        return parts

    @staticmethod
    def _normalize_identifier(identifier: str) -> str:
        value = identifier.strip()
        value = value.strip('"').strip("'")
        return value.lower()

    @staticmethod
    def _describe_column(expr: str) -> Tuple[str, Optional[str], str, bool]:
        cleaned = expr.strip()
        alias = None
        alias_match = re.search(r"\s+AS\s+(?P<alias>\"[^\"]+\"|\w+)$", cleaned, re.IGNORECASE)
        base = cleaned
        if alias_match:
            alias_raw = alias_match.group("alias")
            alias = alias_raw.strip('"').lower()
            base = cleaned[: alias_match.start()].strip()

        identifier_name = base.split(".")[-1]
        normalized = ReturningPlan._normalize_identifier(identifier_name)
        is_simple = bool(re.match(r'^(?:"?\w+"?)(?:\.["?\w+"?])*$', base))
        if is_simple:
            identifier = identifier_name.strip('"').strip("'").upper()
            select_expression = f'"{identifier}"'
        else:
            select_expression = base

        if alias:
            alias_upper = alias.upper()
            select_expression = f'{select_expression} AS "{alias_upper}"'
            normalized = alias

        return normalized, alias, select_expression, is_simple
