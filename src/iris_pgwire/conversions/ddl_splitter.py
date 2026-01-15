"""
Utilities for splitting complex PostgreSQL DDL into IRIS-compatible statements.
"""

import re
import logging

logger = logging.getLogger(__name__)


class DdlSplitter:
    """Splits complex DDL statements into multiple IRIS-compatible statements."""

    def split_alter_table(self, sql: str) -> list[str]:
        """
        Split multi-action ALTER TABLE into individual statements.

        Example:
            ALTER TABLE t ADD c1 INT, ADD c2 INT
        becomes:
            ALTER TABLE t ADD c1 INT;
            ALTER TABLE t ADD c2 INT;
        """
        # Basic check if it's an ALTER TABLE statement with commas
        sql_trimmed = sql.strip().rstrip(";")
        if not re.match(r"^\s*ALTER\s+TABLE", sql_trimmed, re.IGNORECASE):
            return [sql]

        if "," not in sql_trimmed:
            return [sql]

        # Match the base ALTER TABLE <name> part
        # Pattern: ALTER TABLE <name> <action1>, <action2>, ...
        match = re.match(
            r"^\s*(ALTER\s+TABLE\s+\w+)\s+(.+)$", sql_trimmed, re.IGNORECASE | re.DOTALL
        )
        if not match:
            return [sql]

        base_cmd = match.group(1)
        actions_str = match.group(2)

        # Split actions by comma, but be careful of commas inside parentheses (e.g. decimal precision)
        actions = self._split_actions(actions_str)

        if len(actions) <= 1:
            return [sql]

        # Reconstruct individual statements
        split_statements = [f"{base_cmd} {action.strip()}" for action in actions]

        logger.info(
            "Split multi-action ALTER TABLE",
            original_actions=len(actions),
            table=base_cmd.split()[-1],
        )

        return split_statements

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
