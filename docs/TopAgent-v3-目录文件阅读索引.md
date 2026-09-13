# TopAgent v3 目录与文件阅读索引

版本：3.0.0
更新日期：2026-08-18
项目根目录：`C:\AI_Project`

## 1. 先选阅读路线

### 1.1 15 分钟了解全局

按顺序阅读：

1. [`CLAUDE.md`](../CLAUDE.md)：根级规则、真实能力口径、启动命令。
2. [`docs/TopAgent-v3-体系详解.md`](TopAgent-v3-体系详解.md)：体系全貌。
3. [`docs/topagent-v3-acceptance.md`](topagent-v3-acceptance.md)：如何证明不是提示词散文。
4. [`orchestrator/pipeline.json`](../orchestrator/pipeline.json)：十步流水线权威数据。
5. [`topagent/runtime/dispatcher.py`](../topagent/runtime/dispatcher.py)：统一执行入口。

### 1.2 60 分钟理解一次真实执行

```text
topagent/__main__.py
  → runtime/orchestrator.py
  → runtime/dispatcher.py
  → registry/agents.py
  → runtime/executors.py
  → core/database.py
  → artifacts.py + core/events.py
  → api/server.py + dashboard/
```

### 1.3 阅读 Agent 通信

```text
mcp-bridge/server.py
  → topagent/bus/mcp_server.py
  → topagent/bus/service.py
  → topagent/bus/store.py
  → topagent/bus/models.py
  → topagent/runtime/scheduler.py
  → tests/test_message_bus.py
  → tests/test_mcp_bridge.py
  → tests/test_scheduler.py
```

### 1.4 阅读长期记忆

```text
.claude/agents/memory-learning-agent.md
  → .claude/skills/memory-learning/SKILL.md
  → topagent/memory/store.py
  → topagent/core/database.py 中 memories/memory_fts
  → tests/test_memory.py
```

### 1.5 阅读密钥安全

```text
memory/api-keys.md
  → topagent/secrets/dpapi.py
  → topagent/secrets/vault.py
  → router/config.py
  → tests/test_secrets.py
```

### 1.6 阅读 Evaluation Harness

```text
system/capabilities/*.json
  → tests/test_*.py
  → docs/topagent-v3-acceptance.md
  → docs/TopAgent-v3-操作日志-2026-08-17.md
```

## 2. 顶层目录图

```text
C:\AI_Project
├── CLAUDE.md                 # v3 根级执行规则和入口
├── .claude/
│   ├── agents/               # 19 个 Agent 定义事实源
│   ├── skills/               # 22 个 Skill 定义事实源
│   └── settings.json         # MCP Server 配置
├── topagent/                 # v3 Runtime 主代码
│   ├── core/                 # 模型、数据库、身份、事件
│   ├── runtime/              # Dispatcher/Executor/Scheduler/Orchestrator
│   ├── bus/                  # 持久消息和 MCP 实现
│   ├── registry/             # Agent/Skill/Capability Registry
│   ├── memory/               # 长期记忆生命周期
│   ├── secrets/              # Windows DPAPI vault
│   ├── api/                  # Control Center HTTP/SSE
│   └── dashboard/            # 本地监控前端
├── system/capabilities/      # 8 个机器可读能力契约
├── orchestrator/             # v2 人工门禁兼容层 + pipeline 权威定义
├── router/                   # Provider 模型路由和 fallback
├── mcp-bridge/               # v3 MCP 启动包装
├── memory/                   # 人类可读知识、协议和历史记忆
├── tests/                    # v3 Evaluation Harness
├── docs/                     # 设计、验收、日志和索引
├── manju-studio/             # AI 视频/漫剧示范应用
├── video-notes/              # 视频笔记示范应用
├── runtime/                  # 本机运行状态，Git ignored
├── outputs/                  # Router 媒体输出
├── setup.bat                 # Windows 安装入口，无内嵌密钥
└── setup.sh                  # Linux/macOS 安装入口，无内嵌密钥
```

## 3. 根目录文件

| 文件 | 阅读目的 | 权威性 |
|---|---|---|
| [`CLAUDE.md`](../CLAUDE.md) | 了解 v3 不可违反的执行规则、命令和边界 | 当前总纲 |
| [`.gitignore`](../.gitignore) | 确认 runtime、Manus 离线网页等不会误提交 | 当前配置 |
| [`.claude/settings.json`](../.claude/settings.json) | 查看 MCP Bridge 和 Model Router 如何注册 | 当前配置 |
| [`setup.bat`](../setup.bat) | Windows 初始化；不含密钥值 | 当前入口 |
| [`setup.sh`](../setup.sh) | Linux/macOS 初始化；DPAPI 部分不适用 | 当前入口 |

## 4. `topagent/` Runtime 主代码

### 4.1 包入口

| 文件 | 作用 | 重点符号 |
|---|---|---|
| [`topagent/__init__.py`](../topagent/__init__.py) | 包版本 | `__version__ = 3.0.0` |
| [`topagent/__main__.py`](../topagent/__main__.py) | CLI 命令总入口 | `init`, `dispatch`, `verify`, `run-*`, `serve`, `secrets` |
| [`topagent/settings.py`](../topagent/settings.py) | 所有目录路径和 runtime 初始化 | `Settings`, `settings` |
| [`topagent/artifacts.py`](../topagent/artifacts.py) | SHA-256 内容寻址产物 | `ArtifactStore` |

### 4.2 `topagent/core/`

建议顺序：models → context → database → events → ids。

| 文件 | 作用 | 重点 |
|---|---|---|
| [`core/models.py`](../topagent/core/models.py) | Runtime 数据结构 | `ExecutionRequest`, `ExecutionConstraints`, `ExecutionResult`, `ArtifactRef` |
| [`core/context.py`](../topagent/core/context.py) | 当前 execution 身份注入 | `ExecutionIdentity`, `ContextVar` |
| [`core/database.py`](../topagent/core/database.py) | SQLite Schema 和访问封装 | `SCHEMA`, `Database`, WAL、transaction |
| [`core/events.py`](../topagent/core/events.py) | execution/message 事件 | `EventStore.append/list` |
| [`core/ids.py`](../topagent/core/ids.py) | run/exe/msg 等 ID | `new_id()` |
| [`core/__init__.py`](../topagent/core/__init__.py) | 子包标识 | 无业务逻辑 |

`database.py` 是理解运行事实最重要的底层文件。优先阅读其中 14 个表/索引定义，然后再看
上层代码如何写入。

### 4.3 `topagent/runtime/`

| 文件 | 作用 | 阅读重点 |
|---|---|---|
| [`runtime/dispatcher.py`](../topagent/runtime/dispatcher.py) | 统一执行和独立验证 | `dispatch()`, `verify()`, `_complete()`, `_fail()` |
| [`runtime/executors.py`](../topagent/runtime/executors.py) | backend 适配 | `FakeExecutor`, `SubprocessExecutor`, `ClaudeCodeExecutor`, `RouterExecutor` |
| [`runtime/scheduler.py`](../topagent/runtime/scheduler.py) | 消息→execution→ACK/FAIL | `tick()`, `heartbeat()` |
| [`runtime/orchestrator.py`](../topagent/runtime/orchestrator.py) | pipeline.json 可执行适配 | `create_run()`, `run_step()`, `status()` |
| [`runtime/__init__.py`](../topagent/runtime/__init__.py) | 导出 Dispatcher | 包入口 |

关键依赖方向：

```text
RuntimeOrchestrator → Dispatcher → Executor
Scheduler           → Dispatcher
Dispatcher          → AgentRegistry + ArtifactStore + EventStore + Database
```

不要让 Executor 反向修改 pipeline；不要让 Dashboard 直接承担编排逻辑。

### 4.4 `topagent/bus/`

| 文件 | 作用 | 阅读重点 |
|---|---|---|
| [`bus/models.py`](../topagent/bus/models.py) | Message/Lease 数据结构 | `Message`, `LeasedMessage` |
| [`bus/store.py`](../topagent/bus/store.py) | 持久状态机 | `send`, `lease`, `start_processing`, `acknowledge`, `fail`, `requeue_expired` |
| [`bus/service.py`](../topagent/bus/service.py) | MCP/CLI/Scheduler 稳定边界 | legacy 字段翻译 |
| [`bus/mcp_server.py`](../topagent/bus/mcp_server.py) | MCP JSON-RPC 和 13 个工具 | `TOOLS`, `MCPBridge`, `handle_request` |
| [`bus/__init__.py`](../topagent/bus/__init__.py) | 子包标识 | 无业务逻辑 |

阅读 `store.py` 时重点检查三项：

1. message_id 和 delivery_id 必须匹配。
2. attempts 到达 max_attempts 时进入 dead_letter。
3. sender identity 来自 Runtime Context，而不是 Agent 自报。

### 4.5 `topagent/registry/`

| 文件 | 作用 | 阅读重点 |
|---|---|---|
| [`registry/frontmatter.py`](../topagent/registry/frontmatter.py) | 轻量 frontmatter 解析 | 当前只解析顶层简单标量/列表 |
| [`registry/agents.py`](../topagent/registry/agents.py) | Agent 定义索引 | version/model/backend/status/hash、重复 ID |
| [`registry/skills.py`](../topagent/registry/skills.py) | Skill 定义索引 | metadata vs `load_instructions()` |
| [`registry/selector.py`](../topagent/registry/selector.py) | 渐进式 Skill 选择 | 英文词元、中文二元片段 |
| [`registry/capabilities.py`](../topagent/registry/capabilities.py) | Capability Contract 和 evidence | `build()`, `evidence()` |
| [`registry/builder.py`](../topagent/registry/builder.py) | 一次重建全部 Registry | `build_all()` |
| [`registry/__init__.py`](../topagent/registry/__init__.py) | 子包标识 | 无业务逻辑 |

限制：`frontmatter.py` 不是完整 YAML 解析器，嵌套 `spawns` 仍主要供人和原生态 Agent
加载器阅读；Runtime 的步骤权威数据是 `pipeline.json`。

### 4.6 `topagent/memory/`

| 文件 | 作用 | 阅读重点 |
|---|---|---|
| [`memory/store.py`](../topagent/memory/store.py) | 候选、晋升、冲突、替代、归档、FTS | `add_candidate`, `promote`, `archive`, `search` |
| [`memory/__init__.py`](../topagent/memory/__init__.py) | 导出 MemoryStore | 包入口 |

### 4.7 `topagent/secrets/`

| 文件 | 作用 | 阅读重点 |
|---|---|---|
| [`secrets/dpapi.py`](../topagent/secrets/dpapi.py) | Windows CryptProtectData/CryptUnprotectData 封装 | CurrentUser、UI forbidden、LocalFree |
| [`secrets/vault.py`](../topagent/secrets/vault.py) | 密钥 envelope、解析、迁移 | `WindowsDPAPIVault`, `SecretResolver`, `migrate_legacy` |
| [`secrets/__init__.py`](../topagent/secrets/__init__.py) | 导出 vault/resolver | 包入口 |

审查时禁止在日志或测试错误中打印 `vault.load()` 的值。

### 4.8 `topagent/api/` 和 `dashboard/`

| 文件 | 作用 | 阅读重点 |
|---|---|---|
| [`api/server.py`](../topagent/api/server.py) | stdlib HTTP API、静态文件、SSE | `ControlCenter`, `ControlCenterHandler`, `create_server` |
| [`api/__init__.py`](../topagent/api/__init__.py) | 子包标识 | 无业务逻辑 |
| [`dashboard/index.html`](../topagent/dashboard/index.html) | 页面结构 | 指标、执行、消息、Agent、记忆、能力、事件 |
| [`dashboard/styles.css`](../topagent/dashboard/styles.css) | 本地 Dashboard 样式 | 响应式、状态颜色 |
| [`dashboard/app.js`](../topagent/dashboard/app.js) | API/SSE 数据绑定 | `refresh()`, `connectEvents()` |

## 5. `system/capabilities/`

| 契约 | 证明的能力 | 当前状态 |
|---|---|---|
| [`unified-execution.json`](../system/capabilities/unified-execution.json) | dispatch、结果、Artifact、attestation | implemented / L2 |
| [`durable-message-bus.json`](../system/capabilities/durable-message-bus.json) | lease/ACK/retry/dead-letter | implemented / L2 |
| [`agent-runtime-identity.json`](../system/capabilities/agent-runtime-identity.json) | execution 身份和独立性证据 | partial / L2 |
| [`progressive-registry.json`](../system/capabilities/progressive-registry.json) | Agent/Skill 索引与渐进加载 | implemented / L2 |
| [`memory-lifecycle.json`](../system/capabilities/memory-lifecycle.json) | candidate/conflict/archive | implemented / L2 |
| [`control-center.json`](../system/capabilities/control-center.json) | API、SSE、Dashboard、指标 | implemented / L2 |
| [`dpapi-secret-vault.json`](../system/capabilities/dpapi-secret-vault.json) | Windows DPAPI 密钥库 | implemented / L2 |
| [`pipeline-runtime-adapter.json`](../system/capabilities/pipeline-runtime-adapter.json) | pipeline agent 字符串变 execution | implemented / L2 |

阅读契约时先看 `limitations`，再看 `status`；这样能避免只看“implemented”忽略边界。

## 6. `orchestrator/` 人工门禁兼容层

| 文件 | 作用 | 状态 |
|---|---|---|
| [`pipeline.json`](../orchestrator/pipeline.json) | step、spawn、input/output、gate 权威定义 | 当前权威数据 |
| [`top-agent-orchestrator.py`](../orchestrator/top-agent-orchestrator.py) | v2 状态机、提交、裁决、人工确认、升级 | 兼容保留 |
| [`test_human_gate.py`](../orchestrator/test_human_gate.py) | TTY 人工门禁和伪造攻击测试 | 运行前检查是否会触碰现有 state |
| [`README.md`](../orchestrator/README.md) | v2 门禁使用说明和 v3 边界 | 当前说明 |

不要混淆：

- `orchestrator/state/*.json`：v2 门禁运行状态。
- `runtime/topagent.db`：v3 execution/message/memory/capability 运行事实。

当前为双轨兼容，后续才考虑单一状态源迁移。

## 7. `router/` 模型网关

| 文件 | 作用 | 阅读重点 |
|---|---|---|
| [`config.yaml`](../router/config.yaml) | 平台和 12 类任务路由 | primary/fallback、api_key_env |
| [`config.py`](../router/config.py) | YAML 和 SecretResolver | 环境变量→DPAPI |
| [`providers.py`](../router/providers.py) | OpenAI-compatible、Anthropic、图像、音频 | 请求、响应、错误 |
| [`router.py`](../router/router.py) | 决策和 fallback 循环 | `_get_provider`, `route_task`, `route_and_execute` |
| [`server.py`](../router/server.py) | MCP/CLI | dry-run 默认、安全边界 |
| [`__init__.py`](../router/__init__.py) | 允许 package import | Runtime Adapter 依赖 |
| [`README.md`](../router/README.md) | 平台、调用和实测说明 | 使用入口 |

配套阅读：[`docs/code-reading-guide.md`](code-reading-guide.md)。

## 8. `mcp-bridge/`

| 文件 | 作用 |
|---|---|
| [`server.py`](../mcp-bridge/server.py) | 把项目根加入 sys.path，启动 `topagent.bus.mcp_server.main` |

它不再保存文件队列状态；所有实际逻辑在 `topagent/bus/`。

## 9. `.claude/agents/` Agent 定义索引

### 总控和历史

| 文件 | 状态 |
|---|---|
| [`top-agent.md`](../.claude/agents/top-agent.md) | v3 唯一总指挥 |
| [`delivery-director.md`](../.claude/agents/delivery-director.md) | deprecated 兼容定义 |

### 情报和基础设施

| 文件 | 作用 |
|---|---|
| [`skill-hunter.md`](../.claude/agents/skill-hunter.md) | 搜索验证 Skill/项目 |
| [`memory-learning-agent.md`](../.claude/agents/memory-learning-agent.md) | 长期经验和冲突治理 |
| [`model-router-agent.md`](../.claude/agents/model-router-agent.md) | 模型选择 |
| [`tool-manager.md`](../.claude/agents/tool-manager.md) | MCP 工具、权限和审计 |
| [`agent-forge-agent.md`](../.claude/agents/agent-forge-agent.md) | Agent 创建和版本管理 |

### 架构、开发和交付

| 文件 | 作用 |
|---|---|
| [`architect-agent.md`](../.claude/agents/architect-agent.md) | 架构和 ADR |
| [`frontend-agent.md`](../.claude/agents/frontend-agent.md) | 前端 |
| [`backend-agent.md`](../.claude/agents/backend-agent.md) | 后端 |
| [`ai-engineer-agent.md`](../.claude/agents/ai-engineer-agent.md) | AI/RAG/Agent |
| [`test-agent.md`](../.claude/agents/test-agent.md) | 测试 |
| [`devops-agent.md`](../.claude/agents/devops-agent.md) | 部署和运维 |

### 质量、失败、评估和数据

| 文件 | 作用 |
|---|---|
| [`fact-check-agent.md`](../.claude/agents/fact-check-agent.md) | 事实验证 |
| [`qa-agent.md`](../.claude/agents/qa-agent.md) | 任务级 QA 和否决 |
| [`quality-auditor.md`](../.claude/agents/quality-auditor.md) | 体系级独立审核；当前职责需进一步去重 |
| [`failure-analysis-agent.md`](../.claude/agents/failure-analysis-agent.md) | 失败根因 |
| [`eval-benchmark-agent.md`](../.claude/agents/eval-benchmark-agent.md) | 基准与回归 |
| [`data-curator-agent.md`](../.claude/agents/data-curator-agent.md) | 训练数据 |

## 10. `.claude/skills/` Skill 定义索引

| Skill 路径 | 何时读 |
|---|---|
| [`top-agent/SKILL.md`](../.claude/skills/top-agent/SKILL.md) | 启动完整 TopAgent 流水线 |
| [`delivery-director.md`](../.claude/skills/delivery-director.md) | 只做历史兼容检查 |
| [`skill-hunter/SKILL.md`](../.claude/skills/skill-hunter/SKILL.md) | 搜 Skill/工具 |
| [`github-research/SKILL.md`](../.claude/skills/github-research/SKILL.md) | 搜开源参考 |
| [`env-scan/SKILL.md`](../.claude/skills/env-scan/SKILL.md) | 环境盘点 |
| [`tech-selection/SKILL.md`](../.claude/skills/tech-selection/SKILL.md) | 技术选型 |
| [`agent-team-design/SKILL.md`](../.claude/skills/agent-team-design/SKILL.md) | 设计 Agent 团队 |
| [`skill-generator/SKILL.md`](../.claude/skills/skill-generator/SKILL.md) | 生成新 Skill |
| [`agent-forge/SKILL.md`](../.claude/skills/agent-forge/SKILL.md) | 创建/替换 Agent |
| [`tool-manager/SKILL.md`](../.claude/skills/tool-manager/SKILL.md) | 工具、MCP、ACK/FAIL |
| [`model-router/SKILL.md`](../.claude/skills/model-router/SKILL.md) | 模型路由 |
| [`memory-learning/SKILL.md`](../.claude/skills/memory-learning/SKILL.md) | 记忆检索和生命周期 |
| [`fact-check/SKILL.md`](../.claude/skills/fact-check/SKILL.md) | 事实核验 |
| [`qa-agent/SKILL.md`](../.claude/skills/qa-agent/SKILL.md) | 质量门禁 |
| [`code-review/SKILL.md`](../.claude/skills/code-review/SKILL.md) | 代码审查 |
| [`bug-diagnosis/SKILL.md`](../.claude/skills/bug-diagnosis/SKILL.md) | Bug 诊断 |
| [`failure-analysis/SKILL.md`](../.claude/skills/failure-analysis/SKILL.md) | 失败复盘 |
| [`eval-benchmark/SKILL.md`](../.claude/skills/eval-benchmark/SKILL.md) | 基准和回归 |
| [`data-curator/SKILL.md`](../.claude/skills/data-curator/SKILL.md) | 训练数据 |
| [`auto-documentation/SKILL.md`](../.claude/skills/auto-documentation/SKILL.md) | 自动文档 |
| [`project-delivery/SKILL.md`](../.claude/skills/project-delivery/SKILL.md) | 交付包 |
| [`project-closeout/SKILL.md`](../.claude/skills/project-closeout/SKILL.md) | 收尾；外部推送仍需授权 |

浏览器“网页另存为”的 Manus HTML 和 `_files/` 资源不是可执行 Skill，且可能包含会话信息，
已经 Git ignored，不应纳入 Skill Registry 或提交。

## 11. `memory/` 人类可读知识

### 当前安全和总索引

| 文件 | 作用 |
|---|---|
| [`api-keys.md`](../memory/api-keys.md) | 只保存密钥管理说明，不保存值 |
| [`MEMORY.md`](../memory/MEMORY.md) | v2 历史记忆总索引；部分内容待按 v3 更新 |
| [`session-handoff.md`](../memory/session-handoff.md) | 会话交接；属于用户已有改动 |
| [`project-init.md`](../memory/project-init.md) | 项目初始化记忆 |

### 体系协议和知识

| 文件 | 作用 | 备注 |
|---|---|---|
| [`agent-communication-protocol.md`](../memory/agent-communication-protocol.md) | v2 通信协议 | v3 实际状态以 bus/store.py 为准 |
| [`mcp-specification.md`](../memory/mcp-specification.md) | MCP 规范记录 | 与实际 MCP Schema 对照阅读 |
| [`agent-scoring-system.md`](../memory/agent-scoring-system.md) | Agent 评分和淘汰 | 仍需和 execution evidence 自动关联 |
| [`knowledge-graph.md`](../memory/knowledge-graph.md) | 历史知识图谱 | 人工 Markdown 基线 |
| [`model-config.md`](../memory/model-config.md) | 模型配置知识 | 实际 Router 以 config.yaml 为准 |
| [`model-capability-matrix.md`](../memory/model-capability-matrix.md) | 模型能力记录 | 时效性需定期联网复核 |
| [`training-pipeline.md`](../memory/training-pipeline.md) | 训练数据管道设计 | 多数为设计层 |
| [`download-policy.md`](../memory/download-policy.md) | 下载安全策略 | 操作参考 |
| [`fact-check-sop.md`](../memory/fact-check-sop.md) | 事实验证 SOP | 质量流程参考 |

### 旧消息目录

`memory/message-bus/` 是 v1/v2 文件消息总线历史状态。v3 不再以它作为运行事实源；当前
运行状态在 `runtime/topagent.db`。清理历史文件前需要单独确认，避免删除用户记录。

## 12. `tests/` Evaluation Harness

| 文件 | 覆盖 |
|---|---|
| [`helpers.py`](../tests/helpers.py) | 临时工作区、临时数据库、测试 Agent |
| [`test_dispatcher.py`](../tests/test_dispatcher.py) | execution、Artifact、attestation、付费拒绝、独立 verifier |
| [`test_message_bus.py`](../tests/test_message_bus.py) | 幂等、租约、ACK、重试、死信、过期恢复 |
| [`test_scheduler.py`](../tests/test_scheduler.py) | 消息→execution→ACK→presence |
| [`test_mcp_bridge.py`](../tests/test_mcp_bridge.py) | MCP Schema、legacy identity、协议握手 |
| [`test_memory.py`](../tests/test_memory.py) | candidate/promote/search/archive/conflict/supersede |
| [`test_registry.py`](../tests/test_registry.py) | 三类 Registry 和 Skill 渐进加载 |
| [`test_router.py`](../tests/test_router.py) | dry-run、fallback、未知类型 |
| [`test_orchestrator_runtime.py`](../tests/test_orchestrator_runtime.py) | pipeline Agent 字符串变 execution |
| [`test_control_center.py`](../tests/test_control_center.py) | health、metrics、静态 Dashboard |
| [`test_secrets.py`](../tests/test_secrets.py) | DPAPI round-trip、密文、删除、旧格式解析 |
| [`__init__.py`](../tests/__init__.py) | 测试包标识 |

运行：

```powershell
python -m unittest discover -s tests -v
```

## 13. `docs/` 阅读索引

### v3 当前文档

| 文档 | 用途 |
|---|---|
| [`TopAgent-v3-体系详解.md`](TopAgent-v3-体系详解.md) | 当前体系完整介绍 |
| [`TopAgent-v3-操作日志-2026-08-17.md`](TopAgent-v3-操作日志-2026-08-17.md) | 本轮实施与失败修复全过程 |
| [`TopAgent-v3-目录文件阅读索引.md`](TopAgent-v3-目录文件阅读索引.md) | 本文 |
| [`topagent-v3.md`](topagent-v3.md) | v3 精简技术设计 |
| [`topagent-v3-acceptance.md`](topagent-v3-acceptance.md) | 能力证据和反证标准 |
| [`topagent-v3-operations.md`](topagent-v3-operations.md) | 日常启动、恢复和安全操作 |

### 历史/兼容文档

| 文档 | 状态 |
|---|---|
| [`reality-check.md`](reality-check.md) | 2026-08-06 v2 能力基线，已加历史标记 |
| [`implementation-roadmap.md`](implementation-roadmap.md) | v2 真实化路线图，部分已由 v3 完成 |
| [`code-reading-guide.md`](code-reading-guide.md) | Router 阅读指南，已更新 DPAPI 语义 |
| `操作日志-2026-08-*.md` | 历史构建日志，不应当作当前能力状态 |

## 14. `manju-studio/` 示例应用

| 文件/目录 | 作用 |
|---|---|
| [`ARCHITECTURE.md`](../manju-studio/ARCHITECTURE.md) | 应用架构说明 |
| `ARCHITECTURE-page.html` | 架构可视页面 |
| [`backend/main.py`](../manju-studio/backend/main.py) | 后端入口 |
| [`backend/config.py`](../manju-studio/backend/config.py) | 应用配置 |
| [`backend/models.py`](../manju-studio/backend/models.py) | 数据模型 |
| [`backend/api/routes.py`](../manju-studio/backend/api/routes.py) | API 路由 |
| [`backend/pipeline/orchestrator.py`](../manju-studio/backend/pipeline/orchestrator.py) | 视频任务编排 |
| [`backend/pipeline/scriptwriter.py`](../manju-studio/backend/pipeline/scriptwriter.py) | 脚本生成 |
| [`backend/pipeline/keyframe.py`](../manju-studio/backend/pipeline/keyframe.py) | 关键帧生成 |
| [`backend/pipeline/voiceover.py`](../manju-studio/backend/pipeline/voiceover.py) | 配音 |
| [`backend/pipeline/compositor.py`](../manju-studio/backend/pipeline/compositor.py) | 合成 |
| [`backend/pipeline/progress.py`](../manju-studio/backend/pipeline/progress.py) | 进度 |
| [`frontend/index.html`](../manju-studio/frontend/index.html) | 页面入口 |
| [`frontend/js/app.js`](../manju-studio/frontend/js/app.js) | 前端逻辑 |
| [`frontend/css/style.css`](../manju-studio/frontend/css/style.css) | 前端样式 |
| [`docker/Dockerfile`](../manju-studio/docker/Dockerfile) | 容器构建 |

推荐阅读：ARCHITECTURE → backend/main → routes → pipeline/orchestrator → 各处理步骤 → frontend。

## 15. `video-notes/` 示例应用

| 文件 | 作用 |
|---|---|
| [`README.md`](../video-notes/README.md) | 使用说明 |
| [`pipeline.py`](../video-notes/pipeline.py) | 总流程 |
| [`transcribe.py`](../video-notes/transcribe.py) | 转录 |
| [`keyframes.py`](../video-notes/keyframes.py) | 关键帧 |
| [`generate.py`](../video-notes/generate.py) | 笔记生成 |
| [`__init__.py`](../video-notes/__init__.py) | 包标识 |

推荐阅读：README → pipeline → transcribe/keyframes → generate。

## 16. `runtime/` 运行目录

该目录被 Git ignored，不应作为代码评审输入，却是运行验收的主要证据：

```text
runtime/
├── topagent.db          # SQLite 运行事实
├── secrets.enc          # Windows DPAPI 密文
├── artifacts/           # 内容寻址产物
├── workspaces/          # execution 工作区
└── traces/              # 预留 trace 文件目录
```

不要把 `runtime/` 直接复制进公共仓库。数据库备份和密钥迁移应分开处理，因为 DPAPI
密文绑定 Windows 用户。

## 17. 单一事实源矩阵

| 信息 | 权威事实源 | 派生/历史 |
|---|---|---|
| Agent 定义 | `.claude/agents/*.md` | SQLite `agents` |
| Skill 定义 | `.claude/skills/**/SKILL.md` | SQLite `skills` |
| Pipeline | `orchestrator/pipeline.json` | Skill frontmatter spawns、旧 state |
| Capability 声明 | `system/capabilities/*.json` | SQLite `capabilities` |
| Execution | SQLite `executions/events` | Dashboard/API |
| Message | SQLite `messages/deliveries` | v1 `memory/message-bus` 是历史 |
| Artifact | runtime ArtifactStore + DB hash | 普通裸文件不自动算证据 |
| 活跃记忆状态 | SQLite `memories` + canonical Markdown | v2 MEMORY/knowledge-graph 是历史知识 |
| Router | `router/config.yaml` + code | `memory/model-config.md` 是参考 |
| 密钥 | 环境变量 / DPAPI vault | Markdown/脚本禁止存值 |

## 18. 常用检索命令

```powershell
# 找文件
rg --files topagent tests system/capabilities

# 找统一执行入口
rg -n "class Dispatcher|def dispatch|def verify" topagent/runtime

# 找数据库表
rg -n "CREATE TABLE|CREATE VIRTUAL TABLE" topagent/core/database.py

# 找消息状态迁移
rg -n "queued|leased|processing|retry_wait|dead_letter" topagent/bus

# 找能力限制
rg -n '"limitations"|"status"|"maturity"' system/capabilities

# 找过时 v2 语义
rg -n "Agent\(subagent_type|message-bus/queue|api-keys.md.*Base64" .claude docs router
```

## 19. 修改代码时的影响范围

| 修改目标 | 同步检查 |
|---|---|
| ExecutionResult 字段 | database schema、Dispatcher、API、Dashboard、tests、capability |
| Message 状态 | store、MCP Schema、Scheduler、Dashboard metrics、tests |
| Agent frontmatter | Registry、pipeline 引用、top-agent Skill、init 结果 |
| Skill metadata | ProgressiveSkillLoader、Registry 重复 ID、Skill 文档 |
| Memory 状态 | DB schema、Markdown mirror、API、audit、tests |
| Secret 解析 | router/config、CLI、setup、secret scan、tests |
| Capability status | contract、verification command、evidence、Dashboard |
| pipeline step | v2 orchestrator、v3 adapter、TopAgent Agent/Skill、测试 |

## 20. 阅读结束后的自检问题

读完体系后应能回答：

1. Agent 文件和 Agent execution 有什么区别？
2. 一个裁决怎样证明验证者不是生产者？
3. worker 在处理消息时崩溃，消息怎样恢复？
4. 为什么 MCP 不是消息存储？
5. Skill 为什么不应全部加载进上下文？
6. 新记忆为什么先进入 candidate？
7. Capability 的 `implemented` 和 `L2-verified` 分别意味着什么？
8. 为什么 DPAPI 密文不能作为跨机密钥备份？
9. v2 orchestrator state 和 v3 runtime DB 为什么暂时并存？
10. 哪些证据仍不足以证明 TopAgent 已达到生产级多 Agent 平台？

如果这些问题无法从文件中找到直接证据，应优先补文档、测试或能力契约，而不是追加新的
角色 Prompt。
