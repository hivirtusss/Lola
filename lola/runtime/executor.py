"""Runtime executor for agents and workflows."""

from __future__ import annotations

from typing import Any

from lola.core.agent import Agent
from lola.core.task import Task, TaskResult
from lola.core.workflow import Workflow, WorkflowResult
from lola.ops.config import LolaConfig
from lola.ops.logging import OpsLogger
from lola.tools.registry import ToolRegistry


class Executor:
  """Operational runtime that wires agents, tools, and workflows together."""

  def __init__(
    self,
    *,
    config: LolaConfig | None = None,
    tools: ToolRegistry | None = None,
    logger: OpsLogger | None = None,
  ) -> None:
    self.config = config or LolaConfig()
    self.tools = tools or ToolRegistry()
    self.logger = logger or OpsLogger(level=self.config.ops.log_level)
    self.logger.set_metrics_enabled(self.config.ops.metrics_enabled)
    self._agents: dict[str, Agent] = {}

  def register_agent(self, agent: Agent) -> None:
    self._agents[agent.name] = agent

  def get_agent(self, name: str) -> Agent | None:
    return self._agents.get(name)

  async def run_task(self, agent_name: str, task: Task) -> TaskResult:
    agent = self._agents.get(agent_name)
    if agent is None:
      raise KeyError(f"Agent not found: {agent_name}")

    self.logger.agent_started(agent.id, agent.name, task.id)
    with self.logger.span("agent.run", agent=agent_name, task=task.name):
      result = await agent.run(task)

    if result.error:
      self.logger.agent_failed(agent.id, task.id, result.error)
    else:
      self.logger.agent_completed(agent.id, task.id, task.duration_seconds)

    return result

  async def run_workflow(self, workflow: Workflow, initial_context: dict[str, Any] | None = None) -> WorkflowResult:
    self.logger.workflow_started(workflow.id, workflow.name)
    with self.logger.span("workflow.run", workflow=workflow.name):
      result = await workflow.run(self._agents, initial_context)
    self.logger.workflow_completed(workflow.id, result.succeeded)
    return result

  def agents_from_config(self, handlers: dict[str, Any] | None = None) -> None:
    """Instantiate agents declared in config using optional handlers."""
    handlers = handlers or {}
    for agent_cfg in self.config.agents:
      agent = Agent(
        name=agent_cfg.name,
        role=agent_cfg.role,
        description=agent_cfg.description,
        tools=agent_cfg.tools,
      )
      handler = handlers.get(agent_cfg.name)
      if handler is not None:
        agent.with_handler(handler)
      self.register_agent(agent)

  def workflow_from_config(self, name: str) -> Workflow:
    cfg = next((w for w in self.config.workflows if w.name == name), None)
    if cfg is None:
      raise KeyError(f"Workflow not found in config: {name}")

    from lola.core.workflow import WorkflowStep

    return Workflow(
      name=cfg.name,
      description=cfg.description,
      steps=[
        WorkflowStep(
          name=step.name,
          agent_name=step.agent,
          input_template=step.input,
          depends_on=step.depends_on,
        )
        for step in cfg.steps
      ],
    )
