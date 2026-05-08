from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class AuditRequest(BaseModel):
    content: str
    audit_id: str | None = None
    config: dict[str, Any] | None = None


class BlackboardEntry(BaseModel):
    timestamp: str
    agent: str
    zone: str
    phase: str
    content: str
    data: dict[str, Any] = Field(default_factory=dict)
    raw_llm_output: str | None = None


class AuditResult(BaseModel):
    audit_id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    final_verdict: str  # violation | normal | review | reject | pass
    confidence: float
    logs: list[BlackboardEntry] = Field(default_factory=list)
    agent_results: dict[str, Any] = Field(default_factory=dict)

