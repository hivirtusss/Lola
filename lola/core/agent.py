"""Agent model for AI operations."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Awaitable
from uuid import uuid4

from pydantic import BaseModel, Field

from lola.core.task import Task, TaskResult


class AgentState(str, Enum):
  IDLE = "idle"
  BUSY = "busy"
  ERROR = "error"
  STOPPED = "stopped"


Handler = Callable[[Task], TaskResult | Awaitable[TaskResult]]


class Agent(BaseModel):
  """An operational agent that executes tasks using registered tools."""

  id: str = Field(default_factory=lambda: str(uuid4()))
  name: str
  role: str = "assistant"
  description: str = ""
  tools: list[str] = Field(default_factory=list)
  state: AgentState = AgentState.IDLE
  metadata: dict[str, Any] = Field(default_factory=dict)

  model_config = {"arbitrary_types_allowed": True}

  _handler: Handler | None = None

  def with_handler(self, handler: Handler) -> Agent:
    self._handler = handler
    return self

  async def run(self, task: Task) -> TaskResult:
    if self._handler is None:
      raise RuntimeError(f"Agent '{self.name}' has no task handler configured")

    self.state = AgentState.BUSY
    task.mark_running()

    try:
      result = self._handler(task)
      if hasattr(result, "__await__"):
        result = await result

      if result.error:
        task.mark_failed(result.error, result.metadata)
        self.state = AgentState.ERROR
      else:
        task.mark_completed(result.output, result.metadata)
        self.state = AgentState.IDLE

      return result
    except Exception as exc:  # noqa: BLE001 — operational boundary
      task.mark_failed(str(exc))
      self.state = AgentState.ERROR
      return TaskResult(error=str(exc))
