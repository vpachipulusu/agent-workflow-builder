"""Start the backend, first stopping whatever already serves its port.

    python start.py [--port 8000] [--host 127.0.0.1] [--reload]

On Windows two servers can bind one port and the older one keeps answering, so a
forgotten server makes a fresh start look broken instead of failing to start.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parent
# Shared with the frontend, whose `npm run dev` frees its own port the same way
FREE_PORT_SCRIPT = BACKEND_DIR.parent / "frontend" / "scripts" / "free-port.mjs"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_PORT = 65535

logger = logging.getLogger("start")


def _port(text: str) -> int:
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= MAX_PORT:
        raise argparse.ArgumentTypeError(f"not a port number: {text}")
    return int(text)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the backend on a port that is really free.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT)
    parser.add_argument(
        "--reload", action="store_true", help="restart on code changes (not for Weekend Saver)"
    )
    return parser.parse_args(argv)


def free_port(port: int) -> None:
    """Stop whatever serves the port. Exits when it is in use and cannot be freed."""
    node = shutil.which("node")
    if node is None:
        logger.warning(
            "Node.js was not found, so port %s was not checked for an older server.", port
        )
        return
    freed = subprocess.run([node, str(FREE_PORT_SCRIPT), str(port)], check=False)
    if freed.returncode != 0:
        raise SystemExit(1)  # the script has already said why


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _arguments(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    free_port(arguments.port)
    uvicorn.run(
        "main:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        app_dir=str(BACKEND_DIR),
    )


if __name__ == "__main__":
    main()
