import inspect
from typing import Any, cast

from agent_framework import AgentSession, Message, SessionContext, SupportsAgentRun
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.testclient import TestClient

from a2a_server import main as a2a
from app import middleware as middleware_module
from app.agents import NAMES, build_agents
from app.config import Settings
from app.memory import CASES_END, CASES_START, SimilarCasesProvider
from app.middleware import AuditMiddleware, PolicyMiddleware
from app.tools import FieldTools
from tests.conftest import FakeClients, FakeContainer, context
from tests.test_main import JWKS, bearer

CASE: dict[str, Any] = {"fault": "P-101 (CP-350): seal leak", "root_cause": "worn seal", "resolution": "Replaced seal"}
CASE |= {"parts_used": ["P-1000"], "resolved_at": "2025-05-01"}
WRITES = ("upsert_item", "replace_item", "patch_item", "delete_item")
Audit = list[dict[str, Any]]


def clients(stock: int = 5) -> FakeClients:
    inventory = FakeContainer({"P-1010": {"id": "P-1010", "part_number": "P-1010", "stock": stock}})
    containers = {"inventory": inventory, "audit": FakeContainer(), "memory": FakeContainer(rows=[CASE])}
    return FakeClients(containers | {"assets": FakeContainer(), "interventions": FakeContainer({"abc": {"id": "abc"}})})


async def run_chain(settings: Settings, fakes: FakeClients, name: str, arguments: dict[str, Any]) -> tuple[str, Audit]:
    tools = FieldTools(fakes, settings)
    function = getattr(tools, name)
    ctx = context(intervention_id="abc", actor="supervisor-1")
    ctx.function, ctx.arguments = function, arguments
    policy, audit = PolicyMiddleware(fakes, settings), AuditMiddleware(fakes, "Parts")

    async def innermost() -> None:
        ctx.result = await function.invoke(arguments=arguments, context=ctx, skip_parsing=True)

    async def through_policy() -> None:
        await policy.process(ctx, innermost)

    await audit.process(ctx, through_policy)
    return str(ctx.result), fakes.containers["audit"].created


async def reserve(settings: Settings, fakes: FakeClients, part: str, quantity: int) -> tuple[str, Audit]:
    return await run_chain(settings, fakes, "reserve_parts", {"lines": [{"part_number": part, "quantity": quantity}]})


async def test_policy_rejects_unknown_parts_and_excess_quantities_before_execution_and_audit_records_it(
    settings: Settings,
) -> None:
    fakes = clients()
    result, audit = await reserve(settings, fakes, "P-9999", 1)
    assert result.startswith("Policy violation") and "not in the catalogue" in result
    assert audit[-1]["outcome"] == "rejected" and audit[-1]["tool"] == "reserve_parts"
    assert audit[-1]["actor"] == "supervisor-1"
    result, audit = await reserve(settings, fakes, "P-1010", 99)
    assert "exceeds the bound" in result and fakes.containers["inventory"].items["P-1010"]["stock"] == 5
    result, audit = await reserve(settings, fakes, "P-1010", 2)
    assert result.startswith("Reservation abc-") and audit[-1]["outcome"] == "executed" and len(audit) == 3


def test_audit_module_only_creates_records() -> None:
    source = inspect.getsource(middleware_module)
    assert "create_item" in source and not any(verb in source for verb in WRITES)


async def test_similar_cases_provider_adds_a_delimited_untrusted_block(settings: Settings) -> None:
    provider = SimilarCasesProvider(clients(), settings, "CP-350")
    session_context = SessionContext(session_id="s", input_messages=[Message("user", ["Pump P-101 leaks at the seal"])])
    await provider.before_run(
        agent=cast(SupportsAgentRun, object()), session=AgentSession(), context=session_context, state={}
    )
    added = session_context.get_messages()
    assert len(added) == 1 and added[0].role == "user" and "worn seal" in added[0].text
    assert added[0].text.startswith(CASES_START) and added[0].text.rstrip().endswith(CASES_END)


def test_agents_are_wired_with_the_right_tools_providers_and_middleware(settings: Settings) -> None:
    fakes = clients()
    agents = build_agents(fakes, settings, FieldTools(fakes, settings), None, "CP-350")
    assert [agent.name for agent in agents] == list(NAMES)
    names = {agent.name: sorted(tool.name for tool in agent.default_options["tools"]) for agent in agents}
    expected = {"Triage": ["asset_history"], "Diagnostic": ["search_manual"], "Parts": ["reserve_parts"]}
    assert names == expected | {"WorkOrder": ["create_work_order"]}
    assert all(len(agent.middleware or []) == 2 for agent in agents)
    assert isinstance(agents.diagnostic.context_providers[0], SimilarCasesProvider)


def test_a2a_exposes_the_read_only_advisor_and_requires_the_diagnose_role(settings: Settings) -> None:
    fakes = clients()
    names = sorted(t.name for t in a2a.advisor(fakes, settings).default_options["tools"])
    card = a2a.card(settings)
    assert names == ["asset_history", "search_manual"] and not card.capabilities.streaming
    assert [skill.id for skill in card.skills] == ["diagnose"] and "reserves nothing" in card.description
    app = Starlette(routes=a2a.routes(fakes, settings), middleware=[Middleware(a2a.RoleGate)])
    app.state.settings, app.state.jwks = settings, JWKS()
    client = TestClient(app)
    assert client.get("/.well-known/agent-card.json").status_code == 200
    assert client.post("/", json={}).status_code == 401
    assert client.post("/", json={}, headers=bearer("x", ["Copilot.Use"])).status_code == 403
