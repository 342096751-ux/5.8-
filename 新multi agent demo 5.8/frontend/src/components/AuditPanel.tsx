import { useState } from "react";

interface Props {
  loading: boolean;
  onStart: (content: string) => void;
  onOpenConfig: () => void;
}

export function AuditPanel({ loading, onStart, onOpenConfig }: Props) {
  const [content, setContent] = useState("");

  return (
    <div className="rounded-3xl border border-slate-200 bg-slate-50 p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-slate-900">审核输入</div>
          <div className="mt-1 text-xs leading-relaxed text-slate-500">输入待审核文本，系统会自动调度多 Agent 协作分析。</div>
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <textarea
          className="min-h-36 w-full rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
          placeholder="输入待审核内容..."
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="rounded-2xl bg-blue-600 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => onStart(content)}
            disabled={loading || !content.trim()}
          >
            {loading ? "审核中..." : "开始审核"}
          </button>
          <button
            className="rounded-2xl border border-slate-200 bg-white px-5 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            onClick={onOpenConfig}
          >
            查看配置
          </button>
        </div>
      </div>
    </div>
  );
}
