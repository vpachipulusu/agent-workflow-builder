"""Validate a workflow definition (YAML + Python code)."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import yaml


def validate_workflow(workflow_dir: str) -> str:
    """Validate workflow artefacts in the given directory.

    Returns JSON: {"valid": true/false, "errors": [...]}
    """
    errors: list[str] = []
    wf_path = Path(workflow_dir)

    # -- Check workflow.yaml ------------------------------------------------
    yaml_path = wf_path / "workflow.yaml"
    if not yaml_path.exists():
        errors.append("workflow.yaml not found")
    else:
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                errors.append("workflow.yaml must be a YAML mapping")
            else:
                for field in ("name", "description", "start", "executors", "edges"):
                    if field not in data:
                        errors.append(f"Missing required field: {field}")

                executors = data.get("executors", [])
                edges = data.get("edges", [])
                start = data.get("start", "")

                executor_names = {e["name"] for e in executors if isinstance(e, dict) and "name" in e}

                if start and start not in executor_names:
                    errors.append(f"Start executor '{start}' not found in executor list")

                for i, edge in enumerate(edges):
                    if not isinstance(edge, dict):
                        errors.append(f"Edge {i} is not a mapping")
                        continue
                    src = edge.get("source", "")
                    tgt = edge.get("target", "")
                    if src not in executor_names:
                        errors.append(f"Edge {i}: source '{src}' not in executors")
                    if tgt not in executor_names:
                        errors.append(f"Edge {i}: target '{tgt}' not in executors")

                # Check graph connectivity (BFS from start)
                if start and executor_names and not errors:
                    adj: dict[str, list[str]] = {n: [] for n in executor_names}
                    for edge in edges:
                        if isinstance(edge, dict):
                            adj.setdefault(edge.get("source", ""), []).append(
                                edge.get("target", "")
                            )
                    visited: set[str] = set()
                    queue = [start]
                    while queue:
                        node = queue.pop(0)
                        if node in visited:
                            continue
                        visited.add(node)
                        queue.extend(adj.get(node, []))
                    unreachable = executor_names - visited
                    if unreachable:
                        errors.append(
                            f"Unreachable executors from '{start}': {sorted(unreachable)}"
                        )

        except yaml.YAMLError as exc:
            errors.append(f"YAML parse error: {exc}")

    # -- Check workflow.py --------------------------------------------------
    py_path = wf_path / "workflow.py"
    if not py_path.exists():
        errors.append("workflow.py not found")
    else:
        source = py_path.read_text(encoding="utf-8")
        try:
            ast.parse(source)
        except SyntaxError as exc:
            errors.append(f"Python syntax error in workflow.py: {exc}")

    result = {"valid": len(errors) == 0, "errors": errors}
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {"valid": False, "errors": ["Usage: validate_workflow.py <workflow_dir>"]}
            )
        )
        sys.exit(1)
    print(validate_workflow(sys.argv[1]))
