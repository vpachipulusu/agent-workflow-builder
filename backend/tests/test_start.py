"""The backend launcher: free the port, then start the server."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import start


class _Recorder:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.returncode = returncode

    def __call__(self, command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(tuple(command))
        return subprocess.CompletedProcess(command, self.returncode)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    monkeypatch.setattr(
        start.uvicorn, "run", lambda app, **options: runs.append({"app": app, **options})
    )
    return runs


@pytest.fixture
def node(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr(start.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(start.subprocess, "run", recorder)
    return recorder


def test_frees_the_port_before_starting(node: _Recorder, served: list[dict[str, Any]]) -> None:
    start.main([])

    assert node.calls == [("/bin/node", str(start.FREE_PORT_SCRIPT), "8000")]
    assert served == [
        {
            "app": "main:app",
            "host": "127.0.0.1",
            "port": 8000,
            "reload": False,
            "app_dir": str(start.BACKEND_DIR),
        }
    ]


def test_uses_the_port_and_reload_it_is_given(
    node: _Recorder, served: list[dict[str, Any]]
) -> None:
    start.main(["--port", "8011", "--reload"])

    assert node.calls[0][-1] == "8011"
    assert served[0]["port"] == 8011
    assert served[0]["reload"] is True


def test_does_not_start_when_the_port_cannot_be_freed(
    node: _Recorder, served: list[dict[str, Any]]
) -> None:
    node.returncode = 1

    with pytest.raises(SystemExit) as stopped:
        start.main([])

    assert stopped.value.code == 1
    assert served == []


def test_starts_anyway_when_node_is_missing(
    monkeypatch: pytest.MonkeyPatch, served: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(start.shutil, "which", lambda name: None)

    with caplog.at_level("WARNING"):
        start.main([])

    assert "Node.js was not found" in caplog.text
    assert len(served) == 1


@pytest.mark.parametrize("port", ["0", "65536", "abc"])
def test_refuses_a_port_that_cannot_exist(
    port: str, node: _Recorder, served: list[dict[str, Any]]
) -> None:
    with pytest.raises(SystemExit):
        start.main(["--port", port])

    assert node.calls == []
    assert served == []


def test_points_at_the_script_the_frontend_uses() -> None:
    shared_script = Path(start.BACKEND_DIR).parent / "frontend" / "scripts" / "free-port.mjs"

    assert shared_script == start.FREE_PORT_SCRIPT
    assert start.FREE_PORT_SCRIPT.is_file()
