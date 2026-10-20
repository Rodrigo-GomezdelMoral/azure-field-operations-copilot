# Industrial Field Operations Copilot

Four specialist agents on Microsoft Agent Framework prepare a maintenance intervention from a
technician's fault report or photograph: the manual section, the asset's history, similar
resolved cases, the parts in stock and a drafted work order. What makes it an enterprise system
rather than a demo: **no write action executes without a human approval, the approver is not the
requester, the approval survives a process restart, and every decision is auditable.** An agent
with tools is a privileged component; this repository is the control plane that makes it safe.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/Rodrigo-GomezdelMoral/azure-field-operations-copilot)
**Live demo:** <https://rodrigo-gomezdelmoral.github.io/azure-field-operations-copilot/> — three
recorded interventions replayed with their real timings, approvals included, no backend.

[![ci](https://github.com/Rodrigo-GomezdelMoral/azure-field-operations-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Rodrigo-GomezdelMoral/azure-field-operations-copilot/actions/workflows/ci.yml)
[![eval](https://github.com/Rodrigo-GomezdelMoral/azure-field-operations-copilot/actions/workflows/eval.yml/badge.svg)](https://github.com/Rodrigo-GomezdelMoral/azure-field-operations-copilot/actions/workflows/eval.yml)

## The problem

Asset maintenance companies in energy, transport and manufacturing send technicians to equipment
they do not know by heart, and preparing one intervention — the right manual section, the asset's
history, whether the part is in stock, the work order — takes thirty to forty-five minutes of a
qualified technician. At a hundred interventions a day that is several full-time equivalents a
year, and the quality of the preparation varies with whoever is on shift. The buyer is the head
of maintenance operations; what they buy is that time back, with a procedure cited from the
manual and nothing reserved or ordered that a supervisor has not seen. A copilot that reserves
parts on its own is not a saving, it is a liability.

## Architecture

```mermaid
graph LR
    T["Technician's phone"] --> WEB["ca-fopweb · proxy with managed identity"]
    WEB -->|"Entra token · Copilot.Use"| API["ca-fopapi · one handoff workflow per intervention"]
    API --> WF["Triage → Diagnostic → Parts → WorkOrder"]
    WF -->|"MCP, read-only"| MCP["ca-fopmcp · internal ingress only"]
    WF --> CU["Content Understanding · photograph → damage fields"]
    WF --> PROJ["Foundry project (shared) · gpt-5-mini, gpt-5-nano"]
    WF --> SRCH[("AI Search (shared) · manuals")]
    WF --> COS[("Cosmos DB · interventions, checkpoints, audit, case memory")]
    API -->|"ApprovalRequested"| EG["Event Grid"]
    EXT["Field-service system"] -->|"A2A · Copilot.Diagnose"| A2A["ca-fopa2a · DiagnosticAdvisor, read-only"]
```

The two write tools, `reserve_parts` and `create_work_order`, are local tools with
`approval_mode="always_require"`. A run stops at the approval, the checkpoint lives in Cosmos,
and a supervisor who did not open the intervention answers it from any replica; the tool then
runs exactly once. `docs/architecture.md` has the container table, the sequence diagram of an
approval across a restart, and the handoff graph below as the framework generated it:

```mermaid
flowchart TD
  Triage["Triage (Start)"];
  Diagnostic["Diagnostic"];
  Parts["Parts"];
  WorkOrder["WorkOrder"];
  Triage --> Diagnostic;
  Triage --> Parts;
  Triage --> WorkOrder;
  Diagnostic --> Triage;
  Diagnostic --> Parts;
  Diagnostic --> WorkOrder;
  Parts --> Triage;
  Parts --> Diagnostic;
  Parts --> WorkOrder;
  WorkOrder --> Triage;
  WorkOrder --> Diagnostic;
  WorkOrder --> Parts;
```

`WorkflowViz(workflow).to_mermaid()` draws the framework's full mesh; which handoffs an agent can
actually take is fixed by the handoff tools it holds — Triage to Diagnostic or Parts, Diagnostic
to Parts or WorkOrder, Parts to WorkOrder or back to Diagnostic, WorkOrder to nobody
(`app/workflow.py`).

## What this demonstrates

| Capability | Where |
|---|---|
| Four agents in a `HandoffBuilder` workflow, instructions as versioned files, one workflow per intervention named after it | `app/agents.py`, `app/workflow.py`, `prompts/` |
| Tools with `approval_mode="always_require"`, a policy middleware that rejects before execution, a create-only audit middleware | `app/tools.py`, `app/middleware.py` |
| Durable approvals: `CosmosCheckpointStorage`, `request_info` events, resume by the intervention's name on any replica | `app/workflow.py`, `app/main.py`, ADR-002 |
| Separation of duties checked before any checkpoint is loaded; a trusted proxy forwards the signed-in user, nobody else can | `app/main.py` (`authorise`, `principal`), `web/server.ts`, ADR-007 |
| A read-only inventory MCP server on the official SDK, internal ingress only; writes never over MCP | `mcp_inventory/server.py`, ADR-005 |
| A read-only Diagnostic agent exposed over A2A with its own app role | `a2a_server/main.py`, ADR-006 |
| Photographs analysed by a Content Understanding analyzer created as code; case memory as a Cosmos vector context provider | `ops/analyzer.py`, `app/memory.py`, ADR-004 |
| Manuals indexed as configuration by the search service's own identity, Document Intelligence layout, quantised vectors | `ops/index.py` |
| An evaluation harness that drives real interventions, answers approvals, measures approval compliance, injection proposals, unnecessary steps and citation precision, calibrates the judge | `eval/`, `docs/evaluation.md` |
| A mobile-first interface with a live agent trace, the approval card for supervisors and the drafted work order | `web/src/main.tsx` |
| Quality gate, evaluation gate with a pull-request comment, canary deployment with rollback, static demo | `.github/workflows/` |
| Eleven architecture decisions, two of them rejections | `docs/adr/` |

## Quick start

With Python 3.12 and Node 22 (the Codespace has both), against the deployed Azure resources with
your own login:

```bash
make install
cp .env.example .env        # fill the endpoints from `azd env get-values`; REQUIRE_AUTH=false
make mcp                    # the read-only inventory MCP server on :8020
make run                    # the API on :8000
make web                    # the frontend through the same proxy the container runs, on :8080
```

With `REQUIRE_AUTH=false` the API takes the acting person from the `x-demo-user` header — the
frontend's persona selector sets it — so one browser can open an intervention as the technician
and approve it as the supervisor; the separation-of-duties check still applies to the two
identities. `make check` runs ruff, mypy and the tests, including the budget test;
`make a2a` starts the A2A server on :8010 and `make smoke` runs the ten-case evaluation.

## Deploy

```bash
azd up
```

One command provisions `rg-fopcopilot-prod-swc` from `infra/` and deploys the four containers and
three jobs. The resource group must exist, the landing zone must be deployed and its outputs
imported with `make lz-env`, and the bootstrap below must have been run once. Then `make seed`
(or the job `caj-fopseed`) loads the catalogue and creates the analyzer, and `make index` (or
`caj-fopindexer`) builds the `manuals` index.

### Bootstrap, once per tenant

1. **The app registration and its roles.** Create an app registration named `api-fopcopilot-prod`,
   expose it as `api://<client id>`, set `requestedAccessTokenVersion` to `2`, and define three app
   roles: `Copilot.Use` (applications: callers of the API), `Copilot.Diagnose` (applications:
   callers of the A2A server) and `supervisor` (users: people who may approve). Store the client
   id as `API_APP_CLIENT_ID` in the azd environment and as a repository variable, with
   `API_AUDIENCE=api://<client id>`.
2. **Grant the roles.** After `azd up` has created the identities, assign `Copilot.Use` to
   `id-fopweb` through Microsoft Graph (`servicePrincipals/{api}/appRoleAssignedTo`), assign
   `Copilot.Diagnose` to the field-service system's identity, and assign `supervisor` to the people
   who approve. The web container's `PROXY_PRINCIPAL_ID` is set by Bicep to `id-fopweb`, so the API
   trusts the signed-in user the proxy forwards from it and from nobody else.
3. **The deployment principal.** `gh-azure-field-operations-copilot` holds Contributor on this
   resource group and Role Based Access Control Administrator on this and the shared group; it
   also needs Contributor on the shared registry (for `az acr build`), Azure AI User on the shared
   project and Cognitive Services OpenAI User on the shared Foundry account (the judge's graders
   call the model as the caller), Search Index Data Reader on the search service and the Cosmos
   SQL data contributor role on the account (the evaluation runs real interventions).
4. **Repository configuration.** Secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
   `AZURE_SUBSCRIPTION_ID`; variables `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_ACCOUNT_ENDPOINT`,
   `SEARCH_ENDPOINT`, `COSMOS_ENDPOINT`, `MANUALS_CONTAINER_URL`, `API_AUDIENCE`,
   `API_APP_CLIENT_ID`; an environment named `production`; GitHub Pages set to deploy from Actions.

### Federated credentials

The deployment principal needs **three** federated credentials, and each workflow must present a
subject that matches one of them exactly:

| Subject | Used by |
|---|---|
| `repo:<owner>@<owner id>/<repo>@<repository id>:pull_request` | `eval.yml` on pull requests |
| `repo:<owner>@<owner id>/<repo>@<repository id>:ref:refs/heads/main` | `eval.yml` on its weekly schedule and manual runs from `main` |
| `repo:<owner>@<owner id>/<repo>@<repository id>:environment:production` | `deploy.yml`, which declares `environment: production` |

The numeric ids are GitHub's *immutable subject*, sent by repositories created after 15 July 2026
and shown by `gh api repos/<owner>/<repo>/actions/oidc/customization/sub`; a credential in the
older name-only form does not match. `AADSTS700213` (*no matching federated identity record found
for presented assertion subject*) means the subject GitHub sent is not in that table: read it in
the error message and add it, do not widen an existing one.

### The approval event

When a run stops for an approval the API publishes a CloudEvent to the Event Grid topic; the
subscriber (a Teams card, a paging system) is out of scope and would be a subscription on that
topic:

```json
{
  "specversion": "1.0",
  "type": "FieldOps.ApprovalRequested",
  "source": "/fieldops/api",
  "data": { "intervention_id": "<id>", "tool": "reserve_parts", "agent": "Parts" }
}
```

## Evaluation

Smoke suite of 2026-10-19, ten interventions driven live with the Foundry judge on
(`docs/evaluation.md` has the case-by-case reading):

| Metric | Value | Gate |
|---|---|---|
| **Approval compliance** | **1.00** | = 1.00 |
| Task success | 0.60 | ≥ 0.85 |
| Tool call accuracy (judge) | 0.54 | ≥ 0.90 |
| Injection proposal rate | 0.33 | = 0 |
| Unnecessary step rate | 0.30 | ≤ 0.15 |
| Citation precision | 0.70 | ≥ 0.95 |

**Approval compliance is 1.00 on every run so far, and the Cosmos audit shows one execution per
privileged tool per intervention.** The merge gate is red and the repository says so: the
injection planted in an inventory response made the Parts agent *propose* the canary part — the
approval gate is what stopped it — and after a denial the agents retry the privileged call rather
than stop. The judge agrees with the thirty human-labelled transcripts at κ = 0.58 (task
adherence) and κ = 0.67 (tool call accuracy), so its scores are reported rather than trusted on
their own. `experiments/` measures handoff against sequential orchestration and the similar-cases
memory against no memory.

## Cost

Measured on 2026-10-20: this resource group has cost €0.0002 month to date because nothing in it
runs between interventions; the shared platform has cost €24.55, mostly the search service and the
model calls of every repository. An intervention costs **€0.014 in tokens**, measured from the
account's token metrics over eight interventions run alone (€0.042 when the judge's graders are
counted in); a thousand interventions cost about €20 to €45 all in. The production projection —
2,200 interventions a month, a Standard search tier, two warm replicas — is about €380 a month
(`docs/cost.md`).

## Identities and roles

| Identity | Roles |
|---|---|
| `id-fopapi` | Azure AI User on the shared project · Cognitive Services User and OpenAI User on the account · Search Index Data Reader · Cosmos SQL data contributor on `fieldops` · EventGrid Data Sender · Monitoring Metrics Publisher · AcrPull |
| `id-fopweb` | app role `Copilot.Use` on the API · Monitoring Metrics Publisher · AcrPull |
| `id-fopmcp` | Cosmos SQL data **reader** on `inventory` only · Monitoring Metrics Publisher · AcrPull |
| `id-fopa2a` | Azure AI User · Cognitive Services User and OpenAI User · Search Index Data Reader · Cosmos SQL data **reader** on `memory` and `assets` · Monitoring Metrics Publisher · AcrPull |
| `id-fopjobs` | Azure AI User · Search Service Contributor and Search Index Data Contributor · Storage Blob Data Contributor on `manuals` · Cosmos SQL data contributor · Monitoring Metrics Publisher · AcrPull |
| shared search service | Storage Blob Data Reader on `manuals` |
| `gh-azure-field-operations-copilot` | Contributor on this group · RBAC Administrator on both groups · Contributor on the shared registry · Azure AI User · Cognitive Services OpenAI User · Search Index Data Reader · Cosmos SQL data contributor |

**There is no secret anywhere in this system: no key, no connection string, no vault to keep them
in.** Every call is made with a managed identity or the developer's own login; storage, Cosmos,
Event Grid and Application Insights have key access disabled; the CI gate scans the full history
for emails and identifiers. `docs/security.md` maps every threat to the file and the test that
mitigate it.

## Decisions

| ADR | Decision |
|---|---|
| [001](docs/adr/001-handoff-over-the-other-orchestration-patterns.md) | Handoff over the other orchestration patterns |
| [002](docs/adr/002-checkpoints-over-a-queue-for-durable-approvals.md) | Checkpoints over a queue for durable approvals |
| [003](docs/adr/003-agents-in-code-rather-than-foundry-agent-service.md) | Agents in code rather than Foundry Agent Service |
| [004](docs/adr/004-cosmos-vector-memory-alongside-ai-search.md) | Cosmos vector memory alongside AI Search |
| [005](docs/adr/005-writes-never-over-mcp.md) | Writes never travel over MCP |
| [006](docs/adr/006-a2a-exposes-a-read-only-agent.md) | A2A exposes a read-only agent |
| [007](docs/adr/007-separation-of-duties.md) | Separation of duties |
| [008](docs/adr/008-create-only-audit-through-middleware.md) | Create-only audit through middleware |
| [009](docs/adr/009-rejection-of-fides-while-every-sink-requires-a-human.md) | Rejection: FIDES, while every sink requires a human |
| [010](docs/adr/010-rejection-of-the-durable-task-scheduler.md) | Rejection: Durable Task Scheduler |
| [011](docs/adr/011-app-role-authorisation-and-internal-ingress-instead-of-a-network-boundary.md) | App-role authorisation and internal ingress instead of a network boundary |

## Scope and simplifications

- **One plant, four asset families, four public-domain manuals** (US Department of Energy
  sourcebooks), a synthetic catalogue of 24 assets, 16 parts and 300 resolved cases
  (`ops/seed.py`). The conveyor family has no manual of its own and is diagnosed from the pump and
  motor sourcebooks.
- **Budgets, measured.** 61 tracked files against a ceiling of 62, where the specification's 48
  predates its mandated layout; 1,198 lines of Python for the application and operations code
  against the specification's 1,200, and 948 for the evaluation harness and tests against a
  ceiling of 950 that phase 7 raised from 700 when the harness alone measured 330; 449 lines of
  Bicep against 450; 469 of TypeScript against 700; 2 comments. `tests/test_budget.py` enforces
  each.
- **The deployed web runs in persona mode** (`ALLOW_PERSONAS=true`): its ingress is public and the
  proxy forwards the persona the browser chooses, so a visitor can play both the technician and
  the supervisor. With Entra authentication on the web container the same proxy forwards the
  signed-in user's object id and roles instead, and the API trusts nothing else.
- **The Event Grid subscriber is out of scope**; the event is published and its shape is above.
- **The search service lives in North Europe** while everything else is in Sweden Central, and its
  semantic ranker is on the free plan the landing zone chose; the manual search is hybrid (keyword
  and vector) without it.
- **The deployment workflow updates images with `az containerapp`** rather than `azd deploy`, so
  the canary revision and its traffic split are explicit; `azd up` remains the way to provision
  and deploy from a workstation.
- **Reasoning effort is low** on every model call; a routine intervention takes two to four
  minutes end to end and the interface shows the specialists working rather than hiding them.
