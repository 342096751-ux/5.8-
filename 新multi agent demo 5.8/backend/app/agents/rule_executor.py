from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.agents.rule_recall_secondary import audit_text_recall_secondary, is_recall_secondary_enabled
from app.core.agent_base import BaseAgent


class Verdict(str, Enum):
    VIOLATION = "violation"
    NORMAL = "normal"
    UNCERTAIN = "uncertain"


class EvidenceType(str, Enum):
    RULE = "rule"
    KNOWLEDGE = "knowledge"
    ADVERSARIAL = "adversarial"


@dataclass
class Evidence:
    type: str  # "rule" | "knowledge" | "adversarial"
    content: str
    source_id: str | None = None


@dataclass
class RuleTicket:
    """规则执行员标准票面（写入黑板时放在 detection_details 里）。"""

    agent: str = "rule_executor"
    verdict: str = Verdict.UNCERTAIN.value
    confidence: float = 0.5
    evidence: list[Evidence] = field(default_factory=list)
    need_knowledge: bool = False
    version: int = 1
    revision_reason: str | None = None
    raw_llm_output: str = ""
    status: str = "complete"  # complete|error

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "evidence": [
                {"type": e.type, "content": e.content, "source_id": e.source_id}
                for e in self.evidence
            ],
            "need_knowledge": self.need_knowledge,
            "version": self.version,
            "revision_reason": self.revision_reason,
            "raw_llm_output": self.raw_llm_output,
            "status": self.status,
        }


@dataclass
class RuleExecutorCache:
    original_text: str
    retrieved_rules: list[dict[str, Any]]
    knowledge_results: list[dict[str, Any]] | None = None
    first_pass_result: dict[str, Any] | None = None
    has_revised: bool = False


FIRST_PASS_PROMPT = """你是内容安全规则执行员初筛组件。

参考资料（规则）:
{rules}

待审核内容:
{content}

判定原则（严格遵守）：
1) violation：内容明显违规。命中规则是充分条件但不是必要条件——即使未命中具体规则，只要语义明确违规，仍必须判 violation
2) uncertain：内容模糊、擦边、可能涉及但无法确认时使用
3) normal：明显无关且不构成违规

重要约束：
- 参考资料是辅助，你的语义理解能力本身也是判断依据
- 如果语义明显违规但资料未覆盖，仍应判 violation（置信度可适当降低，如 0.70~0.85）
- uncertain 只用于“真的不确定”，不能因为“没查到规则”而使用
- 尽量给出 matched_rules；无规则可引时 matched_rules 允许空列表，但 reasoning 必须引用文本证据片段
- 不要把明显违规降成 uncertain

输出纯JSON（不要markdown/解释），字段:
- verdict: "violation" | "normal" | "uncertain"
- need_knowledge: true|false（规则不足以判断时为 true）
- confidence: 0~1
- matched_rules: ["id1","id2"]（命中的规则 id 列表，可为空）
- reasoning: 50字以内依据
"""


SECONDARY_PROMPT = """你是复核审查引擎。初判认为需要知识库补充，请结合资料重新判断。

初判结果:
{first_pass}

规则:
{rules}

知识库:
{knowledge}

待审核内容:
{content}

复核原则（严格遵守）：
1) violation：初判依据充分，或即使规则未覆盖但语义明显违规
2) normal：初判误判（如明显引用/讨论语境）且不构成违规
3) uncertain：复核后仍无法确认

重要约束：
- 你有推翻初判的权力，但不能因为“没规则”就把明显违规改成 normal/uncertain
- uncertain 只能用于“确实无法确认”
- 输出必须且只能是合法JSON，不要markdown代码块，不要解释

输出纯JSON（不要markdown/解释），字段:
- verdict: "violation" | "normal" | "uncertain"
- need_knowledge: false
- confidence: 0~1
- matched_rules: ["id1","id2"]（可为空）
- reasoning: 50字以内依据
"""


BASE_JUDGE_PROMPT = """你是内容安全审核员，请先基于文本语义独立判断（不依赖规则检索结果）。

待审核内容:
{content}

输出纯JSON（不要markdown/解释），字段:
- verdict: "violation" | "normal" | "uncertain"
- confidence: 0~1
- reasoning: 50字以内依据
"""


REVISION_PROMPT = """你是内容安全规则执行员。对抗侦探检测到新的对抗特征，请结合这些信息重新判断（只修订一次）。

原始初判结果:
{first_pass}

规则:
{rules}

知识库缓存:
{knowledge}

对抗侦探信息:
{adversarial}

最终待审核内容:
{content}

输出纯JSON（不要markdown/解释），字段:
- verdict: "violation" | "normal" | "uncertain"
- need_knowledge: true|false（若仍需知识库补充）
- confidence: 0~1
- matched_rules: ["id1","id2"]
- reasoning: 50字以内依据
"""


def _first_pass_bundle(out: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    fp: dict[str, Any] = {
        "verdict": out.get("verdict"),
        "need_knowledge": out.get("need_knowledge"),
        "confidence": out.get("confidence"),
        "matched_rules": out.get("matched_rules", []),
        "reasoning": out.get("reasoning", ""),
    }
    for k in ("pipeline", "pipeline_stage", "secondary_verdict", "primary_verdict_raw", "merged_retrieval_len"):
        if isinstance(meta, dict) and k in meta:
            fp[k] = meta[k]
    return fp


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    # 处理 ```json ... ``` 或 ``` ... ```
    if "```" in raw:
        if "```json" in raw:
            raw = raw.split("```json", 1)[1]
        raw = raw.split("```", 1)[0] if "```" in raw else raw
        raw = raw.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _rules_to_text(rules: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for r in rules or []:
        rid = r.get("id") or r.get("rule_id") or r.get("metadata", {}).get("id") or ""
        doc = r.get("document") or r.get("content") or ""
        if rid:
            lines.append(f"- {rid}: {doc}")
        else:
            lines.append(f"- {doc}")
    return "\n".join(lines) or "无匹配规则"


def _knowledge_to_text(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return "无匹配知识"
    lines: list[str] = []
    for k in items:
        kid = k.get("id") or k.get("metadata", {}).get("id") or ""
        doc = k.get("document") or k.get("content") or ""
        if kid:
            lines.append(f"- {kid}: {doc}")
        else:
            lines.append(f"- {doc}")
    return "\n".join(lines) or "无匹配知识"


def _fuse_dual_path(
    *,
    base_verdict: str,
    base_conf: float,
    rag_verdict: str,
    rag_conf: float,
    matched_rules: list[str],
) -> tuple[str, float, str]:
    """LLM直判 + RAG证据 融合。"""
    base_v = str(base_verdict or Verdict.UNCERTAIN.value)
    rag_v = str(rag_verdict or Verdict.UNCERTAIN.value)
    evidence_strong = bool(matched_rules) or rag_v == Verdict.VIOLATION.value

    if base_v == Verdict.VIOLATION.value and not evidence_strong:
        return Verdict.UNCERTAIN.value, max(0.45, min(0.72, base_conf * 0.85)), "语义疑似违规，但规则证据不足"
    if base_v == Verdict.NORMAL.value and evidence_strong:
        return Verdict.UNCERTAIN.value, max(0.42, min(0.68, rag_conf * 0.85)), "规则证据提示风险，语义与证据不一致"
    if base_v == rag_v:
        return base_v, max(base_conf, rag_conf), "语义判断与规则证据一致"
    # 其余冲突场景
    return Verdict.UNCERTAIN.value, max(0.4, (base_conf + rag_conf) / 2.0), "语义判断与规则证据冲突"


async def audit_text(
    text: str,
    *,
    rag_service,
    llm_client,
    rules_top_k: int = 5,
    knowledge_top_k: int = 5,
    category: str | None = None,
    return_trace: bool = True,
) -> dict[str, Any]:
    """
    规则执行员核心判断逻辑（无黑板日志副作用），供对抗侦探复用。

    返回：
    - verdict: violation|normal|uncertain
    - reason
    - confidence
    - _meta: 内部调试信息（rules/knowledge 命中、trace）

    环境变量 RULE_EXECUTOR_PIPELINE=recall_secondary 时启用「召回 + 违规律二次确认」，见 rule_recall_secondary。
    """
    if is_recall_secondary_enabled():
        return await audit_text_recall_secondary(
            text,
            rag_service=rag_service,
            llm_client=llm_client,
            rules_top_k=rules_top_k,
            return_trace=return_trace,
            category=category,
        )

    from app.services.enhanced_rag import EnhancedRetriever

    er = EnhancedRetriever(rag_service)
    rules = er.retrieve_rules_for_executor(text, category)[: max(rules_top_k, 12)]
    rules_text = _rules_to_text(rules)

    base_prompt = BASE_JUDGE_PROMPT.format(content=text)
    base_llm = await llm_client.complete(
        system_prompt="你是严格的内容安全审核员，仅返回JSON。",
        user_prompt=base_prompt,
        use_strong_model=False,
        return_trace=return_trace,
        temperature=0.1,
    )
    base_raw = base_llm.get("output_text", "") if isinstance(base_llm, dict) else str(base_llm)
    base_trace = base_llm.get("trace", {}) if isinstance(base_llm, dict) else {}
    base_parsed = _extract_json(base_raw)

    prompt = FIRST_PASS_PROMPT.format(rules=rules_text, content=text)
    llm_result = await llm_client.complete(
        system_prompt="你是严格的内容安全审核员，仅返回JSON。",
        user_prompt=prompt,
        use_strong_model=False,
        return_trace=return_trace,
        temperature=0.1,
    )
    raw = llm_result.get("output_text", "") if isinstance(llm_result, dict) else str(llm_result)
    trace = llm_result.get("trace", {}) if isinstance(llm_result, dict) else {}
    parsed = _extract_json(raw)

    need_knowledge = bool(parsed.get("need_knowledge", False))
    kb_filtered: list[dict[str, Any]] = []
    secondary_raw = ""
    secondary_trace: dict[str, Any] = {}
    if need_knowledge:
        # R2: need_knowledge=true 时才查知识库，并二次判断
        kb = rag_service.retrieve_knowledge(text, top_k=knowledge_top_k)
        kb_filtered = [k for k in kb if len(k.get("document", "")) > 0][:3]
        kb_text = _knowledge_to_text(kb_filtered)
        sp = SECONDARY_PROMPT.format(
            first_pass=json.dumps(parsed, ensure_ascii=False),
            rules=rules_text,
            knowledge=kb_text,
            content=text,
        )
        llm2 = await llm_client.complete(
            system_prompt="你是严格的内容安全审核员，仅返回JSON。",
            user_prompt=sp,
            use_strong_model=False,
            return_trace=return_trace,
            temperature=0.1,
        )
        secondary_raw = llm2.get("output_text", "") if isinstance(llm2, dict) else str(llm2)
        secondary_trace = llm2.get("trace", {}) if isinstance(llm2, dict) else {}
        parsed2 = _extract_json(secondary_raw)
        if parsed2:
            parsed = parsed2
            parsed["need_knowledge"] = False

    rag_verdict = str(parsed.get("verdict", Verdict.UNCERTAIN.value))
    rag_confidence = float(parsed.get("confidence", 0.5) or 0.5)
    base_verdict = str(base_parsed.get("verdict", Verdict.UNCERTAIN.value))
    base_confidence = float(base_parsed.get("confidence", 0.5) or 0.5)
    matched_rules = parsed.get("matched_rules", []) or []

    fused_verdict, fused_conf, fused_reason = _fuse_dual_path(
        base_verdict=base_verdict,
        base_conf=base_confidence,
        rag_verdict=rag_verdict,
        rag_conf=rag_confidence,
        matched_rules=[str(x) for x in matched_rules],
    )

    out = {
        "verdict": fused_verdict,
        "need_knowledge": bool(parsed.get("need_knowledge", False)),
        "matched_rules": matched_rules,
        "reasoning": f"{fused_reason}; 语义:{base_parsed.get('reasoning', '') or base_parsed.get('reason', '')}; 证据:{parsed.get('reasoning', parsed.get('reason', ''))}",
        "reason": f"{fused_reason}; 语义:{base_parsed.get('reasoning', '') or base_parsed.get('reason', '')}; 证据:{parsed.get('reason', '') or parsed.get('reasoning', '')}",
        "confidence": fused_conf,
        "kb_results": kb_filtered,
        "_meta": {
            "rules_top_k": rules_top_k,
            "knowledge_top_k": knowledge_top_k,
            "knowledge_hits": len(kb_filtered),
            "base_verdict": base_verdict,
            "base_confidence": base_confidence,
            "base_trace": base_trace,
            "base_raw": base_raw,
            "rag_verdict": rag_verdict,
            "rag_confidence": rag_confidence,
            "trace": trace,
            "raw": raw,
            "secondary_trace": secondary_trace,
            "secondary_raw": secondary_raw,
        },
        "_rules": rules,
    }
    return out


class RuleExecutor(BaseAgent):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._cache: dict[str, RuleExecutorCache] = {}

    def _build_evidence(
        self,
        *,
        rules: list[dict[str, Any]],
        matched_rules: list[str],
        kb_results: list[dict[str, Any]] | None,
        adversarial: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        ev: list[Evidence] = []
        want = {str(x) for x in (matched_rules or [])}
        for r in rules or []:
            rid = str(r.get("id") or r.get("rule_id") or "")
            if not rid or rid not in want:
                continue
            doc = str(r.get("document") or r.get("content") or "")
            ev.append(Evidence(type=EvidenceType.RULE.value, content=f"规则 {rid}: {doc}", source_id=rid))
        for k in kb_results or []:
            kid = str(k.get("id") or "")
            doc = str(k.get("document") or k.get("content") or "")
            ev.append(
                Evidence(
                    type=EvidenceType.KNOWLEDGE.value,
                    content=f"知识 {kid or 'unknown'}: {doc}",
                    source_id=kid or None,
                )
            )
        if adversarial:
            ev.append(
                Evidence(
                    type=EvidenceType.ADVERSARIAL.value,
                    content=f"对抗侦探: {json.dumps(adversarial, ensure_ascii=False)[:800]}",
                    source_id="adversarial_detective",
                )
            )
        return ev

    async def revise_once_with_adversarial(
        self,
        *,
        audit_id: str,
        adversarial_result: dict[str, Any],
        restored_text: str | None,
    ) -> RuleTicket | None:
        cache = self._cache.get(audit_id)
        if cache is None or cache.has_revised:
            return None
        will = bool(adversarial_result.get("will_participate", False)) or (
            adversarial_result.get("verdict") == "participating"
        )
        if not will:
            return None
        adv_features = adversarial_result.get("detection_details") or {}
        if not adv_features and not (restored_text or "").strip():
            return None
        cache.has_revised = True

        text = (restored_text or "").strip() or cache.original_text
        rules = cache.retrieved_rules
        kb = cache.knowledge_results
        first_pass = cache.first_pass_result or {}
        prompt = REVISION_PROMPT.format(
            first_pass=json.dumps(first_pass, ensure_ascii=False),
            rules=_rules_to_text(rules),
            knowledge=_knowledge_to_text(kb),
            adversarial=json.dumps(
                {"features": adv_features, "restored_text": (restored_text or "").strip()},
                ensure_ascii=False,
            ),
            content=text,
        )
        llm = await self.llm.complete(
            system_prompt="你是严格的内容安全审核员，仅返回JSON。",
            user_prompt=prompt,
            use_strong_model=False,
            return_trace=True,
            temperature=0.1,
        )
        raw = llm.get("output_text", "") if isinstance(llm, dict) else str(llm)
        parsed = _extract_json(raw)
        verdict = str(parsed.get("verdict", Verdict.UNCERTAIN.value))
        need_k = bool(parsed.get("need_knowledge", False))
        matched = parsed.get("matched_rules", []) or []
        reasoning = str(parsed.get("reasoning", ""))[:200]
        ev = self._build_evidence(
            rules=rules,
            matched_rules=[str(x) for x in matched],
            kb_results=kb,
            adversarial=adv_features or {"restored_text": restored_text or ""},
        )
        return RuleTicket(
            verdict=verdict,
            confidence=float(parsed.get("confidence", 0.5) or 0.5),
            evidence=ev,
            need_knowledge=need_k,
            version=2,
            revision_reason=f"结合对抗特征修订: {reasoning or '无'}",
            raw_llm_output=raw,
            status="complete",
        )

    def cleanup_cache(self, audit_id: str) -> None:
        self._cache.pop(audit_id, None)

    async def run_first_pass(self, text: str) -> dict[str, Any]:
        """初判（is_final=false）"""
        cfg = self.blackboard.get_state(self.audit_id, "config") or {}
        category_raw = self.blackboard.get_state(self.audit_id, "category") or cfg.get("category")
        cat = str(category_raw).strip() if category_raw else None
        out = await audit_text(
            text,
            rag_service=self.rag,
            llm_client=self.llm,
            rules_top_k=5,
            knowledge_top_k=5,
            category=cat,
            return_trace=True,
        )
        meta = out.get("_meta", {}) if isinstance(out, dict) else {}
        rules = out.get("_rules", []) if isinstance(out, dict) else []
        kb_results = out.get("kb_results", []) if isinstance(out, dict) else []
        ticket = RuleTicket(
            verdict=str(out.get("verdict", Verdict.UNCERTAIN.value)),
            confidence=float(out.get("confidence", 0.5) or 0.5),
            evidence=self._build_evidence(
                rules=rules,
                matched_rules=[str(x) for x in (out.get("matched_rules", []) or [])],
                kb_results=kb_results,
            ),
            need_knowledge=bool(out.get("need_knowledge", False)),
            version=1,
            raw_llm_output=str(meta.get("secondary_raw") or meta.get("raw") or ""),
            status="complete",
        )
        # 缓存：供 Phase2（对抗侦探）修订复用，避免重复检索
        self._cache[self.audit_id] = RuleExecutorCache(
            original_text=text,
            retrieved_rules=list(rules) if isinstance(rules, list) else [],
            knowledge_results=list(kb_results) if isinstance(kb_results, list) else None,
            first_pass_result=_first_pass_bundle(out, meta),
            has_revised=False,
        )
        if (meta.get("pipeline") or "") == "recall_secondary":
            await self.log(
                "规则检索",
                "召回_secondary：合并规则+case向量检索（违规则再走复核 LLM）",
                {"top_k": 5, "merged_len": meta.get("merged_retrieval_len", 0), "is_reaudit": False},
            )
        else:
            await self.log("规则检索", "检索到Top-K相关规则", {"top_k": 5, "is_reaudit": False})
        await self.log(
            "知识检索",
            "规则执行员已检索知识库"
            if (meta.get("pipeline") or "") != "recall_secondary"
            else "召回_secondary 未单独查 knowledge_base（案例已并入召回）",
            {"knowledge_hits": meta.get("knowledge_hits", 0), "knowledge_top_k": 5, "is_reaudit": False},
        )
        await self.log(
            "初判",
            "小模型初步判断",
            {
                "verdict": ticket.verdict,
                "reason": ticket.to_dict().get("revision_reason") or out.get("reasoning", ""),
                "confidence": ticket.confidence,
                "need_knowledge": ticket.need_knowledge,
                "matched_rules": out.get("matched_rules", []),
                "version": 1,
                "is_final": False,
                "is_reaudit": False,
                "llm_dialogue": meta.get("trace", {}),
            },
            str(meta.get("secondary_raw") or meta.get("raw") or ""),
        )
        result = {
            "agent": self.name,
            "verdict": ticket.verdict,
            "reason": str(out.get("reasoning", "") or out.get("reason", "") or ""),
            "confidence": ticket.confidence,
            "is_final": False,
            "is_reaudit": False,
            "version": 1,
            "need_knowledge": ticket.need_knowledge,
            "evidence": [e.__dict__ for e in ticket.evidence],
            "detection_details": ticket.to_dict(),
        }
        await self.log("输出结果", "规则执行完成（初判）", result)
        return result

    async def run_reaudit(self, restored_text: str) -> dict[str, Any]:
        """重审（is_final=true, is_reaudit=true）"""
        cfg = self.blackboard.get_state(self.audit_id, "config") or {}
        category_raw = self.blackboard.get_state(self.audit_id, "category") or cfg.get("category")
        cat = str(category_raw).strip() if category_raw else None
        out = await audit_text(
            restored_text,
            rag_service=self.rag,
            llm_client=self.llm,
            rules_top_k=5,
            knowledge_top_k=5,
            category=cat,
            return_trace=True,
        )
        meta = out.get("_meta", {}) if isinstance(out, dict) else {}
        rules = out.get("_rules", []) if isinstance(out, dict) else []
        kb_results = out.get("kb_results", []) if isinstance(out, dict) else []
        ticket = RuleTicket(
            verdict=str(out.get("verdict", Verdict.UNCERTAIN.value)),
            confidence=float(out.get("confidence", 0.5) or 0.5),
            evidence=self._build_evidence(
                rules=rules,
                matched_rules=[str(x) for x in (out.get("matched_rules", []) or [])],
                kb_results=kb_results,
            ),
            need_knowledge=bool(out.get("need_knowledge", False)),
            version=2,
            revision_reason="[对抗变体重审] 使用 restored_text 重新审核",
            raw_llm_output=str(meta.get("secondary_raw") or meta.get("raw") or ""),
            status="complete",
        )
        await self.log("规则检索", "检索到Top-K相关规则", {"top_k": 5, "is_reaudit": True})
        await self.log(
            "知识检索",
            "规则执行员已检索知识库",
            {"knowledge_hits": meta.get("knowledge_hits", 0), "knowledge_top_k": 5, "is_reaudit": True},
        )
        await self.log(
            "重审",
            "对抗变体重审（使用 restored_text 重新审核）",
            {
                "verdict": ticket.verdict,
                "reason": ticket.revision_reason,
                "confidence": ticket.confidence,
                "need_knowledge": ticket.need_knowledge,
                "version": 2,
                "is_final": True,
                "is_reaudit": True,
                "restored_len": len(restored_text or ""),
                "llm_dialogue": meta.get("trace", {}),
            },
            str(meta.get("secondary_raw") or meta.get("raw") or ""),
        )
        result = {
            "agent": self.name,
            "verdict": ticket.verdict,
            "reason": f"{ticket.revision_reason}. {out.get('reasoning', '')}",
            "confidence": ticket.confidence,
            "is_final": True,
            "is_reaudit": True,
            "restored_text": restored_text,
            "version": 2,
            "need_knowledge": ticket.need_knowledge,
            "evidence": [e.__dict__ for e in ticket.evidence],
            "detection_details": ticket.to_dict(),
        }
        await self.log("输出结果", "规则执行完成（重审）", result)
        return result

    async def execute(self, content: str) -> dict:
        # execute 作为兼容入口：默认走初判
        return await self.run_first_pass(content)

