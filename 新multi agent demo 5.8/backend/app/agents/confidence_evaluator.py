from __future__ import annotations

import json
import logging
import math
from typing import Any

from app.core.agent_base import BaseAgent

logger = logging.getLogger(__name__)


def _safe_confidence(value: Any, default: float = 0.5) -> float:
    """规则/案例/对抗节点里的 confidence 可能非数字，避免 float() 抛错。"""
    if value is None:
        return default
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(x):
        return default
    return max(0.0, min(1.0, x))


def _json_safe_floats(obj: Any) -> Any:
    """黑板 WebSocket JSON 序列化不支持 NaN/inf，递归替换为有限数。"""
    if isinstance(obj, float):
        if math.isfinite(obj):
            return obj
        return 0.0
    if isinstance(obj, dict):
        return {k: _json_safe_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe_floats(v) for v in obj]
    return obj


class ConfidenceEvaluator(BaseAgent):
    """
    置信度评估员（A）：
    - 在 R/V/C 后执行
    - 对票据按历史权重校准
    - 给出是否建议大法官介入
    """

    # 默认不对抗计票；若对抗输出 adversarial_judgment（full 管线）则与其它 Agent 同台校准
    WEIGHTS: dict[str, float] = {
        "rule_executor": 0.9,
        "case_executor": 0.8,
        "adversarial_detective": 0.82,
    }
    CONFLICT_THRESHOLD = 0.6
    LOW_CONFIDENCE = 0.4
    ARBITRATION_MIN = 0.5

    _SYSTEM_PROMPT = """你是一名审核质量评估员，仅输出 JSON。

任务：
1) 读取 agent_results（规则、案例；若有 adversarial_detective 则一并计入）；
2) 忽略不参与票，校准置信度 = confidence * weight（保留 3 位小数）；
3) 冲突：同时存在 violation 和 uncertain 且相关票 calibrated > 0.6；
4) 低置信：calibrated < 0.4 计为 ignored；
5) suggest_arbitration 为 true 的条件：
   - conflict_detected=true，或
   - max_calibrated < 0.5，或
   - low_confidence_count > 0。

输出格式：
{
  "calibrated_votes":[
    {"agent":"rule_executor","verdict":"violation","raw":0.92,"calibrated":0.828,"weight":0.9,"ignored":false}
  ],
  "summary":{
    "violation_count":1,
    "uncertain_count":1,
    "max_calibrated":0.828,
    "conflict_detected":true,
    "low_confidence_count":0
  },
  "suggest_arbitration":true,
  "reason":"检测到冲突",
  "recommended_action":"建议大法官介入"
}
"""

    async def should_trigger(self, audit_id: str) -> bool:
        """兼容调度接口：R/V/C 都有结果且尚未评估时触发。"""
        # 仍然要求第一波三Agent都完成（含对抗侦探），但评估阶段只对 R/C 计票
        base_agents = {"rule_executor", "adversarial_detective", "case_executor"}
        done = set(self.blackboard.get_agent_results(audit_id).keys()) & base_agents
        has_a = "confidence_evaluator" in self.blackboard.get_agent_results(audit_id)
        return len(done) == 3 and not has_a

    async def evaluate(self, audit_id: str) -> dict[str, Any]:
        """兼容调度接口：按 audit_id 执行评估。"""
        # 实例可能被调度复用，必须每次绑定当前 audit_id
        self.bind_audit(audit_id)
        content = str(
            self.blackboard.get_state(audit_id, "preprocessed_content", "")
            or self.blackboard.get_state(audit_id, "content", "")
            or ""
        )
        return await self.execute(content)

    async def execute(self, content: str) -> dict[str, Any]:
        await self.log("收集票据", "开始收集 R/V/(C)（及可选对抗 full 票据）")
        base_agents = ["rule_executor", "case_executor"]
        source = self.blackboard.get_agent_results(self.audit_id)

        agent_results: list[dict[str, Any]] = []
        for name in base_agents:
            one = source.get(name) or {}
            verdict = str(one.get("verdict", "") or "").strip()
            if verdict in {"", "not_participate", "not_participating", "not_intervene"}:
                continue
            if name == "rule_executor" and not bool(one.get("is_final", False)):
                # 只取规则执行员最终版（Phase 2 之后才会被标记/覆盖）
                continue
            agent_results.append(
                {
                    "agent": name,
                    "verdict": verdict,
                    "confidence": _safe_confidence(one.get("confidence", 0.0)),
                    "reason": str(one.get("reason", "") or ""),
                }
            )

        adv = source.get("adversarial_detective") or {}
        if (
            isinstance(adv, dict)
            and bool(adv.get("adversarial_judgment"))
            and str(adv.get("verdict", "")).strip()
            not in {"", "not_participate", "not_participating", "participating"}
        ):
            agent_results.append(
                {
                    "agent": "adversarial_detective",
                    "verdict": str(adv.get("verdict", "")).strip(),
                    "confidence": _safe_confidence(adv.get("confidence", 0.0)),
                    "reason": str(adv.get("reason", "") or ""),
                }
            )

        if not agent_results:
            result = {
                "agent": self.name,
                "calibrated_votes": [],
                "summary": {
                    "violation_count": 0,
                    "uncertain_count": 0,
                    "max_calibrated": 0.0,
                    "conflict_detected": False,
                    "low_confidence_count": 0,
                },
                "suggest_arbitration": False,
                "reason": "所有Agent均未参与",
                "recommended_action": "直接交由聚合器",
            }
            await self.log("评估完成", "所有Agent未参与，跳过介入建议", _json_safe_floats(result))
            return result

        prompt = json.dumps(
            {"content": content, "agent_results": agent_results, "weights": self.WEIGHTS},
            ensure_ascii=False,
        )
        raw = ""
        try:
            llm_result = await self.llm.complete(
                system_prompt=self._SYSTEM_PROMPT,
                user_prompt=prompt,
                use_strong_model=False,
                temperature=0.1,
                return_trace=True,
            )
            raw = llm_result.get("output_text", "")
            parsed = self.parse_json_output(raw, {})
            if not isinstance(parsed, dict) or "calibrated_votes" not in parsed:
                parsed = self._fallback_calculate(agent_results)
        except Exception as exc:
            logger.warning(
                "confidence_evaluator LLM/解析失败，已本地回退: %s", exc, exc_info=True
            )
            parsed = self._fallback_calculate(agent_results)
            raw = raw or "(llm 失败，已本地回退)"

        result = _json_safe_floats({"agent": self.name, **parsed})
        await self.log("评估完成", "置信度评估已完成", result, raw if raw else None)
        return result

    def _fallback_calculate(self, agent_results: list[dict[str, Any]]) -> dict[str, Any]:
        calibrated: list[dict[str, Any]] = []
        v_count = 0
        u_count = 0
        low_count = 0
        max_cal = 0.0

        for r in agent_results:
            w = float(self.WEIGHTS.get(r["agent"], 0.8))
            raw = _safe_confidence(r.get("confidence", 0.0))
            cal = round(raw * w, 3)
            ignored = cal < self.LOW_CONFIDENCE
            if ignored:
                low_count += 1
            if r.get("verdict") == "violation":
                v_count += 1
            elif r.get("verdict") == "uncertain":
                u_count += 1
            max_cal = max(max_cal, cal)
            calibrated.append(
                {
                    "agent": r.get("agent"),
                    "verdict": r.get("verdict"),
                    "raw": raw,
                    "calibrated": cal,
                    "weight": w,
                    "ignored": ignored,
                }
            )

        conflict = v_count > 0 and u_count > 0 and max_cal > self.CONFLICT_THRESHOLD
        suggest = conflict or max_cal < self.ARBITRATION_MIN or low_count > 0
        return {
            "calibrated_votes": calibrated,
            "summary": {
                "violation_count": v_count,
                "uncertain_count": u_count,
                "max_calibrated": max_cal,
                "conflict_detected": conflict,
                "low_confidence_count": low_count,
            },
            "suggest_arbitration": suggest,
            "reason": f"冲突：{v_count}违规 vs {u_count}不确定" if conflict else "无冲突",
            "recommended_action": "建议大法官介入" if suggest else "直接聚合",
        }
