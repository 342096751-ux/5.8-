from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from app.models.audit import BlackboardEntry


class Blackboard:
    """Central state manager with per-audit sessions and websocket streaming."""

    def __init__(self) -> None:
        self._logs_by_audit: dict[str, list[BlackboardEntry]] = {}
        self._state_by_audit: dict[str, dict[str, Any]] = {}
        self._ws_by_audit: dict[str, list[WebSocket]] = {}
        self._agent_results_by_audit: dict[str, dict[str, dict[str, Any]]] = {}
        self._agent_status_by_audit: dict[str, dict[str, str]] = {}
        self._completion_events_by_audit: dict[str, dict[str, asyncio.Event]] = {}

    def _ensure(self, audit_id: str) -> None:
        self._logs_by_audit.setdefault(audit_id, [])
        self._state_by_audit.setdefault(audit_id, {})
        self._ws_by_audit.setdefault(audit_id, [])
        self._agent_results_by_audit.setdefault(audit_id, {})
        self._agent_status_by_audit.setdefault(audit_id, {})
        self._completion_events_by_audit.setdefault(audit_id, {})

    async def connect(self, audit_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._ensure(audit_id)
        self._ws_by_audit[audit_id].append(websocket)

    def disconnect(self, audit_id: str, websocket: WebSocket) -> None:
        sockets = self._ws_by_audit.get(audit_id, [])
        if websocket in sockets:
            sockets.remove(websocket)

    async def write_entry(
        self,
        audit_id: str,
        agent: str,
        zone: str,
        phase: str,
        content: str,
        data: dict[str, Any] | None = None,
        raw_llm_output: str | None = None,
    ) -> BlackboardEntry:
        self._ensure(audit_id)
        entry = BlackboardEntry(
            timestamp=f"{datetime.utcnow().isoformat()}Z",
            agent=agent,
            zone=zone,
            phase=phase,
            content=content,
            data=data or {},
            raw_llm_output=raw_llm_output,
        )
        self._logs_by_audit[audit_id].append(entry)
        await self.broadcast(audit_id, entry)
        return entry

    async def broadcast(self, audit_id: str, entry: BlackboardEntry) -> None:
        sockets = self._ws_by_audit.get(audit_id, [])
        if not sockets:
            return
        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(entry.model_dump(mode="json"))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(audit_id, ws)

    def get_logs(self, audit_id: str) -> list[BlackboardEntry]:
        self._ensure(audit_id)
        return list(self._logs_by_audit[audit_id])

    def set_state(self, audit_id: str, key: str, value: Any) -> None:
        self._ensure(audit_id)
        self._state_by_audit[audit_id][key] = value

    def get_state(self, audit_id: str, key: str, default: Any = None) -> Any:
        self._ensure(audit_id)
        return self._state_by_audit[audit_id].get(key, default)

    def get_all_logs(self) -> dict[str, list[BlackboardEntry]]:
        return {k: list(v) for k, v in self._logs_by_audit.items()}

    def set_agent_status(self, audit_id: str, agent: str, status: str) -> None:
        self._ensure(audit_id)
        self._agent_status_by_audit[audit_id][agent] = status
        if status == "running":
            self._completion_events_by_audit[audit_id][agent] = asyncio.Event()
        elif status in {"completed", "skipped"}:
            event = self._completion_events_by_audit[audit_id].setdefault(
                agent, asyncio.Event()
            )
            event.set()

    def set_agent_result(self, audit_id: str, agent: str, result: dict[str, Any]) -> None:
        self._ensure(audit_id)
        self._agent_results_by_audit[audit_id][agent] = result
        verdict = result.get("verdict")
        if verdict in {None, "not_participate", "not_participating"}:
            self.set_agent_status(audit_id, agent, "skipped")
        else:
            self.set_agent_status(audit_id, agent, "completed")

    async def update_agent_result(
        self,
        audit_id: str,
        agent: str,
        result: dict[str, Any],
        *,
        zone: str = "orchestrator",
        phase: str = "agent_result_update",
        reason: str = "",
    ) -> None:
        """
        更新 Agent 结果（支持“新票面覆盖旧票面”，但会把旧票面归档进 entries）。

        - agent_results 中永远保留最新版
        - logs 中会追加 archived + updated 两条记录，便于前端展示 v1/v2 演进
        """
        self._ensure(audit_id)
        old = self._agent_results_by_audit[audit_id].get(agent)
        if isinstance(old, dict) and old:
            await self.write_entry(
                audit_id=audit_id,
                agent=agent,
                zone=zone,
                phase=f"{phase}_history",
                content="archived",
                data={"reason": reason, "archived": old},
            )
        self.set_agent_result(audit_id, agent, result)
        await self.write_entry(
            audit_id=audit_id,
            agent=agent,
            zone=zone,
            phase=phase,
            content="updated",
            data={"reason": reason, "result": result},
        )

    def get_agent_results(self, audit_id: str) -> dict[str, dict[str, Any]]:
        self._ensure(audit_id)
        return dict(self._agent_results_by_audit[audit_id])

    def get_agent_status(self, audit_id: str) -> dict[str, str]:
        self._ensure(audit_id)
        return dict(self._agent_status_by_audit[audit_id])

    async def wait_for_agents(
        self, audit_id: str, agents: list[str], timeout: float = 60.0
    ) -> None:
        self._ensure(audit_id)
        tasks = []
        for agent in agents:
            event = self._completion_events_by_audit[audit_id].setdefault(
                agent, asyncio.Event()
            )
            tasks.append(asyncio.wait_for(event.wait(), timeout=timeout))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_active_results(self, audit_id: str) -> dict[str, dict[str, Any]]:
        self._ensure(audit_id)
        results: dict[str, dict[str, Any]] = {}
        for agent, result in self._agent_results_by_audit[audit_id].items():
            verdict = result.get("verdict")
            if verdict not in {None, "not_participate", "not_participating"}:
                results[agent] = result
        return results

    def has_conflict(self, audit_id: str) -> bool:
        verdicts: set[str] = set()
        for result in self.get_active_results(audit_id).values():
            verdict = str(result.get("verdict"))
            if verdict:
                verdicts.add(verdict)
        return len(verdicts) > 1

    def has_uncertainty(self, audit_id: str) -> bool:
        for result in self.get_active_results(audit_id).values():
            if result.get("verdict") in {"uncertain", "不确定"}:
                return True
        return False

    def discard_audit(self, audit_id: str) -> None:
        """删除某次审核在黑板上的状态与日志，用于批量完成后释放内存。"""
        self._logs_by_audit.pop(audit_id, None)
        self._state_by_audit.pop(audit_id, None)
        self._ws_by_audit.pop(audit_id, None)
        self._agent_results_by_audit.pop(audit_id, None)
        self._agent_status_by_audit.pop(audit_id, None)
        self._completion_events_by_audit.pop(audit_id, None)

    def list_audit_ids_by_recency(self, limit: int = 50, offset: int = 0) -> list[str]:
        scored: list[tuple[str, str]] = []
        for aid, entries in self._logs_by_audit.items():
            if not entries:
                continue
            ts = max(e.timestamp for e in entries)
            scored.append((ts, aid))
        scored.sort(key=lambda x: x[0], reverse=True)
        ids = [a for _, a in scored]
        return ids[offset : offset + limit]

    def audit_summary(self, audit_id: str) -> dict[str, Any]:
        logs = self.get_logs(audit_id)
        content = self.get_state(audit_id, "content", "") or ""
        final_verdict = self.get_state(audit_id, "final_verdict", "") or ""
        ts = logs[0].timestamp if logs else ""
        agents = {e.agent for e in logs}
        return {
            "audit_id": audit_id,
            "timestamp": ts,
            "content_preview": content[:160] if content else "",
            "final_result": final_verdict,
            "agent_count": len(agents),
            "step_count": len(logs),
        }

