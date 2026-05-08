"""
Multi-Agent v2.2 审核流程编排
核心修正：规则执行员初判 uncertain/review 时，不再直接输出，
而是触发深度审核链（对抗侦探 → 判例执行员 → 评估员 → [大法官]）
"""

from __future__ import annotations

from typing import TypedDict, List, Dict, Optional
import asyncio


# ========== 状态定义 ==========

class AuditState(TypedDict):
    content: str
    category: str
    variant_check: Optional[Dict]
    rule_result: Optional[Dict]
    knowledge_result: Optional[Dict]
    detective_result: Optional[Dict]
    case_result: Optional[Dict]
    assessment: Optional[Dict]
    judge_result: Optional[Dict]
    final_verdict: str
    final_confidence: float
    final_reason: str
    log: List[Dict]


# ========== 各 Agent 节点（先用占位实现，后续步骤替换） ==========

async def variant_pre_check(state: AuditState) -> AuditState:
    """变体预检：纯代码检测拼音缩写/谐音/拆字，不调用 LLM"""
    content = state["content"]
    risk_signals = []
    restored_text = content

    # 1. 拼音缩写检测
    pinyin_map = {
        "tw": "台湾", "td": "台独", "zg": "中国",
        "gm": "国民", "dj": "独立", "dz": "独立",
    }
    for pinyin, chinese in pinyin_map.items():
        if pinyin in content.lower().split() or pinyin in content.lower():
            risk_signals.append(f"拼音缩写: {pinyin} -> {chinese}")
            restored_text = restored_text.replace(pinyin, chinese)
            restored_text = restored_text.replace(pinyin.upper(), chinese)

    # 2. 常见谐音/替代字
    homophone_map = {
        "筒": "同", "苔": "台", "弯": "湾",
        "郭": "国", "珉": "民", "裆": "党",
    }
    for fake, real in homophone_map.items():
        if fake in content:
            risk_signals.append(f"谐音替代: {fake} -> {real}")
            restored_text = restored_text.replace(fake, real)

    # 3. 拆字检测（如 弓长 = 张，木子 = 李）
    split_chars = {
        "弓长": "张", "木子": "李", "古月": "胡",
        "口天": "吴", "禾口": "和", "女子": "好",
    }
    for split, char in split_chars.items():
        if split in content:
            risk_signals.append(f"拆字: {split} -> {char}")
            restored_text = restored_text.replace(split, char)

    has_variant = len(risk_signals) > 0

    state["variant_check"] = {
        "has_variant": has_variant,
        "risk_signals": risk_signals,
        "restored_text": restored_text if has_variant else content,
    }
    state["log"].append({"stage": "variant_pre_check", "has_variant": has_variant, "signals": risk_signals})
    return state


async def rule_enforcer(state: AuditState) -> AuditState:
    """规则执行员：完整规则流程（R1 检索 + R2 初判 + R3/R4 二轮）"""
    from app.workflows.rule_enforcer import RuleEnforcer as RuleEnforcerWorkflow

    content = state["content"]
    category = state.get("category", "politics")
    kb = state.get("kb") or state.get("knowledge_base") or None
    llm = state.get("llm") or None
    executor = RuleEnforcerWorkflow(llm=llm, kb=kb)
    result = await executor.execute(content, category)
    state["rule_result"] = result
    state["log"].append({"stage": "rule_enforcer", "result": result})
    return state


async def knowledge_retriever(state: AuditState) -> AuditState:
    """知识库检索：当规则执行员不确定时，先补一层知识检索（规则/知识库）"""
    from app.services.vector_store import VectorStore

    query_text = str(state.get("variant_check", {}).get("restored_text") if state.get("variant_check", {}).get("has_variant") else state.get("content", "") or "")
    vector_store = VectorStore()

    try:
        rule_hits = vector_store.query("rule_base", query_text, top_k=5)
    except Exception:
        rule_hits = []
    try:
        kb_hits = vector_store.query("knowledge_base", query_text, top_k=5)
    except Exception:
        kb_hits = []

    def _normalize_hits(hits: list[dict]) -> list[dict]:
        out = []
        for h in hits:
            meta = h.get("metadata") or {}
            out.append({
                "id": h.get("id", ""),
                "preview": str(h.get("document", "") or "")[:120],
                "distance": h.get("distance"),
                "metadata": meta,
            })
        return out

    def _best_distance(hits: list[dict]) -> float:
        best = 999.0
        for h in hits:
            try:
                d = float(h.get("distance"))
            except Exception:
                continue
            if d < best:
                best = d
        return best if best != 999.0 else 999.0

    normalized_rule_hits = _normalize_hits(rule_hits)
    normalized_kb_hits = _normalize_hits(kb_hits)
    best_rule_distance = _best_distance(rule_hits)
    best_kb_distance = _best_distance(kb_hits)

    if normalized_rule_hits or normalized_kb_hits:
        verdict = "review"
        confidence = 0.6
        reason = "检索到相关知识，但仍需深度审核"
    else:
        verdict = "review"
        confidence = 0.45
        reason = "知识库与规则库均未命中，进入深度审核"

    result = {
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason,
        "rule_hits": normalized_rule_hits,
        "kb_hits": normalized_kb_hits,
        "best_rule_distance": best_rule_distance,
        "best_kb_distance": best_kb_distance,
    }

    state["knowledge_result"] = result
    state["log"].append({"stage": "knowledge_retriever", "result": result})
    return state


async def adversarial_detective(state: AuditState) -> AuditState:
    """对抗侦探：检测变体、反讽、隐喻"""
    from app.agents.adv_variant_restorer import VariantRestorer, adversarial_should_participate

    content = str(state.get("content", "") or "")
    variant = state.get("variant_check", {}) or {}
    restorer = VariantRestorer()

    if variant.get("has_variant"):
        restored_text = str(variant.get("restored_text", "") or "")
        risk_signals = list(variant.get("risk_signals", []) or [])
        detected = True
    else:
        detected = adversarial_should_participate(restorer, content)
        restored_text = ""
        risk_signals = []
        if detected:
            restored_text, risk_signals = restorer.restore(content)

    if detected:
        confidence = 0.9 if risk_signals else 0.78
        reason = f"检测到变体信号: {risk_signals or ['疑似变体绕过']}，需深度审核"
        result = {
            "verdict": "review",
            "confidence": confidence,
            "reason": reason,
            "will_participate": True,
            "restored_text": restored_text or variant.get("restored_text", ""),
            "adversarial_judgment": True,
            "skip_phase2_rule_reaudit": False,
            "detection_details": {
                "risk_signals": risk_signals,
                "pipeline": "deterministic_variant_guard",
                "restored_preview": (restored_text or variant.get("restored_text", ""))[:120],
            },
        }
    else:
        result = {
            "verdict": "not_participate",
            "confidence": 1.0,
            "reason": "未发现对抗性变体，或短文本跳过",
            "will_participate": False,
            "restored_text": "",
            "adversarial_judgment": False,
            "skip_phase2_rule_reaudit": False,
            "detection_details": {
                "risk_signals": [],
                "pipeline": "deterministic_variant_guard",
            },
        }

    state["detective_result"] = result
    state["log"].append({"stage": "adversarial_detective", "result": result})
    return state


async def case_executor(state: AuditState) -> AuditState:
    """判例执行员：真实判例检索 + 投票聚合（基础版）"""
    from pathlib import Path

    from app.services.case_service import CaseService
    from app.services.vector_store import VectorStore

    content = state.get("variant_check", {}).get("restored_text") if state.get("variant_check", {}).get("has_variant") else state.get("content", "")
    query_text = str(content or "")
    vector_store = VectorStore()
    case_service = CaseService(vector_store, data_dir=Path("./data"))

    try:
        retrieved = await case_service.search_cases(query_text, top_k=5)
    except Exception:
        retrieved = []

    votes: list[dict[str, object]] = []
    vote_violation = 0
    vote_normal = 0
    best_similarity = 0.0
    matched_cases: list[dict[str, object]] = []

    for item in retrieved:
        case = item.get("case")
        if not case:
            continue
        similarity = float(item.get("similarity", 0.0) or 0.0)
        best_similarity = max(best_similarity, similarity)
        verdict = str(getattr(case, "verdict", "") or "")
        matched_cases.append(
            {
                "id": getattr(case, "id", ""),
                "verdict": verdict,
                "similarity": round(similarity, 3),
                "category": getattr(case, "category", ""),
                "text": getattr(case, "text", "")[:120],
            }
        )
        vote = {"case_id": getattr(case, "id", ""), "verdict": verdict, "similarity": round(similarity, 3)}
        votes.append(vote)
        if verdict == "violation":
            vote_violation += 1
        elif verdict == "normal":
            vote_normal += 1

    variant = state.get("variant_check", {}) or {}
    has_variant = bool(variant.get("has_variant", False))

    if vote_violation > vote_normal and best_similarity >= 0.35:
        verdict = "violation"
        confidence = min(0.95, 0.55 + best_similarity * 0.4 + vote_violation * 0.05)
        reason = "判例检索结果倾向违规"
    elif vote_normal > vote_violation and best_similarity >= 0.35:
        verdict = "normal"
        confidence = min(0.9, 0.5 + best_similarity * 0.35 + vote_normal * 0.04)
        reason = "判例检索结果倾向正常"
    elif has_variant:
        verdict = "review"
        confidence = 0.58
        reason = "命中变体但判例相似度不足，继续深度审核"
    else:
        verdict = "review"
        confidence = 0.55
        reason = "案例不足，存疑"

    result = {
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason,
        "detection_details": {
            "retrieved_cases": matched_cases,
            "use_case": bool(matched_cases),
            "votes": votes,
            "version": 3,
            "best_similarity": round(best_similarity, 3),
            "vote_violation": vote_violation,
            "vote_normal": vote_normal,
        },
    }
    state["case_result"] = result
    state["log"].append({"stage": "case_executor", "result": result})
    return state


async def confidence_assessor(state: AuditState) -> AuditState:
    """
    置信度评估员：与后端 ConfidenceEvaluator 逻辑尽量对齐
    - 按权重校准 rule / case / detective 置信度
    - 统计冲突、低置信与仲裁建议
    """
    rule = state.get("rule_result", {}) or {}
    detective = state.get("detective_result", {}) or {}
    case = state.get("case_result", {}) or {}
    variant = state.get("variant_check", {}) or {}

    weights = {
        "rule_enforcer": 0.9,
        "case_executor": 0.8,
        "adversarial_detective": 0.82,
    }

    votes = []
    if str(rule.get("verdict", "") or "").strip() not in {"", "not_participate", "not_participating"}:
        votes.append({"agent": "rule_enforcer", "verdict": str(rule.get("verdict", "review")), "raw": float(rule.get("confidence", 0.0) or 0.0)})
    if str(case.get("verdict", "") or "").strip() not in {"", "not_participate", "not_participating"}:
        votes.append({"agent": "case_executor", "verdict": str(case.get("verdict", "review")), "raw": float(case.get("confidence", 0.0) or 0.0)})
    if detective.get("adversarial_judgment") and str(detective.get("verdict", "") or "").strip() not in {"", "not_participate", "participating"}:
        votes.append({"agent": "adversarial_detective", "verdict": str(detective.get("verdict", "review")), "raw": float(detective.get("confidence", 0.0) or 0.0)})

    calibrated_votes = []
    violation_count = 0
    uncertain_count = 0
    low_confidence_count = 0
    max_calibrated = 0.0

    for vote in votes:
        w = float(weights.get(vote["agent"], 0.8))
        raw = max(0.0, min(1.0, float(vote["raw"])))
        calibrated = round(raw * w, 3)
        verdict = vote["verdict"]
        ignored = calibrated < 0.4
        if ignored:
            low_confidence_count += 1
        if verdict in {"violation", "reject"}:
            violation_count += 1
        elif verdict in {"review", "uncertain"}:
            uncertain_count += 1
        max_calibrated = max(max_calibrated, calibrated)
        calibrated_votes.append({
            "agent": vote["agent"],
            "verdict": verdict,
            "raw": raw,
            "calibrated": calibrated,
            "weight": w,
            "ignored": ignored,
        })

    conflict_detected = False
    verdicts = {v["verdict"] for v in calibrated_votes if not v["ignored"]}
    if "violation" in verdicts and "uncertain" in verdicts and max_calibrated > 0.6:
        conflict_detected = True
    if variant.get("has_variant") and str(rule.get("verdict", "") or "").strip() in {"pass", "clean", "normal"}:
        conflict_detected = True
    if str(case.get("verdict", "") or "").strip() == "violation" and str(rule.get("verdict", "") or "").strip() in {"pass", "normal"}:
        conflict_detected = True
    if str(rule.get("verdict", "") or "").strip() == "review" and str(case.get("verdict", "") or "").strip() == "review" and str(detective.get("verdict", "") or "").strip() in {"review", "not_participate"}:
        conflict_detected = True

    suggest_arbitration = conflict_detected or max_calibrated < 0.5 or low_confidence_count > 0 or variant.get("has_variant", False)

    aggregated_verdict = str(rule.get("verdict", "review") or "review")
    aggregated_confidence = float(rule.get("confidence", 0.5) or 0.5)
    if str(case.get("verdict", "") or "") == "violation" and aggregated_verdict in {"review", "pass", "normal"}:
        aggregated_verdict = "review" if variant.get("has_variant") else "reject"
        aggregated_confidence = max(aggregated_confidence, float(case.get("confidence", 0.5) or 0.5))
    if str(detective.get("verdict", "") or "") == "review" and float(detective.get("confidence", 0.0) or 0.0) > aggregated_confidence:
        aggregated_confidence = float(detective.get("confidence", 0.5) or 0.5)

    assessment = {
        "should_arbitrate": suggest_arbitration,
        "arbitration_score": round((1.5 if conflict_detected else 0.0) + (1.0 if variant.get("has_variant") else 0.0) + max_calibrated + (0.5 if low_confidence_count > 0 else 0.0), 3),
        "aggregated_verdict": aggregated_verdict,
        "aggregated_confidence": aggregated_confidence,
        "calibrated_votes": calibrated_votes,
        "summary": {
            "violation_count": violation_count,
            "uncertain_count": uncertain_count,
            "max_calibrated": max_calibrated,
            "conflict_detected": conflict_detected,
            "low_confidence_count": low_confidence_count,
        },
        "suggest_arbitration": suggest_arbitration,
        "reason": "检测到冲突" if conflict_detected else ("存在变体风险" if variant.get("has_variant") else "无冲突"),
        "recommended_action": "建议大法官介入" if suggest_arbitration else "直接聚合",
    }

    state["assessment"] = assessment
    state["log"].append({"stage": "confidence_assessor", "assessment": assessment})
    return state


async def chief_judge(state: AuditState) -> AuditState:
    """
    大法官：受限检索，终审裁决
    高资源消耗，每次调用消耗仲裁配额
    """
    rule = state.get("rule_result", {}) or {}
    case = state.get("case_result", {}) or {}
    detective = state.get("detective_result", {}) or {}
    assessment = state.get("assessment", {}) or {}
    variant = state.get("variant_check", {}) or {}

    if variant.get("has_variant"):
        if str(case.get("verdict", "") or "") == "violation" or str(rule.get("verdict", "") or "") == "reject":
            verdict = "reject"
            confidence = max(float(case.get("confidence", 0.8) or 0.8), float(rule.get("confidence", 0.8) or 0.8), 0.88)
            reason = "大法官终审：检测到变体绕过且判例/规则支持违规"
        else:
            verdict = "review"
            confidence = max(float(assessment.get("aggregated_confidence", 0.65) or 0.65), 0.72)
            reason = "大法官终审：检测到变体绕过，维持复核"
    elif str(rule.get("verdict", "") or "") == "reject":
        verdict = "reject"
        confidence = max(float(rule.get("confidence", 0.8) or 0.8), 0.85)
        reason = "大法官终审：规则执行员已命中违规"
    elif str(case.get("verdict", "") or "") == "violation":
        verdict = "reject"
        confidence = max(float(case.get("confidence", 0.8) or 0.8), 0.82)
        reason = "大法官终审：判例投票支持违规"
    elif str(detective.get("verdict", "") or "") == "review":
        verdict = "review"
        confidence = max(float(assessment.get("aggregated_confidence", 0.65) or 0.65), 0.7)
        reason = "大法官终审：证据仍不足，维持复核"
    else:
        verdict = "review"
        confidence = max(float(assessment.get("aggregated_confidence", 0.65) or 0.65), 0.65)
        reason = "大法官终审：综合证据不足"

    result = {
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason,
    }
    state["judge_result"] = result
    state["log"].append({"stage": "chief_judge", "result": result})
    return state


async def aggregator(state: AuditState) -> AuditState:
    """聚合器：组装最终输出"""
    # 优先级：大法官 > 评估员聚合 > 规则执行员
    if state.get("judge_result"):
        source = state["judge_result"]
    elif state.get("assessment"):
        source = {
            "verdict": state["assessment"]["aggregated_verdict"],
            "confidence": state["assessment"]["aggregated_confidence"]
        }
    else:
        source = state.get("rule_result", {})

    state["final_verdict"] = source.get("verdict", "review")
    state["final_confidence"] = source.get("confidence", 0.5)
    state["final_reason"] = source.get("reason", "无明确理由")
    state["log"].append({"stage": "aggregator", "verdict": state["final_verdict"]})
    return state


# ========== 主流程控制 ==========

async def run_audit(content: str, category: str = "politics", blackboard=None, audit_id: str | None = None) -> AuditState:
    """
    审核主流程。协调员初始化黑板，并并发运行三个专业 Agent。
    """
    state: AuditState = {
        "content": content,
        "category": category,
        "variant_check": None,
        "rule_result": None,
        "knowledge_result": None,
        "detective_result": None,
        "case_result": None,
        "assessment": None,
        "judge_result": None,
        "final_verdict": "",
        "final_confidence": 0.0,
        "final_reason": "",
        "log": []
    }

    state = await variant_pre_check(state)

    if blackboard is None:
        # 兼容旧路径：无黑板时回退到串行执行
        state = await rule_enforcer(state)
        verdict = state["rule_result"].get("verdict", "review")
        has_variant = state.get("variant_check", {}).get("has_variant", False)
        if verdict in ["reject", "pass"] and not has_variant:
            state = await aggregator(state)
        else:
            state = await knowledge_retriever(state)
            state = await adversarial_detective(state)
            state = await case_executor(state)
            state = await confidence_assessor(state)
            if state["assessment"].get("should_arbitrate", False):
                state = await chief_judge(state)
            state = await aggregator(state)
        return state

    audit_id = audit_id or str(__import__("uuid").uuid4())
    blackboard.set_state(audit_id, "content", content)
    blackboard.set_state(audit_id, "category", category)
    blackboard.set_state(audit_id, "variant_check", state["variant_check"])
    blackboard.set_agent_status(audit_id, "rule_enforcer", "running")
    blackboard.set_agent_status(audit_id, "adversarial_detective", "running")
    blackboard.set_agent_status(audit_id, "case_executor", "running")

    async def _run_rule() -> dict:
        local = {**state, "log": []}
        res = await rule_enforcer(local)
        blackboard.set_agent_result(audit_id, "rule_enforcer", {**res["rule_result"], "agent": "rule_enforcer"})
        return res

    async def _run_detective() -> dict:
        local = {**state, "log": []}
        res = await adversarial_detective(local)
        detective = res.get("detective_result", {}) or {}
        if detective.get("will_participate", False):
            blackboard.set_agent_result(audit_id, "adversarial_detective", detective)
        else:
            blackboard.set_agent_result(audit_id, "adversarial_detective", {**detective, "verdict": "not_participate", "agent": "adversarial_detective"})
        return res

    async def _run_case() -> dict:
        local = {**state, "log": []}
        res = await case_executor(local)
        case = res.get("case_result", {}) or {}
        if case.get("detection_details", {}).get("retrieved_cases"):
            blackboard.set_agent_result(audit_id, "case_executor", {**case, "agent": "case_executor"})
        else:
            blackboard.set_agent_result(audit_id, "case_executor", {**case, "verdict": "not_participate", "agent": "case_executor"})
        return res

    rule_task = asyncio.create_task(_run_rule())
    detective_task = asyncio.create_task(_run_detective())
    case_task = asyncio.create_task(_run_case())

    rule_state, detective_state, case_state = await asyncio.gather(rule_task, detective_task, case_task)

    state["rule_result"] = rule_state.get("rule_result")
    state["detective_result"] = detective_state.get("detective_result")
    state["case_result"] = case_state.get("case_result")

    # knowledge_result 作为可选补充层，只在规则不确定/变体时用于评估上下文
    if state["rule_result"].get("verdict", "review") == "review" or state.get("variant_check", {}).get("has_variant", False):
        state = await knowledge_retriever(state)

    state = await confidence_assessor(state)
    if state["assessment"].get("should_arbitrate", False):
        state = await chief_judge(state)
    state = await aggregator(state)

    blackboard.set_state(audit_id, "final_verdict", state.get("final_verdict", ""))
    blackboard.set_state(audit_id, "confidence", state.get("final_confidence", 0.0))
    return state


# ========== 兼容旧接口 ==========

def create_audit_graph():
    """
    兼容旧代码的 create_audit_graph() 接口。
    返回一个可调用的对象，支持 .ainvoke(state) 和 .invoke(state)。
    """
    class MockGraph:
        async def ainvoke(self, state: dict) -> AuditState:
            content = state.get("content", "")
            category = state.get("category", "politics")
            return await run_audit(content, category)

        def invoke(self, state: dict) -> AuditState:
            return asyncio.run(self.ainvoke(state))

    return MockGraph()


# ========== 自测代码 ==========

async def test_flow():
    """验证四种核心分支"""
    print("=" * 50)
    print("审核流程自测")
    print("=" * 50)

    # Case 1: 明确违规 → 直接 reject
    result1 = await run_audit("台独言论【违规】")
    assert result1["final_verdict"] == "reject", f"预期 reject，实际 {result1['final_verdict']}"
    assert len(result1["log"]) == 3, f"预期 3 个 stage，实际 {len(result1['log'])}"
    stages1 = [l["stage"] for l in result1["log"]]
    assert "variant_pre_check" in stages1 and "rule_enforcer" in stages1 and "aggregator" in stages1
    print("✓ Case 1 (reject): 通过 —— 高置信违规，直接聚合输出")

    # Case 2: 明确正常 → 直接 pass
    result2 = await run_audit("今天天气真好【正常】")
    assert result2["final_verdict"] == "pass", f"预期 pass，实际 {result2['final_verdict']}"
    assert len(result2["log"]) == 3
    print("✓ Case 2 (pass): 通过 —— 高置信正常，直接聚合输出")

    # Case 3: 不确定 → 走深度审核链（核心修正验证）
    result3 = await run_audit("这是一段讽刺性言论")
    stages3 = [l["stage"] for l in result3["log"]]

    assert "rule_enforcer" in stages3, "必须有规则执行员"
    assert "variant_pre_check" in stages3, "必须有变体预检"
    assert "adversarial_detective" in stages3, "不确定时必须触发对抗侦探"
    assert "case_executor" in stages3, "不确定时必须触发判例执行员"
    assert "confidence_assessor" in stages3, "不确定时必须触发评估员"
    assert "aggregator" in stages3, "必须有聚合器"
    print("✓ Case 3 (uncertain → deep audit): 通过 —— 触发完整深度审核链")

    # Case 4: 拼音缩写 → 触发变体检测 → 深度审核（核心修正验证）
    result4 = await run_audit("tw是一个独立的国家")
    stages4 = [l["stage"] for l in result4["log"]]

    assert "variant_pre_check" in stages4, "必须有变体预检"
    assert result4["variant_check"]["has_variant"] == True, "必须检测到变体"
    assert "adversarial_detective" in stages4, "拼音缩写必须触发对抗侦探"
    assert "case_executor" in stages4, "拼音缩写必须触发判例执行员"
    assert "confidence_assessor" in stages4, "拼音缩写必须触发评估员"
    print("✓ Case 4 (拼音缩写 → 变体检测 → 深度审核): 通过 —— 对抗侦探参与")

    print("=" * 50)
    print("全部通过！")
    print("=" * 50)
    return result1, result2, result3, result4


if __name__ == "__main__":
    asyncio.run(test_flow())
