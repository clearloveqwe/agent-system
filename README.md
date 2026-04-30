# Agent System — 多 Agent 全栈 Web 开发系统

> 输入自然语言需求，自动完成需求澄清、架构设计、代码生成、沙箱测试、自愈修复、经验存储，最终输出可发布的项目。

## 全链路管线

```
用户模糊需求
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: 需求澄清（ClarifySession）                              │
│                                                                   │
│  discuss_llm 多轮对话，每次追问1个问题                             │
│  自动构建 ClarifiedRequirement（结构化需求文档）                   │
│  最多 10 轮 → 强制提交，open_questions 标记未解决项               │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ClarifiedRequirement (Pydantic 校验)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2: 架构讨论（PlanDraft）                                   │
│                                                                   │
│  plan_draft(clarified_req) → 主方案 + 1-2 备选方案               │
│  plan_refine(draft, feedback) → 迭代精炼，历史保留                │
│  用户 confirm → run_with_plan(plan)                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ ProjectPlan (Pydantic 校验)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ Phase 3: 代码执行（Pipeline）                                    │
│                                                                   │
│  CodeAgent 逐一生成 → Sandbox 单文件验证                         │
│  Healing 重试 ×3（失败后带 stderr 重生成）                       │
│  Pipeline 全量测试（pytest 沙箱内）                              │
│  KB 存储成功经验                                                  │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
              PipelineResult { files[], test_results, ... }
```

---

## 完整协作流

### Step 1 — 需求澄清（ClarifySession）

用户说"写一个 Todo 应用"，系统不会直接生成代码，而是先通过多轮对话澄清需求：

```
你: "Build a habit tracker"
  │
  ▼
session = ClarifySession(discuss_llm)

response = await session.ask(current_state)
  │
  ├── action="ask"  → 显示 question 给用户
  │   └── session.record_answer(answer) → 继续
  │
  └── action="submit" → 得到 ClarifiedRequirement
      └── validate_clarified_requirement(req) 校验
```

**示例对话（真实 DeepSeek V4 Flash 调用）：**

| 轮次 | LLM 提问 | 用户回答 |
|------|----------|----------|
| 1 | 目标用户是谁？ | 个人用户，移动端优先 |
| 2 | 核心功能？ | 记录习惯、查看 streak |
| 3 | 技术栈偏好？ | React + Python + SQLite |
| 4 | 约束条件？ | 无截止时间，原型即可 |
| 5 | 非功能性需求？ | （用户不再补充） |
| 6 | ✅ **自动提交结构化需求** | — |

**产出：** `ClarifiedRequirement` — 包含 project_name、project_goal、4 个功能需求（含验收标准）、技术栈偏好、3 条已确认假设。

### Step 2 — 架构讨论（PlanDraft）

澄清完毕后的结构化解构传递给 `plan_draft()`，产生架构方案：

```
draft = await orchestrator.plan_draft(clarified_req=req)
print(draft.present())
```

输出示例：

```
📋 Architecture Draft (v1)
├── Summary: Habit tracker with React + Python
├── backend/main.py          — FastAPI entry point
├── backend/models.py        — SQLite models
├── frontend/src/App.jsx     — React main component
├── tests/test_api.py        — pytest tests
│
* 回复反馈来调整，或发送 confirm 继续 *
```

用户可以多次反馈精炼：

```python
draft = await orchestrator.plan_refine(draft, "用 Vue 替换 React")
draft = await orchestrator.plan_refine(draft, "添加 Docker 部署")
```

确认后执行：

```python
result = await orchestrator.run_with_plan(draft.plan)
```

### Step 3 — 代码执行（Pipeline）

`run_with_plan()` 跳过规划，直接进入生成执行流水线：

```
for each file_spec in plan.files:
    CodeAgent.execute(file_spec) ──── 生成代码
         │
         ▼
    Sandbox.write_file() ──────────── 写入沙箱
         │
         ▼
    Sandbox.run_file() ────────────── 单文件验证
         │
    ┌────┴────┐
    │  通过   │  失败
    └────┬────┘
         │      │
    ✅ 完成    Healing ×3 ──── 带 stderr 重生成
                  │
              全部失败 → 标记 error

Full pipeline test:
    Sandbox.install_deps(["pytest"])
    Sandbox.run_code("pytest tests/")
    ─── 全量测试 ✅ / ❌

KB Store:
    成功代码自动入库 → 下次相似需求直接复用
```

---

## API 参考

### Orchestrator

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `run(requirement)` | `requirement: str` | `PipelineResult` | 一键全流程（含规划，无讨论） |
| `plan_draft(requirement, clarified_req)` | `requirement: str` 或 `clarified_req: ClarifiedRequirement` | `PlanDraft` | 生成架构草案（含备选方案） |
| `plan_refine(draft, feedback)` | `draft: PlanDraft`, `feedback: str` | `PlanDraft` | 根据用户反馈精炼草案 |
| `run_with_plan(plan)` | `plan: ProjectPlan` | `PipelineResult` | 使用确认后的计划直接执行 |

### ClarifySession

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `ask(current_state)` | `current_state: ClarifiedRequirement`（可选） | `ClarifyResponse` | 追问或提交。action='ask' → 显示问题，action='submit' → 获取最终需求 |
| `record_answer(answer)` | `answer: str` | — | 记录用户回答到对话历史 |

### 验证函数

| 函数 | 返回 | 说明 |
|------|------|------|
| `validate_clarified_requirement(req)` | `(bool, list[str])` | 校验需求文档完整性：必填字段、ID 唯一、优先级合法 |

---

## 核心模型

### 需求层

| 模型 | 关键字段 | 说明 |
|------|----------|------|
| **ClarifiedRequirement** | `project_name`, `project_goal`, `target_users`, `functional_requirements[]`, `non_functional_requirements[]`, `tech_stack_preference`, `constraints`, `confirmed_assumptions[]`, `open_questions[]` | discuss_llm → planner_llm 的标准化交接文档 |
| **FunctionalRequirement** | `id` (FR-1), `description`, `user_story`, `acceptance_criteria[]`, `priority` (must/should/could) | 单个功能需求 |
| **NonFunctionalRequirement** | `category`, `description`, `target_value` | 非功能需求（性能/安全/可用性） |
| **ClarifyResponse** | `action` (ask/submit), `question`, `clarification` | LLM 澄清对话的响应 |
| **ClarifySession** | `.ask()`, `.record_answer()`, `.turns[]`, `MAX_TURNS=10` | 多轮澄清会话状态机 |

### 规划层

| 模型 | 关键字段 | 说明 |
|------|----------|------|
| **PlanDraft** | `plan: ProjectPlan`, `alternatives[]`, `discussion[]`, `confirmed`, `iteration` | 架构讨论草案，`.present()` 可读渲染 |
| **ProjectPlan** | `summary`, `files[]`, `test_strategy` | 单个架构方案 |
| **FileSpec** | `path`, `language`, `purpose`, `dependencies[]` | 单个文件定义 |

### 执行层

| 模型 | 关键字段 | 说明 |
|------|----------|------|
| **PipelineResult** | `success`, `summary`, `files[]`, `pipeline_test`, `kb_stored`, `total_duration`, `corrections` | 全链路执行结果 |
| **PipelineFileResult** | `path`, `language`, `success`, `sandbox_tested`, `sandbox_passed`, `attempts`, `error` | 单文件执行结果 |
| **PipelineTestResult** | `success`, `stdout`, `stderr` | 全量测试结果 |
| **SandboxResult** | `success`, `stdout`, `stderr`, `exit_code`, `error` | 沙箱执行结果 |

---

## 架构

```
src/
├── orchestrator/         # 🧠 编排层
│   └── orchestrator.py   #     ClarifySession + Orchestrator
│
├── agents/               # 🤖 Agent 层
│   ├── base.py           #     BaseAgent 抽象基类
│   └── code_agent.py     #     CodeAgent 代码生成
│
├── sandbox/              # 🏖️ 沙箱层
│   ├── base.py           #     Sandbox 抽象 + SandboxResult
│   ├── e2b_sandbox.py    #     E2BSandbox（云 ☁️）
│   └── docker_sandbox.py #     DockerSandbox（本地）
│
├── common/               # 🔧 共享基础设施
│   ├── schemas.py        #     全部 Pydantic 模型（单文件定义）
│   ├── llm_client.py     #     多 Provider 统一接口
│   ├── knowledge_base.py #     知识库存取抽象
│   └── ...               #     JsonKB + ChromaKB 实现
│
├── config/               # 📋 配置
│   └── agents.yaml       #     Agent 角色、模型、超时
│
└── tests/                # 🧪 测试 (113 项)
    ├── test_clarify.py           # 需求澄清
    ├── test_plan_discussion.py   # 架构讨论
    ├── test_orchestrator.py      # 全链路执行
    ├── test_code_agent.py        # 代码生成
    ├── test_llm_client.py        # LLM 路由
    ├── test_sandbox_*.py         # 沙箱
    └── ...
```

---

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| **LLM 规划/澄清** | DeepSeek V4 Flash | 复杂架构推理 + reasoning_effort=max |
| **LLM 代码生成** | MiniMax M2.7 | 代码生成，温度 0.2 稳定输出 |
| **沙箱** | E2B 云沙箱 / Docker 本地 | 隔离代码执行与测试 |
| **知识库** | Chroma (向量) / JSON 文件 | 经验存储与语义检索 |
| **数据模型** | Pydantic 2 | 全部结构化数据校验 + JSON Schema |
| **CI/CD** | GitHub Actions | ruff lint + pytest + 安全门禁 |
| **HTTP** | httpx | 异步 LLM API 调用 |

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置密钥（DeepSeek / MiniMax / E2B）
cp .env.example .env
# 编辑 .env 填入 API Key

# 3. 运行测试（必须通过）
ruff check src/ tests/ && pytest

# 4. 完整使用示例
from src.orchestrator.orchestrator import Orchestrator, ClarifySession
from src.common.llm_client import LLMClient
from src.common.schemas import ClarifiedRequirement

orc = Orchestrator()
llm = LLMClient()
session = ClarifySession(discuss_llm=llm)

# Phase 1: 需求澄清
state = ClarifiedRequirement(
    project_name="Calculator",
    project_goal="Build a calculator",
    functional_requirements=[],
)
while True:
    resp = await session.ask(current_state=state)
    if resp.action == "submit":
        state = resp.clarification
        break
    print(resp.question)          # 显示给用户
    user_answer = input()          # 收集用户回答
    state.project_goal = user_answer  # 更新状态
    session.record_answer(user_answer)

# Phase 2: 架构讨论
draft = await orc.plan_draft(clarified_req=state)
print(draft.present())
# 用户反馈 → plan_refine → confirm

# Phase 3: 执行
result = await orc.run_with_plan(draft.plan)
print(result.model_dump())
```

---

## 开发工作流

提交代码前必须执行以下两步，否则 CI 会拦截：

```bash
# 1. Lint 检查（必须 0 errors）
ruff check src/ tests/

# 2. 单元测试（必须全部通过）
pytest
```

**常见陷阱：**
- `__init__.py` 导出必须加 `as` 别名（`from .x import X as X`），否则 F401
- 不要留防御性导入（先导入后不用）
- `ruff check --fix` 可自动修复 ~30% 的简单问题

> 完整规范见 `AGENTS.md`（Agent 行为约束）和 `execution_log.md`（问题追溯）。

---

## 项目文档规范

**本文件是项目的单一信息源。** 所有功能迭代、优化、架构变更，必须在实施完成后同步更新本文件。具体要求：

1. **新功能**：在 `README.md` 中添加对应的章节、API 参考和架构说明
2. **模型变更**：在「核心模型」表中更新字段和说明
3. **测试新增**：在「架构」部分的 `tests/` 列表中添加新的测试模块
4. **配置变更**：在「技术栈」或「快速开始」中更新

与 README.md 互补的文档：
- `AGENTS.md` — AI Agent 行为规则（编码规范、讨论式规划流程、提交工作流）
- `execution_log.md` — 项目执行审计日志（里程碑、问题记录、决策记录）

---

## 阶段路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| 一 | 单 Agent 闭环（需求澄清 → 架构讨论 → 代码生成 → 沙箱测试 → 自愈 → 存储） | ✅ 完成 |
| 二 | 多 Agent 协同（Frontend/Backend/DB/QA 专业化 Agent 并行执行） | ⏳ 待开始 |
| 三 | 迭代试错（自动修复 → 人工反馈 → 迭代改进循环） | ⏳ |
| 四 | 人工节点与生产化（PR 自动生成、审批流、监控） | ⏳ |

当前测试覆盖：**113 项全部通过**，含真实 LLM 集成测试（DeepSeek V4 Flash）。
