import json
from pathlib import Path
from typing import List, Optional

from ..llm_utils import call_llm
from ..models import IntentResult

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(path: str) -> str:
    prompt_path = Path(path)
    if not prompt_path.is_absolute():
        prompt_path = PROMPTS_DIR / prompt_path.name
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def analyze_intent(content: str, available_unit_names: Optional[List[str]] = None) -> IntentResult:
    if not available_unit_names:
        available_unit_names = ["政治审核员", "色情审核员"]
    template = load_prompt("prompts/intent_analyst.txt")
    names_line = json.dumps(available_unit_names, ensure_ascii=False)
    prompt = (
        template.replace("{content}", content)
        .replace("{available_unit_names}", names_line)
    )
    data = call_llm(prompt)
    return IntentResult(**data)
