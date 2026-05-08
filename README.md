# 新 multi agent demo 5.8

这是从原项目中整理出来的新版多 Agent 内容审核项目包，按前端、后端、共享审核引擎分目录放置，便于单独查看、启动和后续继续整理。

## 目录结构

```text
新multi agent demo 5.8/
  frontend/        # 新版前端页面与组件
  backend/         # 新版后端 API、Agent、Core、Services
  audit_system/    # 共享审核引擎与提示词
  app.py           # 旧入口/兼容入口
  streamlit_app.py # 旧入口/兼容入口
  requirements.txt # Python 依赖
  work_units_config.yaml
  README.md
```

## 当前已整理的内容

### 前端
- 审核页 `AuditPage`
- 首页 `DashboardPage`
- 知识库管理页 `KnowledgePage`
- 判例库管理页 `CasePage`
- 模型配置页 `ModelConfigPage`
- 审核主流程组件、黑板视图、日志流、批量审核、配置弹窗等

### 后端
- 审核主入口 `backend/app/main.py`
- Agent：文本清洗、规则执行、对抗侦探、判例执行、置信度评估、大法官
- Core：黑板、Agent 基类、配置管理、聚合器
- Routers：批量审核、知识库批量导入、批量删除
- API：判例库管理
- Services：向量库、知识库、判例、LLM、审核流水线

### 共享审核引擎
- `audit_system/` 下的多 Agent 审核核心、提示词与网页入口

## 关于知识库 / 规则库数据

页面手动导入的规则库、知识库数据，代码里对应的是后端的持久化向量库，理论上会落到：

```text
backend/data/chroma/
backend/data/config.json
backend/data/model_configs.json
backend/data/agent_configs.json
```

目前在当前工作区里还没有找到这些实际数据文件，所以如果要迁移历史导入内容，需要把这些持久化数据一并找到并复制进来。

## 启动前建议

1. 安装依赖
2. 先启动后端，再启动前端
3. 确认前端代理或环境变量指向新的后端地址

## 备注

这个文件夹的目标是作为“新架构整理包”，后续可以继续在这里补充：
- 数据迁移
- 启动脚本
- 环境变量说明
- 打包部署说明
