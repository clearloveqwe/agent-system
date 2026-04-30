# Agent System — 多 Agent 全栈 Web 开发系统

> 输入自然语言需求，自动完成前后端代码生成、数据库设计、测试、联调、压力测试，最终生成可发布 PR。

## 架构概览

```
┌──────────────┐
│  Orchestrator│ ← 接收需求 → 拆解 → 分发
└──────┬───────┘
       │
┌──────┴───────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐
│  Frontend   │  │  Backend  │  │   DB     │  │   QA    │
│   Agent     │  │   Agent   │  │  Agent   │  │  Agent   │
└─────────────┘  └───────────┘  └──────────┘  └──────────┘
       └───────────────┴──────────────┴──────────────┘
                        │
                   Sandbox (E2B/Docker)
                        │
                    GitHub PR ─── CI/CD
```

## 探讨式规划（核心特性）

在进入自动开发之前，系统会先与你进行一轮**架构设计讨论**，让你在代码生成前就能审视和调整方案。

### 工作流程

```
你: "写一个 Todo App"
  │
  ▼
┌──────────────────────────────────────────────┐
│ plan_draft(requirement)                       │
│                                               │
│  LLM（DeepSeek V4 Flash + reasoning_effort）  │
│   → 输出 1 个主方案 + 1-2 个备选方案          │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
          📋 Architecture Draft (v1)
          ├── Summary: FastAPI + React
          ├── backend/main.py
          ├── frontend/App.jsx
          ├── tests/test_api.py
          ├── Option 2: Flask + Jinja (SSR)
          ├── Option 3: Express + React
          │
          * 回复反馈来调整，或发送 confirm 继续 *

你: "用 SQLite 替代 PostgreSQL，去掉 Docker"
  │
  ▼
┌──────────────────────────────────────────────┐
│ plan_refine(draft, feedback)                  │
│                                               │
│  LLM 在当前方案 + 历史讨论 + 你的反馈上        │
│  生成更新后的方案                              │
└────────────────────┬─────────────────────────┘
                     │
                     ▼
          📋 Architecture Draft (v2)
          ├── ... 已根据反馈调整 ...

你: "confirm"（或 "确认" / "proceed"）
  │
  ▼
┌──────────────────────────────────────────────┐
│ run_with_plan(confirmed_plan)                 │
│                                               │
│ 跳过规划阶段，直接进入：                       │
│  CodeAgent 生成 → Sandbox 测试 → KB 存储     │
└──────────────────────────────────────────────┘
```

### API 说明

```python
# 1. 生成初始草案（含备选方案）
draft = await orchestrator.plan_draft("写一个 Python 计算器")
print(draft.present())  # 渲染为可读 Markdown

# 2. 根据反馈精炼（可多次迭代）
draft = await orchestrator.plan_refine(draft, "加一个 CLI 界面")
draft = await orchestrator.plan_refine(draft, "改用 Click 库")

# 3. 确认后执行
result = await orchestrator.run_with_plan(draft.plan)
```

### 核心模型

| 模型 | 字段 | 说明 |
|------|------|------|
| **PlanDraft** | `plan` `alternatives` `discussion` `confirmed` `iteration` | 承载一整个讨论过程 |
| **ProjectPlan** | `summary` `files[]` `test_strategy` | 单个架构方案（Pydantic 校验） |
| **FileSpec** | `path` `language` `purpose` `dependencies[]` | 单个文件定义 |
| **PipelineResult** | `success` `files[]` `pipeline_test` `kb_stored` | 全链路执行结果 |

### 技术细节

- **输出约束：** `ProjectPlan.model_json_schema()` 生成 JSON Schema → `response_format: json_schema` 传入 LLM API
- **自动校验：** LLM 输出 → `ProjectPlan.model_validate_json()` → 失败时自动重试（最多 2 次修正）
- **讨论保留：** `PlanDraft.discussion` 累积完整对话历史，每轮迭代 `iteration` +1
- **Pydantic 全链路：** PipelineFileResult、PipelineResult 等均为 Pydantic BaseModel，支持 `model_dump()` 序列化

## 阶段路线

| 阶段 | 内容 | 预计周期 |
|------|------|----------|
| 一 | 单 Agent 闭环 | 4-6 周 |
| 二-三 | 多 Agent 协同 | 8-12 周 |
| 四 | 人工节点与生产化 | 6-8 周 |

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env
# 编辑 .env 填入 DeepSeek 和 MiniMax API Key

# 3. 运行测试
ruff check src/ tests/ && pytest

# 4. 在代码中使用
from src.orchestrator.orchestrator import Orchestrator

orchestrator = Orchestrator()

# 探讨式规划
draft = await orchestrator.plan_draft("写一个计算器")
print(draft.present())
draft = await orchestrator.plan_refine(draft, "加 CLI 界面")
result = await orchestrator.run_with_plan(draft.plan)
```

## 开发工作流

提交代码前必须执行以下两步，否则 CI 会拦截：

```bash
# 1. Lint 检查（必须 0 errors）
ruff check src/ tests/

# 2. 单元测试（必须全部通过）
pytest
```

**常见 lint 陷阱：**
- `__init__.py` 的导出必须加 `as` 别名，否则 ruff F401 报错
  ```python
  # ❌ 错误
  from .code_agent import CodeAgent
  # ✅ 正确
  from .code_agent import CodeAgent as CodeAgent
  ```
- 不要留"防御性导入"（先导入、后不用）— 用完立即删除
- `ruff check --fix` 可自动修复约 30% 的简单问题，复杂问题需手动处理

> 完整规范见 `AGENTS.md`（Agent 行为约束）和 `execution_log.md`（问题追溯）。

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| **LLM 规划** | DeepSeek V4 Flash | 复杂架构推理，thinking mode |
| **LLM 生成** | MiniMax M2.7 | 代码生成、测试生成 |
| **沙箱** | E2B 云沙箱 / Docker 本地 | 隔离代码执行 |
| **知识库** | Chroma / JSON 文件 | 经验存储与检索 |
| **CI/CD** | GitHub Actions | ruff lint + pytest + 安全门禁 |
| **数据模型** | Pydantic 2 | 结构化输出、JSON Schema、自动校验 |
| **HTTP 客户端** | httpx | 异步 LLM API 调用 |
