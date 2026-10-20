# Experiment 002 · Does the similar-cases memory earn its latency?

**Date:** 2026-10-19 · **Decision:** keep the `SimilarCasesProvider` on the Diagnostic agent ·
**Change under test:** the context provider replaced by one that adds nothing (`app/agents.py`,
`SimilarCasesProvider`), everything else identical

**Reports:** `eval/results/experiments-20261019T222059Z-handoff.json` (memory on) and
`eval/results/experiments-20261019T223548Z-handoff_no_memory.json` (memory off); the results
directory is not committed, the summaries are reproduced here.

## Hypothesis

`SimilarCasesProvider` embeds the fault, runs a Cosmos vector query for the five closest resolved
cases of the same equipment model and adds them to the Diagnostic agent's context as a
delimited, untrusted block (ADR-004). It costs one embedding call and one Cosmos query per
diagnosis, and it may bias the agent towards whatever fixed the asset last time. If diagnoses
without it name the expected cause as often and reach a work order as often, the provider is
latency without value and should go.

## Method

The first eight cases of `eval/datasets/tasks.jsonl` (two faults per family, one with a denied
reservation), driven by the evaluation harness exactly as `python -m eval.run` drives them —
approvals answered with the dataset's decision, the technician's answer given when an agent asks —
against the deployed index, catalogue and inventory server, with no other load on the model
deployments. Memory on ran 22:14–22:21 UTC, memory off 22:29–22:36 UTC, on the same evening,
with the same prompts and models (gpt-5-mini for Triage, Diagnostic and WorkOrder, gpt-5-nano for
Parts, reasoning effort low). The checks are the harness's own: the expected diagnosis keyword in
an agent's text, the work order created, every citation retrieved in the run.

Two caveats bound the result. **Eight cases, one run each**: a handoff workflow is not
deterministic, and one case moves every rate by 0.125. And the expected keyword is a proxy for
"the diagnosis is right": a diagnosis of *lubrication loss* for a fault the dataset labels
*bearing wear* counts as a miss although a technician would accept it.

## Results

| | Memory on | Memory off |
|---|---|---|
| Expected cause named in the diagnosis | **6 / 8** | 4 / 8 |
| Work order created | **6 / 8** | 4 / 8 |
| Every citation retrieved in the run | 8 / 8 | 7 / 8 |
| Approvals answered | 12 | 8 |
| Tool calls and handoffs per run (mean) | 12.3 | 12.8 |
| Wall time per run (mean) | 45.8 s | 47.4 s |
| Model cost per run (account token metrics, Retail Prices) | €0.014 | €0.009 |
| Runs that asked the technician instead of diagnosing | 1 (task-007, no drive manual found) | 2 (task-003 asked for a detail, task-007) |

Without the cases, two more runs ended in a question to the technician rather than a diagnosis,
and the Diagnostic agent searched more and cited one label it had not retrieved. With the cases,
the agent reached the cause the plant had seen before and moved to Parts; the two misses with
memory on are the same two faults the full-suite smoke misses — a belt that slips and a drive
that trips — where the manual's guidance is an adjustment and the agent does not name a part.

Latency is not a factor: the provider's embedding and vector query add well under a second to
runs of forty to sixty seconds, and the runs with memory were slightly *faster* because they
asked fewer questions. They cost more per run — €0.014 against €0.009 — because more of them
went all the way to a reservation and a work order, not because of the five cases in the context
(about 400 input tokens each).

## Decision

Keep the provider on the Diagnostic agent, as a user-role block that the prompt calls experience
rather than procedure; the citation check is what keeps it from being cited. The next measurement
is the full task suite with and without it, where sixty cases would make a two-case difference
meaningful; this eight-case run is enough to say it is not latency without value.
