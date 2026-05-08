from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .llm_client import LLMEngine


@dataclass
class BaseAgent:
    name: str
    llm: LLMEngine

    @classmethod
    def with_default_engine(cls, name: str) -> "BaseAgent":
        return cls(name=name, llm=LLMEngine())

    async def safe_generate_json(self, prompt: str, system_prompt: str, model_tier: str) -> dict[str, Any]:
        try:
            return await self.llm.generate_json(prompt=prompt, system_prompt=system_prompt, model_tier=model_tier)
        except Exception as exc:  # noqa: BLE001 - degrade safely on all failures
            return {"verdict": "not_participating", "reason": f"LLM API failure: {exc}"}
