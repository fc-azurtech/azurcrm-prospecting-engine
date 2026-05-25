from typing import Any

from pydantic import BaseModel, Field


class JobCreateRequest(BaseModel):
    request_id: str
    campaign: dict[str, Any]
    scope: dict[str, Any]
    target_profile: dict[str, Any]
    offer: dict[str, Any]
    keywords: dict[str, Any]
    sources: dict[str, Any]
    execution: dict[str, Any]
    assignment: dict[str, Any]
    query_templates: list[dict[str, Any]] = Field(default_factory=list)
    tenant_key: str | None = None
    callback_url: str | None = None


class JobCreateResponse(BaseModel):
    external_job_id: str
    status: str
    accepted_at: str
    deduplicated: bool
    idempotency_key: str
    correlation_id: str
    polling_url: str
    eta_seconds: int


class JobStatusResponse(BaseModel):
    external_job_id: str
    status: str
    request_id: str
    idempotency_key: str
    correlation_id: str
    accepted_at: str
    completed_at: str | None
    callback_status: str | None


class HealthResponse(BaseModel):
    ok: bool
    service: str
    version: str
