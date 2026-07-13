"""Observability: structured logging and metrics hooks."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator


@dataclass
class MetricEvent:
  name: str
  value: float
  tags: dict[str, str] = field(default_factory=dict)
  timestamp: float = field(default_factory=time.time)


class OpsLogger:
  """Structured operational logger for agent and workflow events."""

  def __init__(self, name: str = "lola", level: str = "INFO") -> None:
    self._logger = logging.getLogger(name)
    self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not self._logger.handlers:
      handler = logging.StreamHandler()
      handler.setFormatter(logging.Formatter("%(message)s"))
      self._logger.addHandler(handler)
    self._metrics: list[MetricEvent] = []
    self._metrics_enabled = True

  def set_metrics_enabled(self, enabled: bool) -> None:
    self._metrics_enabled = enabled

  def _emit(self, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    self._logger.info(json.dumps(payload, default=str))

  def agent_started(self, agent_id: str, agent_name: str, task_id: str) -> None:
    self._emit("agent.started", agent_id=agent_id, agent_name=agent_name, task_id=task_id)

  def agent_completed(self, agent_id: str, task_id: str, duration_s: float | None) -> None:
    self._emit("agent.completed", agent_id=agent_id, task_id=task_id, duration_s=duration_s)

  def agent_failed(self, agent_id: str, task_id: str, error: str) -> None:
    self._emit("agent.failed", agent_id=agent_id, task_id=task_id, error=error)

  def workflow_started(self, workflow_id: str, workflow_name: str) -> None:
    self._emit("workflow.started", workflow_id=workflow_id, workflow_name=workflow_name)

  def workflow_completed(self, workflow_id: str, succeeded: bool) -> None:
    self._emit("workflow.completed", workflow_id=workflow_id, succeeded=succeeded)

  def record_metric(self, name: str, value: float, **tags: str) -> None:
    if not self._metrics_enabled:
      return
    self._metrics.append(MetricEvent(name=name, value=value, tags=tags))

  @contextmanager
  def span(self, name: str, **tags: str) -> Generator[None, None, None]:
    start = time.perf_counter()
    self._emit("span.start", span=name, **tags)
    try:
      yield
    finally:
      elapsed = time.perf_counter() - start
      self.record_metric(f"span.{name}.duration", elapsed, **tags)
      self._emit("span.end", span=name, duration_s=elapsed, **tags)

  @property
  def metrics(self) -> list[MetricEvent]:
    return list(self._metrics)
