from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from agent_framework import FunctionInvocationContext, FunctionTool
from agent_framework.foundry import FoundryChatOptions
from azure.core.credentials import AzureKeyCredential
from azure.cosmos.aio import ContainerProxy
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from app.clients import Clients
from app.config import Settings

TENANT = "00000000-0000-0000-0000-000000000000"
URL = "https://x.invalid"
FAKE: dict[str, Any] = {"foundry_project_endpoint": f"{URL}/api/projects/p", "foundry_account_endpoint": URL}
FAKE |= {"search_endpoint": URL, "cosmos_endpoint": URL, "manuals_container_url": f"{URL}/manuals"}
FAKE |= {"storage_account_resource_id": "/subscriptions/x/rg/st", "entra_tenant_id": TENANT, "require_auth": True}
FAKE |= {"api_audience": f"api://{TENANT}"}
Row = dict[str, Any]


async def stream(items: list[Row]) -> AsyncIterator[Row]:
    for item in items:
        yield item


class FakeContainer:
    def __init__(self, items: dict[str, Row] | None = None, rows: list[Row] | None = None) -> None:
        self.items, self.rows, self.created = items or {}, rows or [], list[Row]()
        self.patches = list[tuple[str, list[Row]]]()

    async def read_item(self, item: str, partition_key: str) -> Row:
        if item not in self.items:
            raise CosmosResourceNotFoundError(message=f"{item} not found")  # type: ignore[no-untyped-call]
        return dict(self.items[item])

    async def create_item(self, body: Row) -> Row:
        self.created.append(body)
        return body

    async def replace_item(self, item: Row, body: Row) -> Row:
        self.items[body["id"]] = body
        return body

    async def patch_item(self, item: str, partition_key: str, patch_operations: list[Row]) -> Row:
        self.patches.append((item, patch_operations))
        return {"id": item}

    def query_items(self, query: str, parameters: list[Row] | None = None, **kwargs: Any) -> AsyncIterator[Row]:
        return stream(self.rows)


class FakeSearch:
    def __init__(self, rows: list[Row]) -> None:
        self.rows, self.calls = rows, list[Row]()

    async def search(self, **kwargs: Any) -> AsyncIterator[Row]:
        self.calls.append(kwargs)
        return stream(self.rows)


class FakeEmbeddings:
    async def get_embeddings(self, values: list[str]) -> list[Any]:
        return [SimpleNamespace(vector=[0.1] * 1536) for _ in values]


class FakeClients(Clients):
    def __init__(self, containers: dict[str, FakeContainer], search: FakeSearch | None = None) -> None:
        self.containers, self.search, self.options = containers, cast(Any, search), FoundryChatOptions()
        self.embeddings, self.credential = cast(Any, FakeEmbeddings()), cast(Any, AzureKeyCredential("test"))
        self.chat = self.small_chat = cast(Any, None)

    def container(self, name: str) -> ContainerProxy:
        return cast(ContainerProxy, self.containers[name])


def context(**kwargs: Any) -> FunctionInvocationContext:
    return FunctionInvocationContext(function=cast(FunctionTool, None), arguments={}, kwargs=kwargs)


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, **FAKE)
