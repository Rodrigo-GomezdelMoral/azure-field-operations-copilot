# ADR-007 · Separation of duties on approvals and questions

**Status:** accepted · **Date:** 2026-10-19

## Context

The approval gate on `reserve_parts` and `create_work_order` is only worth something if the person
who approves is not the person who asked. A technician who can open an intervention and then
approve the reservation it produced has, in effect, an unattended write. The same workflow also
pauses when a specialist asks the technician a question; that answer, conversely, must come from
the technician who is standing in front of the machine and not from a supervisor elsewhere.

Both requests arrive at the same route, `POST /v1/interventions/{id}/responses`, carrying a
`request_id` that the client obtained from the stream. A continuation identifier is a capability
only if the server does not trust it.

## Decision

`authorise()` in `app/main.py` runs **before** any checkpoint is loaded, on the intervention
record and the caller's claims alone:

- For a `function_approval` request, the caller must hold the `supervisor` role **and** must not
  be the technician who opened the intervention (`claims.oid != intervention.technician_id`).
- For a `user_question` request, the caller must be that technician.
- In every case the `request_id` must be the one currently pending on that intervention;
  otherwise the route answers `409` and nothing is resumed.

The roles come from the Entra token: `Copilot.Use` is the app role every caller of the API
needs (validated at the Container Apps ingress and again in `principal()`), `supervisor` is a
role claim the organisation assigns to approvers. In local demo mode without authentication the
caller's identity comes from an `x-demo-user` header and both roles are granted, so the rule is
still exercised by the tests and visible in the interface.

## Why

- **Checking before loading** means an unauthorised caller cannot cause a checkpoint read, a
  workflow rebuild or a model call. The expensive and sensitive work happens only for a caller
  the record says may do it.
- **The intervention record is the authority**, not the request. The request carries an id; the
  record says who opened the intervention and what is pending.
- **Two different rules for two different requests** reflect two different risks: an approval
  is a privilege and needs a second person; an answer is context and needs the right person.

## Consequences

- `tests/test_main.py` proves that a supervisor who opened the intervention is refused when
  approving it, that a non-supervisor is refused, that a different technician cannot answer a
  question, and that a stale or unknown `request_id` is refused with `409`.
- A one-person site cannot use the system as shipped: an approval always needs a second account
  with the supervisor role. That is the intended property, stated in the README.
- The audit record of the executed tool carries the approver as `actor` (ADR-008), so the trail
  shows who asked and who approved as two different identities.
