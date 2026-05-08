# -*- coding: utf-8 -*-
"""
新做的 Streamlit 审核前端入口。
仅保留你最近新做的审核中心页面，不再包含老的管理页。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app.workflows.audit_orchestration import run_audit

st.set_page_config(
    page_title="Multi-Agent 审核中心",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CSS = """
<style>
.block-container { padding-top: 1.2rem; padding-bottom: 2rem; }
.hero {
  border-radius: 24px;
  padding: 24px 24px 18px;
  background: linear-gradient(135deg, rgba(15,23,42,1) 0%, rgba(30,41,59,1) 55%, rgba(15,118,110,1) 100%);
  color: white;
  box-shadow: 0 20px 50px rgba(15,23,42,.18);
}
.hero h1 { font-size: 2rem; margin: 0 0 .25rem 0; }
.hero p { margin: .35rem 0 0 0; opacity: .9; }
.card {
  border-radius: 20px;
  padding: 18px 18px 12px;
  background: white;
  border: 1px solid rgba(148,163,184,.22);
  box-shadow: 0 10px 30px rgba(15,23,42,.06);
}
.small-muted { color: #64748b; font-size: .92rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

if "audit_history" not in st.session_state:
    st.session_state.audit_history: list[dict[str, Any]] = []


def render_step_badge(stage: str, detail: str) -> str:
    return f"<div class='card'><b>{stage}</b><div class='small-muted'>{detail}</div></div>"


def run_audit_ui(text: str) -> dict[str, Any]:
    result = run_audit(text)
    trace_lines = []
    for step in result.get("log", []):
        stage = str(step.get("stage") or "")
        detail = str(step.get("result") or step.get("assessment") or step.get("signals") or step)
        trace_lines.append(render_step_badge(stage, detail[:220]))
    return {"trace_html": "".join(trace_lines), "data": result}


def page_audit() -> None:
    st.markdown(
        """
        <div class="hero">
          <h1>Multi-Agent 审核中心</h1>
          <p>意图分析 → 工作单元 → 验证器 → 置信度评估 → 仲裁/终审</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([1.35, 0.9])
    with col_left:
        text = st.text_area("待审核内容", height=220, placeholder="在此输入待审文本…")
    with col_right:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.subheader("说明")
        st.write("• 只保留新审核中心")
        st.write("• 不再显示旧管理页")
        st.write("• 适合部署展示")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.subheader("流程")
        st.write("1. 提交文本")
        st.write("2. 串行跑审核链")
        st.write("3. 展示轨迹与结构化结果")
        st.markdown("</div>", unsafe_allow_html=True)

    run_col, clear_col = st.columns([1, 4])
    with run_col:
        run_clicked = st.button("开始审核", type="primary", use_container_width=True)
    with clear_col:
        if st.button("清空结果", use_container_width=True):
            st.session_state.audit_history = []
            st.rerun()

    if run_clicked:
        if not text.strip():
            st.warning("请输入内容后再审核。")
        else:
            with st.spinner("审核进行中…"):
                result = run_audit_ui(text.strip())
                st.session_state.audit_history.append({"text": text.strip(), **result})

    if st.session_state.audit_history:
        latest = st.session_state.audit_history[-1]
        data = latest.get("data") or {}
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            st.metric("最终裁决", str(data.get("final_verdict", "-")))
        with col_b:
            st.metric("置信度", f"{float(data.get('final_confidence', 0.0) or 0.0):.2f}")
        with col_c:
            st.metric("阶段数", len(data.get("log") or []))
        with col_d:
            st.metric("是否仲裁", "是" if data.get("judge_result") else "否")

        tab1, tab2, tab3 = st.tabs(["流程轨迹", "结构化结果", "历史记录"])
        with tab1:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.markdown(latest.get("trace_html") or "_无轨迹_", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with tab2:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.json(data)
            st.markdown("</div>", unsafe_allow_html=True)
        with tab3:
            for idx, item in enumerate(reversed(st.session_state.audit_history[-5:]), 1):
                st.write(f"{idx}. {item.get('text','')[:60]}")
                if isinstance(item.get("data"), dict):
                    st.caption(f"裁决: {item['data'].get('final_verdict', '-')}")


page_audit()
