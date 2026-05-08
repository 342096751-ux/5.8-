export interface BlackboardEntry {
  timestamp: string;
  agent: string;
  zone: string;
  phase: string;
  content: string;
  data?: {
    verdict?: string;
    confidence?: number;
    reason?: string;
    [key: string]: unknown;
  };
  raw_llm_output?: string;
}

export interface AuditResult {
  audit_id: string;
  content: string;
  final_verdict: "violation" | "normal" | "review" | "reject" | "pass";
  confidence: number;
  logs: BlackboardEntry[];
  agent_results: Record<string, unknown>;
}

export interface AgentConfig {
  enabled: boolean;
  zone?: string;
  temperature?: number;
  [key: string]: unknown;
}

export type ModelProvider = "openai" | "deepseek" | "moonshot" | "zhipu" | "qwen" | "custom";

export interface ModelConfig {
  id: string;
  name: string;
  provider: ModelProvider;
  api_key: string;
  base_url: string;
  small_model: string;
  strong_model: string;
  embedding_model: string;
  is_default: boolean;
  enabled: boolean;
}

export interface TestConnectionResult {
  success: boolean;
  message: string;
  models_available: string[];
}
