"""Keep a record of what the workflow switched off and on.

The state file only knows what is switched off right now. This record keeps every
change, so each resource has a history: when it was disabled, when it came back, and
what failed. One JSON object per line in activity.jsonl:
    {"at", "resource_id", "action", "outcome", "detail", "state"}
"""

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Protocol

from weekend_saver.errors import ActivityLogError

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 50
# Kept in the same folder as the state file
ACTIVITY_FILE = "activity.jsonl"
# Roughly ten thousand changes; what is older than that stays in the file, unread
MAX_READ_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Change:
    """One attempt to switch one resource off or on."""

    at: str  # ISO-8601 time the run confirmed it
    resource_id: str
    action: str  # "disable" or "enable"
    outcome: str  # "succeeded" or "failed"
    detail: str
    state: str  # the power state the resource was left in

    @property
    def key(self) -> str:
        return self.resource_id.lower()

    @property
    def name(self) -> str:
        return self.resource_id.rstrip("/").rsplit("/", 1)[-1]


_FIELDS = tuple(field.name for field in fields(Change))


class ActivityLog(Protocol):
    def record(self, changes: Iterable[Change]) -> None: ...

    def recent(
        self, limit: int = DEFAULT_LIMIT, resource_id: str | None = None
    ) -> tuple[Change, ...]:
        """The newest changes first, of every resource or of one."""
        ...

    def latest(self) -> dict[str, Change]:
        """The last change of each resource, keyed by lower-cased ARM ID."""
        ...


class JsonlActivityLog:
    def __init__(self, path: Path, max_read_bytes: int = MAX_READ_BYTES) -> None:
        self._path = path
        self._max_read_bytes = max_read_bytes

    def record(self, changes: Iterable[Change]) -> None:
        lines = [json.dumps(asdict(change)) + "\n" for change in changes]
        if not lines:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.writelines(lines)
        except OSError as exc:
            raise ActivityLogError(
                f"Could not write the activity record {self._path}: {exc}"
            ) from exc

    def recent(
        self, limit: int = DEFAULT_LIMIT, resource_id: str | None = None
    ) -> tuple[Change, ...]:
        wanted = resource_id.lower() if resource_id else None
        newest_first = (change for change in reversed(self._read()) if wanted in (None, change.key))
        return tuple(change for _, change in zip(range(limit), newest_first, strict=False))

    def latest(self) -> dict[str, Change]:
        # Later lines replace earlier ones
        return {change.key: change for change in self._read()}

    def _read(self) -> list[Change]:
        """The readable changes, oldest first. A damaged line is skipped, not fatal.

        Only the newest part of a very long record is read, so a call costs the same
        however long the record has been kept.
        """
        try:
            with self._path.open("rb") as handle:
                start = max(0, handle.seek(0, os.SEEK_END) - self._max_read_bytes)
                handle.seek(start)
                lines = handle.read().decode("utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise ActivityLogError(
                f"Could not read the activity record {self._path}: {exc}"
            ) from exc
        if start > 0:
            lines = lines[1:]  # the cut landed inside this one
        changes = [self._parsed(line) for line in lines]
        return [change for change in changes if change is not None]

    def _parsed(self, line: str) -> Change | None:
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            document = None
        if not isinstance(document, dict) or not all(
            isinstance(document.get(name), str) for name in _FIELDS
        ):
            logger.warning("Skipping an unreadable line in %s", self._path)
            return None
        return Change(**{name: document[name] for name in _FIELDS})
