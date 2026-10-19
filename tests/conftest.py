from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from agent_framework import FunctionInvocationContext, FunctionTool
from agent_framework.foundry import FoundryChatOptions
from azure.cosmos.aio import ContainerProxy

from app.clients import Clients
from app.config import Settings

TENANT = "00000000-0000-0000-0000-000000000000"
URL = "https://x.invalid"
FAKE: dict[str, Any] = {
    "foundry_project_endpoint": f"{URL}/api/projects/p",
    "foundry_account_endpoint": URL,
    "search_endpoint": URL,
    "cosmos_endpoint": URL,
    "manuals_container_url": f"{URL}/manuals",
    "storage_account_resource_id": "/subscriptions/x/rg/st",
    "entra_tenant_id": TENANT,
    "api_audience": f"api://{TENANT}",
    "require_auth": True,
}


async def stream(items: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    for item in items:
        yield item


class FakeContainer:
    def __init__(
        self, items: dict[str, dict[str, Any]] | None = None, rows: list[dict[str, Any]] | None = None
    ) -> None:
        self.items, self.rows, self.patches = items or {}, rows or [], list[tuple[str, list[dict[str, Any]]]]()

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        return dict(self.items[item])

    async def replace_item(self, item: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        self.items[body["id"]] = body
        return body

    async def patch_item(self, item: str, partition_key: str, patch_operations: list[dict[str, Any]]) -> dict[str, Any]:
        self.patches.append((item, patch_operations))
        return {"id": item}

    def query_items(
        self, query: str, parameters: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        return stream(self.rows)


class FakeSearch:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows, self.calls = rows, list[dict[str, Any]]()

    async def search(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(kwargs)
        return stream(self.rows)


class FakeClients(Clients):
    def __init__(self, containers: dict[str, FakeContainer], search: FakeSearch | None = None) -> None:
        self.containers, self.search, self.options = containers, cast(Any, search), FoundryChatOptions()

    def container(self, name: str) -> ContainerProxy:
        return cast(ContainerProxy, self.containers[name])


def context(**kwargs: Any) -> FunctionInvocationContext:
    return FunctionInvocationContext(function=cast(FunctionTool, None), arguments={}, kwargs=kwargs)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, **FAKE)
