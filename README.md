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

## 阶段路线

| 阶段 | 内容 | 预计周期 |
|------|------|----------|
| 一 | 单 Agent 闭环 | 4-6 周 |
| 二-三 | 多 Agent 协同 | 8-12 周 |
| 四 | 人工节点与生产化 | 6-8 周 |

## 快速开始

（阶段一完成后补充）

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

- **LLM 策略：** 复杂任务→海外顶级模型，常规任务→DeepSeek/Qwen
- **沙箱：** E2B 云沙箱 / Docker 本地
- **CI/CD：** GitHub Actions
- **知识库：** Chroma（初期）
