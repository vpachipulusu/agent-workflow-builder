"""Routes for looking through Azure one level at a time, and for what the workflow did.

Listing a whole tenant takes long and shows mostly things nobody will pick, so the
resource picker asks for subscriptions, then the groups of one, then the resources of
one group. The activity routes read the record the workflow keeps of every change.
"""

import asyncio
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from weekend_saver.activity import DEFAULT_LIMIT, ActivityLog
from weekend_saver.dashboard.serialize import change_to_json
from weekend_saver.dashboard.views import selection_rows
from weekend_saver.discovery import Discovery
from weekend_saver.models import ResourceSpec

MAX_ACTIVITY_LIMIT = 200
# Longer than any real value; what a value may contain is checked where it is used
MAX_SUBSCRIPTION_CHARS = 64
MAX_GROUP_CHARS = 90
MAX_RESOURCE_ID_CHARS = 1024


def _ok(data: Any) -> JSONResponse:
    return JSONResponse({"success": True, "data": data, "error": None})


def add_resource_routes(
    app: FastAPI,
    *,
    discovery: Discovery,
    activity: ActivityLog,
    load_specs: Callable[[], tuple[ResourceSpec, ...]],
) -> None:
    @app.get("/api/discovery/subscriptions")
    async def subscriptions() -> JSONResponse:
        return _ok([asdict(summary) for summary in await discovery.subscriptions()])

    @app.get("/api/discovery/groups")
    async def groups(
        subscription: str = Query(min_length=1, max_length=MAX_SUBSCRIPTION_CHARS),
    ) -> JSONResponse:
        return _ok([asdict(summary) for summary in await discovery.groups(subscription)])

    @app.get("/api/discovery/resources")
    async def group_resources(
        subscription: str = Query(min_length=1, max_length=MAX_SUBSCRIPTION_CHARS),
        group: str = Query(min_length=1, max_length=MAX_GROUP_CHARS),
    ) -> JSONResponse:
        found = await discovery.resources(subscription, group)
        return _ok([{**asdict(resource), "tags": dict(resource.tags)} for resource in found])

    @app.get("/api/selection")
    async def selection() -> JSONResponse:
        # The saved list only: no call to Azure, so the picker opens at once
        return _ok(selection_rows(await asyncio.to_thread(load_specs)))

    @app.get("/api/activity")
    async def activity_feed(
        resource: str = Query(default="", max_length=MAX_RESOURCE_ID_CHARS),
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_ACTIVITY_LIMIT),
    ) -> JSONResponse:
        changes = await asyncio.to_thread(activity.recent, limit, resource or None)
        return _ok([change_to_json(change) for change in changes])
