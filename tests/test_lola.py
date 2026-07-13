"""Tests for the Lola AI operational framework."""

from __future__ import annotations

import pytest

from lola.core.agent import Agent
from lola.core.task import Task, TaskResult, TaskStatus
from lola.core.workflow import Workflow, WorkflowStep
from lola.ops.config import LolaConfig
from lola.runtime.executor import Executor
from lola.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_agent_runs_task_successfully():
  agent = Agent(name="test-agent").with_handler(lambda task: TaskResult(output={"echo": task.input}))

  task = Task(name="echo", input={"message": "hello"})
  result = await agent.run(task)

  assert result.output == {"echo": {"message": "hello"}}
  assert task.status == TaskStatus.COMPLETED
  assert task.duration_seconds is not None


@pytest.mark.asyncio
async def test_agent_handles_failures():
  agent = Agent(name="failing").with_handler(lambda _: TaskResult(error="boom"))

  task = Task(name="fail")
  result = await agent.run(task)

  assert result.error == "boom"
  assert task.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_tool_registry_invokes_function_tool():
  registry = ToolRegistry()

  @registry.function("add", description="Add two numbers")
  def add(a: int, b: int) -> int:
    return a + b

  assert await registry.invoke("add", a=2, b=3) == 5
  assert len(registry.list_tools()) == 1


@pytest.mark.asyncio
async def test_workflow_runs_steps_in_dependency_order():
  order: list[str] = []

  async def step_a_handler(task):
    order.append("a")
    return TaskResult(output="A-output")

  async def step_b_handler(task):
    order.append("b")
    assert task.input["brief"] == "A-output"
    return TaskResult(output="B-output")

  agents = {
    "agent-a": Agent(name="agent-a").with_handler(step_a_handler),
    "agent-b": Agent(name="agent-b").with_handler(step_b_handler),
  }

  workflow = Workflow(
    name="test-flow",
    steps=[
      WorkflowStep(name="a", agent_name="agent-a"),
      WorkflowStep(name="b", agent_name="agent-b", input_template={"brief": "$a"}, depends_on=["a"]),
    ],
  )

  result = await workflow.run(agents)
  assert result.succeeded
  assert order == ["a", "b"]
  assert result.context["b"] == "B-output"


@pytest.mark.asyncio
async def test_executor_run_workflow_with_config(tmp_path):
  config_path = tmp_path / "lola.yaml"
  LolaConfig(
    agents=[{"name": "worker", "role": "general"}],
    workflows=[{"name": "single", "steps": [{"name": "work", "agent": "worker"}]}],
  ).to_yaml(config_path)

  executor = Executor(config=LolaConfig.from_yaml(config_path))

  async def worker_handler(task):
    return TaskResult(output="done")

  executor.agents_from_config(handlers={"worker": worker_handler})
  workflow = executor.workflow_from_config("single")
  result = await executor.run_workflow(workflow)

  assert result.succeeded
  assert result.steps["work"].output == "done"
