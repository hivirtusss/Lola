"""Task model and lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
  PENDING = "pending"
  RUNNING = "running"
  COMPLETED = "completed"
  FAILED = "failed"
  CANCELLED = "cancelled"


class TaskResult(BaseModel):
  output: Any = None
  error: str | None = None
  metadata: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
  """A unit of work executed by an agent or workflow step."""

  id: str = Field(default_factory=lambda: str(uuid4()))
  name: str
  description: str = ""
  input: dict[str, Any] = Field(default_factory=dict)
  status: TaskStatus = TaskStatus.PENDING
  result: TaskResult | None = None
  created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
  started_at: datetime | None = None
  completed_at: datetime | None = None

  def mark_running(self) -> None:
    self.status = TaskStatus.RUNNING
    self.started_at = datetime.now(timezone.utc)

  def mark_completed(self, output: Any = None, metadata: dict[str, Any] | None = None) -> None:
    self.status = TaskStatus.COMPLETED
    self.result = TaskResult(output=output, metadata=metadata or {})
    self.completed_at = datetime.now(timezone.utc)

  def mark_failed(self, error: str, metadata: dict[str, Any] | None = None) -> None:
    self.status = TaskStatus.FAILED
    self.result = TaskResult(error=error, metadata=metadata or {})
    self.completed_at = datetime.now(timezone.utc)

  @property
  def succeeded(self) -> bool:
    return self.status == TaskStatus.COMPLETED

  @property
  def duration_seconds(self) -> float | None:
    if self.started_at is None or self.completed_at is None:
      return None
    return (self.completed_at - self.started_at).total_seconds()
