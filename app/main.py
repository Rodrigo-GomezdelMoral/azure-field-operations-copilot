import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

import jwt
from agent_framework import AgentResponseUpdate, Content, MCPStreamableHTTPTool, Message, WorkflowEvent
from agent_framework.exceptions import ToolException
from agent_framework_azure_cosmos import CosmosCheckpointStorage
from azure.core.messaging import CloudEvent
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.clients import build_clients
from app.config import Settings
from app.models import AuditEvent, Fault, Intervention, PendingRequest, RequestResponse
from app.telemetry import configure, pending_age
from app.tools import FieldTools
from app.workflow import Runtime, create_workflow, latest_pending, pending_request, response_for, run_events

LOGIN = "https://login.microsoftonline.com"
AUDIT = "SELECT * FROM c WHERE c.intervention_id = @id ORDER BY c.at"
CHECKPOINT_TYPES = ["types:GenericAlias"]


class NewIntervention(Fault):
    image_base64: str | None = None


class Resolution(BaseModel):
    summary: str = Field(min_length=10, max_length=2000)
    root_cause: str = Field(min_length=3, max_length=500)
    parts_used: list[str] = []


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    configure(settings)
    clients = build_clients(settings)
    mcp_tool = MCPStreamableHTTPTool(name="inventory", url=settings.inventory_mcp_url)
    inventory: MCPStreamableHTTPTool | None = mcp_tool
    try:
        await mcp_tool.connect()
    except ToolException:
        inventory = None
    storage = CosmosCheckpointStorage(
        container_client=clients.container("checkpoints"), allowed_checkpoint_types=CHECKPOINT_TYPES
    )
    app.state.settings = settings
    app.state.jwks = jwt.PyJWKClient(f"{LOGIN}/{settings.entra_tenant_id}/discovery/v2.0/keys")
    app.state.runtime = Runtime(clients, settings, FieldTools(clients, settings), storage, inventory)
    yield
    if inventory is not None:
        await inventory.close()
    await clients.close()


app = FastAPI(title="Industrial Field Operations Copilot", lifespan=lifespan)


def verify_token(settings: Settings, jwks: jwt.PyJWKClient, authorization: str, role: str) -> dict[str, Any]:
    token = authorization[len("Bearer ") :]
    if not token:
        raise HTTPException(401, "a bearer token is required")
    issuer = f"{LOGIN}/{settings.entra_tenant_id}/v2.0"
    audiences = [settings.api_audience, settings.api_audience.removeprefix("api://")]
    try:
        key = jwks.get_signing_key_from_jwt(token).key
        claims: dict[str, Any] = jwt.decode(token, key, algorithms=["RS256"], audience=audiences, issuer=issuer)
    except jwt.PyJWTError as error:
        raise HTTPException(401, f"invalid token: {error}") from error
    if role not in claims.get("roles", []):
        raise HTTPException(403, f"the {role} app role is required")
    return claims


def principal(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if not settings.require_auth:
        demo = request.headers.get("x-demo-user", "local")
        return {"oid": demo, "roles": [settings.api_app_role, settings.supervisor_role]}
    authorization = request.headers.get("authorization", "")
    claims = verify_token(settings, request.app.state.jwks, authorization, settings.api_app_role)
    forwarded = request.headers.get("x-forwarded-user")
    if forwarded and claims.get("oid") == settings.proxy_principal_id:
        return {"oid": forwarded, "roles": request.headers.get("x-forwarded-roles", "").split(",")}
    return claims


Claims = Annotated[dict[str, Any], Depends(principal)]


def frame(event: WorkflowEvent) -> str:
    data = event.data
    agent = (event.source_executor_id if event.type == "request_info" else None) or event.executor_id
    request_id = event.request_id if event.type == "request_info" else None
    body: dict[str, Any] = {"type": event.type, "agent": agent, "request_id": request_id}
    if isinstance(data, Content):
        body["data"] = data.to_dict()
    elif isinstance(data, AgentResponseUpdate):
        body["data"] = {
            "role": str(data.role),
            "author": data.author_name,
            "contents": [c.to_dict() for c in data.contents],
        }
    elif hasattr(data, "text"):
        body["data"] = {"text": data.text}
    elif data is not None and event.type != "superstep_completed":
        body["data"] = str(data)[:2000]
    return f"event: {event.type}\ndata: {json.dumps(body, default=str)}\n\n"


async def stream_run(
    request: Request, intervention: Intervention, events: AsyncIterator[WorkflowEvent]
) -> AsyncIterator[str]:
    runtime: Runtime = request.app.state.runtime
    container, status, pending = runtime.clients.container("interventions"), "completed", None
    async for event in events:
        yield frame(event)
        if found := pending_request(event):
            pending = found
    if pending is not None:
        status = "pending_approval" if pending.kind == "function_approval" else "pending_question"
        if pending.kind == "function_approval" and runtime.clients.events is not None:
            payload = {"intervention_id": intervention.id, "tool": pending.tool, "agent": pending.agent}
            await runtime.clients.events.send(
                CloudEvent(source="/fieldops/api", type="FieldOps.ApprovalRequested", data=payload)
            )
    patched = intervention.model_copy(update={"status": status, "pending": pending})
    await container.upsert_item(patched.model_dump(mode="json"))
    final = {"status": status, "pending": pending.model_dump(mode="json") if pending else None}
    yield f"event: status\ndata: {json.dumps(final)}\n\n"


async def load(request: Request, intervention_id: str) -> Intervention:
    runtime: Runtime = request.app.state.runtime
    try:
        return Intervention.model_validate(
            await runtime.clients.container("interventions").read_item(intervention_id, partition_key=intervention_id)
        )
    except CosmosResourceNotFoundError as error:
        raise HTTPException(404, "intervention not found") from error


@app.post("/v1/interventions")
async def open_intervention(body: NewIntervention, request: Request, claims: Claims) -> StreamingResponse:
    runtime: Runtime = request.app.state.runtime
    asset = await runtime.clients.container("assets").read_item(body.asset_id, partition_key=body.asset_id)
    intervention = Intervention(
        technician_id=claims["oid"], asset_id=body.asset_id, equipment_model=asset.get("equipment_model")
    )
    await runtime.clients.container("interventions").create_item(intervention.model_dump(mode="json"))
    contents: list[Content] = [Content.from_text(body.description)]
    if body.image_base64 and body.image_media_type:
        contents.append(Content.from_data(data=base64.b64decode(body.image_base64), media_type=body.image_media_type))
    workflow, message = create_workflow(runtime, intervention), Message("user", contents)
    events = run_events(runtime, workflow, claims["oid"], intervention.id, message=message)
    headers = {"x-intervention-id": intervention.id}
    return StreamingResponse(stream_run(request, intervention, events), media_type="text/event-stream", headers=headers)


@app.post("/v1/interventions/{intervention_id}/responses")
async def respond(intervention_id: str, body: RequestResponse, request: Request, claims: Claims) -> StreamingResponse:
    runtime: Runtime = request.app.state.runtime
    intervention = await load(request, intervention_id)
    pending = intervention.pending
    if pending is None or pending.request_id != body.request_id:
        raise HTTPException(409, "no such pending request on this intervention")
    authorise(runtime.settings, claims, intervention, pending)
    decision = ("approved" if body.approved else "denied") if pending.kind == "function_approval" else "answered"
    fields: dict[str, Any] = {"intervention_id": intervention_id, "agent": pending.agent, "actor": claims["oid"]}
    record = AuditEvent(**fields, tool=pending.tool or "question", arguments=pending.arguments, outcome=decision)
    await runtime.clients.container("audit").create_item(record.model_dump(mode="json"))
    checkpoint = await latest_pending(runtime.storage, intervention_id)
    if checkpoint is None:
        raise HTTPException(409, "no checkpoint to resume from")
    workflow, responses = create_workflow(runtime, intervention), {pending.request_id: response_for(pending, body)}
    checkpoint_id = checkpoint.checkpoint_id
    events = run_events(
        runtime, workflow, claims["oid"], intervention_id, responses=responses, checkpoint_id=checkpoint_id
    )
    return StreamingResponse(stream_run(request, intervention, events), media_type="text/event-stream")


def authorise(settings: Settings, claims: dict[str, Any], intervention: Intervention, pending: PendingRequest) -> None:
    oid, roles = claims.get("oid"), claims.get("roles", [])
    if pending.kind == "function_approval":
        if settings.supervisor_role not in roles:
            raise HTTPException(403, "only a supervisor may answer an approval request")
        if oid == intervention.technician_id:
            raise HTTPException(403, "the technician who opened the intervention may not approve its own actions")
    elif oid != intervention.technician_id:
        raise HTTPException(403, "only the technician who opened the intervention may answer its questions")


@app.post("/v1/interventions/{intervention_id}/close", status_code=204)
async def close_intervention(intervention_id: str, body: Resolution, request: Request, claims: Claims) -> None:
    runtime: Runtime = request.app.state.runtime
    intervention = await load(request, intervention_id)
    if claims.get("oid") != intervention.technician_id:
        raise HTTPException(403, "only the technician who opened the intervention may close it")
    text = f"{intervention.asset_id} ({intervention.equipment_model}): {body.summary}"
    vector = list(next(iter(await runtime.clients.embeddings.get_embeddings([text]))).vector)
    case: dict[str, Any] = {"id": f"wo-{intervention.id}", "asset_id": intervention.asset_id, "fault": text}
    case |= {"equipment_model": intervention.equipment_model, "root_cause": body.root_cause, "embedding": vector}
    case |= {"resolution": body.summary, "parts_used": body.parts_used}
    case |= {"resolved_at": datetime.now(UTC).date().isoformat()}
    await runtime.clients.container("memory").upsert_item(case)
    closed = intervention.model_copy(update={"status": "closed", "resolution": body.summary, "pending": None})
    await runtime.clients.container("interventions").upsert_item(closed.model_dump(mode="json"))


@app.get("/v1/interventions/{intervention_id}")
async def get_intervention(intervention_id: str, request: Request, claims: Claims) -> dict[str, Any]:
    runtime: Runtime = request.app.state.runtime
    intervention = await load(request, intervention_id)
    supervisor = runtime.settings.supervisor_role in claims.get("roles", [])
    if claims.get("oid") != intervention.technician_id and not supervisor:
        raise HTTPException(403, "not your intervention")
    if intervention.pending is not None:
        pending_age.record((datetime.now(UTC) - intervention.pending.created_at).total_seconds() / 3600)
    rows = runtime.clients.container("audit").query_items(AUDIT, parameters=[{"name": "@id", "value": intervention_id}])
    return intervention.model_dump(mode="json") | {"audit": [row async for row in rows]}


@app.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    return {"status": "ok"}
