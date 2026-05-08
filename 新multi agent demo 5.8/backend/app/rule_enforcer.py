from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RetrievedRule:
    id: str
    content: str
    score: float
    category: str = ""
    matched_text: str = ""


class RuleEnforcer:
    """
    规则执行员：
    - R1 检索规则库
    - R2 初判
    - R3 仅违规时二次确认
    - R4 初判 uncertain 时二轮检索知识库/案例库补充判断
    """

    def __init__(self, llm: Any = None, kb: Any = None) -> None:
        self.llm = llm
        self.kb = kb

    async def _log(self, blackboard: Any, audit_id: str | None, phase: str, content: str, data: dict[str, Any] | None = None) -> None:
        if blackboard is None or not audit_id:
            return
        try:
            await blackboard.write_entry(
                audit_id=audit_id,
                agent="rule_enforcer",
                zone="rule_zone",
                phase=phase,
                content=content,
                data=data or {},
            )
        except Exception:
            return

    async def execute(self, content: str, category: str, blackboard: Any = None, audit_id: str | None = None) -> Dict:
        """规则执行员完整执行流程"""

        await self._log(blackboard, audit_id, "R1", "开始检索规则库", {"stage": "R1", "category": category})
        # R1: 检索规则库
        retrieved = await self.r1_retrieve(content, category)
        await self._log(
            blackboard,
            audit_id,
            "R1",
            "检索规则库完成",
            {"stage": "R1", "retrieved_count": len(retrieved), "retrieved": [r.__dict__ for r in retrieved[:5]]},
        )

        await self._log(blackboard, audit_id, "R2", "开始初判", {"stage": "R2"})
        # R2: 初判
        primary = await self.r2_primary_judge(content, retrieved, category)
        await self._log(blackboard, audit_id, "R2", "初判完成", {"stage": "R2", **primary})

        # 分支逻辑
        if primary["verdict"] == "violation":
            await self._log(blackboard, audit_id, "R3", "触发二次确认", {"stage": "R3", "primary_verdict": primary["verdict"]})
            # R3: 二次确认（仅违规时）
            secondary = await self.r3_secondary_confirm(content, primary, retrieved)
            await self._log(blackboard, audit_id, "R3", "二次确认完成", {"stage": "R3", **secondary})
            final_verdict = secondary.get("verdict", "review")
            final_confidence = float(secondary.get("confidence", 0.5) or 0.5)
            second_round_verdict = None
            stage = "full_pipeline"
            confirmed = final_verdict == "reject"
            reason = f"初判: {primary['reason']} | 二次确认: {secondary.get('reason', '')}"
            result = {
                "agent": f"{category}_rule_enforcer",
                "verdict": final_verdict,
                "confidence": final_confidence,
                "primary_verdict": primary["verdict"],
                "secondary_verdict": secondary.get("verdict"),
                "second_round_verdict": second_round_verdict,
                "confirmed": confirmed,
                "reason": reason,
                "matches": primary.get("matches", []),
                "retrieved_count": len(retrieved),
                "stage": stage,
            }
            await self._log(blackboard, audit_id, "输出结果", "规则执行完成", result)
            return result

        # 初判非违规：clean 或 uncertain
        second_round = None
        if primary["verdict"] == "uncertain":
            await self._log(blackboard, audit_id, "R4", "初判不确定，开始二轮检索", {"stage": "R4", "primary": primary})
            # 只有 uncertain 才需要二轮检索，clean 直接放行
            second_round = await self.r4_second_round(content, category, primary, retrieved)
            await self._log(blackboard, audit_id, "R4", "二轮检索完成", {"stage": "R4", **second_round})

            if second_round["verdict"] in ["reject", "pass"]:
                # 二轮明确了 → 直接输出
                result = {
                    "agent": f"{category}_rule_enforcer",
                    "verdict": second_round["verdict"],
                    "confidence": second_round["confidence"],
                    "primary_verdict": primary["verdict"],
                    "secondary_verdict": None,
                    "second_round_verdict": second_round["verdict"],
                    "confirmed": second_round["verdict"] == "reject",
                    "reason": f"初判: {primary['reason']} | 二轮检索: {second_round['reason']}",
                    "matches": primary.get("matches", []),
                    "retrieved_count": len(retrieved),
                    "stage": "second_round",
                }
                await self._log(blackboard, audit_id, "输出结果", "规则执行完成", result)
                return result
            else:
                # 二轮后仍不确定 → 输出 review（交给外部深度审核链）
                final_verdict = "review"
                final_confidence = 0.4
        else:
            # 初判 clean → 直接 pass
            final_verdict = "pass"
            final_confidence = float(primary["confidence"])

        result = {
            "agent": f"{category}_rule_enforcer",
            "verdict": final_verdict,
            "confidence": final_confidence,
            "primary_verdict": primary["verdict"],
            "secondary_verdict": None,
            "second_round_verdict": second_round.get("verdict") if second_round else None,
            "confirmed": False,
            "reason": primary["reason"],
            "matches": primary.get("matches", []),
            "retrieved_count": len(retrieved),
            "stage": "primary_only" if primary["verdict"] == "clean" else "second_round_uncertain",
        }
        await self._log(blackboard, audit_id, "输出结果", "规则执行完成", result)
        return result

    async def r1_retrieve(self, content: str, category: str) -> List[RetrievedRule]:
        """R1：检索规则库"""
        if self.kb and hasattr(self.kb, "search_rules"):
            rows = await self.kb.search_rules(query=content, category=category, top_k=5)
            return [
                RetrievedRule(
                    id=str(item.get("id", "")),
                    content=str(item.get("content", item.get("text", "")) or ""),
                    score=float(item.get("score", 0.0) or 0.0),
                    category=str(item.get("category", category) or category),
                    matched_text=str(item.get("matched_text", "") or ""),
                )
                for item in rows
            ]
        return self._fallback_rules(content, category)

    async def r2_primary_judge(self, content: str, retrieved: List[RetrievedRule], category: str) -> Dict[str, Any]:
        """R2：初判"""
        text = content.strip()
        lowered = text.lower()
        matches: list[dict[str, Any]] = []

        if any(k in text for k in ["【违规】", "台独", "独立", "分裂", "煽动", "暴力"]):
            matches.append({"type": "strong_violation", "source": "content"})
            return {
                "verdict": "violation",
                "confidence": 0.95,
                "reason": "命中强违规特征",
                "matches": matches,
            }

        rule_hits = [r for r in retrieved if r.score >= 0.65]
        if rule_hits:
            best = max(rule_hits, key=lambda x: x.score)
            if best.score >= 0.8:
                verdict = "violation" if any(x in best.content for x in ["违规", "禁止", "台独", "煽动", "暴力"]) else "pass"
                confidence = 0.9 if verdict == "violation" else 0.88
                reason = f"规则库高相似命中: {best.id}"
                matches.append({"rule_id": best.id, "score": best.score, "content": best.content[:120]})
                return {"verdict": verdict, "confidence": confidence, "reason": reason, "matches": matches}

        if any(x in lowered for x in ["tw", "td", "zg"]):
            return {
                "verdict": "uncertain",
                "confidence": 0.45,
                "reason": "疑似缩写变体，规则初判不确定",
                "matches": matches,
            }

        if any(x in text for x in ["正常", "合规", "无害", "可公开"]):
            return {
                "verdict": "clean",
                "confidence": 0.92,
                "reason": "命中正常特征",
                "matches": matches,
            }

        if retrieved:
            top = max(retrieved, key=lambda x: x.score)
            if top.score >= 0.6:
                return {
                    "verdict": "uncertain",
                    "confidence": 0.5,
                    "reason": f"规则命中不足，但存在相似规则: {top.id}",
                    "matches": [{"rule_id": top.id, "score": top.score, "content": top.content[:120]}],
                }

        return {
            "verdict": "uncertain",
            "confidence": 0.45,
            "reason": "无法确认",
            "matches": matches,
        }

    async def r3_secondary_confirm(self, content: str, primary_result: Dict, retrieved: List[RetrievedRule]) -> Dict[str, Any]:
        """R3：仅违规时二次确认"""
        strong_rule = [r for r in retrieved if r.score >= 0.8]
        if strong_rule:
            top = max(strong_rule, key=lambda x: x.score)
            if any(k in top.content for k in ["违规", "禁止", "台独", "煽动", "暴力"]):
                return {
                    "verdict": "reject",
                    "confidence": min(0.98, max(0.9, top.score)),
                    "reason": f"二次确认命中强违规规则: {top.id}",
                }
        return {
            "verdict": "review",
            "confidence": 0.55,
            "reason": "二次确认未能消除分歧",
        }

    async def r4_second_round(
        self,
        content: str,
        category: str,
        primary_result: Dict,
        first_retrieved: List[RetrievedRule],
    ) -> Dict:
        """
        二轮检索：当初判 uncertain 时，补充检索知识库/案例库

        与一轮的区别：
        - 一轮：严格规则匹配，高置信才判 violation
        - 二轮：放宽条件，语义相似度/知识库补充匹配
        """
        knowledge_results = await self._search_knowledge(content=content, category=category, top_k=5)
        case_results = await self._search_cases(content=content, category=category, top_k=5, min_similarity=0.5)

        second_items = []
        for k in knowledge_results:
            second_items.append(
                {
                    "id": k["id"],
                    "type": "knowledge",
                    "content": k["content"],
                    "score": k["score"],
                }
            )
        for c in case_results:
            second_items.append(
                {
                    "id": c["id"],
                    "type": "case",
                    "content": c["content"],
                    "score": c["score"] * 0.9,
                }
            )

        # 规则优先：若二轮有高置信命中，则直接明确
        if any(item["type"] == "knowledge" and item["score"] >= 0.75 and self._looks_violative(item["content"]) for item in second_items):
            return {
                "verdict": "reject",
                "confidence": 0.86,
                "reason": f"二轮知识库命中明确违规: {self._top_item_hint(second_items)}",
                "matched_items": self._matched_items(second_items),
                "stage": "second_round",
            }

        viol_cases = [i for i in second_items if i["type"] == "case" and i["score"] >= 0.5 and self._looks_violative(i["content"])]
        if viol_cases and len(viol_cases) >= 1:
            return {
                "verdict": "reject",
                "confidence": 0.82,
                "reason": f"二轮案例库命中违规案例: {viol_cases[0]['id']}",
                "matched_items": self._matched_items(second_items),
                "stage": "second_round",
            }

        if not second_items:
            return {
                "verdict": "review",
                "confidence": 0.4,
                "reason": "二轮未检索到补充资料",
                "matched_items": [],
                "stage": "second_round",
            }

        if any(item["type"] == "knowledge" and item["score"] >= 0.65 and self._looks_clean(item["content"]) for item in second_items):
            return {
                "verdict": "pass",
                "confidence": 0.8,
                "reason": f"二轮知识库支持正常: {self._top_item_hint(second_items)}",
                "matched_items": self._matched_items(second_items),
                "stage": "second_round",
            }

        if any(item["type"] == "case" and item["score"] >= 0.65 and self._looks_clean(item["content"]) for item in second_items):
            return {
                "verdict": "pass",
                "confidence": 0.76,
                "reason": f"二轮案例库支持正常: {self._top_item_hint(second_items)}",
                "matched_items": self._matched_items(second_items),
                "stage": "second_round",
            }

        return {
            "verdict": "review",
            "confidence": 0.4,
            "reason": "二轮检索后仍不确定",
            "matched_items": self._matched_items(second_items),
            "stage": "second_round",
        }

    def _format_second_items(self, items: List[Dict]) -> str:
        """格式化二轮检索结果"""
        lines = []
        for item in items:
            type_label = "【知识】" if item["type"] == "knowledge" else "【案例】"
            lines.append(f"{type_label} {item['id']} (相关度: {item['score']:.2f})\n{item['content']}")
        return "\n\n".join(lines) if lines else "未检索到补充资料"

    async def _search_knowledge(self, content: str, category: str, top_k: int = 5) -> list[dict[str, Any]]:
        if self.kb and hasattr(self.kb, "search_knowledge"):
            return await self.kb.search_knowledge(query=content, category=category, top_k=top_k)
        return self._fallback_knowledge(content, category, top_k)

    async def _search_cases(self, content: str, category: str, top_k: int = 5, min_similarity: float = 0.5) -> list[dict[str, Any]]:
        if self.kb and hasattr(self.kb, "search_cases"):
            return await self.kb.search_cases(query=content, category=category, top_k=top_k, min_similarity=min_similarity)
        return self._fallback_cases(content, category, top_k, min_similarity)

    def _matched_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for item in items:
            out.append(
                {
                    "item_id": item["id"],
                    "item_type": item["type"],
                    "matched_text": str(item["content"])[:120],
                }
            )
        return out

    def _top_item_hint(self, items: list[dict[str, Any]]) -> str:
        if not items:
            return ""
        top = max(items, key=lambda x: float(x.get("score", 0.0) or 0.0))
        return f"{top['type']}:{top['id']}"

    def _looks_violative(self, text: str) -> bool:
        text = str(text or "")
        return any(k in text for k in ["违规", "禁止", "台独", "煽动", "暴力", "分裂"])

    def _looks_clean(self, text: str) -> bool:
        text = str(text or "")
        return any(k in text for k in ["正常", "合规", "无害", "可公开", "允许"])

    def _fallback_rules(self, content: str, category: str) -> List[RetrievedRule]:
        text = str(content or "")
        items = []
        if any(k in text for k in ["台独", "独立", "分裂", "煽动", "暴力"]):
            items.append(RetrievedRule(id=f"{category}_rule_violence_01", content="违规相关规则：涉及分裂、煽动、暴力等内容禁止", score=0.83, category=category))
        if any(k in text for k in ["正常", "合规", "无害", "可公开"]):
            items.append(RetrievedRule(id=f"{category}_rule_normal_01", content="正常表达规则：合规、无害内容可放行", score=0.8, category=category))
        return items

    def _fallback_knowledge(self, content: str, category: str, top_k: int) -> list[dict[str, Any]]:
        text = str(content or "")
        out = []
        if any(k in text for k in ["台独", "独立", "分裂"]):
            out.append({"id": f"{category}_kb_violence_01", "type": "knowledge", "content": "知识：涉及台独、分裂的表达属于敏感违规内容", "score": 0.78})
        if any(k in text for k in ["正常", "合规", "无害"]):
            out.append({"id": f"{category}_kb_normal_01", "type": "knowledge", "content": "知识：正常讨论不应误伤，合规表达可放行", "score": 0.7})
        return out[:top_k]

    def _fallback_cases(self, content: str, category: str, top_k: int, min_similarity: float) -> list[dict[str, Any]]:
        text = str(content or "")
        out = []
        if any(k in text for k in ["台独", "独立", "分裂"]):
            out.append({"id": f"{category}_case_violence_01", "type": "case", "content": "案例：类似台独/分裂表述判定违规", "score": max(0.55, min_similarity)})
        if any(k in text for k in ["正常", "合规", "无害"]):
            out.append({"id": f"{category}_case_normal_01", "type": "case", "content": "案例：正常表达判定正常", "score": max(0.55, min_similarity)})
        return out[:top_k]
