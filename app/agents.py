from dataclasses import dataclass
from typing import Any

from agent_framework import Agent, ContextProvider, FunctionMiddleware, FunctionTool, MCPStreamableHTTPTool
from agent_framework_azure_contentunderstanding import ContentUnderstandingContextProvider

from app.clients import Clients
from app.config import PROMPTS_DIR, Settings
from app.memory import SimilarCasesProvider
from app.middleware import AuditMiddleware, PolicyMiddleware
from app.tools import FieldTools

NAMES = ("Triage", "Diagnostic", "Parts", "WorkOrder")


@dataclass(frozen=True)
class Agents:
    triage: Agent[Any]
    diagnostic: Agent[Any]
    parts: Agent[Any]
    workorder: Agent[Any]

    def __iter__(self) -> Any:
        return iter((self.triage, self.diagnostic, self.parts, self.workorder))


def instructions(name: str) -> str:
    return (PROMPTS_DIR / f"{name}_v1.md").read_text(encoding="utf-8")


def vision_provider(clients: Clients, settings: Settings) -> ContextProvider:
    endpoint, analyzer = settings.foundry_account_endpoint, settings.analyzer_id
    return ContentUnderstandingContextProvider(
        endpoint=endpoint, credential=clients.credential, analyzer_id=analyzer, max_wait=90
    )


def build_agents(
    clients: Clients,
    settings: Settings,
    tools: FieldTools,
    inventory: MCPStreamableHTTPTool | None,
    equipment_model: str,
) -> Agents:
    def agent(name: str, client: Any, agent_tools: list[Any], providers: list[ContextProvider]) -> Agent[Any]:
        middleware: list[FunctionMiddleware] = [AuditMiddleware(clients, name), PolicyMiddleware(clients, settings)]
        return Agent(
            client,
            instructions(name.lower()),
            name=name,
            tools=agent_tools,
            default_options=clients.options,
            context_providers=providers,
            middleware=middleware,
            require_per_service_call_history_persistence=True,
        )

    inventory_tools: list[FunctionTool | MCPStreamableHTTPTool] = [inventory] if inventory else []
    return Agents(
        triage=agent("Triage", clients.chat, [tools.asset_history], [vision_provider(clients, settings)]),
        diagnostic=agent(
            "Diagnostic",
            clients.chat,
            [tools.search_manual],
            [SimilarCasesProvider(clients, settings, equipment_model)],
        ),
        parts=agent("Parts", clients.small_chat, [*inventory_tools, tools.reserve_parts], []),
        workorder=agent("WorkOrder", clients.chat, [tools.create_work_order], []),
    )
