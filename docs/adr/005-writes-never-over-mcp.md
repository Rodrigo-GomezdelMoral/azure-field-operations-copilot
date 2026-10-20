# ADR-005 · Writes never travel over MCP

**Status:** accepted · **Date:** 2026-10-19

## Context

The Parts specialist needs the inventory: which catalogue numbers exist for an asset family,
what is in stock, and then a reservation. The inventory lives behind a Model Context Protocol
server (`mcp_inventory/`) because that is how a tool that belongs to another system should be
exposed to an agent: discoverable, typed, replaceable, and reachable from any framework. The
obvious extension is to put `reserve_parts` on the same server, next to the reads.

Two things stop that. First, the approval gate and the audit middleware of this repository wrap
**our** tools: `@tool(approval_mode="always_require")` on a function we own, `AuditMiddleware`
and `PolicyMiddleware` on the agent that calls it. A write exposed by a remote MCP server is
called through `MCPStreamableHTTPTool`, which is a different code path; the framework can still
gate it, but the guarantee then depends on configuration on both sides of a network boundary
instead of on one decorator in one file. Second, the MCP server runs under its own identity,
`id-fopmcp`, which holds the Cosmos data **reader** role on the `inventory` container and nothing
else. A write on that server would need a wider role on a component whose whole point is to have
no public surface and no privilege worth stealing.

## Decision

- The inventory MCP server, built on the official `mcp` SDK's `FastMCP`, exposes **read-only**
  tools: `find_parts` and `part_stock`. Its
  identity can read one container. `tests/test_tools.py` asserts that the server registers no
  tool whose name starts with a write verb and that the module never calls a Cosmos write method.
- `reserve_parts` and `create_work_order` are **local tools** of this repository
  (`app/tools.py`), bound methods of `FieldTools` with `approval_mode="always_require"`. They run
  under `id-fopapi`, the only identity with the data contributor role, inside the agent process
  where the approval request, the policy check and the audit record are produced by code this
  repository owns and tests.
- The MCP server has **internal ingress only** (`ca-fopmcp` in `infra/modules/apps.bicep`): it is
  reachable from the Container Apps environment and from nowhere else, so even a read has no
  public surface.

## Consequences

- An agent framework feature is used exactly where it replaces code: `MCPStreamableHTTPTool`
  replaces a bespoke inventory client. It is not used for the writes, where it would replace a
  guarantee with a configuration.
- A future inventory system with its own reservation API would be called from `reserve_parts`,
  behind the same gate, rather than exposed as a remote tool.
- The MCP server is a second process to run locally (`make mcp`) and a second container to
  deploy; the cost of the boundary is paid in operations, not in the authorisation model.

## Rejected

- **Reads and writes on the MCP server**, gated by the framework's remote-tool approval. It
  works; it moves the guarantee out of the repository's own tests.
- **No MCP server at all**, the inventory read as a local tool. Simpler, and it would hide the
  one integration pattern an enterprise actually asks about: how does an agent reach a system it
  does not own?
