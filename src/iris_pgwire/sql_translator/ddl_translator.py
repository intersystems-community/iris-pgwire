"""DDL translation helper models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from ..config import DDLTranslationConfig
from .reserved_words import ReservedWordChecker

if TYPE_CHECKING:
    from .constraint_translator import ConstraintTranslator
    from .ddl_parser import ColumnDefinition, ConstraintDefinition, IndexDefinition
    from .type_translator import TypeTranslator


@dataclass(frozen=True)
class DDLTranslationError(Exception):
    """Structured error raised when DDL cannot be translated."""

    error_code: str
    message: str
    suggested_fix: str | None
    original_sql: str

    def __str__(self) -> str:
        return f"{self.error_code}: {self.message}"


@dataclass(frozen=True)
class DDLStatement:
    """Captured representation of a DDL statement and its translation."""

    raw_sql: str
    statement_type: str
    translated_sql: str | None = None
    schema_name: str | None = None
    table_name: str | None = None
    operation: str | None = None
    operation_details: dict[str, Any] | None = None
    index_name: str | None = None
    index_definition: IndexDefinition | None = None
    columns: tuple[ColumnDefinition, ...] = field(default_factory=tuple)
    constraints: tuple[ConstraintDefinition, ...] = field(default_factory=tuple)
    translation_warnings: tuple[str, ...] = field(default_factory=tuple)
    is_translatable: bool = True
    skip_reason: str | None = None


class DDLTranslator:
    """Translates parsed DDL statements into IRIS-compatible SQL."""

    def __init__(
        self,
        config: DDLTranslationConfig | None = None,
        reserved_checker: ReservedWordChecker | None = None,
        type_translator: TypeTranslator | None = None,
        constraint_translator: ConstraintTranslator | None = None,
    ) -> None:
        self._config = config or DDLTranslationConfig()
        self._reserved_checker = reserved_checker or ReservedWordChecker()
        self._type_translator = type_translator or self._load_type_translator()
        self._constraint_translator = constraint_translator or self._load_constraint_translator()

    def translate_statement(self, parsed_statement: DDLStatement) -> DDLStatement:
        base_warnings = tuple(parsed_statement.translation_warnings)
        statement_type = (parsed_statement.statement_type or "").upper()

        try:
            if statement_type == "CREATE_TABLE":
                return self.translate_create_table(parsed_statement)

            if statement_type == "ALTER_TABLE":
                operation = (parsed_statement.operation or "").upper()
                if operation == "ADD_COLUMN":
                    return self.translate_alter_add_column(parsed_statement)
                if operation == "DROP_COLUMN":
                    return self.translate_alter_drop_column(parsed_statement)
                if operation == "RENAME_COLUMN":
                    return self.translate_alter_rename_column(parsed_statement)
                warning = f"Unsupported ALTER TABLE operation: {operation or 'UNKNOWN'}"
                return replace(
                    parsed_statement,
                    is_translatable=False,
                    translation_warnings=base_warnings + (warning,),
                    skip_reason="Unsupported ALTER TABLE operation",
                )

            if statement_type == "DROP_TABLE":
                return self.translate_drop_table(parsed_statement)

            warning = f"Unsupported statement type: {statement_type or 'UNKNOWN'}"
            return replace(
                parsed_statement,
                is_translatable=False,
                translation_warnings=base_warnings + (warning,),
                skip_reason="Unsupported statement type",
            )

        except DDLTranslationError as error:
            message = f"{error.error_code}: {error.message}"
            if error.suggested_fix:
                message = f"{message}. {error.suggested_fix}"
            return replace(
                parsed_statement,
                is_translatable=False,
                translation_warnings=base_warnings + (message,),
                skip_reason=error.message,
            )

        except Exception as error:
            message = f"Translation error: {error}"
            return replace(
                parsed_statement,
                is_translatable=False,
                translation_warnings=base_warnings + (message,),
                skip_reason=str(error),
            )

    def translate_create_table(self, parsed_stmt: DDLStatement) -> DDLStatement:
        warnings: list[str] = list(parsed_stmt.translation_warnings)
        table_identifier = self._build_table_identifier(
            parsed_stmt.schema_name, parsed_stmt.table_name
        )
        if not table_identifier:
            warnings.append("Missing table name for CREATE TABLE statement")
            return DDLStatement(
                raw_sql=parsed_stmt.raw_sql,
                statement_type=parsed_stmt.statement_type,
                schema_name=parsed_stmt.schema_name,
                table_name=parsed_stmt.table_name,
                index_name=parsed_stmt.index_name,
                columns=parsed_stmt.columns,
                constraints=parsed_stmt.constraints,
                translation_warnings=tuple(warnings),
                is_translatable=False,
                skip_reason="Missing table name",
            )

        column_clauses: list[str] = []
        translated_columns: list[ColumnDefinition] = []
        try:
            for column in parsed_stmt.columns:
                translated = self._type_translator.translate_column(column)
                translated_columns.append(translated)
                column_clauses.append(self._build_column_clause(translated))

            for constraint in parsed_stmt.constraints:
                constraint_sql = self._constraint_translator.translate_constraint(constraint)
                if constraint_sql:
                    column_clauses.append(constraint_sql)

            body = ",\n    ".join(column_clauses)
            if not body:
                body = ""
            translated_sql = (
                f"CREATE TABLE {table_identifier} (\n    {body}\n);"
                if body
                else f"CREATE TABLE {table_identifier} ();"
            )

            return DDLStatement(
                raw_sql=parsed_stmt.raw_sql,
                statement_type=parsed_stmt.statement_type,
                translated_sql=translated_sql,
                schema_name=parsed_stmt.schema_name,
                table_name=parsed_stmt.table_name,
                index_name=parsed_stmt.index_name,
                columns=tuple(translated_columns),
                constraints=parsed_stmt.constraints,
                translation_warnings=tuple(warnings),
                is_translatable=True,
            )
        except DDLTranslationError as error:
            warnings.append(str(error))
            return DDLStatement(
                raw_sql=parsed_stmt.raw_sql,
                statement_type=parsed_stmt.statement_type,
                schema_name=parsed_stmt.schema_name,
                table_name=parsed_stmt.table_name,
                index_name=parsed_stmt.index_name,
                columns=parsed_stmt.columns,
                constraints=parsed_stmt.constraints,
                translation_warnings=tuple(warnings),
                is_translatable=False,
                skip_reason=error.message,
            )

    def translate_alter_add_column(self, stmt: DDLStatement) -> DDLStatement:
        warnings = list(stmt.translation_warnings)
        table_identifier = self._build_table_identifier(stmt.schema_name, stmt.table_name)
        if not table_identifier:
            warnings.append("Missing table name for ALTER TABLE ADD COLUMN statement")
            return replace(
                stmt,
                is_translatable=False,
                translation_warnings=tuple(warnings),
                skip_reason="Missing table name",
            )

        if not stmt.columns:
            warnings.append("No column definition present for ALTER TABLE ADD COLUMN")
            return replace(
                stmt,
                is_translatable=False,
                translation_warnings=tuple(warnings),
                skip_reason="Missing column definition",
            )

        column_clauses: list[str] = []
        translated_columns: list[ColumnDefinition] = []
        try:
            # Use ALTER TABLE-specific type translator with IRIS native syntax workaround
            alter_type_translator = self._load_type_translator(use_alter_table_syntax=True)

            for column in stmt.columns:
                translated = alter_type_translator.translate_column(column)
                translated_columns.append(translated)
                column_clauses.append(self._build_column_clause(translated))

            clause_sql = ", ".join(column_clauses)
            translated_sql = f"ALTER TABLE {table_identifier} ADD COLUMN {clause_sql};"
            return DDLStatement(
                raw_sql=stmt.raw_sql,
                statement_type=stmt.statement_type,
                translated_sql=translated_sql,
                schema_name=stmt.schema_name,
                table_name=stmt.table_name,
                operation=stmt.operation,
                operation_details=stmt.operation_details,
                columns=tuple(translated_columns),
                translation_warnings=tuple(warnings),
                is_translatable=True,
            )
        except DDLTranslationError as error:
            warnings.append(str(error))
            return replace(
                stmt,
                is_translatable=False,
                translation_warnings=tuple(warnings),
                skip_reason=error.message,
            )

    def translate_alter_drop_column(self, stmt: DDLStatement) -> DDLStatement:
        warnings = list(stmt.translation_warnings)
        table_identifier = self._build_table_identifier(stmt.schema_name, stmt.table_name)
        if not table_identifier:
            warnings.append("Missing table name for ALTER TABLE DROP COLUMN statement")
            return replace(
                stmt,
                is_translatable=False,
                translation_warnings=tuple(warnings),
                skip_reason="Missing table name",
            )

        details = stmt.operation_details or {}
        column_name = details.get("column_name")
        if not column_name:
            warnings.append("Missing column name for ALTER TABLE DROP COLUMN statement")
            return replace(
                stmt,
                is_translatable=False,
                translation_warnings=tuple(warnings),
                skip_reason="Missing column name",
            )

        quoted_column = self._quote_identifier(column_name)
        if not quoted_column:
            warnings.append("Unable to quote column name for ALTER TABLE DROP COLUMN")
            return replace(
                stmt,
                is_translatable=False,
                translation_warnings=tuple(warnings),
                skip_reason="Invalid column name",
            )

        translated_sql = f"ALTER TABLE {table_identifier} DROP COLUMN {quoted_column};"
        return DDLStatement(
            raw_sql=stmt.raw_sql,
            statement_type=stmt.statement_type,
            translated_sql=translated_sql,
            schema_name=stmt.schema_name,
            table_name=stmt.table_name,
            operation=stmt.operation,
            operation_details=stmt.operation_details,
            columns=stmt.columns,
            translation_warnings=tuple(warnings),
            is_translatable=True,
        )

    def translate_alter_rename_column(self, stmt: DDLStatement) -> DDLStatement:
        warnings = list(stmt.translation_warnings)

        # IRIS doesn't support ALTER TABLE RENAME COLUMN
        warnings.append("IRIS does not support ALTER TABLE RENAME COLUMN")
        return replace(
            stmt,
            is_translatable=False,
            translation_warnings=tuple(warnings),
            skip_reason="RENAME COLUMN not supported by IRIS",
        )

    def translate_drop_table(self, stmt: DDLStatement) -> DDLStatement:
        warning_msg = (
            "DROP TABLE support deferred - manually execute DROP TABLE with CASCADE or RESTRICT as needed",
        )
        return replace(
            stmt,
            is_translatable=False,
            translation_warnings=stmt.translation_warnings + warning_msg,
            skip_reason="DROP TABLE support deferred",
        )

    def _build_column_clause(self, column: ColumnDefinition) -> str:
        parts: list[str] = []
        quoted_name = self._quote_identifier(column.name)
        if quoted_name:
            parts.append(quoted_name)
        else:
            parts.append(column.name)
        parts.append(column.iris_type)
        if column.default:
            default_value = column.default.strip()
            # Skip DEFAULT if marked as unsupported (e.g., gen_random_uuid() for UUID)
            if default_value and default_value != "__SKIP_DEFAULT__":
                parts.append(f"DEFAULT {default_value}")
        if column.is_primary_key:
            parts.append("PRIMARY KEY")
        if not column.nullable:
            parts.append("NOT NULL")
        return " ".join(parts)

    def _build_table_identifier(
        self, schema_name: str | None, table_name: str | None
    ) -> str | None:
        quoted_table = self._quote_identifier(table_name)
        if not quoted_table:
            return None
        quoted_schema = self._quote_identifier(schema_name)
        if quoted_schema:
            return f"{quoted_schema}.{quoted_table}"
        return quoted_table

    def _quote_identifier(self, identifier: str | None) -> str | None:
        if identifier is None:
            return None
        normalized = identifier.strip()
        if not normalized:
            return None
        already_quoted = normalized.startswith('"') and normalized.endswith('"')
        if already_quoted:
            return normalized
        if not self._config.auto_quote_reserved_words:
            return normalized
        return self._reserved_checker.quote_if_needed(normalized)

    def _load_type_translator(self, use_alter_table_syntax: bool = False) -> TypeTranslator:
        from .type_translator import TypeTranslator

        return TypeTranslator(use_alter_table_syntax=use_alter_table_syntax)

    def _load_constraint_translator(self) -> ConstraintTranslator:
        from .constraint_translator import ConstraintTranslator

        return ConstraintTranslator()


__all__ = ["DDLTranslationError", "DDLStatement", "DDLTranslator"]
