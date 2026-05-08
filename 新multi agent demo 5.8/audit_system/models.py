from typing import List, Optional

from pydantic import BaseModel


class IntentResult(BaseModel):
    意图标签: List[str] = []
    建议激活单元: List[str] = []
    关键词: List[str] = []
    简述: str = ""


class Evidence(BaseModel):
    内容片段: str
    依据条款: str


class SelfCheck(BaseModel):
    证据是否充分: bool
    歧义是否排除: bool
    是否需要补全: bool


class WorkUnitFinding(BaseModel):
    结论: str  # 违规/安全/存疑
    严重程度: str  # 高/中/低
    置信度: str  # 高/中/低
    证据: List[Evidence] = []
    自我检查: SelfCheck
    推理过程: str


class Challenge(BaseModel):
    质疑类型: str  # 证据不足/标准误用/忽略语境/跨单元冲突
    指向发现ID: str = ""
    质疑理由: str
    建议动作: str  # 修改结论/推翻结论/补充证据


class WorkUnitResponse(BaseModel):
    回应动作: str  # 修改结论/反驳质疑/补充信息
    补充证据: List[Evidence] = []
    新结论: Optional[str] = None
    反驳理由: str = ""
    是否需要补全: bool = False


class ArbiterDecision(BaseModel):
    最终判定: str  # 违规/安全/存疑
    执行动作: str  # 拦截/放行/放行但记录
    判定依据: str  # 证据强度/交叉验证/策略兜底/证据不足/标准错配
    简要理由: str
    采纳的证据: str
    拒绝的主张: str
