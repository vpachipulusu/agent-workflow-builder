"""Host the weekend-saver workflow inside the builder.

The builder's own endpoints only write files and simulate runs. This workflow really
stops and starts Azure resources as the signed-in person, so it is served by its own
protected app, mounted under /ws: reached through a one-time link, guarded by a
session cookie, and changed only from the builder's page.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import sys
import time
import webbrowser
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
# Where the one-time link sends the browser: the builder's Weekend Saver page
HOME_PAGE = "/weekend-saver"
# Lower than the builder's default: a note or a stop decision should not be inventive
STEP_TEMPERATURE = 0.2
# The frontend is usually started after the backend, so the browser waits for it
PAGE_WAIT_SECONDS = 600.0
PAGE_POLL_SECONDS = 1.0
CONNECT_TIMEOUT_SECONDS = 1.0
DEFAULT_PORTS = {"http": 80, "https": 443}


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


async def is_served(host: str, port: int) -> bool:
    """Whether something accepts connections on that port."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT_SECONDS
        )
    except (OSError, TimeoutError):
        return False
    writer.close()
    with suppress(OSError):
        await writer.wait_closed()
    return True


@dataclass(frozen=True)
class _Page:
    origin: str
    host: str
    port: int


def _local_page(link: str) -> _Page | None:
    """The page a link points at, when that is a web page on this computer.

    The link is built from FRONTEND_ORIGINS, so a mistake there ends here instead of
    being handed to the operating system to open.
    """
    target = urlsplit(link)
    try:
        port = target.port or DEFAULT_PORTS.get(target.scheme)
    except ValueError:  # a port that cannot exist
        return None
    if port is None or target.scheme not in DEFAULT_PORTS or target.hostname not in LOCAL_HOSTS:
        return None
    return _Page(f"{target.scheme}://{target.netloc}", target.hostname, port)


async def open_when_served(
    link: str,
    *,
    opener: Callable[[str], bool] = webbrowser.open,
    wait_seconds: float = PAGE_WAIT_SECONDS,
    poll_seconds: float = PAGE_POLL_SECONDS,
) -> bool:
    """Open the one-time link in the browser once the page it points at is running.

    The link goes through the frontend: opened before that has started, it would only
    show a connection error. The link itself is kept out of the log.
    """
    page = _local_page(link)
    if page is None:
        logger.warning(
            "Weekend Saver was not opened in the browser: the first entry of "
            "FRONTEND_ORIGINS is not a web page on this computer."
        )
        return False
    deadline = time.monotonic() + wait_seconds
    # Waiting first also gives this backend, started a moment ago, time to listen
    await asyncio.sleep(poll_seconds)
    while not await is_served(page.host, page.port):
        if time.monotonic() >= deadline:
            logger.warning(
                "Weekend Saver: %s is not running, so nothing was opened. "
                "Start the frontend, then open the link printed above.",
                page.origin,
            )
            return False
        await asyncio.sleep(poll_seconds)
    try:
        opened = await asyncio.to_thread(opener, link)
        reason = "no browser was found"
    except Exception as error:  # a convenience: no browser problem may stop the backend
        opened = False
        reason = type(error).__name__  # its text can repeat the link
    if not opened:
        logger.warning(
            "Weekend Saver could not be opened in the browser (%s). "
            "Open the link printed above yourself.",
            reason,
        )
    return bool(opened)


@dataclass(frozen=True)
class Hosted:
    app: FastAPI
    services: DashboardServices
    definitions: DefinitionStore
    link: str
    open_link: bool = False

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """Enter from the builder's lifespan: mounted apps do not get one of their own."""
        # Written here, not at import, so importing the builder never touches the disk
        self.definitions.ensure()
        by_itself = (
            "it opens in your browser by itself once the frontend is running; "
            if self.open_link
            else ""
        )
        sys.stdout.write(
            f"Weekend Saver: open {self.link}\n"
            f"({by_itself}the link works once and unlocks the Weekend Saver controls; "
            "restart the backend for a new one)\n"
        )
        sys.stdout.flush()
        opening = asyncio.create_task(open_when_served(self.link)) if self.open_link else None
        try:
            async with background(self.services):
                yield
        finally:
            if opening is not None:
                opening.cancel()
                with suppress(asyncio.CancelledError):
                    await opening


def build_hosted(
    *,
    workflows_dir: Path,
    origins: tuple[str, ...],
    model_configured: bool,
    demo: bool = False,
    data_dir: Path | None = None,
    open_link: bool = False,
) -> Hosted:
    """Build the protected app. `origins` are the pages the builder is served from.

    With `open_link` the running backend opens the one-time link in the browser itself.

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
        home_url=HOME_PAGE,
        cookie_path=MOUNT_PATH,
    )
    app = create_app(services, token, exposure=exposure)
    link = f"{origins[0]}{MOUNT_PATH}/?token={token}"
    return Hosted(app, services, definitions, link, open_link)
