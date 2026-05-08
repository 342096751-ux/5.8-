import { useEffect, useMemo, useState } from "react";

import { CaseItem, createCase, deleteCase, importCases, listCases, updateCase, getCaseTemplateUrl, previewCasesImport } from "../services/api";

type VerdictFilter = "" | "violation" | "normal";

const EMPTY_FORM: CaseItem = {
  id: "",
  text: "",
  verdict: "violation",
  violation_reason: "",
  category: "未分类",
  confidence: 0.8,
  matched_rules: [],
  source: "manual",
};

export function CasePage() {
  const [rows, setRows] = useState<CaseItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<CaseItem | null>(null);
  const [form, setForm] = useState<CaseItem>(EMPTY_FORM);
  const [importing, setImporting] = useState(false);
  const [previewRows, setPreviewRows] = useState<Array<Record<string, unknown>>>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewFileName, setPreviewFileName] = useState("");

  const refresh = async () => {
    setLoading(true);
    try {
      const data = await listCases({
        category: categoryFilter || undefined,
        verdict: verdictFilter || undefined,
      });
      setRows(data);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "加载判例失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [categoryFilter, verdictFilter]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => set.add(r.category || "未分类"));
    return Array.from(set).sort();
  }, [rows]);

  const openCreate = () => {
    setEditing(null);
    setForm({ ...EMPTY_FORM, id: `CASE_${Date.now()}` });
    setOpen(true);
  };

  const openEdit = (row: CaseItem) => {
    setEditing(row);
    setForm({
      ...row,
      matched_rules: Array.isArray(row.matched_rules) ? row.matched_rules : [],
    });
    setOpen(true);
  };

  const submit = async () => {
    try {
      const payload: CaseItem = {
        ...form,
        matched_rules: form.matched_rules || [],
      };
      if (!payload.id.trim()) {
        window.alert("请填写判例ID");
        return;
      }
      if (!payload.text.trim()) {
        window.alert("请填写文本内容");
        return;
      }
      if (payload.verdict === "violation" && !payload.violation_reason.trim()) {
        window.alert("违规判例请填写违规原因");
        return;
      }
      if (editing) await updateCase(editing.id, payload);
      else await createCase(payload);
      setOpen(false);
      await refresh();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "保存失败");
    }
  };

  const onDelete = async (id: string) => {
    if (!window.confirm(`确认删除判例 ${id} ?`)) return;
    try {
      await deleteCase(id);
      await refresh();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "删除失败");
    }
  };

  const handleImport = async (file: File) => {
    setPreviewLoading(true);
    try {
      const preview = await previewCasesImport(file);
      setPreviewRows(preview.data.preview || []);
      setPreviewFileName(file.name);
      setPreviewOpen(true);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "预览失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const confirmImport = async () => {
    if (!previewRows.length) return;
    setImporting(true);
    try {
      const blob = new Blob([JSON.stringify(previewRows)], { type: "application/json" });
      const file = new File([blob], previewFileName || "cases.json", { type: "application/json" });
      const res = await importCases(file);
      window.alert(`导入完成：成功 ${res.success}，失败 ${res.failed}`);
      setPreviewOpen(false);
      await refresh();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "导入失败");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <div className="rounded-xl bg-white p-4 ring-1 ring-slate-200">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">
            <button className="rounded bg-blue-600 px-3 py-2 text-sm text-white" onClick={openCreate}>
              新增判例
            </button>
            <a
              className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
              href={getCaseTemplateUrl("csv")}
              download
            >
              下载批量导入模板
            </a>
            <label className="cursor-pointer rounded border border-slate-300 px-3 py-2 text-sm">
              {previewLoading ? "预览中..." : importing ? "导入中..." : "批量导入"}
              <input
                className="hidden"
                type="file"
                accept=".json,.csv,.xlsx,.xls"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleImport(file);
                  e.currentTarget.value = "";
                }}
              />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <input
              className="rounded border px-2 py-1"
              placeholder="按类别筛选"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              list="case-category-list"
            />
            <datalist id="case-category-list">
              {categories.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
            <select
              className="rounded border px-2 py-1"
              value={verdictFilter}
              onChange={(e) => setVerdictFilter(e.target.value as VerdictFilter)}
            >
              <option value="">全部判定</option>
              <option value="violation">违规</option>
              <option value="normal">正常</option>
            </select>
            <button className="rounded border px-3 py-1" onClick={() => void refresh()}>
              刷新
            </button>
            <span className="text-slate-500">{loading ? "加载中..." : `共 ${rows.length} 条`}</span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b text-left text-slate-600">
                <th className="px-2 py-2">ID</th>
                <th className="px-2 py-2">文本</th>
                <th className="px-2 py-2">判定</th>
                <th className="px-2 py-2">违规原因</th>
                <th className="px-2 py-2">类别</th>
                <th className="px-2 py-2">置信度</th>
                <th className="px-2 py-2">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b align-top">
                  <td className="px-2 py-2 font-mono text-xs">{r.id}</td>
                  <td className="max-w-md px-2 py-2">{r.text}</td>
                  <td className="px-2 py-2">
                    <span
                      className={`rounded px-2 py-1 text-xs ${
                        r.verdict === "violation" ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
                      }`}
                    >
                      {r.verdict === "violation" ? "违规" : "正常"}
                    </span>
                  </td>
                  <td className="max-w-md px-2 py-2">{r.violation_reason || "-"}</td>
                  <td className="px-2 py-2">{r.category}</td>
                  <td className="px-2 py-2">{Number(r.confidence ?? 0).toFixed(2)}</td>
                  <td className="px-2 py-2">
                    <div className="flex gap-2">
                      <button className="rounded border px-2 py-1" onClick={() => openEdit(r)}>
                        编辑
                      </button>
                      <button className="rounded border border-red-300 px-2 py-1 text-red-600" onClick={() => void onDelete(r.id)}>
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {previewOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4">
          <div className="w-full max-w-4xl rounded-xl bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="text-lg font-semibold">判例导入预览</div>
              <button className="rounded border px-3 py-1 text-sm" onClick={() => setPreviewOpen(false)}>
                关闭
              </button>
            </div>
            <div className="mb-3 text-sm text-slate-600">文件：{previewFileName}</div>
            <div className="max-h-[55vh] overflow-auto rounded border">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-100">
                  <tr>
                    {previewRows[0] ? Object.keys(previewRows[0]).map((k) => (
                      <th key={k} className="px-3 py-2">{k}</th>
                    )) : null}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, idx) => (
                    <tr key={idx} className="border-t">
                      {Object.keys(previewRows[0] || {}).map((k) => (
                        <td key={k} className="px-3 py-2">{String(row[k] ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button className="rounded border px-3 py-2" onClick={() => setPreviewOpen(false)}>
                取消
              </button>
              <button className="rounded bg-blue-600 px-3 py-2 text-white" onClick={() => void confirmImport()}>
                确认导入
              </button>
            </div>
          </div>
        </div>
      )}

      {open && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl rounded-xl bg-white p-4">
            <div className="mb-3 text-lg font-semibold">{editing ? "编辑判例" : "新增判例"}</div>
            <div className="grid gap-2">
              <input
                className="rounded border p-2"
                placeholder="ID"
                value={form.id}
                disabled={Boolean(editing)}
                onChange={(e) => setForm((s) => ({ ...s, id: e.target.value }))}
              />
              <textarea
                className="min-h-24 rounded border p-2"
                placeholder="文本内容"
                value={form.text}
                onChange={(e) => setForm((s) => ({ ...s, text: e.target.value }))}
              />
              <div className="grid grid-cols-2 gap-2">
                <select
                  className="rounded border p-2"
                  value={form.verdict}
                  onChange={(e) => setForm((s) => ({ ...s, verdict: e.target.value as "violation" | "normal" }))}
                >
                  <option value="violation">违规</option>
                  <option value="normal">正常</option>
                </select>
                <input
                  className="rounded border p-2"
                  placeholder="类别（如 政治敏感）"
                  value={form.category}
                  onChange={(e) => setForm((s) => ({ ...s, category: e.target.value }))}
                />
              </div>
              <textarea
                className="min-h-20 rounded border p-2"
                placeholder="违规原因（normal 可留空）"
                value={form.violation_reason}
                onChange={(e) => setForm((s) => ({ ...s, violation_reason: e.target.value }))}
              />
              <div className="grid grid-cols-2 gap-2">
                <label className="flex items-center gap-2 text-sm">
                  置信度
                  <input
                    className="w-full"
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={form.confidence}
                    onChange={(e) => setForm((s) => ({ ...s, confidence: Number(e.target.value) }))}
                  />
                  <span>{Number(form.confidence).toFixed(2)}</span>
                </label>
                <input
                  className="rounded border p-2"
                  placeholder="matched_rules，逗号分隔"
                  value={(form.matched_rules || []).join(",")}
                  onChange={(e) =>
                    setForm((s) => ({
                      ...s,
                      matched_rules: e.target.value
                        .split(",")
                        .map((x) => x.trim())
                        .filter(Boolean),
                    }))
                  }
                />
              </div>
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <button className="rounded border px-3 py-2" onClick={() => setOpen(false)}>
                取消
              </button>
              <button className="rounded bg-blue-600 px-3 py-2 text-white" onClick={() => void submit()}>
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
