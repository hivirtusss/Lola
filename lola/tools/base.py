"""Base tool interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
  name: str
  description: str = ""
  parameters: dict[str, Any] = Field(default_factory=dict)


class Tool(ABC):
  """A callable capability exposed to agents."""

  @property
  @abstractmethod
  def spec(self) -> ToolSpec:
    ...

  @abstractmethod
  async def invoke(self, **kwargs: Any) -> Any:
    ...

  def to_openai_schema(self) -> dict[str, Any]:
    return {
      "type": "function",
      "function": {
        "name": self.spec.name,
        "description": self.spec.description,
        "parameters": self.spec.parameters,
      },
    }
