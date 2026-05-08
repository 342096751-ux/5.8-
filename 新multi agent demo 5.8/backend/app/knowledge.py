from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class KnowledgeItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KnowledgeCreate(BaseModel):
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)


class KnowledgeUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None

