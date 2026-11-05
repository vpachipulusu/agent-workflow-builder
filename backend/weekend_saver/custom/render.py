"""Describe a workflow message in plain text for an AI step.

The model gets resource names, types, states and decisions. It does not get
subscription IDs or tags: names are enough to reason about a run, and anything sent
here leaves the machine.
"""

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from weekend_saver.dashboard.serialize import short_name
from weekend_saver.models import (
    ActionPlan,
    ActionResult,
    AppliedPlan,
    ApprovedPlan,
    RunReport,
    RunRequest,
    ValidatedRequest,
)

MAX_LINES = 200
_SUBSCRIPTION = re.compile(r"/subscriptions/[^/\s]+", re.IGNORECASE)
# Error text can quote a mistyped resource ID, which the pattern above misses
_GUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


def request_of(message: Any) -> RunRequest | None:
    """The request a message belongs to; None once the run has passed the plan stage."""
    if isinstance(message, RunRequest):
        return message
    if isinstance(message, ValidatedRequest | ActionPlan):
        return message.request
    if isinstance(message, ApprovedPlan):
        return message.plan.request
    return None


def plan_of(message: Any) -> ActionPlan | None:
    if isinstance(message, ActionPlan):
        return message
    if isinstance(message, ApprovedPlan):
        return message.plan
    return None


def render_message(message: Any, now: datetime) -> str:
    lines = [f"Today is {now:%A %Y-%m-%d}.", *_describe(message)]
    text = _SUBSCRIPTION.sub("/subscriptions/(hidden)", "\n".join(lines))
    return _GUID.sub("(hidden id)", text)


def _describe(message: Any) -> list[str]:
    plan = plan_of(message)
    if plan is not None:
        approved = " (approved)" if isinstance(message, ApprovedPlan) else ""
        return [
            _run_line(plan.request),
            f"Plan{approved}: {len(plan.actionable)} of {len(plan.items)} resources "
            "will be changed.",
            *_capped(
                f"- {item.target.name} ({_kind(item.target.resource_type)}): "
                f"{item.current_state.value}, {item.decision.value}, {item.reason}"
                for item in plan.items
            ),
        ]
    if isinstance(message, RunRequest):
        return [
            _run_line(message),
            f"Resources requested ({len(message.resources)}):",
            *_capped(f"- {short_name(spec.resource_id)}" for spec in message.resources),
        ]
    if isinstance(message, ValidatedRequest):
        return [
            _run_line(message.request),
            f"Resources ({len(message.targets)}):",
            *_capped(
                f"- {target.name} ({_kind(target.resource_type)})" for target in message.targets
            ),
        ]
    if isinstance(message, AppliedPlan):
        return [
            f"Run: {message.action.value}. The changes have been made:",
            *_result_lines(message.results),
        ]
    if isinstance(message, RunReport):
        error = [f"Error: {message.error}"] if message.error else []
        return [
            f"Run: {message.action.value}. Status: {message.status.value}.",
            *error,
            *_result_lines(message.results),
        ]
    return [f"A message of type {type(message).__name__}."]


def _run_line(request: RunRequest) -> str:
    flags = [
        label
        for flag, label in (
            (request.dry_run, "dry run"),
            (request.auto_approve, "pre-approved"),
        )
        if flag
    ]
    suffix = f" ({', '.join(flags)})" if flags else ""
    return f"Run: {request.action.value}{suffix}."


def _result_lines(results: Iterable[ActionResult]) -> list[str]:
    return _capped(
        f"- {short_name(result.resource_id)}: {result.outcome.value}, {result.detail} "
        f"(now {result.state.value})"
        for result in results
    )


def _kind(resource_type: str) -> str:
    return resource_type.rsplit("/", 1)[-1]


def _capped(lines: Iterable[str]) -> list[str]:
    lines = list(lines)
    if len(lines) <= MAX_LINES:
        return lines
    return [*lines[:MAX_LINES], f"... and {len(lines) - MAX_LINES} more"]
