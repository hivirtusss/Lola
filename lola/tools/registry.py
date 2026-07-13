"""Registry for discovering and invoking tools."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from lola.tools.base import Tool, ToolSpec


FunctionToolHandler = Callable[..., Any | Awaitable[Any]]


class FunctionTool(Tool):
  def __init__(self, name: str, description: str, handler: FunctionToolHandler, parameters: dict[str, Any] | None = None):
    self._spec = ToolSpec(name=name, description=description, parameters=parameters or {"type": "object", "properties": {}})
    self._handler = handler

  @property
  def spec(self) -> ToolSpec:
    return self._spec

  async def invoke(self, **kwargs: Any) -> Any:
    result = self._handler(**kwargs)
    if hasattr(result, "__await__"):
      return await result
    return result


class ToolRegistry:
  """Central registry for operational tools."""

  def __init__(self) -> None:
    self._tools: dict[str, Tool] = {}

  def register(self, tool: Tool) -> None:
    self._tools[tool.spec.name] = tool

  def function(
    self,
    name: str,
    *,
    description: str = "",
    parameters: dict[str, Any] | None = None,
  ) -> Callable[[FunctionToolHandler], FunctionToolHandler]:
    def decorator(handler: FunctionToolHandler) -> FunctionToolHandler:
      self.register(FunctionTool(name, description, handler, parameters))
      return handler

    return decorator

  def get(self, name: str) -> Tool | None:
    return self._tools.get(name)

  def list_tools(self) -> list[ToolSpec]:
    return [tool.spec for tool in self._tools.values()]

  def openai_schemas(self) -> list[dict[str, Any]]:
    return [tool.to_openai_schema() for tool in self._tools.values()]

  async def invoke(self, name: str, **kwargs: Any) -> Any:
    tool = self.get(name)
    if tool is None:
      raise KeyError(f"Tool not found: {name}")
    return await tool.invoke(**kwargs)
