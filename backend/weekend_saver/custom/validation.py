"""Decide whether an edited definition is safe to run.

The six core steps must all be present and every outcome of a core step must still
reach the core step it reached originally. Other steps may sit on the way: they pass
the run on unchanged, and an AI step may also end a run early (a gate), but only
before anything has been changed.

The framework's own type check cannot be relied on here, because a step that accepts
any message hides a mismatch between the steps on either side of it.
"""

import re
from collections.abc import Iterator

from weekend_saver.custom.catalog import CORE_BY_ID, CORE_BY_REF, CORE_STEPS
from weekend_saver.custom.definition import AGENT, BUILTIN, FUNCTION, EdgeDef, StepDef, WorkflowDef
from weekend_saver.errors import ConfigError
from weekend_saver.executors import (
    DEFAULT_ROUTES,
    LOAD_TARGETS_ID,
    REPORT_ID,
    VERIFY_ID,
)

MAX_STEPS = 30
# Each AI step can hold a run up while it waits for the model, enable runs included
MAX_AI_STEPS = 6
MAX_EDGES = 100
MAX_INSTRUCTION_CHARS = 4000
MAX_CONDITION_CHARS = 300
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TYPES = (BUILTIN, AGENT, FUNCTION)
# A run that is heading for one of these has already ended or already changed things
_TOO_LATE_FOR_A_GATE = frozenset({REPORT_ID, VERIFY_ID})


class DefinitionError(ConfigError):
    """The definition breaks one or more rules; `errors` lists them all."""

    def __init__(self, errors: tuple[str, ...]) -> None:
        super().__init__("The workflow definition is not valid. " + " ".join(errors))
        self.errors = errors


def validate(definition: WorkflowDef) -> tuple[str, ...]:
    """Every reason the definition cannot run; empty when it can."""
    # Each stage assumes the one before it found nothing, so stop at the first that does
    for check in (_shape_errors, _edge_rule_errors, _path_errors):
        # The same problem can be found from several edges; say it once
        errors = tuple(dict.fromkeys(check(definition)))
        if errors:
            return errors
    return ()


def core_routes(definition: WorkflowDef) -> dict[str, dict[str, str]]:
    """For each core step, the step each of its outcomes is sent to first.

    Only meaningful for a definition that passed `validate`.
    """
    return {
        step_id: {
            outcome: _outcome_edges(definition, step_id, outcome)[0].target for outcome in outcomes
        }
        for step_id, outcomes in DEFAULT_ROUTES.items()
    }


def forward_target(definition: WorkflowDef, name: str) -> str:
    """Where a custom step passes the run on to."""
    return next(edge.target for edge in definition.edges_from(name) if not edge.condition)


def stop_conditions(definition: WorkflowDef, name: str) -> tuple[str, ...]:
    """The conditions under which a custom step ends the run; non-empty makes it a gate."""
    return tuple(edge.condition for edge in definition.edges_from(name) if edge.condition)


# -- Stage 1: steps and edges are well formed --------------------------------------


def _shape_errors(definition: WorkflowDef) -> Iterator[str]:
    if len(definition.steps) > MAX_STEPS:
        yield f"A workflow can have at most {MAX_STEPS} steps."
    if len(definition.edges) > MAX_EDGES:
        yield f"A workflow can have at most {MAX_EDGES} edges."
    if sum(1 for step in definition.steps if step.type == AGENT) > MAX_AI_STEPS:
        yield (
            f"A workflow can have at most {MAX_AI_STEPS} AI steps; each one can hold "
            "a run up while it waits for the model."
        )
    names = [step.name for step in definition.steps]
    for name in sorted({name for name in names if names.count(name) > 1}):
        yield f"The step name '{name}' is used more than once."
    for step in definition.steps:
        yield from _step_errors(step)
    for core in CORE_STEPS:
        if not any(step.ref == core.ref for step in definition.steps if step.type == BUILTIN):
            yield (
                f"The core step '{core.step_id}' is missing; the six core steps "
                "cannot be removed."
            )
    known = set(names)
    for edge in definition.edges:
        for end in (edge.source, edge.target):
            if end not in known:
                yield f"An edge refers to a step named '{end}', which does not exist."
        if len(edge.condition) > MAX_CONDITION_CHARS:
            yield (
                f"The condition on the edge {edge.source} -> {edge.target} is longer "
                f"than {MAX_CONDITION_CHARS} characters."
            )
        if edge.fan_in:
            yield f"The edge {edge.source} -> {edge.target} uses fan-in, which is not supported."
    if definition.start not in known:
        yield f"The start step '{definition.start}' does not exist."


def _step_errors(step: StepDef) -> Iterator[str]:
    if not _NAME.fullmatch(step.name):
        yield (
            f"'{step.name}' is not a valid step name; use lower-case letters, digits and "
            "underscores, starting with a letter."
        )
    if step.type not in _TYPES:
        yield f"Step '{step.name}' has the unknown type '{step.type}'."
    elif step.type == BUILTIN:
        yield from _builtin_errors(step)
    elif step.type == AGENT and not step.instructions.strip():
        yield f"AI step '{step.name}' needs instructions."
    if step.type in (AGENT, FUNCTION) and step.config:
        yield f"Step '{step.name}' has settings, but only built-in steps have any."
    if len(step.instructions) > MAX_INSTRUCTION_CHARS:
        yield (
            f"The instructions of '{step.name}' are longer than "
            f"{MAX_INSTRUCTION_CHARS} characters."
        )


def _builtin_errors(step: StepDef) -> Iterator[str]:
    core = CORE_BY_REF.get(step.ref)
    if core is None:
        yield f"Step '{step.name}' uses an unknown built-in step '{step.ref}'."
        return
    if step.name != core.step_id:
        yield f"The built-in step '{step.ref}' must be named '{core.step_id}', not '{step.name}'."
    settings = {setting.name: setting for setting in core.settings}
    for key, value in step.config.items():
        if key not in settings:
            yield f"Step '{core.step_id}' has no setting named '{key}'."
        elif problem := settings[key].problem_with(value):
            yield f"Step '{core.step_id}': the setting '{key}' {problem}."


# -- Stage 2: every step has the edges its kind allows ------------------------------


def _edge_rule_errors(definition: WorkflowDef) -> Iterator[str]:
    for step in definition.steps:
        if step.is_core:
            yield from _core_edge_errors(definition, step.name)
        else:
            yield from _custom_edge_errors(definition, step)


def _core_edge_errors(definition: WorkflowDef, step_id: str) -> Iterator[str]:
    outcomes = CORE_BY_ID[step_id].outcomes
    outgoing = definition.edges_from(step_id)
    if not outcomes:
        if outgoing:
            yield f"'{step_id}' ends the run, so no edge can start from it."
        return
    listed = ", ".join(outcomes)
    for outcome in outcomes:
        if len(_outcome_edges(definition, step_id, outcome)) != 1:
            yield f"Step '{step_id}' needs exactly one edge for its outcome '{outcome}'."
    for edge in outgoing:
        if edge.condition and edge.condition not in outcomes:
            yield (
                f"Step '{step_id}' has no outcome named '{edge.condition}'; "
                f"its outcomes are: {listed}."
            )
        elif not edge.condition and len(outcomes) > 1:
            yield (
                f"Step '{step_id}' has several outcomes, so each of its edges needs one of "
                f"them as its condition: {listed}."
            )


def _outcome_edges(definition: WorkflowDef, step_id: str, outcome: str) -> list[EdgeDef]:
    # A step with a single outcome may leave the condition off its one edge
    accepted = {outcome} if len(CORE_BY_ID[step_id].outcomes) > 1 else {outcome, ""}
    return [edge for edge in definition.edges_from(step_id) if edge.condition in accepted]


def _custom_edge_errors(definition: WorkflowDef, step: StepDef) -> Iterator[str]:
    outgoing = definition.edges_from(step.name)
    if sum(1 for edge in outgoing if not edge.condition) != 1:
        yield (
            f"Step '{step.name}' needs exactly one edge without a condition, "
            "to pass the run on to the next step."
        )
    stops = [edge for edge in outgoing if edge.condition]
    if stops and step.type != AGENT:
        yield (
            "Only AI steps can stop a run; remove the conditions on the edges from "
            f"'{step.name}'."
        )
    for edge in stops:
        if edge.target != REPORT_ID:
            yield (
                f"A conditional edge from '{step.name}' ends the run, so it can only "
                f"point at '{REPORT_ID}'."
            )


# -- Stage 3: every path still connects the core steps the original way -------------


def _path_errors(definition: WorkflowDef) -> Iterator[str]:
    used: set[str] = set()

    start_target, chain = _follow(definition, definition.start)
    used.update(chain)
    if start_target != LOAD_TARGETS_ID:
        yield (
            f"The workflow must start at '{LOAD_TARGETS_ID}', directly or through "
            "custom steps."
        )

    for step_id, outcomes in DEFAULT_ROUTES.items():
        for outcome, expected in outcomes.items():
            first = _outcome_edges(definition, step_id, outcome)[0].target
            reached, chain = _follow(definition, first)
            used.update(chain)
            if reached is None:
                yield f"The path from '{step_id}' ({outcome}) never reaches a core step."
            elif reached != expected:
                yield (
                    f"The outcome '{outcome}' of '{step_id}' must lead to '{expected}', "
                    f"but it leads to '{reached}'."
                )
            elif expected in _TOO_LATE_FOR_A_GATE:
                yield from _late_gate_errors(definition, chain)

    for step in definition.steps:
        if not step.is_core and step.name not in used:
            yield f"Step '{step.name}' is not on any path of the workflow."


def _follow(definition: WorkflowDef, name: str) -> tuple[str | None, tuple[str, ...]]:
    """Walk through custom steps from `name` to the first core step.

    Returns that core step (None when the walk loops) and the custom steps passed.
    """
    chain: list[str] = []
    while name not in CORE_BY_ID:
        if name in chain:
            return None, tuple(chain)
        chain.append(name)
        name = forward_target(definition, name)
    return name, tuple(chain)


def _late_gate_errors(definition: WorkflowDef, chain: tuple[str, ...]) -> Iterator[str]:
    for name in chain:
        if stop_conditions(definition, name):
            yield (
                f"Gate step '{name}' is placed where the run has already ended or changed "
                "things; a gate can only stop a run before 'apply'."
            )
