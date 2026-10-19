# CLAUDE.md — working agreement

`azure-field-operations-copilot` is the Industrial Field Operations Copilot: four specialist
agents on Microsoft Agent Framework that prepare an intervention from a fault description or a
photograph, propose parts and a work order, and **execute no write without a human approval that
survives a process restart and is given by someone other than the requester**. A staff engineer
reads it for ten minutes and must conclude the author builds agent systems an enterprise would let
near production. That depends on **restraint**: every framework feature used here replaces code
that would otherwise exist, and nothing is used to show it is known.

Two rules govern every choice:

> If a capability exists in the Azure service or in Microsoft Agent Framework, do not reimplement it.
>
> Every framework feature used here must replace code that would otherwise exist.

Re-read this file at the start of every phase.

## Process

- Do not stage, commit or push. The author commits at the end of each phase with the message
  printed in the phase summary, on a `feature/<words>` branch; `main` is protected and receives
  pull requests only.
- At the end of each phase stop and print:

  ```
  ── PHASE n COMPLETE ──
  Files: <n>/56   Python: <app>/1200 + <eval and tests>/700   Bicep: <n>/450   TS: <n>/700   Comments: <n>/25
  Verified: ruff ✓  mypy ✓  pytest ✓  budget ✓
  Commit with:
    git add <paths>
    git commit -m "<message>"
  Say "continue" for phase n+1.
  ```

- Every Agent Framework and Azure SDK name is verified against the installed package before it is
  written. The names below were verified on 2026-10-19 against the pinned versions in
  `requirements.txt`; the framework renamed many types before 1.0 (`ChatAgent` → `Agent`,
  `AIFunction` → `FunctionTool`, `@ai_function` → `@tool`, orchestration builders moved to
  `agent_framework.orchestrations`, middleware `call_next()` takes no argument), so code copied
  from older samples looks right and does not run.

## Non-negotiable constraints

1. **No identity leakage** anywhere, fixtures and commit messages included. Placeholders only.
2. **Zero secrets.** `DefaultAzureCredential` for every Azure call. No Key Vault.
3. **Size budget, enforced by `tests/test_budget.py`:** tracked files excluding `docs/`,
   `eval/datasets/`, `web/node_modules/` and `web/fixtures/` at most 56 (the specification says
   48; its own mandated layout — four workflows, three servers, a web app, infrastructure in
   modules — needs more, and the README records the count); the specification's 1,200 lines of
   Python apply to the application and operations code (`app/`, `ops/`, `mcp_inventory/`,
   `a2a_server/`), whose per-module targets it lists, and the evaluation harness and tests have
   their own ceiling of 700; ≤ 450 Bicep; ≤ 700 TypeScript; directory depth 3; functions ≤ 35
   lines.
4. **Comments.** No `#` comment may restate the code; fewer than 25 in the whole Python codebase.
   Type hints replace them.
5. **No defensive clutter.** No bare `except Exception`; ruff rule `BLE001` and the budget test
   both enforce it.
6. **Minimal dependencies.** `agent-framework-foundry`, `agent-framework-orchestrations`,
   `agent-framework-azure-cosmos`, `agent-framework-azure-contentunderstanding` and
   `agent-framework-a2a`, never the `agent-framework` metapackage; `fastmcp` for the inventory
   server; `a2a-sdk` for the agent card and routes.
7. **`targetScope = 'resourceGroup'`.** `rg-fopcopilot-prod-swc` exists; never create it.
8. **English** everywhere. Nothing unfinished.

## SDK reference — verified against the installed packages

| Purpose | Verified names |
|---|---|
| Agents | `agent_framework.Agent(client, instructions, name=, tools=, default_options=, context_providers=, middleware=)`; `await agent.run(messages, session=, options=)` → `AgentResponse` with `.value`, `.text`, `.usage_details` |
| Tools | `agent_framework.tool(func=None, *, name=, description=, schema=<BaseModel>, approval_mode="always_require")`; `tool(...)(bound_method)` for methods of a class holding clients; `FunctionTool` is the resulting type |
| Middleware | `agent_framework.FunctionMiddleware.process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]])`; a policy sets `context.result` and returns without calling `call_next()` |
| Context | `agent_framework.ContextProvider` with `before_run(...)`/`after_run(...)`; `SessionContext.extend_messages(...)`; `Message(role, [Content...])`, `Content.from_text(...)`, `Content.from_data(data=bytes, media_type=)` |
| Handoff | `agent_framework.orchestrations.HandoffBuilder(name=, participants=[...]).with_start_agent(a).add_handoff(source, [targets]).with_checkpointing(storage).with_termination_condition(fn).build()` → `Workflow`; `HandoffAgentUserRequest` with `.create_response(text)` |
| Workflow runs | `await workflow.run(message=None, *, stream=, responses={request_id: ...}, checkpoint_id=, checkpoint_storage=)`; events are `WorkflowEvent` with `.type` (`request_info`, `executor_invoked`, `executor_completed`, …), `.request_id`, `.data`; an approval request is a `Content` with `type == "function_approval_request"`, answered with `content.to_function_approval_response(approved)` |
| Checkpoints | `agent_framework_azure_cosmos.CosmosCheckpointStorage(container_client=, ...)`; the container partition key path is `/workflow_name` |
| Vision | `agent_framework_azure_contentunderstanding.ContentUnderstandingContextProvider(endpoint=, credential=, analyzer_id=, max_wait=)`; the analyzer is created by `ops/analyzer.py` with `azure.ai.contentunderstanding` |
| MCP | `agent_framework.MCPStreamableHTTPTool(name=, url=, load_tools=True, ...)` used as an async context manager and passed in `tools=`; `fastmcp.FastMCP` and `@mcp.tool()` on the server side |
| A2A | `agent_framework.a2a.A2AExecutor(agent, stream=False)`; `a2a.types.AgentCard`, `AgentSkill`, `AgentCapabilities`, `AgentInterface`; `a2a.server.request_handlers.DefaultRequestHandler`; `a2a.server.tasks.InMemoryTaskStore`; `a2a.server.routes.agent_card_routes.create_agent_card_routes`, `a2a.server.routes.jsonrpc_routes.create_jsonrpc_routes` |
| Foundry | `agent_framework.foundry.FoundryChatClient(project_endpoint=, model=<deployment>, credential=)`, `FoundryChatOptions`, `FoundryEvals(client=, evaluators=[...])` |
| Embeddings | `agent_framework.openai.OpenAIEmbeddingClient(model=, credential=, base_url=)` |
| Evaluation | `agent_framework.evaluate_workflow(*, workflow=, queries=, expected_output=, evaluators=[...])` → results with `sub_results`; `LocalEvaluator`, `@evaluator`, `tool_called_check`, `tool_call_args_match`, `ExpectedToolCall`, `raise_for_status()` |
| Visualisation | `agent_framework.WorkflowViz(workflow).to_mermaid()` |
| Events | `azure.eventgrid.aio.EventGridPublisherClient(endpoint, credential)` |

`model=` always takes the deployment name. The framework emits agent, tool and workflow spans and
token usage by itself; this repository adds only the `search` and `audit` spans.

## Architecture in one paragraph

`ca-fopweb` (external) proxies with its managed identity to `ca-fopapi` (external, Entra token with
the `Copilot.Use` app role). The API creates **one handoff workflow per intervention**, named after
it: `Triage` (with the Content Understanding provider for the photograph) hands off to
`Diagnostic` (manual search plus the similar-cases provider) or `Parts` (read-only inventory MCP
plus `reserve_parts`), and `Diagnostic` or `Parts` hand off to `WorkOrder` (`create_work_order`).
The two write tools require approval; the run stops at a `request_info` event, the checkpoint in
Cosmos survives the process, and a supervisor who is not the requester answers it from any instance.
`AuditMiddleware` writes every tool call and handoff with `create_item`; `PolicyMiddleware`
checks arguments before `reserve_parts` runs. `ca-fopmcp` has internal ingress only. `ca-fopa2a`
exposes the read-only Diagnostic agent to a field-service system over A2A with the
`Copilot.Diagnose` role.

## Phases

| # | Work | Commit message |
|---|---|---|
| 1 | `CLAUDE.md`, scaffold, tooling, `config.py`, `models.py`, `test_budget.py`, `docs/agent-spec.md` | `chore: scaffold project and define agent specification` |
| 2 | `infra/`: Cosmos with six containers and vector policy, Event Grid, Storage, Container Apps with ingress and roles, jobs, alerts, `azure.yaml` | `feat(infra): data plane, ingress model and role assignments` |
| 3 | `ops/seed.py`, `ops/index.py`, `ops/analyzer.py`, ADR-004 | `feat(knowledge): manuals index, case memory and damage analyzer` |
| 4 | `prompts/`, `clients.py`, `tools.py`, `mcp_inventory/`, ADR-005 | `feat(tools): field tools and read-only inventory mcp server` |
| 5 | `agents.py`, `memory.py`, `middleware.py`, ADR-003, ADR-008 | `feat(agents): four specialists with audit and policy middleware` |
| 6 | `workflow.py`, `main.py`, `telemetry.py`, ADR-001, ADR-002, ADR-007, ADR-011 | `feat(workflow): handoff orchestration with durable approvals` |
| 7 | `eval/`, five datasets, thresholds, `a2a_server/`, ADR-006 | `feat(eval): agent evaluation and read-only a2a exposure` |
| 8 | `web/`, workflows, `experiments/`, docs, remaining ADRs, README | `ci: quality gate, interface and portfolio documentation` |

## Definition of done

Budget green with actual counts · ruff, mypy, pytest clean · bicep clean and
`azd provision --preview` succeeds · `ca-fopmcp` has no external FQDN · the API rejects a request
without the app role · a test kills the process between approval request and response, resumes
from the checkpoint, and the privileged tool executes exactly once · a test proves a supervisor
cannot approve their own intervention · a test proves no privileged tool executes without an
approval record · the MCP server exposes no write tool · the handoff diagram was generated by
`WorkflowViz` · no Key Vault, no service key · no import from the metapackage · demo mode runs with
no backend · no email or GUID outside placeholders · no unfinished-work markers and no bare
`except Exception` · comment count under 25, reported · nothing committed or pushed. Then list
anything that could not be verified without a live deployment.
