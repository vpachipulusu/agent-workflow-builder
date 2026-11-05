"""Host the weekend-saver workflow inside the builder.

The builder's own endpoints only write files and simulate runs. This workflow really
stops and starts Azure resources as the signed-in person, so it is served by its own
protected app, mounted under /ws: reached through a one-time link, guarded by a
session cookie, and changed only from the builder's page.
"""

from __future__ import annotations

import logging
import secrets
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import Receive, Scope, Send

from llm_client import chat_completion
from orchestrator import request_workflow_edit
from weekend_saver.cli import notifier_from_environment
from weekend_saver.custom.definition import DEFINITION_NAME
from weekend_saver.custom.guidance import edit_guidance
from weekend_saver.custom.store import DefinitionStore
from weekend_saver.dashboard.app import DashboardServices, Exposure, background, create_app
from weekend_saver.dashboard.server import build_services
from weekend_saver.files import default_data_dir

logger = logging.getLogger(__name__)

MOUNT_PATH = "/ws"
COOKIE_NAME = "weekend_saver_session_builder"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
# Lower than the builder's default: a note or a stop decision should not be inventive
STEP_TEMPERATURE = 0.2


class OpenApiCors(CORSMiddleware):
    """CORS for the builder's open API, leaving the protected app out of it.

    Middleware on the builder also wraps what is mounted in it. With CORS applied, any
    other site on an allowed localhost origin could read the protected app's answers
    using the session cookie, which browsers send regardless of port.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if path == MOUNT_PATH or path.startswith(f"{MOUNT_PATH}/"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


class BuilderModel:
    """Answers the workflow's AI steps with the builder's Azure OpenAI deployment."""

    async def complete(self, system: str, user: str, *, as_json: bool = False) -> str:
        return await chat_completion(
            system,
            user,
            temperature=STEP_TEMPERATURE,
            response_format={"type": "json_object"} if as_json else None,
        )


async def edit_with_chat(current: dict[str, Any], prompt: str) -> dict[str, Any]:
    """Ask the builder's workflow designer for an edited definition."""
    current_yaml = yaml.safe_dump(current, sort_keys=False, allow_unicode=True)
    return await request_workflow_edit(current_yaml, prompt, guidance=edit_guidance())


@dataclass(frozen=True)
class Hosted:
    app: FastAPI
    services: DashboardServices
    definitions: DefinitionStore
    link: str

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """Enter from the builder's lifespan: mounted apps do not get one of their own."""
        # Written here, not at import, so importing the builder never touches the disk
        self.definitions.ensure()
        sys.stdout.write(
            f"Weekend Saver: open {self.link}\n"
            "(the link works once and unlocks the Weekend Saver controls; "
            "restart the backend for a new one)\n"
        )
        sys.stdout.flush()
        async with background(self.services):
            yield


def build_hosted(
    *,
    workflows_dir: Path,
    origins: tuple[str, ...],
    model_configured: bool,
    demo: bool = False,
    data_dir: Path | None = None,
) -> Hosted:
    """Build the protected app. `origins` are the pages the builder is served from.

    Without a configured model, AI steps and chat edits say so at once instead of
    waiting on a client that has nowhere to connect to.
    """
    definitions = DefinitionStore(workflows_dir / DEFINITION_NAME / "workflow.yaml")
    services = build_services(
        data_dir=data_dir or default_data_dir(),
        demo=demo,
        notifier=notifier_from_environment(),
        definitions=definitions,
        model=BuilderModel() if model_configured else None,
        editor=edit_with_chat if model_configured else None,
    )
    token = secrets.token_urlsafe(32)
    exposure = Exposure(
        cookie_name=COOKIE_NAME,
        hosts=LOCAL_HOSTS,
        origins=frozenset(origin.lower() for origin in origins),
        home_url="/",
        cookie_path=MOUNT_PATH,
    )
    app = create_app(services, token, exposure=exposure)
    return Hosted(app, services, definitions, f"{origins[0]}{MOUNT_PATH}/?token={token}")
