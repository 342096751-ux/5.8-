import uuid
from enum import Enum

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    name: str
    enabled: bool = True
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    prompt: str = ""


class SystemConfig(BaseModel):
    openai_model: str = "gpt-4o-mini"
    use_llm: bool = False
    agents: dict[str, AgentConfig] = Field(default_factory=dict)


class ModelProvider(str, Enum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    MOONSHOT = "moonshot"
    ZHIPU = "zhipu"
    QWEN = "qwen"
    CUSTOM = "custom"


class ModelConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    provider: ModelProvider
    api_key: str
    base_url: str
    small_model: str = "gpt-3.5-turbo"
    strong_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    is_default: bool = False
    enabled: bool = True


class TestConnectionResult(BaseModel):
    success: bool
    message: str
    models_available: list[str] = Field(default_factory=list)

