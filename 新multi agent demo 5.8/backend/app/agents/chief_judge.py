from __future__ import annotations

from typing import Any

from app.core.agent_base import BaseAgent


def _format_retrieved_block(title: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"（无{title}）"
    lines: list[str] = []
    for item in rows:
        rid = str(item.get("id", "") or "")
        doc = str(item.get("document", "") or "")
        d = item.get("distance")
        lines.append(f"- [{rid}] dist={d}\n{doc[:1200]}")
    return "\n".join(lines)


class ChiefJudge(BaseAgent):
    def __init__(
        self,
        *args,
        trigger_on_conflict: bool = True,
        trigger_on_uncertain: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.trigger_on_conflict = trigger_on_conflict
        self.trigger_on_uncertain = trigger_on_uncertain

    async def execute(self, content: str) -> dict:
        # 被动调用模式：由调度器在 Phase 4 明确触发（不监听/不等待）
        await self.log("启动仲裁", "大法官被动触发，开始仲裁", {"mode": "passive"})
        agent_results = list(self.blackboard.get_active_results(self.audit_id).values())
        if not agent_results:
            return {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": "未获取到可用结果",
                "confidence": 0.0,
            }

        from app.services.enhanced_rag import EnhancedRetriever

        cfg = self.blackboard.get_state(self.audit_id, "config") or {}
        focus = self.blackboard.get_state(self.audit_id, "category") or cfg.get("category")
        er = EnhancedRetriever(self.rag)
        bundle = er.comprehensive_retrieve(
            content,
            str(focus) if focus else None,
            rules_top_k=10,
            kb_top_k=5,
            cases_top_k=5,
        )
        rules_block = _format_retrieved_block("规则", bundle.get("rules") or [])
        kb_block = _format_retrieved_block("知识库", bundle.get("knowledge") or [])
        cases_block = _format_retrieved_block("案例", bundle.get("cases") or [])
        await self.log(
            "综合检索",
            "全库多路召回（规则+知识+案例）",
            {
                "rules_n": len(bundle.get("rules") or []),
                "kb_n": len(bundle.get("knowledge") or []),
                "cases_n": len(bundle.get("cases") or []),
                "recall_detail": bundle.get("recall_detail"),
            },
        )
        kb_text = f"{rules_block}\n\n{kb_block}\n\n{cases_block}"
        judge_prompt = (
            "你是终审仲裁引擎，负责解决多Agent意见冲突。\n"
            "你拥有最高裁决权，检索资料是辅助而非唯一依据。\n"
            "若语义上明确违规，即使资料未覆盖也应判 violation（可降低置信度）；"
            "normal 仅用于明显不违规；uncertain 仅用于确实无法判断。\n"
            "禁止把“资料不全”作为 uncertain 的唯一理由。\n"
            "返回JSON:\n"
            '{"verdict":"violation|normal|uncertain","reason":"仲裁理由","confidence":0.95}\n'
            f"清洗后内容: {content}\n争议焦点: {focus or 'general'}\n已有结论: {agent_results}\n\n检索资料:\n{kb_text}"
        )
        llm_result = await self.llm.complete(
            system_prompt="你是最终仲裁者，仅返回JSON。",
            user_prompt=judge_prompt,
            use_strong_model=True,
            return_trace=True,
        )
        raw = llm_result.get("output_text", "")
        llm_dialogue = llm_result.get("trace", {})
        parsed = self.parse_json_output(
            raw,
            {"verdict": "normal", "reason": "fallback", "confidence": 0.6},
        )
        result = {
            "agent": self.name,
            "verdict": parsed.get("verdict", "normal"),
            "reason": parsed.get("reason", ""),
            "confidence": float(parsed.get("confidence", 0.6)),
        }
        await self.log("最终仲裁", "大法官最终裁决", {**result, "llm_dialogue": llm_dialogue}, raw)
        return result

    async def intervene(self, audit_id: str) -> dict:
        """兼容调度接口：按 audit_id 触发大法官。"""
        self.bind_audit(audit_id)
        content = str(
            self.blackboard.get_state(audit_id, "preprocessed_content", "")
            or self.blackboard.get_state(audit_id, "content", "")
            or ""
        )
        return await self.execute(content)

