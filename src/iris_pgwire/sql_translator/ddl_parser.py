"""DDL parser data classes and helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

import sqlparse
from sqlparse.sql import Identifier, Parenthesis, Statement, Token

from .ddl_translator import DDLStatement


class ConstraintType(Enum):
    """Supported DDL constraint categories."""

    PRIMARY_KEY = "PRIMARY_KEY"
    FOREIGN_KEY = "FOREIGN_KEY"
    UNIQUE = "UNIQUE"
    CHECK = "CHECK"


@dataclass(frozen=True)
class ColumnDefinition:
    """Metadata for a single table column."""

    name: str
    pg_type: str
    iris_type: str
    nullable: bool
    default: str | None
    is_primary_key: bool


@dataclass(frozen=True)
class ConstraintDefinition:
    """Structured information about a table constraint."""

    constraint_type: ConstraintType
    columns: tuple[str, ...]
    references: str | None = None
    on_delete: str | None = None
    on_update: str | None = None


@dataclass(frozen=True)
class IndexDefinition:
    """Structured representation of a CREATE INDEX statement."""

    name: str
    table: str
    columns: tuple[str, ...]
    unique: bool
    where_clause: str | None = None
    include_columns: tuple[str, ...] | None = None


class DDLParser:
    """Parses PostgreSQL DDL statements into structured metadata."""

    _CLAUSE_KEYWORDS = {
        "DEFAULT",
        "NOT",
        "NULL",
        "PRIMARY",
        "KEY",
        "UNIQUE",
        "REFERENCES",
        "CHECK",
        "CONSTRAINT",
    }

    def parse(self, sql: str) -> list[DDLStatement]:
        """Return CREATE TABLE statements parsed into DDLStatement objects."""

        # Strip single-line SQL comments (-- ...) before parsing.
        # sqlparse wraps leading comments into ttype=None tokens which confuse
        # the DDL keyword detection logic in _is_create_table and friends.
        sql = re.sub(r"--[^\n]*", "", sql)

        statements = sqlparse.parse(sql)
        result: list[DDLStatement] = []
        for stmt in statements:
            if self._is_create_table(stmt):
                schema_name, table_name = self._extract_table_name(stmt)
                columns, constraints = self._parse_columns_and_constraints(stmt)
                result.append(
                    DDLStatement(
                        raw_sql=str(stmt).strip(),
                        statement_type="CREATE_TABLE",
                        schema_name=schema_name,
                        table_name=table_name,
                        columns=tuple(columns),
                        constraints=tuple(constraints),
                    )
                )
                continue
            if self._is_alter_table(stmt):
                result.append(self._parse_alter_table(stmt))
                continue
            if self._is_create_index(stmt):
                result.append(self._parse_create_index(stmt))
                continue
            if self._is_drop_index(stmt):
                result.append(self._parse_drop_index(stmt))
                continue
            if self._is_drop_table(stmt):
                result.append(self._parse_drop_table(stmt))
        return result

    def _non_whitespace_tokens(self, stmt: Statement) -> list[Token]:
        return [token for token in stmt.tokens if not token.is_whitespace]

    def _is_create_table(self, stmt: Statement) -> bool:
        tokens = self._non_whitespace_tokens(stmt)
        if len(tokens) < 3:
            return False
        return tokens[0].match(sqlparse.tokens.Keyword.DDL, "CREATE") and tokens[1].match(
            sqlparse.tokens.Keyword, "TABLE"
        )

    def _is_alter_table(self, stmt: Statement) -> bool:
        tokens = self._non_whitespace_tokens(stmt)
        if len(tokens) < 3:
            return False
        return tokens[0].match(sqlparse.tokens.Keyword.DDL, "ALTER") and tokens[1].match(
            sqlparse.tokens.Keyword, "TABLE"
        )

    def _is_drop_table(self, stmt: Statement) -> bool:
        tokens = self._non_whitespace_tokens(stmt)
        if len(tokens) < 3:
            return False
        return tokens[0].match(sqlparse.tokens.Keyword.DDL, "DROP") and tokens[1].match(
            sqlparse.tokens.Keyword, "TABLE"
        )

    def _extract_table_name(self, stmt: Statement) -> tuple[str | None, str | None]:
        seen_table = False
        for token in stmt.tokens:
            if token.is_whitespace or token.ttype in {sqlparse.tokens.Newline}:
                continue
            if token.match(sqlparse.tokens.Keyword, "TABLE"):
                seen_table = True
                continue
            if not seen_table:
                continue
            if (
                token.match(sqlparse.tokens.Keyword, "IF")
                or token.match(sqlparse.tokens.Keyword, "NOT")
                or token.match(sqlparse.tokens.Keyword, "EXISTS")
            ):
                continue
            if isinstance(token, Identifier):
                return self._split_qualified_identifier(token.value)
            if token.ttype in {sqlparse.tokens.Name, sqlparse.tokens.Name.Builtin}:
                return None, token.value
        return None, None

    def _extract_clause_after_table(self, stmt: Statement) -> str:
        tokens = self._non_whitespace_tokens(stmt)
        clause_parts: list[str] = []
        seen_table = False
        table_ident_found = False

        for token in tokens:
            if not seen_table:
                if token.match(sqlparse.tokens.Keyword, "TABLE"):
                    seen_table = True
                continue
            if not table_ident_found:
                if (
                    token.match(sqlparse.tokens.Keyword, "IF")
                    or token.match(sqlparse.tokens.Keyword, "NOT")
                    or token.match(sqlparse.tokens.Keyword, "EXISTS")
                ):
                    continue
                if isinstance(token, Identifier) or token.ttype in {
                    sqlparse.tokens.Name,
                    sqlparse.tokens.Name.Builtin,
                }:
                    table_ident_found = True
                    continue
                continue
            clause_parts.append(token.value)

        clause = " ".join(part.strip() for part in clause_parts if part and not part.isspace())
        return clause.strip()

    def _split_qualified_identifier(self, identifier: str) -> tuple[str | None, str | None]:
        parts: list[str] = []
        buffer: list[str] = []
        in_double = False
        for char in identifier:
            if char == '"':
                in_double = not in_double
                buffer.append(char)
                continue
            if char == "." and not in_double:
                segment = "".join(buffer).strip()
                if segment:
                    parts.append(segment)
                buffer = []
                continue
            buffer.append(char)
        if buffer:
            parts.append("".join(buffer).strip())
        if len(parts) >= 2:
            return parts[-2], parts[-1]
        if parts:
            return None, parts[-1]
        return None, None

    def _parse_columns_and_constraints(
        self, stmt: Statement
    ) -> tuple[list[ColumnDefinition], list[ConstraintDefinition]]:
        parenthesis = next((token for token in stmt.tokens if isinstance(token, Parenthesis)), None)
        if parenthesis is None:
            return [], []
        content = parenthesis.value
        if content.startswith("(") and content.endswith(")"):
            content = content[1:-1]
        entries = self._split_definitions(content)
        columns: list[ColumnDefinition] = []
        constraints: list[ConstraintDefinition] = []
        for entry in entries:
            normalized = entry.strip()
            if not normalized:
                continue
            upper = normalized.upper()
            if upper.startswith("PRIMARY KEY") or (
                upper.startswith("CONSTRAINT") and "PRIMARY KEY" in upper
            ):
                constraints.append(self._parse_primary_key_constraint(normalized))
                continue
            columns.append(self._parse_column_definition(normalized))
        return columns, constraints

    def _parse_alter_table(self, statement: Statement) -> DDLStatement:
        schema_name, table_name = self._extract_table_name(statement)
        clause = (self._extract_clause_after_table(statement) or "").strip()
        operation = self._determine_alter_operation(clause)
        details, columns, warnings, is_translatable = self._handle_alter_operation(
            clause, operation
        )
        if clause:
            details = details or {"clause": clause}
        operation_details = details or None
        return DDLStatement(
            raw_sql=str(statement).strip(),
            statement_type="ALTER_TABLE",
            schema_name=schema_name,
            table_name=table_name,
            operation=operation,
            operation_details=operation_details,
            columns=tuple(columns),
            translation_warnings=tuple(warnings),
            is_translatable=is_translatable,
        )

    def _handle_alter_operation(
        self,
        clause: str,
        operation: str | None,
    ) -> tuple[dict[str, Any] | None, list[ColumnDefinition], list[str], bool]:
        handlers = {
            "ADD_COLUMN": self._handle_alter_add_column_operation,
            "DROP_COLUMN": self._handle_alter_drop_column_operation,
            "RENAME_COLUMN": self._handle_alter_rename_column_operation,
        }
        if not operation:
            return self._handle_unsupported_alter(clause, operation)
        handler = handlers.get(operation)
        if handler:
            return handler(clause)
        return self._handle_unsupported_alter(clause, operation)

    def _handle_alter_add_column_operation(
        self, clause: str
    ) -> tuple[dict[str, Any] | None, list[ColumnDefinition], list[str], bool]:
        column_definition = self._parse_alter_add_column_clause(clause)
        if not column_definition:
            return None, [], ["Could not parse ALTER TABLE ADD COLUMN clause"], False
        return {"column_definition": column_definition}, [column_definition], [], True

    def _handle_alter_drop_column_operation(
        self, clause: str
    ) -> tuple[dict[str, Any] | None, list[ColumnDefinition], list[str], bool]:
        column_name = self._parse_alter_drop_column_clause(clause)
        if not column_name:
            return None, [], ["Could not parse ALTER TABLE DROP COLUMN clause"], False
        return {"column_name": column_name}, [], [], True

    def _handle_alter_rename_column_operation(
        self, clause: str
    ) -> tuple[dict[str, Any] | None, list[ColumnDefinition], list[str], bool]:
        rename_result = self._parse_alter_rename_column_clause(clause)
        if not rename_result:
            return None, [], ["Could not parse ALTER TABLE RENAME COLUMN clause"], False
        old_name, new_name = rename_result
        return {"old_column": old_name, "new_column": new_name}, [], [], True

    def _handle_unsupported_alter(
        self, clause: str, operation: str | None
    ) -> tuple[dict[str, Any] | None, list[ColumnDefinition], list[str], bool]:
        warnings: list[str] = []
        if clause:
            warnings.append(f"Unsupported ALTER TABLE operation: {operation or clause}".strip())
        else:
            warnings.append("ALTER TABLE clause missing")
        return None, [], warnings, False

    def _parse_drop_table(self, statement: Statement) -> DDLStatement:
        schema_name, table_name = self._extract_table_name(statement)
        clause = self._extract_clause_after_table(statement)
        warnings = ("DROP TABLE parsing stub - manual execution required",)
        return DDLStatement(
            raw_sql=str(statement).strip(),
            statement_type="DROP_TABLE",
            schema_name=schema_name,
            table_name=table_name,
            operation="DROP_TABLE",
            operation_details={"clause": clause} if clause else None,
            translation_warnings=warnings,
            is_translatable=False,
        )

    def _is_create_index(self, stmt: Statement) -> bool:
        tokens = self._non_whitespace_tokens(stmt)
        if len(tokens) < 3:
            return False
        return tokens[0].match(sqlparse.tokens.Keyword.DDL, "CREATE") and (
            tokens[1].match(sqlparse.tokens.Keyword, "INDEX")
            or tokens[1].match(sqlparse.tokens.Keyword, "UNIQUE")
        )

    def _parse_create_index(self, stmt: Statement) -> DDLStatement:
        """Parse CREATE INDEX statement and detect unsupported features."""
        raw_sql = str(stmt).strip()

        # Check for unsupported features
        warnings = []
        is_translatable = True
        skip_reason = None

        upper_sql = raw_sql.upper()
        if "WHERE" in upper_sql:
            warnings.append(
                "UNSUPPORTED_INDEX_FEATURE: IRIS does not support partial indexes (WHERE clause). "
                "Remove WHERE clause or create index on full table."
            )
            is_translatable = False
            skip_reason = "IRIS does not support partial indexes"

        if "INCLUDE" in upper_sql:
            warnings.append(
                "UNSUPPORTED_INDEX_FEATURE: IRIS does not support INCLUDE columns. "
                "Create separate index or remove INCLUDE clause."
            )
            is_translatable = False
            skip_reason = "IRIS does not support INCLUDE columns"

        # Check for expression indexes (function calls in column list)
        if "(" in raw_sql and "LOWER(" in upper_sql:
            warnings.append(
                "UNSUPPORTED_INDEX_FEATURE: IRIS does not support expression indexes. "
                "Create index on column directly."
            )
            is_translatable = False
            skip_reason = "IRIS does not support expression indexes"

        return DDLStatement(
            raw_sql=raw_sql,
            statement_type="CREATE_INDEX",
            translation_warnings=tuple(warnings),
            is_translatable=is_translatable,
            skip_reason=skip_reason,
        )

    def _is_drop_index(self, stmt: Statement) -> bool:
        return False

    def _parse_drop_index(self, stmt: Statement) -> DDLStatement:
        raise NotImplementedError("DROP INDEX parsing is not implemented yet")

    def _determine_alter_operation(self, clause: str) -> str | None:
        normalized = clause.upper()
        for keyword, label in [
            ("ADD COLUMN", "ADD_COLUMN"),
            ("DROP COLUMN", "DROP_COLUMN"),
            ("RENAME COLUMN", "RENAME_COLUMN"),
            ("RENAME TO", "RENAME_TABLE"),
            ("ADD CONSTRAINT", "ADD_CONSTRAINT"),
            ("DROP CONSTRAINT", "DROP_CONSTRAINT"),
        ]:
            if keyword in normalized:
                return label
        return None

    def _parse_primary_key_constraint(self, definition: str) -> ConstraintDefinition:
        start = definition.upper().find("PRIMARY KEY")
        open_paren = definition.find("(", start)
        close_paren = definition.rfind(")")
        column_names: tuple[str, ...]
        if open_paren == -1 or close_paren == -1 or close_paren < open_paren:
            column_names = ()
        else:
            inner = definition[open_paren + 1 : close_paren]
            parsed = tuple(name.strip() for name in self._split_definitions(inner) if name.strip())
            column_names = parsed
        return ConstraintDefinition(
            constraint_type=ConstraintType.PRIMARY_KEY,
            columns=column_names,
        )

    def _split_definitions(self, content: str) -> list[str]:
        segments: list[str] = []
        buffer: list[str] = []
        depth = 0
        in_single = False
        in_double = False
        for char in content:
            if char == '"' and not in_single:
                in_double = not in_double
                buffer.append(char)
                continue
            if char == "'" and not in_double:
                in_single = not in_single
                buffer.append(char)
                continue
            if char == "(" and not in_single and not in_double:
                depth += 1
                buffer.append(char)
                continue
            if char == ")" and not in_single and not in_double:
                depth = max(depth - 1, 0)
                buffer.append(char)
                continue
            if char == "," and depth == 0 and not in_single and not in_double:
                segment = "".join(buffer).strip()
                if segment:
                    segments.append(segment)
                buffer = []
                continue
            buffer.append(char)
        final_segment = "".join(buffer).strip()
        if final_segment:
            segments.append(final_segment)
        return segments

    def _normalize_default_expression(self, default_value: str) -> str:
        normalized = default_value.strip()
        compact = re.sub(r"\s+", "", normalized).upper()
        # IRIS limitation: Cannot use function calls in DEFAULT for UUID columns
        # Return special marker to signal DEFAULT should be skipped entirely
        if compact == "GEN_RANDOM_UUID()":
            return "__SKIP_DEFAULT__"
        if compact in {"CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP()"}:
            return "CURRENT_TIMESTAMP"
        # IRIS requires CURRENT_TIMESTAMP, not NOW()
        if compact == "NOW()":
            return "CURRENT_TIMESTAMP"
        # Boolean literals must be converted to integers for IRIS
        if compact in {"TRUE", "FALSE"}:
            return "1" if compact == "TRUE" else "0"
        return normalized

    def _parse_column_definition(self, definition: str) -> ColumnDefinition:
        parsed = sqlparse.parse(definition)[0]
        tokens = [
            token
            for token in parsed.tokens
            if not token.is_whitespace and token.ttype is not sqlparse.tokens.Comment
        ]
        if not tokens:
            raise ValueError("Empty column definition")
        column_name = tokens[0].value
        pg_type, idx = self._collect_column_type_tokens(tokens, 1)
        nullable, default, is_primary_key = self._parse_column_constraints(tokens, idx)
        return ColumnDefinition(
            name=column_name,
            pg_type=pg_type,
            iris_type="",
            nullable=nullable,
            default=default,
            is_primary_key=is_primary_key,
        )

    def _collect_column_type_tokens(self, tokens: list[Token], start_idx: int) -> tuple[str, int]:
        parts: list[str] = []
        idx = start_idx
        while idx < len(tokens):
            token = tokens[idx]
            if token.ttype is sqlparse.tokens.Keyword:
                token_upper = token.value.upper()
                if any(kw in token_upper for kw in self._CLAUSE_KEYWORDS):
                    break
            parts.append(token.value)
            idx += 1
        return " ".join(parts).strip(), idx

    def _parse_column_constraints(
        self, tokens: list[Token], start_idx: int
    ) -> tuple[bool, str | None, bool]:
        nullable = True
        default: str | None = None
        is_primary_key = False
        idx = start_idx
        while idx < len(tokens):
            token = tokens[idx]
            if token.ttype is sqlparse.tokens.Keyword:
                keyword = token.value.upper()
                if "NOT NULL" in keyword or keyword == "NOT":
                    idx = self._consume_not_null_clause(tokens, idx)
                    nullable = False
                    continue
                if keyword == "DEFAULT":
                    default_value, idx = self._extract_default_clause(tokens, idx + 1)
                    if default_value:
                        default = self._normalize_default_expression(default_value)
                    continue
                if "PRIMARY KEY" in keyword or keyword == "PRIMARY":
                    idx = self._consume_primary_clause(tokens, idx)
                    is_primary_key = True
                    nullable = False
                    continue
            idx += 1
        return nullable, default, is_primary_key

    def _consume_not_null_clause(self, tokens: list[Token], idx: int) -> int:
        keyword = tokens[idx].value.upper()
        if "NOT NULL" in keyword:
            return idx + 1
        next_token = self._peek_token(tokens, idx + 1)
        if next_token and next_token.match(sqlparse.tokens.Keyword, "NULL"):
            return idx + 2
        return idx + 1

    def _consume_primary_clause(self, tokens: list[Token], idx: int) -> int:
        keyword = tokens[idx].value.upper()
        if "PRIMARY KEY" in keyword:
            return idx + 1
        next_token = self._peek_token(tokens, idx + 1)
        if next_token and next_token.match(sqlparse.tokens.Keyword, "KEY"):
            return idx + 2
        return idx + 1

    def _extract_default_clause(self, tokens: list[Token], start_idx: int) -> tuple[str, int]:
        default_tokens: list[str] = []
        depth = 0
        idx = start_idx
        while idx < len(tokens):
            inner = tokens[idx]
            if inner.value == "(":
                depth += 1
            elif inner.value == ")":
                if depth <= 0:
                    break
                depth -= 1
            upper_inner = inner.value.upper()
            if (
                depth == 0
                and inner.ttype is sqlparse.tokens.Keyword
                and upper_inner in self._CLAUSE_KEYWORDS
            ):
                break
            if depth == 0 and inner.value == ",":
                break
            default_tokens.append(inner.value)
            idx += 1
        return " ".join(default_tokens).strip(), idx

    def _parse_alter_add_column_clause(self, clause: str) -> ColumnDefinition | None:
        body = self._extract_clause_after_keyword(clause, "ADD COLUMN")
        if not body:
            return None
        body = self._strip_if_not_exists_clause(body)
        body = body.rstrip(";")
        if not body:
            return None
        return self._parse_column_definition(body)

    def _parse_alter_drop_column_clause(self, clause: str) -> str | None:
        body = self._extract_clause_after_keyword(clause, "DROP COLUMN")
        if not body:
            return None
        body = self._strip_if_exists_clause(body)
        body = body.rstrip(";")
        parsed = sqlparse.parse(body)
        if not parsed:
            return None
        tokens = [token for token in parsed[0].tokens if not token.is_whitespace]
        return self._collect_first_identifier_value(tokens)

    def _parse_alter_rename_column_clause(self, clause: str) -> tuple[str, str] | None:
        body = self._extract_clause_after_keyword(clause, "RENAME COLUMN")
        if not body:
            return None
        body = body.rstrip(";")
        parsed = sqlparse.parse(body)
        if not parsed:
            return None
        tokens = [token for token in parsed[0].tokens if not token.is_whitespace]
        identifier_values: list[str] = []
        for token in tokens:
            if token.match(sqlparse.tokens.Keyword, "TO"):
                continue
            value = self._identifier_value(token)
            if value:
                identifier_values.append(value)
        if len(identifier_values) >= 2:
            return (identifier_values[0], identifier_values[1])
        return None

    def _extract_clause_after_keyword(self, clause: str, keyword: str) -> str:
        if not clause:
            return ""
        normalized = clause.upper()
        normalized_keyword = keyword.upper()
        idx = normalized.find(normalized_keyword)
        if idx == -1:
            return ""
        start = idx + len(keyword)
        return clause[start:].strip()

    def _strip_if_not_exists_clause(self, clause: str) -> str:
        normalized = clause.lstrip()
        upper = normalized.upper()
        prefix = "IF NOT EXISTS"
        if upper.startswith(prefix):
            return normalized[len(prefix) :].strip()
        return clause

    def _strip_if_exists_clause(self, clause: str) -> str:
        normalized = clause.lstrip()
        upper = normalized.upper()
        prefix = "IF EXISTS"
        if upper.startswith(prefix):
            return normalized[len(prefix) :].strip()
        return clause

    def _collect_first_identifier_value(self, tokens: list[Token]) -> str | None:
        for token in tokens:
            value = self._identifier_value(token)
            if value:
                return value
        return None

    def _identifier_value(self, token: Token) -> str | None:
        if isinstance(token, Identifier):
            return token.value
        if token.ttype in {sqlparse.tokens.Name, sqlparse.tokens.Name.Builtin}:
            return token.value
        return None

    def _peek_token(self, tokens: list[Token], idx: int) -> Token | None:
        return tokens[idx] if idx < len(tokens) else None
