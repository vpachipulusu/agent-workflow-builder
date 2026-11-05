"""Find the resources the signed-in account can see, via Azure Resource Graph.

Either everything at once (`list`), or one level at a time: subscriptions, then the
resource groups of one subscription, then the resources of one group. A large tenant
takes long to list in full, and most of it is never looked at.
"""

import asyncio
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from azure.core.credentials import TokenCredential
from azure.mgmt.resourcegraph import ResourceGraphClient
from azure.mgmt.resourcegraph.models import QueryRequest, QueryRequestOptions

from weekend_saver.errors import ConfigError

PAGE_SIZE = 1000
MAX_PAGES = 50

# Resource Graph queries take no parameters, so what goes into one is checked first.
# None of these patterns lets a quote, a backslash, a pipe or a line break through.
_SUBSCRIPTION_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)
_RESOURCE_GROUP = re.compile(r"[-\w.()]{1,90}(?<!\.)")
_RESOURCE_TYPE = re.compile(r"[a-z0-9.]+/[a-z0-9]+")

# Everything is listed, not only what weekend-saver can stop, so the picker can show why
# a resource someone expects to see is not selectable.
RESOURCES_QUERY = (
    "Resources "
    "| project id, name, type, resourceGroup, subscriptionId, location, tags "
    "| order by subscriptionId asc, resourceGroup asc, name asc"
)
_SUBSCRIPTIONS_QUERY = (
    "ResourceContainers "
    "| where type =~ 'microsoft.resources/subscriptions' "
    "| project subscriptionId, name"
)


@dataclass(frozen=True)
class DiscoveredResource:
    resource_id: str
    name: str
    resource_type: str
    resource_group: str
    subscription_id: str
    subscription_name: str
    location: str
    tags: Mapping[str, str] = field(default_factory=dict)
    # False for types weekend-saver has no way to stop and start
    supported: bool = True


@dataclass(frozen=True)
class SubscriptionSummary:
    subscription_id: str
    name: str
    total: int
    # How many of them weekend-saver can stop and start
    supported: int


@dataclass(frozen=True)
class GroupSummary:
    subscription_id: str
    resource_group: str
    total: int
    supported: int


class Discovery(Protocol):
    async def list(self) -> tuple[DiscoveredResource, ...]: ...

    async def subscriptions(self) -> tuple[SubscriptionSummary, ...]: ...

    async def groups(self, subscription_id: str) -> tuple[GroupSummary, ...]: ...

    async def resources(
        self, subscription_id: str, resource_group: str
    ) -> tuple[DiscoveredResource, ...]: ...


def checked_subscription_id(subscription_id: str) -> str:
    if not _SUBSCRIPTION_ID.fullmatch(subscription_id):
        raise ConfigError("That is not a subscription ID.")
    return subscription_id.lower()


def checked_resource_group(resource_group: str) -> str:
    if not _RESOURCE_GROUP.fullmatch(resource_group):
        raise ConfigError("That is not a resource group name.")
    return resource_group


def _counts(supported_types: Collection[str]) -> str:
    """The `summarize` columns: everything, and what weekend-saver can stop."""
    unusable = sorted(name for name in supported_types if not _RESOURCE_TYPE.fullmatch(name))
    if unusable:
        raise ValueError(f"Not a resource type: {unusable[0]!r}")
    listed = ", ".join(f"'{name}'" for name in sorted(supported_types))
    stoppable = f"type in~ ({listed})" if listed else "false"
    return f"total = count(), supported = countif({stoppable})"


def list_subscriptions(
    client: Any, supported_types: Collection[str]
) -> tuple[SubscriptionSummary, ...]:
    """Every subscription the credential can see, with how much it holds."""
    query = f"Resources | summarize {_counts(supported_types)} by subscriptionId"
    held = {row["subscriptionId"]: row for row in _query_all(client, query)}
    summaries = (
        SubscriptionSummary(
            subscription_id=row["subscriptionId"],
            name=row["name"],
            total=int(held.get(row["subscriptionId"], {}).get("total", 0)),
            supported=int(held.get(row["subscriptionId"], {}).get("supported", 0)),
        )
        for row in _query_all(client, _SUBSCRIPTIONS_QUERY)
    )
    return tuple(sorted(summaries, key=lambda summary: summary.name.lower()))


def list_groups(
    client: Any, subscription_id: str, supported_types: Collection[str]
) -> tuple[GroupSummary, ...]:
    """The resource groups of one subscription that hold anything."""
    subscription_id = checked_subscription_id(subscription_id)
    query = (
        f"Resources | summarize {_counts(supported_types)} by resourceGroup "
        "| order by resourceGroup asc"
    )
    return tuple(
        GroupSummary(
            subscription_id, row["resourceGroup"], int(row["total"]), int(row["supported"])
        )
        for row in _query_all(client, query, subscription_id)
    )


def list_group_resources(
    client: Any, subscription_id: str, resource_group: str, supported_types: Collection[str]
) -> tuple[DiscoveredResource, ...]:
    """The resources of one resource group."""
    subscription_id = checked_subscription_id(subscription_id)
    query = (
        f"Resources | where resourceGroup =~ '{checked_resource_group(resource_group)}' "
        "| project id, name, type, resourceGroup, subscriptionId, location, tags "
        "| order by name asc"
    )
    return tuple(
        _to_resource(row, {}, supported_types) for row in _query_all(client, query, subscription_id)
    )


def discover_resources(
    client: Any, supported_types: Collection[str]
) -> tuple[DiscoveredResource, ...]:
    """Query every subscription the credential can see (no subscription list needed)."""
    rows = _query_all(client, RESOURCES_QUERY)
    subscription_names = {
        row["subscriptionId"]: row["name"] for row in _query_all(client, _SUBSCRIPTIONS_QUERY)
    }
    return tuple(_to_resource(row, subscription_names, supported_types) for row in rows)


def _query_all(client: Any, query: str, subscription_id: str | None = None) -> list[dict[str, Any]]:
    """Run a query to its last page, across the tenant or inside one subscription."""
    subscriptions = [subscription_id] if subscription_id else None
    rows: list[dict[str, Any]] = []
    skip_token: str | None = None
    for _ in range(MAX_PAGES):
        options = QueryRequestOptions(
            skip_token=skip_token, top=PAGE_SIZE, result_format="objectArray"
        )
        response = client.resources(
            QueryRequest(query=query, options=options, subscriptions=subscriptions)
        )
        rows.extend(response.data)
        skip_token = response.skip_token
        if not skip_token:
            return rows
    raise RuntimeError(f"Azure Resource Graph paging did not finish within {MAX_PAGES} pages")


def _to_resource(
    row: Mapping[str, Any],
    subscription_names: Mapping[str, str],
    supported_types: Collection[str],
) -> DiscoveredResource:
    subscription_id = row["subscriptionId"]
    resource_type = str(row["type"]).lower()
    return DiscoveredResource(
        resource_id=row["id"],
        name=row["name"],
        resource_type=resource_type,
        resource_group=row["resourceGroup"],
        subscription_id=subscription_id,
        subscription_name=subscription_names.get(subscription_id, subscription_id),
        location=row.get("location") or "",
        tags=dict(row.get("tags") or {}),
        supported=resource_type in supported_types,
    )


class AzureDiscovery:
    def __init__(
        self,
        credential: TokenCredential,
        supported_types: Collection[str],
        *,
        client_factory: Callable[[TokenCredential], Any] = ResourceGraphClient,
    ) -> None:
        self._client = client_factory(credential)
        self._supported_types = supported_types

    async def list(self) -> tuple[DiscoveredResource, ...]:
        return await asyncio.to_thread(discover_resources, self._client, self._supported_types)

    async def subscriptions(self) -> tuple[SubscriptionSummary, ...]:
        return await asyncio.to_thread(list_subscriptions, self._client, self._supported_types)

    async def groups(self, subscription_id: str) -> tuple[GroupSummary, ...]:
        return await asyncio.to_thread(
            list_groups, self._client, subscription_id, self._supported_types
        )

    async def resources(
        self, subscription_id: str, resource_group: str
    ) -> tuple[DiscoveredResource, ...]:
        return await asyncio.to_thread(
            list_group_resources,
            self._client,
            subscription_id,
            resource_group,
            self._supported_types,
        )
