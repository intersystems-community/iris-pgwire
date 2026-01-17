"""
Utilities for tracking and monitoring bulk insert operations in iris-pgwire.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


@dataclass
class BulkInsertJob:
    """Track bulk insert operation state."""

    table_name: str
    total_rows: int
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    inserted_rows: int = 0
    failed_rows: int = 0
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    def mark_started(self) -> None:
        """Mark the job as started."""
        self.status = "running"
        self.started_at = datetime.now(UTC)

    def mark_completed(self, rows_inserted: int | None = None) -> None:
        """
        Mark the job as completed successfully.

        Args:
            rows_inserted: Optional total rows inserted (defaults to total_rows)
        """
        self.status = "completed"
        self.completed_at = datetime.now(UTC)
        if rows_inserted is not None:
            self.inserted_rows = rows_inserted
        else:
            self.inserted_rows = self.total_rows

    def mark_failed(self, error: str) -> None:
        """
        Mark the job as failed.

        Args:
            error: Error message
        """
        self.status = "failed"
        self.completed_at = datetime.now(UTC)
        self.error_message = error

    def rows_per_second(self) -> float:
        """
        Calculate the throughput of the bulk insert job.

        Returns:
            Rows per second
        """
        if not self.started_at:
            return 0.0

        end_time = self.completed_at or datetime.now(UTC)
        duration = (end_time - self.started_at).total_seconds()

        if duration <= 0:
            return float(self.inserted_rows)

        return self.inserted_rows / duration
