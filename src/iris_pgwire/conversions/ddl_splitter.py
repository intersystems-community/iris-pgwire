"""
Utilities for splitting complex PostgreSQL DDL into IRIS-compatible statements.
"""

import re

import structlog

logger = structlog.get_logger()


class DdlSplitter:
    """Splits complex DDL statements into multiple IRIS-compatible statements."""

    def split(self, sql: str) -> list[str]:
        """
        Split SQL text into individual statements, respecting comments and quotes.
        Comments are stripped to ensure IRIS compatibility.

        Args:
            sql: SQL string possibly containing multiple statements.

        Returns:
            List of individual SQL statements.
        """
        statements = []
        current_statement = []
        in_single_quote = False
        in_double_quote = False
        in_line_comment = False
        in_block_comment = False

        i = 0
        while i < len(sql):
            char = sql[i]
            next_char = sql[i + 1] if i + 1 < len(sql) else ""

            if char == "'" and not in_double_quote and not in_line_comment and not in_block_comment:
                in_single_quote = not in_single_quote
            elif (
                char == '"' and not in_single_quote and not in_line_comment and not in_block_comment
            ):
                in_double_quote = not in_double_quote
            elif (
                char == "-"
                and next_char == "-"
                and not in_single_quote
                and not in_double_quote
                and not in_block_comment
            ):
                in_line_comment = True
                i += 2
                continue
            elif char == "\n" and in_line_comment:
                in_line_comment = False
                i += 1
                continue
            elif (
                char == "/"
                and next_char == "*"
                and not in_single_quote
                and not in_double_quote
                and not in_line_comment
            ):
                in_block_comment = True
                i += 2
                continue
            elif char == "*" and next_char == "/" and in_block_comment:
                in_block_comment = False
                i += 2
                continue

            if in_line_comment or in_block_comment:
                i += 1
                continue

            if char == ";" and not in_single_quote and not in_double_quote:
                stmt = "".join(current_statement).strip()
                if stmt:
                    statements.append(stmt)
                current_statement = []
                i += 1
                continue

            current_statement.append(char)
            i += 1

        final_stmt = "".join(current_statement).strip()
        if final_stmt:
            statements.append(final_stmt)

        return statements

    def split_alter_table(self, sql: str) -> list[str]:
        """
        Split multi-action ALTER TABLE into individual statements and translate them.
        """
        sql_trimmed = sql.strip().rstrip(";")
        if not re.match(r"^\s*ALTER\s+TABLE", sql_trimmed, re.IGNORECASE):
            return [sql]

        sql_translated = self.translate_alter_table(sql_trimmed)

        if "," not in sql_translated:
            return [sql_translated]

        match = re.match(
            r"^\s*(ALTER\s+TABLE\s+[\w\.\"]+)\s+(.+)$", sql_translated, re.IGNORECASE | re.DOTALL
        )
        if not match:
            return [sql_translated]

        base_cmd = match.group(1)
        actions_str = match.group(2)

        actions = self._split_actions(actions_str)

        if len(actions) <= 1:
            return [sql_translated]

        split_statements = [f"{base_cmd} {action.strip()}" for action in actions]

        logger.info(
            "Split multi-action ALTER TABLE",
            actions_count=len(actions),
            table=base_cmd.split()[-1],
        )

        return split_statements

    def translate_alter_table(self, sql: str) -> str:
        """
        Translate PostgreSQL ALTER TABLE syntax to IRIS syntax.
        - ALTER COLUMN col SET DATA TYPE type -> ALTER COLUMN col type
        - ALTER COLUMN col DROP NOT NULL -> ALTER COLUMN col NULL
        - ALTER COLUMN col SET NOT NULL -> ALTER COLUMN col NOT NULL
        """
        # Pattern 1: SET DATA TYPE type -> type
        # PostgreSQL: ALTER TABLE t ALTER COLUMN c SET DATA TYPE VARCHAR(100)
        # IRIS: ALTER TABLE t ALTER COLUMN c VARCHAR(100)
        sql = re.sub(
            r"\bSET\s+DATA\s+TYPE\s+",
            "",
            sql,
            flags=re.IGNORECASE,
        )

        # Pattern 2: DROP NOT NULL -> NULL
        sql = re.sub(
            r"\bDROP\s+NOT\s+NULL\b",
            "NULL",
            sql,
            flags=re.IGNORECASE,
        )

        # Pattern 3: SET NOT NULL -> NOT NULL
        sql = re.sub(
            r"\bSET\s+NOT\s+NULL\b",
            "NOT NULL",
            sql,
            flags=re.IGNORECASE,
        )

        return sql

    def _split_actions(self, actions_str: str) -> list[str]:
        """Split actions string by commas outside parentheses."""
        actions = []
        current_action = []
        paren_depth = 0
        in_single_quote = False
        in_double_quote = False

        i = 0
        while i < len(actions_str):
            char = actions_str[i]

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif char == "(" and not in_single_quote and not in_double_quote:
                paren_depth += 1
            elif char == ")" and not in_single_quote and not in_double_quote:
                paren_depth -= 1
            elif char == "," and paren_depth == 0 and not in_single_quote and not in_double_quote:
                # Found a separator
                actions.append("".join(current_action).strip())
                current_action = []
                # Skip whitespace after comma
                while i + 1 < len(actions_str) and actions_str[i + 1].isspace():
                    i += 1
                i += 1
                continue

            current_action.append(char)
            i += 1

        if current_action:
            actions.append("".join(current_action).strip())

        return actions
