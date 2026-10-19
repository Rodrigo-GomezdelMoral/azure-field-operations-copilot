# ADR-004 · Cosmos DB vector memory alongside AI Search

**Status:** accepted · **Date:** 2026-10-19

## Context

The Diagnostic agent needs two kinds of knowledge. The **manuals** say what the procedure is: a
few hundred pages of public maintenance handbooks, chunked by section so that a step can be
cited by its section label. The **experience** says what actually fixed this fault on this
equipment model last time: three hundred resolved work orders, each a short record with a fault
description, a root cause, a resolution and the parts used, written by the technician who closed
the intervention and growing by one record each time an intervention is closed.

Both are retrieved by similarity. The obvious design puts both in the shared Azure AI Search
service: one index for manuals, one for cases. The alternative is to keep the cases in the Cosmos
DB account the workload already owns, in a container with a vector embedding policy, and to query
them with `VectorDistance` from a context provider.

## Decision

Manuals live in **AI Search**, built by the shared service's own identity from the manuals
container with an indexer, a Document Intelligence layout skill, a split skill and an embedding
skill, exactly as the RAG platform builds its corpus (`ops/index.py`). Cases live in **Cosmos
DB**, in the `memory` container partitioned by `/equipment_model`, with a 1,536-dimension
cosine vector policy and a `quantizedFlat` index created in Bicep (`infra/modules/data.bicep`).
`ops/seed.py` embeds the synthetic cases with the same embedding deployment the index uses, and
`app/memory.py` embeds the fault in `before_run` and queries the five closest cases of the same
equipment model.

## Why

- **The record of experience is transactional.** A case is written when an intervention closes,
  by the same API call that updates the intervention, in the same account, under the same
  identity and role. Writing it to a search index instead would add a second write path, a second
  identity grant and an indexer lag between closing an intervention and the next technician
  seeing it. The write path that exists is the one that is audited.
- **The query is scoped, not global.** A case is only useful for the same equipment model, so the
  query is a partition-key lookup first and a vector distance second. Cosmos answers that from one
  logical partition; AI Search would answer it from an index filter over all cases. For three
  hundred records, and even for a hundred thousand, the partitioned query is the cheaper shape.
- **The data has one owner.** The manuals are shared knowledge that any workload may index; the
  cases are this workload's private memory, in its own resource group, deletable with it, with
  the reader role scoped to the container (`id-fopa2a` reads `memory` and `assets` and nothing
  else). A second index on the shared search service would blur that line.
- **One embedding deployment serves both.** The search index's vectorizer and the seed script use
  the same `text-embedding-3-small` deployment, so a fault embedded once at request time can be
  compared with either store. Nothing is embedded twice.

## Consequences

- Two retrieval paths exist and the Diagnostic prompt receives two delimited blocks, both labelled
  untrusted, one per store. The agent is told which is normative (the manual) and which is
  anecdotal (the cases), and the citation rules apply only to the manual.
- Cosmos vector search on a serverless account has no semantic ranker and no hybrid text ranking;
  for this query shape, equipment model plus similarity, neither is needed.
- The case memory contains no proprietary data: three hundred synthetic records generated
  deterministically from a seed, plus whatever technicians close during the demo.

## Rejected

- **Everything in AI Search.** Simpler to describe, worse to operate: a second indexer, a second
  identity grant, and an index that lags the transaction that should feed it.
- **Everything in Cosmos.** The manuals need a layout model, chunking by heading and a semantic
  ranker over hundreds of pages; that is what the search service is for and what the RAG platform
  already proved.
