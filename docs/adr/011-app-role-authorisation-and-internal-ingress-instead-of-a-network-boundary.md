# ADR-011 · App-role authorisation and internal ingress instead of a network boundary

**Status:** accepted · **Date:** 2026-10-19

## Context

The landing zone has no virtual network, no private endpoints and no private DNS zones, by a
platform decision recorded there: with public access disabled, the operator sits outside the
perimeter and cannot build an index or deploy from a workstation, and the private link estate
costs more per month than the workloads it would protect. This repository has four services with
very different exposure needs: a web frontend for people, an API that executes privileged tools,
an inventory server that should be reachable by one caller only, and an A2A endpoint for another
organisation's agent.

## Decision

Authorisation is **identity, not topology**, with one exception for the component that needs no
public surface at all.

| Service | Ingress | Who may call it |
|---|---|---|
| `ca-fopweb` | external, anonymous | people; it proxies to the API with its managed identity |
| `ca-fopapi` | external, **Entra required** at the ingress (`authConfigs`), `Copilot.Use` app role checked again in code | the web identity and any client holding the role |
| `ca-fopmcp` | **internal only** | callers inside the Container Apps environment; it has no public FQDN |
| `ca-fopa2a` | external, **Entra required**, `Copilot.Diagnose` app role | a field-service system's agent holding that role |

Both external APIs share one app registration whose two app roles name the two capabilities;
the token's audience is the registration and the role claim is the permission. Inside the API,
`principal()` validates the token a second time and `authorise()` applies the separation of
duties (ADR-007). Data-plane access is per identity and per container (`infra/modules/data.bicep`,
`shared-access.bicep`): the MCP identity reads `inventory` and nothing else, the A2A identity
reads `memory` and `assets`, only the API identity writes.

## Why

- **A role is a reviewable statement; a subnet is not.** "Holders of `Copilot.Diagnose` may call
  the A2A endpoint" can be read in the token, in Bicep and in the tests. "Callers from 10.0.2.0/24
  may call it" says nothing about who they are.
- **Internal ingress is the right tool for the one case where the caller set is a place.** The
  inventory server is called by the API from inside the environment and by nobody else; the
  platform offers exactly that boundary at no cost, so it is used, and the definition of done
  checks that the app has no external FQDN.
- **Defence in depth without a second perimeter.** Ingress authentication rejects anonymous
  traffic before it reaches the container; the code checks the role and the record; the identity
  limits what a compromised component could read or write. Three independent checks, none of
  them a network.

## Consequences

- The web frontend is the only anonymous surface, and it holds no data and no privilege beyond
  the role its identity was granted on the API.
- A client that needs the API from outside must obtain a token for the registration and hold the
  role; the README shows the two-command check (401 without a token, 403 without the role).
- Private endpoints remain costed, not built, in the landing zone's ADR; adding them later changes
  nothing in this repository's authorisation model, which is the point of making the model
  independent of the network.
