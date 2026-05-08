import { useMemo, useState } from "react";

import { batchDeleteKnowledge } from "../services/api";

type RowData = Record<string, unknown>;

interface TableWithBatchDeleteProps {
  type: "rules" | "knowledge";
  data: RowData[];
  onRefresh: () => void | Promise<void>;
}

function rowContent(r: RowData): string {
  const md = typeof r.metadata === "object" && r.metadata !== null ? (r.metadata as RowData) : {};
  return String(r.document ?? md["内容"] ?? md.content ?? r.content ?? "").trim();
}

function rowLabel(type: "rules" | "knowledge", r: RowData): string {
  const md = typeof r.metadata === "object" && r.metadata !== null ? (r.metadata as RowData) : {};
  if (type === "rules") return String(md["分类"] ?? r.category ?? "").trim();
  return String(md["主题"] ?? r.topic ?? "").trim();
}

function rowExtra(type: "rules" | "knowledge", r: RowData): string {
  const md = typeof r.metadata === "object" && r.metadata !== null ? (r.metadata as RowData) : {};
  if (type === "rules") return String(md["严重度"] ?? r.severity ?? "").trim();
  return String(md["关联规则"] ?? r.related_rule ?? "").trim();
}

export function TableWithBatchDelete({ type, data, onRefresh }: TableWithBatchDeleteProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewItems, setPreviewItems] = useState<Array<{ id: string; content_preview: string }>>([]);
  const [previewNotFound, setPreviewNotFound] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const allIds = useMemo(() => data.map((r) => String(r.id ?? "")).filter(Boolean), [data]);
  const selectedIds = useMemo(() => allIds.filter((id) => selected[id]), [allIds, selected]);
  const allChecked = allIds.length > 0 && selectedIds.length === allIds.length;

  const toggleAll = () => {
    if (allChecked) {
      setSelected({});
      return;
    }
    const next: Record<string, boolean> = {};
    for (const id of allIds) next[id] = true;
    setSelected(next);
  };

  const toggleOne = (id: string) => {
    setSelected((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const openPreview = async () => {
    if (selectedIds.length === 0) return;
    if (selectedIds.length > 1000) {
      window.alert("单次最多删除1000条，请减少勾选数量。");
      return;
    }
    setSubmitting(true);
    try {
      const bucket = type === "rules" ? "rules" : "kb";
      const res = await batchDeleteKnowledge(bucket, selectedIds, false);
      setPreviewItems(res.preview ?? []);
      setPreviewNotFound(res.not_found_ids ?? []);
      setPreviewOpen(true);
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "预检查失败");
    } finally {
      setSubmitting(false);
    }
  };

  const confirmDelete = async () => {
    setSubmitting(true);
    try {
      const bucket = type === "rules" ? "rules" : "kb";
      const res = await batchDeleteKnowledge(bucket, selectedIds, true);
      window.alert(`删除完成：成功 ${res.deleted ?? 0}，失败 ${res.failed ?? 0}，不存在 ${res.not_found}`);
      setSelected({});
      setPreviewOpen(false);
      setPreviewItems([]);
      setPreviewNotFound([]);
      await onRefresh();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "删除失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-2">
      {selectedIds.length > 0 ? (
        <div className="flex items-center justify-between rounded border border-red-200 bg-red-50 p-2">
          <span className="text-sm text-red-700">已选中 {selectedIds.length} 条</span>
          <button
            type="button"
            className="rounded bg-red-600 px-3 py-1 text-sm text-white disabled:opacity-50"
            disabled={submitting}
            onClick={() => void openPreview()}
          >
            批量删除 ({selectedIds.length})
          </button>
        </div>
      ) : null}

      <div className="max-h-[min(70vh,720px)] overflow-auto rounded-lg border border-slate-100">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="sticky top-0 z-[1] bg-slate-50">
            <tr className="border-b text-slate-500">
              <th className="w-10 py-2 pl-2">
                <input type="checkbox" checked={allChecked} onChange={toggleAll} />
              </th>
              <th className="py-2">ID</th>
              <th>{type === "rules" ? "分类" : "主题"}</th>
              <th>内容</th>
              <th className="pr-2">{type === "rules" ? "严重度" : "关联规则"}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r, idx) => {
              const id = String(r.id ?? "");
              return (
                <tr key={`${id}-${idx}`} className="border-b hover:bg-slate-50">
                  <td className="pl-2 align-top">
                    <input type="checkbox" checked={Boolean(selected[id])} onChange={() => toggleOne(id)} />
                  </td>
                  <td className="max-w-[120px] break-all py-2 font-mono text-xs align-top">{id}</td>
                  <td className="align-top">{rowLabel(type, r)}</td>
                  <td className="max-w-md whitespace-pre-wrap break-words align-top">{rowContent(r)}</td>
                  <td className="pr-2 align-top">{rowExtra(type, r)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {previewOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
          <div className="w-full max-w-3xl rounded-xl bg-white p-5 shadow-xl">
            <h3 className="mb-2 text-lg font-semibold text-red-700">确认批量删除</h3>
            <p className="mb-3 text-sm text-slate-600">
              预检查命中 {previewItems.length} 条可删，{previewNotFound.length} 条不存在。
            </p>
            <div className="max-h-80 overflow-auto rounded border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50">
                  <tr>
                    <th className="p-2">ID</th>
                    <th className="p-2">内容预览</th>
                  </tr>
                </thead>
                <tbody>
                  {previewItems.map((x) => (
                    <tr key={x.id} className="border-t">
                      <td className="p-2 font-mono text-xs">{x.id}</td>
                      <td className="p-2">{x.content_preview}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-slate-300 px-3 py-2 text-sm"
                onClick={() => setPreviewOpen(false)}
              >
                取消
              </button>
              <button
                type="button"
                className="rounded bg-red-600 px-3 py-2 text-sm text-white disabled:opacity-50"
                disabled={submitting}
                onClick={() => void confirmDelete()}
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

