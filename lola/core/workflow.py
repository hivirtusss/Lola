"""Workflow orchestration across tasks and agents."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from lola.core.agent import Agent
from lola.core.task import Task, TaskResult, TaskStatus


class WorkflowStep(BaseModel):
  name: str
  agent_name: str
  input_template: dict[str, Any] = Field(default_factory=dict)
  depends_on: list[str] = Field(default_factory=list)


class WorkflowResult(BaseModel):
  workflow_id: str
  steps: dict[str, TaskResult]
  succeeded: bool
  context: dict[str, Any] = Field(default_factory=dict)


class Workflow(BaseModel):
  """A directed sequence of agent-backed steps with shared context."""

  id: str = Field(default_factory=lambda: str(uuid4()))
  name: str
  description: str = ""
  steps: list[WorkflowStep] = Field(default_factory=list)

  def _resolve_input(self, step: WorkflowStep, context: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key, value in step.input_template.items():
      if isinstance(value, str) and value.startswith("$"):
        ref = value[1:]
        resolved[key] = context.get(ref, value)
      else:
        resolved[key] = value
    return resolved

  def _topological_order(self) -> list[WorkflowStep]:
    by_name = {step.name: step for step in self.steps}
    visited: set[str] = set()
    order: list[WorkflowStep] = []

    def visit(name: str) -> None:
      if name in visited:
        return
      step = by_name[name]
      for dep in step.depends_on:
        visit(dep)
      visited.add(name)
      order.append(step)

    for step in self.steps:
      visit(step.name)

    return order

  async def run(self, agents: dict[str, Agent], initial_context: dict[str, Any] | None = None) -> WorkflowResult:
    context = dict(initial_context or {})
    results: dict[str, TaskResult] = {}
    succeeded = True

    for step in self._topological_order():
      agent = agents.get(step.agent_name)
      if agent is None:
        error = f"No agent registered for step '{step.name}': {step.agent_name}"
        results[step.name] = TaskResult(error=error)
        succeeded = False
        break

      task = Task(
        name=step.name,
        description=f"Workflow '{self.name}' step",
        input=self._resolve_input(step, context),
      )

      result = await agent.run(task)
      results[step.name] = result

      if result.output is not None:
        context[step.name] = result.output

      if task.status != TaskStatus.COMPLETED:
        succeeded = False
        break

    return WorkflowResult(
      workflow_id=self.id,
      steps=results,
      succeeded=succeeded,
      context=context,
    )
