from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generator

from .agents.intent_analyst import analyze_intent
from .agents.verifier import evaluate_response, generate_challenges
from .agents.work_unit import WorkUnit
from .arbiter import arbitrate
from .config import STRATEGY
from .llm_utils import get_llm_trace, reset_llm_trace
from .mermaid_trace import execution_trace_to_mermaid, flowchart_pipeline_parallel
from .models import Evidence, WorkUnitResponse
from .work_units_loader import list_work_unit_graph_rows, load_work_unit_map


def get_work_unit_map() -> dict[str, WorkUnit]:
    """从 work_units_config.yaml 加载，每次调用重新读取，便于不重启改配置。"""
    return load_work_unit_map()


def simulate_work_unit_response(challenge, finding) -> WorkUnitResponse:
    if challenge.建议动作 == "补充证据":
        return WorkUnitResponse(
            回应动作="补充信息",
            补充证据=[Evidence(内容片段="原文语句已引用", 依据条款="条款补充说明")],
            新结论=finding.结论,
            反驳理由="已补充原文证据和条款映射。",
            是否需要补全=False,
        )
    if challenge.建议动作 in {"修改结论", "推翻结论"}:
        return WorkUnitResponse(
            回应动作="修改结论",
            新结论="存疑",
            反驳理由="证据存在歧义，调整为存疑并建议人工复核。",
            是否需要补全=False,
        )
    return WorkUnitResponse(
        回应动作="反驳质疑",
        新结论=finding.结论,
        反驳理由="现有证据链条完整，结论保持不变。",
        是否需要补全=False,
    )


# 向后兼容：旧代码若引用 WORK_UNIT_MAP，仍可用（映射到一次加载结果）
def __getattr__(name: str) -> Any:  # noqa: ANN401
    if name == "WORK_UNIT_MAP":
        return get_work_unit_map()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_trace(execution_trace: list[dict[str, str]], 阶段: str, 详情: str) -> None:
    execution_trace.append({"时间": _now_iso(), "阶段": 阶段, "详情": 详情})


def _progress(stage: str, detail: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "阶段名": stage,
        "内容": detail,
        "时间戳": _now_iso(),
        "数据": data or {},
    }


def _pipeline_mermaid() -> str:
    rows = list_work_unit_graph_rows()
    return flowchart_pipeline_parallel(
        [{"name": r["name"], "domain": r["domain"]} for r in rows],
    )


def run_audit_stream(content: str) -> Generator[dict[str, Any], None, None]:
    reset_llm_trace()
    work_unit_map = get_work_unit_map()
    if not work_unit_map:
        yield _progress(
            "完成",
            "未加载任何工作单元。请在项目根目录配置 work_units_config.yaml。",
            {
                "intent": {},
                "findings": {},
                "final_decisions": [],
                "reasoning_trace": [],
                "llm_calls": get_llm_trace(),
                "execution_trace": [],
                "mermaid_sequential": "flowchart TD\n  err[无工作单元配置]\n",
                "mermaid_pipeline": "flowchart TD\n  err2[无工作单元配置]\n",
            },
        )
        return

    available_names = list(work_unit_map.keys())
    reasoning_trace: list[dict[str, Any]] = []
    execution_trace: list[dict[str, str]] = []
    findings: dict[str, Any] = {}
    final_decisions: list[Any] = []
    mermaid_pipeline = _pipeline_mermaid()

    _append_trace(execution_trace, "启动", f"待审内容 {len(content)} 字符")
    yield _progress("启动", "审核任务已开始。", {"内容长度": len(content)})

    # 1. 意图分析
    intent = analyze_intent(content, available_unit_names=available_names)
    intent_stage = {
        "阶段": "意图分析",
        "说明": intent.简述,
        "关键词": intent.关键词,
        "建议激活单元": intent.建议激活单元,
    }
    reasoning_trace.append(intent_stage)
    sug = "、".join(intent.建议激活单元) if intent.建议激活单元 else "无"
    _append_trace(execution_trace, "意图分析", f"建议激活: {sug}")
    yield _progress("意图分析", "意图分析完成。", intent.model_dump())

    # 2. 激活对应工作单元
    activated_units = []
    for unit_name in intent.建议激活单元:
        if unit_name in work_unit_map:
            activated_units.append(work_unit_map[unit_name])

    act_detail = f"{[u.domain for u in activated_units]}" if activated_units else "无"
    _append_trace(execution_trace, "工作单元激活", f"已激活: {act_detail}")
    yield _progress(
        "工作单元激活",
        "已完成工作单元激活。",
        {"激活单元": [unit.domain for unit in activated_units], "建议单元": intent.建议激活单元},
    )

    if not activated_units:
        _append_trace(execution_trace, "完成", "无需激活审核员，判定为安全")
        mermaid_seq = execution_trace_to_mermaid(execution_trace)
        final_payload = {
            "intent": intent.model_dump(),
            "findings": {},
            "final_decisions": [],
            "reasoning_trace": reasoning_trace,
            "llm_calls": get_llm_trace(),
            "execution_trace": list(execution_trace),
            "mermaid_sequential": mermaid_seq,
            "mermaid_pipeline": mermaid_pipeline,
        }
        yield _progress("完成", "无需激活审核员，判定为安全。", final_payload)
        return

    # 3. 运行工作单元（串行）
    for unit in activated_units:
        _append_trace(execution_trace, f"工作单元-{unit.domain}", "开始执行")
        yield _progress(f"工作单元-{unit.domain}", "工作单元执行中...", {"domain": unit.domain})
        finding = unit.run(content, str(intent))
        findings[unit.domain] = finding
        work_stage = {
            "阶段": f"工作单元-{unit.domain}",
            "结论": finding.结论,
            "严重程度": finding.严重程度,
            "置信度": finding.置信度,
            "推理过程": finding.推理过程,
        }
        reasoning_trace.append(work_stage)
        _append_trace(execution_trace, f"工作单元-{unit.domain}", f"完成，结论: {finding.结论}")
        yield _progress(f"工作单元-{unit.domain}", "工作单元执行完成。", finding.model_dump())

    # 4. 验证器辩论
    for domain, finding in findings.items():
        _append_trace(execution_trace, f"验证器-{domain}", "开始审查")
        yield _progress(f"验证器-{domain}", "验证器审查中...", {"domain": domain})
        challenges = generate_challenges(content, finding, findings)
        if not challenges:
            verifier_stage = {
                "阶段": f"验证器-{domain}",
                "说明": "无质疑，通过",
            }
            reasoning_trace.append(verifier_stage)
            _append_trace(execution_trace, f"验证器-{domain}", "无异议，通过")
            yield _progress(f"验证器-{domain}", "验证器无异议。", {"质疑": []})
            continue

        for ch in challenges:
            verifier_stage = {
                "阶段": f"验证器-{domain}",
                "质疑类型": ch.质疑类型,
                "质疑理由": ch.质疑理由,
                "建议动作": ch.建议动作,
            }
            reasoning_trace.append(verifier_stage)
            _append_trace(execution_trace, f"验证器-{domain}", f"质疑: {ch.质疑类型}")
            yield _progress(f"验证器-{domain}", "验证器提出质疑。", ch.model_dump())
            response = simulate_work_unit_response(ch, finding)
            if evaluate_response(ch, response):
                response_stage = {
                    "阶段": f"回应-{domain}",
                    "动作": response.回应动作,
                    "结果": "验证器接受",
                    "理由": response.反驳理由,
                }
                reasoning_trace.append(response_stage)
                _append_trace(execution_trace, f"工作单元回应-{domain}", f"{response.回应动作}，验证通过")
                yield _progress(f"回应-{domain}", "工作单元回应通过。", response.model_dump())
            else:
                decision = arbitrate(finding, [ch], [response], findings, STRATEGY)
                final_decisions.append(decision)
                arbiter_stage = {
                    "阶段": f"仲裁-{domain}",
                    "最终判定": decision.最终判定,
                    "执行动作": decision.执行动作,
                    "简要理由": decision.简要理由,
                }
                reasoning_trace.append(arbiter_stage)
                _append_trace(execution_trace, f"仲裁-{domain}", f"判定: {decision.最终判定} / {decision.执行动作}")
                yield _progress(f"仲裁-{domain}", "仲裁完成。", decision.model_dump())

    _append_trace(execution_trace, "完成", "审核流程已完成")
    mermaid_seq = execution_trace_to_mermaid(execution_trace)
    final_payload = {
        "intent": intent.model_dump(),
        "findings": {k: v.model_dump() for k, v in findings.items()},
        "final_decisions": [d.model_dump() for d in final_decisions],
        "reasoning_trace": reasoning_trace,
        "llm_calls": get_llm_trace(),
        "execution_trace": list(execution_trace),
        "mermaid_sequential": mermaid_seq,
        "mermaid_pipeline": mermaid_pipeline,
    }
    yield _progress("完成", "审核流程已完成。", final_payload)


def run_audit(content: str) -> dict[str, Any]:
    final_payload: dict[str, Any] | None = None
    for item in run_audit_stream(content):
        if item.get("阶段名") == "完成":
            data = item.get("数据")
            if isinstance(data, dict):
                final_payload = data
    if final_payload is not None:
        return final_payload
    return {
        "intent": {},
        "findings": {},
        "final_decisions": [],
        "reasoning_trace": [],
        "llm_calls": [],
        "execution_trace": [],
        "mermaid_sequential": "",
        "mermaid_pipeline": "",
    }
