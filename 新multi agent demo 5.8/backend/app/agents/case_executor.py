from __future__ import annotations

import json
from app.core.agent_base import BaseAgent


class CaseExecutor(BaseAgent):
    async def execute(self, content: str) -> dict:
        # 优先使用真实判例库（CaseService），否则回退向量库原始结果
        similar_cases = []
        if self.case_service is not None and hasattr(self.case_service, "search_cases"):
            similar_cases = await self.case_service.search_cases(content, top_k=3)  # type: ignore[attr-defined]
        else:
            from app.services.enhanced_rag import EnhancedRetriever, score_from_distance

            cfg = self.blackboard.get_state(self.audit_id, "config") or {}
            cat_raw = self.blackboard.get_state(self.audit_id, "category") or cfg.get("category")
            cat = str(cat_raw).strip() if cat_raw else None
            er = EnhancedRetriever(self.rag)
            raw_rows = er.retrieve_cases_filtered(
                content,
                cat,
                top_k=5,
                min_similarity=0.55,
                expand_queries=3,
            )
            for r in raw_rows:
                sim = float(r.get("_sim", score_from_distance(r)))
                similar_cases.append(
                    {
                        "case": {
                            "id": r.get("id", ""),
                            "text": r.get("document", ""),
                            "verdict": str((r.get("metadata") or {}).get("verdict", "")),
                            "violation_reason": str(
                                (r.get("metadata") or {}).get("violation_reason", "")
                            ),
                            "category": str((r.get("metadata") or {}).get("category", "未分类")),
                            "confidence": 0.8,
                        },
                        "similarity": sim,
                        "matched_text": r.get("document", ""),
                    }
                )

        await self.log(
            "判例检索",
            "检索到Top-3条相关判例",
            {
                "cases_count": len(similar_cases),
                "case_ids": [
                    (c.get("case").id if hasattr(c.get("case"), "id") else c.get("case", {}).get("id"))
                    for c in similar_cases
                ][:10],
            },
        )
        if not similar_cases:
            result = {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": "判例库中未检索到相似案例",
                "confidence": 1.0,
                "detection_details": {"retrieved_cases": [], "use_case": False},
            }
            await self.log("输出结果", "判例执行员不参与", result)
            return result

        cases_desc_lines = []
        for i, item in enumerate(similar_cases):
            case = item.get("case")
            if hasattr(case, "to_dict"):
                cd = case.to_dict()
                cid = cd.get("id")
                ctext = cd.get("text", "")
                cver = cd.get("verdict")
                creason = cd.get("violation_reason", "")
            else:
                cd = dict(case or {})
                cid = cd.get("id")
                ctext = cd.get("text", "")
                cver = cd.get("verdict")
                creason = cd.get("violation_reason", "")
            sim = float(item.get("similarity", 0.0) or 0.0)
            cases_desc_lines.append(
                f"判例{i+1}: id={cid} verdict={cver} similarity={sim:.3f} text={str(ctext)[:100]} reason={str(creason)[:80]}"
            )
        cases_desc = "\n".join(cases_desc_lines)

        use_case_prompt = f"""【系统】你是判例匹配与参考引擎。

【待审核文本】
{content}

【检索到的相似判例】
{cases_desc}

判定原则：
- 案例是参考，不是唯一依据
- 即使案例召回较弱，也可基于语义判断是否建议 use_case=true（可降低置信度）
- 不能因为“没案例”就机械地判 not_similar/use_case=false

【输出要求】只输出JSON:
{{
  \"use_case\": true|false,
  \"confidence\": 0.0-1.0,
  \"reasoning\": \"案例匹配理由（可引用文本依据）\",
  \"relevant_case_ids\": [\"CASE_001\"]
}}
"""
        llm_result = await self.llm.complete(
            system_prompt="你是判例审核员，仅返回JSON。",
            user_prompt=use_case_prompt,
            use_strong_model=False,
            return_trace=True,
            temperature=0.1,
        )
        raw = llm_result.get("output_text", "")
        llm_dialogue = llm_result.get("trace", {})
        decision = self.parse_json_output(
            raw,
            {"use_case": False, "confidence": 0.6, "reasoning": "解析失败，默认不引用", "relevant_case_ids": []},
        )
        await self.log("采纳判断", "判断是否采纳判例", {**decision, "llm_dialogue": llm_dialogue}, raw)
        if not bool(decision.get("use_case", False)):
            result = {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": f"LLM判断不引用历史判例: {decision.get('reasoning', '')}",
                "confidence": float(decision.get("confidence", 0.7) or 0.7),
                "detection_details": {
                    "retrieved_cases": [
                        (c.get("case").to_dict() if hasattr(c.get("case"), "to_dict") else c.get("case"))
                        for c in similar_cases
                    ],
                    "use_case": False,
                    "reasoning": decision.get("reasoning", ""),
                },
            }
            await self.log("输出结果", "判例执行员不采纳判例", result)
            return result

        rel_ids = set(str(x) for x in (decision.get("relevant_case_ids") or []) if str(x).strip())
        scoped = []
        if rel_ids:
            for item in similar_cases:
                case = item.get("case")
                cid = case.id if hasattr(case, "id") else (case or {}).get("id")
                if str(cid) in rel_ids:
                    scoped.append(item)
        else:
            scoped = list(similar_cases)

        if not scoped:
            scoped = list(similar_cases)

        votes: list[dict] = []
        for item in scoped:
            case = item.get("case")
            sim = float(item.get("similarity", 0.0) or 0.0)
            if hasattr(case, "to_dict"):
                cd = case.to_dict()
            else:
                cd = dict(case or {})
            vote = {
                "case_id": cd.get("id"),
                "verdict": cd.get("verdict"),
                "similarity": sim,
                "weight": sim,
                "reason": cd.get("violation_reason", ""),
                "category": cd.get("category", "未分类"),
            }
            votes.append(vote)

        total_weight = sum(float(v.get("weight", 0.0) or 0.0) for v in votes) or 0.0
        vio_w = sum(float(v.get("weight", 0.0) or 0.0) for v in votes if v.get("verdict") == "violation")
        nor_w = sum(float(v.get("weight", 0.0) or 0.0) for v in votes if v.get("verdict") == "normal")
        if vio_w > nor_w:
            verdict = "violation"
            confidence = (vio_w / total_weight) if total_weight > 0 else 0.5
            reasoning = f"多数判例(加权)判定违规: {[v.get('case_id') for v in votes if v.get('verdict')=='violation']}"
        elif nor_w > vio_w:
            verdict = "normal"
            confidence = (nor_w / total_weight) if total_weight > 0 else 0.5
            reasoning = f"多数判例(加权)判定正常: {[v.get('case_id') for v in votes if v.get('verdict')=='normal']}"
        else:
            verdict = "uncertain"
            confidence = 0.5
            reasoning = "判例投票平局，无法确定"
        result = {
            "agent": self.name,
            "verdict": verdict,
            "reason": reasoning,
            "confidence": float(confidence),
            "detection_details": {
                "retrieved_cases": [
                    (c.get("case").to_dict() if hasattr(c.get("case"), "to_dict") else c.get("case"))
                    for c in similar_cases
                ],
                "use_case": True,
                "votes": votes,
                "version": 1,
            },
        }
        await self.log(
            "多数投票",
            "判例投票统计",
            {"violation_weight": vio_w, "normal_weight": nor_w, "votes": votes, **result},
            raw_llm_output=str(raw) if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False),
        )
        return result

