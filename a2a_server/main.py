from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import jwt
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT
from agent_framework import Agent
from agent_framework.a2a import A2AExecutor
from fastapi import HTTPException
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute

from app.agents import instructions
from app.clients import Clients, build_clients
from app.config import Settings
from app.main import LOGIN, verify_token
from app.tools import FieldTools

ADVISOR = """

## Consulted over A2A

An external field-service system is asking, not a technician of this plant. You have no colleague to
hand off to and no tool that writes, so the handoff rule above does not apply: answer with the
diagnosis, the cited procedure, the safety section and the parts as plain names, then stop."""
DESCRIPTION = (
    "Read-only diagnostic specialist for industrial assets: the most likely cause, the procedure cited from the "
    "maintenance manuals, the safety requirements and the parts likely needed. It reserves nothing and creates nothing."
)
SKILL = AgentSkill(id="diagnose", name="Diagnose a fault", description=DESCRIPTION, tags=["maintenance", "diagnosis"])
SKILL.examples.append("P-101 (CP-350) trips on high vibration after five minutes at full load.")


def advisor(clients: Clients, settings: Settings) -> Agent[Any]:
    tools = FieldTools(clients, settings).read_only()
    prompt = instructions("diagnostic") + ADVISOR
    return Agent(clients.chat, prompt, name="DiagnosticAdvisor", tools=tools, default_options=clients.options)


def card(settings: Settings) -> AgentCard:
    binding = {"protocol_binding": "JSONRPC", "protocol_version": PROTOCOL_VERSION_CURRENT}
    fields: dict[str, Any] = {"name": "DiagnosticAdvisor", "description": DESCRIPTION, "version": "1.0.0"}
    fields |= {"default_input_modes": ["text"], "default_output_modes": ["text"], "skills": [SKILL]}
    fields |= {"supported_interfaces": [AgentInterface(url=settings.a2a_public_url, **binding)]}
    return AgentCard(capabilities=AgentCapabilities(streaming=False, push_notifications=False), **fields)


def routes(clients: Clients, settings: Settings) -> list[BaseRoute]:
    agent_card, executor = card(settings), A2AExecutor(advisor(clients, settings))
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=agent_card)
    return [*create_agent_card_routes(agent_card), *create_jsonrpc_routes(handler, "/")]


class RoleGate(BaseHTTPMiddleware):
    """Requires the Copilot.Diagnose app role on the JSON-RPC route; the agent card stays readable."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        settings: Settings = request.app.state.settings
        if request.method == "POST" and settings.require_auth:
            try:
                authorization = request.headers.get("authorization", "")
                verify_token(settings, request.app.state.jwks, authorization, settings.a2a_app_role)
            except HTTPException as refused:
                return JSONResponse({"detail": refused.detail}, status_code=refused.status_code)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    settings = Settings()
    clients = build_clients(settings)
    app.state.settings = settings
    app.state.jwks = jwt.PyJWKClient(f"{LOGIN}/{settings.entra_tenant_id}/discovery/v2.0/keys")
    app.router.routes.extend(routes(clients, settings))
    yield
    await clients.close()


app = Starlette(lifespan=lifespan, middleware=[Middleware(RoleGate)])
