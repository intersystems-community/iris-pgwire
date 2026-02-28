"""No-op cursor for skipped or idempotent DDL statements."""


class NoopCursor:
    """Cursor that returns no results. Used for skipped/comment-only/idempotent DDL."""

    def __init__(self):
        self.description = None
        self.rowcount = 0

    def close(self):
        pass

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def __iter__(self):
        return iter([])
