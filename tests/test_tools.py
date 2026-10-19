import inspect
from typing import Any

import pytest

from app.config import Settings
from app.models import PartLine, WorkOrderDraft
from app.tools import EVIDENCE_END, EVIDENCE_START, FieldTools
from mcp_inventory import server
from tests.conftest import FAKE, FakeClients, FakeContainer, FakeSearch, context

PASSAGE = {
    "manual": "doe-pump-sourcebook",
    "section_label": "Basic Pump Maintenance > Predictive Maintenance",
    "content": "Vibration analysis...",
}
ASSET = {
    "id": "P-101",
    "asset_id": "P-101",
    "family": "pump",
    "equipment_model": "CP-350",
    "location": "Bay 2",
    "commissioned": "2019-03-15",
}
CASE = {
    "fault": "P-101 (CP-350): high vibration",
    "root_cause": "bearing wear",
    "resolution": "Replaced bearing set",
    "resolved_at": "2025-06-01",
}


def tools(
    search_rows: list[dict[str, Any]] | None = None, stock: int = 3
) -> tuple[FieldTools, FakeClients, FakeSearch]:
    containers = {
        "assets": FakeContainer({"P-101": ASSET}),
        "memory": FakeContainer(rows=[CASE]),
        "interventions": FakeContainer({"abc": {"id": "abc"}}),
        "inventory": FakeContainer({"P-1010": {"id": "P-1010", "part_number": "P-1010", "stock": stock}}),
    }
    search = FakeSearch(search_rows or [])
    clients = FakeClients(containers, search)
    return FieldTools(clients, Settings(_env_file=None, **FAKE)), clients, search


async def test_search_manual_wraps_passages_as_untrusted_evidence_and_filters_by_family() -> None:
    field, _, search = tools([PASSAGE])
    text = await field.search_manual.invoke(arguments={"query": "pump vibration", "family": "pump"}, skip_parsing=True)
    assert str(text).startswith(EVIDENCE_START) and str(text).rstrip().endswith(EVIDENCE_END)
    assert "[Basic Pump Maintenance > Predictive Maintenance] (doe-pump-sourcebook)" in str(text)
    assert search.calls[0]["filter"] == "family eq 'pump'" and search.calls[0]["top"] == 6
    empty = await tools([])[0].search_manual.invoke(arguments={"query": "x"}, skip_parsing=True)
    assert "No passage found" in str(empty)


async def test_asset_history_reads_the_registry_and_the_resolved_cases() -> None:
    field, _, _ = tools()
    text = str(await field.asset_history.invoke(arguments={"asset_id": "P-101"}, skip_parsing=True))
    assert text.startswith("Asset P-101: pump CP-350, Bay 2") and "bearing wear" in text


async def test_write_tools_require_approval_and_touch_cosmos_only_through_the_intervention() -> None:
    field, clients, _ = tools(stock=3)
    assert (
        field.reserve_parts.approval_mode == "always_require"
        and field.create_work_order.approval_mode == "always_require"
    )
    lines = [PartLine(part_number="P-1010", quantity=2)]
    ctx = context(intervention_id="abc")
    text = str(await field.reserve_parts.invoke(arguments={"lines": lines}, context=ctx, skip_parsing=True))
    assert text.startswith("Reservation abc-") and clients.containers["inventory"].items["P-1010"]["stock"] == 1
    refused = str(await field.reserve_parts.invoke(arguments={"lines": lines}, context=ctx, skip_parsing=True))
    assert refused.startswith("Reservation refused") and clients.containers["inventory"].items["P-1010"]["stock"] == 1
    draft = WorkOrderDraft(
        asset_id="P-101", title="Pump P-101 vibration", diagnosis="bearing wear", procedure_refs=["A > B"]
    )
    text = str(await field.create_work_order.invoke(arguments={"draft": draft}, context=ctx, skip_parsing=True))
    ((item, operations),) = clients.containers["interventions"].patches
    assert text.startswith("Work order WO-") and item == "abc" and operations[0]["value"]["procedure_refs"] == ["A > B"]


async def test_inventory_server_exposes_read_only_tools() -> None:
    assert sorted(t.name for t in await server.mcp.list_tools()) == ["find_parts", "part_stock"]
    source = inspect.getsource(server)
    assert not any(
        verb in source for verb in ("upsert_item", "create_item", "replace_item", "patch_item", "delete_item")
    )


@pytest.mark.parametrize("quantity", [0, -3])
def test_part_line_bounds(quantity: int) -> None:
    with pytest.raises(ValueError):
        PartLine(part_number="P-1010", quantity=quantity)
