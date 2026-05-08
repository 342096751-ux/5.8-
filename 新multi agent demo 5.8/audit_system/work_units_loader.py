from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import agent_manager
from .agents.work_unit import WorkUnit

# audit_system/ 的上一级为项目根目录（与 agent_manager 一致）
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_NAMES = ("work_units_config.yaml", "work_units_config.yml")


def _config_path() -> Path:
    """与 agent_manager 使用同一套路径逻辑；优先从 agent_manager 获取。"""
    p = agent_manager.get_config_path()
    if p.is_file():
        return p
    for name in _CONFIG_NAMES:
        cand = _PROJECT_ROOT / name
        if cand.is_file():
            return cand
    return p


def load_work_units_config_raw() -> dict[str, Any]:
    """读取 YAML 原始内容；不替代 agent_manager 的写操作。"""
    agent_manager.ensure_default_config()
    path = _config_path()
    if not path.is_file():
        return {"units": []}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {"units": []}
    units = data.get("units")
    if not isinstance(units, list):
        return {"units": []}
    return {"units": units, "_path": str(path)}


def _unit_enabled(item: dict[str, Any]) -> bool:
    return item.get("enabled", True) is not False


def load_work_unit_map() -> dict[str, WorkUnit]:
    """从 YAML 构建 name -> WorkUnit；仅包含 enabled 为真（或缺省）的单元。"""
    data = load_work_units_config_raw()
    out: dict[str, WorkUnit] = {}
    for item in data.get("units", []):
        if not isinstance(item, dict):
            continue
        if not _unit_enabled(item):
            continue
        name = str(item.get("name") or "").strip()
        domain = str(item.get("domain") or "").strip()
        prompt = str(item.get("prompt_file") or "").strip() or f"work_unit_{domain}.txt"
        if not name or not domain:
            continue
        out[name] = WorkUnit(domain, prompt)
    return out


def list_work_unit_graph_rows() -> list[dict[str, str]]:
    """用于 UGC 流程图与 resolve_node；仅已启用的单元。"""
    data = load_work_units_config_raw()
    rows: list[dict[str, str]] = []
    for item in data.get("units", []):
        if not isinstance(item, dict):
            continue
        if not _unit_enabled(item):
            continue
        name = str(item.get("name") or "").strip()
        domain = str(item.get("domain") or "").strip()
        if not name or not domain:
            continue
        rows.append(
            {
                "name": name,
                "domain": domain,
                "node_id": f"audit_{domain}",
            }
        )
    return rows
