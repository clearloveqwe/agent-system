# Execution Log — 多 Agent 软件开发系统

## 项目信息

| 字段 | 内容 |
|------|------|
| 项目名称 | 多 Agent 全栈 Web 开发系统 |
| 启动日期 | 2026-04-29 |
| 系统架构 | Hermes Agent + 多子 Agent 编排 |
| 代码托管 | GitHub (`git@github.com:clearloveqwe/agent-system.git`) |
| CI/CD | GitHub Actions |
| 沙箱方案 | E2B 云沙箱 / Docker 本地 |
| LLM 策略 | 分层调用（复杂→海外顶级，常规→DeepSeek/Qwen） |
| 知识存储 | Chroma（初期）→ Qdrant/Milvus（演进） |
| 审计保留 | ≥ 6 个月 |

---

## 已确认决策清单

详见 [前置探讨确认书](#)

---

## 阶段一：单 Agent 闭环（4-6 周）

### 目标

搭建单 Agent 闭环流水线：自然语言需求 → 架构设计 → 代码生成 → 测试 → PR 发布。

### 里程碑

| 里程碑 | 预计完成 | 实际完成 | 状态 |
|--------|----------|----------|------|
| M1: 项目骨架与配置 | 2026-04-29 | 2026-04-29 | ✅ |
| M2: 简单 Code Gen Agent | 2026-04-29 | 2026-04-29 | ✅ |
| M3: 测试框架集成 | 2026-04-29 | 2026-04-29 | ✅ |
| M4: 沙箱执行环境 | 2026-04-29 | 2026-04-29 | ✅ |
| M5: 单 Agent 端到端流水线 | 2026-04-29 | 2026-04-29 | ✅ |

### M1 关键动作日志

| 时间 | 动作 | 结果 | 备注 |
|------|------|------|------|
| 2026-04-29 | 前置探讨确认书全部 16 项确认 | ✅ 已记录 | - |
| 2026-04-29 | 创建 execution_log.md | ✅ 已写入 | - |
| 2026-04-29 | Git init + 远程仓库关联 | ✅ 已配置 | SSH 认证完成 |
| 2026-04-29 | 创建项目目录结构 | ✅ 已创建 | src/ tests/ config/ docs/ .github/ |
| 2026-04-29 | 创建 README.md | ✅ 已写入 | 架构概览 + 阶段路线 |
| 2026-04-29 | 创建 AGENTS.md | ✅ 已写入 | Agent 行为规则 |
| 2026-04-29 | 创建 policy.yaml | ✅ 已写入 | 网络策略 + 风险分级 |
| 2026-04-29 | 创建 .gitignore | ✅ 已写入 | Python/Node/IDE 过滤 |
| 2026-04-29 | 创建 CI 流水线 | ✅ 已写入 | ruff lint + pytest + high-risk gate |
| 2026-04-29 | 创建 agents.yaml 配置 | ✅ 已写入 | Agent 角色、模型优先级、沙箱 |
| 2026-04-29 | 创建 Python 包骨架 | ✅ 已写入 | orchestrator/agents/sandbox/common |

### M2 关键动作日志

| 时间 | 动作 | 结果 | 备注 |
|------|------|------|------|
| 2026-04-29 | 实现 LLMClient — 多 Provider 统一接口 | ✅ 已实现 | 支持 OpenRouter/DeepSeek/OpenAI/自定义 |
| 2026-04-29 | 实现 CodeAgent — 代码生成逻辑 | ✅ 已实现 | 含 code fence 清理、文件写入 |
| 2026-04-29 | 实现 Orchestrator.run — 单 Agent 闭环 | ✅ 已实现 | 需求→规划→生成→输出 |
| 2026-04-29 | 编写单元测试 18 项 | ✅ 全部通过 | LLMClient 9 + CodeAgent 7 + Orchestrator 2 |
| 2026-04-29 | 添加 requirements.txt | ✅ 已写入 | httpx + pytest + ruff |

### API Key 与模型分配

| 时间 | 动作 | 结果 | 备注 |
|------|------|------|------|
| 2026-04-29 | 配置 MiniMax M2.7 Key | ✅ 已写入 .env | 分配给 Frontend/Backend/Database/QA |
| 2026-04-29 | 配置 DeepSeek V4 Key | ✅ 已写入 .env | 分配给 Orchestrator |
| 2026-04-29 | 更新 LLMClient 支持 MiniMax | ✅ 已实现 | api.minimaxi.com 路由 |
| 2026-04-29 | 更新 LLMClient 支持 reasoning_effort | ✅ 已实现 | 思考模式 + extra_body |
| 2026-04-29 | 更新 agents.yaml 模型分配 | ✅ 已配置 | Orchestrator→DeepSeek-V4-Flash(max), 其余→MiniMax M2.7 |
| 2026-04-29 | 测试 24 项 | ✅ 全部通过 | 含 reasoning_effort 验证 |

### M3 关键动作日志

| 时间 | 动作 | 结果 | 备注 |
|------|------|------|------|
| 2026-04-29 | 实现 KnowledgeEntry + BaseKnowledgeBase 抽象 | ✅ 已实现 | 通用知识库接口 |
| 2026-04-29 | 实现 JsonKnowledgeBase（文件持久化） | ✅ 已实现 | JSON 后端，零依赖 |
| 2026-04-29 | CodeAgent 接入知识库 | ✅ 已实现 | 检索历史 + 存储新结果 |
| 2026-04-29 | 创建 pyproject.toml（覆盖率门槛 85%） | ✅ 已配置 | |
| 2026-04-29 | 知识库 + CodeAgent KB 测试 | ✅ 33 项全部通过 | 含持久化/搜索/类型过滤 |

### M4 关键动作日志

| 时间 | 动作 | 结果 | 备注 |
|------|------|------|------|
| 2026-04-29 | 配置 pip 国内镜像源（清华 TUNA） | ✅ 已配置 | |
| 2026-04-29 | 安装 chromadb 1.5.8 + e2b-code-interpreter 2.6.1 | ✅ 已安装 | 镜像加速后约 3 分钟 |
| 2026-04-29 | 实现 ChromaKnowledgeBase | ✅ 已实现 | 向量语义搜索，PersistentClient |
| 2026-04-29 | 更新 Sandbox 基类（新增 SandboxResult + run_file/write_file/read_file） | ✅ 已更新 | |
| 2026-04-29 | 实现 E2BSandbox（E2B 云沙箱） | ✅ 已实现 | 代码执行/文件读写/依赖安装 |
| 2026-04-29 | 实现 DockerSandbox（Docker 本地沙箱） | ✅ 已实现 | subprocess 调用，network_disabled 选项 |
| 2026-04-29 | Docker + E2B 沙箱测试 17 项 | ✅ 全部通过 | Mock 模式，无需真实 Docker/E2B |

### M5 关键动作日志

| 时间 | 动作 | 结果 | 备注 |
|------|------|------|------|
| 2026-04-29 | 改造 Orchestrator — 注入 Sandbox + KB | ✅ 已实现 | config/agents.yaml 驱动 |
| 2026-04-29 | 实现生成 → 沙箱写入 → 测试执行 → 检验 | ✅ 已实现 | 每文件独立 sandbox test |
| 2026-04-29 | 实现 Healing 重试循环（×3） | ✅ 已实现 | 失败后携带 stderr 重生成 |
| 2026-04-29 | 实现 Pipeline 级测试（pytest 沙箱内） | ✅ 已实现 | 全局测试 + 单文件双重验证 |
| 2026-04-29 | 实现 KB 自动存储成功经验 | ✅ 已实现 | PipelineResult.kb_stored |
| 2026-04-29 | 新增 PipelineFileResult / PipelineResult 数据类 | ✅ 已实现 | to_dict() 序列化 |
| 2026-04-29 | 新增测试 13 项 | ✅ 69/69 通过 | 覆盖 plan/generate/heal/exhaust/KB/test |

---

## 问题记录

| 日期 | 现象 | 根因 | 修复 | 预防措施 |
|------|------|------|------|----------|
| 2026-04-29 | CI → ruff check 失败 (F401，20 个错误) | 代码快速迭代中"防御性导入"未清理，__init__.py 导出缺 `as` 别名，本地未跑 lint 即提交 | `ruff check --fix` 自动修复 6 个，显式 `as` 别名修复 14 个 | 见下方「F401 根因分析与预防」|

---

### F401 根因分析与预防

#### 现象

GitHub Actions CI 中 `ruff check src/ tests/` 报 20 个 `F401`（Module imported but unused）错误，含 `unittest.mock.patch`、`os`、`json` 等标准库及项目内模块，流程 exit code 1 终止。

#### 根因链

```
代码快速迭代（M2-M4）+ 代码生成→编缉器→提交 跳过 lint
         │
         ▼
防御性导入：写 imports 时"先全部导入，用到时再说"
         │
         ▼
__init__.py 裸导出：`from .x import X` → ruff 认为 X 未在当前模块使用
         │
         ▼
本地验证不完整：只跑 pytest，未跑 ruff check
         │
         ▼
CI 拦截，反馈延迟 2-3 分钟
```

#### 三类典型场景

| 场景 | 示例 | 修复方式 |
|------|------|----------|
| 标准库/三方库用不到 | `import os`, `import json` | 直接删除 |
| 调试变量留在代码里 | `LANGUAGE_COMMANDS`、`cmd_template` | 确认无用后删除 |
| __init__.py 转发导出 | `from .code_agent import CodeAgent` | 加 `as` 别名：`from .code_agent import CodeAgent as CodeAgent`，或 `# noqa: F401` |

#### 预防措施（写入项目规范）

1. **提交前必须全量检查**：`ruff check . && pytest`
2. **代码生成后加一步 lint**：Agent 写完文件后立即执行 `ruff check --fix <file>` 再提交
3. **__init__.py 统一风格**：所有导出加 `as` 别名（PEP 484 推荐 + 消除 F401）
4. **CI 保留 lint 门禁**：不允许 `exit code 1` 通过，保留当前配置

---

## 人工审批区

| 阶段 | 审批人 | 状态 | 日期 | 签名 |
|------|--------|------|------|------|
| 前置探讨确认 | 项目负责人 | ✅ 已确认 | 2026-04-29 | - |
| 阶段一启动 | 项目负责人 | ✅ 已批准 | 2026-04-29 | - |
| M1: 项目骨架与配置 | 项目负责人 | ⏳ 待审批 | 2026-04-29 | - |
| 阶段一完成 | - | ⏳ | - | - |
