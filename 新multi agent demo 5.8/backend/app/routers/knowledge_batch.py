from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.services.knowledge_service import (
    KnowledgeService,
    RuleImportStrategy,
)
from app.services.vector_store import VectorStore


class RulesConfirmPayload(BaseModel):
    preview_id: str = Field(..., min_length=4)
    strategy: RuleImportStrategy


BATCH_SIZE = 100
MAX_FILE_SIZE = 50 * 1024 * 1024
PREVIEW_TTL_SEC = 1800


def create_knowledge_batch_router(_vector_store: VectorStore, ks: KnowledgeService) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge-batch"])
    progress_store: dict[str, dict[str, Any]] = {}
    preview_rules_store: dict[str, dict[str, Any]] = {}

    def normalize_rule(row: dict[str, Any]) -> dict[str, Any]:
        out = {str(k).strip(): "" if v is None else str(v).strip() for k, v in row.items()}
        if out.get("内容") == "" and out.get("content"):
            out["内容"] = out["content"]
        if out.get("分类") == "" and out.get("category"):
            out["分类"] = out["category"]
        if out.get("严重度") == "" and out.get("severity"):
            out["严重度"] = out["severity"]
        if out.get("示例") == "" and out.get("examples"):
            out["示例"] = out["examples"]
        if out.get("备注") == "" and out.get("note"):
            out["备注"] = out["note"]
        return out

    def normalize_kb(row: dict[str, Any]) -> dict[str, Any]:
        out = {str(k).strip(): "" if v is None else str(v).strip() for k, v in row.items()}
        if out.get("主题") == "":
            for k in ("topic", "theme", "title", "subject"):
                if out.get(k):
                    out["主题"] = out[k]
                    break
        if out.get("内容") == "":
            for k in ("content", "body", "text"):
                if out.get(k):
                    out["内容"] = out[k]
                    break
        if out.get("关联规则") == "" and out.get("related"):
            out["关联规则"] = out["related"]
        if out.get("标签") == "" and out.get("tags"):
            out["标签"] = out["tags"]
        return out

    def gc_previews() -> None:
        now = time.monotonic()
        dead = [
            pid
            for pid, payload in preview_rules_store.items()
            if payload.get("expires", 0) < now
        ]
        for pid in dead:
            preview_rules_store.pop(pid, None)

    async def run_kb_import(
        collection_name: str,
        records: list[dict[str, Any]],
        progress_id: str,
    ) -> None:
        try:
            progress_store[progress_id]["status"] = "processing"
            total_rows = len(records)
            normalized = [normalize_kb(r) for r in records]

            valid, errors = ks._validate_records(normalized, collection_name)
            new_records, duplicates = ks._check_duplicates(valid, collection_name)
            errs_preview: list[dict[str, Any]] = [
                {"row": e.get("row"), "error": str(e.get("error", ""))[:200]}
                for e in errors[:30]
            ]
            for d in duplicates[:20]:
                errs_preview.append({"row": d.get("row"), "error": str(d.get("error", ""))[:200]})

            handled = len(errors) + len(duplicates)
            progress_store[progress_id].update(
                {
                    "failed": len(errors),
                    "skipped": len(duplicates),
                    "success": 0,
                    "processed": min(handled, total_rows),
                    "errors": errs_preview[:10],
                }
            )

            success_written = 0
            idx = 0
            while idx < len(new_records):
                chunk = new_records[idx : idx + BATCH_SIZE]
                await ks._batch_store(chunk, collection_name)
                success_written += len(chunk)
                idx += BATCH_SIZE
                handled_so_far = len(errors) + len(duplicates) + success_written
                progress_store[progress_id].update(
                    {
                        "processed": min(handled_so_far, total_rows),
                        "success": success_written,
                        "status": "processing",
                    }
                )

            progress_store[progress_id].update(
                {
                    "status": "completed",
                    "processed": total_rows,
                    "success": success_written,
                }
            )
        except Exception as exc:
            progress_store[progress_id]["status"] = "failed"
            progress_store[progress_id]["errors"] = [{"row": 0, "error": repr(exc)}]

    def run_rules_confirm_import(tagged_valid: Any, strategy: RuleImportStrategy, progress_id: str) -> None:
        try:
            progress_store[progress_id]["status"] = "processing"
            total = len(tagged_valid)
            progress_store[progress_id]["total"] = total
            progress_store[progress_id]["processed"] = 0

            counters, errs, logs = ks.apply_rules_import_with_strategy(tagged_valid, strategy)
            prog = progress_store[progress_id]
            prog.update(
                {
                    "status": "completed",
                    "processed": total,
                    "success": counters.get("success_imported", 0)
                    + counters.get("overwrite", 0)
                    + counters.get("merged_update", 0)
                    + counters.get("both_kept_added", 0),
                    "skipped": counters.get("skipped_duplicate", 0),
                    "failed": counters.get("failed", 0),
                    "errors": (
                        [{"row": e.get("row"), "error": e.get("error", "")} for e in errs[:80]]
                        + prog.get("errors", [])[:40]
                    )[:120],
                    "report": {
                        "success_imported": counters.get("success_imported", 0),
                        "skipped_duplicate": counters.get("skipped_duplicate", 0),
                        "overwrite": counters.get("overwrite", 0),
                        "merged_update": counters.get("merged_update", 0),
                        "both_kept_added": counters.get("both_kept_added", 0),
                        "failed": counters.get("failed", 0),
                    },
                    "log_tail": logs[-50:],
                }
            )
        except Exception as exc:
            progress_store[progress_id]["status"] = "failed"
            progress_store[progress_id]["errors"] = [{"row": 0, "error": repr(exc)}]

    @router.post("/rules/batch-upload/preview")
    async def rules_batch_preview_rules(
        file: UploadFile = File(...),
        file_type: str = Form("csv"),
    ) -> dict[str, Any]:
        gc_previews()
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 限制",
            )
        ft = (file_type or "csv").lower().strip(".")
        try:
            records = ks._parse_file(content, ft)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not records:
            raise HTTPException(status_code=400, detail="文件为空或无法解析")

        normalized = [normalize_rule(r) for r in records]
        tagged_valid, errors = ks._validate_records_tagged(normalized, "rule_base")
        analysis = ks.analyze_rules_duplicate_batch(tagged_valid)

        preview_id = str(uuid4())[:12]
        preview_rules_store[preview_id] = {
            "expires": time.monotonic() + PREVIEW_TTL_SEC,
            "tagged_valid": tagged_valid,
        }
        return {
            "preview_id": preview_id,
            "total_rows": len(records),
            "valid_row_count": len(tagged_valid),
            "analysis": analysis,
            "validation_errors": [
                {"row": e.get("row"), "error": str(e.get("error", ""))[:300]} for e in errors[:80]
            ],
        }

    @router.post("/rules/batch-upload/confirm")
    async def rules_batch_confirm(
        confirm: RulesConfirmPayload,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        gc_previews()
        entry = preview_rules_store.pop(confirm.preview_id, None)
        if not entry:
            raise HTTPException(status_code=404, detail="预览已过期或不存在，请重新上传文件分析")

        progress_id = str(uuid4())[:8]
        progress_store[progress_id] = {
            "total": len(entry["tagged_valid"]),
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "status": "queued",
            "errors": [],
            "report": {},
        }
        background_tasks.add_task(
            run_rules_confirm_import,
            entry["tagged_valid"],
            confirm.strategy,
            progress_id,
        )
        return {
            "progress_id": progress_id,
            "message": "已按所选策略后台导入",
            "poll_url": f"/api/knowledge/progress/{progress_id}",
        }

    @router.post("/kb/batch-upload")
    async def batch_upload_kb(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        file_type: str = Form("csv"),
    ) -> dict[str, Any]:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB 限制",
            )
        ft = (file_type or "csv").lower().strip(".")
        try:
            records = ks._parse_file(content, ft)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not records:
            raise HTTPException(status_code=400, detail="文件为空或无法解析")

        progress_id = str(uuid4())[:8]
        progress_store[progress_id] = {
            "total": len(records),
            "processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "status": "queued",
            "errors": [],
        }
        background_tasks.add_task(run_kb_import, "knowledge_base", records, progress_id)
        return {
            "progress_id": progress_id,
            "total": len(records),
            "message": "上传已接收，正在后台处理",
            "poll_url": f"/api/knowledge/progress/{progress_id}",
        }

    @router.get("/progress/{progress_id}")
    async def get_progress(progress_id: str) -> dict[str, Any]:
        data = progress_store.get(progress_id)
        if not data:
            raise HTTPException(status_code=404, detail="进度不存在或已过期")
        return data

    return router
