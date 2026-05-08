from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from app.core.blackboard import Blackboard
from app.services.llm_client import LLMClient
from app.services.rag_service import RAGService


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        zone: str,
        blackboard: Blackboard,
        llm_client: LLMClient,
        rag_service: RAGService,
        case_service: object | None = None,
    ) -> None:
        self.name = name
        self.zone = zone
        self.blackboard = blackboard
        self.llm = llm_client
        self.rag = rag_service
        # 可选注入（判例执行员使用）
        self.case_service = case_service
        self.audit_id: str = ""

    @abstractmethod
    async def execute(self, content: str) -> dict:
        raise NotImplementedError

    def bind_audit(self, audit_id: str) -> None:
        self.audit_id = audit_id

    async def log(
        self,
        phase: str,
        content: str,
        data: dict | None = None,
        raw_llm_output: str | None = None,
    ) -> None:
        if not self.audit_id:
            raise ValueError("audit_id is not bound, call bind_audit first")
        await self.blackboard.write_entry(
            audit_id=self.audit_id,
            agent=self.name,
            zone=self.zone,
            phase=phase,
            content=content,
            data=data or {},
            raw_llm_output=raw_llm_output,
        )

    @staticmethod
    def parse_json_output(raw: str, fallback: dict) -> dict:
        text = str(raw or "").strip()
        if not text:
            return fallback
        # 兼容 ```json ... ``` / ``` ... ``` 包裹
        if "```" in text:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
            if m:
                text = m.group(1).strip()
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else fallback
        except Exception:
            # 兼容前后有解释文字，只提取第一个 JSON 对象
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    return obj if isinstance(obj, dict) else fallback
                except Exception:
                    pass
            return fallback

