import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle,
  Download,
  FileSpreadsheet,
  Loader,
  Play,
  Upload,
  X,
} from "lucide-react";

import "../styles/batch-audit.css";

interface BatchAuditTask {
  task_id: string;
  total: number;
  completed: number;
  failed: number;
  percent: number;
  remaining?: number;
  status: string;
  message: string;
  created_at?: string;
}

interface AuditResultRow {
  id: string;
  content: string;
  status: string;
  final_result?: string;
  rule_executor?: { verdict?: string; confidence?: number | string };
  adversarial_detective?: { verdict?: string };
  case_executor?: { verdict?: string; confidence?: number | string };
  chief_judge?: { verdict?: string; confidence?: number | string };
  error?: string;
}

function apiErrorDetail(data: unknown): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return JSON.stringify(d);
    return String(d);
  }
  return "请求失败";
}

const verdictVisual: Record<string, { text: string; color: string; bg: string }> = {
  violation: { text: "违规", color: "#9C0006", bg: "#FFC7CE" },
  违规: { text: "违规", color: "#9C0006", bg: "#FFC7CE" },
  normal: { text: "正常", color: "#006100", bg: "#C6EFCE" },
  正常: { text: "正常", color: "#006100", bg: "#C6EFCE" },
  uncertain: { text: "疑似", color: "#9C5700", bg: "#FFEB9C" },
  疑似: { text: "疑似", color: "#9C5700", bg: "#FFEB9C" },
  not_participating: { text: "不参与", color: "#666", bg: "#D9D9D9" },
  not_participate: { text: "不参与", color: "#666", bg: "#D9D9D9" },
  不参与: { text: "不参与", color: "#666", bg: "#D9D9D9" },
  not_intervene: { text: "未介入", color: "#666", bg: "#D9D9D9" },
  未介入: { text: "未介入", color: "#666", bg: "#D9D9D9" },
  "-": { text: "-", color: "#666", bg: "#f0f0f0" },
};

function verdictStyle(result: string | undefined) {
  const key = (result || "-").trim();
  return verdictVisual[key] || { text: key || "-", color: "#333", bg: "#fff" };
}

export function BatchAuditPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [concurrency, setConcurrency] = useState(3);
  const [uploading, setUploading] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<BatchAuditTask | null>(null);
  const [results, setResults] = useState<AuditResultRow[]>([]);
  const [viewMode, setViewMode] = useState<"upload" | "running" | "completed">("upload");
  const [error, setError] = useState<string | null>(null);

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      setFile(f);
      setError(null);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) {
      setFile(f);
      setError(null);
    }
  }, []);

  const pollStatus = async (tid: string) => {
    try {
      const res = await fetch(`/api/batch-audit/${tid}/status`);
      const data = (await res.json()) as BatchAuditTask & { detail?: string };

      if (!res.ok) throw new Error(apiErrorDetail(data));

      setStatus({
        ...data,
        percent: typeof data.percent === "number" ? data.percent : 0,
      });

      if (data.status === "completed") {
        await fetchResults(tid);
        setViewMode("completed");
      } else if (data.status === "failed") {
        setError(data.message || "任务失败");
        setViewMode("upload");
      } else {
        pollTimerRef.current = setTimeout(() => void pollStatus(tid), 1500);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "轮询失败";
      setError(`轮询失败: ${msg}`);
      setViewMode("upload");
    }
  };

  const fetchResults = async (tid: string, offset = 0) => {
    try {
      const res = await fetch(`/api/batch-audit/${tid}/results?limit=200&offset=${offset}`);
      const data = (await res.json()) as { items?: AuditResultRow[] };
      if (res.ok && data.items) {
        setResults(data.items);
      }
    } catch {
      /* ignore */
    }
  };

  const startAudit = async () => {
    if (!file) {
      setError("请先上传 Excel 文件");
      return;
    }

    setUploading(true);
    setError(null);
    setStatus(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const qs = new URLSearchParams({
        concurrency: String(concurrency),
        strategy: "one_vote_veto",
      });
      const res = await fetch(`/api/batch-audit/upload?${qs}`, {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(apiErrorDetail(data));
      }

      setTaskId(data.task_id as string);
      setViewMode("running");
      setUploading(false);
      void pollStatus(data.task_id as string);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "创建任务失败");
      setUploading(false);
    }
  };

  const handleExport = async () => {
    if (!taskId) return;

    try {
      const res = await fetch(`/api/batch-audit/${taskId}/export`);
      if (!res.ok) throw new Error("导出失败");

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.style.display = "none";
      a.href = url;
      a.download = `批量审核结果_${new Date().toISOString().slice(0, 19).replace(/[-:]/g, "")}.xlsx`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      }, 100);
    } catch (err: unknown) {
      alert(`导出失败: ${err instanceof Error ? err.message : ""}`);
    }
  };

  const reset = () => {
    setFile(null);
    setTaskId(null);
    setStatus(null);
    setResults([]);
    setViewMode("upload");
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const contentPreview = (text: string | undefined, max = 80) => {
    const s = text || "";
    if (s.length <= max) return s;
    return `${s.slice(0, max)}…`;
  };

  return (
    <div className="batch-audit-panel">
      <div className="panel-header">
        <h2>
          <FileSpreadsheet size={20} /> 批量审核
        </h2>
        {viewMode !== "upload" && (
          <button type="button" className="btn-reset" onClick={reset}>
            <X size={14} /> 重新开始
          </button>
        )}
      </div>

      {viewMode === "upload" && (
        <div className="upload-section">
          <div className="drop-zone" onDrop={handleDrop} onDragOver={(e) => e.preventDefault()}>
            <Upload size={48} className="upload-icon" />
            <p>
              拖拽 Excel 文件到此处，或{" "}
              <label className="file-label">
                点击选择
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xls"
                  onChange={handleFileSelect}
                  hidden
                />
              </label>
            </p>
            <p className="hint">Excel 需包含 id + content（或中文列名），最多 5000 条</p>
            {file && (
              <div className="selected-file">
                <FileSpreadsheet size={16} />
                <span>{file.name}</span>
                <span className="file-size">({(file.size / 1024).toFixed(1)} KB)</span>
              </div>
            )}
          </div>

          <div className="config-section">
            <div className="config-item">
              <label>并发数</label>
              <div className="concurrency-control">
                <button type="button" onClick={() => setConcurrency(Math.max(1, concurrency - 1))}>
                  -
                </button>
                <span>{concurrency}</span>
                <button type="button" onClick={() => setConcurrency(Math.min(10, concurrency + 1))}>
                  +
                </button>
              </div>
              <span className="hint">同时审核数量（1-10）</span>
            </div>
          </div>

          {error && (
            <div className="error-msg">
              <AlertTriangle size={14} /> {error}
            </div>
          )}

          <button type="button" className="btn-start-audit" onClick={() => void startAudit()} disabled={uploading || !file}>
            {uploading ? (
              <>
                <Loader size={16} className="spin" /> 创建任务中...
              </>
            ) : (
              <>
                <Play size={16} /> 开始批量审核
              </>
            )}
          </button>
        </div>
      )}

      {viewMode === "running" && (
        <div className="running-section">
          {status ? (
            <>
              <div className="task-info">
                <span className="task-id">任务: {status.task_id}</span>
                <span className="task-total">共 {status.total} 条</span>
              </div>

              <div className="progress-container">
                <div className="progress-bar-bg">
                  <div className="progress-bar-fill" style={{ width: `${status.percent}%` }} />
                </div>
                <span className="progress-text">{status.percent}%</span>
              </div>

              <div className="progress-stats">
                <div className="stat">
                  <span className="stat-num completed">{status.completed}</span>
                  <span className="stat-label">已完成</span>
                </div>
                <div className="stat">
                  <span className="stat-num failed">{status.failed}</span>
                  <span className="stat-label">失败</span>
                </div>
                <div className="stat">
                  <span className="stat-num remaining">{status.remaining ?? 0}</span>
                  <span className="stat-label">剩余</span>
                </div>
              </div>

              <p className="status-message">
                <Loader size={14} className="spin" /> {status.message}
              </p>
            </>
          ) : (
            <p className="status-message">
              <Loader size={14} className="spin" /> 连接任务状态…
            </p>
          )}
        </div>
      )}

      {viewMode === "completed" && (
        <div className="completed-section">
          <div className="result-header">
            <div className="result-summary">
              <CheckCircle size={20} color="#52c41a" />
              <span>审核完成！</span>
              <span className="summary-detail">
                成功 {status?.completed ?? 0} / 失败 {status?.failed ?? 0} / 总计 {status?.total ?? 0}
              </span>
            </div>
            <button type="button" className="btn-export" onClick={() => void handleExport()}>
              <Download size={14} /> 导出宽表
            </button>
          </div>

          <div className="results-table-container">
            <table className="results-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>内容</th>
                  <th>规则执行员</th>
                  <th>对抗侦探</th>
                  <th>判例执行员</th>
                  <th>大法官</th>
                  <th>最终结果</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => {
                  const final = verdictStyle(r.final_result);
                  return (
                    <tr key={r.id} className={r.status === "failed" ? "failed-row" : ""}>
                      <td className="col-id">{r.id}</td>
                      <td className="col-content" title={r.content}>
                        {contentPreview(r.content)}
                      </td>
                      <td>
                        <VerdictBadge result={r.rule_executor?.verdict} />
                      </td>
                      <td>
                        <VerdictBadge result={r.adversarial_detective?.verdict} />
                      </td>
                      <td>
                        <VerdictBadge result={r.case_executor?.verdict} />
                      </td>
                      <td>
                        <VerdictBadge result={r.chief_judge?.verdict} />
                      </td>
                      <td>
                        <span className="final-badge" style={{ background: final.bg, color: final.color }}>
                          {final.text}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

const VerdictBadge: React.FC<{ result?: string }> = ({ result }) => {
  const s = verdictStyle(result);
  return (
    <span className="verdict-mini" style={{ background: s.bg, color: s.color }}>
      {s.text}
    </span>
  );
};
