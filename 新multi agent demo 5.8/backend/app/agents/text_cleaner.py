from __future__ import annotations

import os
import re
from typing import Any

from app.core.agent_base import BaseAgent
from app.services.text_clean_pipeline import clean_text


_CLEAN_PROMPT = """你是文本清洗员。

任务：只做字符级与智能清洗，不改变语义，不增加新信息，不删减关键含义。

清洗规则（可综合使用）：
- 去除不可见控制字符（如 \\u200b 等零宽字符）、多余重复空白
- 统一全角/半角空白与换行
- 去除明显的乱码分隔符、无意义的重复标点（不影响语义前提下）

输出要求：
- 只输出“清洗后的纯文本”
- 不要任何解释、不要 JSON、不要代码块
"""


def _risk_signals(raw: str, cleaned: str) -> list[str]:
    signals: list[str] = []
    r, c = raw or "", cleaned or ""
    if re.search(r"[\u200b\u200c\u200d\u2060\ufeff]", r, re.I):
        signals.append("检测到零宽字符")
    if "\x00" in r or "\x08" in r:
        signals.append("检测到控制字符")
    if r.strip() != c.strip():
        signals.append("文本经归一化/清洗后与原文不一致")
    return signals


class TextCleaner(BaseAgent):
    """文本清洗员：唯一字符级清洗入口；清洗结果写入 preprocessed_content / cleaned_text。"""

    async def execute(self, content: str) -> dict[str, Any]:
        raw = str(content or "")
        await self.log("清洗输入", "收到原始文本", {"raw_len": len(raw)})

        use_llm = os.getenv("TEXT_CLEANER_USE_LLM", "").strip().lower() in {"1", "true", "yes"}
        if use_llm:
            llm_result = await self.llm.complete(
                system_prompt=_CLEAN_PROMPT,
                user_prompt=raw[:8000],
                use_strong_model=False,
                temperature=0.0,
                return_trace=True,
            )
            out = str(llm_result.get("output_text", "") or "").strip()
            fallback = clean_text(raw)
            cleaned = out
            if not cleaned or cleaned.startswith("{") or cleaned.startswith("["):
                cleaned = fallback
            cleaned = clean_text(cleaned)
        else:
            cleaned = clean_text(raw)

        signals = _risk_signals(raw, cleaned)
        was_modified = raw.strip() != cleaned.strip()

        self.blackboard.set_state(self.audit_id, "preprocessed_content", cleaned)
        self.blackboard.set_state(self.audit_id, "cleaned_text", cleaned)
        self.blackboard.set_state(self.audit_id, "risk_signals", signals)
        self.blackboard.set_state(self.audit_id, "was_cleaned", was_modified)
        await self.log(
            "清洗输出",
            "已输出清洗后的文本",
            {
                "clean_len": len(cleaned),
                "raw_len": len(raw),
                "risk_signals": signals,
                "was_cleaned": was_modified,
                "deterministic_clean": not use_llm,
                "raw_preview": raw[:800],
                "clean_preview": cleaned[:800],
            },
            raw_llm_output=cleaned,
        )
        return {
            "agent": self.name,
            "verdict": "preprocessed",
            "reason": "文本已清洗",
            "confidence": 1.0,
        }
