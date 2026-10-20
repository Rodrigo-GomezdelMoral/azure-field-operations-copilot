# ADR-002 · Durable approvals through workflow checkpoints, not a queue

**Status:** accepted · **Date:** 2026-10-19

## Context

`reserve_parts` and `create_work_order` require a supervisor's approval. The supervisor is not in
the room: the request may wait minutes or hours, the API container may scale to zero or be
replaced by a deployment in between, and the answer may arrive at a different instance than the
one that asked. The system must therefore hold the state of a half-finished run somewhere that
outlives the process, and resume it exactly where it stopped, with the tool executing exactly
once.

The conventional design is a queue plus a table: on an approval request, serialise what is known
into a `pending_approvals` record, publish a message, end the request; on the answer, read the
record, rebuild the context by hand and continue. Microsoft Agent Framework offers another
mechanism: workflow checkpoints.

## Decision

The handoff workflow is built with `with_checkpointing(CosmosCheckpointStorage(...))`
(`app/workflow.py`), one workflow per intervention named after it, because the storage partitions
by `/workflow_name`. When a tool with `approval_mode="always_require"` is reached, the framework
emits a `request_info` event whose data is a `function_approval_request`; the API records the
request on the intervention, publishes `FieldOps.ApprovalRequested` to the Event Grid topic, ends
the stream, and the process may exit. The checkpoint, including the pending request, is already
in Cosmos. Later, from any instance, `POST /v1/interventions/{id}/responses` authorises the caller,
loads the latest checkpoint for the workflow name, rebuilds the workflow from the same code and
calls `workflow.run(checkpoint_id=..., responses={request_id: ...})` — resume and answer in one
call. The approval response is reconstructed from the request payload the API stored, so no
in-memory object survives between the two requests.

The same path serves a specialist's question to the technician (`HandoffAgentUserRequest`): the
answer becomes the response, the technician is the only authorised responder.

## Why

- **The workflow already persists exactly the state a queue would duplicate**: the conversation,
  the active specialist, the pending request and its id. A queue message would carry a copy that
  can drift from the checkpoint, and the resume logic would be ours to write and to get wrong.
- **Exactly-once is a property of the checkpoint, not of our code.** The tool runs when the
  approval response is applied to the checkpointed run; a second answer to the same request finds
  no pending request and is rejected by the API before anything is loaded.
- **The approval request is an event, the state is not.** Event Grid carries the notification
  (something is waiting), Cosmos carries the truth (what is waiting and where to resume). Each
  does the one thing it is for.

## Consequences

- `tests/test_workflow.py` runs a scripted workflow to an approval request, discards the workflow
  object, rebuilds it, resumes from the stored checkpoint with an approval, and asserts that the
  privileged tool executed once and the run terminated. That test is the contract of this ADR.
- Checkpoints carry conversation text and tool arguments; the `checkpoints` container has a
  90-day TTL and the data-plane role on it belongs to the API identity only.
- The subscriber of `FieldOps.ApprovalRequested` is out of scope; the README says so and shows
  the event.

## Rejected

- **Service Bus queue plus a pending-approvals table.** Standard, and twice the state.
- **Durable Task Scheduler** as the orchestration runtime (ADR-010): a second orchestrator under
  the one the framework already provides.
