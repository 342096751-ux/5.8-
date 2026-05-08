import { useEffect, useState } from "react";

import { BatchUploadButton } from "../components/BatchUploadModal";
import { TableWithBatchDelete } from "../components/BatchDeleteModal";
import "../styles/batch-upload.css";
import "../styles/batch-delete.css";

import { BatchImportModal } from "../components/KnowledgeManager/BatchImportModal";
import { createKnowledge, fetchKnowledgeList, getKnowledgeTemplateUrl, updateKnowledge } from "../services/api";

type Bucket = "rules" | "kb";
type RowData = Record<string, unknown>;

export function KnowledgePage() {
  const [tab, setTab] = useState<Bucket>("rules");
  const [rows, setRows] = useState<RowData[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<RowData | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [form, setForm] = useState({ id: "", category: "", topic: "", content: "", severity: "", related_rule: "" });

  const refresh = async () => {
    setLoading(true);
    try {
      const res = await fetchKnowledgeList(tab, { page: 1, page_size: 0 });
      setRows(res.items as RowData[]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [tab]);

  const handleSave = async () => {
    const payload: RowData = { ...form, text: form.content };
    if (editing?.id) await updateKnowledge(tab, String(editing.id), payload);
    else await createKnowledge(tab, payload);
    setEditing(null);
    setForm({ id: "", category: "", topic: "", content: "", severity: "", related_rule: "" });
    await refresh();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <div className="flex gap-2">
        <button className={`rounded px-3 py-2 text-sm ${tab === "rules" ? "bg-blue-600 text-white" : "bg-white ring-1 ring-slate-300"}`} onClick={() => setTab("rules")}>规则库</button>
        <button className={`rounded px-3 py-2 text-sm ${tab === "kb" ? "bg-blue-600 text-white" : "bg-white ring-1 ring-slate-300"}`} onClick={() => setTab("kb")}>知识库</button>
      </div>

      <div className="rounded-xl bg-white p-4 ring-1 ring-slate-200">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">
            <button className="rounded bg-blue-600 px-3 py-2 text-sm text-white" type="button" onClick={() => setEditing({})}>添加{tab === "rules" ? "规则" : "知识"}</button>
            <button type="button" className="rounded border border-slate-300 px-3 py-2 text-sm" onClick={() => setImportOpen(true)}>批量导入</button>
            <BatchUploadButton
              type="rules"
              onSuccess={(n) => {
                window.alert(`导入${n}条`);
                void refresh();
              }}
            />
            <BatchUploadButton
              type="knowledge"
              onSuccess={(n) => {
                window.alert(`导入${n}条`);
                void refresh();
              }}
            />
            <a
              className="rounded border border-slate-300 px-3 py-2 text-sm"
              href={getKnowledgeTemplateUrl(tab === "rules" ? "rule_base" : "knowledge_base", "csv")}
              target="_blank"
              rel="noreferrer"
            >
              下载批量导入模板
            </a>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-700">
            {loading ? <span className="text-slate-500">加载中…</span> : <span className="font-medium">共 {rows.length} 条</span>}
          </div>
        </div>

        <TableWithBatchDelete
          type={tab === "rules" ? "rules" : "knowledge"}
          data={rows}
          onRefresh={() => refresh()}
        />
      </div>

      {editing && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-xl rounded-xl bg-white p-4">
            <div className="mb-3 text-lg font-semibold">{editing.id ? "编辑" : "新增"}</div>
            <div className="grid gap-2">
              <input className="rounded border p-2" placeholder="ID" value={form.id} onChange={(e) => setForm((s) => ({ ...s, id: e.target.value }))} />
              {tab === "rules" ? (
                <>
                  <input className="rounded border p-2" placeholder="分类" value={form.category} onChange={(e) => setForm((s) => ({ ...s, category: e.target.value }))} />
                  <input className="rounded border p-2" placeholder="严重度" value={form.severity} onChange={(e) => setForm((s) => ({ ...s, severity: e.target.value }))} />
                </>
              ) : (
                <>
                  <input className="rounded border p-2" placeholder="主题" value={form.topic} onChange={(e) => setForm((s) => ({ ...s, topic: e.target.value }))} />
                  <input className="rounded border p-2" placeholder="关联规则" value={form.related_rule} onChange={(e) => setForm((s) => ({ ...s, related_rule: e.target.value }))} />
                </>
              )}
              <textarea className="min-h-24 rounded border p-2" placeholder="内容" value={form.content} onChange={(e) => setForm((s) => ({ ...s, content: e.target.value }))} />
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <button className="rounded border px-3 py-2" type="button" onClick={() => setEditing(null)}>取消</button>
              <button className="rounded bg-blue-600 px-3 py-2 text-white" type="button" onClick={() => void handleSave()}>保存</button>
            </div>
          </div>
        </div>
      )}
      <BatchImportModal
        open={importOpen}
        collection={tab === "rules" ? "rule_base" : "knowledge_base"}
        onClose={() => setImportOpen(false)}
        onImportComplete={() => {
          void refresh();
        }}
      />
    </div>
  );
}
