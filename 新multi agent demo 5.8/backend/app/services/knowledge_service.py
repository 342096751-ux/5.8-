from __future__ import annotations

import csv
import io
import json
import uuid
from difflib import SequenceMatcher
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.knowledge import KnowledgeCreate, KnowledgeItem, KnowledgeUpdate
from app.services.vector_store import VectorStore


RuleImportStrategy = Literal["skip", "overwrite", "keep_both", "merge"]

DEFAULT_SIMILARITY_HIGH = 0.9


class BatchImportResult(BaseModel):
    total_rows: int
    success_count: int
    skip_count: int
    error_count: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: int


class KnowledgeService:
    def __init__(self, vector_store: VectorStore) -> None:
        self.vector_store = vector_store

    @staticmethod
    def _squeeze_ws(s: str) -> str:
        return " ".join((s or "").split())

    def _similarity_two_texts(self, a: str, b: str, *, containment_high: float = 0.92) -> float:
        """简单相似度：归一化后相等、包含关系提升、否则 SequenceMatcher。"""
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        na, nb = self._squeeze_ws(a), self._squeeze_ws(b)
        if na == nb:
            return 1.0
        short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
        if len(short) >= 8 and short in long:
            return max(containment_high, len(short) / max(len(long), 1))
        return float(SequenceMatcher(None, na, nb).ratio())

    def _collect_existing_rule_rows(self) -> list[tuple[str, str, dict[str, Any]]]:
        """(id, 内容纯文本, metadata 副本)"""
        out: list[tuple[str, str, dict[str, Any]]] = []
        for row in self.vector_store.get_all("rule_base"):
            rid = str(row.get("id", "") or "")
            meta = dict(row.get("metadata") or {})
            txt = str(meta.get("内容", "") or meta.get("content", "") or row.get("document", "") or "").strip()
            out.append((rid, txt, meta))
        return out

    def _match_new_rule_against_existing(
        self,
        new_text: str,
        existing: list[tuple[str, str, dict[str, Any]]],
        *,
        threshold: float = DEFAULT_SIMILARITY_HIGH,
    ) -> tuple[str, str, float, str]:
        """
        返回 (kind, matched_id, similarity, matched_content_preview)
        kind: new | duplicate_exact | duplicate_similar
        """
        if not existing:
            return "new", "", 0.0, ""
        exact_id = ""
        for eid, txt, _ in existing:
            if txt == new_text or self._squeeze_ws(txt) == self._squeeze_ws(new_text):
                exact_id = eid
                break
            if new_text.strip() != "" and new_text.strip() == txt.strip():
                exact_id = eid
                break
        if exact_id:
            return "duplicate_exact", exact_id, 1.0, new_text[:200]

        best_id, best_txt, best_r = "", "", 0.0
        for eid, txt, _ in existing:
            r = self._similarity_two_texts(new_text, txt)
            if r > best_r:
                best_r, best_id, best_txt = r, eid, txt
        if best_r >= threshold:
            return "duplicate_similar", best_id, best_r, best_txt[:200]
        return "new", "", best_r if best_txt else 0.0, ""

    def analyze_rules_duplicate_batch(
        self,
        tagged_valid: list[tuple[int, dict[str, Any]]],
        *,
        threshold: float = DEFAULT_SIMILARITY_HIGH,
    ) -> dict[str, Any]:
        """用于预览：与库内已有规则 + 本次文件中已排的规则逐条比对。"""
        pool = list(self._collect_existing_rule_rows())
        items: list[dict[str, Any]] = []
        summary = {"new": 0, "duplicate_exact": 0, "duplicate_similar": 0}

        for row_num, record in tagged_valid:
            text = self._extract_content(record, "rule_base").strip()
            kind, mid, sim, mprev = self._match_new_rule_against_existing(
                text, pool, threshold=threshold
            )
            if kind == "new":
                summary["new"] += 1
            elif kind == "duplicate_exact":
                summary["duplicate_exact"] += 1
            else:
                summary["duplicate_similar"] += 1
            items.append(
                {
                    "row": row_num,
                    "kind": kind,
                    "similarity": round(sim, 4),
                    "matched_id": mid or None,
                    "matched_preview": mprev[:500] if mprev else None,
                    "content_preview": text[:280],
                    "severity": record.get("严重度", ""),
                    "category": record.get("分类", ""),
                }
            )

            if kind == "new":
                pool.append((str(uuid.uuid4()), text, dict(record)))

        return {"items": items, "summary": summary, "similarity_threshold": threshold}

    def apply_rules_import_with_strategy(
        self,
        tagged_valid: list[tuple[int, dict[str, Any]]],
        strategy: RuleImportStrategy,
        *,
        threshold: float = DEFAULT_SIMILARITY_HIGH,
        suffix_fn: Any | None = None,
    ) -> tuple[dict[str, int], list[dict[str, Any]], list[str]]:
        """
        执行规则导入策略。返回统计、错误列表（行级）、以及用于进度条的日志消息。
        统计字段：success_added, overwrite, merged_update, skipped_duplicate, both_kept_added, validation_skipped
        
        （validation_skipped 在预览阶段不产生；此处通常为 0）
        """
        existing = self._collect_existing_rule_rows()

        counters = {
            "success_imported": 0,
            "skipped_duplicate": 0,
            "overwrite": 0,
            "merged_update": 0,
            "both_kept_added": 0,
            "failed": 0,
        }
        errs: list[dict[str, Any]] = []
        log_lines: list[str] = []

        def dup_kind_for(text: str) -> tuple[str, str, float]:
            kind, mid, sim, _ = self._match_new_rule_against_existing(
                text, existing, threshold=threshold
            )
            return kind, mid, sim

        for row_num, rec in tagged_valid:
            text = self._extract_content(rec, "rule_base").strip()
            kind, matched_id, _sim = dup_kind_for(text)

            try:
                if kind == "new":
                    rid = str(rec.get("id", "")).strip() or str(uuid.uuid4())
                    if self._id_exists(existing, rid):
                        errs.append({"row": row_num, "error": f"ID `{rid}` 已存在"})
                        counters["failed"] += 1
                        continue
                    meta = dict({**rec, "id": rid})
                    self.vector_store.add_one(
                        "rule_base",
                        rid,
                        text,
                        meta,
                    )
                    counters["success_imported"] += 1
                    existing.append((rid, text, meta))
                    log_lines.append(f"行{row_num}: 新增写入 {rid[:8]}...")
                    continue

                # duplicate_exact or duplicate_similar
                if strategy == "skip":
                    counters["skipped_duplicate"] += 1
                    log_lines.append(f"行{row_num}: 跳过重复 (match={matched_id})")
                    continue

                if strategy == "overwrite":
                    self.vector_store.update_one(
                        "rule_base",
                        matched_id,
                        text,
                        {**rec, "id": matched_id},
                    )
                    counters["overwrite"] += 1
                    for i, (eid, _t, _m) in enumerate(existing):
                        if eid == matched_id:
                            existing[i] = (matched_id, text, dict({**rec, "id": matched_id}))
                            break
                    else:
                        existing.append((matched_id, text, dict({**rec, "id": matched_id})))
                    log_lines.append(f"行{row_num}: 覆盖 {matched_id[:8]}...")
                    continue

                if strategy == "keep_both":
                    nid = str(uuid.uuid4())
                    rec2 = dict(rec)
                    suf = suffix_fn(row_num) if suffix_fn else f"导入副本{row_num}"
                    cat = str(rec2.get("分类", "")).strip()
                    rec2["分类"] = f"{cat}-{suf}".strip("-") if cat else suf
                    rec2.setdefault("备注", "")
                    prev_note = str(rec2.get("备注", "")).strip()
                    rec2["备注"] = f"{prev_note} 原相似项ID:{matched_id}".strip()
                    rid_new = nid
                    self.vector_store.add_one(
                        "rule_base",
                        rid_new,
                        self._extract_content(rec2, "rule_base"),
                        rec2,
                    )
                    counters["both_kept_added"] += 1
                    existing.append((rid_new, self._extract_content(rec2, "rule_base").strip(), rec2))
                    log_lines.append(f"行{row_num}: 保留两者，新ID={rid_new[:8]}...")
                    continue

                if strategy == "merge":
                    old_meta_raw = next(
                        (dict(m) if m else {} for eid, _t, m in existing if eid == matched_id),
                        {},
                    )
                    merged = {**old_meta_raw, **dict(rec)}
                    merged["id"] = matched_id
                    merged_doc = self._extract_content(merged, "rule_base")
                    self.vector_store.update_one(
                        "rule_base",
                        matched_id,
                        merged_doc,
                        merged,
                    )
                    counters["merged_update"] += 1
                    for i, (eid, _t, _m) in enumerate(existing):
                        if eid == matched_id:
                            existing[i] = (matched_id, merged_doc.strip(), merged)
                            break
                    log_lines.append(f"行{row_num}: 合并更新 {matched_id[:8]}...")
                    continue

            except Exception as ex:  # noqa: BLE001
                counters["failed"] += 1
                errs.append({"row": row_num, "error": repr(ex)[:200]})

        return counters, errs, log_lines

    @staticmethod
    def _id_exists(existing_rows: list[tuple[str, str, dict[str, Any]]], rid: str) -> bool:
        return any(eid == rid for eid, _t, _m in existing_rows)

    async def batch_import(
        self, collection_name: str, file_content: bytes, file_type: str
    ) -> BatchImportResult:
        start = perf_counter()
        records = self._parse_file(file_content, file_type)
        valid_records, errors = self._validate_records(records, collection_name)
        new_records, duplicates = self._check_duplicates(valid_records, collection_name)
        await self._batch_store(new_records, collection_name)
        duration_ms = int((perf_counter() - start) * 1000)
        return BatchImportResult(
            total_rows=len(records),
            success_count=len(new_records),
            skip_count=len(duplicates) + len(errors),
            error_count=len(errors),
            errors=errors + duplicates,
            duration_ms=duration_ms,
        )

    async def rule_exists(self, rule_id: str) -> bool:
        rows = self.vector_store.get_all("rule_base")
        rid = str(rule_id or "").strip()
        return any(str(r.get("id", "")) == rid for r in rows)

    async def knowledge_exists(self, knowledge_id: str) -> bool:
        rows = self.vector_store.get_all("knowledge_base")
        kid = str(knowledge_id or "").strip()
        return any(str(r.get("id", "")) == kid for r in rows)

    async def delete_rule(self, rule_id: str) -> None:
        self.vector_store.delete("rule_base", [str(rule_id)])

    async def delete_knowledge(self, knowledge_id: str) -> None:
        self.vector_store.delete("knowledge_base", [str(knowledge_id)])

    def preview_batch_delete(self, collection_name: str, ids: list[str]) -> dict[str, Any]:
        rows = self.vector_store.get_all(collection_name)
        by_id = {str(r.get("id", "")): r for r in rows}
        found: list[dict[str, Any]] = []
        not_found: list[str] = []
        for raw in ids:
            iid = str(raw or "").strip()
            if not iid:
                continue
            row = by_id.get(iid)
            if row is None:
                not_found.append(iid)
                continue
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            text = str((meta or {}).get("内容", "") or row.get("document", "") or "")
            found.append({"id": iid, "content_preview": text[:240]})
        return {"found": found, "not_found": not_found}

    def batch_delete(self, collection_name: str, ids: list[str]) -> dict[str, int]:
        rows = self.vector_store.get_all(collection_name)
        by_id = {str(r.get("id", "")) for r in rows}
        to_delete: list[str] = []
        not_found = 0
        for raw in ids:
            iid = str(raw or "").strip()
            if not iid:
                continue
            if iid in by_id:
                to_delete.append(iid)
            else:
                not_found += 1
        deleted = 0
        failed = 0
        if to_delete:
            try:
                self.vector_store.delete(collection_name, to_delete)
                deleted = len(to_delete)
                # Rebuild index after batch delete
                self.vector_store.rebuild_collection(collection_name)
            except Exception:
                failed = len(to_delete)
        return {"deleted": deleted, "failed": failed, "not_found": not_found}

    def _parse_file(self, content: bytes, file_type: str) -> list[dict[str, Any]]:
        ft = file_type.lower().strip(".")
        if ft == "csv":
            return self._parse_csv(content)
        if ft == "json":
            return self._parse_json(content)
        if ft in {"xlsx", "xls"}:
            return self._parse_excel(content)
        raise ValueError(f"不支持的文件格式: {file_type}")

    def _parse_csv(self, content: bytes) -> list[dict[str, Any]]:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    def _parse_json(self, content: bytes) -> list[dict[str, Any]]:
        text = content.decode("utf-8").strip()
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [dict(item) for item in data]
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass
        rows: list[dict[str, Any]] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            rows.append(dict(json.loads(line)))
        if not rows:
            raise ValueError("JSON格式必须是数组、对象或NDJSON逐行JSON")
        return rows

    def _parse_excel(self, content: bytes) -> list[dict[str, Any]]:
        import pandas as pd

        df = pd.read_excel(io.BytesIO(content))
        return [
            {str(k): ("" if pd.isna(v) else v) for k, v in row.items()}
            for row in df.to_dict("records")
        ]

    def _validate_records_tagged(
        self, records: list[dict[str, Any]], collection_name: str
    ) -> tuple[list[tuple[int, dict[str, Any]]], list[dict[str, Any]]]:
        required_fields = {
            "rule_base": ["内容"],
            "knowledge_base": ["主题", "内容"],
        }
        required = required_fields.get(collection_name, ["内容"])
        valid: list[tuple[int, dict[str, Any]]] = []
        errors: list[dict[str, Any]] = []
        for idx, record in enumerate(records, 1):
            missing = [
                f
                for f in required
                if f not in record or str(record.get(f, "")).strip() == ""
            ]
            if missing:
                errors.append(
                    {
                        "row": idx,
                        "record": record,
                        "error": f"缺少必填字段: {', '.join(missing)}",
                    }
                )
                continue
            if collection_name == "rule_base" and str(record.get("严重度", "")).strip() == "":
                record["严重度"] = "中"
            valid.append((idx, record))
        return valid, errors

    def _validate_records(
        self, records: list[dict[str, Any]], collection_name: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tagged, errors = self._validate_records_tagged(records, collection_name)
        return [r for _, r in tagged], errors

    def _check_duplicates(
        self, records: list[dict[str, Any]], collection_name: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        existing = self.vector_store.get_all(collection_name)
        existing_ids = {str(item.get("id")) for item in existing if item.get("id")}
        new_records: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        for idx, record in enumerate(records, 1):
            rid = str(record.get("id", "")).strip()
            if rid and rid in existing_ids:
                duplicates.append({"row": idx, "record": record, "error": "ID重复，已跳过"})
                continue
            new_records.append(record)
        return new_records, duplicates

    async def _batch_store(
        self, records: list[dict[str, Any]], collection_name: str
    ) -> None:
        if not records:
            return
        ids = [str(r.get("id", "")) or str(uuid.uuid4()) for r in records]
        documents = [self._extract_content(r, collection_name) for r in records]
        metadatas = records
        batch_size = 50
        for i in range(0, len(records), batch_size):
            self.vector_store.add(
                collection=collection_name,
                ids=ids[i : i + batch_size],
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
            )

    def _extract_content(self, record: dict[str, Any], collection_name: str) -> str:
        if collection_name == "rule_base":
            return str(record.get("内容", ""))
        if collection_name == "knowledge_base":
            return f"{record.get('主题', '')} {record.get('内容', '')}".strip()
        return str(record.get("内容", ""))

    # Compatibility CRUD methods used by older modules
    def list_items(self) -> list[KnowledgeItem]:
        rows = self.vector_store.get_all("knowledge_base")
        items: list[KnowledgeItem] = []
        for row in rows:
            meta = row.get("metadata", {})
            items.append(
                KnowledgeItem(
                    id=str(row.get("id", "")),
                    title=str(meta.get("主题", meta.get("title", ""))),
                    content=str(meta.get("内容", meta.get("content", row.get("document", "")))),
                    tags=list(meta.get("tags", [])) if isinstance(meta.get("tags", []), list) else [],
                )
            )
        return items

    def create_item(self, payload: KnowledgeCreate) -> KnowledgeItem:
        item = KnowledgeItem(title=payload.title, content=payload.content, tags=payload.tags)
        self.vector_store.add_one(
            "knowledge_base",
            item.id,
            f"{item.title} {item.content}",
            {"title": item.title, "content": item.content, "tags": item.tags, "主题": item.title, "内容": item.content},
        )
        return item

    def update_item(self, item_id: str, payload: KnowledgeUpdate) -> KnowledgeItem:
        current = next((x for x in self.list_items() if x.id == item_id), None)
        if current is None:
            raise ValueError(f"Knowledge item not found: {item_id}")
        updated = current.model_copy(
            update={
                "title": payload.title if payload.title is not None else current.title,
                "content": payload.content if payload.content is not None else current.content,
                "tags": payload.tags if payload.tags is not None else current.tags,
            }
        )
        self.vector_store.update_one(
            "knowledge_base",
            item_id,
            f"{updated.title} {updated.content}",
            {"title": updated.title, "content": updated.content, "tags": updated.tags, "主题": updated.title, "内容": updated.content},
        )
        return updated

    def delete_item(self, item_id: str) -> None:
        self.vector_store.delete("knowledge_base", [item_id])

    def search(self, query: str, limit: int = 3) -> list[KnowledgeItem]:
        rows = self.vector_store.query("knowledge_base", query, top_k=limit)
        results: list[KnowledgeItem] = []
        for row in rows:
            meta = row.get("metadata", {})
            results.append(
                KnowledgeItem(
                    id=str(row.get("id", "")),
                    title=str(meta.get("主题", meta.get("title", ""))),
                    content=str(meta.get("内容", meta.get("content", row.get("document", "")))),
                    tags=list(meta.get("tags", [])) if isinstance(meta.get("tags", []), list) else [],
                )
            )
        return results

