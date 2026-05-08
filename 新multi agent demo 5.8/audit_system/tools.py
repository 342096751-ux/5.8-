from __future__ import annotations

from typing import Any


def query_rule_base(text: str, top_k: int = 3) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "R-001",
            "title": "示例规则：禁止违规推广",
            "matched_text": text[:40],
            "score": 0.91,
        }
    ][:top_k]


def query_knowledge_base(term: str, top_k: int = 3) -> list[dict[str, Any]]:
    return [
        {
            "entity": term,
            "definition": "示例知识：用于还原混淆语义的词条解释",
            "source": "kb-demo",
        }
    ][:top_k]


def query_case_base(text: str, top_k: int = 3) -> list[dict[str, Any]]:
    return [
        {
            "case_id": "C-1001",
            "summary": "与疑似违规表述高度相似的历史判例",
            "outcome": "violation",
        }
    ][:top_k]
