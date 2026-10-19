from collections.abc import AsyncIterator, Awaitable, Sequence
from typing import Any, cast

from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    FunctionInvocationLayer,
    InMemoryCheckpointStorage,
    Message,
    ResponseStream,
    WorkflowCheckpoint,
)

from app.config import Settings
from app.models import Intervention, PendingRequest, RequestResponse
from app.tools import FieldTools
from app.workflow import DONE_MARKER, Runtime, create_workflow, pending_request, response_for, run_events
from tests.conftest import FakeClients, FakeContainer

DRAFT = {"asset_id": "P-101", "title": "Pump P-101 vibration", "diagnosis": "bearing wear", "procedure_refs": ["A > B"]}
INTERVENTION = Intervention(id="int-1", technician_id="tech-1", asset_id="P-101", equipment_model="CP-350")


class ScriptedClient(FunctionInvocationLayer[Any], BaseChatClient[Any]):
    """Returns pre-written assistant turns, one per model call, in order, streaming or not."""

    def __init__(self, turns: list[list[Content]]) -> None:
        super().__init__()
        self.turns = list(turns)

    def _inner_get_response(
        self, *, messages: Sequence[Message], stream: bool, options: Any, **kwargs: Any
    ) -> Awaitable[ChatResponse] | ResponseStream[ChatResponseUpdate, ChatResponse]:
        contents = self.turns.pop(0) if self.turns else [Content.from_text("nothing more to say")]

        async def updates() -> AsyncIterator[ChatResponseUpdate]:
            yield ChatResponseUpdate(contents=contents, role="assistant")

        async def response() -> ChatResponse:
            return ChatResponse(messages=[Message("assistant", contents)])

        return ResponseStream(updates(), finalizer=ChatResponse.from_updates) if stream else response()


def call(name: str, **arguments: Any) -> Content:
    return Content.from_function_call(call_id=f"call-{name}", name=name, arguments=arguments)


def runtime(storage: InMemoryCheckpointStorage, turns: list[list[Content]], settings: Settings) -> Runtime:
    containers = {name: FakeContainer() for name in ("audit", "memory", "assets", "inventory")}
    fakes = FakeClients(containers | {"interventions": FakeContainer({"int-1": {"id": "int-1"}})})
    fakes.chat = fakes.small_chat = cast(Any, ScriptedClient(turns))
    return Runtime(fakes, settings, FieldTools(fakes, settings), storage)


def patches(run: Runtime) -> list[Any]:
    return cast(FakeContainer, run.clients.container("interventions")).patches


async def run_to_approval(
    storage: InMemoryCheckpointStorage, settings: Settings
) -> tuple[Runtime, PendingRequest, WorkflowCheckpoint]:
    turns = [[call("handoff_to_Diagnostic")], [call("handoff_to_WorkOrder")], [call("create_work_order", draft=DRAFT)]]
    first = runtime(storage, turns, settings)
    message = Message("user", ["Pump P-101 trips on high vibration after five minutes at full load."])
    events = [
        e async for e in run_events(first, create_workflow(first, INTERVENTION), "tech-1", "int-1", message=message)
    ]
    pending = next(p for p in map(pending_request, events) if p)
    assert pending.kind == "function_approval" and pending.tool == "create_work_order" and patches(first) == []
    checkpoint = await storage.get_latest(workflow_name="int-1")
    assert checkpoint is not None
    return first, pending, checkpoint


async def resume(
    storage: InMemoryCheckpointStorage,
    settings: Settings,
    pending: PendingRequest,
    checkpoint: WorkflowCheckpoint,
    approved: bool,
    turns: list[list[Content]],
) -> Runtime:
    second = runtime(storage, turns, settings)
    answer = response_for(pending, RequestResponse(request_id=pending.request_id, approved=approved))
    events = run_events(
        second,
        create_workflow(second, INTERVENTION),
        "sup-1",
        "int-1",
        responses={pending.request_id: answer},
        checkpoint_id=checkpoint.checkpoint_id,
    )
    kinds = {p.kind for p in [pending_request(e) async for e in events] if p}
    assert kinds <= (set() if approved else {"user_question"})
    return second


async def test_approval_survives_a_restart_and_the_privileged_tool_runs_exactly_once(settings: Settings) -> None:
    storage = InMemoryCheckpointStorage()
    _, pending, checkpoint = await run_to_approval(storage, settings)
    second = await resume(
        storage, settings, pending, checkpoint, True, [[Content.from_text(f"{DONE_MARKER}1 created")]]
    )
    assert len(patches(second)) == 1 and patches(second)[0][1][0]["value"]["procedure_refs"] == ["A > B"]
    executed = [
        row
        for row in cast(FakeContainer, second.clients.container("audit")).created
        if row["tool"] == "create_work_order"
    ]
    assert len(executed) == 1 and executed[0]["actor"] == "tech-1" and executed[0]["outcome"] == "executed"


async def test_no_privileged_tool_executes_without_an_approval(settings: Settings) -> None:
    storage = InMemoryCheckpointStorage()
    _, pending, checkpoint = await run_to_approval(storage, settings)
    second = await resume(
        storage, settings, pending, checkpoint, False, [[Content.from_text("Understood, nothing created.")]]
    )
    assert patches(second) == [] and not any(
        row["tool"] == "create_work_order" for row in cast(FakeContainer, second.clients.container("audit")).created
    )
