from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - optional dependency bootstrap
    AsyncOpenAI = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ModelRouting:
    gateway_model: str = "gpt-4o-mini"
    reasoning_model: str = "gpt-4o"

    @classmethod
    def from_env(cls) -> "ModelRouting":
        return cls(
            gateway_model=os.getenv("OPENAI_GATEWAY_MODEL", "gpt-4o-mini"),
            reasoning_model=os.getenv("OPENAI_REASONING_MODEL", "gpt-4o"),
        )


class LLMEngine:
    """Unified async OpenAI client with JSON-mode routing and retries."""

    _instance: "LLMEngine | None" = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "LLMEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        if AsyncOpenAI is None:
            raise RuntimeError("openai package is required: pip install openai")
        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.routing = ModelRouting.from_env()
        self.max_retries = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
        self.retry_backoff = float(os.getenv("OPENAI_RETRY_BACKOFF", "0.8"))
        self._initialized = True

    async def generate_json(self, prompt: str, system_prompt: str, model_tier: str) -> dict[str, Any]:
        if model_tier == "tier_1":
            return await self.call_gateway_model(system_prompt=system_prompt, user_prompt=prompt)
        if model_tier == "tier_2":
            return await self.call_reasoning_model(system_prompt=system_prompt, user_prompt=prompt)
        raise ValueError(f"Unknown model_tier: {model_tier}")

    async def call_gateway_model(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return await self._call_model(self.routing.gateway_model, system_prompt, user_prompt)

    async def call_reasoning_model(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return await self._call_model(self.routing.reasoning_model, system_prompt, user_prompt)

    async def _call_model(self, model: str, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or "{}"
                return json.loads(content)
            except Exception as exc:  # noqa: BLE001 - API/network/parse failures are unified here
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_backoff * attempt)
                continue
        return {"verdict": "not_participating", "reason": f"LLM API failure: {last_error}"}
