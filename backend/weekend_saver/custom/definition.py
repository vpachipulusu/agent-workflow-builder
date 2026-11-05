"""A workflow definition in the builder's format: steps (executors) and edges.

The format is the builder's `workflow.yaml`, with one addition: steps of type
`builtin` name one of the weekend-saver core steps through `ref`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from weekend_saver.custom.catalog import CORE_BY_REF, CORE_STEPS
from weekend_saver.errors import ConfigError
from weekend_saver.executors import DEFAULT_ROUTES, LOAD_TARGETS_ID

BUILTIN = "builtin"
AGENT = "agent"
FUNCTION = "function"

DEFINITION_NAME = "weekend_saver"
_DESCRIPTION = "Disable or enable Azure resources to save cost over the weekend"


@dataclass(frozen=True)
class StepDef:
    name: str
    type: str = AGENT
    instructions: str = ""
    ref: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_core(self) -> bool:
        return self.type == BUILTIN and self.ref in CORE_BY_REF


@dataclass(frozen=True)
class EdgeDef:
    source: str
    target: str
    condition: str = ""
    fan_in: bool = False


@dataclass(frozen=True)
class WorkflowDef:
    name: str
    description: str
    start: str
    steps: tuple[StepDef, ...]
    edges: tuple[EdgeDef, ...]

    def step(self, name: str) -> StepDef | None:
        return next((step for step in self.steps if step.name == name), None)

    def edges_from(self, name: str) -> tuple[EdgeDef, ...]:
        return tuple(edge for edge in self.edges if edge.source == name)


def default_definition() -> WorkflowDef:
    """The unmodified pipeline, as shipped."""
    steps = tuple(
        StepDef(step.step_id, BUILTIN, step.description, step.ref) for step in CORE_STEPS
    )
    edges = tuple(
        EdgeDef(source, target, outcome)
        for source, outcomes in DEFAULT_ROUTES.items()
        for outcome, target in outcomes.items()
    )
    return WorkflowDef(DEFINITION_NAME, _DESCRIPTION, LOAD_TARGETS_ID, steps, edges)


def parse_definition(data: Any) -> WorkflowDef:
    """Read the builder's format; raises ConfigError when the shape itself is wrong."""
    if not isinstance(data, Mapping):
        raise ConfigError("A workflow definition must be a mapping.")
    executors = _list_of_mappings(data, "executors")
    edges = _list_of_mappings(data, "edges")
    return WorkflowDef(
        _text(data, "name"),
        _text(data, "description", required=False),
        _text(data, "start"),
        tuple(_parse_step(item) for item in executors),
        tuple(_parse_edge(item) for item in edges),
    )


def definition_to_dict(definition: WorkflowDef) -> dict[str, Any]:
    """The builder's format, ready to be written as YAML or sent as JSON."""
    return {
        "name": definition.name,
        "description": definition.description,
        "start": definition.start,
        "executors": [_step_to_dict(step) for step in definition.steps],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "condition": edge.condition or None,
                "fan_in": edge.fan_in,
            }
            for edge in definition.edges
        ],
    }


def _step_to_dict(step: StepDef) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": step.name,
        "type": step.type,
        "instructions": step.instructions,
    }
    if step.type == BUILTIN:
        data["ref"] = step.ref
        data["config"] = dict(step.config)
    return data


def _parse_step(item: Mapping[str, Any]) -> StepDef:
    config = item.get("config", {})
    if config is None:
        config = {}
    if not isinstance(config, Mapping):
        raise ConfigError("The 'config' of a step must be a mapping of setting names to values.")
    return StepDef(
        _text(item, "name"),
        _text(item, "type", required=False) or AGENT,
        _text(item, "instructions", required=False),
        _text(item, "ref", required=False),
        dict(config),
    )


def _parse_edge(item: Mapping[str, Any]) -> EdgeDef:
    return EdgeDef(
        _text(item, "source"),
        _text(item, "target"),
        _text(item, "condition", required=False).strip(),
        item.get("fan_in") is True,
    )


def _list_of_mappings(data: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    items = data.get(key)
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        raise ConfigError(f"'{key}' must be a list of mappings.")
    return items


def _text(data: Mapping[str, Any], key: str, *, required: bool = True) -> str:
    value = data.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value):
        raise ConfigError(f"'{key}' must be {'a non-empty' if required else 'a'} string.")
    return value
