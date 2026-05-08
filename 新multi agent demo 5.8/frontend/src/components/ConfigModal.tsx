import { useEffect, useState } from "react";

import { listModelConfigs } from "../services/api";
import type { AgentConfig, ModelConfig } from "../types/audit";

interface Props {
  open: boolean;
  agents: Record<string, AgentConfig>;
  selectedModelConfigId: string;
  onClose: () => void;
  onSaveAuditConfig: (config: { model_config_id: string; temperature: number }) => void;
  onSave: (name: string, cfg: Partial<AgentConfig>) => Promise<void>;
}

export function ConfigModal({ open, agents, selectedModelConfigId, onClose, onSaveAuditConfig, onSave }: Props) {
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>([]);
  const [modelConfigId, setModelConfigId] = useState("");
  const [temperature, setTemperature] = useState(0.2);
  const [localAgents, setLocalAgents] = useState<Record<string, AgentConfig>>({});

  useEffect(() => {
    setLocalAgents(agents);
    setModelConfigId(selectedModelConfigId);
  }, [agents, selectedModelConfigId]);
  useEffect(() => {
    listModelConfigs().then(setModelConfigs).catch(() => setModelConfigs([]));
  }, []);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/20 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-slate-900">审核配置</h3>
          <p className="mt-1 text-sm text-slate-500">选择模型配置并控制各 Agent 是否启用。</p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="md:col-span-2 space-y-1">
            <span className="text-xs font-medium text-slate-600">模型配置</span>
            <select
              className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-4 focus:ring-blue-100"
              value={modelConfigId}
              onChange={(e) => setModelConfigId(e.target.value)}
            >
              <option value="">选择审核使用的模型配置</option>
              {modelConfigs
                .filter((cfg) => cfg.enabled)
                .map((cfg) => (
                  <option key={cfg.id} value={cfg.id}>
                    {cfg.name} / {cfg.small_model} / {cfg.strong_model}
                  </option>
                ))}
            </select>
          </label>

          <label className="md:col-span-2 space-y-2">
            <div className="flex items-center justify-between text-xs font-medium text-slate-600">
              <span>Temperature</span>
              <span className="text-slate-500">{temperature.toFixed(1)}</span>
            </div>
            <input
              className="w-full accent-blue-600"
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
            />
          </label>
        </div>

        <div className="mt-5 space-y-2">
          <div className="text-xs font-medium text-slate-600">Agent 启用状态</div>
          {Object.entries(localAgents).map(([name, cfg]) => (
            <label key={name} className="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
              <span className="text-slate-700">{name}</span>
              <input
                type="checkbox"
                checked={Boolean(cfg.enabled)}
                onChange={(e) => {
                  const enabled = e.target.checked;
                  setLocalAgents((prev) => ({ ...prev, [name]: { ...prev[name], enabled } }));
                }}
              />
            </label>
          ))}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50" onClick={onClose}>
            取消
          </button>
          <button
            className="rounded-xl bg-blue-600 px-4 py-2 text-sm text-white transition hover:bg-blue-500"
            onClick={async () => {
              onSaveAuditConfig({ model_config_id: modelConfigId, temperature });
              for (const [name, cfg] of Object.entries(localAgents)) {
                await onSave(name, cfg);
              }
              onClose();
            }}
          >
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
