"""
Enum Translator - PostgreSQL ENUM type translation (Feature 035)

Translates PostgreSQL ENUM type references for IRIS compatibility:
- Column types: "enum_type" → VARCHAR(64)
- Type casts: 'value'::"enum_type" → 'value'
- ALTER COLUMN SET DATA TYPE: "enum_type" → VARCHAR(64)

Constitutional Requirements:
- Must use enum registry to identify registered types
- Case-insensitive matching
- Handle schema-qualified and quoted identifiers
"""

import re

from .enum_registry import EnumTypeRegistry


class EnumTranslator:
    """
    Translates PostgreSQL ENUM type references to IRIS-compatible types.

    Works with EnumTypeRegistry to identify which types are registered enums.

    Translations:
    - Column type definitions using enum types → VARCHAR(64)
    - Enum type casts 'value'::"type" → 'value' (cast stripped)
    - ALTER COLUMN SET DATA TYPE "enum" → VARCHAR(64)
    """

    # Target type for enum columns
    VARCHAR_REPLACEMENT = "VARCHAR(64)"

    def __init__(self, enum_registry: EnumTypeRegistry):
        """
        Initialize enum translator with registry.

        Args:
            enum_registry: Session-scoped enum type registry
        """
        self._enum_registry = enum_registry

    def translate(self, sql: str) -> tuple[str, int]:
        """
        Apply all enum translations to SQL statement.

        Args:
            sql: SQL statement potentially containing enum references

        Returns:
            Tuple of (translated_sql, translation_count)
        """
        if not sql or len(self._enum_registry) == 0:
            return sql, 0

        total_count = 0

        # Step 1: Strip enum casts
        sql, cast_count = self.strip_enum_casts(sql)
        total_count += cast_count

        # Step 2: Translate column types
        sql, type_count = self.translate_column_types(sql)
        total_count += type_count

        return sql, total_count

    def translate_column_types(self, sql: str) -> tuple[str, int]:
        """
        Translate enum type references to VARCHAR(64) in column definitions.

        Handles patterns like:
        - "column_name" "enum_type" NOT NULL
        - "column_name" "public"."enum_type"
        - SET DATA TYPE "enum_type"

        Args:
            sql: SQL statement

        Returns:
            Tuple of (translated_sql, translation_count)
        """
        count = 0

        # Build pattern to match registered enum types
        # Match: "type_name" or "schema"."type_name" as a type reference
        # This is tricky because we need context to know it's a type, not a column name

        for type_name in self._enum_registry.get_registered_types():
            # Pattern to match the type as a column type (after column name or after SET DATA TYPE)
            # We look for patterns where the enum appears as a type reference

            # Pattern 1: SET DATA TYPE ["schema".]"type_name"
            pattern1 = re.compile(
                rf'\bSET\s+DATA\s+TYPE\s+("[\w]+"\.)?"?{re.escape(type_name)}"?', re.IGNORECASE
            )
            sql, n = pattern1.subn(f"SET DATA TYPE {self.VARCHAR_REPLACEMENT}", sql)
            count += n

            # Pattern 2: Column definition where type follows column name
            # "col_name" "enum_type" or "col_name" "schema"."enum_type"
            # This is hard to do perfectly with regex, so we match the type when it appears
            # as a standalone quoted identifier that matches our enum

            # Pattern: standalone "enum_type" that is a registered enum (as type position)
            # We need to be careful not to replace column names, so we look for
            # patterns where the enum type appears after another identifier or after a comma

            pattern2 = re.compile(
                rf'(\s+|,\s*)("[\w]+"\.)?"?{re.escape(type_name)}"?(\s*(?:NOT\s+NULL|NULL|DEFAULT|PRIMARY|UNIQUE|REFERENCES|CHECK|,|\)))',
                re.IGNORECASE,
            )

            def replace_type(m):
                nonlocal count
                count += 1
                prefix = m.group(1)
                suffix = m.group(3)
                return f"{prefix}{self.VARCHAR_REPLACEMENT}{suffix}"

            sql = pattern2.sub(replace_type, sql)

        return sql, count

    def strip_enum_casts(self, sql: str) -> tuple[str, int]:
        """
        Strip enum type casts from expressions.

        Converts:
        - 'value'::"public"."enum_type" → 'value'
        - 'value'::"enum_type" → 'value'

        Args:
            sql: SQL statement with potential enum casts

        Returns:
            Tuple of (translated_sql, cast_strip_count)
        """
        count = 0

        for type_name in self._enum_registry.get_registered_types():
            # Pattern: 'value'::"schema"."type" or 'value'::"type"
            # The value can be any string literal
            pattern = re.compile(
                rf"('(?:[^']|'')*')::\"?(?:[\w]+\"\.)?\"?{re.escape(type_name)}\"?", re.IGNORECASE
            )

            def replace_cast(m):
                nonlocal count
                count += 1
                return m.group(1)  # Just the value without cast

            sql = pattern.sub(replace_cast, sql)

        return sql, count
