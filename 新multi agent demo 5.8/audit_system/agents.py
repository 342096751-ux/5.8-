from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base_agent import BaseAgent
from .schemas import (
    Blackboard,
    RuleEnforcerOutput,
    RuleEnforcerStep1Output,
    RuleEnforcerStep2Input,
    RuleEnforcerStep2Output,
    Verdict,
)
from .tools import query_knowledge_base, query_rule_base


@dataclass
class RuleEnforcer(BaseAgent):
    """Gateway-first, two-step state machine for rule-based inspection.

    Step 1 is a lightweight gateway that only decides:
    - whether the agent should participate
    - whether knowledge retrieval is needed

    Step 2 is only entered when Step 1 allows it.
    """

    top_k_rules: int = 3
    top_k_knowledge: int = 3

    def __init__(self, llm: Any | None = None, name: str = "RuleEnforcer") -> None:
        super().__init__(name=name, llm=llm or BaseAgent.with_default_engine(name).llm)
        self.top_k_rules = 3
        self.top_k_knowledge = 3

    def step1(self, cleaned_text: str) -> RuleEnforcerStep1Output:
        rule_hits = query_rule_base(cleaned_text, top_k=self.top_k_rules)
        need_knowledge = self._should_use_knowledge(rule_hits=rule_hits, cleaned_text=cleaned_text)
        verdict = self._gateway_verdict(rule_hits=rule_hits)
        confidence = self._step1_confidence(rule_hits=rule_hits, verdict=verdict)
        reason = self._build_reason("step1", rule_hits=rule_hits)
        return RuleEnforcerStep1Output(
            verdict=verdict,
            confidence=confidence,
            reason=reason,
            need_knowledge=need_knowledge,
        )

    def step2(self, payload: RuleEnforcerStep2Input) -> RuleEnforcerStep2Output:
        rule_hits = payload.rule_hits or query_rule_base(payload.cleaned_text, top_k=self.top_k_rules)
        knowledge_hits = list(payload.knowledge_hits)

        if payload.step1.need_knowledge and not knowledge_hits:
            knowledge_hits = query_knowledge_base(payload.cleaned_text, top_k=self.top_k_knowledge)

        verdict, confidence = self._derive_final_verdict(
            step1_verdict=payload.step1.verdict,
            rule_hits=rule_hits,
            knowledge_hits=knowledge_hits,
            need_knowledge=payload.step1.need_knowledge,
        )
        reason = self._build_reason("step2", rule_hits=rule_hits, knowledge_hits=knowledge_hits)
        return RuleEnforcerStep2Output(
            verdict=verdict,
            confidence=confidence,
            reason=reason,
            gateway_flags=payload.step1.gateway_flags,
        )

    def run(self, blackboard: Blackboard) -> RuleEnforcerOutput:
        step1 = self.step1(blackboard.cleaned_text)
        if not step1.gateway_flags.will_participate and not step1.need_knowledge:
            result = RuleEnforcerOutput(step1=step1)
        else:
            rule_hits = query_rule_base(blackboard.cleaned_text, top_k=self.top_k_rules)
            knowledge_hits = (
                query_knowledge_base(blackboard.cleaned_text, top_k=self.top_k_knowledge)
                if step1.need_knowledge
                else []
            )
            step2 = self.step2(
                RuleEnforcerStep2Input(
                    cleaned_text=blackboard.cleaned_text,
                    step1=step1,
                    rule_hits=rule_hits,
                    knowledge_hits=knowledge_hits,
                )
            )
            result = RuleEnforcerOutput(step1=step1, step2=step2)

        blackboard.findings["RuleEnforcer"] = result.model_dump()
        return result

    def _gateway_verdict(self, rule_hits: list[dict[str, Any]]) -> Verdict:
        if not rule_hits:
            return "not_participating"
        return "violation"

    def _should_use_knowledge(self, rule_hits: list[dict[str, Any]], cleaned_text: str) -> bool:
        return bool(rule_hits) and (
            any(self._looks_ambiguous(hit) for hit in rule_hits)
            or self._contains_uncertain_tokens(cleaned_text)
        )

    def _step1_confidence(self, rule_hits: list[dict[str, Any]], verdict: Verdict) -> float:
        if verdict == "not_participating":
            return 0.1
        if not rule_hits:
            return 0.2
        return min(0.9, 0.65 + 0.1 * min(len(rule_hits), 2))

    def _derive_final_verdict(
        self,
        *,
        step1_verdict: Verdict,
        rule_hits: list[dict[str, Any]],
        knowledge_hits: list[dict[str, Any]],
        need_knowledge: bool,
    ) -> tuple[Verdict, float]:
        if not rule_hits:
            return "not_participating", 0.15
        if knowledge_hits:
            return "violation", 0.93
        if need_knowledge:
            return "uncertain", 0.52
        if step1_verdict == "violation":
            return "violation", 0.8
        return "uncertain", 0.45

    @staticmethod
    def _looks_ambiguous(hit: dict[str, Any]) -> bool:
        score = float(hit.get("score", 0))
        return score < 0.92

    @staticmethod
    def _contains_uncertain_tokens(text: str) -> bool:
        tokens = ("黑话", "谐音", "缩写", "变体", "代称", "混淆", "暗示")
        return any(token in text for token in tokens)

    @staticmethod
    def _build_reason(stage: str, **artifacts: Any) -> str:
        pieces: list[str] = [f"{stage}完成"]
        if artifacts.get("rule_hits"):
            pieces.append(
                "命中规则ID=" + ",".join(str(hit.get("rule_id", "unknown")) for hit in artifacts["rule_hits"])
            )
        if artifacts.get("knowledge_hits"):
            pieces.append(
                "知识命中=" + ",".join(str(hit.get("entity", "unknown")) for hit in artifacts["knowledge_hits"])
            )
        return "；".join(pieces)
