"""Weekend Saver inside the builder: mounted, protected, and out of reach of the open API."""

import time
from urllib.parse import urlsplit

import pytest
from agent_framework import BaseChatClient, ChatResponse, Message
from agent_framework.openai import OpenAIChatCompletionClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

import llm_client
import main
import orchestrator
import weekend_saver_host
from config import AZURE_OPENAI_DEPLOYMENT
from tests.test_custom_definition import summary_before_report
from weekend_saver.custom.definition import default_definition, definition_to_dict
from weekend_saver.custom.guidance import edit_guidance
from weekend_saver.dashboard.app import CHANGE_HEADER

BACKEND = "http://localhost:8000"
PAGE = {CHANGE_HEADER: "1", "origin": "http://localhost:5173"}


@pytest.fixture(scope="module")
def client():
    """The builder app with its lifespan running, signed in through the one-time link."""
    with TestClient(main.app, base_url=BACKEND, follow_redirects=False) as test_client:
        link = urlsplit(main.weekend_saver.link)
        opened = test_client.get(f"{link.path}?{link.query}")
        assert opened.status_code == 303
        yield test_client


@pytest.fixture(autouse=True)
def default_workflow():
    yield
    main.weekend_saver.definitions.reset()


def data(response):
    body = response.json()
    assert body["success"], body
    return body["data"]


def a_plain_workflow(name: str = "greeter", executor_type: str = "function") -> dict:
    return {
        "name": name,
        "description": "Says hello",
        "start": "hello",
        "executors": [{"name": "hello", "type": executor_type, "instructions": "Say hello."}],
        "edges": [],
    }


# --- what the open API may and may not do -------------------------------------------------


def test_the_workflow_is_listed_next_to_the_builders_own(client):
    names = [item["name"] for item in client.get("/api/workflows").json()["workflows"]]

    assert "weekend_saver" in names


def test_the_open_api_can_read_the_definition(client):
    definition = client.get("/api/workflows/weekend_saver").json()["definition"]

    assert definition == definition_to_dict(default_definition())


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("DELETE", "/api/workflows/weekend_saver", None),
        (
            "PUT",
            "/api/workflows/weekend_saver/edit",
            {"workflow_name": "weekend_saver", "prompt": "remove the approval step"},
        ),
        ("POST", "/api/workflows/weekend_saver/run", {"message": "go"}),
    ],
)
def test_the_open_api_cannot_change_or_run_it(client, method, path, body):
    response = client.request(method, path, json=body)

    assert response.status_code == 403
    assert "Weekend Saver" in response.json()["detail"]
    assert main.weekend_saver.definitions.load() == default_definition()


def test_the_open_api_cannot_create_a_workflow_with_the_reserved_name(client):
    response = client.post("/api/workflows", json={"definition": a_plain_workflow("weekend_saver")})

    assert response.status_code == 403
    assert main.weekend_saver.definitions.load() == default_definition()


def test_the_open_api_cannot_use_builtin_steps_under_another_name(client):
    response = client.post(
        "/api/workflows", json={"definition": a_plain_workflow("sneaky", "builtin")}
    )

    assert response.status_code == 403
    assert not (orchestrator.WORKFLOWS_DIR / "sneaky").exists()


def test_ordinary_workflows_still_work(client):
    created = client.post("/api/workflows", json={"definition": a_plain_workflow()})

    assert created.status_code == 200
    assert created.json()["validation"]["valid"] is True
    assert client.delete("/api/workflows/greeter").status_code == 200


# --- the protected app --------------------------------------------------------------------


def test_the_protected_routes_need_the_session():
    with TestClient(main.app, base_url=BACKEND) as anonymous:
        assert anonymous.get("/ws/api/definition").status_code == 401


def test_the_link_printed_at_startup_points_at_the_builder_page():
    link = urlsplit(main.weekend_saver.link)

    assert f"{link.scheme}://{link.netloc}" == "http://localhost:5173"
    assert link.path == "/ws/"
    assert link.query.startswith("token=")


def test_signed_in_the_page_sees_demo_mode(client):
    assert data(client.get("/ws/api/auth"))["demo"] is True


def test_a_dry_run_goes_through_the_real_compiled_workflow(client):
    started = data(
        client.post("/ws/api/runs", json={"action": "disable", "dry_run": True}, headers=PAGE)
    )

    deadline = time.monotonic() + 10
    record = None
    while time.monotonic() < deadline and record is None:
        runs = data(client.get("/ws/api/runs"))
        record = next((run for run in runs["recent"] if run["id"] == started["run_id"]), None)
        time.sleep(0.05)

    assert record is not None, "the dry run did not finish in time"
    assert record["status"] == "dry_run"
    assert record["results"]


# --- chat edits through the builder's model -----------------------------------------------


async def test_a_chat_edit_gives_the_builders_model_the_rules(monkeypatch):
    seen: list[tuple[str, str]] = []
    proposal = definition_to_dict(summary_before_report())

    async def fake_json(system: str, user: str) -> dict:
        seen.append((system, user))
        return proposal

    monkeypatch.setattr(orchestrator, "chat_completion_json", fake_json)
    current = definition_to_dict(default_definition())

    result = await weekend_saver_host.edit_with_chat(current, "summarize before the report")

    system, user = seen[0]
    assert result == proposal
    assert "summarize before the report" in user
    assert 'ref "weekend_saver.apply"' in system
    assert "ref: weekend_saver.apply" in system
    assert "A gate may only sit before" in system


def test_a_chat_edit_from_the_page_is_validated_and_saved(client, monkeypatch):
    async def fake_json(system: str, user: str) -> dict:
        return definition_to_dict(summary_before_report())

    monkeypatch.setattr(orchestrator, "chat_completion_json", fake_json)

    view = data(
        client.post(
            "/ws/api/definition/edit", json={"prompt": "summarize the results"}, headers=PAGE
        )
    )

    assert view["errors"] == []
    names = [
        item["name"]
        for item in client.get("/api/workflows/weekend_saver").json()["definition"]["executors"]
    ]
    assert "summary" in names


class RecordingChatClient(BaseChatClient):
    """An Agent Framework chat client that records what the agent sends it."""

    def __init__(self, answer: str) -> None:
        super().__init__()
        self._answer = answer
        self.calls: list[tuple[list[tuple[str, str]], dict]] = []

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        sent = [(str(message.role), message.text) for message in messages]
        watched = ("instructions", "temperature", "response_format", "tools")
        asked = {key: options.get(key) for key in watched}
        self.calls.append((sent, asked))
        return ChatResponse(messages=Message("assistant", [self._answer]))


async def test_ai_steps_are_agent_framework_agents():
    client = RecordingChatClient("All quiet.")
    model = weekend_saver_host.AgentModel(client)

    answer = await model.complete("Summarize.", "Run: disable.")
    await model.complete("Decide.", "Run: disable.", as_json=True)

    temperature = weekend_saver_host.STEP_TEMPERATURE
    assert answer == "All quiet."
    # The step's instructions are the agent's instructions; the run description is its
    # input; no tools, so a resource name in that description cannot make anything run
    assert client.calls == [
        (
            [("user", "Run: disable.")],
            {
                "instructions": "Summarize.",
                "temperature": temperature,
                "response_format": None,
                "tools": None,
            },
        ),
        # Gates ask for JSON, so the model cannot wrap its verdict in prose
        (
            [("user", "Run: disable.")],
            {
                "instructions": "Decide.",
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "tools": None,
            },
        ),
    ]


async def test_an_empty_answer_is_a_failure_not_a_blank_note():
    model = weekend_saver_host.AgentModel(RecordingChatClient(""))

    with pytest.raises(RuntimeError, match="no text"):
        await model.complete("Summarize.", "Run: disable.")


def test_ai_steps_run_on_the_builders_azure_openai_deployment():
    client = weekend_saver_host.step_chat_client()

    assert isinstance(client, OpenAIChatCompletionClient)
    assert client.model == AZURE_OPENAI_DEPLOYMENT
    # The same signed-in client the builder's chat uses, so one sign-in covers both
    assert client.client is llm_client.get_client()


def test_without_a_configured_model_chat_edits_and_ai_steps_are_switched_off(tmp_path):
    hosted = weekend_saver_host.build_hosted(
        workflows_dir=tmp_path,
        origins=("http://localhost:5173",),
        model_configured=False,
        demo=True,
    )

    assert hosted.services.editor is None
    # Mounted the way the builder mounts it: the session cookie is limited to that prefix
    host = FastAPI()
    host.mount(weekend_saver_host.MOUNT_PATH, hosted.app)
    with TestClient(host, base_url=BACKEND, follow_redirects=False) as test_client:
        link = urlsplit(hosted.link)
        test_client.get(f"{link.path}?{link.query}")
        response = test_client.post(
            "/ws/api/definition/edit", json={"prompt": "add a summary"}, headers=PAGE
        )

    assert response.status_code == 400
    assert "language model" in response.json()["error"]


def test_the_guidance_names_every_builtin_step_and_its_outcomes():
    guidance = edit_guidance()

    for step in ("load_targets", "resolve_state", "approval", "apply", "verify", "report"):
        assert f'ref "weekend_saver.{step}"' in guidance
    assert '"replan" -> load_targets' in guidance
    assert "require_approval (bool, default True)" in guidance
