# ADR-008 · Create-only audit through function middleware

**Status:** accepted · **Date:** 2026-10-19

## Context

Every decision an agent takes that touches the world must be reconstructible afterwards: which
specialist called which tool, with which arguments, under which intervention, on behalf of whom,
and whether it ran or was stopped. The handoffs between specialists are decisions too, and in
Microsoft Agent Framework they are function calls like any other tool. The two write tools run
only after a supervisor's approval, and the approval itself is a record the API writes when it
answers the request.

The obvious implementation is an `audit(...)` call inside each tool. It is also the wrong one:
a tool that forgets to call it is invisible, the handoff functions the framework generates cannot
be edited, and a tool that fails before its last line writes nothing.

## Decision

`AuditMiddleware` (`app/middleware.py`) is a `FunctionMiddleware` attached to **all four agents**.
For every function invocation — tool or handoff — it lets the call proceed and then writes one
`AuditEvent` with the agent, the tool name, the arguments, the intervention and actor taken from
the invocation kwargs, and the outcome: `executed`, or `rejected` when `PolicyMiddleware` stopped
the call. The record is written with **`create_item`**, never `upsert_item` or `replace_item`;
the `audit` container is partitioned by `/intervention_id` and the identity that writes it holds
no delete permission beyond the data role the API needs for its own work.

`PolicyMiddleware` sits inside the audit in the chain, so that a rejected call is audited as
rejected: it checks `reserve_parts` arguments against the catalogue and the quantity bound before
execution, sets `context.result` to the violation and returns without calling `call_next()`.

## Why

- **One place, every call.** The middleware sees the handoff functions the framework creates and
  every tool the agents hold, without a line in any tool.
- **Append-only by construction.** An audit that can be overwritten is a log, not an audit.
  `create_item` fails on a duplicate id, and each event carries its own random id; there is no
  path in the code that modifies an existing record.
- **The outcome is part of the record.** Writing after `call_next()` means the record says what
  happened, including a policy rejection, rather than what was about to happen. The approval
  request itself is recorded by the API when the workflow pauses, so the trail reads: requested,
  approved or denied by whom, executed or rejected.

## Consequences

- The audit write adds a Cosmos call per tool invocation. For a workflow with a dozen calls that
  is a dozen small writes, well inside serverless pricing (`docs/cost.md`).
- If the audit write fails, the tool result is still returned to the agent; the failure surfaces
  in telemetry rather than blocking the technician. An enterprise that needs the opposite trade
  swaps the order of the two statements in `process`.
- `tests/test_agents.py` asserts that a rejected reservation produces an audit record with
  outcome `rejected`, that an executed call produces `executed`, and that the module never calls
  an update method.
