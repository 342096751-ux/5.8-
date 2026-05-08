import type { AuditResult, BlackboardEntry } from "../types/audit";

type StepState = "waiting" | "running" | "completed" | "skipped";

type FlowPhase =
  | "startup"
  | "cleaning"
  | "cleaned"
  | "first_wave"
  | "first_wave_complete"
  | "rule_reaudit"
  | "rule_reaudit_complete"
  | "assessing"
  | "assessment_complete"
  | "judging"
  | "judge_complete"
  | "aggregating"
  | "final";

interface StepItem {
  key: string;
  title: string;
  state: StepState;
  text: string;
}

interface Props {
  logs: BlackboardEntry[];
  result: AuditResult | null;
}

const AGENTS = {
  cleaner: "text_cleaner",
  rule: "rule_executor",
  adv: "adversarial_detective",
  case: "case_executor",
  confidence: "confidence_evaluator",
  judge: "chief_judge",
};

function hasAnyLog(logs: BlackboardEntry[], agent: string, keywords: string[]): boolean {
  return keywords.some((keyword) => hasLog(logs, agent, keyword));
}

function getCurrentPhase(logs: BlackboardEntry[]): FlowPhase | null {
  const phases = logs
    .filter((l) => l.agent === "system" && typeof l.phase === "string")
    .map((l) => l.phase as FlowPhase)
    .filter((phase) => [
      "startup",
      "cleaning",
      "cleaned",
      "first_wave",
      "first_wave_complete",
      "rule_reaudit",
      "rule_reaudit_complete",
      "assessing",
      "assessment_complete",
      "judging",
      "judge_complete",
      "aggregating",
      "final",
    ].includes(phase));
  return phases.length ? phases[phases.length - 1] : null;
}

function detectSecondRound(logs: BlackboardEntry[]): boolean {
  return (
    hasAnyLog(logs, AGENTS.rule, ["二轮", "R4", "二轮检索完成", "二轮知识库", "二轮案例库"]) ||
    hasAnyLog(logs, AGENTS.adv, ["二轮", "v_second_round_trigger", "需二轮审核", "需要二轮审核"]) ||
    hasAnyLog(logs, AGENTS.confidence, ["二轮", "保留复审", "触发仲裁", "建议仲裁"]) ||
    logs.some((l) =>
      String(l.data?.stage ?? "") === "second_round_required" ||
      String(l.data?.stage ?? "") === "second_round" ||
      String(l.data?.reason ?? "").includes("二轮"),
    )
  );
}

function hasLog(logs: BlackboardEntry[], agent: string, keyword: string): boolean {
  return logs.some((l) => l.agent === agent && (l.phase.includes(keyword) || l.content.includes(keyword)));
}

function agentStep(logs: BlackboardEntry[], agent: string, runningHint: string): { state: StepState; text: string } {
  const error = hasLog(logs, agent, "执行异常");
  if (error) return { state: "skipped", text: "已跳过" };
  const skipped = logs.some((l) => l.agent === agent && String(l.data?.verdict ?? "") === "not_participate");
  if (skipped || hasLog(logs, agent, "不参与")) return { state: "skipped", text: "已跳过" };
  // 文本清洗员完成阶段是「清洗输出」，不是通用的「输出结果」
  if (agent === "text_cleaner" && hasLog(logs, agent, "清洗输出")) {
    return { state: "completed", text: "已清洗" };
  }
  if (agent === "confidence_evaluator" && hasLog(logs, agent, "评估完成")) {
    return { state: "completed", text: "已完成" };
  }
  if (hasLog(logs, agent, "输出结果") || hasLog(logs, agent, "最终仲裁")) return { state: "completed", text: "已输出" };
  if (logs.some((l) => l.agent === agent)) return { state: "running", text: runningHint };
  return { state: "waiting", text: "等待" };
}

/** 单次审核接口返回后，以 agent_results 为准收尾（避免仅依赖日志关键词漏判「已完成/跳过」） */
function stepFromFinalResult(agent: string, ar: unknown, logs: BlackboardEntry[]): { state: StepState; text: string } | null {
  if (!ar || typeof ar !== "object") return null;
  const rec = ar as Record<string, unknown>;
  const verdict = String(rec.verdict ?? "").trim();
  const v = verdict.toLowerCase();

  if (hasLog(logs, agent, "执行异常")) return { state: "skipped", text: "已跳过" };

  if (agent === "text_cleaner") {
    if (v === "preprocessed") return { state: "completed", text: "已清洗" };
  }

  if (agent === "confidence_evaluator") {
    const hasPayload =
      Array.isArray(rec.calibrated_votes) ||
      rec.summary !== undefined ||
      typeof rec.suggest_arbitration === "boolean";
    if (hasPayload) return { state: "completed", text: "已完成" };
  }

  if (agent === "chief_judge") {
    if (v === "not_participate" || v === "not_participating") return { state: "skipped", text: "不参与" };
    if (v === "violation" || v === "normal" || v === "uncertain") return { state: "completed", text: "已裁决" };
  }

  if (v === "not_participate" || v === "not_participating") return { state: "skipped", text: "已跳过" };
  if (v === "preprocessed") return { state: "completed", text: "已输出" };

  if (v && v !== "") {
    if (["violation", "normal", "uncertain", "participating"].includes(v)) {
      return { state: "completed", text: "已输出" };
    }
  }

  return null;
}

export function buildStepItems(logs: BlackboardEntry[], result: AuditResult | null): StepItem[] {
  const submitState: StepState = logs.length > 0 || result ? "completed" : "waiting";
  const submitText = submitState === "completed" ? "已提交" : "等待";

  const started = logs.some((l) => l.agent === "system" && l.phase.includes("启动审核"));
  const cleanerStep = agentStep(logs, AGENTS.cleaner, "清洗中");
  const allPrimaryTouched =
    logs.some((l) => l.agent === AGENTS.rule) &&
    logs.some((l) => l.agent === AGENTS.adv) &&
    logs.some((l) => l.agent === AGENTS.case);
  const startState: StepState = allPrimaryTouched ? "completed" : started ? "running" : "waiting";
  const startText = allPrimaryTouched ? "已完成" : started ? "运行中" : "等待";

  const rule = agentStep(logs, AGENTS.rule, "检索/初判中");
  const adv = agentStep(logs, AGENTS.adv, "对抗检测中");
  const caseStep = agentStep(logs, AGENTS.case, "判例检索中");
  if (hasLog(logs, AGENTS.case, "知识")) caseStep.text = "查询知识库中";
  const confidence = agentStep(logs, AGENTS.confidence, "校准/冲突检测中");

  const judgeBase = agentStep(logs, AGENTS.judge, "就绪");
  let judge = judgeBase;
  if (judgeBase.state === "running") judge = { state: "running", text: "仲裁中" };
  if (hasLog(logs, AGENTS.judge, "启动仲裁")) judge = { state: "running", text: "仲裁中" };
  if (hasLog(logs, AGENTS.judge, "不介入") || hasLog(logs, AGENTS.judge, "未触发介入条件")) {
    judge = { state: "skipped", text: "不参与" };
  }
  if (hasLog(logs, AGENTS.judge, "最终仲裁")) {
    judge = { state: "completed", text: "已介入" };
  }

  const currentPhase = getCurrentPhase(logs);
  const secondRoundDetected = detectSecondRound(logs);
  const secondRoundStep = secondRoundDetected
    ? {
        key: "second_round",
        title: "大法官二次审核",
        state: currentPhase === "judge_complete" || currentPhase === "final" || result ? ("completed" as StepState) : ("running" as StepState),
        text: currentPhase === "judge_complete" || currentPhase === "final" || result ? "已完成" : "进行中",
      }
    : null;

  /** 单次审核已完成：用语义结果收口，修正「清洗仍转圈」「大法官一直等待」等 */
  if (result?.agent_results) {
    const ars = result.agent_results as Record<string, unknown>;
    const apply = (key: string, cur: { state: StepState; text: string }) => {
      const fin = stepFromFinalResult(key, ars[key], logs);
      return fin ?? cur;
    };
    const c0 = apply(AGENTS.cleaner, cleanerStep);
    const c1 = apply(AGENTS.rule, rule);
    const c2 = apply(AGENTS.adv, adv);
    const c3 = apply(AGENTS.case, caseStep);
    const c4 = apply(AGENTS.confidence, confidence);
    const c5 = apply(AGENTS.judge, judge);
    const items: StepItem[] = [
      { key: "submit", title: "提交", state: submitState, text: submitText },
      { key: "parallel", title: "并行启动", state: startState, text: startText },
      { key: AGENTS.cleaner, title: "文本清洗员", state: c0.state, text: c0.text },
      { key: AGENTS.rule, title: "规则执行员", state: c1.state, text: c1.text },
      { key: AGENTS.adv, title: "对抗侦探", state: c2.state, text: c2.text },
      { key: AGENTS.case, title: "判别执行员", state: c3.state, text: c3.text },
      { key: AGENTS.confidence, title: "置信度评估员", state: c4.state, text: c4.text },
    ];
    if (secondRoundStep) items.push(secondRoundStep);
    items.push(
      { key: AGENTS.judge, title: "大法官", state: c5.state, text: c5.text },
      {
        key: "aggregator",
        title: "聚合与结果",
        state: "completed",
        text:
          result.final_verdict === "violation"
            ? "完成：违规"
            : result.final_verdict === "normal"
              ? "完成：安全"
              : "完成：存疑",
      },
    );
    return items;
  }

  let finalState: StepState = "waiting";
  let finalText = "等待";
  if (logs.length > 0) {
    finalState = "running";
    finalText = "运行中";
  }
  if (result) {
    finalState = "completed";
    finalText = result.final_verdict === "violation" ? "完成：违规" : result.final_verdict === "normal" ? "完成：安全" : "完成：存疑";
  }

  const items: StepItem[] = [
    { key: "submit", title: "提交", state: submitState, text: submitText },
    { key: "parallel", title: "并行启动", state: startState, text: startText },
    { key: AGENTS.cleaner, title: "文本清洗员", state: cleanerStep.state, text: cleanerStep.text },
    { key: AGENTS.rule, title: "规则执行员", state: rule.state, text: rule.text },
    { key: AGENTS.adv, title: "对抗侦探", state: adv.state, text: adv.text },
    { key: AGENTS.case, title: "判别执行员", state: caseStep.state, text: caseStep.text },
    { key: AGENTS.confidence, title: "置信度评估员", state: confidence.state, text: confidence.text },
  ];
  if (secondRoundStep) items.push(secondRoundStep);
  items.push(
    { key: AGENTS.judge, title: "大法官", state: judge.state, text: judge.text },
    { key: "aggregator", title: "聚合与结果", state: finalState, text: finalText },
  );
  return items;
}

function NodeIcon({ state }: { state: StepState }) {
  if (state === "completed") return <span className="text-green-600">✓</span>;
  if (state === "running") return <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />;
  if (state === "skipped") return <span className="text-slate-500">⏭</span>;
  return <span className="text-slate-400">○</span>;
}

export function AgentStepProgress({ logs, result }: Props) {
  const steps = buildStepItems(logs, result);
  return (
    <div className="overflow-x-auto rounded-3xl border border-slate-200 bg-gradient-to-b from-white to-slate-50 px-4 py-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">审核流程进度</div>
          <div className="text-xs text-slate-500">提交、并行启动、专业 Agent、聚合结果一目了然</div>
        </div>
        <div className="rounded-full bg-slate-100 px-3 py-1 text-[11px] text-slate-500">实时同步黑板</div>
      </div>
      <div className="flex min-w-[980px] items-start pb-1">
        {steps.map((step, idx) => {
          const activeLine = step.state === "completed" || step.state === "running";
          const skipped = step.state === "skipped";
          const tone =
            step.state === "completed"
              ? "from-emerald-50 to-white border-emerald-200 text-emerald-700"
              : step.state === "running"
                ? "from-blue-50 to-white border-blue-200 text-blue-700"
                : skipped
                  ? "from-slate-100 to-white border-slate-300 text-slate-600"
                  : "from-slate-50 to-white border-slate-200 text-slate-500";
          return (
            <div key={step.key} className="flex flex-1 items-center">
              <div className="flex w-full flex-col items-center">
                <div className={`flex h-10 min-w-10 items-center justify-center rounded-full border bg-gradient-to-b text-xs shadow-sm ${tone}`}>
                  <NodeIcon state={step.state} />
                </div>
                <div className="mt-2 text-sm font-semibold text-slate-800">{step.title}</div>
                <div className="mt-1 rounded-full bg-white px-2.5 py-0.5 text-[11px] text-slate-500 ring-1 ring-slate-200">{step.text}</div>
              </div>
              {idx < steps.length - 1 && (
                <div className={`mx-2 h-0.5 flex-1 rounded-full ${activeLine ? "bg-blue-400" : "bg-slate-300"}`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

