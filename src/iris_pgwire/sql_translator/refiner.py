"""
SQL Refiner - Targeted SQL transformations for specific IRIS edge cases (Feature 036)

This module handles ad-hoc SQL fixes that are not part of general normalization
but are required for specific ORMs or IRIS SQL compiler quirks.
"""

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger("iris_pgwire.sql_translator.refiner")


@dataclass
class RefinerConfig:
    """Configuration for SQL refiner"""

    fix_order_by_aliases: bool = True
    preserve_case_for_quoted: bool = True
    enforce_exact_collation: bool = True


class SQLRefiner:
    """
    Handles targeted SQL refinements for IRIS compatibility.
    """

    def __init__(self, config: RefinerConfig | None = None):
        self.config = config or RefinerConfig()

        self._select_from_pattern = re.compile(r"SELECT\s+(.+?)\s+FROM", re.IGNORECASE | re.DOTALL)
        self._alias_pattern = re.compile(r"(.+?)\s+AS\s+(\w+)", re.IGNORECASE)
        self._order_by_pattern = re.compile(r"ORDER\s+BY\s+(.+)$", re.IGNORECASE | re.DOTALL)
        self._distinct_prefix_pattern = re.compile(r"(?is)(\s*DISTINCT\b)(\s*)(.*)")
        self._as_alias_suffix_pattern = re.compile(
            r"\s+AS\s+(?P<alias>(\"[^\"]+\"|'[^']+'|\[[^\]]+\]|[A-Za-z_][\w$]*))\s*$",
            re.IGNORECASE,
        )
        self._identifier_suffix_pattern = re.compile(
            r"(?P<alias>\"(?:[^\"]|\"\")*\"|\[[^\]]+\]|[A-Za-z_][\w$]*)\s*$"
        )
        self._union_split_pattern = re.compile(r"(\bUNION\b(?:\s+ALL\b)?)", re.IGNORECASE)
        self._union_token_pattern = re.compile(r"\bUNION\b", re.IGNORECASE)
        self._union_all_pattern = re.compile(r"\bUNION\s+ALL\b", re.IGNORECASE)

    def refine(self, sql: str) -> str:
        """Apply all configured refinements to the SQL"""
        if not sql:
            return sql

        if self.config.fix_order_by_aliases:
            sql = self._fix_order_by_aliases(sql)

        if self.config.enforce_exact_collation:
            sql = self._enforce_exact_collation(sql)

        return sql

    def _fix_order_by_aliases(self, sql: str) -> str:
        """
        Fix ORDER BY clauses that reference SELECT clause aliases.
        """
        select_match = self._select_from_pattern.search(sql)
        if not select_match:
            return sql

        select_clause = select_match.group(1)
        aliases = {}

        for match in self._alias_pattern.finditer(select_clause):
            expression = match.group(1).strip()
            if "," in expression:
                parts = []
                current = []
                depth = 0
                for char in expression:
                    if char == "(":
                        depth += 1
                    elif char == ")":
                        depth -= 1
                    if char == "," and depth == 0:
                        parts.append("".join(current))
                        current = []
                    else:
                        current.append(char)
                parts.append("".join(current))
                expression = parts[-1].strip()

            alias = match.group(2)
            aliases[alias.lower()] = expression

        if not aliases:
            return sql

        order_by_match = self._order_by_pattern.search(sql)
        if not order_by_match:
            return sql

        order_by_clause = order_by_match.group(1)
        modified_order_by = order_by_clause

        changed = False
        for alias, expression in aliases.items():
            pattern = rf"\b{re.escape(alias)}\b"
            if re.search(pattern, modified_order_by, re.IGNORECASE):
                modified_order_by = re.sub(
                    pattern, expression, modified_order_by, flags=re.IGNORECASE
                )
                changed = True

        if changed:
            logger.info("🔧 Fixed ORDER BY aliases for IRIS compatibility")
            return sql[: order_by_match.start(1)] + modified_order_by

        return sql

    def _enforce_exact_collation(self, sql: str) -> str:
        has_distinct = bool(re.search(r"\bSELECT\s+DISTINCT\b", sql, re.IGNORECASE))
        union_count = len(self._union_token_pattern.findall(sql))
        union_all_count = len(self._union_all_pattern.findall(sql))
        only_union_all = union_count > 0 and union_count == union_all_count
        if not (has_distinct or (union_count > 0 and not only_union_all)):
            return sql

        parts = self._union_split_pattern.split(sql)
        changed = False
        for i in range(0, len(parts), 2):
            segment = parts[i]
            wrapped = self._wrap_select_segment(segment)
            if wrapped != segment:
                changed = True
            parts[i] = wrapped

        if not changed:
            return sql

        logger.info("🔧 Enforced exact collation for IRIS 2024.2+")
        return "".join(parts)

    def _wrap_select_segment(self, segment: str) -> str:
        select_match = self._select_from_pattern.search(segment)
        if not select_match:
            return segment

        select_list = select_match.group(1)
        wrapped_list = self._wrap_select_list(select_list)
        if wrapped_list == select_list:
            return segment

        return segment[: select_match.start(1)] + wrapped_list + segment[select_match.end(1) :]

    def _wrap_select_list(self, select_list: str) -> str:
        distinct_prefix = ""
        separator = ""
        body = select_list
        distinct_match = self._distinct_prefix_pattern.match(select_list)
        if distinct_match:
            distinct_prefix = distinct_match.group(1)
            separator = distinct_match.group(2)
            body = distinct_match.group(3)

        columns = self._split_select_list(body)
        wrapped_columns = []
        changed = False
        for index, column in enumerate(columns):
            trimmed = column.strip()
            if not trimmed:
                continue
            if trimmed.upper().startswith("%EXACT"):
                wrapped_columns.append(trimmed)
                continue

            base_expr, alias = self._extract_base_and_alias(trimmed)
            if not alias:
                alias = self._derive_alias_from_expression(base_expr)
            if not alias:
                alias = f"COL_{index + 1}"

            wrapped_columns.append(f"%EXACT {base_expr.strip()} AS {alias}")
            changed = True

        if not changed:
            return select_list

        joined = ", ".join(wrapped_columns)
        return f"{distinct_prefix}{separator}{joined}"

    def _split_select_list(self, body: str) -> list[str]:
        parts: list[str] = []
        buffer: list[str] = []
        depth = 0
        in_single = False
        in_double = False
        index = 0
        while index < len(body):
            char = body[index]
            if char == "'" and not in_double:
                if in_single and index + 1 < len(body) and body[index + 1] == "'":
                    buffer.append(char)
                    buffer.append("'")
                    index += 2
                    continue
                in_single = not in_single
            elif char == '"' and not in_single:
                if in_double and index + 1 < len(body) and body[index + 1] == '"':
                    buffer.append(char)
                    buffer.append('"')
                    index += 2
                    continue
                in_double = not in_double
            elif char == "(" and not in_single and not in_double:
                depth += 1
            elif char == ")" and not in_single and not in_double and depth > 0:
                depth -= 1

            if char == "," and depth == 0 and not in_single and not in_double:
                parts.append("".join(buffer))
                buffer = []
                index += 1
                continue

            buffer.append(char)
            index += 1

        if buffer:
            parts.append("".join(buffer))

        return parts

    def _extract_base_and_alias(self, expression: str) -> tuple[str, str | None]:
        alias_match = self._as_alias_suffix_pattern.search(expression)
        if alias_match:
            alias = alias_match.group("alias")
            base = expression[: alias_match.start()].rstrip()
            return base or expression, alias
        return expression, None

    def _derive_alias_from_expression(self, expression: str) -> str | None:
        trimmed = expression.rstrip()
        alias_match = self._identifier_suffix_pattern.search(trimmed)
        if not alias_match:
            return None
        return alias_match.group("alias")
