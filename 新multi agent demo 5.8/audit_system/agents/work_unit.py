from pathlib import Path

from ..llm_utils import call_llm
from ..models import WorkUnitFinding
from ..tools.knowledge_base import query_knowledge_base

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class WorkUnit:
    def __init__(self, domain: str, prompt_path: str):
        self.domain = domain
        path = Path(prompt_path)
        if not path.is_absolute():
            path = PROMPTS_DIR / path.name
        with open(path, "r", encoding="utf-8") as f:
            self.template = f.read()

    def run(self, content: str, intent_info: str) -> WorkUnitFinding:
        prompt = self.template.replace("{content}", content).replace("{intent_info}", intent_info)
        data = call_llm(prompt)
        finding = WorkUnitFinding(**data)

        max_retries = 2
        for _ in range(max_retries):
            if not finding.自我检查.是否需要补全:
                break
            extra_info = query_knowledge_base(content, self.domain)
            retry_prompt = self.template.replace("{content}", content).replace("{intent_info}", intent_info)
            retry_prompt += f"\n\n补充信息：{extra_info}"
            data = call_llm(retry_prompt)
            finding = WorkUnitFinding(**data)
        return finding
