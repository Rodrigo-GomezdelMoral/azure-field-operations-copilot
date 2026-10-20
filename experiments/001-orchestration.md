# Experiment 001 · Handoff against sequential orchestration

**Date:** 2026-10-19 · **Decision:** keep `HandoffBuilder` (ADR-001) · **Change under test:** the
same four agents, tools and prompts built with `SequentialBuilder` in the fixed order
Triage → Diagnostic → Parts → WorkOrder, first with the default chaining and then with
`chain_only_agent_responses=True`

**Reports:** `eval/results/experiments-20261019T222059Z-handoff.json`,
`experiments-20261019T222929Z-sequential.json`, `experiments-20261019T224404Z-sequential.json`
(the results directory is not committed; the figures are reproduced here)

## Hypothesis

ADR-001 chose the handoff pattern because an intervention does not always need every specialist:
a repeat fault with a known part can skip Diagnostic, a diagnosis that needs no part can skip
Parts, and a question from any specialist should pause the run where it is. The price is that
the agents decide the route, and the smoke suite shows them paying it — Parts handing back to
Diagnostic and Diagnostic handing forward again before anything is reserved. A sequential
pipeline removes that freedom: four turns, no handoff tools, every agent exactly once. If it
reaches the work order as often with fewer steps and fewer tokens, the handoff is a cost without
a benefit for the routine fault, which is most of the volume.

## Method

The first eight cases of `eval/datasets/tasks.jsonl` (two faults per family; one with a denied
reservation), driven by the evaluation harness exactly as `python -m eval.run` drives them,
against the deployed index, catalogue and inventory server, with nothing else running on the
model deployments. The sequential variant is the one line

```python
SequentialBuilder(
    name=intervention.id,
    participants=[triage, diagnostic, parts, workorder],
    checkpoint_storage=storage,
    chain_only_agent_responses=True,
).build()
```

in place of `create_workflow`; the agents, their tools, middlewares, providers and
`require_per_service_call_history_persistence=True` are the production ones from
`app/agents.py`. Steps are tool calls plus handoffs; cost is read from the Foundry account's
`InputTokens`/`OutputTokens` metrics over each variant's window at the Retail Prices in
`app/config.py`; success is the harness's own check (expected cause named, work order created,
expected fields).

## Results

| | Handoff (production) | Sequential, default chaining | Sequential, agent responses only |
|---|---|---|---|
| Runs completed | **8 / 8** | 2 / 8 | 0 / 8 |
| Work order created | 6 / 8 | 1 / 8 (one `create_work_order`, no diagnosis before it) | — |
| Expected cause named | 6 / 8 | 0 / 8 | — |
| Every citation retrieved | 8 / 8 | — | — |
| Steps per run (mean) | 12.3 | 0.5 | — |
| Wall time per run (mean) | 45.8 s | 108 s, mostly spent failing | — |
| Model cost per run | €0.014 (mini 284,708 in / 20,377 out; nano 144,934 / 18,288 for the eight) | not measurable | not measurable |
| Failure | — | 6 × `400 No tool call found for function call output with call None` | 5 × the same `400`, 3 × `Model deployment rate limit exceeded` |

The sequential pipeline **does not run** with these agents. When a participant that has called a
tool hands its conversation to the next participant, the Responses API rejects the request
because the function-call outputs arrive without the function calls they answer; with
`store=False` (`app/clients.py`) there is no server-side history to resolve them against.
Chaining only the agents' responses did not remove the error, which means it also arises inside
a single participant's own turn in this pattern, and the larger first message each participant
now sends — the whole conversation so far, every time — hit the deployment's tokens-per-minute
quota on three of the eight runs even with nothing else running. The two runs that completed
under the default chaining did so by doing almost nothing: zero tool calls in one, a single
`create_work_order` without a diagnosis in the other.

The handoff workflow completed all eight. Its known weakness is visible in the steps: three runs
contain a `Parts → Diagnostic → Parts` round trip before the inventory is read, and two routine
faults went to WorkOrder without a reservation because the manual prescribes an adjustment, which
is where the two misses on the expected cause come from. Its cost, €0.014 per intervention, is
the figure `docs/cost.md` uses.

## Decision

Keep the handoff pattern; ADR-001 stands, now for a reason it did not have when it was written:
with tool-using agents, per-service-call history persistence and `store=False`, the sequential
pattern in this framework version cannot carry the tool-call history from one participant to the
next, and the experiment could not measure what it set out to measure. What *was* measured is the
handoff's step overhead — the Parts ↔ Diagnostic round trip — and that is a prompt problem, not an
orchestration problem: the next change is a Parts prompt that reads the inventory before it
considers handing back, measured on the same eight cases.

## Caveats

Eight cases, one run each, against a non-deterministic workflow; the handoff figures are
indicative and the full task suite is the number to quote. The sequential failure is reproducible
(eleven of sixteen attempts, the other five being rate limits) and is reported as what the
framework did on 2026-10-19 with `agent-framework-core` 1.22.0 and `agent-framework-orchestrations`
1.3.2, not as a property of the pattern in general.
