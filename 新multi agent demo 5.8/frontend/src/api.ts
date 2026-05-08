import type { AgentConfig, AuditResult, ModelConfig, TestConnectionResult } from "../types/audit";

const API_BASE = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "/api";

/** FastAPI 错误体：detail 可能是 string / 422 校验项数组[{loc,msg,type}]，避免转成 "[object Object]" */
export function formatApiErrorDetail(body: unknown, fallback = "请求失败"): string {
  if (body == null || typeof body !== "object") return fallback;
  const d = (body as { detail?: unknown }).detail;
  if (d == null || d === "") return fallback;
  if (typeof d === "string") return d;
  if (typeof d === "number" || typeof d === "boolean") return String(d);
  if (Array.isArray(d)) {
    const parts = d.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "msg" in item) {
        const o = item as { loc?: unknown; msg?: unknown };
        let locSuffix = "";
        if (Array.isArray(o.loc) && o.loc.length) {
          const tail = o.loc.slice(1).join(".");
          if (tail) locSuffix = `${tail}: `;
        }
        const msg =
          typeof o.msg === "string" ? o.msg : o.msg !== undefined ? JSON.stringify(o.msg) : JSON.stringify(o);
        return `${locSuffix}${msg}`;
      }
      try {
        return JSON.stringify(item);
      } catch {
        return String(item);
      }
    });
    const joined = parts.filter(Boolean).join("; ");
    return joined || fallback;
  }
  try {
    return JSON.stringify(d);
  } catch {
    return fallback;
  }
}

export async function startAudit(content: string, config?: Record<string, unknown>, auditId?: string): Promise<AuditResult> {
  const response = await fetch(`${API_BASE}/audit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, config, audit_id: auditId }),
  });
  if (!response.ok) throw new Error("Failed to start audit");
  return response.json();
}

export async function getAgents(): Promise<Record<string, AgentConfig>> {
  const response = await fetch(`${API_BASE}/agents`);
  if (!response.ok) throw new Error("Failed to fetch agents");
  return response.json();
}

export async function updateAgent(name: string, payload: Partial<AgentConfig>): Promise<AgentConfig> {
  const response = await fetch(`${API_BASE}/agents/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("Failed to update agent");
  return response.json();
}

export function getExportUrl(): string {
  return `${API_BASE}/logs/export`;
}

export async function testAgent(name: string, content: string): Promise<AuditResult> {
  const response = await fetch(`${API_BASE}/agents/${name}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) throw new Error("Failed to test agent");
  return response.json();
}

export interface KnowledgeListResponse {
  items: Array<Record<string, unknown>>;
  total: number;
  page: number;
  page_size: number;
  had_query?: boolean;
}

/**
 * GET /api/knowledge/rules | /api/knowledge/kb
 * page_size=0 → 服务端一次返回整张表全部条目（后端仍会做长度上限校验）
 */
export async function fetchKnowledgeList(
  bucket: "rules" | "kb",
  opts?: { page?: number; page_size?: number; q?: string },
): Promise<KnowledgeListResponse> {
  const path = bucket === "rules" ? `${API_BASE}/knowledge/rules` : `${API_BASE}/knowledge/kb`;
  const url = new URL(path, window.location.origin);
  const page = opts?.page ?? 1;
  const page_size = opts?.page_size ?? 0;
  url.searchParams.set("page", String(page));
  url.searchParams.set("page_size", String(page_size));
  if (opts?.q?.trim()) url.searchParams.set("q", opts.q.trim());
  const response = await fetch(url.pathname + url.search);
  if (!response.ok) throw new Error("Failed to list knowledge");
  return response.json() as Promise<KnowledgeListResponse>;
}

/** 等价于一次性拉齐（page_size=0），仅返回条目数组便于旧表单使用 */
export async function listKnowledge(bucket: "rules" | "kb", query = ""): Promise<Array<Record<string, unknown>>> {
  const r = await fetchKnowledgeList(bucket, { page: 1, page_size: 0, q: query || undefined });
  return r.items;
}

export async function createKnowledge(bucket: "rules" | "kb", payload: Record<string, unknown>) {
  const response = await fetch(`${API_BASE}/knowledge/item/${bucket}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("Failed to create knowledge");
  return response.json();
}

export async function updateKnowledge(bucket: "rules" | "kb", itemId: string, payload: Record<string, unknown>) {
  const response = await fetch(`${API_BASE}/knowledge/item/${bucket}/${itemId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("Failed to update knowledge");
  return response.json();
}

export async function deleteKnowledge(bucket: "rules" | "kb", itemId: string) {
  const response = await fetch(`${API_BASE}/knowledge/item/${bucket}/${itemId}`, { method: "DELETE" });
  if (!response.ok) throw new Error("Failed to delete knowledge");
  return response.json();
}

export interface BatchDeletePreviewItem {
  id: string;
  content_preview: string;
}

export interface BatchDeleteResponse {
  confirm: boolean;
  total: number;
  can_delete?: number;
  deleted?: number;
  failed?: number;
  not_found: number;
  preview?: BatchDeletePreviewItem[];
  not_found_ids?: string[];
}

export async function batchDeleteKnowledge(
  bucket: "rules" | "kb",
  ids: string[],
  confirm: boolean,
): Promise<BatchDeleteResponse> {
  const path = bucket === "rules" ? `${API_BASE}/knowledge/rules/batch` : `${API_BASE}/knowledge/kb/batch`;
  const response = await fetch(path, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, confirm }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(formatApiErrorDetail(body, "批量删除失败"));
  }
  return body as BatchDeleteResponse;
}

export async function importKnowledge(target: "rules" | "kb", items: Array<Record<string, unknown>>) {
  const response = await fetch(`${API_BASE}/knowledge/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target, items }),
  });
  if (!response.ok) throw new Error("Failed to import knowledge");
  return response.json();
}

export interface ImportPreview {
  file_name: string;
  file_type: string;
  total_rows: number;
  valid_count: number;
  error_count: number;
  headers: string[];
  sample_rows: Array<Record<string, unknown>>;
  errors: Array<{ row: number; error: string; record?: Record<string, unknown> }>;
}

export interface BatchImportResult {
  total_rows: number;
  success_count: number;
  skip_count: number;
  error_count: number;
  errors: Array<{ row?: number; error: string; record?: Record<string, unknown> }>;
  duration_ms: number;
}

export async function previewKnowledgeImport(file: File, collection: "rule_base" | "knowledge_base"): Promise<ImportPreview> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("collection", collection);
  const response = await fetch(`${API_BASE}/knowledge/preview`, { method: "POST", body: fd });
  if (!response.ok) throw new Error("导入预览失败");
  return response.json();
}

export async function batchImportKnowledge(file: File, collection: "rule_base" | "knowledge_base"): Promise<BatchImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("collection", collection);
  const response = await fetch(`${API_BASE}/knowledge/import`, { method: "POST", body: fd });
  if (!response.ok) throw new Error("批量导入失败");
  return response.json();
}

export interface BatchUploadStartResponse {
  progress_id: string;
  total: number;
  message: string;
  poll_url: string;
}

export interface ImportReport {
  success_imported: number;
  skipped_duplicate: number;
  overwrite: number;
  merged_update: number;
  both_kept_added: number;
  failed: number;
}

export interface KnowledgeBatchProgressPayload {
  total: number;
  processed: number;
  success: number;
  failed: number;
  skipped: number;
  status: string;
  errors: Array<{ row?: number; error: string }>;
  /** 规则批量导入完成后的分项统计（知识库大批量可能为空） */
  report?: ImportReport;
  log_tail?: string[];
}

/** 大批量后台写入 + 进度轮询（单机内存进度，重启后失效） */
export async function startKnowledgeBatchUpload(kind: "rules" | "kb", file: File, fileType: string): Promise<BatchUploadStartResponse> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("file_type", fileType);
  if (kind === "rules") {
    throw new Error("规则库已改为「预览→选策略→确认导入」，请使用 previewRulesBatchUpload / confirmRulesBatchUpload");
  }
  const path = `${API_BASE}/knowledge/kb/batch-upload`;
  const response = await fetch(path, { method: "POST", body: fd });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "上传失败"));
  return body as BatchUploadStartResponse;
}

export type RuleDupKind = "new" | "duplicate_exact" | "duplicate_similar";
export type RuleImportStrategyApi = "skip" | "overwrite" | "keep_both" | "merge";

export interface RulesBatchPreviewItem {
  row: number;
  kind: RuleDupKind;
  similarity: number;
  matched_id?: string | null;
  matched_preview?: string | null;
  content_preview?: string;
  severity?: string;
  category?: string;
}

export interface RulesBatchPreviewResponse {
  preview_id: string;
  total_rows: number;
  valid_row_count: number;
  analysis: {
    items: RulesBatchPreviewItem[];
    summary: { new: number; duplicate_exact: number; duplicate_similar: number };
    similarity_threshold: number;
  };
  validation_errors: Array<{ row?: number; error: string }>;
}

export async function previewRulesBatchUpload(file: File, fileType: string): Promise<RulesBatchPreviewResponse> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("file_type", fileType);
  const response = await fetch(`${API_BASE}/knowledge/rules/batch-upload/preview`, { method: "POST", body: fd });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "预览分析失败"));
  return body as RulesBatchPreviewResponse;
}

export async function confirmRulesBatchUpload(previewId: string, strategy: RuleImportStrategyApi): Promise<BatchUploadStartResponse> {
  const response = await fetch(`${API_BASE}/knowledge/rules/batch-upload/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preview_id: previewId, strategy }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "确认导入失败"));
  return body as BatchUploadStartResponse;
}

export async function getKnowledgeBatchProgress(pollUrl: string): Promise<KnowledgeBatchProgressPayload> {
  const response = await fetch(pollUrl);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "获取进度失败"));
  return body as KnowledgeBatchProgressPayload;
}

export function getKnowledgeTemplateUrl(collection: "rule_base" | "knowledge_base", format: "csv" | "json" = "csv"): string {
  return `${API_BASE}/knowledge/template?collection=${collection}&format=${format}`;
}

export function getCaseTemplateUrl(format: "csv" | "json" = "csv"): string {
  return `${API_BASE}/cases/template?format=${format}`;
}

export async function listModelConfigs(): Promise<ModelConfig[]> {
  const response = await fetch(`${API_BASE}/model-configs`);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "获取模型配置失败"));
  return body as ModelConfig[];
}

export async function createModelConfig(payload: ModelConfig): Promise<ModelConfig> {
  const response = await fetch(`${API_BASE}/model-configs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "创建模型配置失败"));
  return body as ModelConfig;
}

export async function updateModelConfig(id: string, payload: ModelConfig): Promise<ModelConfig> {
  const response = await fetch(`${API_BASE}/model-configs/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error("更新模型配置失败");
  return response.json();
}

export async function deleteModelConfig(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/model-configs/${id}`, { method: "DELETE" });
  if (!response.ok) throw new Error("删除模型配置失败");
}

export async function testModelConfig(id: string): Promise<TestConnectionResult> {
  const response = await fetch(`${API_BASE}/model-configs/${id}/test`, { method: "POST" });
  if (!response.ok) throw new Error("测试连通性失败");
  return response.json();
}

export async function setDefaultModelConfig(id: string): Promise<ModelConfig> {
  const response = await fetch(`${API_BASE}/model-configs/${id}/default`, { method: "POST" });
  if (!response.ok) throw new Error("设置默认配置失败");
  return response.json();
}

export interface CaseItem {
  id: string;
  text: string;
  verdict: "violation" | "normal";
  violation_reason: string;
  category: string;
  confidence: number;
  matched_rules: string[];
  source: string;
  created_at?: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
}

interface CasesListResponse {
  success: boolean;
  data: CaseItem[];
  total: number;
}

interface CaseSingleResponse {
  success: boolean;
  data: CaseItem;
}

export async function listCases(params?: { category?: string; verdict?: string }): Promise<CaseItem[]> {
  const url = new URL(`${API_BASE}/cases`, window.location.origin);
  if (params?.category?.trim()) url.searchParams.set("category", params.category.trim());
  if (params?.verdict?.trim()) url.searchParams.set("verdict", params.verdict.trim());
  const response = await fetch(url.pathname + url.search);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "获取判例列表失败"));
  return (body as CasesListResponse).data || [];
}

export async function createCase(payload: CaseItem): Promise<CaseItem> {
  const response = await fetch(`${API_BASE}/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "创建判例失败"));
  return (body as CaseSingleResponse).data;
}

export async function updateCase(caseId: string, updates: Partial<CaseItem>): Promise<CaseItem> {
  const response = await fetch(`${API_BASE}/cases/${caseId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "更新判例失败"));
  return (body as CaseSingleResponse).data;
}

export async function deleteCase(caseId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/cases/${caseId}`, { method: "DELETE" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "删除判例失败"));
}

export async function importCases(file: File): Promise<{ success: number; failed: number; errors: string[] }> {
  const fd = new FormData();
  fd.append("file", file);
  const response = await fetch(`${API_BASE}/cases/import`, {
    method: "POST",
    body: fd,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "导入判例失败"));
  return (body as { data?: { success: number; failed: number; errors: string[] } }).data || {
    success: 0,
    failed: 0,
    errors: [],
  };
}

export async function previewCasesImport(file: File): Promise<{ success: boolean; data: { preview: Array<Record<string, unknown>>; total: number } }> {
  const fd = new FormData();
  fd.append("file", file);
  const response = await fetch(`${API_BASE}/cases/import-preview`, {
    method: "POST",
    body: fd,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(formatApiErrorDetail(body, "预览判例导入失败"));
  return body as { success: boolean; data: { preview: Array<Record<string, unknown>>; total: number } };
}
