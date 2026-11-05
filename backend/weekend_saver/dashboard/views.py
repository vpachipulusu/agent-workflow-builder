"""Read-only views the dashboard shows: the workflow graph and the managed-resource table."""

import asyncio
import logging
from collections.abc import Iterable, Mapping
from typing import Any

from agent_framework import Workflow

from weekend_saver.activity import ActivityLog
from weekend_saver.arm import parse_resource_id
from weekend_saver.dashboard.serialize import short_name
from weekend_saver.errors import ActivityLogError, ConfigError, StateStoreError
from weekend_saver.executors import MAX_CONCURRENCY, describe_error
from weekend_saver.handlers import ResourceHandler
from weekend_saver.models import PowerState, ResourceSpec
from weekend_saver.planning import SKIP_TAG, SKIP_TAG_VALUE
from weekend_saver.state_store import StateStore

logger = logging.getLogger(__name__)

_STEP_LABELS = {
    "load_targets": ("Load targets", "Validate the resource list"),
    "resolve_state": ("Resolve state", "Read power state and decide what to do"),
    "approval": ("Approval", "Wait for a yes or no"),
    "apply": ("Apply", "Stop or start the resources"),
    "verify": ("Verify", "Confirm each one reached its target state"),
    "report": ("Report", "Summarise and notify"),
}


def workflow_graph(workflow: Workflow) -> dict[str, Any]:
    """Describe the graph as it was actually built, so the picture cannot drift from it."""
    order = list(workflow.executors)
    edges = [
        (edge.source_id, edge.target_id)
        for group in workflow.edge_groups
        for edge in group.edges
        if edge.source_id in workflow.executors
    ]
    return {
        "nodes": [
            {
                "id": step,
                "label": _STEP_LABELS.get(step, (step, ""))[0],
                "description": _STEP_LABELS.get(step, (step, ""))[1],
            }
            for step in order
        ],
        "edges": [
            {"from": source, "to": target, "kind": _edge_kind(order, source, target)}
            for source, target in edges
        ],
    }


def _edge_kind(order: list[str], source: str, target: str) -> str:
    step = order.index(target) - order.index(source)
    if step == 1:
        return "main"
    return "loop" if step < 0 else "skip"


async def managed_rows(
    specs: Iterable[ResourceSpec],
    handlers: Mapping[str, ResourceHandler],
    state_store: StateStore,
    activity: ActivityLog,
) -> list[dict[str, Any]]:
    """One row per managed resource with its live power state; errors stay per row."""
    recorded = _recorded_keys(state_store)
    latest = _latest_changes(activity)
    limiter = asyncio.Semaphore(MAX_CONCURRENCY)
    rows = await asyncio.gather(*(_row(spec, handlers, recorded, limiter) for spec in specs))
    return [{**row, "last_change": latest.get(row["id"].lower())} for row in rows]


def selection_rows(specs: Iterable[ResourceSpec]) -> list[dict[str, Any]]:
    """The saved selection as it is on disk, without asking Azure about anything."""
    return [_described(spec) for spec in specs]


def _described(spec: ResourceSpec) -> dict[str, Any]:
    row = {
        "id": spec.resource_id,
        "name": short_name(spec.resource_id),
        "order": spec.order,
        "type": "",
        "resource_group": "",
        "subscription_id": "",
    }
    try:
        target = parse_resource_id(spec.resource_id, spec.order)
    except ConfigError:
        return row
    return {
        **row,
        "type": target.resource_type,
        "resource_group": target.resource_group,
        "subscription_id": target.subscription_id,
    }


def _latest_changes(activity: ActivityLog) -> dict[str, dict[str, str]]:
    """What the workflow last did to each resource, keyed by lower-cased ARM ID."""
    try:
        latest = activity.latest()
    except ActivityLogError:
        logger.warning("Could not read the activity record for the dashboard", exc_info=True)
        return {}
    return {
        key: {
            "action": change.action,
            "outcome": change.outcome,
            "at": change.at,
            "detail": change.detail,
        }
        for key, change in latest.items()
    }


def _recorded_keys(state_store: StateStore) -> frozenset[str]:
    try:
        snapshot = state_store.load()
    except StateStoreError:
        logger.warning("Could not read the state file for the dashboard", exc_info=True)
        return frozenset()
    return frozenset(snapshot.disabled) if snapshot else frozenset()


async def _row(
    spec: ResourceSpec,
    handlers: Mapping[str, ResourceHandler],
    recorded: frozenset[str],
    limiter: asyncio.Semaphore,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": spec.resource_id,
        "name": short_name(spec.resource_id),
        "order": spec.order,
        "type": "",
        "resource_group": "",
        "subscription_id": "",
        "state": PowerState.UNKNOWN.value,
        "skip": False,
        "disabled_by_us": False,
        "error": "",
    }
    try:
        target = parse_resource_id(spec.resource_id, spec.order)
        handler = handlers[target.resource_type]
    except (ConfigError, KeyError):
        return {**row, "error": "not a supported resource"}
    row = {
        **row,
        "type": target.resource_type,
        "resource_group": target.resource_group,
        "subscription_id": target.subscription_id,
        "disabled_by_us": target.key in recorded,
    }
    try:
        async with limiter:
            status = await handler.get_status(target)
    except Exception as exc:
        logger.exception("Could not read the state of %s", spec.resource_id)
        return {**row, "error": describe_error(exc)}
    tags = {name.lower(): value for name, value in status.tags.items()}
    return {
        **row,
        "state": status.power_state.value,
        "skip": tags.get(SKIP_TAG, "").lower() == SKIP_TAG_VALUE,
    }
