"""Validate an agent definition (YAML + Python code)."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import yaml


def validate_agent(agent_dir: str) -> str:
    """Validate agent artefacts in the given directory.

    Returns JSON: {"valid": true/false, "errors": [...]}
    """
    errors: list[str] = []
    agent_path = Path(agent_dir)

    # -- Check agent.yaml ---------------------------------------------------
    yaml_path = agent_path / "agent.yaml"
    if not yaml_path.exists():
        errors.append("agent.yaml not found")
    else:
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                errors.append("agent.yaml must be a YAML mapping")
            else:
                for field in ("name", "description", "instructions", "model"):
                    if field not in data:
                        errors.append(f"Missing required field: {field}")
                instructions = data.get("instructions", "")
                if isinstance(instructions, str):
                    if len(instructions) < 10:
                        errors.append(
                            f"Instructions too short ({len(instructions)} chars, min 10)"
                        )
                    if len(instructions) > 32_000:
                        errors.append(
                            f"Instructions too long ({len(instructions)} chars, max 32000)"
                        )
        except yaml.YAMLError as exc:
            errors.append(f"YAML parse error: {exc}")

    # -- Check agent.py -----------------------------------------------------
    py_path = agent_path / "agent.py"
    if not py_path.exists():
        errors.append("agent.py not found")
    else:
        source = py_path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            errors.append(f"Python syntax error in agent.py: {exc}")

    result = {"valid": len(errors) == 0, "errors": errors}
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"valid": False, "errors": ["Usage: validate_agent.py <agent_dir>"]}))
        sys.exit(1)
    print(validate_agent(sys.argv[1]))
