import asyncio

from azure.ai.contentunderstanding.aio import ContentUnderstandingClient
from azure.ai.contentunderstanding.models import ContentAnalyzer, ContentFieldDefinition, ContentFieldSchema
from azure.identity.aio import DefaultAzureCredential

from app.config import Settings

COMPONENTS = [
    "bearing",
    "seal",
    "impeller",
    "belt",
    "coupling",
    "motor winding",
    "fan blade",
    "housing",
    "wiring",
    "other",
]
SEVERITIES = ["minor", "moderate", "severe", "critical"]
SAFETY = ["none", "stop before work", "lock-out required"]


def field(description: str, enum: list[str] | None = None) -> ContentFieldDefinition:
    method = "classify" if enum else "generate"
    return ContentFieldDefinition(method=method, type="string", enum=enum, description=description)


FIELDS = {
    "component_type": field("The damaged component", COMPONENTS),
    "visible_damage": field("What is visibly wrong, in one sentence"),
    "severity": field("How far the damage has progressed", SEVERITIES),
    "safety_flag": field("Whether the equipment must be stopped or locked out before work", SAFETY),
}


def definition(settings: Settings) -> ContentAnalyzer:
    return ContentAnalyzer(
        base_analyzer_id="prebuilt-image",
        description="Classifies the damage visible in a technician's photograph before triage",
        field_schema=ContentFieldSchema(name="damage", fields=FIELDS),
        models={"completion": settings.chat_deployment},
    )


async def create_analyzer(settings: Settings) -> str:
    async with (
        DefaultAzureCredential() as credential,
        ContentUnderstandingClient(endpoint=settings.foundry_account_endpoint, credential=credential) as client,
    ):
        await client.update_defaults(model_deployments={"gpt-5-mini": settings.chat_deployment})
        poller = await client.begin_create_analyzer(settings.analyzer_id, definition(settings), allow_replace=True)
        analyzer = await poller.result()
    return str(analyzer.status)


if __name__ == "__main__":
    print(asyncio.run(create_analyzer(Settings())))
