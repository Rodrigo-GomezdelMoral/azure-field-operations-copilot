import asyncio
import json
from typing import Any

import httpx
from azure.identity.aio import DefaultAzureCredential

from app.config import Settings

API = "2026-04-01"
SECTIONS, CHUNKS = "/document/sections/*", "/document/sections/*/chunks/*"
H1, H2 = f"$({SECTIONS}/sections/h1)", f"$({SECTIONS}/sections/h2)"
SECTION_LABEL = f'={H2}!="" ? {H1} + " > " + {H2} : {H1}'
TEXT = {"type": "Edm.String", "searchable": True, "analyzer": "en.microsoft"}
KEYWORD = {"type": "Edm.String", "filterable": True, "facetable": True}
VECTOR = {"type": "Collection(Edm.Single)", "dimensions": 1536, "vectorSearchProfile": "vectors", "stored": False}
FIELDS = [
    {"name": "chunk_id", "type": "Edm.String", "key": True, "analyzer": "keyword"},
    {"name": "parent_id", "type": "Edm.String", "filterable": True},
    {"name": "manual", **KEYWORD},
    {"name": "family", **KEYWORD},
    {"name": "title", "type": "Edm.String"},
    {"name": "source_url", "type": "Edm.String"},
    {"name": "section_label", **TEXT, "filterable": True},
    {"name": "content", **TEXT},
    {"name": "vector", **VECTOR},
]
METADATA = ("manual", "family", "title", "source_url")
RESCORING = {"enableRescoring": True, "rescoreStorageMethod": "preserveOriginals"}
SOFT_DELETE = {
    "@odata.type": "#Microsoft.Azure.Search.SoftDeleteColumnDeletionDetectionPolicy",
    "softDeleteColumnName": "isDeleted",
}


def skill(kind: str, context: str, inputs: dict[str, str], outputs: dict[str, str], **extra: Any) -> dict[str, Any]:
    return {
        "@odata.type": f"#Microsoft.Skills.{kind}",
        "context": context,
        "inputs": [{"name": k, "source": v} for k, v in inputs.items()],
        "outputs": [{"name": k, "targetName": v} for k, v in outputs.items()],
        **extra,
    }


def embedding(settings: Settings) -> dict[str, str]:
    return {"resourceUri": settings.foundry_account_endpoint, "deploymentId": settings.embedding_deployment}


def index_definition(settings: Settings, name: str) -> dict[str, Any]:
    model = {**embedding(settings), "modelName": settings.embedding_deployment}
    vectorizer = {"name": "embed", "kind": "azureOpenAI", "azureOpenAIParameters": model}
    compression = {"name": "int8", "kind": "scalarQuantization", "rescoringOptions": RESCORING}
    profile = {"name": "vectors", "algorithm": "hnsw", "compression": "int8", "vectorizer": "embed"}
    algorithms = [{"name": "hnsw", "kind": "hnsw"}]
    vectors = {
        "algorithms": algorithms,
        "compressions": [compression],
        "vectorizers": [vectorizer],
        "profiles": [profile],
    }
    fields = {"titleField": {"fieldName": "section_label"}, "prioritizedContentFields": [{"fieldName": "content"}]}
    semantic = {"configurations": [{"name": settings.semantic_configuration, "prioritizedFields": fields}]}
    return {"name": name, "fields": FIELDS, "vectorSearch": vectors, "semantic": semantic}


def skills(settings: Settings) -> list[dict[str, Any]]:
    layout = {"outputMode": "oneToMany", "markdownHeaderDepth": "h2"}
    split = {"textSplitMode": "pages", "maximumPageLength": 2000, "pageOverlapLength": 200}
    embed = {**embedding(settings), "modelName": settings.embedding_deployment, "dimensions": 1536}
    return [
        skill(
            "Util.DocumentIntelligenceLayoutSkill",
            "/document",
            {"file_data": "/document/file_data"},
            {"markdown_document": "sections"},
            **layout,
        ),
        skill("Util.ShaperSkill", SECTIONS, {"section_label": SECTION_LABEL}, {"output": "cite"}),
        skill("Text.SplitSkill", SECTIONS, {"text": f"{SECTIONS}/content"}, {"textItems": "chunks"}, **split),
        skill("Text.AzureOpenAIEmbeddingSkill", CHUNKS, {"text": CHUNKS}, {"embedding": "vector"}, **embed),
    ]


def skillset_definition(settings: Settings, name: str) -> dict[str, Any]:
    sources = {"content": CHUNKS, "vector": f"{CHUNKS}/vector", "section_label": f"{SECTIONS}/cite/section_label"}
    sources |= {field: f"/document/{field}" for field in METADATA}
    mappings = [{"name": k, "source": v} for k, v in sources.items()]
    selector = {
        "targetIndexName": settings.search_index,
        "parentKeyFieldName": "parent_id",
        "sourceContext": CHUNKS,
        "mappings": mappings,
    }
    projections = {"selectors": [selector], "parameters": {"projectionMode": "skipIndexingParentDocuments"}}
    ai = {
        "@odata.type": "#Microsoft.Azure.Search.AIServicesByIdentity",
        "subdomainUrl": settings.foundry_account_endpoint,
        "identity": None,
    }
    return {"name": name, "skills": skills(settings), "indexProjections": projections, "cognitiveServices": ai}


def indexer_definition(settings: Settings, names: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    credentials = {"connectionString": f"ResourceId={settings.storage_account_resource_id};"}
    deletion = {**SOFT_DELETE, "softDeleteMarkerValue": "true"}
    source = {
        "name": names["source"],
        "type": "azureblob",
        "credentials": credentials,
        "container": {"name": "manuals"},
        "dataDeletionDetectionPolicy": deletion,
    }
    configuration = {"dataToExtract": "storageMetadata", "allowSkillsetToReadFileData": True}
    indexer = {
        "name": names["indexer"],
        "dataSourceName": names["source"],
        "skillsetName": names["skillset"],
        "targetIndexName": settings.search_index,
    }
    return source, indexer | {"schedule": {"interval": "P1D"}, "parameters": {"configuration": configuration}}


async def run_and_wait(http: httpx.AsyncClient, indexer: str) -> dict[str, Any]:
    (await http.post(f"/indexers/{indexer}/run")).raise_for_status()
    while True:
        await asyncio.sleep(30)
        status = (await http.get(f"/indexers/{indexer}/status")).raise_for_status().json()["lastResult"]
        if status and status["status"] != "inProgress":
            return {k: status.get(k) for k in ("status", "itemsProcessed", "itemsFailed", "errorMessage")}


async def main(settings: Settings) -> None:
    index = settings.search_index
    names = {"index": index, "skillset": f"{index}-skillset", "source": f"{index}-blobs", "indexer": f"{index}-indexer"}
    source, indexer = indexer_definition(settings, names)
    definitions = [
        ("indexes", index_definition(settings, index)),
        ("skillsets", skillset_definition(settings, names["skillset"])),
    ]
    definitions += [("datasources", source), ("indexers", indexer)]
    async with DefaultAzureCredential() as credential:
        token = (await credential.get_token("https://search.azure.com/.default")).token
        headers, params = {"Authorization": f"Bearer {token}"}, {"api-version": API}
        async with httpx.AsyncClient(
            base_url=settings.search_endpoint, params=params, headers=headers, timeout=60
        ) as http:
            for kind, body in definitions:
                response = await http.put(f"/{kind}/{body['name']}", json=body)
                assert response.is_success, f"{kind}/{body['name']}: {response.text}"
            print(json.dumps(await run_and_wait(http, names["indexer"])))


if __name__ == "__main__":
    asyncio.run(main(Settings()))
