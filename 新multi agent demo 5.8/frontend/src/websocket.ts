import type { BlackboardEntry } from "../types/audit";

export function connectAuditStream(
  auditId: string,
  onMessage: (entry: BlackboardEntry) => void,
  onClose?: () => void,
): WebSocket {
  const apiBase = import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "";
  const apiUrl = apiBase.startsWith("http") ? new URL(apiBase) : new URL(apiBase || "/", window.location.origin);
  const protocol = apiUrl.protocol === "https:" ? "wss" : "ws";
  const host = apiUrl.host || window.location.host;
  const ws = new WebSocket(`${protocol}://${host}/ws/audit/${auditId}`);
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data) as BlackboardEntry);
    } catch {
      // no-op
    }
  };
  ws.onclose = () => onClose?.();
  return ws;
}
