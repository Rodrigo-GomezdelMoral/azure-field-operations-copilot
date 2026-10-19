# ADR-006 · A2A exposes a read-only agent

**Status:** accepted · **Date:** 2026-10-19

## Context

A field-service system outside the plant wants to ask the copilot what is wrong with an asset
and what the manual says to do about it. Agent-to-Agent (A2A) is the protocol for that: the
caller discovers an agent card, sends a message over JSON-RPC and receives a task with the
agent's answer. The framework ships `A2AExecutor`, which runs any `Agent` behind the `a2a-sdk`
request handler, so the whole server is an agent, a card and two route factories.

The question is **which** agent to put behind it. The handoff workflow is the obvious candidate:
it already does everything, including reserving parts and drafting work orders under a
supervisor's approval. Exposing it would hand an external system the same powers a technician
has inside the plant, with the approval gate now spanning an organisational boundary: the
supervisor who answers the request would be approving an action requested by software they do
not run, on behalf of a user they cannot see.

## Decision

- `ca-fopa2a` serves **`DiagnosticAdvisor`**: the Diagnostic specialist's instructions, with a
  short addendum that removes the handoff rule, and the **read-only** field tools
  (`search_manual`, `asset_history`). No handoff, no `reserve_parts`, no `create_work_order`,
  no inventory MCP tool and no similar-cases provider: the external caller gets the manual and
  the registry, not the plant's experience and not its stock.
- Its identity, `id-fopa2a`, holds the Cosmos **reader** role on `assets` and `memory` and the
  search reader role, and nothing that can write (`infra/modules/shared-access.bicep`,
  `infra/modules/data.bicep`). The audit container is not writable by it either, which is why the
  advisor carries no `AuditMiddleware`: the A2A task store is the record of what it was asked.
- The ingress is external with **Entra authentication required**, and the JSON-RPC route also
  checks the `Copilot.Diagnose` app role in the token (`a2a_server/main.py`, `RoleGate`); the
  agent card stays readable so the caller can discover the interface before authenticating.
- The card declares one skill, no streaming and no push notifications: the advisor answers one
  question with one message.

## Consequences

- Write actions never cross the organisational boundary. If the external system wants parts
  reserved, it asks a technician of this plant, who opens an intervention through the API and
  whose supervisor approves it: the authorisation model stays in one place.
- `tests/test_agents.py` asserts that the advisor's tools are exactly the read-only pair, that
  the card advertises no write capability and that the route refuses a token without the role.
- The advisor's answer cites manual sections like the internal Diagnostic agent, so the caller
  can verify it against the same sourcebooks; the citation precision measured by `eval/run.py`
  applies to the same prompt.

## Rejected

- **The full workflow over A2A.** It works technically; it moves the approval gate across an
  organisational boundary and gives an external identity a path to the plant's writes.
- **A2A with the write tools but approvals routed back to the caller.** The caller would then be
  the approver of its own requests, which is exactly the separation of duties the API refuses
  (ADR-007).
- **A plain REST endpoint for the diagnosis.** Simpler, and the caller would need a bespoke
  client; the A2A card and task model are what another agent runtime already speaks.
