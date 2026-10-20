import asyncio
from dataclasses import dataclass

from agent_framework.foundry import FoundryChatClient, FoundryChatOptions
from agent_framework.openai import OpenAIEmbeddingClient
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.eventgrid.aio import EventGridPublisherClient
from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient

from app.config import Settings


@dataclass
class Clients:
    credential: DefaultAzureCredential
    chat: FoundryChatClient
    small_chat: FoundryChatClient
    embeddings: OpenAIEmbeddingClient
    search: SearchClient
    cosmos: CosmosClient
    database: str
    options: FoundryChatOptions
    events: EventGridPublisherClient | None = None

    def container(self, name: str) -> ContainerProxy:
        return self.cosmos.get_database_client(self.database).get_container_client(name)

    async def close(self) -> None:
        closers = [self.search.close(), self.cosmos.close(), self.credential.close()]
        await asyncio.gather(*closers, *([self.events.close()] if self.events else []))


def build_clients(settings: Settings) -> Clients:
    credential = DefaultAzureCredential(process_timeout=60)
    project = settings.foundry_project_endpoint
    topic = settings.event_grid_topic_endpoint
    events = EventGridPublisherClient(topic, credential) if topic else None
    return Clients(
        credential=credential,
        chat=FoundryChatClient(project_endpoint=project, model=settings.chat_deployment, credential=credential),
        small_chat=FoundryChatClient(
            project_endpoint=project, model=settings.small_chat_deployment, credential=credential
        ),
        embeddings=OpenAIEmbeddingClient(
            model=settings.embedding_deployment, credential=credential, azure_endpoint=settings.foundry_account_endpoint
        ),
        search=SearchClient(settings.search_endpoint, settings.search_index, credential),
        cosmos=CosmosClient(settings.cosmos_endpoint, credential),
        database=settings.cosmos_database,
        options=FoundryChatOptions(reasoning={"effort": "low"}, store=False),
        events=events,
    )
