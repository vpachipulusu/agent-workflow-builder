"""The customizable workflow through the protected API, alone and mounted in a host app."""

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import VM_TYPE, FakeHandler, vm_id
from tests.test_custom_definition import (
    agent,
    holiday_gate,
    summary_before_report,
    with_changes,
)
from tests.test_custom_workflow import FakeModel
from tests.test_dashboard_api import BASE_URL as STANDALONE_URL
from tests.test_dashboard_api import COOKIE as STANDALONE_COOKIE
from tests.test_dashboard_api import SESSION as STANDALONE_SESSION
from tests.test_dashboard_api import Dashboard, FakeAuth, FakeDiscovery
from weekend_saver.activity import JsonlActivityLog
from weekend_saver.config import save_resource_specs
from weekend_saver.custom.compiler import compile_workflow
from weekend_saver.custom.definition import EdgeDef, default_definition, definition_to_dict
from weekend_saver.custom.store import DefinitionStore
from weekend_saver.dashboard import definition_api
from weekend_saver.dashboard.app import (
    CHANGE_HEADER,
    DashboardServices,
    Exposure,
    background,
    create_app,
)
from weekend_saver.dashboard.history import RunHistory
from weekend_saver.dashboard.run_manager import RunManager
from weekend_saver.dashboard.scheduler import Scheduler, ScheduleStore
from weekend_saver.models import PowerState, ResourceSpec, RunRequest, StepNote
from weekend_saver.state_store import JsonFileStateStore, Snapshot

TOKEN = "one-time-link-code"
SESSION = "test-session-id"
COOKIE = "weekend_saver_session_builder"
PAGE_ORIGIN = "http://localhost:5173"
BACKEND = "http://localhost:8000"
CHANGE = {CHANGE_HEADER: "1"}
RUNNING, STOPPED = PowerState.RUNNING, PowerState.STOPPED
NOW = datetime(2026, 11, 6, 18, 0)
FAST_VERIFY = {"verify": {"attempts": 1, "interval_seconds": 0}}

BUILDER_EXPOSURE = Exposure(
    cookie_name=COOKIE,
    hosts=frozenset({"localhost", "127.0.0.1"}),
    origins=frozenset({PAGE_ORIGIN}),
    home_url="/",
)


def fast(data: dict) -> dict:
    """The definition with verification that does not wait, so tests do not sleep."""
    executors = [
        {**item, "config": {**item.get("config", {}), **FAST_VERIFY.get(item["name"], {})}}
        for item in data["executors"]
    ]
    return {**data, "executors": executors}


class Customizable:
    """A dashboard whose workflow comes from a saved definition, wired to fakes."""

    def __init__(self, tmp_path, handler: FakeHandler, model=None, editor=None) -> None:
        self.handler = handler
        self.model = model or FakeModel()
        self.definitions = DefinitionStore(
            tmp_path / "workflows" / "weekend_saver" / "workflow.yaml"
        )
        self.resources_path = tmp_path / "resources.yaml"
        self.state_store = JsonFileStateStore(tmp_path / "state.json")
        self.history = RunHistory(tmp_path / "runs.jsonl")
        self.activity = JsonlActivityLog(tmp_path / "activity.jsonl")
        handlers = {VM_TYPE: handler}

        def workflow_factory(request: RunRequest):
            definition, notice = self.definitions.runnable(request.action)
            return compile_workflow(
                definition,
                handlers,
                self.state_store,
                model=self.model,
                verify_interval_seconds=0,
                notes=(StepNote("workflow", notice),) if notice else (),
                activity=self.activity,
            )

        runs = RunManager(workflow_factory, self.history, clock=lambda: NOW)
        schedule_store = ScheduleStore(tmp_path / "schedule.json")
        self.services = DashboardServices(
            auth=FakeAuth(),
            discovery=FakeDiscovery(),
            handlers=handlers,
            state_store=self.state_store,
            resources_path=self.resources_path,
            workflow_factory=workflow_factory,
            runs=runs,
            schedule_store=schedule_store,
            scheduler=Scheduler(
                schedule_store, runs, request_for=lambda action: RunRequest(action, ())
            ),
            history=self.history,
            activity=self.activity,
            clock=lambda: NOW,
            definitions=self.definitions,
            editor=editor,
        )
        self.inner = create_app(self.services, TOKEN, session_id=SESSION, exposure=BUILDER_EXPOSURE)

        @asynccontextmanager
        async def lifespan(_: FastAPI):
            async with background(self.services):
                yield

        # The way the builder hosts it: mounted under a prefix, lifespan run by the host
        self.app = FastAPI(lifespan=lifespan)
        self.app.mount("/ws", self.inner)

    def manage(self, *names: str) -> None:
        save_resource_specs(self.resources_path, tuple(ResourceSpec(vm_id(n)) for n in names))


@pytest.fixture
def dashboard(tmp_path):
    return Customizable(tmp_path, FakeHandler({"app": RUNNING}))


def client_for(dashboard: Customizable) -> TestClient:
    client = TestClient(dashboard.app, base_url=BACKEND, follow_redirects=False)
    client.cookies.set(COOKIE, SESSION)
    return client


@pytest.fixture
def client(dashboard):
    with client_for(dashboard) as test_client:
        yield test_client


def data(response):
    body = response.json()
    assert body["success"], body
    return body["data"]


def finished_run(client: TestClient, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runs = data(client.get("/ws/api/runs"))
        if runs["current"] is None and runs["recent"]:
            return runs["recent"][0]
        time.sleep(0.02)
    raise AssertionError("the run did not finish in time")


def pending_plan(client: TestClient, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = data(client.get("/ws/api/runs"))["current"]
        if current and current["pending_plan"]:
            return current
        time.sleep(0.02)
    raise AssertionError("the run did not ask for approval in time")


# --- reading and changing the definition --------------------------------------------------


def test_the_definition_starts_as_the_default_with_the_step_catalog(client):
    view = data(client.get("/ws/api/definition"))

    assert view["definition"] == definition_to_dict(default_definition())
    assert view["is_default"] is True
    assert view["errors"] == []
    assert view["catalog"][0]["name"] == "load_targets"
    assert view["catalog"][2]["outcomes"] == {
        "approved": "apply",
        "replan": "load_targets",
        "ended": "report",
    }


def test_a_valid_definition_is_saved_and_drawn(client, dashboard):
    wanted = definition_to_dict(summary_before_report())

    view = data(client.put("/ws/api/definition", json={"definition": wanted}, headers=CHANGE))

    assert view["is_default"] is False
    assert dashboard.definitions.load() == summary_before_report()
    graph = data(client.get("/ws/api/workflow"))
    assert "summary" in [node["id"] for node in graph["nodes"]]


def test_an_invalid_definition_is_refused_with_every_reason(client, dashboard):
    broken = definition_to_dict(with_changes(default_definition(), drop_steps=("approval",)))

    response = client.put("/ws/api/definition", json={"definition": broken}, headers=CHANGE)

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert any("'approval' is missing" in error for error in body["data"]["errors"])
    assert dashboard.definitions.load() == default_definition()


def test_a_malformed_definition_is_refused(client):
    response = client.put("/ws/api/definition", json={"definition": {"name": "x"}}, headers=CHANGE)

    assert response.status_code == 400
    assert response.json()["data"]["errors"]


def test_reset_restores_the_default(client, dashboard):
    dashboard.definitions.save(summary_before_report())

    view = data(client.post("/ws/api/definition/reset", headers=CHANGE))

    assert view["is_default"] is True
    assert dashboard.definitions.load() == default_definition()


def test_changing_the_definition_needs_the_session_and_the_change_header(dashboard):
    wanted = {"definition": definition_to_dict(summary_before_report())}
    with client_for(dashboard) as signed_in:
        assert signed_in.put("/ws/api/definition", json=wanted).status_code == 403
    with TestClient(dashboard.app, base_url=BACKEND) as anonymous:
        assert anonymous.get("/ws/api/definition").status_code == 401
        assert anonymous.put("/ws/api/definition", json=wanted, headers=CHANGE).status_code == 401


def test_the_definition_routes_do_not_exist_for_a_fixed_workflow(tmp_path):
    fixed = Dashboard(tmp_path, FakeHandler({}))
    with TestClient(fixed.app, base_url=STANDALONE_URL) as standalone:
        standalone.cookies.set(STANDALONE_COOKIE, STANDALONE_SESSION)

        assert standalone.get("/api/definition").status_code == 404


# --- chat edits ---------------------------------------------------------------------------


def test_a_chat_edit_is_saved_even_when_the_model_drops_builtin_fields(tmp_path):
    asked: list[tuple[dict, str]] = []

    async def editor(current: dict, prompt: str) -> dict:
        asked.append((current, prompt))
        proposal = definition_to_dict(summary_before_report())
        for item in proposal["executors"]:
            # What a model typically returns: only the fields the builder's prompt lists
            item.pop("ref", None)
            item.pop("config", None)
            if item["name"] != "summary":
                item["type"] = "function"
        return proposal

    dashboard = Customizable(tmp_path, FakeHandler({}), editor=editor)
    with client_for(dashboard) as client:
        view = data(
            client.post(
                "/ws/api/definition/edit",
                json={"prompt": "summarize the results before the report"},
                headers=CHANGE,
            )
        )

    assert asked == [
        (definition_to_dict(default_definition()), "summarize the results before the report")
    ]
    assert view["errors"] == []
    assert dashboard.definitions.load() == summary_before_report()


def test_a_chat_edit_keeps_settings_the_model_did_not_mention(tmp_path):
    async def editor(current: dict, prompt: str) -> dict:
        return {
            **current,
            "executors": [
                {key: value for key, value in item.items() if key != "config"}
                for item in current["executors"]
            ],
        }

    dashboard = Customizable(tmp_path, FakeHandler({}), editor=editor)
    with client_for(dashboard) as client:
        data(
            client.put(
                "/ws/api/definition",
                json={"definition": fast(definition_to_dict(default_definition()))},
                headers=CHANGE,
            )
        )
        data(client.post("/ws/api/definition/edit", json={"prompt": "tidy up"}, headers=CHANGE))

    assert dashboard.definitions.load().step("verify").config == FAST_VERIFY["verify"]


def test_a_chat_edit_that_breaks_a_rule_changes_nothing(tmp_path):
    async def editor(current: dict, prompt: str) -> dict:
        return definition_to_dict(with_changes(default_definition(), drop_steps=("verify",)))

    dashboard = Customizable(tmp_path, FakeHandler({}), editor=editor)
    with client_for(dashboard) as client:
        response = client.post(
            "/ws/api/definition/edit", json={"prompt": "skip verification"}, headers=CHANGE
        )

    assert response.status_code == 400
    assert any("'verify' is missing" in error for error in response.json()["data"]["errors"])
    assert dashboard.definitions.load() == default_definition()


def test_a_failing_model_is_reported_without_its_message(tmp_path):
    async def editor(current: dict, prompt: str) -> dict:
        raise RuntimeError("api key sk-secret rejected")

    dashboard = Customizable(tmp_path, FakeHandler({}), editor=editor)
    with client_for(dashboard) as client:
        response = client.post(
            "/ws/api/definition/edit", json={"prompt": "anything"}, headers=CHANGE
        )

    assert response.status_code == 502
    assert "RuntimeError" in response.json()["error"]
    assert "sk-secret" not in response.text


async def test_a_model_that_does_not_answer_is_given_up_on(tmp_path, monkeypatch):
    async def editor(current: dict, prompt: str) -> dict:
        await asyncio.sleep(5)
        return current

    monkeypatch.setattr(definition_api, "EDIT_TIMEOUT_SECONDS", 0.05)
    dashboard = Customizable(tmp_path, FakeHandler({}), editor=editor)
    with client_for(dashboard) as client:
        response = client.post(
            "/ws/api/definition/edit", json={"prompt": "anything"}, headers=CHANGE
        )

    assert response.status_code == 502
    assert "TimeoutError" in response.json()["error"]
    assert dashboard.definitions.load() == default_definition()


def test_a_chat_edit_without_a_model_explains_itself(client):
    response = client.post("/ws/api/definition/edit", json={"prompt": "anything"}, headers=CHANGE)

    assert response.status_code == 400
    assert "language model" in response.json()["error"]


# --- running the customized workflow ------------------------------------------------------


def test_a_run_uses_the_saved_definition_and_records_its_notes(tmp_path):
    dashboard = Customizable(tmp_path, FakeHandler({"app": RUNNING}), FakeModel("All quiet."))
    dashboard.manage("app")
    dashboard.definitions.save(summary_before_report())

    with client_for(dashboard) as client:
        data(client.post("/ws/api/runs", json={"action": "disable"}, headers=CHANGE))
        plan = pending_plan(client)
        data(
            client.post(
                "/ws/api/runs/approval",
                json={"run_id": plan["id"], "approved": True},
                headers=CHANGE,
            )
        )
        record = finished_run(client)

    assert record["status"] == "completed"
    assert record["notes"] == [{"step": "summary", "text": "All quiet."}]
    assert dashboard.handler.calls == [("disable", "app")]


def test_notes_made_before_approval_come_with_the_plan(tmp_path):
    definition = with_changes(
        default_definition(),
        add_steps=(agent("explain", "Explain the plan."),),
        drop_edges=(("resolve_state", "approval"),),
        add_edges=(EdgeDef("resolve_state", "explain", "planned"), EdgeDef("explain", "approval")),
    )
    dashboard = Customizable(tmp_path, FakeHandler({"app": RUNNING}), FakeModel("Stops one VM."))
    dashboard.manage("app")
    dashboard.definitions.save(definition)

    with client_for(dashboard) as client:
        data(client.post("/ws/api/runs", json={"action": "disable"}, headers=CHANGE))
        plan = pending_plan(client)
        client.post(
            "/ws/api/runs/approval", json={"run_id": plan["id"], "approved": False}, headers=CHANGE
        )
        finished_run(client)

    assert plan["pending_plan"]["notes"] == [{"step": "explain", "text": "Stops one VM."}]


def test_a_gate_can_stop_a_disable_run_started_from_the_page(tmp_path):
    model = FakeModel('{"stop": true, "reason": "Monday is a public holiday."}')
    dashboard = Customizable(tmp_path, FakeHandler({"app": RUNNING}), model)
    dashboard.manage("app")
    dashboard.definitions.save(holiday_gate())

    with client_for(dashboard) as client:
        data(client.post("/ws/api/runs", json={"action": "disable"}, headers=CHANGE))
        record = finished_run(client)

    assert record["status"] == "stopped"
    assert record["failed"] is False
    assert dashboard.handler.calls == []


def _break_the_saved_definition(dashboard: Customizable) -> None:
    broken = definition_to_dict(with_changes(default_definition(), drop_steps=("approval",)))
    dashboard.definitions.path.parent.mkdir(parents=True, exist_ok=True)
    dashboard.definitions.path.write_text(yaml.safe_dump(broken), encoding="utf-8")


def test_a_disable_run_refuses_a_broken_definition_and_says_why(dashboard):
    dashboard.manage("app")
    _break_the_saved_definition(dashboard)

    with client_for(dashboard) as client:
        data(client.post("/ws/api/runs", json={"action": "disable"}, headers=CHANGE))
        record = finished_run(client)

    assert record["failed"] is True
    assert "'approval' is missing" in record["error"]
    assert dashboard.handler.calls == []


def test_an_enable_run_falls_back_to_the_default_workflow_and_says_so(tmp_path):
    dashboard = Customizable(tmp_path, FakeHandler({"app": STOPPED}))
    dashboard.manage("app")
    stamp = "2026-11-06T17:00:00+00:00"
    dashboard.state_store.save(Snapshot({vm_id("app").lower(): stamp}, stamp))
    _break_the_saved_definition(dashboard)

    with client_for(dashboard) as client:
        data(
            client.post(
                "/ws/api/runs",
                json={"action": "enable", "ignore_prior_state": True},
                headers=CHANGE,
            )
        )
        plan = pending_plan(client)
        client.post(
            "/ws/api/runs/approval", json={"run_id": plan["id"], "approved": True}, headers=CHANGE
        )
        record = finished_run(client)

    assert dashboard.handler.calls == [("enable", "app")]
    assert record["notes"][0]["step"] == "workflow"
    assert "default workflow" in record["notes"][0]["text"]


def test_the_graph_of_a_broken_definition_shows_the_default(dashboard, client):
    _break_the_saved_definition(dashboard)

    graph = data(client.get("/ws/api/workflow"))

    assert sorted(node["id"] for node in graph["nodes"]) == [
        "apply",
        "approval",
        "load_targets",
        "report",
        "resolve_state",
        "verify",
    ]
    view = data(client.get("/ws/api/definition"))
    assert any("'approval' is missing" in error for error in view["errors"])


# --- hosted inside another app -------------------------------------------------------------


def test_the_one_time_link_sets_the_cookie_and_sends_the_browser_home(dashboard):
    with TestClient(dashboard.app, base_url=BACKEND, follow_redirects=False) as fresh:
        redirect = fresh.get(f"/ws/?token={TOKEN}")
        again = fresh.get(f"/ws/?token={TOKEN}")

    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/"
    assert COOKIE in redirect.headers["set-cookie"]
    assert again.status_code == 401


def test_the_mounted_page_and_its_files_are_served_under_the_prefix(client):
    page = client.get("/ws/")
    script = client.get("/ws/static/app.js")

    assert page.status_code == 200
    assert 'src="static/app.js"' in page.text
    assert script.status_code == 200
    assert 'new EventSource(relative("/api/events"))' in script.text


def test_any_local_port_is_accepted_but_other_hosts_are_not(dashboard):
    for base_url, expected in (
        ("http://localhost:8000", 200),
        ("http://127.0.0.1:9123", 200),
        ("http://evil.example:8000", 403),
        ("http://localhost.evil.example", 403),
    ):
        with TestClient(dashboard.app, base_url=base_url) as test_client:
            test_client.cookies.set(COOKIE, SESSION)
            assert test_client.get("/ws/api/auth").status_code == expected, base_url


def test_changes_are_accepted_from_the_builder_page_only(client):
    def reset(origin: str | None) -> int:
        headers = {**CHANGE, **({"origin": origin} if origin else {})}
        return client.post("/ws/api/definition/reset", headers=headers).status_code

    assert reset(PAGE_ORIGIN) == 200
    assert reset(None) == 200
    assert reset("http://evil.example") == 403
    assert reset("http://localhost:3000") == 403


def test_create_app_needs_to_know_how_it_is_reached(dashboard):
    with pytest.raises(ValueError, match="port or an exposure"):
        create_app(dashboard.services, TOKEN)
