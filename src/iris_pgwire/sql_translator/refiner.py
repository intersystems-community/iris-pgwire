"""
SQL Refiner - Targeted SQL transformations for specific IRIS edge cases (Feature 036)

This module handles ad-hoc SQL fixes that are not part of general normalization
but are required for specific ORMs or IRIS SQL compiler quirks.
"""

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger("iris_pgwire.sql_translator.refiner")


@dataclass
class RefinerConfig:
    """Configuration for SQL refiner"""

    fix_order_by_aliases: bool = False
    preserve_case_for_quoted: bool = True


class SQLRefiner:
    """
    Handles targeted SQL refinements for IRIS compatibility.
    """

    def __init__(self, config: RefinerConfig | None = None):
        self.config = config or RefinerConfig()

        self._select_from_pattern = re.compile(r"SELECT\s+(.+?)\s+FROM", re.IGNORECASE | re.DOTALL)
        self._alias_pattern = re.compile(r"(.+?)\s+AS\s+(\w+)", re.IGNORECASE)
        self._order_by_pattern = re.compile(r"ORDER\s+BY\s+(.+)$", re.IGNORECASE | re.DOTALL)

    def refine(self, sql: str) -> str:
        """Apply all configured refinements to the SQL"""
        if not sql:
            return sql

        if self.config.fix_order_by_aliases:
            sql = self._fix_order_by_aliases(sql)

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
