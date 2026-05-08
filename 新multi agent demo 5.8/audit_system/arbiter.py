from pathlib import Path

from .llm_utils import call_llm
from .models import ArbiterDecision

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(path: str) -> str:
    prompt_path = Path(path)
    if not prompt_path.is_absolute():
        prompt_path = PROMPTS_DIR / prompt_path.name
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def arbitrate(finding, challenges, responses, other_findings, strategy) -> ArbiterDecision:
    template = _load_prompt("prompts/arbiter.txt")
    prompt = template.replace("{strategy}", str(strategy))
    prompt = prompt.replace(
        "{finding}",
        getattr(finding, "model_dump_json", lambda **_: str(finding))(ensure_ascii=False),
    )
    prompt = prompt.replace("{challenges}", str([c.model_dump() for c in challenges]))
    prompt = prompt.replace("{responses}", str([r.model_dump() for r in responses]))
    prompt = prompt.replace(
        "{other_findings}",
        str({k: v.model_dump() for k, v in other_findings.items()}),
    )
    data = call_llm(prompt)
    return ArbiterDecision(**data)
