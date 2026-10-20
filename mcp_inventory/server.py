from typing import Any

from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.identity.aio import DefaultAzureCredential
from mcp.server.fastmcp import FastMCP

from app.config import Settings

FIND = "SELECT c.part_number, c.description, c.stock, c.unit_cost_eur FROM c WHERE c.family = @family "
FIND += "AND CONTAINS(LOWER(c.description), LOWER(@query))"
INSTRUCTIONS = "Read-only view of the spare-parts inventory; nothing here reserves or orders."
mcp = FastMCP("inventory", instructions=INSTRUCTIONS, host="0.0.0.0", port=8020)
_container: ContainerProxy | None = None


def inventory() -> ContainerProxy:
    global _container
    if _container is None:
        settings = Settings()
        client = CosmosClient(settings.cosmos_endpoint, DefaultAzureCredential())
        _container = client.get_database_client(settings.cosmos_database).get_container_client("inventory")
    return _container


@mcp.tool()
async def find_parts(family: str, query: str = "") -> list[dict[str, Any]]:
    """List catalogue parts of an asset family (pump, fan, drive, conveyor) whose description contains the query."""
    parameters: list[dict[str, object]] = [{"name": "@family", "value": family}, {"name": "@query", "value": query}]
    return [dict(item) async for item in inventory().query_items(FIND, parameters=parameters)]


@mcp.tool()
async def part_stock(part_number: str) -> dict[str, Any]:
    """Return the stock and unit cost of one catalogue part by its exact part number."""
    item = await inventory().read_item(part_number, partition_key=part_number)
    return {key: item[key] for key in ("part_number", "description", "stock", "unit_cost_eur")}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
