"""Turn a validated definition into a runnable Agent Framework workflow."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_framework import CheckpointStorage, Executor, Workflow, WorkflowBuilder

from weekend_saver.custom.catalog import CORE_BY_ID
from weekend_saver.custom.definition import FUNCTION, StepDef, WorkflowDef
from weekend_saver.custom.steps import (
    MODEL_TIMEOUT_SECONDS,
    GateStep,
    NoteStep,
    PassThrough,
    StepModel,
)
from weekend_saver.custom.validation import (
    DefinitionError,
    core_routes,
    forward_target,
    stop_conditions,
    validate,
)
from weekend_saver.executors import (
    APPLY_ID,
    APPROVAL_ID,
    LOAD_TARGETS_ID,
    REPORT_ID,
    RESOLVE_STATE_ID,
    VERIFY_ID,
    Apply,
    Approval,
    LoadTargets,
    Report,
    ResolveState,
    Verify,
)
from weekend_saver.handlers import ResourceHandler
from weekend_saver.models import StepNote
from weekend_saver.notifier import Notifier
from weekend_saver.state_store import StateStore
from weekend_saver.workflow import WORKFLOW_NAME

__all__ = ["DefinitionError", "compile_workflow"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def compile_workflow(
    definition: WorkflowDef,
    handlers: Mapping[str, ResourceHandler],
    state_store: StateStore,
    *,
    model: StepModel,
    notifier: Notifier | None = None,
    checkpoint_storage: CheckpointStorage | None = None,
    clock: Callable[[], datetime] = _utc_now,
    model_timeout_seconds: float = MODEL_TIMEOUT_SECONDS,
    verify_interval_seconds: float | None = None,
    notes: tuple[StepNote, ...] = (),
) -> Workflow:
    """Build the workflow a definition describes; raises DefinitionError if it is invalid.

    `verify_interval_seconds` replaces the default wait between checks when the
    definition does not set one. `notes` are added to every report of this workflow.
    """
    errors = validate(definition)
    if errors:
        raise DefinitionError(errors)

    core = _CoreOptions(handlers, state_store, notifier, clock, verify_interval_seconds, notes)
    steps = _core_steps(definition, core)
    for step in definition.steps:
        if not step.is_core:
            steps[step.name] = _custom_step(definition, step, model, clock, model_timeout_seconds)

    builder = WorkflowBuilder(
        name=WORKFLOW_NAME,
        description=definition.description,
        start_executor=steps[definition.start],
        checkpoint_storage=checkpoint_storage,
        output_from=[steps[REPORT_ID]],
    )
    # A gate with several stop conditions has several edges to the same step
    for source, target in dict.fromkeys((edge.source, edge.target) for edge in definition.edges):
        builder = builder.add_edge(steps[source], steps[target])
    return builder.build()


@dataclass(frozen=True)
class _CoreOptions:
    handlers: Mapping[str, ResourceHandler]
    state_store: StateStore
    notifier: Notifier | None
    clock: Callable[[], datetime]
    verify_interval_seconds: float | None
    notes: tuple[StepNote, ...]


def _core_steps(definition: WorkflowDef, options: _CoreOptions) -> dict[str, Executor]:
    routes = core_routes(definition)
    handlers, state_store = options.handlers, options.state_store

    def setting(step_id: str, name: str, fallback: Any = None) -> Any:
        step = definition.step(step_id)
        default = next(item.default for item in CORE_BY_ID[step_id].settings if item.name == name)
        if fallback is not None:
            default = fallback
        return step.config.get(name, default) if step else default

    return {
        LOAD_TARGETS_ID: LoadTargets(frozenset(handlers), routes=routes[LOAD_TARGETS_ID]),
        RESOLVE_STATE_ID: ResolveState(
            handlers,
            state_store,
            clock=options.clock,
            max_snapshot_age=timedelta(days=setting(RESOLVE_STATE_ID, "max_snapshot_age_days")),
            routes=routes[RESOLVE_STATE_ID],
        ),
        APPROVAL_ID: Approval(
            require_approval=setting(APPROVAL_ID, "require_approval"),
            routes=routes[APPROVAL_ID],
        ),
        APPLY_ID: Apply(handlers, state_store, options.clock, routes=routes[APPLY_ID]),
        VERIFY_ID: Verify(
            handlers,
            state_store,
            attempts=setting(VERIFY_ID, "attempts"),
            interval_seconds=setting(
                VERIFY_ID, "interval_seconds", options.verify_interval_seconds
            ),
            routes=routes[VERIFY_ID],
        ),
        REPORT_ID: Report(
            options.notifier if setting(REPORT_ID, "notify") else None, options.notes
        ),
    }


def _custom_step(
    definition: WorkflowDef,
    step: StepDef,
    model: StepModel,
    clock: Callable[[], datetime],
    timeout_seconds: float,
) -> Executor:
    forward_to = forward_target(definition, step.name)
    if step.type == FUNCTION:
        return PassThrough(step.name, forward_to)

    def local_now() -> datetime:
        return clock().astimezone()

    conditions = stop_conditions(definition, step.name)
    if conditions:
        return GateStep(
            step.name,
            forward_to,
            REPORT_ID,
            step.instructions,
            conditions,
            model,
            local_now,
            timeout_seconds,
        )
    return NoteStep(step.name, forward_to, step.instructions, model, local_now, timeout_seconds)
