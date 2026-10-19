# ADR-001 · Handoff over the other four orchestration patterns

**Status:** accepted · **Date:** 2026-10-19

## Context

Microsoft Agent Framework ships five orchestration patterns: sequential, concurrent, group chat,
magentic and handoff. Four specialists prepare an intervention: Triage reads the fault and the
history, Diagnostic reads the manual and the similar cases, Parts reads stock and proposes a
reservation, WorkOrder drafts the order. Two of them hold tools that pause for a human, and any
of them may need to ask the technician a question before continuing.

## Decision

`HandoffBuilder` (`app/workflow.py`), with the handoff table below and nothing else: one
specialist is active at a time and control transfers explicitly through a handoff tool the
framework generates on each source agent.

| From | May hand off to |
|---|---|
| Triage (start) | Diagnostic, Parts |
| Diagnostic | Parts, WorkOrder |
| Parts | WorkOrder, Diagnostic |
| WorkOrder | — |

The workflow terminates when WorkOrder confirms a created work order. Any other final response
without a handoff is a question to the technician, which the framework surfaces as a
`HandoffAgentUserRequest` and this repository persists as a pending request.

## Why not the others

- **Sequential** fixes the order Triage → Diagnostic → Parts → WorkOrder. Not every fault needs
  parts, and a known fault on a known asset can skip the diagnosis; the plan is not a line.
- **Concurrent** runs the specialists at once. The steps depend on each other: Parts needs the
  diagnosis, WorkOrder needs both. Parallelism would produce a reservation for a diagnosis that
  does not exist yet.
- **Group chat** adds a moderator that chooses who speaks. The problem has no open-ended
  discussion to moderate; the next specialist is determined by what the current one found, and
  the current one knows it best.
- **Magentic** plans dynamically with a manager and a ledger. The plan here is known in advance
  and small; a planner would add a model call per step and a layer of indirection a reviewer
  would have to read before trusting the system.
- **Handoff** is also the only pattern that is **interactive by default**: a specialist that ends
  its turn without handing off is asking the user, and the run pauses. That is exactly the
  behaviour the technician's question needs, and it comes without code.

## Consequences

- The handoff graph is data in one function; `WorkflowViz(workflow).to_mermaid()` renders it in
  `docs/architecture.md`, so the documentation cannot drift from the code.
- Each handoff is a function call and is therefore audited by `AuditMiddleware` like any tool
  (ADR-008).
- The termination condition is a predicate over the conversation, not a flag in a tool: it is
  visible, testable, and does not couple the tool to the orchestration.
- Experiment 001 compares this choice with a sequential pipeline on task success, step count and
  cost rather than taking it on faith.
