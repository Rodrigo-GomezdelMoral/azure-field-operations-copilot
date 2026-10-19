from collections.abc import Awaitable, Callable
from typing import Any

from agent_framework import FunctionInvocationContext, FunctionMiddleware
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from app.clients import Clients
from app.config import Settings
from app.models import AuditEvent, PartLine

Next = Callable[[], Awaitable[None]]
PRIVILEGED = ("reserve_parts", "create_work_order")


class AuditMiddleware(FunctionMiddleware):
    """Writes one create-only record per tool call and handoff, whatever the outcome."""

    def __init__(self, clients: Clients, agent: str) -> None:
        self.clients, self.agent = clients, agent

    async def process(self, context: FunctionInvocationContext, call_next: Next) -> None:
        await call_next()
        outcome = "rejected" if context.metadata.get("policy_violation") else "executed"
        event = AuditEvent(
            intervention_id=str(context.kwargs.get("intervention_id", "unknown")),
            agent=self.agent,
            tool=context.function.name,
            arguments=dict(context.arguments or {}),
            outcome=outcome,
            actor=str(context.kwargs.get("actor", "system")),
        )
        await self.clients.container("audit").create_item(event.model_dump(mode="json"))


class PolicyMiddleware(FunctionMiddleware):
    """Checks reservation arguments against the catalogue and the quantity bound before the tool runs."""

    def __init__(self, clients: Clients, settings: Settings) -> None:
        self.clients, self.settings = clients, settings

    async def process(self, context: FunctionInvocationContext, call_next: Next) -> None:
        if context.function.name == "reserve_parts":
            violation = await self.violation(context.arguments or {})
            if violation:
                context.metadata["policy_violation"] = violation
                context.result = f"Policy violation, nothing reserved: {violation}"
                return
        await call_next()

    async def violation(self, arguments: Any) -> str | None:
        inventory, bound = self.clients.container("inventory"), self.settings.max_part_quantity
        for raw in arguments.get("lines", []):
            line = PartLine.model_validate(raw)
            if line.quantity > bound:
                return f"{line.part_number}: quantity {line.quantity} exceeds the bound of {bound}"
            try:
                await inventory.read_item(line.part_number, partition_key=line.part_number)
            except CosmosResourceNotFoundError:
                return f"{line.part_number} is not in the catalogue"
        return None
