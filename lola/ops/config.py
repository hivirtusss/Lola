"""Configuration loading for operational deployments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
  name: str
  role: str = "assistant"
  description: str = ""
  tools: list[str] = Field(default_factory=list)


class WorkflowStepConfig(BaseModel):
  name: str
  agent: str
  input: dict[str, Any] = Field(default_factory=dict)
  depends_on: list[str] = Field(default_factory=list)


class WorkflowConfig(BaseModel):
  name: str
  description: str = ""
  steps: list[WorkflowStepConfig] = Field(default_factory=list)


class OpsConfig(BaseModel):
  log_level: str = "INFO"
  metrics_enabled: bool = True


class LolaConfig(BaseModel):
  agents: list[AgentConfig] = Field(default_factory=list)
  workflows: list[WorkflowConfig] = Field(default_factory=list)
  ops: OpsConfig = Field(default_factory=OpsConfig)

  @classmethod
  def from_yaml(cls, path: str | Path) -> LolaConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return cls.model_validate(data or {})

  def to_yaml(self, path: str | Path) -> None:
    Path(path).write_text(
      yaml.safe_dump(self.model_dump(), sort_keys=False),
      encoding="utf-8",
    )
