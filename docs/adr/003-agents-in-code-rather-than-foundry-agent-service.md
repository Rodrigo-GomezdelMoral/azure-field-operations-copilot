# ADR-003 · Agents defined in code, not in Foundry Agent Service

**Status:** accepted · **Date:** 2026-10-19

## Context

Microsoft Foundry can host an agent as a service object: instructions, tools and model are
stored in the project, the agent has a durable identity, threads are kept by the service, and a
client calls it by name. The alternative is what Microsoft Agent Framework calls a local agent:
`Agent(client=FoundryChatClient(...), instructions=..., tools=...)`, an object this process
creates from files in this repository on every request and that the service never sees as an
entity. Both talk to the same model deployments under the same identity.

This repository has four specialists, two of which hold tools that must not run without a human
approval, an audit middleware that must see every tool call, a policy middleware that must be
able to stop one, a context provider that must inject retrieved cases before the Diagnostic
specialist reads the conversation, and a handoff workflow that must survive a process restart
through a checkpoint this repository owns.

## Decision

The four agents are **code**: `app/agents.py` builds them from `prompts/*.md`, `app/tools.py`,
`app/memory.py` and `app/middleware.py`, once per intervention, inside the API process. The
Foundry project is used for what only it can do — model deployments, the content filter, the
evaluation service and the Content Understanding analyzer — and not as the registry of what the
agents are.

## Why

- **The control plane lives where the tests are.** Approval, policy and audit are middleware
  and decorators in this repository, covered by `tests/`. A hosted agent would move the tool
  definitions and part of the invocation path into the service, where the guarantee that no
  write runs without an approval record would depend on the service's configuration rather than
  on code a reader can open.
- **The prompt is a versioned file.** `prompts/diagnostic_v1.md` is reviewed in a pull request,
  diffed, and evaluated against a dated report. A hosted agent's instructions are a field in a
  portal or an API call; the version is whatever was last written.
- **The workflow owns the state.** `HandoffBuilder` checkpoints the whole orchestration — which
  specialist is active, the pending approval, the conversation — into Cosmos under
  `/workflow_name`. Hosted threads would hold a second copy of part of that state in the service,
  with a second lifecycle and a second deletion path.
- **Nothing is lost.** Tracing, token usage and evaluations arrive from the framework and from
  `FoundryEvals` either way; the only thing a hosted agent adds for this workload is a durable
  identity for an object that is rebuilt per intervention by design.

## Consequences

- Scaling the agents means scaling the API container; there is no per-agent quota or endpoint.
  For a system whose every write waits for a human, that is the right granularity.
- An external party cannot call a specialist by name through the Foundry endpoint. The one
  specialist that should be callable from outside, Diagnostic, is exposed through A2A by this
  repository (ADR-006), read-only and behind Entra.

## Revisit when

The hosted service offers middleware, approvals and checkpoints with the same guarantees. The
agents would then move with their prompts, and the tools would stay local.
