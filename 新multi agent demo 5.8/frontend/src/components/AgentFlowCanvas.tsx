import type { BlackboardEntry } from "../types/audit";

type AgentStatus = "waiting" | "running" | "completed" | "skipped" | "error";

interface FlowNodeState {
  agent: string;
  status: AgentStatus;
  currentPhase?: string;
}

interface FlowState {
  nodes: FlowNodeState[];
}

interface Props {
  flowState: FlowState;
  onNodeClick?: (agentId: string) => void;
}

const AGENT_NODES = [
  { id: "rule_executor", name: "规则执行员", x: 200, y: 50 },
  { id: "adversarial_detective", name: "对抗侦探", x: 100, y: 180 },
  { id: "case_executor", name: "判例执行员", x: 300, y: 180 },
  { id: "chief_judge", name: "大法官", x: 200, y: 310 },
  { id: "aggregator", name: "聚合器", x: 200, y: 420 },
] as const;

const CONNECTIONS = [
  { from: "rule_executor", to: "adversarial_detective" },
  { from: "rule_executor", to: "case_executor" },
  { from: "adversarial_detective", to: "chief_judge" },
  { from: "case_executor", to: "chief_judge" },
  { from: "chief_judge", to: "aggregator" },
] as const;

const STATUS_STYLE: Record<AgentStatus, { fill: string; text: string; icon: string }> = {
  waiting: { fill: "#e5e7eb", text: "等待中", icon: "⚪" },
  running: { fill: "#60a5fa", text: "执行中", icon: "🔵" },
  completed: { fill: "#4ade80", text: "已完成", icon: "🟢" },
  skipped: { fill: "#9ca3af", text: "未参与", icon: "⚫" },
  error: { fill: "#f87171", text: "出错", icon: "🔴" },
};

function nodeStatus(flowState: FlowState, id: string): AgentStatus {
  return flowState.nodes.find((n) => n.agent === id)?.status ?? "waiting";
}

function lineActive(flowState: FlowState, from: string, to: string): boolean {
  const fromStatus = nodeStatus(flowState, from);
  const toStatus = nodeStatus(flowState, to);
  return fromStatus !== "waiting" && toStatus !== "waiting";
}

export function buildFlowState(entries: BlackboardEntry[], hasResult: boolean): FlowState {
  const init: FlowState = {
    nodes: AGENT_NODES.map((n) => ({
      agent: n.id,
      status: "waiting",
      currentPhase: "",
    })),
  };
  const index = new Map(init.nodes.map((n) => [n.agent, n]));

  for (const entry of entries) {
    const node = index.get(entry.agent);
    if (!node) continue;
    node.currentPhase = entry.phase;
    if (entry.phase === "执行异常") {
      node.status = "error";
      continue;
    }
    const verdict = String(entry.data?.verdict ?? "");
    if (verdict === "not_participate" || verdict === "not_participating") {
      node.status = "skipped";
      continue;
    }
    if (entry.phase.includes("输出结果") || entry.phase.includes("最终仲裁") || entry.phase.includes("不介入")) {
      node.status = "completed";
      continue;
    }
    if (node.status === "waiting") node.status = "running";
  }

  const aggregator = index.get("aggregator");
  if (aggregator) {
    if (hasResult) {
      aggregator.status = "completed";
      aggregator.currentPhase = "聚合完成";
    } else if (entries.length > 0) {
      aggregator.status = "running";
      aggregator.currentPhase = "等待聚合";
    }
  }

  return init;
}

export function AgentFlowCanvas({ flowState, onNodeClick }: Props) {
  return (
    <div className="rounded-lg bg-white p-4 shadow ring-1 ring-slate-200">
      <h3 className="mb-4 text-lg font-bold">Agent 执行流程</h3>
      <svg viewBox="0 0 400 500" className="h-[420px] w-full">
        {CONNECTIONS.map((conn, idx) => {
          const from = AGENT_NODES.find((n) => n.id === conn.from)!;
          const to = AGENT_NODES.find((n) => n.id === conn.to)!;
          const active = lineActive(flowState, conn.from, conn.to);
          return (
            <line
              key={idx}
              x1={from.x}
              y1={from.y + 30}
              x2={to.x}
              y2={to.y - 30}
              stroke={active ? "#3b82f6" : "#94a3b8"}
              strokeWidth={active ? 3 : 2}
              strokeDasharray={active ? "0" : "5,5"}
            />
          );
        })}

        {AGENT_NODES.map((node) => {
          const state = flowState.nodes.find((n) => n.agent === node.id);
          const style = STATUS_STYLE[state?.status ?? "waiting"];
          const running = state?.status === "running";
          return (
            <g key={node.id} onClick={() => onNodeClick?.(node.id)} className="cursor-pointer">
              <rect
                x={node.x - 80}
                y={node.y - 25}
                width={160}
                height={52}
                rx={10}
                fill={style.fill}
                stroke={running ? "#2563eb" : "#cbd5e1"}
                strokeWidth={running ? 3 : 1}
                className={running ? "animate-pulse" : ""}
              />
              <text x={node.x} y={node.y - 4} textAnchor="middle" fontSize="14" fontWeight="700" fill="#0f172a">
                {node.name}
              </text>
              <text x={node.x} y={node.y + 16} textAnchor="middle" fontSize="11" fill="#0f172a">
                {style.icon} {style.text}
                {state?.currentPhase ? ` - ${state.currentPhase}` : ""}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

