import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";

import { AgentsPage } from "./pages/AgentsPage";
import { AuditPage } from "./pages/AuditPage";
import { CasePage } from "./pages/CasePage";
import { DashboardPage } from "./pages/DashboardPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { ModelConfigPage } from "./pages/ModelConfigPage";
import "./style.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <div className="min-h-screen bg-slate-100">
        <header className="border-b bg-white">
          <div className="mx-auto flex max-w-6xl items-center gap-4 p-4 text-sm">
            <Link to="/" className="font-semibold text-slate-800">首页</Link>
            <Link to="/audit" className="text-slate-600 hover:text-slate-900">审核</Link>
            <Link to="/knowledge" className="text-slate-600 hover:text-slate-900">知识库管理</Link>
            <Link to="/cases" className="text-slate-600 hover:text-slate-900">判例库管理</Link>
            <Link to="/agents" className="text-slate-600 hover:text-slate-900">Agent配置</Link>
            <Link to="/model-config" className="text-slate-600 hover:text-slate-900">模型配置</Link>
          </div>
        </header>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/cases" element={<CasePage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/model-config" element={<ModelConfigPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </BrowserRouter>
  </React.StrictMode>,
);
