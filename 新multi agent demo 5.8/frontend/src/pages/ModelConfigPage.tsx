import { useEffect, useState } from "react";

import {
  createModelConfig,
  deleteModelConfig,
  listModelConfigs,
  setDefaultModelConfig,
  testModelConfig,
  updateModelConfig,
} from "../services/api";
import type { ModelConfig, ModelProvider } from "../types/audit";

const providerOptions: Array<{ value: ModelProvider; label: string; base: string }> = [
  { value: "openai", label: "OpenAI", base: "https://api.openai.com/v1" },
  { value: "deepseek", label: "DeepSeek", base: "https://api.deepseek.com/v1" },
  { value: "moonshot", label: "Moonshot", base: "https://api.moonshot.cn/v1" },
  { value: "zhipu", label: "Zhipu", base: "https://open.bigmodel.cn/api/paas/v4" },
  {
    value: "qwen",
    label: "通义/Qwen(DashScope)",
    base: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  },
  { value: "custom", label: "自定义", base: "" },
];

const emptyConfig = (): ModelConfig => ({
  id: crypto.randomUUID(),
  name: "新配置",
  provider: "openai",
  api_key: "",
  base_url: "https://api.openai.com/v1",
  small_model: "gpt-3.5-turbo",
  strong_model: "gpt-4o",
  embedding_model: "text-embedding-3-small",
  is_default: false,
  enabled: true,
});

const providerTemplates: Record<
  ModelProvider,
  { base_url: string; small_model: string; strong_model: string; embedding_model: string; name: string }
> = {
  openai: {
    name: "OpenAI-主账号",
    base_url: "https://api.openai.com/v1",
    small_model: "gpt-4o-mini",
    strong_model: "gpt-4o",
    embedding_model: "text-embedding-3-small",
  },
  deepseek: {
    name: "DeepSeek-备用",
    base_url: "https://api.deepseek.com/v1",
    small_model: "deepseek-chat",
    strong_model: "deepseek-chat",
    embedding_model: "text-embedding-3-small",
  },
  moonshot: {
    name: "Moonshot-默认",
    base_url: "https://api.moonshot.cn/v1",
    small_model: "moonshot-v1-8k",
    strong_model: "moonshot-v1-128k",
    embedding_model: "text-embedding-3-small",
  },
  zhipu: {
    name: "Zhipu-默认",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    small_model: "glm-4-flash",
    strong_model: "glm-4-plus",
    embedding_model: "text-embedding-3-small",
  },
  qwen: {
    name: "通义DashScope-北京兼容",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    small_model: "qwen-turbo",
    strong_model: "qwen-plus",
    embedding_model: "text-embedding-v4",
  },
  custom: {
    name: "自定义-OpenAI兼容",
    base_url: "",
    small_model: "custom-small",
    strong_model: "custom-strong",
    embedding_model: "custom-embedding",
  },
};

export function ModelConfigPage() {
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  const refresh = async () => {
    setListError(null);
    try {
      setConfigs(await listModelConfigs());
    } catch (e) {
      setListError(e instanceof Error ? e.message : "加载失败");
      setConfigs([]);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);

  const applyTemplate = (id: string, provider: ModelProvider) => {
    const template = providerTemplates[provider];
    setConfigs((prev) =>
      prev.map((x) =>
        x.id === id
          ? {
              ...x,
              provider,
              name: x.name || template.name,
              base_url: template.base_url,
              small_model: template.small_model,
              strong_model: template.strong_model,
              embedding_model: template.embedding_model,
            }
          : x,
      ),
    );
  };

  const applyJuguangTemplate = (id: string) => {
    setConfigs((prev) =>
      prev.map((x) =>
        x.id === id
          ? {
              ...x,
              provider: "custom" as ModelProvider,
              name: x.name?.trim() || "聚光 API（OpenAI兼容）",
              base_url: "",
              small_model: x.small_model || "gpt-4o-mini",
              strong_model: x.strong_model || "gpt-4o",
            }
          : x,
      ),
    );
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <h2 className="text-xl font-semibold text-slate-800">模型 API 配置（填一次即可调用大模型）</h2>
      <div className="rounded-lg border border-amber-200 bg-amber-50/90 p-4 text-sm leading-relaxed text-amber-950">
        <p className="font-medium">不会配？按下面任选一种方式：</p>
        <ol className="mt-2 list-decimal space-y-2 pl-5">
          <li>
            <span className="font-medium">方式 A（推荐，改文件即可）</span>：在项目根目录的{" "}
            <code className="rounded bg-white px-1 py-0.5 text-xs ring-1 ring-amber-200">.env</code> 里增加两行（把值换成聚光控制台给你的）：
            <pre className="mt-1 overflow-x-auto rounded bg-white p-2 text-xs ring-1 ring-amber-100">
              {`JUGUANG_API_KEY=sk-你的密钥
JUGUANG_BASE_URL=https://聚光文档里的接口根地址/v1`}
            </pre>
            保存后<span className="font-medium">重启后端</span>。可同时设置 <code className="text-xs">LLM_SMALL_MODEL</code>{" "}
            / <code className="text-xs">LLM_STRONG_MODEL</code> 为文档里的模型名。
          </li>
          <li>
            <span className="font-medium">方式 B（本页填写）</span>：在下面某一条配置里，「供应商」选「自定义」，把{" "}
            <span className="font-medium">接口地址（Base URL）</span> 和 <span className="font-medium">密钥 sk</span>{" "}
            粘进去，模型名按聚光文档填写，点「保存」再点「设为默认」。
          </li>
        </ol>
        <p className="mt-2 text-xs text-amber-900/80">
          说明：Base URL 一般类似 <code className="rounded bg-white px-1">https://xxx.com/v1</code>，末尾不要多写{" "}
          <code className="rounded bg-white px-1">/chat/completions</code>。
        </p>
      </div>
      <p className="text-xs text-slate-500">
        网页里保存的配置在 <code className="rounded bg-slate-100 px-1">backend/data/model_configs.json</code>
        。若同时配置了 .env 里的 <code className="rounded bg-slate-100 px-1">JUGUANG_*</code>/<code className="rounded bg-slate-100 px-1">LLM_*</code>
        ，运行时以<span className="font-medium">环境变量为准</span>合并到默认配置上。
      </p>
      {listError && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          加载失败：{listError}（请确认已启动后端且本页通过开发代理访问 /api）
        </div>
      )}
      <div className="flex gap-2">
        <button
          className="rounded bg-blue-600 px-3 py-2 text-sm text-white"
          onClick={async () => {
            const cfg = emptyConfig();
            try {
              await createModelConfig(cfg);
              await refresh();
            } catch (e) {
              window.alert(e instanceof Error ? e.message : "创建失败");
            }
          }}
        >
          添加配置
        </button>
      </div>
      <div className="space-y-3">
        {configs.map((cfg) => (
          <div key={cfg.id} className="rounded-xl bg-white p-4 ring-1 ring-slate-200">
            <div className="grid gap-2 md:grid-cols-2">
              <div className="md:col-span-2 flex items-center gap-2">
                <span className="text-sm text-slate-600">一键模板:</span>
                {providerOptions.map((p) => (
                  <button
                    key={`${cfg.id}-${p.value}`}
                    type="button"
                    className="rounded border px-2 py-1 text-xs hover:bg-slate-50"
                    onClick={() => applyTemplate(cfg.id, p.value)}
                  >
                    {p.label}
                  </button>
                ))}
                <button type="button" className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900 hover:bg-amber-100" onClick={() => applyJuguangTemplate(cfg.id)}>
                  聚光：选自定义并清空地址
                </button>
              </div>
              <div className="md:col-span-2 flex flex-col gap-1">
                <span className="text-xs text-slate-500">配置名称</span>
                <input className="rounded border p-2 text-sm" value={cfg.name} placeholder="例如：聚光-主用" onChange={(e) => setConfigs((prev) => prev.map((x) => x.id === cfg.id ? { ...x, name: e.target.value } : x))} />
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-xs text-slate-500">供应商</span>
                <select
                  className="rounded border p-2 text-sm"
                  value={cfg.provider}
                  onChange={(e) => {
                    const nextProvider = e.target.value as ModelProvider;
                    const found = providerOptions.find((x) => x.value === nextProvider);
                    setConfigs((prev) =>
                      prev.map((x) => x.id === cfg.id ? { ...x, provider: nextProvider, base_url: nextProvider === "custom" ? x.base_url : (found?.base ?? x.base_url) } : x),
                    );
                  }}
                >
                  {providerOptions.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-xs text-slate-500">密钥（sk-…）</span>
                <input
                  className="rounded border p-2 text-sm"
                  value={cfg.api_key}
                  placeholder="从聚光控制台复制"
                  autoComplete="off"
                  onChange={(e) => setConfigs((prev) => prev.map((x) => x.id === cfg.id ? { ...x, api_key: e.target.value } : x))}
                />
              </div>
              <div className="md:col-span-2 flex flex-col gap-1">
                <span className="text-xs text-slate-500">接口根地址（Base URL）</span>
                <input
                  className="rounded border p-2 text-sm"
                  value={cfg.base_url}
                  placeholder="https://…/v1（按聚光文档，勿带 /chat/completions）"
                  onChange={(e) => setConfigs((prev) => prev.map((x) => x.id === cfg.id ? { ...x, base_url: e.target.value } : x))}
                />
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-xs text-slate-500">小模型名称</span>
                <input className="rounded border p-2 text-sm" value={cfg.small_model} placeholder="聚光控制台里显示的模型 ID" onChange={(e) => setConfigs((prev) => prev.map((x) => x.id === cfg.id ? { ...x, small_model: e.target.value } : x))} />
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-xs text-slate-500">强模型名称</span>
                <input className="rounded border p-2 text-sm" value={cfg.strong_model} placeholder="一般用更大或同一模型 ID" onChange={(e) => setConfigs((prev) => prev.map((x) => x.id === cfg.id ? { ...x, strong_model: e.target.value } : x))} />
              </div>
              <div className="md:col-span-2 flex flex-col gap-1">
                <span className="text-xs text-slate-500">向量嵌入模型（知识库/Chroma，可后配）</span>
                <input className="rounded border p-2 text-sm" value={cfg.embedding_model} placeholder="Embedding 模型 ID" onChange={(e) => setConfigs((prev) => prev.map((x) => x.id === cfg.id ? { ...x, embedding_model: e.target.value } : x))} />
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={cfg.enabled} onChange={(e) => setConfigs((prev) => prev.map((x) => x.id === cfg.id ? { ...x, enabled: e.target.checked } : x))} />
                启用
              </label>
              <button className="rounded border px-3 py-1.5" onClick={async () => { await setDefaultModelConfig(cfg.id); await refresh(); }}>设为默认</button>
              <button className="rounded border px-3 py-1.5" onClick={async () => { const res = await testModelConfig(cfg.id); window.alert(`${res.message}\n模型数量: ${res.models_available.length}`); }}>测试连通</button>
              <button className="rounded bg-blue-600 px-3 py-1.5 text-white" onClick={async () => { await updateModelConfig(cfg.id, cfg); await refresh(); }}>保存</button>
              <button className="rounded bg-red-600 px-3 py-1.5 text-white" onClick={async () => { if (window.confirm("确认删除该配置?")) { await deleteModelConfig(cfg.id); await refresh(); } }}>删除</button>
              {cfg.is_default && <span className="rounded bg-emerald-100 px-2 py-1 text-emerald-700">默认配置</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
