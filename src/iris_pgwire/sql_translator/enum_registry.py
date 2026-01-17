"""
Enum Type Registry - Session-scoped PostgreSQL ENUM type tracking (Feature 035)

Tracks registered PostgreSQL ENUM type names within a session to enable:
- Column type translation (enum → VARCHAR(64))
- Cast stripping ('value'::"enum_type" → 'value')
- DROP TYPE skip for registered enums

Constitutional Requirements:
- Session-scoped (not global)
- Case-insensitive matching
- Schema qualifiers stripped
"""



class EnumTypeRegistry:
    """
    Session-scoped registry for PostgreSQL ENUM type names.

    Maintains a set of registered enum type names (lowercase, unqualified)
    for use in column type translation and cast stripping.

    Lifecycle:
    - Created per connection/session
    - Types registered when CREATE TYPE ... AS ENUM is processed
    - Cleared when connection closes
    """

    def __init__(self):
        """Initialize empty enum type registry."""
        self._type_names: set[str] = set()
        self._enum_definitions: dict[str, list[str]] = {}

    def register(self, type_name: str, values: list[str] | None = None) -> None:
        """
        Register an enum type name and its values.

        Args:
            type_name: The enum type name, possibly schema-qualified and/or quoted.
            values: Optional list of enum values.
        """
        normalized = self._normalize_type_name(type_name)
        self._type_names.add(normalized)
        if values is not None:
            self._enum_definitions[normalized] = values

    def get_values(self, type_name: str) -> list[str] | None:
        """Get values for a registered enum."""
        normalized = self._normalize_type_name(type_name)
        return self._enum_definitions.get(normalized)

    def is_registered(self, type_name: str) -> bool:
        """
        Check if a type name is a registered enum.

        Args:
            type_name: The type name to check, possibly schema-qualified and/or quoted.

        Returns:
            True if the type is registered as an enum, False otherwise.
        """
        normalized = self._normalize_type_name(type_name)
        return normalized in self._type_names

    def clear(self) -> None:
        """Clear all registered enum types (called on connection close)."""
        self._type_names.clear()
        self._enum_definitions.clear()

    def get_registered_types(self) -> set[str]:
        """
        Get a copy of all registered type names.

        Returns:
            Set of normalized (lowercase, unqualified) type names.
        """
        return self._type_names.copy()

    def _normalize_type_name(self, type_name: str) -> str:
        """
        Normalize a type name for registry storage/lookup.

        Normalization:
        1. Strip schema qualifier ("public"."name" → "name")
        2. Remove quotes ("MyEnum" → MyEnum)
        3. Convert to lowercase (MyEnum → myenum)

        Args:
            type_name: Raw type name from SQL

        Returns:
            Normalized type name for registry operations
        """
        name = type_name.strip()

        # Handle schema-qualified names: "schema"."name" or schema."name" or "schema".name
        # Take the last part after any dot
        if "." in name:
            # Split on dot, take last part
            parts = name.split(".")
            name = parts[-1]

        # Remove surrounding quotes
        name = name.strip('"').strip("'")

        # Lowercase for case-insensitive matching
        return name.lower()

    def __len__(self) -> int:
        """Return number of registered enum types."""
        return len(self._type_names)

    def __contains__(self, type_name: str) -> bool:
        """Support 'in' operator for checking registration."""
        return self.is_registered(type_name)


# Global registry instance for tests (per-session instances used in production)
_default_registry = EnumTypeRegistry()


def get_enum_registry() -> EnumTypeRegistry:
    """Get the default enum registry."""
    return _default_registry
