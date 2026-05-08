from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.models.case import AuditCase
from app.services.vector_store import VectorStore


class CaseService:
    """
    判例库服务：
    - 文件持久化（cases.json）
    - 向量检索（case_base collection）
    - CRUD + 批量导入
    """

    def __init__(
        self,
        vector_store: VectorStore,
        *,
        data_dir: Path,
        cases_filename: str = "cases.json",
        initial_filename: str = "initial_cases.json",
    ) -> None:
        self.vector_store = vector_store
        self.data_dir = data_dir
        self.cases_path = data_dir / cases_filename
        self.initial_path = data_dir / initial_filename
        self._cases: dict[str, AuditCase] = {}
        self._load_cases()

    def _load_cases(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 优先加载 cases.json；若没有则尝试 initial_cases.json 并落盘为 cases.json
        seed_path = self.cases_path if self.cases_path.exists() else self.initial_path
        if not seed_path.exists():
            return

        try:
            raw = json.loads(seed_path.read_text(encoding="utf-8"))
        except Exception:
            raw = []
        if not isinstance(raw, list):
            raw = []

        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                case = AuditCase.from_dict(item)
                self._cases[case.id] = case
            except Exception:
                continue

        # 若是从 initial 加载且 cases.json 不存在，写回一份 cases.json
        if seed_path == self.initial_path and not self.cases_path.exists() and self._cases:
            self._save_cases()

        self._sync_to_vector_store()

    def _save_cases(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = [c.to_dict() for c in self._cases.values()]
        self.cases_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _sync_to_vector_store(self) -> None:
        if not self._cases:
            return
        ids: list[str] = []
        docs: list[str] = []
        metas: list[dict[str, Any]] = []
        for case in self._cases.values():
            ids.append(case.id)
            docs.append(case.to_embedding_text())
            metas.append(
                {
                    "id": case.id,
                    "category": case.category,
                    "verdict": case.verdict,
                    "source": case.source,
                }
            )
        self.vector_store.add(collection="case_base", ids=ids, documents=docs, metadatas=metas)

    # ===== CRUD =====

    def create_case(self, case: AuditCase) -> AuditCase:
        if case.id in self._cases:
            raise ValueError(f"判例ID已存在: {case.id}")
        self._cases[case.id] = case
        self._save_cases()
        self.vector_store.add_one(
            collection="case_base",
            item_id=case.id,
            text=case.to_embedding_text(),
            metadata={
                "id": case.id,
                "category": case.category,
                "verdict": case.verdict,
                "source": case.source,
            },
        )
        return case

    def get_case(self, case_id: str) -> AuditCase | None:
        return self._cases.get(case_id)

    def list_cases(self, *, category: str | None = None, verdict: str | None = None) -> list[AuditCase]:
        out = list(self._cases.values())
        if category:
            out = [c for c in out if c.category == category]
        if verdict:
            out = [c for c in out if c.verdict == verdict]
        return out

    def update_case(self, case_id: str, updates: dict[str, Any]) -> AuditCase:
        if case_id not in self._cases:
            raise ValueError(f"判例不存在: {case_id}")
        case = self._cases[case_id]
        for k, v in (updates or {}).items():
            if hasattr(case, k):
                setattr(case, k, v)
        case.updated_at = datetime.utcnow().isoformat()
        self._cases[case_id] = case
        self._save_cases()
        self.vector_store.update_one(
            collection="case_base",
            item_id=case.id,
            text=case.to_embedding_text(),
            metadata={
                "id": case.id,
                "category": case.category,
                "verdict": case.verdict,
                "source": case.source,
            },
        )
        return case

    def delete_case(self, case_id: str) -> None:
        if case_id not in self._cases:
            raise ValueError(f"判例不存在: {case_id}")
        del self._cases[case_id]
        self._save_cases()
        self.vector_store.delete(collection="case_base", ids=[case_id])

    def import_cases(self, cases_data: list[dict[str, Any]]) -> dict[str, Any]:
        success = 0
        failed = 0
        errors: list[str] = []
        for data in cases_data:
            try:
                case = AuditCase.from_dict(dict(data))
                self.create_case(case)
                success += 1
            except Exception as exc:
                failed += 1
                errors.append(f"{data.get('id', 'unknown')}: {exc}")
        return {"success": success, "failed": failed, "errors": errors}

    # ===== 检索 =====

    async def search_cases(self, text: str, top_k: int = 3) -> list[dict[str, Any]]:
        rows = self.vector_store.query(collection="case_base", text=text, top_k=top_k)
        out: list[dict[str, Any]] = []
        for r in rows:
            cid = str(r.get("id", "") or "")
            case = self._cases.get(cid)
            if not case:
                continue
            dist = r.get("distance")
            try:
                d = float(dist) if dist is not None else None
            except Exception:
                d = None
            similarity = (1.0 / (1.0 + d)) if (d is not None and d >= 0) else 0.0
            out.append({"case": case, "similarity": similarity, "matched_text": r.get("document", "")})
        return out

