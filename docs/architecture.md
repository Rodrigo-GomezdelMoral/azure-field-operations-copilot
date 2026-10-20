# Architecture

Four specialist agents on Microsoft Agent Framework prepare a maintenance intervention from a
technician's fault report or photograph: the manual, the asset's history, similar resolved cases,
the parts in stock and a drafted work order. The architecture is a **control plane for agents with
tools**: every write is a local tool behind a human approval that survives a process restart, the
approver is never the requester, and every tool call and handoff is written to an append-only
audit container before the result is used.

## Containers

```mermaid
graph LR
    T["Technician's phone"] --> WEB["ca-fopweb<br/>Node proxy + static app<br/>identity: id-fopweb"]
    WEB -->|"Entra token · Copilot.Use"| API["ca-fopapi<br/>FastAPI · one handoff workflow per intervention<br/>identity: id-fopapi"]
    API --> WF["HandoffBuilder workflow<br/>Triage · Diagnostic · Parts · WorkOrder"]
    WF -->|"MCPStreamableHTTPTool"| MCP["ca-fopmcp · internal ingress only<br/>read-only inventory<br/>identity: id-fopmcp"]
    WF --> CU["Content Understanding analyzer<br/>damageTriageV1"]
    WF --> PROJ["Foundry project (shared)<br/>gpt-5-mini · gpt-5-nano · embeddings"]
    WF --> SRCH[("Azure AI Search (shared)<br/>index manuals · 720 section chunks")]
    WF --> COS[("Cosmos DB fieldops<br/>interventions · checkpoints · audit<br/>memory (vector) · assets · inventory")]
    API -->|"ApprovalRequested"| EG["Event Grid topic"]
    EXT["Field-service system"] -->|"A2A · Entra · Copilot.Diagnose"| A2A["ca-fopa2a<br/>DiagnosticAdvisor, read-only<br/>identity: id-fopa2a"]
    A2A --> SRCH
    A2A --> COS
    BLOB[("Blob manuals<br/>4 DOE sourcebooks")] --> IDXR["indexer + skillset<br/>Document Intelligence layout"] --> SRCH
    JOBS["caj-fopseed · caj-fopindexer · caj-fopeval<br/>identity: id-fopjobs"] --> BLOB
    JOBS --> COS
```

| Component | Runs | Identity | What it may touch |
|---|---|---|---|
| `ca-fopweb` | `web/server.ts` serving `web/dist` and proxying `/v1/*` with a token for `api://<client id>` | `id-fopweb` | the API only |
| `ca-fopapi` | `app/main.py` on uvicorn, external ingress, Entra authentication required at the ingress and the `Copilot.Use` app role in the code, multiple revisions for the canary | `id-fopapi` | the Foundry project and account, the search index (reader), the `fieldops` database (data contributor), the Event Grid topic (sender), Application Insights |
| `ca-fopmcp` | `python -m mcp_inventory.server`, **internal ingress only** | `id-fopmcp` | the `inventory` container (reader) |
| `ca-fopa2a` | `uvicorn a2a_server.main:app`, external ingress, Entra required, `Copilot.Diagnose` checked in the code | `id-fopa2a` | the project and account, the search index (reader), `assets` and `memory` (reader) |
| `caj-fopseed`, `caj-fopindexer`, `caj-fopeval` | `ops.seed`, `ops.index`, `eval.run --suite full` (Mondays 06:00 UTC) | `id-fopjobs` | the `manuals` container (blob contributor), the search service (contributor), Cosmos (data contributor), the project |
| shared search service | indexer, skillset, index projection | its own system identity | the `manuals` container (blob reader), the embedding deployment through the Foundry account |

Everything shared — the Foundry account and project, the model deployments, the search service,
the container registry, Log Analytics, the action group — is created by `azure-ai-landing-zone` and
referenced through the `landingZone` parameter. This repository creates its own resource group's
resources only: five identities, storage, Cosmos, Event Grid, Application Insights, the Container
Apps environment, four apps, three jobs, two alerts, a budget, and every role assignment,
including the ones on shared resources (`infra/modules/shared-access.bicep`).

## The handoff graph, as the framework sees it

Generated with `WorkflowViz(workflow).to_mermaid()` from the workflow `app/workflow.py` builds
(`tests` build the same workflow with a scripted model):

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

The framework wires every participant to every other at the executor level and routes through its
handoff coordinator; **which handoffs an agent can actually take is decided by the handoff tools it
is given**, and that is where this repository restricts the graph (`HandoffBuilder.add_handoff` in
`app/workflow.py`, asserted by `tests/test_eval.py` through the tool definitions the evaluation
reads from the built workflow):

| Agent | Model | Handoff tools | Own tools | Context providers |
|---|---|---|---|---|
| Triage (start) | gpt-5-mini | `handoff_to_Diagnostic`, `handoff_to_Parts` | `asset_history` | Content Understanding (`damageTriageV1`) |
| Diagnostic | gpt-5-mini | `handoff_to_Parts`, `handoff_to_WorkOrder` | `search_manual` | similar resolved cases (Cosmos vector search) |
| Parts | gpt-5-nano | `handoff_to_WorkOrder`, `handoff_to_Diagnostic` | `find_parts`, `part_stock` (MCP, read-only), `reserve_parts` (approval) | — |
| WorkOrder | gpt-5-mini | none; the run ends when its message carries the work-order number | `create_work_order` (approval) | — |

Every agent carries the same two middlewares: `AuditMiddleware` (one `create_item` per tool call
and handoff) and `PolicyMiddleware` (catalogue and quantity bound before `reserve_parts` runs).

## An approval across a process restart

```mermaid
sequenceDiagram
    participant T as Technician (browser)
    participant W as ca-fopweb
    participant A1 as ca-fopapi · replica 1
    participant C as Cosmos DB
    participant S as Supervisor (browser)
    participant A2 as ca-fopapi · replica 2
    participant E as Event Grid
    T->>W: POST /v1/interventions {asset_id, description, photo}
    W->>A1: same + Bearer (Copilot.Use) + forwarded user
    A1->>C: create intervention {technician_id = oid}
    A1->>A1: HandoffBuilder workflow · Triage → Diagnostic → Parts
    A1-->>W: SSE: executor_invoked, output (tool calls, text), handoff_sent …
    A1->>A1: Parts calls reserve_parts → approval_mode="always_require"
    A1->>C: checkpoint with the pending request_info (CosmosCheckpointStorage)
    A1->>C: intervention.status = pending_approval, pending = {request_id, tool, arguments}
    A1->>E: CloudEvent FieldOps.ApprovalRequested
    A1-->>W: SSE: status {pending_approval}
    Note over A1: the replica is killed, scales to zero, or is replaced by a deployment
    S->>W: POST /v1/interventions/{id}/responses {request_id, approved: true, reason}
    W->>A2: same + Bearer + forwarded user (supervisor role)
    A2->>C: read intervention
    A2->>A2: authorise(): supervisor role, and oid ≠ technician_id — before any checkpoint is read
    A2->>C: audit {outcome: approved, actor: supervisor}
    A2->>C: list_checkpoints(workflow_name = intervention id) → newest with a pending request
    A2->>A2: workflow.run(responses={request_id: approval}, checkpoint_id, checkpoint_storage)
    A2->>C: reserve_parts runs once · audit {outcome: executed}
    A2-->>W: SSE: Parts → WorkOrder → create_work_order → second approval …
```

`tests/test_workflow.py` is this diagram as a test: it stops after the approval request, builds
a second runtime from the checkpoint, answers, and asserts that the privileged tool ran exactly
once and that nothing ran when the answer was a denial.

## The authorisation boundary

There is no virtual network. What a caller must present is an Entra token for the API's app
registration carrying the `Copilot.Use` app role (`infra/modules/apps.bicep`, `authConfigs`;
`app/main.py`, `verify_token`). The web proxy requests that token with its managed identity and
forwards the signed-in user's object id and roles (`web/server.ts`); the API honours those headers
only when the token belongs to the proxy's own identity (`PROXY_PRINCIPAL_ID`), so a direct caller
cannot impersonate anyone. Every route authorises the caller against the intervention **before** a
checkpoint is loaded; the continuation identifier is never trusted on its own. The MCP server has
no public address; the A2A server exposes a read-only agent with its own role (ADR-006, ADR-011).

## Environments

`azd up` provisions `rg-fopcopilot-prod-swc` from `infra/` and deploys the four containers; the
Bicep is `targetScope = 'resourceGroup'` and never creates the group. Locally, `make run`,
`make mcp` and `make a2a` start the three Python servers against Azure with the developer's own
login (`DefaultAzureCredential`) and `REQUIRE_AUTH=false`, in which case the `x-demo-user` header
names the acting technician or supervisor; `make web` serves the frontend through the same proxy
the container runs. `VITE_DEMO_MODE=true` builds the static demo published on GitHub Pages, which
replays the recorded interventions in `web/fixtures/` with their real timings and never calls a
backend.
