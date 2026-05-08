from __future__ import annotations

import json
import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.agents.adversarial_detective import AdversarialDetective
from app.agents.case_executor import CaseExecutor
from app.agents.chief_judge import ChiefJudge
from app.agents.confidence_evaluator import ConfidenceEvaluator
from app.agents.rule_executor import RuleExecutor
from app.agents.text_cleaner import TextCleaner
from app.core.batch_audit_manager import BatchAuditManager
from app.core.blackboard import Blackboard
from app.core.config_manager import ConfigManager
from app.models.audit import AuditRequest, AuditResult
from app.models.config import ModelConfig, TestConnectionResult
from app.routers.batch_audit import create_batch_audit_router
from app.routers.export_excel import create_export_router
from app.routers.knowledge_batch import create_knowledge_batch_router
from app.routers.knowledge_delete import create_knowledge_delete_router
from app.services.case_service import CaseService
from app.services.knowledge_service import KnowledgeService
from app.services.llm_client import LLMClient
from app.services.rag_service import RAGService
from app.services.audit_runner import run_complete_audit
from app.workflows.audit_orchestration import run_audit
from app.services.vector_store import VectorStore
from app.api.cases import create_cases_router

app = FastAPI(
    title="多Agent内容审核系统后端",
    description="多Agent UGC内容安全审核核心服务",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _normalize_knowledge_store_row(row: dict[str, Any]) -> dict[str, Any]:
    """将 Chroma 返回行展开，便于前端直接读 分类/内容 等字段。"""
    mid = str(row.get("id", "") or "")
    meta_raw = row.get("metadata")
    meta = dict(meta_raw) if isinstance(meta_raw, dict) else {}
    doc = str(row.get("document", "") or "")
    out: dict[str, Any] = {"id": mid, "document": doc, "metadata": meta}
    out.update(meta)
    if "内容" in meta:
        out.setdefault("content", meta.get("内容"))
    return out


def _list_knowledge_bundle(
    collection: str,
    *,
    q: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    if q.strip():
        raw = vector_store.query(
            collection=collection,
            text=q,
            top_k=min(50000, 100_000),
        )
        items = [_normalize_knowledge_store_row(x) for x in raw]
        n = len(items)
        return {"items": items, "total": n, "page": 1, "page_size": n or 1, "had_query": True}
    rows = vector_store.get_all(collection=collection)
    total = len(rows)
    if page_size == 0:
        chunk = rows
        eff_ps = max(total, 1)
    else:
        start = (page - 1) * page_size
        chunk = rows[start : start + page_size]
        eff_ps = page_size
    items = [_normalize_knowledge_store_row(x) for x in chunk]
    return {"items": items, "total": total, "page": page, "page_size": eff_ps, "had_query": False}


data_dir = __import__("pathlib").Path(__file__).resolve().parents[1] / "data"
data_dir.mkdir(parents=True, exist_ok=True)
agent_config_path = data_dir / "agent_configs.json"
config_manager = ConfigManager(data_dir)
llm_client = LLMClient(config_manager)

blackboard = Blackboard()
vector_store = VectorStore()
knowledge_service = KnowledgeService(vector_store)
case_service = CaseService(vector_store, data_dir=data_dir)
app.include_router(create_knowledge_batch_router(vector_store, knowledge_service))
app.include_router(create_knowledge_delete_router(knowledge_service))
app.include_router(create_export_router(blackboard))
app.include_router(create_cases_router(case_service))


class ResponseMessage:
    AUDIT_STARTED = "审核已开始"
    AUDIT_COMPLETED = "审核完成"
    AGENT_ENABLED = "Agent已启用"
    AGENT_DISABLED = "Agent已禁用"
    CONFIG_SAVED = "配置已保存"
    RULE_ADDED = "规则已添加"
    RULE_UPDATED = "规则已更新"
    RULE_DELETED = "规则已删除"
    IMPORT_SUCCESS = "导入成功"
    IMPORT_FAILED = "导入失败"
    CONNECTION_SUCCESS = "连接成功"
    CONNECTION_FAILED = "连接失败"


agent_configs: dict[str, dict[str, Any]] = {
    "text_cleaner": {"enabled": True, "zone": "preprocess_zone", "temperature": 0.0, "model": "gpt-3.5-turbo", "prompt": "", "top_k": 0},
    "rule_executor": {"enabled": True, "zone": "rule_zone", "temperature": 0.1, "model": "gpt-3.5-turbo", "prompt": "", "top_k": 5},
    "adversarial_detective": {"enabled": True, "zone": "adversarial_zone", "temperature": 0.2, "model": "gpt-3.5-turbo", "prompt": "", "top_k": 5},
    "case_executor": {"enabled": True, "zone": "case_zone", "temperature": 0.2, "model": "gpt-3.5-turbo", "prompt": "", "top_k": 3},
    "confidence_evaluator": {
        "enabled": True,
        "zone": "evaluation_zone",
        "temperature": 0.1,
        "model": "gpt-3.5-turbo",
        "prompt": "",
        "top_k": 0,
        "weights": {"rule_executor": 0.9, "adversarial_detective": 0.85, "case_executor": 0.8},
    },
    "chief_judge": {
        "enabled": True,
        "zone": "final_zone",
        "temperature": 0.0,
        "model": "gpt-4o",
        "prompt": "",
        "top_k": 5,
        "trigger_conditions": ["conflict", "uncertainty", "suggest_arbitration"],
    },
}


def _load_agent_configs() -> dict[str, dict[str, Any]]:
    if not agent_config_path.exists():
        return agent_configs
    try:
        loaded = json.loads(agent_config_path.read_text(encoding="utf-8"))
    except Exception:
        return agent_configs
    if not isinstance(loaded, dict):
        return agent_configs
    merged = {**agent_configs}
    for name, cfg in loaded.items():
        if name in merged and isinstance(cfg, dict):
            merged[name].update(cfg)
    return merged


def _save_agent_configs(configs: dict[str, dict[str, Any]]) -> None:
    agent_config_path.write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")


agent_configs = _load_agent_configs()


async def process_audit(audit_id: str, content: dict, cluster_id: str = "standard"):
    """处理审核流程——真正调用 Multi-Agent 审核"""
    text = content.get("text", "")
    category = content.get("category", "politics")

    await blackboard.write_entry(
        audit_id=audit_id,
        agent="orchestrator",
        zone="orchestrator",
        phase="started",
        content=f"开始审核: {text[:50]}...",
        data={"cluster_id": cluster_id, "category": category},
    )

    result = await run_audit(text, category)

    stages = result.get("log", [])
    total = len(stages)

    agent_map = {
        "variant_pre_check": ("adversarial_detective", "变体预检"),
        "rule_enforcer": ("rule_enforcer", "规则执行员"),
        "adversarial_detective": ("adversarial_detective", "对抗侦探"),
        "case_executor": ("case_executor", "判例执行员"),
        "confidence_assessor": ("confidence_assessor", "置信度评估员"),
        "chief_judge": ("chief_judge", "大法官"),
        "aggregator": ("aggregator", "聚合器"),
    }

    for i, log_entry in enumerate(stages):
        stage = log_entry.get("stage", "unknown")
        agent_id, agent_name = agent_map.get(stage, (stage, stage))
        payload = log_entry.get("result", log_entry.get("assessment", log_entry))
        await blackboard.write_entry(
            audit_id=audit_id,
            agent=agent_id,
            zone=agent_id,
            phase=stage,
            content=f"{stage}: {str(payload)[:100]}",
            data={"index": i, "total": total, "payload": payload},
        )
        await blackboard.write_entry(
            audit_id=audit_id,
            agent="system",
            zone="orchestrator",
            phase="phase_change",
            content=agent_name,
            data={"currentNode": agent_id, "progress": (i + 1) / total * 100 if total > 0 else 0},
        )
        await asyncio.sleep(0.5)

    await blackboard.write_entry(
        audit_id=audit_id,
        agent="system",
        zone="orchestrator",
        phase="completed",
        content="审核完成",
        data={
            "auditId": audit_id,
            "result": result.get("final_verdict"),
            "confidence": result.get("final_confidence"),
            "summary": result.get("final_reason"),
            "log": [entry.get("stage", "unknown") for entry in stages],
        },
    )


async def _batch_run_audit(audit_id: str, content: str, strategy: str) -> AuditResult:
    return await run_complete_audit(
        blackboard=blackboard,
        vector_store=vector_store,
        llm_client=llm_client,
        case_service=case_service,
        audit_id=audit_id,
        content=content,
        runtime_cfg=None,
        strategy=strategy,
    )


batch_audit_manager = BatchAuditManager(_batch_run_audit, discard_audit=blackboard.discard_audit)
app.include_router(create_batch_audit_router(batch_audit_manager))


@app.post("/api/audit", response_model=AuditResult)
async def start_audit(payload: AuditRequest) -> AuditResult:
    audit_id = payload.audit_id or str(uuid4())
    # process_audit 负责真正广播 workflow；这里直接返回真实审核结果供前端/接口使用
    asyncio.create_task(process_audit(audit_id, {"text": payload.content, "category": (payload.config or {}).get("category", "politics")}, "standard"))
    return await run_complete_audit(
        blackboard=blackboard,
        vector_store=vector_store,
        llm_client=llm_client,
        case_service=case_service,
        audit_id=audit_id,
        content=payload.content,
        runtime_cfg=payload.config,
        strategy="one_vote_veto",
    )


@app.websocket("/ws/audit/{audit_id}")
async def ws_audit(audit_id: str, websocket: WebSocket) -> None:
    await blackboard.connect(audit_id, websocket)
    try:
        for entry in blackboard.get_logs(audit_id):
            await websocket.send_json(entry.model_dump(mode="json"))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        blackboard.disconnect(audit_id, websocket)


@app.get("/api/agents")
async def get_agents() -> dict[str, dict[str, Any]]:
    return agent_configs


@app.put("/api/agents/{name}")
async def update_agent(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if name not in agent_configs:
        raise HTTPException(status_code=404, detail="Agent不存在")
    agent_configs[name].update(payload)
    _save_agent_configs(agent_configs)
    try:
        system_cfg = config_manager.get()
        if name in system_cfg.agents:
            agent_obj = system_cfg.agents[name]
            if "enabled" in payload:
                agent_obj.enabled = bool(payload["enabled"])
            if "prompt" in payload:
                agent_obj.prompt = str(payload["prompt"] or "")
            if "threshold" in payload:
                agent_obj.threshold = float(payload["threshold"])
        config_manager.update(system_cfg)
    except Exception:
        pass
    return agent_configs[name]


@app.post("/api/agents/{name}/test")
async def test_agent(name: str, payload: AuditRequest) -> AuditResult:
    if name not in agent_configs:
        raise HTTPException(status_code=404, detail="Agent不存在")
    audit_id = str(uuid4())
    rag_service = RAGService(vector_store)
    blackboard.set_state(audit_id, "content", payload.content)
    blackboard.set_state(audit_id, "config", payload.config or {})
    blackboard.set_agent_status(audit_id, name, "running")
    if name == "chief_judge":
        for dep in ["rule_executor", "adversarial_detective", "case_executor", "confidence_evaluator"]:
            blackboard.set_agent_result(audit_id, dep, {"agent": dep, "verdict": "not_participate", "reason": "test mode", "confidence": 1.0})
    if name == "text_cleaner":
        agent = TextCleaner(name=name, zone=agent_configs[name]["zone"], blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    elif name == "rule_executor":
        agent = RuleExecutor(name=name, zone=agent_configs[name]["zone"], blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    elif name == "adversarial_detective":
        agent = AdversarialDetective(name=name, zone=agent_configs[name]["zone"], blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    elif name == "case_executor":
        agent = CaseExecutor(name=name, zone=agent_configs[name]["zone"], blackboard=blackboard, llm_client=llm_client, rag_service=rag_service, case_service=case_service)
    elif name == "confidence_evaluator":
        for dep in ["rule_executor", "adversarial_detective", "case_executor"]:
            blackboard.set_agent_result(audit_id, dep, {"agent": dep, "verdict": "normal", "reason": "test seed", "confidence": 0.8})
        agent = ConfidenceEvaluator(name=name, zone=agent_configs[name]["zone"], blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    else:
        agent = ChiefJudge(name=name, zone=agent_configs[name]["zone"], blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    agent.bind_audit(audit_id)
    try:
        timeout = 25.0
        if name in {"rule_executor", "adversarial_detective", "case_executor"}:
            timeout = 120.0
        elif name in {"confidence_evaluator", "chief_judge"}:
            timeout = 90.0
        result = await asyncio.wait_for(agent.execute(payload.content), timeout=timeout)
    except Exception as exc:
        result = {"agent": name, "verdict": "not_participate", "reason": str(exc), "confidence": 0.0}
    blackboard.set_agent_result(audit_id, name, result)
    verdict = result.get("verdict", "normal")
    confidence = float(result.get("confidence", 0.0))
    fv = verdict if str(verdict) in {"violation", "normal"} else str(verdict)
    blackboard.set_state(audit_id, "final_verdict", fv)
    blackboard.set_state(audit_id, "confidence", confidence)
    return AuditResult(audit_id=audit_id, content=payload.content, final_verdict=fv, confidence=confidence, logs=blackboard.get_logs(audit_id), agent_results=blackboard.get_agent_results(audit_id))


@app.post("/api/knowledge/item/{bucket}")
async def create_knowledge(bucket: str, payload: dict[str, Any]) -> dict[str, str]:
    if bucket not in {"rules", "kb"}:
        raise HTTPException(status_code=404, detail="知识库分组不存在")
    collection = "rule_base" if bucket == "rules" else "knowledge_base"
    item_id = payload.get("id", str(uuid4()))
    text = payload.get("text", "")
    vector_store.add_one(collection=collection, item_id=item_id, text=text, metadata=payload)
    return {"id": item_id, "status": "created", "message": ResponseMessage.RULE_ADDED}


@app.get("/api/knowledge/rules")
async def knowledge_rules_list(q: str = "", page: int = Query(1, ge=1), page_size: int = Query(9999, ge=0, le=100_000)) -> dict[str, Any]:
    return _list_knowledge_bundle("rule_base", q=q.strip(), page=page, page_size=page_size)


@app.get("/api/knowledge/kb")
async def knowledge_kb_list(q: str = "", page: int = Query(1, ge=1), page_size: int = Query(9999, ge=0, le=100_000)) -> dict[str, Any]:
    return _list_knowledge_bundle("knowledge_base", q=q.strip(), page=page, page_size=page_size)


@app.get("/api/knowledge/item/{bucket}")
async def list_knowledge(bucket: str, q: str = "", page: int = Query(1, ge=1), page_size: int = Query(9999, ge=0, le=100_000), top_k: int | None = Query(None, ge=1, le=100_000)) -> dict[str, Any] | list[dict[str, Any]]:
    if bucket not in {"rules", "kb"}:
        raise HTTPException(status_code=404, detail="知识库分组不存在")
    collection = "rule_base" if bucket == "rules" else "knowledge_base"
    if top_k is not None:
        if q:
            raw = vector_store.query(collection=collection, text=q, top_k=top_k)
        else:
            raw = vector_store.get_all(collection=collection)[:top_k]
        return [_normalize_knowledge_store_row(x) for x in raw]
    return _list_knowledge_bundle(collection, q=q.strip(), page=page, page_size=page_size)


@app.put("/api/knowledge/item/{bucket}/{item_id}")
async def update_knowledge(bucket: str, item_id: str, payload: dict[str, Any]) -> dict[str, str]:
    if bucket not in {"rules", "kb"}:
        raise HTTPException(status_code=404, detail="知识库分组不存在")
    collection = "rule_base" if bucket == "rules" else "knowledge_base"
    vector_store.update_one(collection=collection, item_id=item_id, text=payload.get("text", ""), metadata=payload)
    return {"id": item_id, "status": "updated", "message": ResponseMessage.RULE_UPDATED}


@app.delete("/api/knowledge/item/{bucket}/{item_id}")
async def delete_knowledge(bucket: str, item_id: str) -> dict[str, str]:
    if bucket not in {"rules", "kb"}:
        raise HTTPException(status_code=404, detail="知识库分组不存在")
    collection = "rule_base" if bucket == "rules" else "knowledge_base"
    vector_store.delete(collection=collection, ids=[item_id])
    return {"id": item_id, "status": "deleted", "message": ResponseMessage.RULE_DELETED}


@app.post("/api/knowledge/import-json")
async def import_knowledge_json(payload: dict[str, Any]) -> dict[str, Any]:
    target = payload.get("target", "kb")
    items = payload.get("items", [])
    if target not in {"rules", "kb", "cases"}:
        raise HTTPException(status_code=400, detail="target必须是rules|kb|cases")
    collection_map = {"rules": "rule_base", "kb": "knowledge_base", "cases": "case_base"}
    collection = collection_map[target]
    imported = 0
    for item in items:
        item_id = item.get("id", str(uuid4()))
        vector_store.add_one(collection=collection, item_id=item_id, text=item.get("text", ""), metadata=item)
        imported += 1
    return {"target": target, "imported": imported, "message": ResponseMessage.IMPORT_SUCCESS}


@app.post("/api/knowledge/preview")
async def preview_import(file: UploadFile = File(...), collection: str = Form(...)) -> dict[str, Any]:
    collection_map = {"rule_base": "rule_base", "knowledge_base": "knowledge_base", "rules": "rule_base", "kb": "knowledge_base"}
    if collection not in collection_map:
        raise HTTPException(status_code=400, detail="collection必须是rule_base或knowledge_base")
    content = await file.read()
    file_type = (file.filename or "").split(".")[-1]
    records = knowledge_service._parse_file(content, file_type)
    valid, errors = knowledge_service._validate_records(records, collection_map[collection])
    return {"file_name": file.filename or "", "file_type": file_type, "total_rows": len(records), "valid_count": len(valid), "error_count": len(errors), "headers": list(records[0].keys()) if records else [], "sample_rows": valid[:5], "errors": errors[:10]}


@app.post("/api/knowledge/import")
async def batch_import(file: UploadFile = File(...), collection: str = Form(...)) -> dict[str, Any]:
    collection_map = {"rule_base": "rule_base", "knowledge_base": "knowledge_base", "rules": "rule_base", "kb": "knowledge_base"}
    if collection not in collection_map:
        raise HTTPException(status_code=400, detail="collection必须是rule_base或knowledge_base")
    content = await file.read()
    file_type = (file.filename or "").split(".")[-1]
    result = await knowledge_service.batch_import(collection_map[collection], content, file_type)
    return result.model_dump(mode="json")


@app.get("/api/knowledge/template")
async def download_template(collection: str, format: str = "csv") -> Response:
    collection_map = {"rule_base": "rule_base", "knowledge_base": "knowledge_base", "rules": "rule_base", "kb": "knowledge_base"}
    c = collection_map.get(collection)
    if c is None:
        raise HTTPException(status_code=400, detail="collection必须是rule_base或knowledge_base")
    if c == "rule_base":
        csv_tpl = "id,分类,内容,严重度,示例,备注\n001,政治敏感,禁止讨论政治事件,高,这是一个政治敏感示例,适用于所有平台"
        json_tpl = json.dumps([{"id": "001", "分类": "政治敏感", "内容": "禁止讨论政治事件", "严重度": "高", "示例": "这是一个政治敏感示例", "备注": "适用于所有平台"}], ensure_ascii=False)
    else:
        csv_tpl = "id,主题,内容,关联规则,标签\n001,政治概念,政治事件指国家重大决策...,政治敏感|政治人物,基础概念"
        json_tpl = json.dumps([{"id": "001", "主题": "政治概念", "内容": "政治事件指国家重大决策...", "关联规则": "政治敏感|政治人物", "标签": "基础概念"}], ensure_ascii=False)
    if format == "json":
        content = json_tpl
        media = "application/json"
        ext = "json"
    else:
        content = csv_tpl
        media = "text/csv"
        ext = "csv"
    return Response(content=content, media_type=media, headers={"Content-Disposition": f"attachment; filename={c}_template.{ext}"})


@app.get("/api/logs/export")
async def export_logs() -> list[dict[str, Any]]:
    exported: list[dict[str, Any]] = []
    for audit_id, entries in blackboard.get_all_logs().items():
        for entry in entries:
            exported.append({"audit_id": audit_id, "timestamp": entry.timestamp, "agent": entry.agent, "zone": entry.zone, "phase": entry.phase, "content": entry.content, "raw_llm_output": entry.raw_llm_output, "data": entry.data, "exported_at": f"{datetime.utcnow().isoformat()}Z"})
    return exported


@app.get("/api/model-configs", response_model=list[ModelConfig])
async def list_model_configs() -> list[ModelConfig]:
    return config_manager.list_model_configs()


@app.post("/api/model-configs", response_model=ModelConfig)
async def create_model_config(payload: ModelConfig) -> ModelConfig:
    return config_manager.create_model_config(payload)


@app.get("/api/model-configs/{config_id}", response_model=ModelConfig)
async def get_model_config(config_id: str) -> ModelConfig:
    try:
        return config_manager.get_model_config(config_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/model-configs/{config_id}", response_model=ModelConfig)
async def update_model_config(config_id: str, payload: ModelConfig) -> ModelConfig:
    try:
        updated = config_manager.update_model_config(config_id, payload)
        if updated.is_default:
            llm_client.switch_config(updated.id)
        return updated
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/model-configs/{config_id}")
async def delete_model_config(config_id: str) -> dict[str, str]:
    try:
        config_manager.delete_model_config(config_id)
        llm_client._init_client()
        return {"message": "删除成功"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/model-configs/{config_id}/test", response_model=TestConnectionResult)
async def test_model_config(config_id: str) -> TestConnectionResult:
    try:
        config = ConfigManager.apply_llm_env_overlay(config_manager.get_model_config(config_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await llm_client.test_connection(config)


@app.post("/api/model-configs/{config_id}/default", response_model=ModelConfig)
async def set_default_model_config(config_id: str) -> ModelConfig:
    try:
        config = config_manager.set_default_model_config(config_id)
        llm_client.switch_config(config_id)
        return config
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
