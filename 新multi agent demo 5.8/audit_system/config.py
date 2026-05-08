import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o")  # 优先读取环境配置

# 系统策略
STRATEGY = "安全优先"  # 或 "自由优先"
