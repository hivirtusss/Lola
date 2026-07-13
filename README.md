# Lola

**Lola** is a lightweight AI operational framework for orchestrating agents, tools, and workflows. It gives you a small, explicit runtime for building reliable AI operations — from single-agent tasks to multi-step pipelines — with structured logging and YAML-driven configuration.

## Why Lola?

Running AI in production means more than calling an LLM. You need:

- **Agents** with clear roles and lifecycle state
- **Tasks** with status tracking and timing
- **Tools** registered in one place and invocable by name
- **Workflows** that chain steps with shared context and dependencies
- **Observability** via structured JSON logs and metric hooks

Lola provides these primitives without prescribing a specific LLM provider or UI.

## Quick start

### Install

```bash
pip install -e ".[dev]"
```

### Initialize config

```bash
lola init
```

This writes a starter `lola.yaml` with two agents and a content pipeline workflow.

### Run the example

```bash
python examples/content_pipeline.py
```

### Validate config

```bash
lola validate examples/lola.yaml
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Config    │────▶│   Executor   │────▶│  Workflow   │
│  (YAML)     │     │   Runtime    │     │  Engine     │
└─────────────┘     └──────┬───────┘     └──────┬──────┘
                           │                     │
                    ┌──────▼───────┐      ┌──────▼──────┐
                    │    Agents    │      │    Tasks    │
                    └──────┬───────┘      └─────────────┘
                           │
                    ┌──────▼───────┐
                    │ ToolRegistry │
                    └──────────────┘
```

## Core concepts

### Agents

An agent has a name, role, optional tools, and a task handler. Handlers return `TaskResult` with output or error.

```python
from lola.core.agent import Agent
from lola.core.task import Task, TaskResult

agent = Agent(name="researcher", role="research").with_handler(
    lambda task: TaskResult(output=f"Researched: {task.input['query']}")
)
```

### Tools

Register callable tools with decorators or explicit registration. Schemas can be exported for LLM function-calling.

```python
from lola.tools.registry import ToolRegistry

tools = ToolRegistry()

@tools.function("search", description="Search the web")
def search(query: str) -> list[str]:
    return [f"result for {query}"]
```

### Workflows

Workflows run ordered steps across agents. Step inputs support `$variable` references to prior step outputs.

```python
from lola.core.workflow import Workflow, WorkflowStep

workflow = Workflow(
    name="pipeline",
    steps=[
        WorkflowStep(name="research", agent_name="researcher", input_template={"query": "$topic"}),
        WorkflowStep(name="draft", agent_name="writer", input_template={"brief": "$research"}, depends_on=["research"]),
    ],
)
```

### Executor

The executor wires config, agents, tools, and observability together.

```python
from lola.runtime.executor import Executor
from lola.ops.config import LolaConfig

executor = Executor(config=LolaConfig.from_yaml("lola.yaml"))
executor.agents_from_config(handlers={...})
result = await executor.run_workflow(executor.workflow_from_config("content_pipeline"))
```

## Configuration

See `examples/lola.yaml` for a full example. Key sections:

| Section | Purpose |
|---------|---------|
| `ops` | Log level and metrics toggles |
| `agents` | Agent definitions (name, role, tools) |
| `workflows` | Multi-step pipelines with dependencies |

## Observability

Lola emits structured JSON log events for agent and workflow lifecycle:

- `agent.started` / `agent.completed` / `agent.failed`
- `workflow.started` / `workflow.completed`
- `span.start` / `span.end` with duration metrics

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT — see [LICENSE](LICENSE).
