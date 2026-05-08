import { useEffect, useRef, useState } from "react";
import { Activity, Bot, BrainCircuit, ShieldCheck, Sparkles, Workflow } from "lucide-react";

import { AgentLogStream } from "../components/AgentLogStream";
import { AgentStepProgress } from "../components/AgentStepProgress";
import { AuditPanel } from "../components/AuditPanel";
import { BatchAuditPanel } from "../components/BatchAuditPanel";
import { BlackboardView } from "../components/BlackboardView";
import { ConfigModal } from "../components/ConfigModal";
import { ResultPanel } from "../components/ResultPanel";
import { getAgents, startAudit, updateAgent } from "../services/api";
import { connectAuditStream } from "../services/websocket";
import type { AgentConfig, AuditResult, BlackboardEntry } from "../types/audit";

type AuditPageTab = "single" | "batch";

export function AuditPage() {
  const [pageTab, setPageTab] = useState<AuditPageTab>("single");
  const [logs, setLogs] = useState<BlackboardEntry[]>([]);
  const [result, setResult] = useState<AuditResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [agents, setAgents] = useState<Record<string, AgentConfig>>({});
  const [auditConfig, setAuditConfig] = useState<{ model_config_id: string; temperature: number }>({
    model_config_id: "",
    temperature: 0.2,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const displayLogs = logs.length ? logs : result?.logs ?? [];
  const createAuditId = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return `audit-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  };

  useEffect(() => {
    getAgents().then(setAgents).catch(() => setAgents({}));
    return () => wsRef.current?.close();
  }, []);

  const runAudit = async (content: string) => {
    setLoading(true);
    setLogs([]);
    const auditId = createAuditId();
    wsRef.current?.close();
    wsRef.current = connectAuditStream(
      auditId,
      (entry) => setLogs((prev) => [...prev, entry]),
      () => undefined,
    );
    try {
      const res = await startAudit(content, auditConfig, auditId);
      setResult(res);
    } catch (error) {
      const message = error instanceof Error ? error.message : "审核请求失败";
      setLogs((prev) => [
        ...prev,
        {
          timestamp: new Date().toISOString(),
          agent: "system",
          zone: "orchestrator",
          phase: "请求失败",
          content: message,
          data: {},
          raw_llm_output: null,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-50 via-slate-50 to-slate-100 text-slate-900">
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white/80 p-5 shadow-sm backdrop-blur">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="text-xs font-medium uppercase tracking-[0.2em] text-blue-600">Multi-Agent Audit</div>
              <h1 className="mt-1 text-2xl font-semibold text-slate-900">多 Agent 内容审核控制台</h1>
              <p className="mt-2 max-w-2xl text-sm text-slate-500">统一查看步骤进度、实时日志流、黑板状态与最终结果。</p>
            </div>
            <div className="hidden items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 md:flex">
              <Sparkles className="h-4 w-4 text-blue-500" />
              实时调度 / 黑板同步 / 导出结果
            </div>
          </div>
          <div className="mt-5 flex gap-2 rounded-2xl bg-slate-100 p-1">
            <button
              type="button"
              className={`flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-colors ${
                pageTab === "single" ? "bg-white text-blue-600 shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
              onClick={() => setPageTab("single")}
            >
              单次审核
            </button>
            <button
              type="button"
              className={`flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-colors ${
                pageTab === "batch" ? "bg-white text-blue-600 shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
              onClick={() => setPageTab("batch")}
            >
              批量审核
            </button>
          </div>
        </div>

        {pageTab === "batch" ? (
          <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm backdrop-blur">
            <BatchAuditPanel />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm backdrop-blur">
              <AgentStepProgress logs={displayLogs} result={result} />
            </div>

            <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
              <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm backdrop-blur">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <Activity className="h-4 w-4 text-blue-500" />
                    Agent 日志流
                  </div>
                  <div className="text-xs text-slate-500">按 Agent 分组，支持展开详情</div>
                </div>
                <AgentLogStream logs={displayLogs} />
              </div>
              <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm backdrop-blur">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <Workflow className="h-4 w-4 text-blue-500" />
                    黑板视图
                  </div>
                  <div className="text-xs text-slate-500">流程、置信度、终审一屏展示</div>
                </div>
                <BlackboardView logs={displayLogs} agentResults={(result?.agent_results as Record<string, unknown>) ?? null} />
              </div>
            </div>

            <div className="grid gap-4 xl:grid-cols-[1fr_0.95fr]">
              <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm backdrop-blur">
                <AuditPanel loading={loading} onStart={runAudit} onOpenConfig={() => setModalOpen(true)} />
              </div>
              <div className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm backdrop-blur">
                <ResultPanel result={result} />
              </div>
            </div>
          </div>
        )}

        <ConfigModal
          open={modalOpen}
          agents={agents}
          selectedModelConfigId={auditConfig.model_config_id}
          onClose={() => setModalOpen(false)}
          onSaveAuditConfig={(cfg) => setAuditConfig(cfg)}
          onSave={async (name, cfg) => {
            const updated = await updateAgent(name, cfg);
            setAgents((prev) => ({ ...prev, [name]: updated }));
          }}
        />
      </div>
    </div>
  );
}
