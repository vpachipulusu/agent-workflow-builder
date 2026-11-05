"""Core steps route by outcome name, and notes left by other steps reach the report."""

from typing import Any

import pytest
from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler

from tests.helpers import VM_TYPE, FakeHandler, specs
from weekend_saver.dashboard.serialize import report_to_json
from weekend_saver.errors import ConfigError
from weekend_saver.executors import (
    APPLY_ID,
    APPROVAL_ID,
    DEFAULT_ROUTES,
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
from weekend_saver.models import (
    Action,
    ApprovalRequest,
    PowerState,
    RunReport,
    RunRequest,
    RunStatus,
    StepNote,
)
from weekend_saver.notes import MAX_NOTE_CHARS, add_note, read_notes
from weekend_saver.report import format_report
from weekend_saver.runner import run_to_completion
from weekend_saver.state_store import JsonFileStateStore

RUNNING = PowerState.RUNNING


class Tap(Executor):
    """A step that is not part of the core pipeline: notes what it saw and passes it on."""

    def __init__(self, step_id: str, forward_to: str) -> None:
        super().__init__(id=step_id)
        self.forward_to = forward_to
        self.seen: list[Any] = []

    @handler
    async def passthrough(self, message: Any, ctx: WorkflowContext[Any]) -> None:
        self.seen.append(message)
        add_note(ctx, self.id, f"saw {type(message).__name__}")
        await ctx.send_message(message, target_id=self.forward_to)


def workflow_with_tap(handler_: FakeHandler, store, tap: Tap, routes: dict[str, dict[str, str]]):
    """The default pipeline with `tap` spliced in wherever `routes` point at it."""
    handlers = {VM_TYPE: handler_}
    steps = {
        LOAD_TARGETS_ID: LoadTargets(frozenset(handlers), routes=routes.get(LOAD_TARGETS_ID)),
        RESOLVE_STATE_ID: ResolveState(handlers, store, routes=routes.get(RESOLVE_STATE_ID)),
        APPROVAL_ID: Approval(routes=routes.get(APPROVAL_ID)),
        APPLY_ID: Apply(handlers, store, routes=routes.get(APPLY_ID)),
        VERIFY_ID: Verify(
            handlers, store, attempts=1, interval_seconds=0, routes=routes.get(VERIFY_ID)
        ),
        REPORT_ID: Report(),
        tap.id: tap,
    }
    builder = WorkflowBuilder(
        name="tapped", start_executor=steps[LOAD_TARGETS_ID], output_from=[steps[REPORT_ID]]
    )
    for source, outcomes in DEFAULT_ROUTES.items():
        for outcome, default_target in outcomes.items():
            target = routes.get(source, {}).get(outcome, default_target)
            builder = builder.add_edge(steps[source], steps[target])
    builder = builder.add_edge(tap, steps[tap.forward_to])
    return builder.build()


@pytest.fixture
def store(tmp_path) -> JsonFileStateStore:
    return JsonFileStateStore(tmp_path / "state.json")


async def must_not_ask(_: ApprovalRequest) -> bool:
    raise AssertionError("approval was requested but should not have been")


async def test_a_step_can_be_spliced_between_two_core_steps(store):
    handler_ = FakeHandler({"app": RUNNING})
    tap = Tap("summary", forward_to=REPORT_ID)
    workflow = workflow_with_tap(handler_, store, tap, {VERIFY_ID: {"verified": "summary"}})

    report = await run_to_completion(
        workflow, RunRequest(Action.DISABLE, specs("app"), auto_approve=True), must_not_ask
    )

    assert report.status is RunStatus.COMPLETED
    assert handler_.calls == [("disable", "app")]
    assert [type(message) for message in tap.seen] == [RunReport]


async def test_notes_left_by_a_step_are_carried_into_the_report(store):
    tap = Tap("summary", forward_to=REPORT_ID)
    workflow = workflow_with_tap(
        FakeHandler({"app": RUNNING}), store, tap, {VERIFY_ID: {"verified": "summary"}}
    )

    report = await run_to_completion(
        workflow, RunRequest(Action.DISABLE, specs("app"), auto_approve=True), must_not_ask
    )

    assert report.notes == (StepNote("summary", "saw RunReport"),)


async def test_notes_left_before_approval_are_shown_with_the_plan(store):
    tap = Tap("explain", forward_to=APPROVAL_ID)
    workflow = workflow_with_tap(
        FakeHandler({"app": RUNNING}), store, tap, {RESOLVE_STATE_ID: {"planned": "explain"}}
    )
    asked: list[ApprovalRequest] = []

    async def reject(request: ApprovalRequest) -> bool:
        asked.append(request)
        return False

    report = await run_to_completion(workflow, RunRequest(Action.DISABLE, specs("app")), reject)

    assert asked[0].notes == (StepNote("explain", "saw ActionPlan"),)
    assert report.status is RunStatus.REJECTED


async def test_the_early_exit_of_a_core_step_can_be_rerouted(store):
    tap = Tap("on_invalid", forward_to=REPORT_ID)
    workflow = workflow_with_tap(
        FakeHandler({}), store, tap, {LOAD_TARGETS_ID: {"invalid": "on_invalid"}}
    )

    report = await run_to_completion(workflow, RunRequest(Action.DISABLE, ()), must_not_ask)

    assert report.status is RunStatus.INVALID
    assert len(tap.seen) == 1


def test_default_routes_describe_the_original_pipeline():
    assert DEFAULT_ROUTES[APPROVAL_ID] == {
        "approved": APPLY_ID,
        "replan": LOAD_TARGETS_ID,
        "ended": REPORT_ID,
    }
    assert REPORT_ID not in DEFAULT_ROUTES


def test_an_unknown_outcome_name_is_rejected():
    with pytest.raises(ConfigError, match="'done'"):
        Approval(routes={"done": REPORT_ID})


async def test_approval_can_be_switched_off_for_manual_runs(store):
    handler_ = FakeHandler({"app": RUNNING})
    handlers = {VM_TYPE: handler_}
    load = LoadTargets(frozenset(handlers))
    resolve = ResolveState(handlers, store)
    approval = Approval(require_approval=False)
    apply = Apply(handlers, store)
    verify = Verify(handlers, store, attempts=1, interval_seconds=0)
    report_step = Report()
    workflow = (
        WorkflowBuilder(name="no-approval", start_executor=load, output_from=[report_step])
        .add_chain([load, resolve, approval, apply, verify, report_step])
        .add_edge(approval, load)
        .add_edge(load, report_step)
        .add_edge(resolve, report_step)
        .add_edge(approval, report_step)
        .build()
    )

    report = await run_to_completion(
        workflow, RunRequest(Action.DISABLE, specs("app")), must_not_ask
    )

    assert report.status is RunStatus.COMPLETED
    assert handler_.calls == [("disable", "app")]


async def test_a_dry_run_changes_nothing_even_without_approval(store):
    handler_ = FakeHandler({"app": RUNNING})
    handlers = {VM_TYPE: handler_}
    load = LoadTargets(frozenset(handlers))
    resolve = ResolveState(handlers, store)
    approval = Approval(require_approval=False)
    apply = Apply(handlers, store)
    verify = Verify(handlers, store, attempts=1, interval_seconds=0)
    report_step = Report()
    workflow = (
        WorkflowBuilder(name="dry", start_executor=load, output_from=[report_step])
        .add_chain([load, resolve, approval, apply, verify, report_step])
        .add_edge(approval, load)
        .add_edge(load, report_step)
        .add_edge(resolve, report_step)
        .add_edge(approval, report_step)
        .build()
    )

    report = await run_to_completion(
        workflow, RunRequest(Action.DISABLE, specs("app"), dry_run=True), must_not_ask
    )

    assert report.status is RunStatus.DRY_RUN
    assert handler_.calls == []


class _StateOnly:
    """The part of a workflow context that notes use."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    def get_state(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        self._state[key] = value


def test_notes_accumulate_in_order():
    ctx = _StateOnly()

    add_note(ctx, "first", "one")
    add_note(ctx, "second", "two")

    assert read_notes(ctx) == (StepNote("first", "one"), StepNote("second", "two"))


def test_a_step_that_speaks_again_replaces_its_earlier_note():
    ctx = _StateOnly()

    add_note(ctx, "explain", "first plan")
    add_note(ctx, "summary", "done")
    add_note(ctx, "explain", "second plan")

    assert read_notes(ctx) == (StepNote("summary", "done"), StepNote("explain", "second plan"))


def test_a_long_note_is_cut_short():
    ctx = _StateOnly()

    add_note(ctx, "chatty", "x" * (MAX_NOTE_CHARS + 500))

    assert len(read_notes(ctx)[0].text) == MAX_NOTE_CHARS


def test_an_empty_note_is_not_recorded():
    ctx = _StateOnly()

    add_note(ctx, "quiet", "   ")

    assert read_notes(ctx) == ()


def test_the_text_report_lists_notes():
    report = RunReport(
        Action.DISABLE, RunStatus.COMPLETED, notes=(StepNote("summary", "All quiet."),)
    )

    assert "  note (summary): All quiet." in format_report(report)


def test_a_stopped_run_has_its_own_headline():
    report = RunReport(Action.DISABLE, RunStatus.STOPPED)

    assert "stopped by a workflow step, nothing changed" in format_report(report)
    assert not report.failed


def test_the_json_report_includes_notes():
    report = RunReport(
        Action.DISABLE, RunStatus.COMPLETED, notes=(StepNote("summary", "All quiet."),)
    )

    assert report_to_json(report)["notes"] == [{"step": "summary", "text": "All quiet."}]
