from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse, urlunparse

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, BadRequestError, DEFAULT_TIMEOUT

from app.core.config_manager import ConfigManager
from app.models.config import ModelConfig, ModelProvider, TestConnectionResult


def _normalize_openai_compatible_base_url(url: str) -> str:
    """避免出现 .../chat/completions 被误填进 base_url，SDK 会与路径拼接重复。"""
    u = (url or "").strip().rstrip("/")
    for suf in (
        "/chat/completions",
        "/v1/chat/completions",
        "/compatible-mode/v1/chat/completions",
    ):
        while u.endswith(suf):
            u = u[: -len(suf)].rstrip("/")
    # 只填「https://域名」而未带路径时，自动补上 /v1（聚光/OpenAI 兼容常见漏填）
    parsed = urlparse(u)
    path_clean = (parsed.path or "").strip("/")
    if path_clean == "" and parsed.scheme in ("http", "https") and parsed.netloc:
        u = urlunparse((parsed.scheme, parsed.netloc, "/v1", "", "", "")).rstrip("/")
    return u or url


def _looks_like_qwen_style(base_url: str, model_name: str, provider: ModelProvider | None) -> bool:
    b = (base_url or "").lower()
    m = (model_name or "").lower()
    if provider == ModelProvider.QWEN:
        return True
    return (
        "dashscope" in b
        or "aliyuncs.com" in b
        or "qwen" in b
        or m.startswith("qwen")
        or "-qwen" in m
    )


def _message_variants(system_prompt: str, user_prompt: str) -> list[list[dict[str, str]]]:
    """
    DashScope 要求末尾为 user，且不能只含 system（常见 400）。
    """
    sys_c = (system_prompt or "").strip()
    usr_c = (user_prompt or "").strip()
    if not usr_c:
        usr_c = "（无正文）"

    sys_block = sys_c or "请根据以下内容完成任务。"
    messages_sys_user: list[dict[str, str]] = [
        {"role": "system", "content": sys_block},
        {"role": "user", "content": usr_c},
    ]
    merged = f"[系统指令]\n{sys_block}\n\n[用户内容]\n{usr_c}"
    messages_user_only: list[dict[str, str]] = [{"role": "user", "content": merged}]
    return [messages_sys_user, messages_user_only]


def _format_llm_failure_reason(exc: BaseException) -> str:
    if isinstance(exc, APIConnectionError):
        parts = [exc.message.strip() or "Connection error."]
        req = getattr(exc, "request", None)
        if req is not None:
            try:
                parts.append(f"URL={req.url}")
            except Exception:
                pass
        cause = exc.__cause__ or exc.__context__
        if cause is not None:
            parts.append(f"底层: {type(cause).__name__}: {cause}")
        hint = ""
        msg_l = "; ".join(parts).lower()
        if "ssl" in msg_l or "certificate" in msg_l:
            hint = "（多为证书或 HTTPS 拦截，可检查系统代理/VPN）"
        elif "name or service not known" in msg_l or "nodename nor servname" in msg_l:
            hint = "（DNS 无法解析域名，检查拼写或网络/DNS）"
        elif "refused" in msg_l or "connection refused" in msg_l:
            hint = "（端口被拒绝，检查域名与是否需全局代理访问该站）"
        elif "timed out" in msg_l or "timeout" in msg_l:
            hint = "（连接超时：防火墙、路由器或专线无法访问境外/该主机）"
        return (" | ".join(parts) + hint)[:900]

    if isinstance(exc, APIStatusError):
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("code")
                if msg:
                    return f"{type(exc).__name__}: {msg}"
            inner = body.get("message")
            if isinstance(inner, str) and inner.strip():
                return f"{type(exc).__name__}: {inner[:400]}"
        return f"{type(exc).__name__}: {exc.message[:400]}"
    return f"{type(exc).__name__}: {exc!s}"[:500]


def _iter_qwen_chat_kwargs(
    model: str,
    temperature: float,
    variants: list[list[dict[str, str]]],
) -> Any:
    """通义兼容：依次尝试 temperature+max_tokens、仅 max_tokens、仅 temperature 等组合。"""
    for msgs in variants:
        yield {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": 8192,
        }
        yield {"model": model, "messages": msgs, "max_tokens": 8192}
    for msgs in variants:
        yield {"model": model, "messages": msgs, "temperature": temperature}


class LLMClient:
    def __init__(self, config_manager: ConfigManager, temperature: float = 0.2) -> None:
        self.config_manager = config_manager
        self.temperature = temperature
        self.active_config: ModelConfig | None = None
        self.client: AsyncOpenAI | None = None
        self.logs: list[dict[str, Any]] = []
        self._init_client()

    def _init_client(self) -> None:
        config = self.config_manager.get_default_model_config()
        self.active_config = config
        base = _normalize_openai_compatible_base_url(config.base_url)
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=base,
            timeout=DEFAULT_TIMEOUT,
        )

    def switch_config(self, config_id: str) -> None:
        raw = self.config_manager.get_model_config(config_id)
        config = self.config_manager.apply_llm_env_overlay(raw)
        self.active_config = config
        base = _normalize_openai_compatible_base_url(config.base_url)
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=base,
            timeout=DEFAULT_TIMEOUT,
        )

    async def test_connection(self, config: ModelConfig) -> TestConnectionResult:
        if not str(config.api_key or "").strip():
            return TestConnectionResult(
                success=False,
                message="连接失败：未填写 API Key。可在网页填写，或通过环境变量 JUGUANG_API_KEY / LLM_API_KEY 注入后重启后端。",
            )

        base_raw = _normalize_openai_compatible_base_url(config.base_url)
        if not base_raw.strip():
            return TestConnectionResult(
                success=False,
                message="连接失败：未填写 Base URL。聚光/New API 类服务一般填：https://域名/v1 （末尾须有 /v1，勿带 /chat/completions）。",
            )

        try:
            client = AsyncOpenAI(
                api_key=config.api_key.strip(),
                base_url=base_raw,
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:
            return TestConnectionResult(
                success=False,
                message=f"初始化客户端失败: {_format_llm_failure_reason(exc)}",
            )

        list_err_detail = ""
        try:
            response = await client.models.list()
            return TestConnectionResult(
                success=True,
                message="连接成功（已获取模型列表）。",
                models_available=[m.id for m in response.data],
            )
        except Exception as list_exc:
            list_err_detail = _format_llm_failure_reason(list_exc)

        # 不少三方中继未实现或未开放 GET /v1/models（会 403/404/501），改用最小对话校验密钥与地址
        model_try = (
            (config.small_model or config.strong_model or "gpt-3.5-turbo").strip() or "gpt-3.5-turbo"
        )
        try:
            await client.chat.completions.create(
                model=model_try,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return TestConnectionResult(
                success=True,
                message=(
                    "连接成功：该接口未返回可用模型列表（或列表接口不可用），"
                    f"已用「最小对话」验证通过。列表错误：{list_err_detail}"
                ),
                models_available=[model_try],
            )
        except Exception as chat_exc:
            chat_detail = _format_llm_failure_reason(chat_exc)
            return TestConnectionResult(
                success=False,
                message=(
                    "连接失败。\n"
                    f"1) 列出模型：{list_err_detail}\n"
                    f"2) 最小对话（模型名「{model_try}」）：{chat_detail}\n"
                    "请核对：Base URL 是否类似 https://ai.juguang.chat/v1 （域名以你控制台为准，末尾必须有 /v1）；"
                    "密钥是否完整；「小模型」名称是否与聚光控制台里显示的模型 ID 一致。"
                ),
            )

    def get_model_name(self, model_type: str = "small") -> str:
        if not self.active_config:
            raise ValueError("未配置模型")
        return (
            self.active_config.small_model
            if model_type == "small"
            else self.active_config.strong_model
        )

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        use_strong_model: bool = False,
        temperature: float | None = None,
        return_trace: bool = False,
    ) -> Any:
        if self.client is None or self.active_config is None:
            fallback = "模型未配置"
            if return_trace:
                return {
                    "output_text": fallback,
                    "trace": {
                        "model": "",
                        "temperature": self.temperature if temperature is None else temperature,
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                        "response": fallback,
                    },
                }
            return fallback
        if not str(self.active_config.api_key or "").strip():
            fallback = "未配置API Key，使用本地回退判断。"
            trace = {
                "model": self.get_model_name("strong" if use_strong_model else "small"),
                "temperature": self.temperature if temperature is None else temperature,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response": fallback,
            }
            self.logs.append(trace)
            if return_trace:
                return {"output_text": fallback, "trace": trace}
            return fallback
        selected_model = self.get_model_name("strong" if use_strong_model else "small")
        selected_temperature = (
            self.temperature if temperature is None else temperature
        )
        cfg = self.active_config
        qwen_like = _looks_like_qwen_style(cfg.base_url, selected_model, cfg.provider)
        variants = _message_variants(system_prompt, user_prompt)

        req_log: dict[str, Any] = {
            "model": selected_model,
            "temperature": selected_temperature,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "qwen_compat": qwen_like,
        }

        response = None
        try:
            if not qwen_like:
                response = await self.client.chat.completions.create(
                    model=selected_model,
                    temperature=selected_temperature,
                    messages=variants[0],
                )
            else:
                last_exc: BadRequestError | None = None
                for kwargs in _iter_qwen_chat_kwargs(
                    selected_model, selected_temperature, variants
                ):
                    try:
                        response = await self.client.chat.completions.create(**kwargs)
                        break
                    except BadRequestError as e:
                        last_exc = e
                        continue
                if response is None and last_exc is not None:
                    raise last_exc
                if response is None:
                    raise RuntimeError("模型调用无可行参数组合")
            msg = response.choices[0].message  # type: ignore[union-attr]
            output_text = (msg.content or "").strip()
        except Exception as exc:
            detail = _format_llm_failure_reason(exc)
            output_text = json.dumps(
                {
                    "verdict": "uncertain",
                    "need_knowledge": False,
                    "reason": f"模型调用失败: {detail}",
                    "confidence": 0.0,
                },
                ensure_ascii=False,
            )
            req_log["error"] = detail
            if isinstance(exc, APIStatusError):
                req_log["error_body"] = exc.body

        trace = {**req_log, "response": output_text}
        self.logs.append(trace)
        if return_trace:
            return {"output_text": output_text, "trace": trace}
        return output_text
