"""单次完整审核流水线，供 `/api/audit` 与批量审核复用。"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any


def _env_timeout_seconds(name: str, default: float) -> float:
    """毫秒级慢推理时调高：AUDIT_PRIMARY_AGENT_TIMEOUT_SEC / AUDIT_JUDGE_TIMEOUT_SEC"""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(30.0, float(raw))
    except ValueError:
        return default


# 单次 Agent 卡在 LLM/RAG 上时原先 150s 易触发 TimeoutError（与 OpenAI SDK 自带的 HTTP 超时无关）
_PRIMARY_AGENT_TIMEOUT_SEC = _env_timeout_seconds("AUDIT_PRIMARY_AGENT_TIMEOUT_SEC", 300.0)
_PREPROCESS_TIMEOUT_SEC = _env_timeout_seconds("AUDIT_PREPROCESS_TIMEOUT_SEC", 60.0)
_CONF_EVAL_TIMEOUT_SEC = _env_timeout_seconds("AUDIT_CONF_EVAL_TIMEOUT_SEC", 120.0)
_JUDGE_TIMEOUT_SEC = _env_timeout_seconds("AUDIT_JUDGE_TIMEOUT_SEC", 240.0)

from app.agents.text_cleaner import TextCleaner
from app.agents.adversarial_detective import AdversarialDetective
from app.agents.case_executor import CaseExecutor
from app.agents.chief_judge import ChiefJudge
from app.agents.confidence_evaluator import ConfidenceEvaluator
from app.agents.rule_executor import RuleExecutor
from app.core.aggregator import Aggregator
from app.core.blackboard import Blackboard
from app.models.audit import AuditResult
from app.services.llm_client import LLMClient
from app.services.rag_service import RAGService
from app.services.vector_store import VectorStore
from app.workflows.audit_orchestration import create_audit_graph, run_audit as run_workflow_audit

_AUDIT_STARTED = "审核已开始"


async def run_complete_audit(
    *,
    blackboard: Blackboard,
    vector_store: VectorStore,
    llm_client: LLMClient,
    case_service: Any | None = None,
    audit_id: str,
    content: str,
    runtime_cfg: dict[str, Any] | None,
    strategy: str = "one_vote_veto",
) -> AuditResult:
    # 先构建图，确保 workflow 已接入现有后端入口，便于后续按图调度/调试。
    _workflow = create_audit_graph()
    try:
        workflow_state = await run_workflow_audit(content, str(runtime_cfg.get("category") or "politics"))
        blackboard.set_state(audit_id, "workflow_state", workflow_state)
        blackboard.set_state(audit_id, "variant_check", workflow_state.get("variant_check"))
        if workflow_state.get("final_verdict"):
            blackboard.set_state(audit_id, "final_verdict", workflow_state.get("final_verdict"))
        if workflow_state.get("final_confidence") is not None:
            blackboard.set_state(audit_id, "confidence", float(workflow_state.get("final_confidence") or 0.0))
        if workflow_state.get("final_reason"):
            blackboard.set_state(audit_id, "final_reason", str(workflow_state.get("final_reason") or ""))
        if workflow_state.get("variant_check"):
            blackboard.set_state(audit_id, "variant_check", workflow_state.get("variant_check") or {})
            await blackboard.write_entry(
                audit_id=audit_id,
                agent="system",
                zone="orchestrator",
                phase="variant_pre_check",
                content="变体预检完成",
                data=workflow_state.get("variant_check") or {},
            )
        if workflow_state.get("detective_result"):
            blackboard.set_agent_result(audit_id, "adversarial_detective", workflow_state.get("detective_result") or {})
            await blackboard.write_entry(
                audit_id=audit_id,
                agent="adversarial_detective",
                zone="adversarial_zone",
                phase="workflow_result",
                content="对抗侦探参与完成",
                data=workflow_state.get("detective_result") or {},
            )
        if workflow_state.get("case_result"):
            blackboard.set_agent_result(audit_id, "case_executor", workflow_state.get("case_result") or {})
            await blackboard.write_entry(
                audit_id=audit_id,
                agent="case_executor",
                zone="case_zone",
                phase="workflow_result",
                content="判例执行员完成",
                data=workflow_state.get("case_result") or {},
            )
        if workflow_state.get("assessment"):
            blackboard.set_agent_result(audit_id, "confidence_evaluator", {
                "agent": "confidence_evaluator",
                "verdict": str((workflow_state.get("assessment") or {}).get("aggregated_verdict") or "review"),
                "reason": str((workflow_state.get("assessment") or {}).get("reason") or "workflow assessment"),
                "confidence": float((workflow_state.get("assessment") or {}).get("aggregated_confidence") or 0.0),
                "suggest_arbitration": bool((workflow_state.get("assessment") or {}).get("should_arbitrate") or False),
            })
            await blackboard.write_entry(
                audit_id=audit_id,
                agent="confidence_evaluator",
                zone="evaluation_zone",
                phase="workflow_result",
                content="置信度评估完成",
                data=workflow_state.get("assessment") or {},
            )
        if workflow_state.get("judge_result"):
            blackboard.set_agent_result(audit_id, "chief_judge", workflow_state.get("judge_result") or {})
            await blackboard.write_entry(
                audit_id=audit_id,
                agent="chief_judge",
                zone="final_zone",
                phase="workflow_result",
                content="大法官结果已写回",
                data=workflow_state.get("judge_result") or {},
            )
    except Exception as exc:
        await blackboard.write_entry(
            audit_id=audit_id,
            agent="system",
            zone="orchestrator",
            phase="workflow执行失败",
            content="workflow执行失败，回退现有流水线",
            data={"error": repr(exc), "error_type": type(exc).__name__},
        )

    rag_service = RAGService(vector_store)
    aggregator = Aggregator({"strategy": strategy, "chief_judge_priority": True})
    runtime_cfg = runtime_cfg or {}
    model_config_id = runtime_cfg.get("model_config_id")
    if model_config_id:
        try:
            llm_client.switch_config(str(model_config_id))
        except Exception as exc:
            await blackboard.write_entry(
                audit_id=audit_id,
                agent="system",
                zone="orchestrator",
                phase="模型切换失败",
                content="指定模型配置不可用，回退默认模型",
                data={"error": str(exc), "model_config_id": model_config_id},
            )
            llm_client._init_client()
    temp = runtime_cfg.get("temperature")
    if isinstance(temp, (int, float)):
        llm_client.temperature = float(temp)

    blackboard.set_state(audit_id, "config", runtime_cfg)
    blackboard.set_state(audit_id, "category", str((runtime_cfg or {}).get("category") or "general").strip())
    blackboard.set_state(audit_id, "_created_at_iso", datetime.utcnow().replace(microsecond=0).isoformat() + "Z")
    blackboard.set_state(audit_id, "raw_content", content)
    blackboard.set_state(audit_id, "content", content)
    blackboard.set_agent_status(audit_id, "text_cleaner", "running")
    blackboard.set_agent_status(audit_id, "rule_executor", "pending")
    blackboard.set_agent_status(audit_id, "adversarial_detective", "pending")
    blackboard.set_agent_status(audit_id, "case_executor", "pending")
    blackboard.set_agent_status(audit_id, "confidence_evaluator", "pending")
    blackboard.set_agent_status(audit_id, "chief_judge", "pending")

    async def set_phase(phase: str, **data: Any) -> None:
        blackboard.set_state(audit_id, "audit_phase", phase)
        await blackboard.write_entry(
            audit_id=audit_id,
            agent="system",
            zone="orchestrator",
            phase="phase_change",
            content=phase,
            data=data,
        )

    await blackboard.write_entry(
        audit_id=audit_id,
        agent="system",
        zone="orchestrator",
        phase="启动审核",
        content=_AUDIT_STARTED,
        data={"content_length": len(content)},
    )
    cleaner = TextCleaner(name="text_cleaner", zone="preprocess_zone", blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    rule_agent = RuleExecutor(name="rule_executor", zone="rule_zone", blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    adv_agent = AdversarialDetective(name="adversarial_detective", zone="adversarial_zone", blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    case_agent = CaseExecutor(name="case_executor", zone="case_zone", blackboard=blackboard, llm_client=llm_client, rag_service=rag_service, case_service=case_service)
    judge_agent = ChiefJudge(name="chief_judge", zone="final_zone", blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    conf_eval_agent = ConfidenceEvaluator(name="confidence_evaluator", zone="evaluation_zone", blackboard=blackboard, llm_client=llm_client, rag_service=rag_service)
    for agent in [cleaner, rule_agent, adv_agent, case_agent, conf_eval_agent, judge_agent]:
        agent.bind_audit(audit_id)

    cleaned_content = content
    await set_phase("cleaning")
    try:
        result = await asyncio.wait_for(cleaner.execute(content), timeout=_PREPROCESS_TIMEOUT_SEC)
        blackboard.set_agent_result(audit_id, "text_cleaner", result)
        cleaned_content = str(blackboard.get_state(audit_id, "preprocessed_content", "") or "").strip() or content
        blackboard.set_state(audit_id, "content", cleaned_content)
        blackboard.set_agent_status(audit_id, "text_cleaner", "completed")
    except Exception as exc:
        await blackboard.write_entry(audit_id=audit_id, agent="text_cleaner", zone="preprocess_zone", phase="执行异常", content="text_cleaner执行失败", data={"error": repr(exc), "error_type": type(exc).__name__})
        blackboard.set_agent_result(audit_id, "text_cleaner", {"agent": "text_cleaner", "verdict": "not_participate", "reason": repr(exc), "confidence": 0.0})
        cleaned_content = content
        blackboard.set_state(audit_id, "preprocessed_content", cleaned_content)
        blackboard.set_state(audit_id, "cleaned_text", cleaned_content)
        blackboard.set_state(audit_id, "risk_signals", [])
        blackboard.set_state(audit_id, "was_cleaned", False)
        blackboard.set_state(audit_id, "content", cleaned_content)
        blackboard.set_agent_status(audit_id, "text_cleaner", "completed")

    await set_phase("cleaned", cleaned_len=len(cleaned_content))
    await blackboard.wait_for_agents(audit_id, ["text_cleaner"], timeout=_PREPROCESS_TIMEOUT_SEC)

    async def run_primary_agents() -> None:
        preprocess = str(blackboard.get_state(audit_id, "preprocessed_content", "") or cleaned_content)
        blackboard.set_agent_status(audit_id, "rule_executor", "running")
        blackboard.set_agent_status(audit_id, "adversarial_detective", "running")
        blackboard.set_agent_status(audit_id, "case_executor", "running")
        await set_phase("first_wave")

        results = await asyncio.gather(
            asyncio.wait_for(rule_agent.run_first_pass(preprocess), timeout=_PRIMARY_AGENT_TIMEOUT_SEC),
            asyncio.wait_for(adv_agent.execute(preprocess), timeout=_PRIMARY_AGENT_TIMEOUT_SEC),
            asyncio.wait_for(case_agent.execute(preprocess), timeout=_PRIMARY_AGENT_TIMEOUT_SEC),
            return_exceptions=True,
        )

        for agent_name, result in zip(["rule_executor", "adversarial_detective", "case_executor"], results):
            if isinstance(result, Exception):
                await blackboard.write_entry(audit_id=audit_id, agent=agent_name, zone="orchestrator", phase="执行异常", content=f"{agent_name}执行失败", data={"error": repr(result), "error_type": type(result).__name__})
                blackboard.set_agent_result(audit_id, agent_name, {"agent": agent_name, "verdict": "not_participate", "reason": repr(result), "confidence": 0.0})
                blackboard.set_agent_status(audit_id, agent_name, "completed")
            else:
                blackboard.set_agent_result(audit_id, agent_name, result)
                blackboard.set_agent_status(audit_id, agent_name, "completed")

        await set_phase("first_wave_complete")

    async def run_judge() -> None:
        try:
            result = await asyncio.wait_for(judge_agent.intervene(audit_id), timeout=_JUDGE_TIMEOUT_SEC)
            blackboard.set_agent_result(audit_id, "chief_judge", result)
        except Exception as exc:
            await blackboard.write_entry(audit_id=audit_id, agent="chief_judge", zone="final_zone", phase="执行异常", content="大法官执行失败", data={"error": repr(exc), "error_type": type(exc).__name__})
            blackboard.set_agent_result(audit_id, "chief_judge", {"agent": "chief_judge", "verdict": "not_participate", "reason": repr(exc), "confidence": 0.0})

    await run_primary_agents()

    await set_phase("rule_reaudit")
    adv = blackboard.get_agent_results(audit_id).get("adversarial_detective", {}) or {}
    will_participate = bool(adv.get("will_participate", False)) or (adv.get("verdict") == "participating")
    restored_text = str(adv.get("restored_text", "") or "").strip()
    skip_rule_reaudit = bool(adv.get("skip_phase2_rule_reaudit"))
    reaudit_trigger = bool(will_participate and restored_text and not skip_rule_reaudit)
    if reaudit_trigger:
        blackboard.set_agent_status(audit_id, "rule_executor", "running")
        try:
            revised = await asyncio.wait_for(rule_agent.revise_once_with_adversarial(audit_id=audit_id, adversarial_result=adv, restored_text=restored_text), timeout=_PRIMARY_AGENT_TIMEOUT_SEC)
            if revised is None:
                rule_re = await asyncio.wait_for(rule_agent.run_reaudit(restored_text), timeout=_PRIMARY_AGENT_TIMEOUT_SEC)
                await blackboard.update_agent_result(audit_id, "rule_executor", {**rule_re, "is_final": True, "is_reaudit": True}, zone="rule_zone", phase="rule_ticket_v2", reason="对抗侦探触发重审（兜底路径）")
            else:
                v2 = {
                    "agent": "rule_executor",
                    "verdict": revised.verdict,
                    "reason": revised.revision_reason or "",
                    "confidence": float(revised.confidence),
                    "is_final": True,
                    "is_reaudit": True,
                    "restored_text": restored_text,
                    "version": 2,
                    "need_knowledge": bool(revised.need_knowledge),
                    "evidence": [e.__dict__ for e in revised.evidence],
                    "detection_details": revised.to_dict(),
                }
                await blackboard.update_agent_result(audit_id, "rule_executor", v2, zone="rule_zone", phase="rule_ticket_v2", reason="对抗侦探触发一次轻量修订（v2）")
            blackboard.set_agent_status(audit_id, "rule_executor", "completed")
        except Exception as exc:
            await blackboard.write_entry(audit_id=audit_id, agent="rule_executor", zone="rule_zone", phase="执行异常", content="rule_executor修订/重审执行失败", data={"error": repr(exc), "error_type": type(exc).__name__})
            blackboard.set_agent_result(audit_id, "rule_executor", {"agent": "rule_executor", "verdict": "not_participate", "reason": f"重审失败: {repr(exc)}", "confidence": 0.0, "is_final": True, "is_reaudit": True, "restored_text": restored_text})
            blackboard.set_agent_status(audit_id, "rule_executor", "completed")
    elif skip_rule_reaudit and will_participate and restored_text:
        rule_first = blackboard.get_agent_results(audit_id).get("rule_executor", {}) or {}
        if isinstance(rule_first, dict) and rule_first:
            rule_first["is_final"] = True
            rule_first["is_reaudit"] = False
            rule_first["skipped_reaudit_reason"] = "adversarial_full_judge"
            blackboard.set_agent_result(audit_id, "rule_executor", rule_first)
    else:
        rule_first = blackboard.get_agent_results(audit_id).get("rule_executor", {}) or {}
        if isinstance(rule_first, dict) and rule_first:
            rule_first["is_final"] = True
            rule_first["is_reaudit"] = False
            blackboard.set_agent_result(audit_id, "rule_executor", rule_first)
    await set_phase("rule_reaudit_complete", triggered=reaudit_trigger)

    blackboard.set_agent_status(audit_id, "confidence_evaluator", "running")
    await set_phase("assessing")
    eval_result: dict[str, Any] = {"agent": "confidence_evaluator", "verdict": "not_participate", "reason": "评估未触发", "confidence": 0.0, "suggest_arbitration": False}
    try:
        eval_result = await asyncio.wait_for(conf_eval_agent.evaluate(audit_id), timeout=_CONF_EVAL_TIMEOUT_SEC)
        blackboard.set_agent_result(audit_id, "confidence_evaluator", eval_result)
        blackboard.set_agent_status(audit_id, "confidence_evaluator", "completed")
    except Exception as exc:
        await blackboard.write_entry(audit_id=audit_id, agent="confidence_evaluator", zone="evaluation_zone", phase="执行异常", content="confidence_evaluator执行失败", data={"error": repr(exc), "error_type": type(exc).__name__})
        blackboard.set_agent_result(audit_id, "confidence_evaluator", {"agent": "confidence_evaluator", "verdict": "not_participate", "reason": repr(exc), "confidence": 0.0, "suggest_arbitration": False})
        blackboard.set_agent_status(audit_id, "confidence_evaluator", "completed")

    await set_phase("assessment_complete", suggest_arbitration=bool(eval_result.get("suggest_arbitration", False)))

    if bool(eval_result.get("suggest_arbitration", False)):
        blackboard.set_agent_status(audit_id, "chief_judge", "running")
        await set_phase("judging")
        await run_judge()
        blackboard.set_agent_status(audit_id, "chief_judge", "completed")
        await set_phase("judge_complete")
    else:
        blackboard.set_agent_result(audit_id, "chief_judge", {"agent": "chief_judge", "verdict": "not_participate", "reason": "confidence_evaluator建议直接聚合", "confidence": 1.0})
        blackboard.set_agent_status(audit_id, "chief_judge", "skipped")

    await set_phase("aggregating")
    final_result = await aggregator.aggregate(blackboard, audit_id)

    final_verdict = final_result.get("verdict", "normal")
    if final_verdict not in {"violation", "normal"}:
        final_verdict = "normal"
    blackboard.set_state(audit_id, "final_verdict", final_verdict)
    blackboard.set_state(audit_id, "confidence", float(final_result.get("confidence", 0.9)))
    blackboard.set_state(audit_id, "aggregated_reason", str(final_result.get("reason", "") or ""))
    blackboard.set_state(audit_id, "final_reason", str(final_result.get("reason", "") or ""))
    blackboard.set_state(audit_id, "audit_complete", True)
    await set_phase("final", final_verdict=final_verdict)

    try:
        rule_agent.cleanup_cache(audit_id)
    except Exception:
        pass

    return AuditResult(
        audit_id=audit_id,
        content=content,
        final_verdict=final_verdict,
        confidence=float(final_result.get("confidence", 0.9)),
        logs=blackboard.get_logs(audit_id),
        agent_results=blackboard.get_agent_results(audit_id),
    )
