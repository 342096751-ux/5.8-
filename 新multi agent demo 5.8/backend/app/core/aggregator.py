from __future__ import annotations

STRATEGY_NAMES = {
    "one_vote_veto": "一票否决",
    "majority_vote": "多数投票",
    "weighted_vote": "加权投票",
    "unanimous": "全票通过",
    "chief_judge_only": "大法官独断",
}

VERDICT_NAMES = {
    "violation": "违规",
    "normal": "正常",
    "uncertain": "不确定",
    "not_participating": "不参与",
}


class Aggregator:
    def __init__(self, config: dict):
        self.strategy = config.get("strategy", "one_vote_veto")
        self.chief_judge_priority = config.get("chief_judge_priority", True)
        self.weights = config.get("weights", {})

    async def aggregate(self, blackboard, audit_id: str) -> dict:
        status = blackboard.get_agent_status(audit_id)
        if status.get("chief_judge") == "running":
            await blackboard.wait_for_agents(audit_id, ["chief_judge"], timeout=60.0)

        active_results = blackboard.get_active_results(audit_id)
        judge_result = active_results.get("chief_judge")

        if judge_result and self.chief_judge_priority:
            return {
                "verdict": judge_result.get("verdict", "normal"),
                "confidence": float(judge_result.get("confidence", 0.95)),
                "reason": f"大法官裁决: {judge_result.get('reason', '')}",
                "judge_overrides": True,
            }

        # 优先读取置信度评估员输出：calibrated_votes -> 过滤 ignored 票
        logs = blackboard.get_logs(audit_id)
        evaluator_entries = [e for e in logs if e.agent == "confidence_evaluator"]
        evaluator_valid_votes: list[dict] = []
        if evaluator_entries:
            data = dict(evaluator_entries[-1].data or {})
            votes = data.get("calibrated_votes", [])
            if isinstance(votes, list):
                evaluator_valid_votes = [
                    v for v in votes if isinstance(v, dict) and not bool(v.get("ignored", False))
                ]

        if self.strategy == "one_vote_veto":
            if evaluator_valid_votes:
                violations = [
                    str(v.get("agent", "unknown"))
                    for v in evaluator_valid_votes
                    if str(v.get("verdict", "")) == "violation"
                ]
                if violations:
                    max_conf = max(float(v.get("calibrated", 0.9) or 0.9) for v in evaluator_valid_votes)
                    return {
                        "verdict": "violation",
                        "confidence": max_conf,
                        "reason": f"置信度评估员有效票触发违规: {', '.join(violations)}",
                        "violations": violations,
                        "source": "confidence_evaluator",
                    }
                return {
                    "verdict": "normal",
                    "confidence": 0.9,
                    "reason": "置信度评估员有效票均未触发违规",
                    "source": "confidence_evaluator",
                }

            violations = [
                name
                for name, result in active_results.items()
                if result.get("verdict") == "violation"
            ]
            if violations:
                return {
                    "verdict": "violation",
                    "confidence": 0.9,
                    "reason": f"以下Agent判定违规: {', '.join(violations)}",
                    "violations": violations,
                }

        return {"verdict": "normal", "confidence": 0.9, "reason": "所有Agent判定正常"}

