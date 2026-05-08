import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";

import type { ImportReport, RulesBatchPreviewResponse, RuleImportStrategyApi } from "../services/api";
import {
  confirmRulesBatchUpload,
  getKnowledgeBatchProgress,
  previewRulesBatchUpload,
  startKnowledgeBatchUpload,
} from "../services/api";

interface Props {
  type: "rules" | "knowledge";
  open: boolean;
  onClose: () => void;
  /** 规则/知识大批量结束后：成功写入条数的合计（取自进度聚合） */
  onSuccess?: (writtenCount: number) => void;
}

type PollState = {
  total: number;
  processed: number;
  success: number;
  failed: number;
  skipped: number;
  status: string;
  poll_url?: string;
  errors: Array<{ row?: number; error: string }>;
  report?: ImportReport | null;
};

const strategyLabels: Record<RuleImportStrategyApi, string> = {
  skip: "跳过重复（保留库里已有规则，本条不写入）",
  overwrite: "覆盖重复（删除并替换已有规则内容）",
  keep_both: "保留两者（新规则换新 ID，并在分类中加后缀标注副本）",
  merge: "合并更新（沿用已有规则 ID，用文件中的字段覆盖更新）",
};

const dupKindZh = (k: string) =>
  ({
    new: "新内容",
    duplicate_exact: "完全重复",
    duplicate_similar: "疑似重复（高度相似）",
  })[k] ?? k;

/** 单行错误字段可能是 string 或后端嵌套对象，避免渲染成 [object Object] */
function displayRowError(raw: unknown): string {
  if (raw == null) return "";
  if (typeof raw === "string") return raw;
  if (typeof raw === "number" || typeof raw === "boolean") return String(raw);
  try {
    return JSON.stringify(raw);
  } catch {
    return String(raw);
  }
}

export function BatchUploadModal({ type, open, onClose, onSuccess }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [preview, setPreview] = useState<RulesBatchPreviewResponse | null>(null);
  const [strategy, setStrategy] = useState<RuleImportStrategyApi>("skip");
  const pollRef = useRef<number | null>(null);
  const [progressState, setProgressState] = useState<PollState | null>(null);

  const title = type === "rules" ? "批量导入规则库（后台）" : "批量导入知识库（后台）";
  const kind = type === "rules" ? "rules" : "kb";

  const reset = () => {
    setFile(null);
    setUploading(false);
    setAnalyzing(false);
    setPreview(null);
    setStrategy("skip");
    setProgressState(null);
    if (pollRef.current) window.clearTimeout(pollRef.current);
    pollRef.current = null;
  };

  useEffect(
    () => () => {
      if (pollRef.current) window.clearTimeout(pollRef.current);
    },
    [],
  );

  const pickFileExt = (f: File): string => {
    const ext = (f.name.split(".").pop() || "csv").toLowerCase();
    if (["csv", "json", "xlsx", "xls"].includes(ext)) return ext;
    return "csv";
  };

  const poll = (pollUrl: string) => {
    const loop = async () => {
      try {
        const p = await getKnowledgeBatchProgress(pollUrl);
        const st = p.status;
        setProgressState((prev) => ({
          total: p.total,
          processed: p.processed,
          success: p.success,
          failed: p.failed,
          skipped: p.skipped,
          status: st,
          errors: p.errors || [],
          report: p.report ?? prev?.report,
          poll_url: pollUrl,
        }));
        if (st === "completed") {
          setUploading(false);
          onSuccess?.(p.success);
          return;
        }
        if (st === "failed") {
          setUploading(false);
          return;
        }
      } catch {
        setUploading(false);
      }
      pollRef.current = window.setTimeout(() => void loop(), 800);
    };
    pollRef.current = window.setTimeout(() => void loop(), 300);
  };

  /** 规则：分析重复预览 */
  const analyzeRulesDuplicates = async () => {
    if (!file || kind !== "rules") return;
    const ext = pickFileExt(file);
    setAnalyzing(true);
    setProgressState(null);
    try {
      const data = await previewRulesBatchUpload(file, ext);
      setPreview(data);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "分析失败");
    } finally {
      setAnalyzing(false);
    }
  };

  /** 规则：确认策略并后台写入 */
  const confirmRulesImport = async () => {
    if (!preview || kind !== "rules") return;
    setUploading(true);
    setProgressState({ total: 0, processed: 0, success: 0, failed: 0, skipped: 0, status: "queued", errors: [] });
    try {
      const data = await confirmRulesBatchUpload(preview.preview_id, strategy);
      setProgressState({
        total: preview.valid_row_count,
        processed: 0,
        success: 0,
        failed: 0,
        skipped: 0,
        status: "processing",
        poll_url: data.poll_url,
        errors: [],
      });
      poll(data.poll_url);
    } catch (e) {
      setUploading(false);
      setProgressState(null);
      window.alert(e instanceof Error ? e.message : "确认导入失败");
    }
  };

  /** 知识库：直接大批量上传（无预览） */
  const startKbUpload = async () => {
    if (!file || kind !== "kb") return;
    const ext = pickFileExt(file);
    setProgressState({ total: 0, processed: 0, success: 0, failed: 0, skipped: 0, status: "queued", errors: [] });
    setUploading(true);
    try {
      const data = await startKnowledgeBatchUpload("kb", file, ext);
      setProgressState({
        total: data.total,
        processed: 0,
        success: 0,
        failed: 0,
        skipped: 0,
        status: "processing",
        poll_url: data.poll_url,
        errors: [],
      });
      poll(data.poll_url);
    } catch (e) {
      setUploading(false);
      setProgressState(null);
      window.alert(e instanceof Error ? e.message : "上传失败");
    }
  };

  const onDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) {
      setFile(f);
      setPreview(null);
    }
  }, []);

  if (!open) return null;

  const pct = progressState && progressState.total > 0 ? Math.round((progressState.processed / progressState.total) * 100) : 0;

  const showFileStep = kind === "kb" ? !progressState : !progressState && !preview;
  const showRulesPreview = kind === "rules" && preview && !progressState;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4"
      onClick={() => {
        reset();
        onClose();
      }}
    >
      <div
        className={`w-full ${kind === "rules" && preview ? "max-w-4xl" : "max-w-lg"} max-h-[90vh] overflow-y-auto rounded-xl bg-white p-5 shadow-xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-4 text-lg font-semibold">{title}</h3>

        {showFileStep && (
          <>
            <div
              className={`rounded-xl border-2 border-dashed p-6 text-center ${dragging ? "border-blue-500 bg-blue-50" : "border-slate-300"}`}
              onDragOver={(e) => e.preventDefault()}
              onDragEnter={() => setDragging(true)}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <p className="text-sm text-slate-700">拖拽文件到此处，或点击下方选择文件</p>
              <input
                type="file"
                accept=".csv,.json,.xlsx,.xls"
                className="mt-3 text-sm"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    setFile(f);
                    setPreview(null);
                  }
                }}
              />
              <p className="mt-2 text-xs text-slate-500">支持 CSV / JSON / NDJSON / Excel · 单文件 ≤50MB</p>
              {file && <p className="mt-2 truncate text-xs text-slate-600">{file.name}（{(file.size / 1024).toFixed(1)} KB）</p>}
            </div>

            <p className="mt-2 text-xs text-amber-800">
              {kind === "rules"
                ? "规则库会先分析与已有内容及同文件前面行的相似度（≥90% 为疑似），再请选择处理策略。"
                : "知识库大批量将直接写入后台并行显示进度（无预览）。"}
            </p>
          </>
        )}

        {showRulesPreview && preview && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2 text-xs text-slate-700">
              <span>文件总行：{preview.total_rows}</span>
              <span>校验通过待导入：{preview.valid_row_count}</span>
              <span className="text-emerald-700">新机：{preview.analysis.summary.new}</span>
              <span className="text-rose-700">完全相同：{preview.analysis.summary.duplicate_exact}</span>
              <span className="text-amber-800">疑似重复：{preview.analysis.summary.duplicate_similar}</span>
              <span className="text-slate-500">阈值：{(preview.analysis.similarity_threshold * 100).toFixed(0)}%</span>
            </div>

            {preview.validation_errors.length > 0 && (
              <div className="max-h-24 overflow-auto rounded border border-red-200 bg-red-50 p-2 text-xs text-red-900">
                {preview.validation_errors.map((ev, idx) => (
                  <div key={idx}>
                    {ev.row !== undefined ? `第${ev.row}行：` : ""}
                    {displayRowError(ev.error)}
                  </div>
                ))}
              </div>
            )}

            <div>
              <label className="mb-1 block text-sm font-medium text-slate-800">出现重复/疑似重复时的策略</label>
              <select
                className="w-full rounded border border-slate-300 p-2 text-sm"
                value={strategy}
                onChange={(e) => setStrategy(e.target.value as RuleImportStrategyApi)}
              >
                {(Object.keys(strategyLabels) as RuleImportStrategyApi[]).map((k) => (
                  <option key={k} value={k}>
                    {strategyLabels[k]}
                  </option>
                ))}
              </select>
            </div>

            <div className="max-h-56 overflow-auto rounded border border-slate-200">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-slate-100">
                  <tr>
                    <th className="p-2">行</th>
                    <th className="p-2">判定</th>
                    <th className="p-2">相似度</th>
                    <th className="p-2">匹配ID</th>
                    <th className="p-2">内容预览</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.analysis.items.map((it) => (
                    <tr key={it.row} className="border-t border-slate-100">
                      <td className="p-2 align-top">{it.row}</td>
                      <td className="p-2 align-top">{dupKindZh(it.kind)}</td>
                      <td className="p-2 align-top">{it.kind === "new" ? "—" : `${(it.similarity * 100).toFixed(1)}%`}</td>
                      <td className="p-2 align-top font-mono text-[10px]">{it.matched_id ?? "—"}</td>
                      <td className="max-w-xs p-2 align-top break-words text-slate-600">{it.content_preview}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {progressState && (
          <div className="mt-4 space-y-3">
            <div className="h-2 overflow-hidden rounded bg-slate-200">
              <div className="h-full bg-blue-600 transition-[width]" style={{ width: `${pct}%` }} />
            </div>
            <div className="flex flex-wrap gap-3 text-xs text-slate-600">
              <span>总数：{progressState.total}</span>
              <span>已处理：{progressState.processed}</span>
              <span className="text-emerald-600">成功写入（合计）：{progressState.success}</span>
              {progressState.skipped > 0 && <span className="text-slate-500">跳过重复：{progressState.skipped}</span>}
              {progressState.failed > 0 && <span className="text-amber-600">失败：{progressState.failed}</span>}
            </div>
            {progressState.report && progressState.status === "completed" && (
              <div className="rounded border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900">
                <p className="font-medium">导入报告</p>
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  <li>新写入：{progressState.report.success_imported}</li>
                  <li>跳过重复：{progressState.report.skipped_duplicate}</li>
                  <li>覆盖更新：{progressState.report.overwrite}</li>
                  <li>合并更新：{progressState.report.merged_update}</li>
                  <li>保留两者（新增副本）：{progressState.report.both_kept_added}</li>
                  <li>失败：{progressState.report.failed}</li>
                </ul>
              </div>
            )}
            <p className="text-xs text-slate-500">
              {progressState.status === "queued" && "队列中"}
              {progressState.status === "processing" && "处理中"}
              {progressState.status === "completed" && "已完成"}
              {progressState.status === "failed" && "失败"}
            </p>
            {progressState.errors.length > 0 && (
              <div className="max-h-36 overflow-auto rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
                {progressState.errors.map((err, idx) => (
                  <div key={idx}>
                    {err.row !== undefined ? `第${err.row}行：` : ""}
                    {displayRowError(err.error)}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="mt-4 flex flex-wrap justify-end gap-2 border-t pt-4">
          <button
            type="button"
            className="rounded border border-slate-300 px-3 py-2 text-sm"
            onClick={() => {
              reset();
              onClose();
            }}
          >
            关闭
          </button>

          {showFileStep && kind === "rules" && (
            <button
              type="button"
              className="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50"
              disabled={!file || analyzing}
              onClick={() => void analyzeRulesDuplicates()}
            >
              {analyzing ? "分析中…" : "下一步：分析重复"}
            </button>
          )}

          {showRulesPreview && (
            <>
              <button
                type="button"
                className="rounded border border-slate-300 px-3 py-2 text-sm"
                onClick={() => setPreview(null)}
              >
                上一步重新选文件
              </button>
              <button
                type="button"
                className="rounded bg-emerald-600 px-3 py-2 text-sm text-white disabled:opacity-50"
                disabled={uploading || preview.valid_row_count === 0}
                onClick={() => void confirmRulesImport()}
              >
                确认导入
              </button>
            </>
          )}

          {showFileStep && kind === "kb" && (
            <button
              type="button"
              className="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-50"
              disabled={!file}
              onClick={() => void startKbUpload()}
            >
              开始导入
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

interface ButtonProps {
  type: "rules" | "knowledge";
  onSuccess?: (writtenCount: number) => void;
  className?: string;
}

/** 带触发按钮的大批量后台导入（规则库 / 知识库） */
export function BatchUploadButton({ type, onSuccess, className }: ButtonProps) {
  const [open, setOpen] = useState(false);
  const label = type === "rules" ? "大批量导入规则（进度）" : "大批量导入知识（进度）";
  return (
    <>
      <button
        type="button"
        className={`batch-upload-btn ${type === "rules" ? "batch-upload-btn--rules" : "batch-upload-btn--knowledge"} rounded border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 ${className ?? ""}`}
        onClick={() => setOpen(true)}
      >
        {label}
      </button>
      <BatchUploadModal
        type={type}
        open={open}
        onClose={() => setOpen(false)}
        onSuccess={(n) => {
          onSuccess?.(n);
          setOpen(false);
        }}
      />
    </>
  );
}
