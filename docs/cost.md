# Cost

Every figure here is either **measured** — read from Azure Cost Management, from the Foundry
account's token metrics, from the Retail Prices API or from an evaluation report — or **modelled**
from a measured unit price and a stated assumption, and each table says which.

## What the workload costs today (measured)

Azure Cost Management, actual cost, month to date on 2026-10-20, grouped by resource group:

| Resource group | Month to date | What drives it |
|---|---|---|
| `rg-fopcopilot-prod-swc` (this repository) | €0.0002 | serverless Cosmos request units for the catalogue, the checkpoints and the audit rows of the evaluation runs; Container Apps while provisioned with the placeholder image; a few megabytes of Log Analytics ingestion |
| `rg-aiplatform-shared-swc` (the landing zone, shared by every repository) | €24.55 | Azure AI Search Basic (about €2.13 a day), the registry, the Log Analytics workspace, and the **model calls of every repository**, which are billed to the shared Foundry account |

The group's own resources cost nothing between interventions: the apps scale to zero, Cosmos is
serverless, Event Grid bills per event. What this system actually spends is model tokens, billed
to the shared account, which the next section isolates.

## What an intervention costs (measured from the account's token metrics)

The Foundry account's `InputTokens` and `OutputTokens` metrics, by deployment, for the two hours
on 2026-10-19 (20:00–22:00 UTC) in which the three smoke runs, the calibration run and their
judges ran — 29 interventions plus about 130 judged items:

| Deployment | Input tokens | Output tokens | Retail price (Sweden Central, per million, 2026-10-14) | Cost |
|---|---|---|---|---|
| gpt-5-mini (Triage, Diagnostic, WorkOrder, the judge's graders) | 1,914,218 | 444,453 | €0.22 in · €1.76 out | €0.42 + €0.78 = €1.20 |
| gpt-5-nano (Parts) | 325,035 | 53,735 | €0.044 in · €0.352 out | €0.014 + €0.019 = €0.03 |
| text-embedding-3-small (similar cases, search vectors) | 3,485 | — | €0.018 | < €0.001 |

That is €1.23 for the two hours, or **at most €0.042 per intervention** if every token were an
intervention's; the judge's graders read every agent conversation three times, so the agents'
own share is lower. The experiment windows had no judge and nothing else running, and give the
clean figure — eight interventions with the similar-cases memory on, 22:14–22:21 UTC the same
evening:

| Deployment | Input tokens | Output tokens | Cost for 8 interventions |
|---|---|---|---|
| gpt-5-mini | 284,708 | 20,377 | €0.0626 + €0.0359 = €0.099 |
| gpt-5-nano | 144,934 | 18,288 | €0.0064 + €0.0064 = €0.013 |
| text-embedding-3-small | 724 | — | < €0.001 |

**€0.111 for eight, €0.014 per intervention**, of which the input side is nine tenths: every
agent re-reads the growing conversation, Diagnostic searches two to four times with six passages
of up to 1,200 characters each, and Parts reads the inventory three or four times. The
eight runs without memory (`experiments/002-memory.md`) cost €0.009 each, less because four of
them stopped before reserving anything.

What does **not** cost tokens: approvals (the run is a checkpoint in Cosmos while it waits), the
audit trail, the A2A card, the MCP reads, and the web proxy.

## Cost per 1,000 interventions (modelled from the measured unit costs)

| Component | Per 1,000 interventions | Basis |
|---|---|---|
| Model tokens | €14 to €42 | €0.014 measured without a judge, €0.042 measured with the judge's graders included |
| Content Understanding, one photograph in three | about €1 | prebuilt-image analyzer, Retail Prices, modelled |
| Cosmos serverless | under €1 | about 60 request-unit operations per intervention (intervention, audit rows, checkpoints, memory query), €0.25 per million RUs |
| Container Apps consumption | about €2 | active CPU while a run streams, roughly four minutes per intervention at 0.5 vCPU |
| **Total** | **about €20 to €45** | |

A technician's preparation time is the comparison the product makes: thirty to forty-five
minutes of a qualified technician per intervention against one and a half cents of tokens.

## Projection to production (modelled)

Assumptions, stated so they can be changed: 100 interventions a working day, 2,200 a month;
one photograph in three; the shared search service upgraded to a Standard tier with the semantic
ranker on the paid plan (the free plan's 1,000 semantic queries a month were exhausted during
development); a dedicated Foundry account for this workload; two Container Apps replicas kept
warm for the API; the judge run weekly on the full suite.

| Item | Monthly | Basis |
|---|---|---|
| Model tokens, 2,200 interventions | €31 | €0.014 measured per intervention |
| Weekly full evaluation with the judge, 105 interventions each | €25 | the smoke evening's judge share, scaled |
| Azure AI Search Standard S1, semantic ranker paid plan | €230 | Retail Prices |
| Container Apps, two warm API replicas plus the three other apps on consumption | €70 | Retail Prices |
| Cosmos serverless, Event Grid, Application Insights, Log Analytics | €20 | measured RU and ingestion volumes, scaled |
| Content Understanding, 730 photographs | €4 | Retail Prices |
| **Total** | **about €380 a month** | |

The dominant item is the search tier, which the landing zone shares across repositories; the
model cost of the agents is a tenth of it.

## How to refresh these numbers

```bash
# month-to-date by resource group (Cost Management REST)
az rest --method post --headers "Content-Type=application/json" \
  --url "https://management.azure.com/subscriptions/<id>/providers/Microsoft.CostManagement/query?api-version=2023-11-01" \
  --body '{"type":"ActualCost","timeframe":"MonthToDate","dataset":{"granularity":"None","aggregation":{"totalCost":{"name":"Cost","function":"Sum"}},"grouping":[{"type":"Dimension","name":"ResourceGroupName"}]}}'

# tokens per deployment for a window
az monitor metrics list --resource <foundry account id> --metric InputTokens OutputTokens \
  --start-time 2026-10-19T20:00:00Z --end-time 2026-10-19T22:00:00Z --interval PT1H --aggregation Total \
  --filter "ModelDeploymentName eq '*'"
```

The prices in `app/config.py` (`PRICES_EUR_PER_MILLION`) are the ones used above and must be
refreshed with the Retail Prices API when a deployment changes.
