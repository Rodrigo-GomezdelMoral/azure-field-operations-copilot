# ADR-010 · Rejection: Durable Task Scheduler for the long-running approval

**Status:** rejected · **Date:** 2026-10-20

## Context

An intervention pauses for hours or days while a supervisor decides. Azure's Durable Task
Scheduler (and the Durable Functions model it hosts) is built for exactly that shape: an
orchestration that waits for an external event, survives restarts, and resumes where it stopped,
with a managed store and a dashboard. Microsoft Agent Framework offers an integration for it. The
alternative implemented here is the framework's own checkpointing: `HandoffBuilder(...)
.with_checkpointing(CosmosCheckpointStorage)`, a `request_info` event that stops the run, and a
resume from the latest checkpoint on any replica (ADR-002).

## Decision

Keep the framework's checkpoints in Cosmos; do not add the scheduler.

- **The state already has a home.** The intervention document, the pending request, the audit
  trail and the checkpoint live in the same Cosmos account under the same identity and the same
  data-plane role. A second durable store would hold a copy of the workflow state under a second
  identity and a second access model, and the audit question *what exactly was pending when the
  supervisor decided* would have two answers.
- **The pause is a `request_info` event, not a timer.** The scheduler's strength is scheduling:
  timers, fan-out, retries with back-off. This workflow has one kind of wait, answered by a human
  through an authenticated route; the framework's checkpoint restores the exact pending request
  (`pending_request_info_events`) and the tool runs once (`tests/test_workflow.py`).
- **One more managed service is one more thing to secure and pay for**, in a repository whose
  thesis is restraint: every framework feature used here replaces code that would otherwise exist.
  The scheduler would replace nothing; `with_checkpointing` already did.

## Consequences

- Resume is explicit in the API: the newest checkpoint of the intervention that holds a pending
  request (`latest_pending` in `app/workflow.py`; two checkpoints can share a timestamp, so the
  iteration count breaks the tie — a restart test caught `get_latest` picking the wrong one) then
  `workflow.run(responses=..., checkpoint_id=...)`. The route that resumes is the route that
  authorises, so the two can never be ordered wrongly (ADR-007).
- Pending requests have no built-in expiry. `app.pending_request_age_hours` is recorded on every
  read and `infra/modules/apps.bicep` alerts when a request is older than four hours; closing or
  cancelling a stale intervention is a human action, by design.
- The approval wait is as durable as Cosmos (continuous backup, serverless) and no more; there is
  no replay dashboard beyond the audit trail and the `GET /v1/interventions/{id}` route.

## Revisit when

Interventions need scheduled behaviour — an automatic escalation after a deadline, retries of a
failed reservation against an external inventory system, fan-out across sites — and that
behaviour must itself be durable. Then the scheduler earns its place and this ADR is superseded.
