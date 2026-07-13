"""Command-line interface for Lola."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from lola import __version__
from lola.ops.config import LolaConfig
from lola.runtime.executor import Executor


def main() -> None:
  parser = argparse.ArgumentParser(prog="lola", description="Lola AI operational framework")
  parser.add_argument("--version", action="version", version=f"lola {__version__}")

  sub = parser.add_subparsers(dest="command")

  validate = sub.add_parser("validate", help="Validate a Lola YAML config file")
  validate.add_argument("config", type=Path, help="Path to lola.yaml")

  init = sub.add_parser("init", help="Write a starter lola.yaml")
  init.add_argument("path", type=Path, nargs="?", default=Path("lola.yaml"))

  args = parser.parse_args()

  if args.command == "validate":
    config = LolaConfig.from_yaml(args.config)
    print(json.dumps({"valid": True, "agents": len(config.agents), "workflows": len(config.workflows)}))
    return

  if args.command == "init":
    starter = LolaConfig(
      agents=[
        {"name": "researcher", "role": "research", "tools": ["search", "summarize"]},
        {"name": "writer", "role": "content", "tools": ["draft"]},
      ],
      workflows=[
        {
          "name": "content_pipeline",
          "description": "Research then draft content",
          "steps": [
            {"name": "research", "agent": "researcher", "input": {"query": "$topic"}},
            {"name": "draft", "agent": "writer", "input": {"brief": "$research"}, "depends_on": ["research"]},
          ],
        }
      ],
    )
    starter.to_yaml(args.path)
    print(f"Wrote starter config to {args.path}")
    return

  parser.print_help()


if __name__ == "__main__":
  main()
