import { useMemo } from "react";

import type { BlackboardEntry } from "../types/audit";

interface Props {
  logs: BlackboardEntry[];
  /** 审核结束后的最终快照（优先于「仅看最后一条日志」，避免中间步骤无 verdict 时误显「审核中」） */
  agentResults?: Record<string, unknown> | null;
}

const targetAgents = [
  "rule_executor",
  "adversarial_detective",
  "case_executor",
  "confidence_evaluator",
  "chief_judge",
];
const AGENT_NAMES: Record<string, string> = {
  text_cleaner: "文本清洗员",
  rule_executor: "规则执行员",
  adversarial_detective: "对抗侦探",
  case_executor: "判例执行员",
  confidence_evaluator: "置信度评估员",
  chief_judge: "大法官",
};
const STATUS_TEXT: Record<string, string> = {
  running: "审核中...",
  completed: "审核完成",
  waiting: "等待中",
  intervened: "大法官介入",
  skipped: "未参与",
  violation: "违规",
  normal: "正常",
  uncertain: "不确定",
  not_participating: "不参与",
  not_participate: "不参与",
};

function verdictFromAgentResults(agent: string, agentResults: Record<string, unknown> | null | undefined): string | null {
  const raw = agentResults?.[agent];
  if (!raw || typeof raw !== "object") return null;
  const v = (raw as { verdict?: unknown }).verdict;
  if (v === undefined || v === null || String(v).trim() === "") return null;
  return String(v);
}

/** 从日志中找「带 verdict 的最后一条」，避免中间 phase 覆盖最终结果 */
function verdictFromLogs(agent: string, logs: BlackboardEntry[]): string | null {
  const list = logs.filter((l) => l.agent === agent);
  for (let i = list.length - 1; i >= 0; i--) {
    const d = list[i].data;
    if (d && typeof d === "object" && "verdict" in d) {
      const v = (d as { verdict?: unknown }).verdict;
      if (v !== undefined && v !== null && String(v).trim() !== "") return String(v);
    }
  }
  return null;
}

export function BlackboardView({ logs, agentResults }: Props) {
  const summary = useMemo(() => {
    const latest: Record<string, BlackboardEntry | undefined> = {};
    for (const agent of targetAgents) latest[agent] = undefined;
    for (const log of logs) {
      if (targetAgents.includes(log.agent)) latest[log.agent] = log;
    }
    return latest;
  }, [logs]);

  const stageTimeline = useMemo(() => {
    const phaseOrder: Record<string, number> = {
      started: 0,
      variant_pre_check: 1,
      rule_enforcer: 2,
      knowledge_retriever: 3,
      adversarial_detective: 4,
      case_executor: 5,
      confidence_assessor: 6,
      chief_judge: 7,
      aggregator: 8,
      phase_change: 9,
      completed: 99,
    };

    return logs
      .filter((l) => ["started", "variant_pre_check", "rule_enforcer", "knowledge_retriever", "adversarial_detective", "case_executor", "confidence_assessor", "chief_judge", "aggregator", "phase_change", "completed"].includes(l.phase))
      .slice()
      .sort((a, b) => {
        const ap = phaseOrder[a.phase] ?? 50;
        const bp = phaseOrder[b.phase] ?? 50;
        if (ap !== bp) return ap - bp;
        return String(a.timestamp ?? "").localeCompare(String(b.timestamp ?? ""));
      })
      .map((l, idx) => ({
        key: `${l.agent}-${l.phase}-${idx}`,
        stage: l.phase,
        agent: l.agent,
        content: l.content,
        data: l.data,
      }));
  }, [logs]);

  const currentStage = stageTimeline[stageTimeline.length - 1]?.stage ?? null;

  const preprocessData = useMemo(() => {
    const latest = [...logs]
      .reverse()
      .find((l) => l.agent === "text_cleaner" && l.phase === "清洗输出");
    const d = (latest?.data ?? {}) as { raw_preview?: string; clean_preview?: string; raw_len?: number; clean_len?: number };
    const cleanedFull = String(latest?.raw_llm_output ?? "");
    return {
      rawPreview: String(d.raw_preview ?? ""),
      cleanPreview: String(d.clean_preview ?? ""),
      rawLen: Number(d.raw_len ?? 0),
      cleanLen: Number(d.clean_len ?? 0),
      cleanedFull,
      has: Boolean(latest),
    };
  }, [logs]);

  const confidenceData = useMemo(() => {
    const latest = [...logs]
      .slice()
      .sort((a, b) => String(a.timestamp ?? "").localeCompare(String(b.timestamp ?? "")))
      .reverse()
      .find((l) => l.agent === "confidence_evaluator" && l.data);
    const data = (latest?.data ?? {}) as {
      calibrated_votes?: Array<{
        agent?: string;
        raw?: number;
        calibrated?: number;
        ignored?: boolean;
        verdict?: string;
      }>;
      summary?: { conflict_detected?: boolean; max_calibrated?: number; low_confidence_count?: number };
      suggest_arbitration?: boolean;
      reason?: string;
      recommended_action?: string;
      arbitration_score?: number;
    };
    const votes = Array.isArray(data.calibrated_votes) ? data.calibrated_votes : [];
    return {
      votes,
      conflict: Boolean(data.summary?.conflict_detected),
      maxCalibrated: Number(data.summary?.max_calibrated ?? 0),
      lowCount: Number(data.summary?.low_confidence_count ?? 0),
      suggestArbitration: Boolean(data.suggest_arbitration),
      reason: String(data.reason ?? ""),
      recommendedAction: String(data.recommended_action ?? ""),
      arbitrationScore: Number(data.arbitration_score ?? 0),
    };
  }, [logs]);

  return (
    <div className="h-[500px] overflow-auto rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold text-slate-900">黑板状态</h3>
      <div className="space-y-2 text-sm">
        {targetAgents.map((agent) => {
          const fromResult = verdictFromAgentResults(agent, agentResults ?? null);
          const fromLogs = verdictFromLogs(agent, logs);
          const verdict = fromResult ?? fromLogs ?? String(summary[agent]?.data?.verdict ?? "waiting");
          return (
            <div key={agent} className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
              <span className="font-medium text-slate-700">{AGENT_NAMES[agent] ?? agent}</span>
              <span className="text-slate-600">{STATUS_TEXT[verdict] ?? verdict}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-4 rounded-xl border border-blue-100 bg-blue-50 p-3">
        <div className="mb-2 text-sm font-semibold text-blue-800">文本清洗员（preprocess_zone）</div>
        {!preprocessData.has ? (
          <div className="text-xs text-blue-700">暂无清洗结果</div>
        ) : (
          <div className="space-y-2">
            <div className="grid gap-2 md:grid-cols-2">
              <div className="rounded-lg border border-blue-100 bg-white p-2">
                <div className="mb-1 text-xs font-medium text-slate-700">
                  原文预览 <span className="text-[10px] text-slate-500">({preprocessData.rawLen} chars)</span>
                </div>
                <pre className="max-h-28 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-700">
                  {preprocessData.rawPreview || "（空）"}
                </pre>
              </div>
              <div className="rounded-lg border border-blue-100 bg-white p-2">
                <div className="mb-1 text-xs font-medium text-slate-700">
                  清洗后预览 <span className="text-[10px] text-slate-500">({preprocessData.cleanLen} chars)</span>
                </div>
                <pre className="max-h-28 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-700">
                  {preprocessData.cleanPreview || "（空）"}
                </pre>
              </div>
            </div>
            <details className="rounded-lg border border-blue-100 bg-white p-2">
              <summary className="cursor-pointer select-none text-xs text-blue-800">展开查看清洗后全文</summary>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-700">
                {preprocessData.cleanedFull || "（空）"}
              </pre>
            </details>
          </div>
        )}
      </div>
      <div className="mt-4 rounded-xl border border-violet-100 bg-violet-50 p-3">
        <div className="mb-2 text-sm font-semibold text-violet-800">置信度评估员</div>
        {confidenceData.votes.length === 0 ? (
          <div className="text-xs text-violet-700">暂无评估结果</div>
        ) : (
          <div className="space-y-2">
            {confidenceData.votes.map((v, idx) => {
              const raw = Number(v.raw ?? 0);
              const calibrated = Number(v.calibrated ?? 0);
              const name = AGENT_NAMES[v.agent ?? ""] ?? v.agent ?? `票${idx + 1}`;
              return (
                <div key={`${name}-${idx}`} className="rounded-lg border border-violet-100 bg-white p-2">
                  <div className="mb-1 flex items-center justify-between text-xs text-slate-700">
                    <span>{name}</span>
                    <span className={v.ignored ? "text-slate-400" : "text-violet-700"}>
                      {v.ignored ? "已忽略" : String(v.verdict ?? "-")}
                    </span>
                  </div>
                  <div className="space-y-1">
                    <div>
                      <div className="mb-0.5 text-[10px] text-slate-500">原始 {raw.toFixed(3)}</div>
                      <div className="h-1.5 rounded bg-slate-200">
                        <div className="h-1.5 rounded bg-slate-500" style={{ width: `${Math.min(raw * 100, 100)}%` }} />
                      </div>
                    </div>
                    <div>
                      <div className="mb-0.5 text-[10px] text-violet-700">校准后 {calibrated.toFixed(3)}</div>
                      <div className="h-1.5 rounded bg-violet-100">
                        <div
                          className="h-1.5 rounded bg-violet-600"
                          style={{ width: `${Math.min(calibrated * 100, 100)}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        <div className="mt-2 space-y-2 text-xs">
          <div className="flex items-center justify-between">
            <span className={confidenceData.conflict ? "font-medium text-red-700" : "text-slate-600"}>
              {confidenceData.conflict ? "⚠ 冲突标记：已触发" : "冲突标记：未触发"}
            </span>
            <span className={`rounded px-2 py-0.5 ${confidenceData.suggestArbitration ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"}`}>
              suggest_arbitration: {String(confidenceData.suggestArbitration)}
            </span>
          </div>
          <div className="flex flex-wrap gap-2 text-slate-600">
            <span className="rounded bg-white px-2 py-1 ring-1 ring-slate-200">仲裁分: {confidenceData.arbitrationScore.toFixed(2)}</span>
            <span className="rounded bg-white px-2 py-1 ring-1 ring-slate-200">最高校准: {confidenceData.maxCalibrated.toFixed(3)}</span>
            <span className="rounded bg-white px-2 py-1 ring-1 ring-slate-200">低置信票: {confidenceData.lowCount}</span>
          </div>
          {(confidenceData.reason || confidenceData.recommendedAction) && (
            <div className="rounded-lg bg-white p-2 text-slate-700 ring-1 ring-slate-200">
              <div>{confidenceData.reason || "-"}</div>
              <div className="mt-1 text-[11px] text-slate-500">{confidenceData.recommendedAction || ""}</div>
            </div>
          )}
        </div>
      </div>
      <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="text-sm font-semibold text-slate-900">阶段 DAG</div>
          <div className="text-xs text-slate-500">当前阶段: {currentStage ?? "无"}</div>
        </div>
        {stageTimeline.length === 0 ? (
          <div className="text-xs text-slate-500">暂无阶段记录</div>
        ) : (
          <div className="space-y-4">
            {stageTimeline.map((item, index) => {
              const isCurrent = index === stageTimeline.length - 1;
              const isBranchPoint = item.stage === "adversarial_detective" || item.stage === "confidence_assessor";
              const nextNode = index < stageTimeline.length - 1;
              return (
                <div key={item.key} className="relative pl-7">
                  <div className={`absolute left-0 top-3 z-10 h-4 w-4 rounded-full border-2 shadow-sm ${isCurrent ? "border-blue-600 bg-blue-500" : "border-slate-300 bg-white"}`} />
                  {nextNode && <div className="absolute left-[0.4375rem] top-7 h-full w-0.5 bg-slate-300" />}
                  <div
                    className={`rounded-2xl border px-3 py-3 text-sm transition ${isCurrent ? "border-blue-300 bg-blue-50 shadow-sm" : "border-slate-200 bg-white"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`font-medium ${isCurrent ? "text-blue-700" : "text-slate-800"}`}>{item.stage}</span>
                      <span className="text-[11px] text-slate-500">{item.agent}</span>
                    </div>
                    <div className="mt-1 line-clamp-3 text-[11px] leading-5 text-slate-600">{String(item.content ?? "")}</div>
                    {isBranchPoint && (
                      <div className="mt-2 inline-flex rounded-full bg-blue-100 px-2 py-0.5 text-[10px] text-blue-700">
                        分支决策点
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="mt-4 rounded-xl bg-slate-50 p-2 text-sm text-slate-600">
        大法官介入: {summary.chief_judge ? "是" : "否"}
      </div>
    </div>
  );
}
