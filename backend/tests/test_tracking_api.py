"""The calls behind the drill-down picker and the per-resource record of changes."""

import pytest
from fastapi.testclient import TestClient

from tests.helpers import SUBSCRIPTION_ID, VM_TYPE, FakeHandler, vm_id
from tests.test_dashboard_api import (
    BASE_URL,
    CHANGE,
    COOKIE,
    SESSION,
    Dashboard,
    data,
    wait_for,
)
from weekend_saver.activity import Change
from weekend_saver.config import save_resource_specs
from weekend_saver.models import PowerState, ResourceSpec

RUNNING, STOPPED = PowerState.RUNNING, PowerState.STOPPED
FRIDAY = "2026-11-06T18:00:00+00:00"
MONDAY = "2026-11-09T06:00:00+00:00"


@pytest.fixture
def dashboard(tmp_path):
    return Dashboard(tmp_path, FakeHandler({"app": RUNNING, "db": STOPPED, "other": RUNNING}))


@pytest.fixture
def client(dashboard):
    with TestClient(dashboard.app, base_url=BASE_URL, follow_redirects=False) as test_client:
        test_client.cookies.set(COOKIE, SESSION)
        yield test_client


def signed_in(dashboard: Dashboard) -> TestClient:
    test_client = TestClient(dashboard.app, base_url=BASE_URL)
    test_client.cookies.set(COOKIE, SESSION)
    return test_client


def changed(name: str, action: str, at: str, outcome: str = "succeeded") -> Change:
    state = "stopped" if action == "disable" else "running"
    return Change(at, vm_id(name), action, outcome, f"{action}d and verified", state)


# --- looking through Azure one level at a time ----------------------------------------------


def test_subscriptions_come_with_what_they_hold(client):
    assert data(client.get("/api/discovery/subscriptions")) == [
        {"subscription_id": SUBSCRIPTION_ID, "name": "Test Sub", "total": 4, "supported": 3}
    ]


def test_the_groups_of_one_subscription_are_listed(client):
    groups = data(client.get("/api/discovery/groups", params={"subscription": SUBSCRIPTION_ID}))

    assert groups == [
        {
            "subscription_id": SUBSCRIPTION_ID,
            "resource_group": "rg-test",
            "total": 4,
            "supported": 3,
        }
    ]


def test_the_resources_of_one_group_say_which_can_be_managed(client):
    found = data(
        client.get(
            "/api/discovery/resources",
            params={"subscription": SUBSCRIPTION_ID, "group": "rg-test"},
        )
    )

    by_name = {row["name"]: row for row in found}
    assert by_name["app"]["supported"] is True
    assert by_name["app"]["resource_id"] == vm_id("app")
    assert by_name["app"]["resource_type"] == VM_TYPE
    assert by_name["my-openai"]["supported"] is False
    assert by_name["app"]["tags"] == {}


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/discovery/groups", {}),
        ("/api/discovery/resources", {"subscription": SUBSCRIPTION_ID}),
        ("/api/discovery/resources", {"group": "rg-test"}),
        ("/api/discovery/groups", {"subscription": "x" * 65}),
        ("/api/discovery/resources", {"subscription": SUBSCRIPTION_ID, "group": "x" * 91}),
    ],
)
def test_a_level_asked_for_without_saying_which_is_refused(client, path, params):
    response = client.get(path, params=params)

    assert response.status_code == 422
    assert response.json()["success"] is False


@pytest.mark.parametrize(
    ("path", "params", "problem"),
    [
        ("/api/discovery/groups", {"subscription": "not-a-guid"}, "subscription"),
        (
            "/api/discovery/resources",
            {"subscription": SUBSCRIPTION_ID, "group": "rg' or '1'=='1"},
            "resource group",
        ),
    ],
)
def test_a_subscription_or_group_that_cannot_exist_is_refused(client, path, params, problem):
    response = client.get(path, params=params)

    assert response.status_code == 400
    assert problem in response.json()["error"]


# --- the saved selection --------------------------------------------------------------------


def test_the_selection_is_empty_before_anything_is_selected(client):
    assert data(client.get("/api/selection")) == []


def test_the_selection_is_read_from_disk_without_asking_azure(tmp_path):
    handler = FakeHandler({"app": RUNNING, "db": STOPPED}, fail_status_on={"app", "db"})
    dashboard = Dashboard(tmp_path, handler)
    save_resource_specs(
        dashboard.resources_path, (ResourceSpec(vm_id("app")), ResourceSpec(vm_id("db"), 10))
    )

    with signed_in(dashboard) as test_client:
        selection = data(test_client.get("/api/selection"))

    assert selection == [
        {
            "id": vm_id("app"),
            "name": "app",
            "order": 0,
            "type": VM_TYPE,
            "resource_group": "rg-test",
            "subscription_id": SUBSCRIPTION_ID,
        },
        {
            "id": vm_id("db"),
            "name": "db",
            "order": 10,
            "type": VM_TYPE,
            "resource_group": "rg-test",
            "subscription_id": SUBSCRIPTION_ID,
        },
    ]


# --- what the workflow did ------------------------------------------------------------------


def test_nothing_has_happened_yet(client, dashboard):
    dashboard.manage("app")

    assert data(client.get("/api/activity")) == []
    assert data(client.get("/api/resources"))[0]["last_change"] is None


def test_a_run_leaves_a_trace_for_each_resource_it_changed(client, dashboard):
    dashboard.manage("app", "db")

    client.post("/api/runs", json={"action": "disable"}, headers=CHANGE)
    waiting = wait_for(client, lambda runs: runs["current"] and runs["current"]["pending_plan"])
    answer = {"run_id": waiting["current"]["id"], "approved": True}
    client.post("/api/runs/approval", json=answer, headers=CHANGE)
    wait_for(client, lambda runs: runs["current"] is None)

    activity = data(client.get("/api/activity"))
    rows = {row["name"]: row for row in data(client.get("/api/resources"))}
    assert [(c["name"], c["action"], c["outcome"], c["state"]) for c in activity] == [
        ("app", "disable", "succeeded", "stopped")
    ]
    assert activity[0]["resource_id"] == vm_id("app")
    assert rows["app"]["last_change"]["action"] == "disable"
    assert rows["app"]["last_change"]["outcome"] == "succeeded"
    assert rows["app"]["last_change"]["at"] == activity[0]["at"]
    # Already stopped, so the run left it alone
    assert rows["db"]["last_change"] is None


def test_the_last_change_is_the_newest_one(client, dashboard):
    dashboard.manage("app")
    dashboard.activity.record(
        [changed("app", "disable", FRIDAY), changed("app", "enable", MONDAY, "failed")]
    )

    last_change = data(client.get("/api/resources"))[0]["last_change"]

    assert last_change == {
        "action": "enable",
        "outcome": "failed",
        "at": MONDAY,
        "detail": "enabled and verified",
    }


def test_one_resource_can_be_followed_on_its_own(client, dashboard):
    dashboard.activity.record(
        [
            changed("app", "disable", FRIDAY),
            changed("db", "disable", FRIDAY),
            changed("app", "enable", MONDAY),
        ]
    )

    followed = data(client.get("/api/activity", params={"resource": vm_id("app")}))

    assert [(c["name"], c["action"], c["at"]) for c in followed] == [
        ("app", "enable", MONDAY),
        ("app", "disable", FRIDAY),
    ]


def test_only_as_many_changes_as_asked_for_come_back(client, dashboard):
    dashboard.activity.record([changed(f"vm-{index}", "disable", FRIDAY) for index in range(5)])

    assert len(data(client.get("/api/activity", params={"limit": 2}))) == 2
    assert len(data(client.get("/api/activity"))) == 5


@pytest.mark.parametrize("limit", ["0", "201", "many"])
def test_an_unreasonable_number_of_changes_is_refused(client, limit):
    assert client.get("/api/activity", params={"limit": limit}).status_code == 422


def test_an_unreadable_record_does_not_hide_the_resources(tmp_path):
    (tmp_path / "activity.jsonl").mkdir()
    dashboard = Dashboard(tmp_path, FakeHandler({"app": RUNNING}))
    dashboard.manage("app")

    with signed_in(dashboard) as test_client:
        rows = data(test_client.get("/api/resources"))
        activity = test_client.get("/api/activity")

    assert (rows[0]["state"], rows[0]["last_change"]) == ("running", None)
    assert activity.status_code == 500
    assert "activity record" in activity.json()["error"]


@pytest.mark.parametrize(
    "path",
    ["/api/discovery/subscriptions", "/api/selection", "/api/activity"],
)
def test_these_calls_need_the_session_too(dashboard, path):
    with TestClient(dashboard.app, base_url=BASE_URL) as anonymous:
        assert anonymous.get(path).status_code == 401
