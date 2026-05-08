import { useMemo, useRef, useState, type DragEvent } from "react";

import {
  batchImportKnowledge,
  getKnowledgeTemplateUrl,
  type BatchImportResult,
  previewKnowledgeImport,
  type ImportPreview,
} from "../../services/api";

interface BatchImportModalProps {
  open: boolean;
  collection: "rule_base" | "knowledge_base";
  onClose: () => void;
  onImportComplete: () => void;
}

type Step = "upload" | "preview" | "importing" | "done";

export function BatchImportModal({
  open,
  collection,
  onClose,
  onImportComplete,
}: BatchImportModalProps) {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [result, setResult] = useState<BatchImportResult | null>(null);
  const [progress, setProgress] = useState(0);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const title = collection === "rule_base" ? "规则库批量导入" : "知识库批量导入";

  const canImport = useMemo(
    () => step === "preview" && !!preview && preview.valid_count > 0 && !!file,
    [step, preview, file],
  );

  if (!open) return null;

  const reset = () => {
    setStep("upload");
    setFile(null);
    setPreview(null);
    setResult(null);
    setProgress(0);
  };

  const parseAndPreview = async (selected: File) => {
    setFile(selected);
    const p = await previewKnowledgeImport(selected, collection);
    setPreview(p);
    setStep("preview");
  };

  const handleImport = async () => {
    if (!file) return;
    setStep("importing");
    setProgress(8);
    const timer = window.setInterval(() => {
      setProgress((p) => (p >= 92 ? p : p + 6));
    }, 180);
    try {
      const res = await batchImportKnowledge(file, collection);
      setResult(res);
      setProgress(100);
      setStep("done");
      onImportComplete();
    } finally {
      window.clearInterval(timer);
    }
  };

  const onDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const selected = e.dataTransfer.files?.[0];
    if (selected) await parseAndPreview(selected);
  };

  const formatHint = "支持 CSV / JSON / Excel(.xlsx/.xls)";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
      <div className="w-full max-w-3xl rounded-xl bg-white p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button className="rounded border px-3 py-1 text-sm" onClick={() => { reset(); onClose(); }}>
            关闭
          </button>
        </div>

        {step === "upload" && (
          <div className="space-y-3">
            <div
              className={`rounded-xl border-2 border-dashed p-8 text-center ${dragging ? "border-blue-500 bg-blue-50" : "border-slate-300"}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <p className="text-sm text-slate-700">拖拽文件到此处上传</p>
              <p className="my-2 text-sm text-slate-500">或</p>
              <button className="rounded bg-blue-600 px-3 py-2 text-sm text-white" onClick={() => fileInputRef.current?.click()}>
                选择文件
              </button>
              <p className="mt-3 text-xs text-slate-500">{formatHint}</p>
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept=".csv,.json,.xlsx,.xls"
                onChange={(e) => e.target.files?.[0] && void parseAndPreview(e.target.files[0])}
              />
            </div>
            <a
              href={getKnowledgeTemplateUrl(collection, "csv")}
              className="inline-block rounded border border-slate-300 px-3 py-2 text-sm"
              target="_blank"
              rel="noreferrer"
            >
              下载批量导入模板
            </a>
          </div>
        )}

        {step === "preview" && preview && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 rounded bg-slate-50 p-3 text-sm md:grid-cols-5">
              <span>文件: {preview.file_name}</span>
              <span>格式: {preview.file_type.toUpperCase()}</span>
              <span>总行数: {preview.total_rows}</span>
              <span>有效: {preview.valid_count}</span>
              <span>错误: {preview.error_count}</span>
            </div>

            <div className="overflow-auto rounded border">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-100">
                  <tr>
                    {preview.headers.map((h) => (
                      <th key={h} className="px-3 py-2">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.map((row, i) => (
                    <tr key={i} className="border-t">
                      {preview.headers.map((h) => (
                        <td key={h} className="px-3 py-2">{String(row[h] ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {!!preview.errors.length && (
              <div className="max-h-40 overflow-auto rounded border border-amber-300 bg-amber-50 p-2 text-sm">
                {preview.errors.map((e, idx) => (
                  <div key={`${e.row}-${idx}`}>第{e.row}行: {e.error}</div>
                ))}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button className="rounded border px-3 py-2 text-sm" onClick={() => setStep("upload")}>返回修改</button>
              <button
                className="rounded bg-emerald-600 px-3 py-2 text-sm text-white disabled:opacity-50"
                disabled={!canImport}
                onClick={() => void handleImport()}
              >
                确认导入 ({preview.valid_count}条)
              </button>
            </div>
          </div>
        )}

        {step === "importing" && (
          <div className="space-y-3">
            <div className="h-3 overflow-hidden rounded bg-slate-200">
              <div className="h-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className="text-sm text-slate-700">正在导入... {progress}%</p>
            <button className="rounded border px-3 py-2 text-sm" onClick={() => { reset(); onClose(); }}>
              取消导入
            </button>
          </div>
        )}

        {step === "done" && result && (
          <div className="space-y-2 text-sm">
            <h4 className="text-base font-semibold text-emerald-700">导入完成</h4>
            <p>成功导入: {result.success_count} 条</p>
            <p>跳过: {result.skip_count} 条</p>
            <p>耗时: {result.duration_ms} ms</p>
            <div className="pt-2">
              <button className="rounded border px-3 py-2 text-sm" onClick={reset}>继续导入</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
