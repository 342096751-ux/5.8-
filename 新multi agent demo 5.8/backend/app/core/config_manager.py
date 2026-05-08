import json
import logging
import os
from pathlib import Path

from app.models.config import AgentConfig, ModelConfig, ModelProvider, SystemConfig

logger = logging.getLogger(__name__)


def _default_model_configs() -> list[ModelConfig]:
    """首次使用或磁盘上被写成空数组 [] 时的兜底，避免「一条配置都没有」。"""
    return [
        ModelConfig(
            name="OpenAI-默认",
            provider=ModelProvider.OPENAI,
            api_key="",
            base_url="https://api.openai.com/v1",
            small_model="gpt-3.5-turbo",
            strong_model="gpt-4o",
            embedding_model="text-embedding-3-small",
            is_default=True,
            enabled=True,
        )
    ]


def _read_llm_env_overrides() -> dict:
    """从环境变量读取大模型密钥与地址（可与网页配置叠加，便于只改 .env）。"""
    out: dict = {}
    key = ((os.getenv("LLM_API_KEY") or "").strip() or (os.getenv("JUGUANG_API_KEY") or "").strip())
    if key:
        out["api_key"] = key
    base = ((os.getenv("LLM_BASE_URL") or "").strip() or (os.getenv("JUGUANG_BASE_URL") or "").strip())
    if base:
        out["base_url"] = base
    sm = (os.getenv("LLM_SMALL_MODEL") or "").strip()
    if sm:
        out["small_model"] = sm
    st = (os.getenv("LLM_STRONG_MODEL") or "").strip()
    if st:
        out["strong_model"] = st
    emb = (os.getenv("LLM_EMBEDDING_MODEL") or "").strip()
    if emb:
        out["embedding_model"] = emb
    return out


class ConfigManager:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "config.json"
        self._model_path = data_dir / "model_configs.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._config = SystemConfig(
            agents={
                "rule_executor": AgentConfig(name="rule_executor"),
                "adversarial_detective": AgentConfig(name="adversarial_detective"),
                "case_executor": AgentConfig(name="case_executor"),
                "chief_judge": AgentConfig(name="chief_judge"),
            }
        )
        self._model_configs = _default_model_configs()
        self.load()
        self.load_model_configs()

    def load(self) -> SystemConfig:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._config = SystemConfig.model_validate(data)
        return self._config

    def save(self) -> None:
        self._path.write_text(
            self._config.model_dump_json(indent=2), encoding="utf-8"
        )

    def get(self) -> SystemConfig:
        return self._config

    def update(self, config: SystemConfig) -> SystemConfig:
        self._config = config
        self.save()
        return self._config

    def load_model_configs(self) -> list[ModelConfig]:
        """
        从 model_configs.json 加载。若文件不存在则保留 __init__ 中的默认一条；
        若文件存在但为 []、损坏或条目全部校验失败，则写回一条默认配置，避免列表为空导致「配置全没 / 添加也不显示」。
        """
        if self._model_path.exists():
            try:
                raw = json.loads(self._model_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("读取 model_configs.json 失败，使用默认模型配置: %s", exc)
                self._model_configs = _default_model_configs()
                self.save_model_configs()
                return self._model_configs

            if not isinstance(raw, list):
                raw = []

            loaded: list[ModelConfig] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                try:
                    loaded.append(ModelConfig.model_validate(item))
                except Exception as exc:
                    logger.warning("跳过无效模型配置项: %s", exc)

            self._model_configs = loaded

        if not self._model_configs:
            self._model_configs = _default_model_configs()
            self.save_model_configs()

        return self._model_configs

    def save_model_configs(self) -> None:
        payload = [item.model_dump(mode="json") for item in self._model_configs]
        self._model_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_model_configs(self) -> list[ModelConfig]:
        return self._model_configs

    def get_model_config(self, config_id: str) -> ModelConfig:
        for config in self._model_configs:
            if config.id == config_id:
                return config
        raise ValueError(f"模型配置不存在: {config_id}")

    @staticmethod
    def apply_llm_env_overlay(config: ModelConfig) -> ModelConfig:
        """非空环境变量覆盖对应字段（部署时常用 .env 注入密钥而无需改 JSON）。"""
        extra = _read_llm_env_overrides()
        if not extra:
            return config
        return config.model_copy(update=extra)

    def get_default_model_config(self) -> ModelConfig:
        for config in self._model_configs:
            if config.is_default:
                return self.apply_llm_env_overlay(config)
        if not self._model_configs:
            raise ValueError("没有可用模型配置")
        return self.apply_llm_env_overlay(self._model_configs[0])

    def create_model_config(self, payload: ModelConfig) -> ModelConfig:
        if payload.is_default:
            for item in self._model_configs:
                item.is_default = False
        self._model_configs.append(payload)
        self.save_model_configs()
        return payload

    def update_model_config(self, config_id: str, payload: ModelConfig) -> ModelConfig:
        for idx, item in enumerate(self._model_configs):
            if item.id == config_id:
                updated = payload.model_copy(update={"id": config_id})
                if updated.is_default:
                    for other in self._model_configs:
                        other.is_default = False
                self._model_configs[idx] = updated
                self.save_model_configs()
                return updated
        raise ValueError(f"模型配置不存在: {config_id}")

    def delete_model_config(self, config_id: str) -> None:
        old_len = len(self._model_configs)
        self._model_configs = [item for item in self._model_configs if item.id != config_id]
        if len(self._model_configs) == old_len:
            raise ValueError(f"模型配置不存在: {config_id}")
        if self._model_configs and not any(item.is_default for item in self._model_configs):
            self._model_configs[0].is_default = True
        self.save_model_configs()

    def set_default_model_config(self, config_id: str) -> ModelConfig:
        selected: ModelConfig | None = None
        for item in self._model_configs:
            item.is_default = item.id == config_id
            if item.is_default:
                selected = item
        if selected is None:
            raise ValueError(f"模型配置不存在: {config_id}")
        self.save_model_configs()
        return selected

