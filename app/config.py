from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
CONTAINERS = ("interventions", "checkpoints", "memory", "audit", "assets", "inventory")
# EUR per million tokens (input, output), GlobalStandard, Azure Retail Prices API, Sweden Central, 2026-10-14.
PRICES_EUR_PER_MILLION: dict[str, tuple[float, float]] = {"gpt-5-mini": (0.22, 1.76), "gpt-5-nano": (0.044, 0.352)}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    foundry_project_endpoint: str
    foundry_account_endpoint: str
    chat_deployment: str = "gpt-5-mini"
    small_chat_deployment: str = "gpt-5-nano"
    embedding_deployment: str = "text-embedding-3-small"
    analyzer_id: str = "damage-triage-v1"
    search_endpoint: str
    search_index: str = "manuals"
    cosmos_endpoint: str
    cosmos_database: str = "fieldops"
    manuals_container_url: str
    storage_account_resource_id: str
    event_grid_topic_endpoint: str | None = None
    inventory_mcp_url: str = "http://ca-fopmcp/mcp"
    entra_tenant_id: str
    api_audience: str
    api_app_role: str = "Copilot.Use"
    a2a_app_role: str = "Copilot.Diagnose"
    supervisor_role: str = "supervisor"
    require_auth: bool = True
    applicationinsights_connection_string: str | None = None
    similar_cases: int = Field(default=5, ge=1, le=20)
    max_part_quantity: int = Field(default=50, ge=1, le=500)

    @property
    def semantic_configuration(self) -> str:
        return f"{self.search_index}-semantic"

    def price(self, deployment: str, prompt_tokens: int, completion_tokens: int) -> float:
        prompt_price, completion_price = PRICES_EUR_PER_MILLION.get(deployment, (0.0, 0.0))
        return (prompt_tokens * prompt_price + completion_tokens * completion_price) / 1_000_000
