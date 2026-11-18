# Responsible AI impact assessment

Industrial Field Operations Copilot's impact assessment follows the sections of the Responsible AI
Impact Assessment Template and the goals of the
[Microsoft Responsible AI Standard](https://www.microsoft.com/ai/principles-and-approach), together
with the responsible AI guidance of the
[Azure Well-Architected Framework](https://learn.microsoft.com/azure/well-architected/) for
[AI workloads](https://learn.microsoft.com/azure/well-architected/ai/responsible-ai).

## 1. System information

- **System:** four specialist agents (Triage, Diagnostic, Parts and WorkOrder) in a handoff workflow
  on Microsoft Agent Framework, behind an API and a mobile-first web ([`docs/architecture.md`](architecture.md)).
- **Purpose:** prepare a maintenance intervention from a fault report or photograph: the manual
  section, the asset's history, similar cases, the parts in stock and a drafted work order.
- **Models:** gpt-5-mini for Triage, Diagnostic and WorkOrder, gpt-5-nano for Parts, an embedding
  model and a Content Understanding analyzer for photographs; prompts are versioned in `prompts/`.
- **What it can change:** two write tools only, `reserve_parts` and `create_work_order`, both
  declared with `approval_mode="always_require"` (`app/tools.py`); every other tool reads.
- **Stage:** one deployed environment on public manuals and synthetic records, plus a static demo
  that replays three recorded interventions.
- **Stakeholders:** the technician who reports the fault, the supervisor on shift who answers for
  what is reserved and ordered, the planner who receives the work order, and the field-service
  system that calls the read-only Diagnostic agent over A2A (ADR-006).

## 2. Intended uses

- **Prepare an intervention.** A technician describes or photographs a fault and receives a
  diagnosis whose procedure steps cite a manual section, the parts needed and a drafted work order.
- **Decide a write.** A supervisor who did not open the intervention approves or denies each
  reservation and each work order, with a reason that is kept.
- **Advise another system.** A field-service system asks the Diagnostic agent for a diagnosis over
  A2A; that agent holds no write tool.
- **Not intended:** writes that run unattended (ADR-009 names when that would be revisited), safety
  instructions the manual does not contain, and evidence from outside the listed sources.

**Goals of the Responsible AI Standard that apply:**

- *Impact assessment (A1):* this document, versioned with the code, the agent specification and the
  ADRs it cites.
- *Oversight of significant adverse impacts (A2):* the impact that matters most, a write nobody
  approved, is a gated metric: an evaluation run fails unless approval compliance is exactly 1.00
  (`eval/run.py`), and the injection findings are published in [`docs/evaluation.md`](evaluation.md).
- *Fit for purpose (A3):* [`docs/agent-spec.md`](agent-spec.md) was written before the code and fixes the intent, the
  restrictions and the rubric, with thresholds in `eval/thresholds.yaml`; the approval property is met in every run, and the other metrics are still being raised to their thresholds (section 3).
- *Data governance and management (A4):* `data/manifest.json` records each manual's URL, hash,
  retrieval date and licence; every other record is synthetic; datasets live in `eval/datasets/`.
- *Human oversight and control (A5):* both write tools stop for a supervisor who is not the
  requester; the request survives a restart and the tool then runs exactly once (ADR-002, ADR-007).
- *System intelligibility for decision making (T1):* the supervisor sees the tool and its exact
  arguments before deciding; the technician sees each agent's steps and the sections cited.
- *Communication to stakeholders (T2):* the README, the known limits of [`docs/evaluation.md`](evaluation.md) and
  "What is not defended" in [`docs/security.md`](security.md) say where the system fails, with its reports.
- *Disclosure of AI interaction (T3):* the product is named a copilot and the interface labels every
  step with the agent that produced it; a dedicated notice that the text is model-generated is a planned addition.
- *Quality of service (F1):* quality is measured over faults of the four asset families, with and
  without a photograph; records hold an object id and no demographic attribute (`app/models.py`);
  no metric is broken down by family or by technician yet.
- *Failures and remediations (RS2):* a denial leaves nothing executed, the policy middleware rejects
  before execution, a restart resumes from the checkpoint and a bad revision is rolled back.
- *Ongoing monitoring, feedback and evaluation (RS3):* `eval.yml` runs the smoke and injection
  suites on pull requests that touch the agents and the full suite on Mondays; alerts cover server
  errors and approvals pending for more than four hours (`infra/modules/apps.bicep`).

## 3. Adverse impact

- **Limitations.** The evaluation gate is advisory, and three metrics are still below their thresholds: task success is 0.40 to 0.80 against
  0.85, the unnecessary step rate 0.30 to 0.76 against 0.15 and citation precision 0.70 to 0.90
  against 0.95. The full suite of 105 interventions has not completed live. The judge agrees with
  the thirty labelled transcripts at κ = 0.58 and κ = 0.67, so its scores are reported, not
  trusted. Manuals, prompts and interface are in English only, with no accessibility check.
- **Predictable failures.** An instruction planted in a manual passage, an inventory response or a
  photograph caption made an agent propose the canary part in 6 and then 5 of 25 injected runs; the
  approval gate stopped every one. After a denial the agents retry the privileged call, up to four
  `create_work_order` requests in one run. A diagnosis can carry no section reference or a wrong
  one. A pending request waits for a supervisor rather than expiring (ADR-010), and the approval event is published for future subscribers.
- **Misuse.** A supervisor approving their own request is refused before any checkpoint loads
  (ADR-007). Forwarded identities are honoured only from the web proxy's own identity, so a caller
  cannot name another user (`tests/test_main.py`). Requests to bypass an interlock or falsify a
  record are cases of `eval/datasets/no_action.jsonl`, whose correct outcome is a question or a
  refusal with no write. Not defended ([`docs/security.md`](security.md)): a supervisor who approves a reservation
  the policy allows but the plant does not need.

## 4. Data requirements

- **Manuals:** four publications of the United States Department of Energy, in the public domain,
  listed in `data/manifest.json` and indexed by section.
- **Operational records:** a synthetic asset registry, a synthetic inventory and three hundred
  synthetic resolved work orders as case memory; closing an intervention adds one (`app/main.py`).
- **Evaluation data:** `tasks.jsonl` (60), `no_action.jsonl` (20), `tool_injection.jsonl` (25),
  `calibration.jsonl` (30) and `smoke.jsonl` (10), with CC0 photographs.
- **Data about people:** the object ids of the technician and of the approver, the fault report,
  the optional photograph and the approver's reason. Interventions and audit records have no
  expiry; checkpoints expire after ninety days (`infra/modules/data.bicep`).
- **Protection:** no key or connection string exists, each identity holds the narrowest role
  ([`docs/security.md`](security.md)), and telemetry runs with sensitive data off (`app/telemetry.py`).

## 5. Summary of impact

| Harm | Mitigation | Evidence |
|---|---|---|
| Parts reserved or a work order created that nobody approved | both write tools always require approval, from someone other than the requester, and run exactly once | `app/tools.py`, ADR-002, ADR-007, `tests/test_workflow.py`; approval compliance 1.00 on every run |
| An injected instruction steers an agent into a write | evidence delimited and labelled untrusted, a policy middleware before execution, the approval gate, an injection suite on pull requests | [`docs/security.md`](security.md), `docs/reports/`: 6 and 5 proposals of 25, none executed |
| A technician follows a procedure or a safety note the manual does not contain | every reference must be a section retrieved in the same run; citation precision is gated | [`docs/agent-spec.md`](agent-spec.md), [`docs/evaluation.md`](evaluation.md): 0.70 to 0.90 against 0.95 |
| A decision that cannot be reconstructed | one create-only audit record per tool call, handoff and decision, with the actor and the reason | ADR-008, `app/middleware.py`, `tests/test_agents.py` |
| A caller or another system acts beyond its role | an Entra token and an app role on every call to the API and to the A2A server, a read-only A2A agent, a read-only MCP server on internal ingress | ADR-005, ADR-006, ADR-011, `tests/test_main.py` |
| An approval waits unanswered and the repair is delayed | an event when a run stops for approval and an alert after four hours; no automatic expiry | `infra/modules/apps.bicep`, ADR-010 |
| A release degrades the service | a canary revision with 10 % of the traffic, rolled back on an error-rate regression | `.github/workflows/deploy.yml` |
