"""The record of what the workflow switched off and on, one line per resource and change."""

from datetime import UTC, datetime

import pytest

from tests.helpers import VM_TYPE, FakeHandler, specs, vm_id
from tests.test_custom_workflow import FakeModel
from weekend_saver.activity import Change, JsonlActivityLog
from weekend_saver.custom.compiler import compile_workflow
from weekend_saver.custom.definition import default_definition
from weekend_saver.errors import ActivityLogError
from weekend_saver.models import Action, ApprovalRequest, PowerState, RunRequest, RunStatus
from weekend_saver.runner import run_to_completion
from weekend_saver.state_store import JsonFileStateStore, Snapshot
from weekend_saver.workflow import build_workflow

RUNNING, STOPPED = PowerState.RUNNING, PowerState.STOPPED
FRIDAY = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)
MONDAY = datetime(2026, 11, 9, 6, 0, tzinfo=UTC)


def change(name: str, action: str = "disable", at: datetime = FRIDAY, **overrides) -> Change:
    fields = {
        "at": at.isoformat(),
        "resource_id": vm_id(name),
        "action": action,
        "outcome": "succeeded",
        "detail": f"{action}d and verified",
        "state": "stopped" if action == "disable" else "running",
        **overrides,
    }
    return Change(**fields)


@pytest.fixture
def log(tmp_path) -> JsonlActivityLog:
    return JsonlActivityLog(tmp_path / "activity.jsonl")


# --- the file -------------------------------------------------------------------------------


def test_nothing_recorded_reads_as_empty(log):
    assert log.recent() == ()
    assert log.latest() == {}


def test_changes_come_back_newest_first(log):
    log.record([change("app"), change("db")])
    log.record([change("app", "enable", MONDAY)])

    assert [(c.name, c.action) for c in log.recent()] == [
        ("app", "enable"),
        ("db", "disable"),
        ("app", "disable"),
    ]


def test_one_resource_can_be_followed_whatever_the_case_of_its_id(log):
    log.record([change("app"), change("db"), change("app", "enable", MONDAY)])

    followed = log.recent(resource_id=vm_id("app").upper())

    assert [c.action for c in followed] == ["enable", "disable"]


def test_only_as_many_as_asked_for_are_returned(log):
    log.record([change(f"vm-{index}") for index in range(5)])

    assert [c.name for c in log.recent(limit=2)] == ["vm-4", "vm-3"]


def test_the_latest_change_of_each_resource_is_known(log):
    log.record([change("app"), change("db")])
    log.record([change("app", "enable", MONDAY)])

    latest = log.latest()

    assert latest[vm_id("app").lower()].action == "enable"
    assert latest[vm_id("db").lower()].action == "disable"


def test_recording_nothing_does_not_create_the_file(log, tmp_path):
    log.record([])

    assert not (tmp_path / "activity.jsonl").exists()


def test_a_damaged_line_is_skipped_not_fatal(log, tmp_path):
    log.record([change("app")])
    with (tmp_path / "activity.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write('{"at": "2026-11-09T06:00:00+00:00"}\n')
        handle.write('["a", "list"]\n')
    log.record([change("db")])

    assert [c.name for c in log.recent()] == ["db", "app"]


def test_bytes_that_are_not_text_are_skipped_too(log, tmp_path):
    log.record([change("app")])
    with (tmp_path / "activity.jsonl").open("ab") as handle:
        handle.write(b"\xff\xfe not text\n")
    log.record([change("db")])

    assert [c.name for c in log.recent()] == ["db", "app"]


def test_only_the_newest_part_of_a_very_long_record_is_read(tmp_path):
    path = tmp_path / "activity.jsonl"
    JsonlActivityLog(path).record([change(f"vm-{index:02}") for index in range(40)])
    line_bytes = path.stat().st_size // 40

    # Room for ten lines and a bit: the line the cut lands in is dropped, not half-read
    newest = JsonlActivityLog(path, max_read_bytes=line_bytes * 10 + 5).recent()

    assert [c.name for c in newest] == [f"vm-{index:02}" for index in range(39, 29, -1)]


def test_a_record_that_cannot_be_written_says_so(tmp_path):
    in_the_way = tmp_path / "activity.jsonl"
    in_the_way.mkdir()

    with pytest.raises(ActivityLogError, match="activity"):
        JsonlActivityLog(in_the_way).record([change("app")])


def test_a_record_that_cannot_be_read_says_so(tmp_path):
    in_the_way = tmp_path / "activity.jsonl"
    in_the_way.mkdir()

    with pytest.raises(ActivityLogError, match="activity"):
        JsonlActivityLog(in_the_way).recent()


# --- written by the workflow ----------------------------------------------------------------


async def approve(_: ApprovalRequest) -> bool:
    return True


async def reject(_: ApprovalRequest) -> bool:
    return False


@pytest.fixture
def store(tmp_path) -> JsonFileStateStore:
    return JsonFileStateStore(tmp_path / "state.json")


def workflow_for(handler: FakeHandler, store, log, now: datetime = FRIDAY):
    return build_workflow(
        {VM_TYPE: handler},
        store,
        verify_attempts=2,
        verify_interval_seconds=0,
        clock=lambda: now,
        activity=log,
    )


def request(action: Action, *names: str, **flags) -> RunRequest:
    return RunRequest(action, specs(*names), **flags)


async def test_a_disable_run_records_what_it_switched_off(store, log):
    handler = FakeHandler({"app": RUNNING, "idle": STOPPED})

    await run_to_completion(
        workflow_for(handler, store, log), request(Action.DISABLE, "app", "idle"), approve
    )

    assert log.recent() == (change("app", detail="disabled and verified"),)


async def test_an_enable_run_records_what_it_switched_back_on(store, log):
    handler = FakeHandler({"app": STOPPED})
    store.save(Snapshot({vm_id("app").lower(): FRIDAY.isoformat()}, FRIDAY.isoformat()))

    await run_to_completion(
        workflow_for(handler, store, log, MONDAY), request(Action.ENABLE, "app"), approve
    )

    assert log.recent() == (change("app", "enable", MONDAY, detail="enabled and verified"),)


async def test_a_change_that_failed_is_recorded_as_failed(store, log):
    handler = FakeHandler({"app": RUNNING, "db": RUNNING}, fail_action_on={"db"})

    await run_to_completion(
        workflow_for(handler, store, log), request(Action.DISABLE, "app", "db"), approve
    )

    recorded = {c.name: c for c in log.recent()}
    assert recorded["app"].outcome == "succeeded"
    assert (recorded["db"].outcome, recorded["db"].state) == ("failed", "running")
    assert "disable failed" in recorded["db"].detail


async def test_a_resource_the_run_never_touched_leaves_no_trace(store, log):
    # Its state cannot be read, so the plan reports it as failed without acting on it
    handler = FakeHandler({"app": RUNNING, "blind": RUNNING}, fail_status_on={"blind"})

    report = await run_to_completion(
        workflow_for(handler, store, log), request(Action.DISABLE, "app", "blind"), approve
    )

    assert report.failed
    assert handler.calls == [("disable", "app")]
    assert [c.name for c in log.recent()] == ["app"]


async def test_a_customized_workflow_keeps_the_record_too(store, log):
    handler = FakeHandler({"app": RUNNING})
    workflow = compile_workflow(
        default_definition(),
        {VM_TYPE: handler},
        store,
        model=FakeModel(),
        verify_interval_seconds=0,
        clock=lambda: FRIDAY,
        activity=log,
    )

    await run_to_completion(workflow, request(Action.DISABLE, "app"), approve)

    assert log.recent() == (change("app", detail="disabled and verified"),)


async def test_a_resource_that_never_stopped_is_recorded_as_failed(store, log):
    handler = FakeHandler({"app": RUNNING}, stuck={"app"})

    await run_to_completion(
        workflow_for(handler, store, log), request(Action.DISABLE, "app"), approve
    )

    assert [(c.outcome, c.state) for c in log.recent()] == [("failed", "running")]


@pytest.mark.parametrize(
    ("flags", "approver"),
    [({"dry_run": True}, approve), ({}, reject)],
    ids=["dry run", "rejected plan"],
)
async def test_a_run_that_changes_nothing_records_nothing(store, log, flags, approver):
    handler = FakeHandler({"app": RUNNING})

    await run_to_completion(
        workflow_for(handler, store, log), request(Action.DISABLE, "app", **flags), approver
    )

    assert log.recent() == ()


async def test_a_run_still_finishes_when_the_record_cannot_be_written(store, tmp_path):
    in_the_way = tmp_path / "activity.jsonl"
    in_the_way.mkdir()
    handler = FakeHandler({"app": RUNNING})

    report = await run_to_completion(
        workflow_for(handler, store, JsonlActivityLog(in_the_way)),
        request(Action.DISABLE, "app"),
        approve,
    )

    assert report.status is RunStatus.COMPLETED
    assert not report.failed
    assert handler.states["app"] is STOPPED
    assert [note.step for note in report.notes] == ["verify"]
    assert "activity record" in report.notes[0].text


async def test_a_workflow_without_a_record_runs_as_before(store):
    handler = FakeHandler({"app": RUNNING})
    workflow = build_workflow(
        {VM_TYPE: handler}, store, verify_attempts=2, verify_interval_seconds=0
    )

    report = await run_to_completion(workflow, request(Action.DISABLE, "app"), approve)

    assert not report.failed
    assert report.notes == ()
