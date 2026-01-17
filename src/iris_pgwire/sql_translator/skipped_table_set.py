"""
Skipped Table Registry - Session-scoped PostgreSQL table skip tracking (Feature 036)

Tracks table names whose CREATE TABLE statement was skipped due to
unsupported DDL constructs (like GENERATED ALWAYS AS ... STORED).
Enables skipping dependent CREATE INDEX statements.
"""



class SkippedTableSet:
    """
    Session-scoped set for skipped table names.

    Lifecycle:
    - Created per connection/session
    - Tables added when CREATE TABLE is skipped
    - Cleared when connection closes
    """

    def __init__(self):
        """Initialize empty set."""
        self._table_names: set[str] = set()

    def add(self, table_name: str) -> None:
        """
        Add a skipped table name.

        The name is normalized (lowercase, unqualified).
        """
        normalized = self._normalize_table_name(table_name)
        self._table_names.add(normalized)

    def contains(self, table_name: str) -> bool:
        """Check if a table name was skipped."""
        normalized = self._normalize_table_name(table_name)
        return normalized in self._table_names

    def clear(self) -> None:
        """Clear all skipped tables."""
        self._table_names.clear()

    def _normalize_table_name(self, table_name: str) -> str:
        """Normalize table name for set storage/lookup."""
        name = table_name.strip()
        if "." in name:
            name = name.split(".")[-1]
        return name.strip('"').strip("'").lower()

    def __contains__(self, table_name: str) -> bool:
        """Support 'in' operator."""
        return self.contains(table_name)
