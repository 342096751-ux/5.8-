import type { AuditResult } from "../types/audit";

interface Props {
  result: AuditResult | null;
}

const FINAL_VERDICT_TEXT = {
  violation: "最终判定：违规",
  normal: "最终判定：正常",
};

export function ResultPanel({ result }: Props) {
  const isViolation = result?.final_verdict === "violation";
  const confidence = result ? `${Math.round(result.confidence * 100)}%` : "--";
  const finalText = result ? FINAL_VERDICT_TEXT[result.final_verdict] : "最终判定：未审核";
  const excelThis =
    result && result.audit_id
      ? `/api/export/wide-table/excel?audit_ids=${encodeURIComponent(result.audit_id)}`
      : "";
  const excelRecent = "/api/export/wide-table/excel";
  return (
    <div className="rounded-3xl border border-slate-200 bg-slate-50 p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">审核结果</div>
          <div className={`mt-1 text-base font-semibold ${isViolation ? "text-red-600" : "text-emerald-600"}`}>
            {finalText}
          </div>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
          <div className="text-xs text-slate-500">置信度</div>
          <div className="mt-1 text-lg font-semibold">{confidence}</div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {excelThis ? (
          <a
            className="rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-700 transition hover:bg-slate-50"
            href={excelThis}
            target="_blank"
            rel="noreferrer"
          >
            导出本批 Excel 宽表
          </a>
        ) : null}
        <a
          className="rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-600 transition hover:bg-slate-50"
          href={`${excelRecent}?sort=desc`}
          target="_blank"
          rel="noreferrer"
          title="最近10条批次，按时间倒序"
        >
          导出最近批次
        </a>
        <a
          className="rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-500 transition hover:bg-slate-50"
          href="/api/logs/export"
          target="_blank"
          rel="noreferrer"
        >
          导出日志 JSON
        </a>
      </div>
    </div>
  );
}
