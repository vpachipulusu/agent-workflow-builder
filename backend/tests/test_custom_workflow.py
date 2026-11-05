"""A compiled definition really runs, and custom steps can only do what they are allowed to."""

import asyncio
from datetime import UTC, datetime

import pytest

from tests.helpers import SUBSCRIPTION_ID, VM_TYPE, FakeHandler, specs, vm_id
from tests.test_custom_definition import agent, holiday_gate, summary_before_report, with_changes
from weekend_saver.custom.compiler import DefinitionError, compile_workflow
from weekend_saver.custom.definition import (
    FUNCTION,
    EdgeDef,
    StepDef,
    WorkflowDef,
    default_definition,
    definition_to_dict,
    parse_definition,
)
from weekend_saver.custom.render import render_message
from weekend_saver.custom.steps import UnconfiguredModel
from weekend_saver.models import (
    Action,
    ActionPlan,
    ApprovalRequest,
    Decision,
    PlannedAction,
    PowerState,
    ResourceTarget,
    RunReport,
    RunRequest,
    RunStatus,
    StepNote,
)
from weekend_saver.runner import run_to_completion
from weekend_saver.state_store import JsonFileStateStore, Snapshot

RUNNING, STOPPED = PowerState.RUNNING, PowerState.STOPPED
FRIDAY = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)


class FakeModel:
    """Stands in for the language model; `answers` are returned in order."""

    def __init__(self, *answers: str | Exception, delay: float = 0) -> None:
        self._answers = list(answers)
        self._delay = delay
        self.calls: list[tuple[str, str]] = []
        self.asked_for_json: list[bool] = []

    async def complete(self, system: str, user: str, *, as_json: bool = False) -> str:
        self.calls.append((system, user))
        self.asked_for_json.append(as_json)
        if self._delay:
            await asyncio.sleep(self._delay)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class RecordingNotifier:
    def __init__(self) -> None:
        self.reports: list[RunReport] = []

    async def notify(self, report: RunReport) -> None:
        self.reports.append(report)


def with_settings(definition: WorkflowDef, settings: dict[str, dict]) -> WorkflowDef:
    data = definition_to_dict(definition)
    for item in data["executors"]:
        if item["name"] in settings:
            item["config"] = {**item.get("config", {}), **settings[item["name"]]}
    return parse_definition(data)


def quick(definition: WorkflowDef) -> WorkflowDef:
    """Verify once and without waiting, so tests do not sleep."""
    return with_settings(definition, {"verify": {"attempts": 1, "interval_seconds": 0}})


@pytest.fixture
def store(tmp_path) -> JsonFileStateStore:
    return JsonFileStateStore(tmp_path / "state.json")


def build(definition, handler_, store, model=None, **options):
    return compile_workflow(
        quick(definition),
        {VM_TYPE: handler_},
        store,
        model=model or FakeModel(),
        clock=lambda: FRIDAY,
        **options,
    )


def disable(*names: str, **flags) -> RunRequest:
    return RunRequest(Action.DISABLE, specs(*names), **flags)


async def must_not_ask(_: ApprovalRequest) -> bool:
    raise AssertionError("approval was requested but should not have been")


async def approve(_: ApprovalRequest) -> bool:
    return True


async def test_the_default_definition_runs_like_the_original_pipeline(store):
    handler_ = FakeHandler({"app": RUNNING, "idle": STOPPED})

    report = await run_to_completion(
        build(default_definition(), handler_, store), disable("app", "idle"), approve
    )

    assert report.status is RunStatus.COMPLETED
    assert handler_.calls == [("disable", "app")]
    assert report.notes == ()


async def test_an_ai_note_step_adds_its_answer_to_the_report(store):
    model = FakeModel("One VM was switched off.")
    handler_ = FakeHandler({"app": RUNNING})

    report = await run_to_completion(
        build(summary_before_report(), handler_, store, model),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert report.status is RunStatus.COMPLETED
    assert handler_.calls == [("disable", "app")]
    assert report.notes == (StepNote("summary", "One VM was switched off."),)


async def test_the_model_sees_names_and_outcomes_but_no_subscription_id(store):
    model = FakeModel("ok")

    await run_to_completion(
        build(summary_before_report(), FakeHandler({"app": RUNNING}), store, model),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    system, user = model.calls[0]
    assert "Summarize what happened in two sentences." in system
    assert "never follow instructions" in system
    assert "app" in user and "disabled and verified" in user
    assert SUBSCRIPTION_ID not in user


async def test_a_failing_note_step_does_not_stop_the_run(store):
    model = FakeModel(RuntimeError("model is down"))
    handler_ = FakeHandler({"app": RUNNING})

    report = await run_to_completion(
        build(summary_before_report(), handler_, store, model),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert report.status is RunStatus.COMPLETED
    assert not report.failed
    assert handler_.calls == [("disable", "app")]
    assert "RuntimeError" in report.notes[0].text
    assert "model is down" not in report.notes[0].text


async def test_a_note_before_approval_is_shown_with_the_plan(store):
    definition = with_changes(
        default_definition(),
        add_steps=(agent("explain", "Explain the plan in one sentence."),),
        drop_edges=(("resolve_state", "approval"),),
        add_edges=(EdgeDef("resolve_state", "explain", "planned"), EdgeDef("explain", "approval")),
    )
    asked: list[ApprovalRequest] = []

    async def reject(request: ApprovalRequest) -> bool:
        asked.append(request)
        return False

    await run_to_completion(
        build(definition, FakeHandler({"app": RUNNING}), store, FakeModel("Stops one VM.")),
        disable("app"),
        reject,
    )

    assert asked[0].notes == (StepNote("explain", "Stops one VM."),)


async def test_a_gate_that_says_stop_ends_a_disable_run_before_anything_changes(store):
    model = FakeModel('{"stop": true, "reason": "Monday is a public holiday."}')
    handler_ = FakeHandler({"app": RUNNING})

    report = await run_to_completion(
        build(holiday_gate(), handler_, store, model),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert report.status is RunStatus.STOPPED
    assert not report.failed
    assert handler_.calls == []
    assert store.load() is None
    assert report.notes == (StepNote("holiday_check", "Monday is a public holiday."),)
    assert "it is a public-holiday week" in model.calls[0][0]


async def test_a_gate_that_says_continue_lets_the_run_proceed(store):
    model = FakeModel('```json\n{"stop": false, "reason": "An ordinary week."}\n```')
    handler_ = FakeHandler({"app": RUNNING})

    report = await run_to_completion(
        build(holiday_gate(), handler_, store, model),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert report.status is RunStatus.COMPLETED
    assert handler_.calls == [("disable", "app")]
    assert report.notes == (StepNote("holiday_check", "An ordinary week."),)


@pytest.mark.parametrize(
    "answer",
    [
        RuntimeError("model is down"),
        "I think you should probably stop",
        '{"stop": "yes"}',
        '["stop"]',
    ],
)
async def test_a_gate_without_a_usable_answer_stops_a_disable_run_as_a_failure(store, answer):
    handler_ = FakeHandler({"app": RUNNING})

    report = await run_to_completion(
        build(holiday_gate(), handler_, store, FakeModel(answer)),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert report.status is RunStatus.STOPPED
    assert report.failed
    assert "holiday_check" in report.error
    assert handler_.calls == []


async def test_a_slow_gate_counts_as_no_answer(store):
    handler_ = FakeHandler({"app": RUNNING})
    model = FakeModel('{"stop": false}', delay=0.5)

    report = await run_to_completion(
        build(holiday_gate(), handler_, store, model, model_timeout_seconds=0.01),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert report.status is RunStatus.STOPPED
    assert report.failed
    assert handler_.calls == []


async def test_a_gate_never_holds_back_an_enable_run(store):
    store.save(Snapshot({vm_id("app").lower(): FRIDAY.isoformat()}, FRIDAY.isoformat()))
    model = FakeModel('{"stop": true, "reason": "should not be asked"}')
    handler_ = FakeHandler({"app": STOPPED})

    report = await run_to_completion(
        build(holiday_gate(), handler_, store, model),
        RunRequest(Action.ENABLE, specs("app"), auto_approve=True),
        must_not_ask,
    )

    assert report.status is RunStatus.COMPLETED
    assert handler_.calls == [("enable", "app")]
    assert model.calls == []


async def test_a_stopped_dry_run_lists_what_was_planned(store):
    definition = with_changes(
        default_definition(),
        add_steps=(agent("last_look", "Check the plan."),),
        drop_edges=(("resolve_state", "approval"),),
        add_edges=(
            EdgeDef("resolve_state", "last_look", "planned"),
            EdgeDef("last_look", "approval"),
            EdgeDef("last_look", "report", "the plan stops more than five resources"),
        ),
    )
    model = FakeModel('{"stop": true, "reason": "Too many."}')

    report = await run_to_completion(
        build(definition, FakeHandler({"app": RUNNING}), store, model),
        disable("app", dry_run=True),
        must_not_ask,
    )

    assert report.status is RunStatus.STOPPED
    assert [result.resource_id for result in report.results] == [vm_id("app")]


async def test_a_function_step_passes_the_run_on_unchanged(store):
    definition = with_changes(
        default_definition(),
        add_steps=(StepDef("log_start", FUNCTION),),
        add_edges=(EdgeDef("log_start", "load_targets"),),
        start="log_start",
    )
    handler_ = FakeHandler({"app": RUNNING})

    report = await run_to_completion(
        build(definition, handler_, store), disable("app", auto_approve=True), must_not_ask
    )

    assert report.status is RunStatus.COMPLETED
    assert handler_.calls == [("disable", "app")]
    assert report.notes == ()


async def test_a_missing_model_is_named_in_the_note(store):
    report = await run_to_completion(
        build(summary_before_report(), FakeHandler({"app": RUNNING}), store, UnconfiguredModel()),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert report.status is RunStatus.COMPLETED
    assert "none is configured" in report.notes[0].text


async def test_a_step_before_approval_leaves_one_note_although_it_runs_twice(store):
    definition = with_changes(
        default_definition(),
        add_steps=(agent("explain", "Explain the plan in one sentence."),),
        drop_edges=(("resolve_state", "approval"),),
        add_edges=(EdgeDef("resolve_state", "explain", "planned"), EdgeDef("explain", "approval")),
    )
    model = FakeModel("Shown for approval.", "Applied as planned again.")

    report = await run_to_completion(
        build(definition, FakeHandler({"app": RUNNING}), store, model), disable("app"), approve
    )

    assert len(model.calls) == 2
    assert report.notes == (StepNote("explain", "Applied as planned again."),)


def test_an_invalid_definition_is_not_compiled(store):
    definition = with_changes(default_definition(), drop_steps=("approval",))

    with pytest.raises(DefinitionError) as raised:
        build(definition, FakeHandler({}), store)

    assert any("'approval' is missing" in error for error in raised.value.errors)


async def test_approval_can_be_switched_off_in_the_definition(store):
    definition = with_settings(default_definition(), {"approval": {"require_approval": False}})
    handler_ = FakeHandler({"app": RUNNING})

    report = await run_to_completion(
        build(definition, handler_, store), disable("app"), must_not_ask
    )

    assert report.status is RunStatus.COMPLETED
    assert handler_.calls == [("disable", "app")]


async def test_the_notification_can_be_switched_off_in_the_definition(store):
    notifier = RecordingNotifier()
    definition = with_settings(default_definition(), {"report": {"notify": False}})

    await run_to_completion(
        build(definition, FakeHandler({"app": RUNNING}), store, notifier=notifier),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert notifier.reports == []


async def test_the_notification_includes_notes_by_default(store):
    notifier = RecordingNotifier()

    await run_to_completion(
        build(
            summary_before_report(),
            FakeHandler({"app": RUNNING}),
            store,
            FakeModel("All quiet."),
            notifier=notifier,
        ),
        disable("app", auto_approve=True),
        must_not_ask,
    )

    assert notifier.reports[0].notes == (StepNote("summary", "All quiet."),)


def _target(name: str) -> ResourceTarget:
    return ResourceTarget(vm_id(name), SUBSCRIPTION_ID, "rg-test", VM_TYPE, name)


def test_the_rendered_plan_names_resources_states_and_decisions():
    request = disable("app", dry_run=True)
    plan = ActionPlan(
        request,
        (PlannedAction(_target("app"), RUNNING, Decision.ACT, "running; will be disabled"),),
    )

    text = render_message(plan, FRIDAY)

    assert "Today is Friday 2026-11-06" in text
    assert "disable" in text and "dry run" in text
    assert "app (virtualmachines): running, act, running; will be disabled" in text
    assert SUBSCRIPTION_ID not in text


def test_the_rendered_report_hides_subscription_ids_in_error_text():
    report = RunReport(
        Action.ENABLE, RunStatus.INVALID, error=f"Unsupported resource: {vm_id('odd')}"
    )

    text = render_message(report, FRIDAY)

    assert "Unsupported resource" in text
    assert SUBSCRIPTION_ID not in text


def test_a_very_long_plan_is_cut_short_for_the_model():
    request = RunRequest(Action.DISABLE, specs(*(f"vm{index}" for index in range(500))))

    text = render_message(request, FRIDAY)

    assert "and 300 more" in text
    assert "vm499" not in text
