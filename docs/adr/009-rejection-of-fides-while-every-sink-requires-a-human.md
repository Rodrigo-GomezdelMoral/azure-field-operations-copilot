# ADR-009 · Rejection: FIDES information-flow control, while every sink requires a human

**Status:** rejected, revisit · **Date:** 2026-10-20

## Context

FIDES is the information-flow control model for agent systems that Microsoft Agent Framework
exposes as an experimental feature: every piece of data an agent reads carries a label (its
source and trust level), the labels propagate through the conversation, and a policy decides
whether a tool call whose arguments carry a low-trust label may reach a sensitive sink. It is the
principled answer to the central threat of this repository — a manual passage, an inventory
response or the text in a photograph instructing an agent to reserve parts or create an order —
and the question is whether to adopt it.

## Decision

Not now. Three reasons, in order of weight:

- **Every sensitive sink already requires a human.** `reserve_parts` and `create_work_order` carry
  `approval_mode="always_require"`; an injected instruction can at most *propose* an action, which
  a supervisor who is not the requester then reads with its arguments. FIDES would decide
  automatically what a person already decides; it would not remove a step, it would duplicate it.
- **The measurement already exists.** The injection proposal rate in `eval/run.py` counts how
  often planted text reaches a tool-call argument (the canary `ZEBRA-7731`), across the three
  channels. If that rate stays above zero after prompt work, labels are the next lever, and the
  dataset that would prove they help is already written.
- **It is experimental.** The feature is marked as such in the framework; adopting it here would
  put the repository's central guarantee on an API that may change, when the guarantee is
  currently carried by one decorator, one middleware and one test.

## Consequences

- The authorisation model stays explainable in one sentence: no write without a human approval,
  the approver is not the requester, the approval survives a restart.
- The injection suite keeps measuring what the gate would otherwise hide: on the first smoke run,
  the inventory-channel injection did make the Parts agent *propose* the canary, and the approval
  gate was the only thing between that proposal and a reservation (`docs/evaluation.md`).

## Revisit when

A write must run **unattended** — a reservation below a value threshold, a work order for a
recurring fault — so that the human leaves the loop for some sink. At that point the label
propagation is what makes an unattended sink defensible, and this ADR is superseded.
