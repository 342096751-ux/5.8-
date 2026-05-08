from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Verdict = Literal["violation", "uncertain", "not_participating"]


class GatewayFlags(BaseModel):
    need_knowledge_used: bool = False
    will_participate: bool = False
    use_case_matched: bool = False


class RuleEnforcerStep1Output(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    gateway_flags: GatewayFlags = Field(default_factory=GatewayFlags)
    need_knowledge: bool = False

    @model_validator(mode="after")
    def _normalize(self) -> "RuleEnforcerStep1Output":
        self.gateway_flags.need_knowledge_used = self.need_knowledge
        return self


class RuleEnforcerStep2Input(BaseModel):
    cleaned_text: str
    step1: RuleEnforcerStep1Output
    rule_hits: list[dict[str, str]] = Field(default_factory=list)
    knowledge_hits: list[dict[str, str]] = Field(default_factory=list)


class RuleEnforcerStep2Output(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    gateway_flags: GatewayFlags = Field(default_factory=GatewayFlags)


class RuleEnforcerOutput(BaseModel):
    step1: RuleEnforcerStep1Output
    step2: RuleEnforcerStep2Output | None = None

    @property
    def final(self) -> Verdict:
        return self.step2.verdict if self.step2 else self.step1.verdict


@dataclass
class Blackboard:
    user_text: str = ""
    cleaned_text: str = ""
    findings: dict[str, dict[str, object]] = field(default_factory=dict)
