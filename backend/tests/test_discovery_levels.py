"""Discovery one level at a time: subscriptions, then resource groups, then resources."""

from types import SimpleNamespace

import pytest

from tests.helpers import SUBSCRIPTION_ID, VM_TYPE, vm_id
from weekend_saver.dashboard.demo import DemoDiscovery
from weekend_saver.discovery import (
    AzureDiscovery,
    GroupSummary,
    SubscriptionSummary,
    list_group_resources,
    list_groups,
    list_subscriptions,
)
from weekend_saver.errors import ConfigError

TYPES = frozenset({VM_TYPE, "microsoft.web/sites"})
EMPTY_SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"

NAMES = [
    {"subscriptionId": SUBSCRIPTION_ID, "name": "Test Subscription"},
    {"subscriptionId": EMPTY_SUBSCRIPTION, "name": "Empty Subscription"},
]
BY_SUBSCRIPTION = [{"subscriptionId": SUBSCRIPTION_ID, "total": 7, "supported": 2}]
BY_GROUP = [
    {"resourceGroup": "rg-app", "total": 5, "supported": 2},
    {"resourceGroup": "rg-data", "total": 2, "supported": 0},
]
IN_GROUP = [
    {
        "id": vm_id("vm-a", "rg-app"),
        "name": "vm-a",
        "type": "Microsoft.Compute/virtualMachines",
        "resourceGroup": "rg-app",
        "subscriptionId": SUBSCRIPTION_ID,
        "location": "westeurope",
        "tags": None,
    },
    {
        "id": f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-app"
        "/providers/Microsoft.KeyVault/vaults/kv-a",
        "name": "kv-a",
        "type": "Microsoft.KeyVault/vaults",
        "resourceGroup": "rg-app",
        "subscriptionId": SUBSCRIPTION_ID,
        "location": "westeurope",
        "tags": {"env": "test"},
    },
]


class Graph:
    """Answers each kind of query the way Azure Resource Graph would."""

    def __init__(self) -> None:
        self.requests: list = []

    def resources(self, request):
        self.requests.append(request)
        query = request.query.lower()
        if "resourcecontainers" in query:
            rows = NAMES
        elif "by subscriptionid" in query:
            rows = BY_SUBSCRIPTION
        elif "by resourcegroup" in query:
            rows = BY_GROUP
        else:
            rows = IN_GROUP
        return SimpleNamespace(data=rows, skip_token=None)


# --- subscriptions --------------------------------------------------------------------------


def test_every_visible_subscription_is_listed_with_what_it_holds():
    found = list_subscriptions(Graph(), TYPES)

    assert found == (
        SubscriptionSummary(EMPTY_SUBSCRIPTION, "Empty Subscription", 0, 0),
        SubscriptionSummary(SUBSCRIPTION_ID, "Test Subscription", 7, 2),
    )


def test_the_count_query_names_only_the_types_that_can_be_stopped():
    graph = Graph()

    list_subscriptions(graph, TYPES)

    counting = next(r.query for r in graph.requests if "by subscriptionId" in r.query)
    assert "'microsoft.compute/virtualmachines'" in counting
    assert "'microsoft.web/sites'" in counting


def test_with_no_stoppable_types_nothing_counts_as_supported():
    graph = Graph()

    list_subscriptions(graph, frozenset())

    counting = next(r.query for r in graph.requests if "by subscriptionId" in r.query)
    assert "countif(false)" in counting


def test_a_type_name_that_could_change_the_query_is_refused():
    graph = Graph()

    with pytest.raises(ValueError, match="resource type"):
        list_subscriptions(graph, frozenset({"x') | project secret //"}))

    assert graph.requests == []


# --- resource groups ------------------------------------------------------------------------


def test_groups_are_asked_for_one_subscription_only():
    graph = Graph()

    found = list_groups(graph, SUBSCRIPTION_ID, TYPES)

    assert found == (
        GroupSummary(SUBSCRIPTION_ID, "rg-app", 5, 2),
        GroupSummary(SUBSCRIPTION_ID, "rg-data", 2, 0),
    )
    request = graph.requests[0]
    assert request.subscriptions == [SUBSCRIPTION_ID]
    # The subscription narrows the request itself; it is never written into the query
    assert SUBSCRIPTION_ID not in request.query


# --- resources of one group -----------------------------------------------------------------


def test_resources_are_asked_for_one_group_only():
    graph = Graph()

    found = list_group_resources(graph, SUBSCRIPTION_ID, "rg-app", TYPES)

    assert [(r.name, r.supported) for r in found] == [("vm-a", True), ("kv-a", False)]
    assert found[0].tags == {}
    request = graph.requests[0]
    assert request.subscriptions == [SUBSCRIPTION_ID]
    assert "resourceGroup =~ 'rg-app'" in request.query


@pytest.mark.parametrize(
    "subscription_id",
    ["", "not-a-guid", f"{SUBSCRIPTION_ID}'", f"{SUBSCRIPTION_ID} | project x", "*"],
)
def test_something_that_is_not_a_subscription_id_is_refused(subscription_id):
    graph = Graph()

    with pytest.raises(ConfigError, match="subscription"):
        list_groups(graph, subscription_id, TYPES)
    with pytest.raises(ConfigError, match="subscription"):
        list_group_resources(graph, subscription_id, "rg-app", TYPES)

    assert graph.requests == []


@pytest.mark.parametrize(
    "resource_group",
    [
        "",
        "rg' or '1'=='1",
        'rg"',
        "rg\\",
        "rg | project id",
        "rg\nResources",
        "ends-with-a-dot.",
        "x" * 91,
    ],
)
def test_something_that_is_not_a_resource_group_name_is_refused(resource_group):
    graph = Graph()

    with pytest.raises(ConfigError, match="resource group"):
        list_group_resources(graph, SUBSCRIPTION_ID, resource_group, TYPES)

    assert graph.requests == []


@pytest.mark.parametrize("resource_group", ["rg-app", "RG_App.01", "rg(test)", "grüppe-1"])
def test_every_name_azure_allows_for_a_group_is_accepted(resource_group):
    graph = Graph()

    list_group_resources(graph, SUBSCRIPTION_ID, resource_group, TYPES)

    assert f"resourceGroup =~ '{resource_group}'" in graph.requests[0].query


# --- the two implementations ----------------------------------------------------------------


async def test_azure_discovery_answers_each_level():
    discovery = AzureDiscovery(object(), TYPES, client_factory=lambda _: Graph())

    subscriptions = await discovery.subscriptions()
    groups = await discovery.groups(SUBSCRIPTION_ID)
    resources = await discovery.resources(SUBSCRIPTION_ID, "rg-app")

    assert [s.name for s in subscriptions] == ["Empty Subscription", "Test Subscription"]
    assert [g.resource_group for g in groups] == ["rg-app", "rg-data"]
    assert [r.name for r in resources] == ["vm-a", "kv-a"]


async def test_the_demo_answers_each_level_from_its_own_catalogue():
    demo = DemoDiscovery()

    subscriptions = await demo.subscriptions()
    dev = next(s for s in subscriptions if s.name == "Demo Dev/Test")
    groups = await demo.groups(dev.subscription_id)
    resources = await demo.resources(dev.subscription_id, "RG-SHOP-DEV")

    assert (dev.total, dev.supported) == (9, 7)
    assert groups == (GroupSummary(dev.subscription_id, "rg-shop-dev", 9, 7),)
    assert len(resources) == 9
    assert {r.name for r in resources if not r.supported} == {"shopdevstorage", "shop-kv-dev"}
    assert await demo.resources(dev.subscription_id, "rg-nothing-here") == ()


async def test_the_demo_refuses_the_same_input_azure_would():
    demo = DemoDiscovery()

    with pytest.raises(ConfigError):
        await demo.groups("not-a-guid")
    with pytest.raises(ConfigError):
        await demo.resources("11111111-1111-1111-1111-111111111111", "rg'")
