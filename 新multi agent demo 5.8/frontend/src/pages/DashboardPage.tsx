import { Link } from "react-router-dom";
import { Activity, Bot, BrainCircuit, ShieldCheck, Sparkles, Workflow } from "lucide-react";

const featureCards = [
  {
    icon: Workflow,
    title: "黑板共享",
    description: "所有 Agent 共享观察、消息与中间结果，协同推进判断。",
  },
  {
    icon: BrainCircuit,
    title: "多模型集群",
    description: "小/中/大模型按任务复杂度自主路由，兼顾成本与准确率。",
  },
  {
    icon: ShieldCheck,
    title: "冲突仲裁",
    description: "评估员自动检测冲突，必要时触发大法官终审裁决。",
  },
  {
    icon: Sparkles,
    title: "记忆持久化",
    description: "Agent 被 @ 后继续基于历史记忆增量推理，而不是从头开始。",
  },
];

export function DashboardPage() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="absolute inset-x-0 top-0 -z-10 h-[360px] bg-[radial-gradient(circle_at_top,rgba(59,130,246,0.14),transparent_65%)]" />
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
        <section className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-xl shadow-slate-200/60 backdrop-blur">
          <div className="grid gap-6 p-6 lg:grid-cols-[1.3fr_0.7fr] lg:p-8">
            <div className="space-y-5">
              <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
                <Activity className="h-4 w-4" />
                Multi-Agent 合规审核工作台
              </div>
              <div className="space-y-3">
                <h1 className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
                  让 Agent 集群协同思考，
                  <span className="bg-gradient-to-r from-blue-600 to-cyan-600 bg-clip-text text-transparent">完成更稳健的审核决策</span>
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-slate-600 sm:text-base">
                  黑板共享、消息 @、持久化记忆、冲突评估与终审仲裁，全流程在一个页面里可视化。
                  这里是系统入口与总览页，适合快速理解整个 Multi-Agent 审核体系。
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Link to="/audit" className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-500">
                  进入审核界面
                </Link>
                <Link to="/batch" className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 transition hover:bg-slate-50">
                  打开批量审核
                </Link>
                <Link to="/model-config" className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm font-semibold text-sky-700 transition hover:bg-sky-100">
                  去配置模型
                </Link>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
              {[
                { label: "运行模式", value: "单次审核", icon: Workflow },
                { label: "Agent 状态", value: "待命", icon: Bot },
                { label: "推理轨迹", value: "尚未开始", icon: BrainCircuit },
                { label: "终审结果", value: "未出结果", icon: ShieldCheck },
              ].map((item) => (
                <div key={item.label} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <item.icon className="h-4 w-4 text-blue-500" />
                    {item.label}
                  </div>
                  <div className="mt-2 text-lg font-semibold text-slate-900">{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {featureCards.map((card) => (
            <div key={card.title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <card.icon className="h-5 w-5 text-blue-500" />
              <h3 className="mt-3 text-base font-semibold text-slate-900">{card.title}</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">{card.description}</p>
            </div>
          ))}
        </section>

        <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
          <aside className="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-3 text-sm font-semibold text-slate-900">快速入口</div>
            <nav className="space-y-2 text-sm">
              <Link className="block rounded-xl bg-blue-600 px-4 py-2.5 font-medium text-white" to="/audit">
                单次审核
              </Link>
              <Link className="block rounded-xl border border-slate-200 bg-white px-4 py-2.5 font-medium text-slate-700 hover:bg-slate-50" to="/audit?tab=batch">
                批量审核
              </Link>
              <Link className="block rounded-xl border border-slate-200 bg-white px-4 py-2.5 font-medium text-slate-700 hover:bg-slate-50" to="/knowledge">
                知识库管理
              </Link>
              <Link className="block rounded-xl border border-slate-200 bg-white px-4 py-2.5 font-medium text-slate-700 hover:bg-slate-50" to="/cases">
                判例库管理
              </Link>
              <Link className="block rounded-xl border border-slate-200 bg-white px-4 py-2.5 font-medium text-slate-700 hover:bg-slate-50" to="/agents">
                Agent 配置
              </Link>
            </nav>
          </aside>

          <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">这是一个独立的总览界面</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              你可以把它作为系统首页，审核功能放到单独的 `/audit` 页面。
              这样“看整体”和“做审核”就分开了，结构更清晰，也更适合演示给别人看。
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
