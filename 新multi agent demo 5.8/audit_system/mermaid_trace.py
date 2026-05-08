from __future__ import annotations

import re
from typing import Any


def _esc(s: str) -> str:
    """Mermaid 节点文字中的引号/换行处理。"""
    t = re.sub(r"[\n\r]+", " ", str(s) if s is not None else "")
    t = t.replace('"', "#quot;")
    if len(t) > 60:
        t = t[:57] + "..."
    return t


def execution_trace_to_mermaid(execution_trace: list[dict[str, Any]] | None) -> str:
    """
    将执行轨迹转为一串自上而下节点（顺序边）。
    若需展示并行，请使用 work_units 列表调用 flowchart_parallel_from_config。
    """
    rows = execution_trace or []
    if not rows:
        return "graph TD\n  empty[暂无轨迹数据]\n"
    lines = ["flowchart TD"]
    prev: str | None = None
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        step = _esc(row.get("阶段") or row.get("step") or f"步{i+1}")
        detail = _esc(row.get("详情") or row.get("detail") or "")
        label = f"{step}" if not detail else f"{step} — {detail}"
        nid = f"E{i}"
        lines.append(f'  {nid}["{label}"]')
        if prev is not None:
            lines.append(f"  {prev} --> {nid}")
        prev = nid
    return "\n".join(lines) + "\n"


def flowchart_pipeline_parallel(units: list[dict[str, str]]) -> str:
    """
    静态管线示意：开始 → 意图分析 → 激活（扇出到各工作单元）→ 验证器 → 仲裁者 → 结束
    units: [{"name": "政治审核员", "domain": "politics"}, ...]
    """
    if not units:
        return "flowchart TD\n  empty[未配置工作单元]\n"
    lines = [
        "flowchart TD",
        '  start_n["开始"]',
        '  intent_n["意图分析"]',
        '  act_n["激活工作单元"]',
        '  ver_n["验证器"]',
        '  arb_n["仲裁者"]',
        '  end_n["结束"]',
        "  start_n --> intent_n",
        "  intent_n --> act_n",
    ]
    for i, u in enumerate(units):
        wname = u.get("name") or u.get("domain") or f"WU{i}"
        wid = f"WU{i}"
        lines.append(f'  {wid}["{_esc(str(wname))}"]')
        lines.append(f"  act_n --> {wid}")
        lines.append(f"  {wid} --> ver_n")
    lines.extend(
        [
            "  ver_n --> arb_n",
            "  arb_n --> end_n",
        ]
    )
    return "\n".join(lines) + "\n"
