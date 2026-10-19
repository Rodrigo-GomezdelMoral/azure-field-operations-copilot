import asyncio
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import httpx
from agent_framework.openai import OpenAIEmbeddingClient
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient

from app.config import Settings
from ops.analyzer import create_analyzer

MANIFEST = json.loads((Path(__file__).resolve().parent.parent / "data" / "manifest.json").read_text(encoding="utf-8"))
Record = dict[str, Any]
Family = tuple[str, list[str], list[str], list[str], list[str]]
FAMILIES: dict[str, Family] = {
    "pump": (
        "P",
        ["CP-200", "CP-350", "MP-80"],
        ["seal leak", "high vibration at full load", "cavitation noise", "low discharge pressure"],
        ["worn mechanical seal", "bearing wear", "suction restriction", "impeller wear"],
        ["mechanical seal kit", "bearing set", "impeller", "coupling insert"],
    ),
    "fan": (
        "F",
        ["AF-900", "CF-450"],
        ["belt slipping", "blade imbalance", "overheating bearing", "excessive noise"],
        ["worn belt", "dust build-up on blades", "lubrication failure", "loose mounting"],
        ["V-belt", "fan bearing", "mounting bolt set", "pulley"],
    ),
    "drive": (
        "VFD",
        ["VX-31", "VX-55"],
        ["overcurrent fault on start", "overheating", "intermittent trips", "no output"],
        ["blocked cooling path", "degraded capacitor", "loose power terminal", "failed output module"],
        ["cooling fan", "DC bus capacitor", "terminal block", "output module"],
    ),
    "conveyor": (
        "CV",
        ["BC-12", "BC-24"],
        ["belt drifts to one side", "frayed belt edge", "gearbox noise", "stalls under load"],
        ["misaligned idler", "damaged belt edge", "low gearbox oil", "worn drive sprocket"],
        ["carrying idler", "belt splice kit", "gearbox oil", "drive sprocket"],
    ),
}
EMBED_BATCH = 64


def parts_for(family: str, spec: Family, rng: random.Random) -> list[Record]:
    prefix, _, _, _, names = spec
    numbers = [f"{prefix}-{1000 + i * 10}" for i in range(len(names))]
    stock = {"stock": rng.randint(0, 12), "unit_cost_eur": rng.randint(20, 900)}
    return [
        {"id": n, "part_number": n, "description": f"{d} ({family})", "family": family, **stock}
        for n, d in zip(numbers, names, strict=True)
    ]


def cases_for(asset: Record, spec: Family, parts: list[Record], rng: random.Random) -> list[Record]:
    _, _, faults, causes, names = spec
    cases = []
    for k in range(1, 14):
        fault = rng.randrange(len(faults))
        resolved = f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        case = {"id": f"wo-{asset['asset_id']}-{k:02d}", "asset_id": asset["asset_id"], "resolved_at": resolved}
        case |= {"equipment_model": asset["equipment_model"], "root_cause": causes[fault]}
        case |= {"fault": f"{asset['asset_id']} ({asset['equipment_model']}): {faults[fault]}"}
        resolution = {"resolution": f"Replaced {names[fault]} and verified operation"}
        cases.append(case | resolution | {"parts_used": [parts[fault]["part_number"]]})
    return cases


def catalogue() -> tuple[list[Record], list[Record], list[Record]]:
    rng, assets, parts, cases = random.Random(7), [], [], []
    for family, spec in FAMILIES.items():
        prefix, models = spec[0], spec[1]
        family_parts = parts_for(family, spec, rng)
        parts += family_parts
        for n in range(1, 7):
            asset_id, commissioned = f"{prefix}-{100 + n}", f"20{rng.randint(12, 24)}-0{rng.randint(1, 9)}-15"
            asset = {"id": asset_id, "asset_id": asset_id, "family": family, "equipment_model": models[n % len(models)]}
            assets.append(asset | {"location": f"Bay {rng.randint(1, 9)}", "commissioned": commissioned})
            cases += cases_for(asset, spec, family_parts, rng)
    return assets, parts, cases[:300]


async def upload_manuals(settings: Settings, credential: DefaultAzureCredential) -> None:
    async with (
        httpx.AsyncClient(follow_redirects=True, timeout=120, headers={"User-Agent": "Mozilla/5.0"}) as http,
        ContainerClient.from_container_url(settings.manuals_container_url, credential=credential) as container,
    ):
        for doc in MANIFEST["documents"]:
            data = (await http.get(doc["url"])).raise_for_status().content
            assert hashlib.sha256(data).hexdigest() == doc["sha256"], f"{doc['id']} changed upstream"
            metadata = {"manual": doc["id"], "family": doc["family"], "title": doc["title"], "source_url": doc["url"]}
            await container.upload_blob(doc["file"], data, overwrite=True, metadata=metadata)


async def embed_cases(settings: Settings, credential: DefaultAzureCredential, cases: list[Record]) -> None:
    endpoint = settings.foundry_account_endpoint
    client = OpenAIEmbeddingClient(model=settings.embedding_deployment, credential=credential, azure_endpoint=endpoint)
    for start in range(0, len(cases), EMBED_BATCH):
        batch = cases[start : start + EMBED_BATCH]
        texts = [f"{c['fault']}. Root cause: {c['root_cause']}. {c['resolution']}" for c in batch]
        for case, embedding in zip(batch, await client.get_embeddings(texts), strict=True):
            case["embedding"] = list(embedding.vector)


async def seed(settings: Settings) -> None:
    assets, parts, cases = catalogue()
    async with DefaultAzureCredential() as credential, CosmosClient(settings.cosmos_endpoint, credential) as cosmos:
        await upload_manuals(settings, credential)
        await embed_cases(settings, credential, cases)
        database = cosmos.get_database_client(settings.cosmos_database)
        for name, items in (("assets", assets), ("inventory", parts), ("memory", cases)):
            container = database.get_container_client(name)
            await asyncio.gather(*(container.upsert_item(item) for item in items))
    analyzer = await create_analyzer(settings)
    print(f"seeded {len(assets)} assets, {len(parts)} parts, {len(cases)} cases; analyzer {analyzer}")


if __name__ == "__main__":
    asyncio.run(seed(Settings()))
