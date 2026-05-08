from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AuditCase:
    """审核判例（用于判例库 Case Base）。"""

    id: str
    text: str
    verdict: str  # "violation" | "normal"
    violation_reason: str
    category: str
    confidence: float = 0.8
    matched_rules: list[str] = field(default_factory=list)
    source: str = "manual"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "verdict": self.verdict,
            "violation_reason": self.violation_reason,
            "category": self.category,
            "confidence": self.confidence,
            "matched_rules": list(self.matched_rules),
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditCase":
        return cls(
            id=str(data["id"]),
            text=str(data.get("text", "") or ""),
            verdict=str(data.get("verdict", "") or ""),
            violation_reason=str(data.get("violation_reason", "") or ""),
            category=str(data.get("category", "未分类") or "未分类"),
            confidence=float(data.get("confidence", 0.8) or 0.8),
            matched_rules=[str(x) for x in (data.get("matched_rules") or []) if str(x).strip()],
            source=str(data.get("source", "manual") or "manual"),
            created_at=str(data.get("created_at") or datetime.utcnow().isoformat()),
            updated_at=data.get("updated_at"),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_embedding_text(self) -> str:
        verdict_cn = "违规" if self.verdict == "violation" else "正常"
        return (
            f"类别: {self.category}\n"
            f"文本内容: {self.text}\n"
            f"判定结果: {verdict_cn}\n"
            f"违规原因: {self.violation_reason}"
        ).strip()

