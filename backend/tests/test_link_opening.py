"""Opening the one-time link in the browser, so nobody has to copy it from the terminal."""

from __future__ import annotations

import asyncio
import webbrowser
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import weekend_saver_host
from weekend_saver_host import Hosted, is_served, open_when_served

BACKEND = "http://localhost:8000"
LINK = "http://localhost:5173/ws/?token=secret-code"


class _Page:
    """Stands in for the frontend: it answers from the given check onwards, or never."""

    def __init__(self, served_from: int | None) -> None:
        self.checks: list[tuple[str, int]] = []
        self.served_from = served_from

    async def __call__(self, host: str, port: int) -> bool:
        self.checks.append((host, port))
        return self.served_from is not None and len(self.checks) >= self.served_from


class _Browser:
    def __init__(self, opens: bool = True) -> None:
        self.opened: list[str] = []
        self.opens = opens

    def __call__(self, link: str) -> bool:
        self.opened.append(link)
        return self.opens


def hosted(tmp_path, *, open_link: bool) -> Hosted:
    return weekend_saver_host.build_hosted(
        workflows_dir=tmp_path,
        origins=("http://localhost:5173",),
        model_configured=False,
        demo=True,
        open_link=open_link,
    )


# --- waiting for the page, then opening it ------------------------------------------------


async def test_opens_the_link_as_soon_as_the_page_is_served(monkeypatch):
    page = _Page(served_from=3)
    monkeypatch.setattr(weekend_saver_host, "is_served", page)
    browser = _Browser()

    opened = await open_when_served(LINK, opener=browser, poll_seconds=0)

    assert opened is True
    assert browser.opened == [LINK]
    assert page.checks == [("localhost", 5173)] * 3


async def test_gives_up_when_the_page_never_starts(monkeypatch, caplog):
    monkeypatch.setattr(weekend_saver_host, "is_served", _Page(served_from=None))
    browser = _Browser()

    with caplog.at_level("WARNING"):
        opened = await open_when_served(LINK, opener=browser, wait_seconds=0, poll_seconds=0)

    assert opened is False
    assert browser.opened == []
    assert "http://localhost:5173 is not running" in caplog.text
    assert "secret-code" not in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        False,
        webbrowser.Error(f"cannot open {LINK}"),
        OSError(f"denied: {LINK}"),
        RuntimeError(f"unexpected: {LINK}"),
    ],
)
async def test_a_browser_that_does_not_open_is_reported_not_raised(monkeypatch, caplog, failure):
    monkeypatch.setattr(weekend_saver_host, "is_served", _Page(served_from=1))

    def opener(link: str) -> bool:
        if isinstance(failure, Exception):
            raise failure
        return failure

    with caplog.at_level("WARNING"):
        opened = await open_when_served(LINK, opener=opener, poll_seconds=0)

    assert opened is False
    assert "could not be opened" in caplog.text
    assert "secret-code" not in caplog.text


@pytest.mark.parametrize(
    ("link", "port"),
    [("http://localhost/ws/?token=x", 80), ("https://localhost/ws/?token=x", 443)],
)
async def test_a_link_without_a_port_is_checked_on_the_usual_one(monkeypatch, link, port):
    page = _Page(served_from=1)
    monkeypatch.setattr(weekend_saver_host, "is_served", page)

    await open_when_served(link, opener=_Browser(), poll_seconds=0)

    assert page.checks == [("localhost", port)]


@pytest.mark.parametrize(
    "link",
    [
        "http://localhost:99999/ws/?token=secret-code",  # no such port
        "localhost:5173/ws/?token=secret-code",  # no scheme
        "file://localhost/ws/?token=secret-code",  # not a web page
        "http://example.com/ws/?token=secret-code",  # not this computer
    ],
)
async def test_a_link_that_is_not_a_local_page_is_never_opened(monkeypatch, caplog, link):
    page = _Page(served_from=1)
    monkeypatch.setattr(weekend_saver_host, "is_served", page)
    browser = _Browser()

    with caplog.at_level("WARNING"):
        opened = await open_when_served(link, opener=browser, poll_seconds=0)

    assert opened is False
    assert browser.opened == []
    assert page.checks == []
    assert "FRONTEND_ORIGINS" in caplog.text
    assert "secret-code" not in caplog.text


async def test_is_served_tells_a_listening_port_from_a_closed_one():
    server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    listening = await is_served("127.0.0.1", port)
    server.close()
    await server.wait_closed()
    closed = await is_served("127.0.0.1", port)

    assert listening is True
    assert closed is False


# --- when the backend does it ---------------------------------------------------------------


async def test_the_running_backend_opens_its_link_when_asked_to(tmp_path, monkeypatch, capsys):
    asked: list[str] = []

    async def record(link: str) -> bool:
        asked.append(link)
        return True

    monkeypatch.setattr(weekend_saver_host, "open_when_served", record)
    app = hosted(tmp_path, open_link=True)

    async with app.running():
        await asyncio.sleep(0)

    printed = capsys.readouterr().out
    assert asked == [app.link]
    assert f"Weekend Saver: open {app.link}" in printed
    assert "opens in your browser by itself" in printed


async def test_the_running_backend_only_prints_the_link_otherwise(tmp_path, monkeypatch, capsys):
    asked: list[str] = []

    async def record(link: str) -> bool:
        asked.append(link)
        return True

    monkeypatch.setattr(weekend_saver_host, "open_when_served", record)
    app = hosted(tmp_path, open_link=False)

    async with app.running():
        await asyncio.sleep(0)

    printed = capsys.readouterr().out
    assert asked == []
    assert f"Weekend Saver: open {app.link}" in printed
    assert "by itself" not in printed


async def test_stopping_the_backend_stops_waiting_for_the_page(tmp_path, monkeypatch):
    waiting = asyncio.Event()
    cancelled: list[bool] = []

    async def wait_forever(link: str) -> bool:
        waiting.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return False

    monkeypatch.setattr(weekend_saver_host, "open_when_served", wait_forever)

    async with hosted(tmp_path, open_link=True).running():
        await waiting.wait()

    assert cancelled == [True]


async def test_a_backend_that_fails_still_stops_waiting_for_the_page(tmp_path, monkeypatch):
    waiting = asyncio.Event()
    cancelled: list[bool] = []

    async def wait_forever(link: str) -> bool:
        waiting.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return False

    monkeypatch.setattr(weekend_saver_host, "open_when_served", wait_forever)

    with pytest.raises(RuntimeError, match="backend broke"):
        async with hosted(tmp_path, open_link=True).running():
            await waiting.wait()
            raise RuntimeError("backend broke")

    assert cancelled == [True]


def test_the_link_lands_on_the_weekend_saver_page(tmp_path):
    app = hosted(tmp_path, open_link=False)
    host = FastAPI()
    host.mount(weekend_saver_host.MOUNT_PATH, app.app)

    with TestClient(host, base_url=BACKEND, follow_redirects=False) as browser:
        link = urlsplit(app.link)
        opened = browser.get(f"{link.path}?{link.query}")

    assert opened.status_code == 303
    assert opened.headers["location"] == "/weekend-saver"
