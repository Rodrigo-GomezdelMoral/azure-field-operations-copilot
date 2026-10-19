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
COMPRESSION: dict[str, Any] = {"name": "int8", "kind": "scalarQuantization"}
COMPRESSION |= {"rescoringOptions": {"enableRescoring": True, "rescoreStorageMethod": "preserveOriginals"}}
PROFILE = {"name": "vectors", "algorithm": "hnsw", "compression": "int8", "vectorizer": "embed"}
DELETION = {"@odata.type": "#Microsoft.Azure.Search.SoftDeleteColumnDeletionDetectionPolicy"}
DELETION |= {"softDeleteColumnName": "isDeleted", "softDeleteMarkerValue": "true"}
LAYOUT = {"outputMode": "oneToMany", "markdownHeaderDepth": "h2"}
SPLIT = {"textSplitMode": "pages", "maximumPageLength": 2000, "pageOverlapLength": 200}


def skill(kind: str, context: str, inputs: dict[str, str], outputs: dict[str, str], **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"@odata.type": f"#Microsoft.Skills.{kind}", "context": context, **extra}
    body["inputs"] = [{"name": k, "source": v} for k, v in inputs.items()]
    return body | {"outputs": [{"name": k, "targetName": v} for k, v in outputs.items()]}


def embedding(settings: Settings) -> dict[str, Any]:
    deployment = settings.embedding_deployment
    return {"resourceUri": settings.foundry_account_endpoint, "deploymentId": deployment, "modelName": deployment}


def index_definition(settings: Settings, name: str) -> dict[str, Any]:
    vectorizer = {"name": "embed", "kind": "azureOpenAI", "azureOpenAIParameters": embedding(settings)}
    vectors: dict[str, Any] = {"algorithms": [{"name": "hnsw", "kind": "hnsw"}], "compressions": [COMPRESSION]}
    vectors |= {"vectorizers": [vectorizer], "profiles": [PROFILE]}
    fields = {"titleField": {"fieldName": "section_label"}, "prioritizedContentFields": [{"fieldName": "content"}]}
    semantic = {"configurations": [{"name": settings.semantic_configuration, "prioritizedFields": fields}]}
    return {"name": name, "fields": FIELDS, "vectorSearch": vectors, "semantic": semantic}


def skills(settings: Settings) -> list[dict[str, Any]]:
    embed = embedding(settings) | {"dimensions": 1536}
    layout, markdown = {"file_data": "/document/file_data"}, {"markdown_document": "sections"}
    return [
        skill("Util.DocumentIntelligenceLayoutSkill", "/document", layout, markdown, **LAYOUT),
        skill("Util.ShaperSkill", SECTIONS, {"section_label": SECTION_LABEL}, {"output": "cite"}),
        skill("Text.SplitSkill", SECTIONS, {"text": f"{SECTIONS}/content"}, {"textItems": "chunks"}, **SPLIT),
        skill("Text.AzureOpenAIEmbeddingSkill", CHUNKS, {"text": CHUNKS}, {"embedding": "vector"}, **embed),
    ]


def skillset_definition(settings: Settings, name: str) -> dict[str, Any]:
    sources = {"content": CHUNKS, "vector": f"{CHUNKS}/vector", "section_label": f"{SECTIONS}/cite/section_label"}
    sources |= {field: f"/document/{field}" for field in METADATA}
    selector: dict[str, Any] = {"targetIndexName": settings.search_index, "parentKeyFieldName": "parent_id"}
    selector |= {"sourceContext": CHUNKS, "mappings": [{"name": k, "source": v} for k, v in sources.items()]}
    projections = {"selectors": [selector], "parameters": {"projectionMode": "skipIndexingParentDocuments"}}
    ai = {"@odata.type": "#Microsoft.Azure.Search.AIServicesByIdentity", "identity": None}
    ai |= {"subdomainUrl": settings.foundry_account_endpoint}
    return {"name": name, "skills": skills(settings), "indexProjections": projections, "cognitiveServices": ai}


def indexer_definition(settings: Settings, names: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    credentials = {"connectionString": f"ResourceId={settings.storage_account_resource_id};"}
    source: dict[str, Any] = {"name": names["source"], "type": "azureblob", "credentials": credentials}
    source |= {"container": {"name": "manuals"}, "dataDeletionDetectionPolicy": DELETION}
    configuration = {"dataToExtract": "storageMetadata", "allowSkillsetToReadFileData": True}
    indexer: dict[str, Any] = {"name": names["indexer"], "dataSourceName": names["source"]}
    indexer |= {"skillsetName": names["skillset"], "targetIndexName": settings.search_index}
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
    definitions = [("indexes", index_definition(settings, index)), ("datasources", source), ("indexers", indexer)]
    definitions.insert(1, ("skillsets", skillset_definition(settings, names["skillset"])))
    async with DefaultAzureCredential() as credential:
        token = (await credential.get_token("https://search.azure.com/.default")).token
        client = httpx.AsyncClient(base_url=settings.search_endpoint, params={"api-version": API}, timeout=60)
        async with client as http:
            http.headers["Authorization"] = f"Bearer {token}"
            for kind, body in definitions:
                response = await http.put(f"/{kind}/{body['name']}", json=body)
                assert response.is_success, f"{kind}/{body['name']}: {response.text}"
            print(json.dumps(await run_and_wait(http, names["indexer"])))


if __name__ == "__main__":
    asyncio.run(main(Settings()))
