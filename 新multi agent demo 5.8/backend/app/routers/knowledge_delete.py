from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.knowledge_service import KnowledgeService

MAX_BATCH_DELETE = 1000


class BatchDeletePayload(BaseModel):
    ids: list[str] = Field(default_factory=list)
    confirm: bool = False


def create_knowledge_delete_router(ks: KnowledgeService) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge-delete"])

    def _validate_ids(ids: list[str]) -> list[str]:
        clean = [str(x or "").strip() for x in ids if str(x or "").strip()]
        if not clean:
            raise HTTPException(status_code=400, detail="ids 不能为空")
        if len(clean) > MAX_BATCH_DELETE:
            raise HTTPException(status_code=400, detail=f"单次最多删除 {MAX_BATCH_DELETE} 条")
        return list(dict.fromkeys(clean))

    async def _handle(collection: str, payload: BatchDeletePayload) -> dict[str, Any]:
        ids = _validate_ids(payload.ids)
        preview = ks.preview_batch_delete(collection, ids)
        if not payload.confirm:
            return {
                "confirm": False,
                "total": len(ids),
                "can_delete": len(preview["found"]),
                "not_found": len(preview["not_found"]),
                "preview": preview["found"][:120],
                "not_found_ids": preview["not_found"][:120],
            }
        stats = ks.batch_delete(collection, ids)
        return {
            "confirm": True,
            "total": len(ids),
            "deleted": stats["deleted"],
            "failed": stats["failed"],
            "not_found": stats["not_found"],
        }

    @router.delete("/rules/batch")
    async def batch_delete_rules(payload: BatchDeletePayload) -> dict[str, Any]:
        return await _handle("rule_base", payload)

    @router.delete("/kb/batch")
    async def batch_delete_kb(payload: BatchDeletePayload) -> dict[str, Any]:
        return await _handle("knowledge_base", payload)

    return router

