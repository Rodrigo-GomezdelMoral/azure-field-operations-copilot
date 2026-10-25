from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

PART_NUMBER = r"^[A-Z]{1,4}-\d{3,5}$"
Status = Literal["running", "pending_approval", "pending_question", "completed", "closed", "failed"]
RequestKind = Literal["function_approval", "user_question"]


class Fault(BaseModel):
    asset_id: str = Field(min_length=3, max_length=32)
    description: str = Field(min_length=10, max_length=2000)
    image_media_type: Literal["image/jpeg", "image/png"] | None = None


class PartLine(BaseModel):
    part_number: str = Field(pattern=PART_NUMBER)
    quantity: int = Field(ge=1)


class WorkOrderDraft(BaseModel):
    asset_id: str
    title: str = Field(min_length=5, max_length=120)
    diagnosis: str
    procedure_refs: list[str] = Field(description="section labels of the manual, as returned by search_manual")
    parts: list[PartLine] = []
    safety_notes: list[str] = []
    priority: Literal["low", "normal", "high", "safety"] = "normal"


class PendingRequest(BaseModel):
    request_id: str
    kind: RequestKind
    agent: str
    tool: str | None = None
    arguments: dict[str, Any] = {}
    question: str | None = None
    payload: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Intervention(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    technician_id: str
    asset_id: str
    equipment_model: str | None = None
    status: Status = "running"
    pending: PendingRequest | None = None
    draft: WorkOrderDraft | None = None
    resolution: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RequestResponse(BaseModel):
    request_id: str
    approved: bool | None = None
    answer: str | None = Field(default=None, max_length=2000)
    reason: str | None = Field(default=None, max_length=500)


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    intervention_id: str
    agent: str
    tool: str
    arguments: dict[str, Any]
    outcome: Literal["executed", "rejected", "requested", "approved", "denied", "answered"]
    actor: str
    reason: str | None = None
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
