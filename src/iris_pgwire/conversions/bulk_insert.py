"""
Utilities for tracking and monitoring bulk insert operations in iris-pgwire.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional


@dataclass
class BulkInsertJob:
    """Track bulk insert operation state."""

    table_name: str
    total_rows: int
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    inserted_rows: int = 0
    failed_rows: int = 0
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    def mark_started(self) -> None:
        """Mark the job as started."""
        self.status = "running"
        self.started_at = datetime.now(timezone.utc)

    def mark_completed(self, rows_inserted: Optional[int] = None) -> None:
        """
        Mark the job as completed successfully.

        Args:
            rows_inserted: Optional total rows inserted (defaults to total_rows)
        """
        self.status = "completed"
        self.completed_at = datetime.now(timezone.utc)
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
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error

    def rows_per_second(self) -> float:
        """
        Calculate the throughput of the bulk insert job.

        Returns:
            Rows per second
        """
        if not self.started_at:
            return 0.0

        end_time = self.completed_at or datetime.now(timezone.utc)
        duration = (end_time - self.started_at).total_seconds()

        if duration <= 0:
            return float(self.inserted_rows)

        return self.inserted_rows / duration
