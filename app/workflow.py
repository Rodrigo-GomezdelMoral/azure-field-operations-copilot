from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from agent_framework import CheckpointStorage, Content, MCPStreamableHTTPTool, Message, Workflow, WorkflowEvent
from agent_framework.orchestrations import HandoffAgentUserRequest, HandoffBuilder

from app.agents import build_agents
from app.clients import Clients
from app.config import Settings
from app.models import Intervention, PendingRequest, RequestResponse
from app.tools import FieldTools

DONE_MARKER = "Work order WO-"


@dataclass
class Runtime:
    clients: Clients
    settings: Settings
    tools: FieldTools
    storage: CheckpointStorage
    inventory: MCPStreamableHTTPTool | None = None


def finished(messages: list[Message]) -> bool:
    last = messages[-1] if messages else None
    return bool(last is not None and last.author_name == "WorkOrder" and DONE_MARKER in last.text)


def create_workflow(runtime: Runtime, intervention: Intervention) -> Workflow:
    agents = build_agents(
        runtime.clients, runtime.settings, runtime.tools, runtime.inventory, intervention.equipment_model or ""
    )
    builder = HandoffBuilder(name=intervention.id, participants=list(agents)).with_start_agent(agents.triage)
    builder.add_handoff(agents.triage, [agents.diagnostic, agents.parts])
    builder.add_handoff(agents.diagnostic, [agents.parts, agents.workorder])
    builder.add_handoff(agents.parts, [agents.workorder, agents.diagnostic])
    return builder.with_checkpointing(runtime.storage).with_termination_condition(finished).build()


def run_events(
    runtime: Runtime,
    workflow: Workflow,
    actor: str,
    intervention_id: str,
    *,
    message: Message | None = None,
    responses: Mapping[str, Any] | None = None,
    checkpoint_id: str | None = None,
) -> AsyncIterator[WorkflowEvent]:
    kwargs = {"intervention_id": intervention_id, "actor": actor}
    stream = workflow.run(
        message,
        stream=True,
        responses=responses,
        checkpoint_id=checkpoint_id,
        checkpoint_storage=runtime.storage,
        function_invocation_kwargs=kwargs,
    )
    return stream.__aiter__()


def pending_request(event: WorkflowEvent) -> PendingRequest | None:
    if event.type != "request_info" or event.request_id is None:
        return None
    data, agent = event.data, str(event.source_executor_id or event.executor_id or "")
    if isinstance(data, Content) and data.type == "function_approval_request":
        call = getattr(data, "function_call", None)
        arguments = (call.parse_arguments() if call is not None else None) or {}
        tool = str(getattr(call, "name", "")) or None
        return PendingRequest(
            request_id=event.request_id,
            kind="function_approval",
            agent=agent,
            tool=tool,
            arguments=dict(arguments),
            payload=data.to_dict(),
        )
    if isinstance(data, HandoffAgentUserRequest):
        return PendingRequest(
            request_id=event.request_id, kind="user_question", agent=agent, question=data.agent_response.text
        )
    return None


def response_for(pending: PendingRequest, body: RequestResponse) -> Any:
    if pending.kind == "function_approval":
        return Content.from_dict(pending.payload).to_function_approval_response(bool(body.approved))
    return HandoffAgentUserRequest.create_response(body.answer or "")
