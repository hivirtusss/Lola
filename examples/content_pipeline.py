"""Example: run a two-step content pipeline with Lola."""

from __future__ import annotations

import asyncio

from lola.core.task import TaskResult
from lola.ops.config import LolaConfig
from lola.runtime.executor import Executor
from lola.tools.registry import ToolRegistry


async def main() -> None:
  tools = ToolRegistry()

  @tools.function("search", description="Search for information on a topic")
  def search(query: str) -> dict:
    return {"query": query, "findings": [f"Fact about {query} (1)", f"Fact about {query} (2)"]}

  @tools.function("summarize", description="Summarize findings")
  def summarize(findings: list[str]) -> str:
    return " ".join(findings)

  @tools.function("draft", description="Draft content from a brief")
  def draft(brief: str) -> str:
    return f"# Draft\n\nBased on: {brief}"

  config = LolaConfig.from_yaml("examples/lola.yaml")
  executor = Executor(config=config, tools=tools)

  async def researcher_handler(task):
    query = task.input.get("query", "")
    search_result = await tools.invoke("search", query=query)
    summary = await tools.invoke("summarize", findings=search_result["findings"])
    return TaskResult(output=summary)

  async def writer_handler(task):
    brief = task.input.get("brief", "")
    content = await tools.invoke("draft", brief=brief)
    return TaskResult(output=content)

  executor.agents_from_config(
    handlers={
      "researcher": researcher_handler,
      "writer": writer_handler,
    }
  )

  workflow = executor.workflow_from_config("content_pipeline")
  result = await executor.run_workflow(workflow, initial_context={"topic": "operational AI"})

  print("Succeeded:", result.succeeded)
  print("Final context:", result.context)


if __name__ == "__main__":
  asyncio.run(main())
