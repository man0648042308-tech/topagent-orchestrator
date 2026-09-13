# 🧾 能力边界对照文档 — Claude Code 实际能做什么

> **历史基线（2026-08-06）**：本文保留 v2 当时的事实判断。v3 当前状态与可执行
> 证据请以 `docs/topagent-v3-acceptance.md` 和 `system/capabilities/*.json` 为准。

> **定位**：这不是对原文档的覆盖或否定，而是一份**诚实的能力地图**。
> 原 CLAUDE.md、agents/*.md、skills/*.md 的设计思想保留不变——
> 这份文档告诉你：在当前 Claude Code 运行环境中，哪些可以直接跑、哪些需要外部配合、哪些暂时只是蓝图。

**编写日期**：2026-08-06
**编写原因**：用户问「你能真实创立多 Agent 吗？能自主切换模型吗？我的 .claude 你能实现多少？」

---

## 0. 核心认知：你对话的不是 TopAgent

这是最容易误解的地方：

```
CLAUDE.md 说：
  🟠 TopAgent (组织交付者) → 10步流水线 → 调度所有子Agent
  "用 TopAgent 来执行"

实际情况：
  你对话的是 → Claude Code (由 deepseek-v4-pro 或 claude-opus 驱动)
       │
       ├── 它读取 CLAUDE.md 作为行为指南
       ├── 它可以调用 Agent 工具，以 "top-agent" 类型启动子 Agent
       └── 但它自己不是 TopAgent
```

**类比**：CLAUDE.md 是你给 Claude Code 的「岗位说明书」。Claude Code 会尽最大努力按照说明书行事，但它本身的工具箱、模型能力、运行机制是固定的，不能通过写一篇 Markdown 就改变底层。

---

## 1. 总体达成度

```
████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░
                                    约 70%
                            可在 Claude Code 内直接运作
```

| 层次 | 组件 | 达成度 | 说明 |
|------|------|--------|------|
| Agent 提示词 | 19 个 Agent 定义 | 🟢 95% | 所有 Agent 文件都生效——当我以对应类型启动子 Agent 时，它的 frontmatter（model/description）和 body 都会加载为系统提示词 |
| Skill 提示词 | 21 个 Skill 定义 | 🟢 90% | 可以通过 Skill 工具或自动触发来加载，改变我的行为模式 |
| 多 Agent 编排 | 并行启动 + 串行流水线 | 🟢 80% | 可以同时启动多个子 Agent，也可以通过 Workflow 工具做复杂编排 |
| 模型路由 | 跨平台/跨模型动态选择 | 🔴 10% | 只能在 Claude 家族（opus/sonnet/haiku/fable）内选择；不能真的调用 OpenAI/DeepSeek/通义千问 |
| 自动评分/淘汰 | 5 维加权评分 + D 级淘汰 | 🟡 40% | QA Agent 可以人工审核输出并打分，但没有程序化的自动化评分引擎 |
| 热替换/A-B 测试 | Agent 版本热替换 | 🔴 5% | Agent 文件可以手动编辑替换，但没有运行时的路由表、流量切换、并行 Shadow 运行 |
| MCP 消息总线 | Agent 间标准化通信 | 🟡 50% | mcp-bridge/server.py 存在但未作为独立中间件运行；Agent 间通信实际上靠文件读写 |
| 训练数据管道 | SFT/DPO/RLHF 数据导出 | 🟡 30% | 可以生成格式化的训练数据文件，但不能自动化采集、清洗、标注、训练 |

---

## 2. Agent-by-Agent 真实能力

### 🟢 第 1 层：即开即用（7 个）

这些 Agent 的工作 = 专门化提示词 + 标准工具调用。启动即生效，产出可直接用。

| Agent | 实际能做什么 | 限制 |
|-------|-------------|------|
| **architect-agent** | 读取项目结构 → 搜索技术方案 → 输出六层架构设计 + ADR + 接口规范 | 不能画图（只能 ASCII art 或 Mermaid 文本） |
| **frontend-agent** | 写 React/Vue/Next.js 组件、Tailwind CSS、状态管理、响应式布局 | 不能预览渲染结果 |
| **backend-agent** | 写 FastAPI/Django/Node.js API、数据库 schema、认证鉴权、缓存队列逻辑 | 不能启动服务器验证 |
| **ai-engineer-agent** | 写 LLM 调用代码、RAG pipeline、Prompt 模板、Agent 编排逻辑 | 不能接入真实的向量数据库或训练流程 |
| **test-agent** | 写 pytest/jest 测试用例、运行测试、生成覆盖率报告、Bug 报告 | 测试框架需要实际安装 |
| **devops-agent** | 写 Dockerfile、docker-compose、CI/CD 配置（GitHub Actions）、部署文档 | 不能执行 docker build 或 kubectl apply |
| **skill-hunter** | 搜索 GitHub/npm/PyPI、对比开源项目、五维验证（可用性/兼容性/活跃度/许可证/安全性） | 只能搜公开信息 |

### 🟡 第 2 层：模板生效但核心逻辑靠人工（8 个）

这些 Agent 的提示词会生效，但文档描述的「自动化」能力我做不了——需要人工判断或外部系统。

| Agent | 能做 | 不能做 |
|-------|------|--------|
| **top-agent** | 按 10 步流水线提示词逐步推进项目 | 不会自动编排——每步需要你或我手动触发；没有程序化的流水线引擎 |
| **delivery-director** | 按 10 条铁律驱动项目交付（搜索→架构→Agent编队→Dashboard→交付包） | 同上，流水线不是强制的 |
| **qa-agent** | 审查代码输出，按 5 维打分，给出改进建议 | 否决后不能真的「强制重构」或「自动替换 Agent」——我仍然听命于你，不是 QA Agent |
| **fact-check-agent** | Web 搜索 + 交叉验证 → 给出可信度评级 | 可信度是主观判断，不是程序计算的 |
| **failure-analysis-agent** | 分析错误日志、诊断根因、输出改进方案 | 不能自动触发（需要你或我主动调用）；不能真的「更新 QA 审核清单」 |
| **tool-manager** | 管理工具配置、注册新工具 | 不能动态注册新的进程级工具——只能编辑配置文件 |
| **data-curator-agent** | 生成 SFT/DPO/RLHF 格式的训练数据、清洗数据 | 不能自动化采集（需要你提供数据源）、不能接入训练平台 |
| **eval-benchmark-agent** | 运行对比测试、手工评估输出质量、输出 A/B 对比报告 | 没有程序化的基准测试框架；不能自动跑标准 benchmark |

### 🔴 第 3 层：概念设计 — 需要外部基础设施（4 个）

这些 Agent 的核心价值依赖 Claude Code 不具备的能力。

| Agent | 文档描述 | 现实差距 |
|-------|---------|---------|
| **model-router-agent** | 智能路由到 CSDN/百炼/硅基/DeepSeek/本地模型，故障转移链，成本优化 | Claude Code 只能调用 Anthropic 的模型。`model: "opus" \| "sonnet" \| "haiku" \| "fable"` 是唯一的模型选择自由度。不能调用 GPT-4o、通义千问、DeepSeek、本地 Ollama。路由矩阵表（第 68-82 行）在 Claude Code 内无法落地 |
| **agent-forge-agent** | Agent 热替换（<30秒）、A/B 测试、流量切换、Shadow Mode、依赖图自动检查 | Agent = Markdown 文件。替换 = 编辑文件。没有运行时路由表、没有流量控制、没有并行 Shadow 运行。依赖图只能人工维护 |
| **memory-learning-agent** | RAG 向量检索、知识图谱、陷阱模式自动预警、跨项目模式识别 | 知识 = Memory 目录的 Markdown 文件。没有向量数据库、没有图数据库。检索靠全文搜索。预警靠人工提醒 |
| **tool-manager** (MCP 部分) | MCP Bridge Server 作为独立中间件运行，JSON-RPC 消息路由，工具注册发现 | `mcp-bridge/server.py` 存在，但只是代码——它不是运行中的服务。Claude Code 自身的工具系统不通过它 |

---

## 3. Skill-by-Skill 真实能力

### 🟢 直接可用的 Skill

这些 Skill 通过加载专门化指令来改变我的行为——效果立即可见：

| Skill | 效果 |
|-------|------|
| github-research | 我会用 `gh` CLI + WebSearch 做开源项目调研 |
| env-scan | 我会盘点你的 OS/硬件/运行时/API Key |
| tech-selection | 我会输出多方案对比表 + 推荐 + 备选 + 不推荐 |
| code-review | 我会按结构化模板做代码审核 |
| bug-diagnosis | 我会走五步诊断法（日志→复现→定位→方案→验证） |
| agent-team-design | 我会按模板设计 Agent 编队 |
| skill-generator | 我会生成新的 Skill 定义文件 |
| project-delivery | 我会按 8 项交付物清单生成交付包 |
| project-closeout | 我会做项目收尾和总结 |
| auto-documentation | 我会生成项目文档 |

### 🟡 半可用

| Skill | 可用部分 | 不可用部分 |
|-------|---------|-----------|
| top-agent | 指令加载生效，我会按 10 步流水线行事 | 流水线不是程序化的——每步需手动推进 |
| delivery-director | 10 条铁律生效 | 8 阶段不能自动流转 |
| qa-agent | 加载审核视角 | 否决权在现实中受限于你（用户）的最终决定 |
| fact-check | 加载验证视角 | 三层验证中的「知识库」是 Claude 训练数据，不是你的本地知识库 |
| failure-analysis | 加载分析框架 | 不能自动触发 |
| memory-learning | 加载记忆视角 | 没有向量检索 |
| model-router | 加载路由思维 | 实际只能选 Claude 模型 |
| data-curator | 加载数据处理视角 | 不能接入训练 pipeline |
| eval-benchmark | 加载评估视角 | 没有自动化基准测试框架 |
| agent-forge | 加载 Agent 创建视角 | 没有热替换/A-B 测试/运行时路由 |
| tool-manager | 加载管理视角 | MCP bridge 不是运行中的服务 |

---

## 4. 架构组件真实状态

```
文档描述的架构                    实际状态

🟠 TopAgent (总指挥)             → 一种 Agent 类型 + 一个 Skill，可以用，但不会自主运行
🔀 Model Router                  → 只能选 opus/sonnet/haiku/fable，不能跨平台
🔴 QA Agent (最高权限)           → 提示词生效，但没有真正的「权限系统」（都取决于你）
🔵 Fact Check Agent              → 提示词生效，Web 搜索可用，但没有本地知识库
🟠 Failure Analysis              → 提示词生效，手动触发，不能自动触发
📊 评分系统(自动)                → 不存在自动化评分引擎
🔄 Agent Forge                   → 创建/编辑 Agent Markdown 文件可以，热替换/A-B/回滚不行
🔧 Tool Manager                  → MCP Bridge 是代码文件，不是运行中的服务
🏋️ Data Curator                  → 可生成训练数据格式，但不能接入训练流程
📄 Auto Documentation            → 可自动生成文档（这是能做到的）
📊 Eval/Benchmark                → 可手工对比，没有自动化框架
```

---

## 5. 什么真正起作用

### ✅ 你立刻可以这样用

```
1. 给我一个任务
     ↓
2. 我读取 CLAUDE.md 作为行为指南
     ↓
3. 按需要启动子 Agent（架构师/前端/后端/测试/DevOps...）
     ↓
4. 每个子 Agent 加载自己的提示词（agents/*.md）
     ↓
5. 子 Agent 调用工具（读写文件、搜索、运行命令）
     ↓
6. 我整合结果返回给你
```

### ✅ 多 Agent 并行是真实的

```python
# 这不是虚构——我真的可以同时启动多个 Agent：
Agent(subagent_type="architect-agent", description="设计数据库")
Agent(subagent_type="frontend-agent", description="写登录页")
Agent(subagent_type="test-agent", description="写测试")
# 这三个会并行运行，各干各的
```

### ✅ Workflow 工具可以做更复杂的编排

```
pipeline:  项目A → 架构师 → 前端 → 测试 → 审核 (串行流水线)
parallel:  [任务1, 任务2, 任务3] 同时执行 (并行屏障)
```

### ✅ Skill 体系是真实有效的

加载一个 Skill = 我的行为模式改变。例如加载 `code-review` Skill 后，我会按结构化模板审查代码。

---

## 6. 什么需要外部系统

以下能力**不是改文档能解决的**——需要写真正的代码（Python/Node.js 服务）：

| 能力 | 需要什么 |
|------|---------|
| 调用 GPT-4o / DeepSeek / 通义千问 | 一个 API 路由中间件（你说不能切换模型的原因是 Claude Code 本身只调 Anthropic API；但你可以写一个 MCP 工具来桥接其他 API） |
| 自动化 Agent 评分系统 | 一个评分引擎服务，能在每次 Agent 完成后自动运行 Eval |
| Agent 热替换 / A-B 测试 | 一个 Agent Registry 服务 + 流量路由器 |
| 知识图谱 + 向量检索 | 一个数据库（Neo4j + Chroma/Milvus）+ 索引服务 |
| 训练数据管道 | 数据采集脚本 + 清洗 pipeline + 格式导出工具 |
| 自动化流水线 | 一个 Pipeline Engine（类似 Airflow/Temporal） |

这些都是**可实现的**——只是不在 Claude Code 内部。你需要把它们作为独立的后端服务搭建。

---

## 7. 建议

### 短期（现在就能做）

1. **继续用 Agent 体系**——19 个 Agent 作为提示词模板非常有效
2. **多 Agent 并行**是真实威力——复杂任务拆解后并发执行
3. **Skill 体系**作为行为模式切换非常实用

### 中期（需要写一些代码）

4. **MCP Bridge** — `mcp-bridge/server.py` 可以作为真正的 MCP 工具接入 Claude Code，实现 Agent 间消息传递
5. **知识库** — 把 memory/*.md 导入一个向量数据库，配合 embedding 做真正的 RAG 检索

### 长期（需要独立后端）

6. **API Gateway** — 写一个模型路由中间件，统一接入 OpenAI/Anthropic/DeepSeek/通义千问，然后通过 MCP 工具暴露给 Claude Code
7. **Pipeline Engine** — 把 10 步流水线写成程序化的编排引擎，Claude Code 作为其中一个执行节点
8. **Agent Registry** — 带版本管理和 A/B 测试的 Agent 服务注册中心

---

## 8. 一句话总结

> **你的文档设计了一个「AI 软件工厂」的蓝图。Claude Code 可以实现其中 70%——所有涉及「提示词模板 + 文件操作 + 搜索 + 命令执行」的部分。剩下 30% 需要一个独立的后端系统来承载：模型路由网关、评分引擎、向量知识库、流水线编排器。两种不矛盾——Claude Code 是这个工厂里最聪明的一个工人，但它不是整座工厂。**
