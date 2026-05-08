from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import yaml

# 项目根目录 = audit_system 的父目录
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_CONFIG_CANDIDATES = ("work_units_config.yaml", "work_units_config.yml")

_DEFAULT_UNITS: list[dict[str, Any]] = [
    {
        "name": "政治审核员",
        "domain": "politics",
        "prompt_file": "prompts/work_unit_politics.txt",
        "enabled": True,
    },
    {
        "name": "色情审核员",
        "domain": "sexual",
        "prompt_file": "prompts/work_unit_sexual.txt",
        "enabled": True,
    },
]


def get_config_path() -> Path:
    for name in _CONFIG_CANDIDATES:
        p = _PROJECT_ROOT / name
        if p.is_file():
            return p
    return _PROJECT_ROOT / "work_units_config.yaml"


def ensure_default_config() -> Path:
    """若不存在 work_units_config.yaml，则创建包含政治/色情的默认文件。"""
    path = get_config_path()
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    save_units_config({"units": deepcopy(_DEFAULT_UNITS)})
    return get_config_path()


def load_units_config() -> dict[str, Any]:
    ensure_default_config()
    path = get_config_path()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {"units": []}
    units = data.get("units")
    if not isinstance(units, list):
        return {"units": []}
    return {"units": units}


def save_units_config(config: dict[str, Any]) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    units = config.get("units")
    if not isinstance(units, list):
        units = []
    to_dump = {"units": units}
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "# 工作单元注册表。可由 Streamlit「Agent 管理」界面编辑，无需手改（也可手改）。\n"
        )
        yaml.dump(to_dump, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _domain_ok(domain: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9_]{0,40}$", domain or ""))


def _safe_basename(prompt_file: str) -> str:
    name = Path(str(prompt_file).strip() or "work_unit_custom.txt").name
    if not name.endswith(".txt"):
        name = f"{name}.txt"
    if re.search(r"[/\\]", str(prompt_file)) and Path(prompt_file).parts != (name,):
        return Path(name).name
    return name


def prompt_abs_path(basename: str) -> Path:
    return (PROMPTS_DIR / _safe_basename(basename)).resolve()


def read_prompt_file(basename: str) -> str:
    p = prompt_abs_path(basename)
    if not p.is_file():
        return ""
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write_prompt_file(basename: str, text: str) -> None:
    p = prompt_abs_path(basename)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def add_agent(
    name: str,
    domain: str,
    prompt_file: str,
    prompt_text: Optional[str] = None,
    enabled: bool = True,
) -> None:
    name = (name or "").strip()
    domain = (domain or "").strip().lower().replace(" ", "_")
    if not name or not domain:
        raise ValueError("名称与领域代号不能为空")
    if not _domain_ok(domain):
        raise ValueError("领域代号需为小写字母/数字/下划线，且勿与系统保留冲突。")
    basename = _safe_basename(prompt_file or f"work_unit_{domain}.txt")
    cfg = load_units_config()
    units: list[dict[str, Any]] = list(cfg.get("units", []))
    for u in units:
        if isinstance(u, dict) and u.get("domain") == domain:
            raise ValueError(f"已存在领域「{domain}」。")
    rel = f"prompts/{basename}"
    if prompt_text is not None and str(prompt_text).strip() != "":
        write_prompt_file(basename, str(prompt_text))
    elif not prompt_abs_path(basename).is_file():
        write_prompt_file(
            basename,
            f"你是负责「{name}」风险域的审核员。请根据待审内容及意图信息输出结构化 JSON（键名中文），\n"
            "格式同其他 work_unit_*.txt。\n\n"
            "待审核内容：{content}\n意图分析结果：{intent_info}\n",
        )
    units.append(
        {
            "name": name,
            "domain": domain,
            "prompt_file": rel,
            "enabled": bool(enabled),
        }
    )
    save_units_config({"units": units})


def remove_agent(index: int) -> None:
    cfg = load_units_config()
    units: list[dict[str, Any]] = list(cfg.get("units", []))
    if index < 0 or index >= len(units):
        raise ValueError("无效的索引")
    units.pop(index)
    save_units_config({"units": units})


def set_agent_enabled(index: int, enabled: bool) -> None:
    cfg = load_units_config()
    units: list[dict[str, Any]] = list(cfg.get("units", []))
    if index < 0 or index >= len(units):
        raise ValueError("无效的索引")
    u = units[index]
    if isinstance(u, dict):
        u["enabled"] = bool(enabled)
    save_units_config({"units": units})


def update_unit_field(index: int, field: str, value: Any) -> None:
    allowed = {"name", "domain", "prompt_file", "enabled"}
    if field not in allowed:
        raise ValueError("不允许的字段")
    cfg = load_units_config()
    units: list[dict[str, Any]] = list(cfg.get("units", []))
    if index < 0 or index >= len(units):
        raise ValueError("无效的索引")
    u = units[index]
    if not isinstance(u, dict):
        return
    if field == "domain":
        v = str(value or "").strip().lower()
        if not _domain_ok(v):
            raise ValueError("领域代号不合法")
        u["domain"] = v
    elif field == "prompt_file":
        u["prompt_file"] = f"prompts/{_safe_basename(str(value))}"
    elif field == "name":
        u["name"] = str(value or "").strip() or u.get("name", "")
    elif field == "enabled":
        u["enabled"] = bool(value)
    save_units_config({"units": units})


def export_config_yaml_string() -> str:
    cfg = load_units_config()
    from io import StringIO

    buf = StringIO()
    yaml.dump(
        {"units": cfg.get("units", [])},
        buf,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    return buf.getvalue()


def import_config_replace(yaml_text: str) -> None:
    data = yaml.safe_load(yaml_text) or {}
    if not isinstance(data, dict) or "units" not in data:
        raise ValueError("YAML 需包含顶键 units: 列表")
    units = data.get("units")
    if not isinstance(units, list):
        raise ValueError("units 须为列表")
    cleaned: list[dict[str, Any]] = []
    for i, u in enumerate(units):
        if not isinstance(u, dict):
            continue
        name = str(u.get("name", "")).strip()
        domain = str(u.get("domain", "")).strip().lower()
        pf = str(u.get("prompt_file", f"work_unit_{domain or i}.txt")).strip()
        if not name or not domain:
            continue
        if "enabled" not in u:
            u = {**u, "enabled": True}
        if not str(pf).startswith("prompts/"):
            pf = f"prompts/{_safe_basename(pf)}"
        cleaned.append(
            {
                "name": name,
                "domain": domain,
                "prompt_file": pf,
                "enabled": bool(u.get("enabled", True)),
            }
        )
    if not cleaned:
        raise ValueError("没有有效的单元项")
    save_units_config({"units": cleaned})


def basename_from_prompt_file(prompt_file: str) -> str:
    return _safe_basename(Path(str(prompt_file)).name)
