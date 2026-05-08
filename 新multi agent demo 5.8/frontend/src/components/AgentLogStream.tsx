import { useMemo, useState } from "react";

import type { BlackboardEntry } from "../types/audit";

interface Props {
  logs: BlackboardEntry[];
}

const AGENT_NAMES: Record<string, string> = {
  system: "系统",
  text_cleaner: "文本清洗员",
  rule_executor: "规则执行员",
  adversarial_detective: "对抗侦探",
  case_executor: "判例执行员",
  confidence_evaluator: "置信度评估员",
  chief_judge: "大法官",
  aggregator: "结果聚合器",
};

/** 简洁视图一律保留的阶段（编排过程、检索类中间态已过滤） */
const COMPACT_PHASE_ALLOW = new Set([
  "清洗输出",
  "输出结果",
  "评估完成",
  "最终仲裁",
  "执行异常",
]);

function isCompactRelevant(entry: BlackboardEntry): boolean {
  if (entry.phase === "phase_change") return false;
  if (COMPACT_PHASE_ALLOW.has(entry.phase)) return true;
  if (entry.phase.includes("异常")) return true;
  if (entry.agent === "system") return true;
  const v = entry.data?.verdict;
  if (v !== undefined && v !== null && String(v).trim() !== "") return true;
  const c = entry.content ?? "";
  if (/不参与|不采纳|不介入|未触发|跳过|开始审核|adversarial_detective_started/.test(c)) return true;
  return false;
}

function truncate(text: string, max: number): string {
  const t = text.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

const VERDICT_STYLES: Record<string, { label: string; color: string }> = {
  violation: { label: "违规", color: "text-red-600" },
  normal: { label: "正常", color: "text-emerald-600" },
  uncertain: { label: "不确定", color: "text-amber-600" },
  not_participating: { label: "不参与", color: "text-slate-500" },
  not_participate: { label: "不参与", color: "text-slate-500" },
  running: { label: "进行中", color: "text-blue-600" },
  phase_change: { label: "阶段", color: "text-slate-600" },
  log: { label: "日志", color: "text-slate-600" },
  error: { label: "异常", color: "text-red-700" },
};

const colorMap: Record<string, string> = {
  violation: "text-red-600",
  normal: "text-emerald-600",
  uncertain: "text-amber-600",
  not_participate: "text-slate-500",
};

function resolveDisplayVerdict(entry: BlackboardEntry, isExecError: boolean): string {
  if (isExecError) return "error";
  const v = entry.data?.verdict;
  if (v !== undefined && v !== null && String(v).trim() !== "") {
    return String(v);
  }
  if (entry.phase === "phase_change") return "phase_change";
  if (entry.data && typeof entry.data === "object" && (entry.data as { status?: string }).status === "running") {
    return "running";
  }
  return "log";
}

export function AgentLogStream({ logs }: Props) {
  const [compact, setCompact] = useState(true);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const displayLogs = useMemo(() => (compact ? logs.filter(isCompactRelevant) : logs), [logs, compact]);

  const grouped = useMemo(() => {
    const agentOrder = ["system", "text_cleaner", "rule_enforcer", "knowledge_retriever", "adversarial_detective", "case_executor", "confidence_evaluator", "chief_judge", "aggregator"];
    const phaseOrder: Record<string, number> = {
      started: 0,
      variant_pre_check: 1,
      清洗输出: 2,
      rule_enforcer: 3,
      knowledge_retriever: 4,
      adversarial_detective: 5,
      case_executor: 6,
      confidence_assessor: 7,
      confidence_evaluator: 7,
      chief_judge: 8,
      aggregator: 9,
      phase_change: 10,
      completed: 99,
    };

    const map = new Map<string, BlackboardEntry[]>();
    for (const log of displayLogs) {
      const list = map.get(log.agent) ?? [];
      list.push(log);
      map.set(log.agent, list);
    }

    const sortedKeys = [...map.keys()].sort((a, b) => {
      const ai = agentOrder.includes(a) ? agentOrder.indexOf(a) : agentOrder.length + 1;
      const bi = agentOrder.includes(b) ? agentOrder.indexOf(b) : agentOrder.length + 1;
      if (ai !== bi) return ai - bi;
      return a.localeCompare(b, "zh-Hans-CN");
    });

    return sortedKeys.map((agent) => [
      agent,
      [...(map.get(agent) ?? [])].sort((x, y) => {
        const xp = phaseOrder[String(x.phase ?? "")] ?? 50;
        const yp = phaseOrder[String(y.phase ?? "")] ?? 50;
        if (xp !== yp) return xp - yp;
        return String(x.timestamp ?? "").localeCompare(String(y.timestamp ?? ""));
      }),
    ] as [string, BlackboardEntry[]]);
  }, [displayLogs]);

  const maxContent = compact ? 160 : 2000;

  return (
    <div className="h-[500px] overflow-auto rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Agent日志流</h3>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" className="rounded border-slate-300" checked={compact} onChange={(e) => setCompact(e.target.checked)} />
          简洁视图（仅关键步骤）
        </label>
      </div>
      {compact && (
        <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
          已隐藏编排阶段与各 Agent 的中间过程（如阶段切换、规则检索、收集票据等）。需要排查细节时请取消勾选。
        </p>
      )}

      <div className="space-y-3">
        {grouped.length === 0 && compact && logs.length > 0 && (
          <p className="text-sm text-slate-500">
            简洁视图下没有可展示的条目，
            <button type="button" className="ml-1 text-blue-600 underline" onClick={() => setCompact(false)}>
              显示全部日志
            </button>
          </p>
        )}
        {grouped.length === 0 && !(logs.length > 0) && <p className="text-sm text-slate-500">等待日志...</p>}
        {grouped.map(([agent, entries]) => (
          <div id={`agent-log-${agent}`} key={agent} className={`rounded-xl border p-3 ${compact ? "border-slate-100 bg-slate-50" : "border-slate-200 bg-white"}`}>
            {agent === "system" ? (
              <div className="mb-2 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700">
                系统阶段日志会展示变体预检、流程切换和审核开始/完成信息。
              </div>
            ) : null}
            <div className="mb-2 text-sm font-semibold text-slate-800">{AGENT_NAMES[agent] ?? agent}</div>
            <div className="space-y-2">
              {entries.map((entry, idx) => {
                const isExecError =
                  entry.phase === "执行异常" || typeof (entry.data as { error?: unknown } | undefined)?.error === "string";
                const verdict = resolveDisplayVerdict(entry, isExecError);
                const style = VERDICT_STYLES[verdict];
                const cls = style?.color ?? colorMap[verdict] ?? "text-slate-600";
                const rowKey = `${agent}-${idx}-${entry.timestamp}-${entry.phase}`;
                const oneLine = compact;
                const showText = truncate(`${entry.phase} · ${entry.content}`, maxContent);
                const chipVerdicts = new Set(["violation", "normal", "uncertain", "not_participating", "not_participate", "error"]);
                const verdictChip = chipVerdicts.has(verdict) ? style?.label ?? verdict : null;
                const canExpandDetail = Boolean(entry.raw_llm_output || (isExecError && entry.data));

                return (
                  <div key={rowKey} className={`rounded-lg text-sm ${compact ? "bg-white py-2 pl-3 pr-2" : "bg-slate-50 p-2"}`}>
                    <div className="flex items-start justify-between gap-2">
                      <span className={`min-w-0 flex-1 break-words ${cls} ${oneLine ? "text-[13px] leading-snug" : ""}`}>
                        {!oneLine && (
                          <>
                            [{style?.label ?? "日志"}] {entry.phase} · {entry.content}
                          </>
                        )}
                        {oneLine && (
                          <>
                            {verdictChip && (
                              <span className="mr-1.5 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600">
                                {verdictChip}
                              </span>
                            )}
                            {showText}
                          </>
                        )}
                      </span>
                      {(canExpandDetail || !oneLine) && (
                        <button
                          type="button"
                          className="shrink-0 text-xs text-blue-600 hover:underline"
                          onClick={() => setExpanded((s) => ({ ...s, [rowKey]: !s[rowKey] }))}
                        >
                          {expanded[rowKey] ? "收起" : "展开"}
                        </button>
                      )}
                    </div>
                    {expanded[rowKey] && isExecError && entry.data && (
                      <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded border border-red-200 bg-red-50 p-2 text-xs text-red-900">
                        {JSON.stringify(entry.data, null, 2)}
                      </pre>
                    )}
                    {expanded[rowKey] && entry.raw_llm_output && (
                      <pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-700">
                        {entry.raw_llm_output}
                      </pre>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
