from typing import List, Optional
from pathlib import Path

from ..llm_utils import call_llm
from ..models import Challenge, WorkUnitFinding, WorkUnitResponse

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompt(path: str) -> str:
    prompt_path = Path(path)
    if not prompt_path.is_absolute():
        prompt_path = PROMPTS_DIR / prompt_path.name
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def generate_challenges(
    original_content: str,
    finding: WorkUnitFinding,
    other_findings: Optional[dict] = None,
) -> List[Challenge]:
    template = _load_prompt("prompts/verifier.txt")
    prompt = template.replace("{original_content}", original_content)
    prompt = prompt.replace("{work_unit_finding}", finding.model_dump_json(ensure_ascii=False))
    prompt = prompt.replace("{other_findings}", str(other_findings or {}))
    data = call_llm(prompt)
    challenge_items = data if isinstance(data, list) else data.get("质疑列表", [])
    return [Challenge(**item) for item in challenge_items]


def evaluate_response(challenge: Challenge, response: WorkUnitResponse) -> bool:
    if response.回应动作 == "补充信息" and len(response.补充证据) > 0 and not response.是否需要补全:
        return True
    if response.回应动作 == "修改结论" and response.新结论 in {"违规", "安全", "存疑"}:
        return True
    if response.回应动作 == "反驳质疑" and len(response.反驳理由.strip()) > 10:
        return True
    if challenge.建议动作 == "补充证据" and response.是否需要补全:
        return False
    return False
