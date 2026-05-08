import json
import re
from typing import Union

import openai

from .config import MODEL_NAME, OPENAI_API_KEY

client = openai.OpenAI(api_key=OPENAI_API_KEY)
_LLM_TRACE: list[dict] = []


def reset_llm_trace() -> None:
    _LLM_TRACE.clear()


def get_llm_trace() -> list[dict]:
    return list(_LLM_TRACE)


def call_llm(
    prompt: str,
    system_msg: str = "你是一个严格的JSON生成器，只返回要求的JSON。",
) -> Union[dict, list]:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content or ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match_obj = re.search(r"\{.*\}", text, flags=re.DOTALL)
        match_arr = re.search(r"\[.*\]", text, flags=re.DOTALL)
        if match_arr:
            parsed = json.loads(match_arr.group(0))
        elif match_obj:
            parsed = json.loads(match_obj.group(0))
        else:
            raise
    _LLM_TRACE.append(
        {
            "model": MODEL_NAME,
            "temperature": 0.0,
            "response_format": "json_object",
            "system_msg": system_msg,
            "user_prompt": prompt,
            "raw_response": text,
            "parsed_response": parsed,
        }
    )
    return parsed
