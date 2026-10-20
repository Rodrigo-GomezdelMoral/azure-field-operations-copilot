# Security

An agent with tools is a privileged component. The boundary of this system is identity, not
network: every call to the API carries an Entra token with the `Copilot.Use` app role, every call
the agents make to Azure is made with a managed identity holding the narrowest role the service
offers, no write tool runs without a human approval given by someone other than the requester,
and the repository contains no secret of any kind — not in code, templates, fixtures, workflows
or history.

## Identities and roles

| Identity | Role | Scope | Declared in |
|---|---|---|---|
| `id-fopapi` | Azure AI User (Foundry User) | the shared Foundry project | `infra/modules/shared-access.bicep` |
| `id-fopapi`, `id-fopa2a` | Cognitive Services User, Cognitive Services OpenAI User | the shared Foundry account (Content Understanding analyzer, embeddings) | `infra/modules/shared-access.bicep` |
| `id-fopapi`, `id-fopa2a` | Search Index Data Reader | the shared search service | `infra/modules/shared-access.bicep` |
| `id-fopapi`, `id-fopjobs` | Cosmos DB Built-in Data Contributor (SQL role) | database `fieldops` | `infra/modules/data.bicep` |
| `id-fopapi` | EventGrid Data Sender | topic `evgt-fopcopilot-prod-swc` | `infra/modules/data.bicep` |
| `id-fopa2a` | Azure AI User; Cosmos DB Built-in Data **Reader** (SQL role) | the project; containers `memory` and `assets` only | `infra/modules/shared-access.bicep`, `infra/modules/data.bicep` |
| `id-fopmcp` | Cosmos DB Built-in Data **Reader** (SQL role) | container `inventory` only | `infra/modules/data.bicep` |
| `id-fopjobs` | Azure AI User; Search Service Contributor, Search Index Data Contributor; Storage Blob Data Contributor | the project; the search service; the `manuals` container | `infra/modules/shared-access.bicep`, `infra/modules/data.bicep` |
| `id-fopweb` | app role `Copilot.Use` on the API | the API's app registration | bootstrap step in the README (Graph app-role assignment) |
| all five identities | AcrPull; Monitoring Metrics Publisher | the shared registry; Application Insights | `infra/modules/shared-access.bicep`, `infra/modules/apps.bicep` |
| the shared search service's identity | Storage Blob Data Reader | the `manuals` container | `infra/modules/data.bicep` |
| `gh-azure-field-operations-copilot` (GitHub OIDC) | Contributor; Role Based Access Control Administrator; Contributor on the shared registry (`az acr build`); Azure AI User, Cognitive Services OpenAI User (the judge's graders), Search Index Data Reader, Cosmos SQL Data Contributor (the evaluation suite runs real interventions) | this resource group; both groups; the shared registry, project, account and search service; the Cosmos account | bootstrap step in the README |

No identity holds a role it does not need: the MCP server can read one container and write
nothing; the A2A server reads the manual, the registry and the case memory and writes nothing;
the web proxy can only ask the API; the API cannot touch the index definition or the blobs; the
jobs can rebuild the index and the catalogue but never approve anything, because approval is a
route, not a role.

## What a caller has to present

Container Apps rejects any request to `ca-fopapi` or `ca-fopa2a` without a valid Entra token for
`api://<client id>` with `401` at the ingress (`infra/modules/apps.bicep`, `authConfigs`; only
`/healthz` and the agent card are excluded). The code then validates the same token against the
tenant's keys and requires the app role — `Copilot.Use` on the API, `Copilot.Diagnose` on the A2A
server — returning `403` without it (`app/main.py` `verify_token`, `a2a_server/main.py`
`RoleGate`; `tests/test_main.py`, `tests/test_agents.py`).

The web proxy requests its token with its managed identity and forwards the signed-in user's
object id and app roles in `x-forwarded-user` and `x-forwarded-roles`; the API honours those
headers **only** when the token's object id is the proxy's own (`PROXY_PRINCIPAL_ID`), so a direct
caller holding `Copilot.Use` cannot name another user (`tests/test_main.py`,
`test_forwarded_identity_is_honoured_only_from_the_proxy_principal`). With `REQUIRE_AUTH=false`,
which only a local run sets, the `x-demo-user` header names the acting person instead.

### The authorisation boundary of a write

1. A write is one of two local tools, `reserve_parts` and `create_work_order`, declared with
   `approval_mode="always_require"` (`app/tools.py`). The run stops at a `request_info` event; the
   checkpoint in Cosmos holds the pending request; nothing has executed.
2. The response route authorises **before** it loads anything: the responder must hold the
   `supervisor` role and must not be the technician who opened the intervention
   (`app/main.py` `authorise`; `tests/test_main.py`
   `test_separation_of_duties_is_checked_before_any_checkpoint_is_loaded`,
   `test_responses_route_refuses_before_resuming`).
3. The decision is written to the audit container under the approver's identity, the latest
   checkpoint is loaded by the intervention's own name, and the workflow resumes on whichever
   replica received the request. The tool runs once (`tests/test_workflow.py`
   `test_approval_survives_a_restart_and_the_privileged_tool_runs_exactly_once`), or not at all
   on a denial (`test_no_privileged_tool_executes_without_an_approval`).
4. The evaluation suite measures the same property on real runs: approval compliance must be
   exactly 1.00 and `raise_for_status()` fails the run otherwise (`eval/run.py`
   `approval_compliance`; `tests/test_eval.py`).

## Threats and where each one is mitigated

| Threat | Mitigation | File · test |
|---|---|---|
| Injection from a manual passage (`search_manual` evidence instructs an agent to reserve or create) | evidence is returned inside a delimited block labelled untrusted; the prompts treat it as data and report it as suspicious; the privileged tools cannot run without a human; the injection suite plants such passages and counts any canary that reaches a tool call | `app/tools.py` (`EVIDENCE_START`), `prompts/diagnostic_v1.md`, `eval/run.py` (`PlantedTools`, `no_injection_proposal`) · `tests/test_tools.py` `test_search_manual_wraps_passages_as_untrusted_evidence…`, `tests/test_eval.py` `test_a_planted_passage_reaches_the_evidence_and_a_canary_proposal_is_caught` |
| Injection from an inventory response (the MCP result tells Parts to reserve a part) | the Parts prompt treats inventory text as data; `PolicyMiddleware` rejects any part not in the catalogue before the tool runs; the approval gate remains; the suite plants the instruction into the `find_parts` result and measured on the first run that it **did** make Parts propose the canary, which the gate stopped — the finding is recorded, not hidden | `prompts/parts_v1.md`, `app/middleware.py`, `eval/run.py` (`plant_inventory`) · `tests/test_agents.py` `test_policy_rejects_unknown_parts…`, `tests/test_eval.py` |
| Injection from text in a photograph (the analyzer's caption carries an instruction) | the Content Understanding provider adds the description as context the Triage prompt calls data; Triage has no write tool; the suite carries the caption channel | `app/agents.py` (`vision_provider`), `prompts/triage_v1.md`, `eval/datasets/tool_injection.jsonl` · `tests/test_agents.py` `test_agents_are_wired_with_the_right_tools…` |
| Injection from the case memory (a resolved case contains an instruction) | the similar-cases block is delimited, labelled untrusted and marked "cite nothing from here"; citation precision fails any procedure reference not retrieved from the manual in the same run | `app/memory.py`, `eval/run.py` (`citations_grounded`) · `tests/test_agents.py` `test_similar_cases_provider_adds_a_delimited_untrusted_block` |
| Tool misuse (an agent calls a tool it should not have, or with arguments outside policy) | each agent receives only its own tools and handoffs; quantities above the bound and unknown parts are rejected before execution and audited as `rejected` | `app/agents.py`, `app/middleware.py` · `tests/test_agents.py` (wiring, policy) |
| Privilege escalation through chained tools (Diagnostic steers Parts, Parts steers WorkOrder into a write) | every write still stops for the approval, whichever agent asked; the handoff tools an agent holds are fixed by the builder; the MCP server has no write tool and a read-only identity | `app/workflow.py`, `mcp_inventory/server.py`, `infra/modules/data.bicep` · `tests/test_workflow.py`, `tests/test_tools.py` `test_inventory_server_exposes_read_only_tools` |
| Exfiltration through a tool argument (data smuggled into `reserve_parts` or `create_work_order` arguments) | the only outbound writes are the two approved tools, whose arguments are typed pydantic models validated at the boundary and shown to the supervisor before anything runs; the A2A agent has no write tool at all | `app/models.py` (`PartLine`, `WorkOrderDraft`), `app/tools.py`, `a2a_server/main.py` · `tests/test_tools.py` `test_part_line_bounds`, `tests/test_agents.py` `test_a2a_exposes_the_read_only_advisor…` |
| Checkpoint tampering or replay (a forged continuation id, or a response to someone else's request) | the route authorises the caller against the intervention before reading any checkpoint; the request id must match the intervention's pending request; checkpoints are loaded by the intervention's own name from a container only `id-fopapi` can write; deserialisation is limited to the allowed types | `app/main.py` (`respond`, `authorise`, `CHECKPOINT_TYPES`), `infra/modules/data.bicep` · `tests/test_main.py` `test_responses_route_refuses_before_resuming` |
| Self-approval | the approver's object id must differ from the technician's; a supervisor who opened the intervention is refused | `app/main.py` (`authorise`) · `tests/test_main.py` `test_separation_of_duties…` |
| A write without a record | `AuditMiddleware` writes one create-only document per tool call and handoff whatever the outcome, and the module contains no update or delete call | `app/middleware.py` · `tests/test_agents.py` `test_audit_module_only_creates_records` |
| Anonymous or unauthorised access | Entra at the ingress, app role in the code, read-only role on the A2A server, internal ingress on the MCP server | `infra/modules/apps.bicep`, `app/main.py`, `a2a_server/main.py` · `tests/test_main.py`, `tests/test_agents.py` |
| A token in the browser | the frontend proxies server-side with its managed identity and forwards the signed-in user; a direct caller cannot impersonate | `web/server.ts`, `app/main.py` (`principal`) · `tests/test_main.py` `test_forwarded_identity…` |
| Secrets or identifiers in the repository | no key or connection string exists; gitleaks with email and GUID rules over the full history; fixture identifiers replaced by the placeholder | `.gitleaks.toml`, `.github/workflows/ci.yml`, `web/fixtures/` |
| Keys on storage, Cosmos, Event Grid or Application Insights | shared-key and local authentication disabled, Entra-only ingestion | `infra/modules/data.bicep`, `infra/modules/apps.bicep` |
| Vulnerable or tampered dependencies | exact pins for Python and npm, trivy and pip-audit in CI | `requirements.txt`, `web/package-lock.json`, `.github/workflows/ci.yml` |
| Runaway spend or a stuck approval | a monthly budget, scale limits, a 5xx alert and an alert when a pending request is older than four hours | `infra/modules/apps.bicep`, `app/telemetry.py` |
| A bad deployment | a canary revision of the API takes 10 % of traffic and is rolled back on an error-rate regression | `.github/workflows/deploy.yml` |

## What is not defended

A supervisor can approve a reservation the policy allows but the plant does not need; the
controls bound *what* can be reserved and *who* decides, not whether the decision is wise. A
model that follows an injected instruction without putting the canary into a tool call is caught
only by the judge or by a human reading the proposal. The public ingresses accept connections
from anywhere and refuse them cheaply; a web application firewall and a private network are
declined in ADR-011 with the condition under which they return. Pending requests do not expire
on their own (ADR-010).
