from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response, UploadFile

from app.models.case import AuditCase
from app.services.case_service import CaseService


def _parse_case_rows_from_xlsx_or_csv(content: bytes, filename: str) -> list[dict[str, Any]]:
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xls"):
        import pandas as pd
        from io import BytesIO

        df = pd.read_excel(BytesIO(content))
        df = df.fillna("")
        return df.to_dict(orient="records")
    if name.endswith(".csv"):
        import pandas as pd
        from io import BytesIO

        df = pd.read_csv(BytesIO(content))
        df = df.fillna("")
        return df.to_dict(orient="records")
    if name.endswith(".json"):
        import json

        data = json.loads(content.decode("utf-8"))
        return list(data) if isinstance(data, list) else []
    raise HTTPException(status_code=400, detail="仅支持 csv/json/xlsx/xls")


def create_cases_router(case_service: CaseService) -> APIRouter:
    router = APIRouter(prefix="/api/cases", tags=["cases"])

    @router.get("")
    async def list_cases(category: str | None = None, verdict: str | None = None) -> dict[str, Any]:
        data = case_service.list_cases(category=category, verdict=verdict)
        return {"success": True, "data": [c.to_dict() for c in data], "total": len(data)}

    @router.post("")
    async def create_case(payload: dict[str, Any]) -> dict[str, Any]:
        created = case_service.create_case(AuditCase.from_dict(payload))
        return {"success": True, "data": created.to_dict()}

    @router.put("/{case_id}")
    async def update_case(case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        updated = case_service.update_case(case_id, payload)
        return {"success": True, "data": updated.to_dict()}

    @router.delete("/{case_id}")
    async def delete_case(case_id: str) -> dict[str, Any]:
        case_service.delete_case(case_id)
        return {"success": True}

    @router.post("/import")
    async def import_cases(file: UploadFile) -> dict[str, Any]:
        content = await file.read()
        rows = _parse_case_rows_from_xlsx_or_csv(content, file.filename or "")
        result = case_service.import_cases(rows)
        return {"success": True, "data": result}

    @router.post("/import-xlsx")
    async def import_cases_xlsx(file: UploadFile) -> dict[str, Any]:
        content = await file.read()
        rows = _parse_case_rows_from_xlsx_or_csv(content, file.filename or "")
        result = case_service.import_cases(rows)
        return {"success": True, "data": result}

    @router.get("/template")
    async def download_template(format: str = "csv") -> Response:
        csv_tpl = "id,text,verdict,violation_reason,category,confidence,matched_rules,source\nCASE_001,示例违规文本,violation,包含违规内容,政治敏感,0.95,规则A|规则B,manual"
        json_tpl = """[
  {
    "id": "CASE_001",
    "text": "示例违规文本",
    "verdict": "violation",
    "violation_reason": "包含违规内容",
    "category": "政治敏感",
    "confidence": 0.95,
    "matched_rules": ["规则A", "规则B"],
    "source": "manual"
  }
]"""
        if format == "json":
            return Response(content=json_tpl, media_type="application/json", headers={"Content-Disposition": "attachment; filename=cases_template.json"})
        return Response(content=csv_tpl, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=cases_template.csv"})

    return router
