# 🏗️ TopAgent 体系真实化路线图

> **历史路线图（2026-08-06）**：其中一部分已由 TopAgent v3 落地。当前实现与剩余
> 边界请查阅 `docs/topagent-v3.md` 和 `docs/topagent-v3-acceptance.md`。

> **目标**：从「提示词模板集合」进化为「真正可运行的 AI 软件工厂」
> **原则**：渐进式——每一阶段都有可用的产出，不追求一步到位
> **日期**：2026-08-06

---

## 前置：先解决架构冲突

### 当前问题

```
4 份文件都声称自己是「TopAgent 的核心」：
  .claude/skills/top-agent.md       → 入口唤醒器 → 切换为 delivery-director
  .claude/agents/top-agent.md       → 10步流水线，自称"组织交付者"
  .claude/skills/delivery-director.md → 8阶段流程
  .claude/agents/delivery-director.md → 8阶段流程 + 10原则

冲突：谁是真的总指挥？10步 vs 8阶段哪个是标准流程？
```

### 建议方案：合并为单一指挥链

```
🟠 TopAgent = 唯一总指挥（合并 top-agent.md）
   │
   ├── 标准流程：统一为 8 阶段（保留 10 步中的 Step 8.5 反失败 + Step 10 进化）
   │
   ├── 🗑️ 废弃 delivery-director 作为独立 Agent（内容合并到 top-agent）
   │
   └── delivery-director Skill → 改名为 "project-bootstrap"（项目启动器）
       只负责阶段 1-4（需求→搜索→环境→方案），阶段 5-8 交还给 TopAgent
```

**这样**：
- TopAgent = 唯一入口，唯一权威
- delivery-director 降级为启动阶段的辅助 Skill
- 不再有「两个都说了算」的混乱

> ⚠️ 这一步需要你确认。我可以立即执行合并。

---

## Phase 1：夯实基础（本周可完成）

### 1.1 统一 Agent 模板规范

**现状**：19 个 Agent 文件 frontmatter 格式不一致：
- 有些有 `model_requirements`，有些没有
- 有些有 `preferred_models`（写到 CSDN/百炼但实际用不了）
- `model` 字段随意指定

**改进**：统一 frontmatter 为实际可用的格式：

```yaml
---
name: architect-agent
description: 一句话描述
color: "#HEX"
model: sonnet          # 只能填 opus|sonnet|haiku|fable
version: 1.0.0
depends_on: []         # 依赖的其他 Agent（仅用于文档，无运行时强制）
capability_tags: ["architecture", "system-design"]
---
```

### 1.2 删除不可用的 model_requirements

当前约 8 个 Agent 的 frontmatter 里写了 `preferred_models: ["deepseek-v4-pro", "qwen3-coder-plus", ...]`——这些在 Claude Code 中完全无效，反而造成「体系很强大」的错觉。

**改进**：删除所有 `model_requirements` 和 `preferred_models` 中非 Claude 模型的引用。保留为注释供未来使用。

### 1.3 清理 CLAUDE.md

当前 CLAUDE.md 的架构图包含 Model Router、MCP 协议层等暂时不可用的组件。建议标注状态：

```markdown
├── 🔀 Model Router      🟡 [Phase 3 实现]
├── 🔧 MCP 协议层         🟡 [Phase 2 实现]
├── 📊 评分系统(自动)     🟡 [Phase 4 实现]
```

---

## Phase 2：MCP Bridge 上线（2-4 周）

### 目标

让 `mcp-bridge/server.py` 真正跑起来，成为 Agent 间通信的中枢。

### 当前状态

```
mcp-bridge/server.py  ← 代码存在，但未配置为 MCP Server
memory/message-bus/    ← 目录存在，但没有实际消息流转
```

### 实施步骤

**Step 1**：验证 server.py 能独立运行

```powershell
python mcp-bridge/server.py --test
```

**Step 2**：配置为 Claude Code 的 MCP Server

在 `.claude/settings.json` 中添加：
```json
{
  "mcpServers": {
    "topagent-bus": {
      "command": "python",
      "args": ["./mcp-bridge/server.py"],
      "env": {}
    }
  }
}
```

**Step 3**：定义首批 MCP Tools

```python
# server.py 中新增/完善的工具：
- send_message(agent_from, agent_to, payload) → 发送消息
- query_messages(agent_id, limit) → 查询消息
- register_agent(agent_id, capabilities) → 注册 Agent
- get_agent_status(agent_id) → 查询状态
- report_task_result(agent_id, task_id, result) → 报告任务结果
```

**Step 4**：修改 Agent 提示词，让它们知道可以通过 MCP 通信

在每个 Agent 的 `.md` 文件中添加：
```markdown
## 通信方式
当你需要与其他 Agent 协作时，使用 `topagent-bus` MCP 工具发送消息。
```

### 产出

- ✅ Agent 间可以通过消息总线通信（不再是纯文件读写）
- ✅ 可以追踪哪个 Agent 在处理什么任务
- ✅ 为后续的流水线引擎打下基础

---

## Phase 3：模型路由器（4-6 周）

### 目标

实现真正的跨平台模型路由——这是你体系中最核心但当前完全缺失的能力。

### 方案：API 代理中间件

```
Claude Code
    │
    │  调用 MCP Tool: route_task(task, requirements)
    ▼
┌─────────────────────────────────┐
│  Model Router (Python FastAPI)   │
│                                  │
│  输入：任务类型 + 约束条件        │
│  输出：选择最优模型 + 执行调用    │
│                                  │
│  已接入：                        │
│  ├── Anthropic API (Claude)      │
│  ├── OpenAI API (GPT-4o)         │
│  ├── DeepSeek API                │
│  ├── 通义千问 API (百炼)         │
│  └── 本地 Ollama                 │
│                                  │
│  路由逻辑（来自你的 model-router  │
│  agent 设计，但写成真实代码）：   │
│  ├── 任务分类 → 候选模型筛选     │
│  ├── 多因子评分 → 最优选择       │
│  ├── 故障转移链                  │
│  └── 成本追踪                    │
└─────────────────────────────────┘
```

### 实施步骤

**Step 1**：创建 `router/` 目录结构

```
router/
├── server.py          # FastAPI 主服务
├── router.py          # 路由决策引擎
├── providers/         # 各平台适配器
│   ├── anthropic.py
│   ├── openai.py
│   ├── deepseek.py
│   ├── qwen.py
│   └── ollama.py
├── config.yaml        # API Keys + 模型配置
├── cost_tracker.py    # 成本追踪
└── fallback.py        # 故障转移
```

**Step 2**：实现核心路由逻辑（伪代码）

```python
def route(task_type: str, complexity: str, max_cost: float) -> RouteDecision:
    candidates = filter_models(task_type, complexity)
    scored = multi_factor_score(candidates)
    primary = scored[0]
    fallback_chain = scored[1:3]
    return RouteDecision(primary, fallback_chain, estimated_cost)

def multi_factor_score(models):
    return sorted(models, key=lambda m: (
        m.capability_match * 0.40 +
        (1 - m.cost_per_1k / max_cost) * 0.25 +
        (1 - m.avg_latency / 5000) * 0.20 +
        m.historical_success_rate * 0.15
    ), reverse=True)
```

**Step 3**：暴露为 MCP Tool

Claude Code 通过 MCP 调用：
```
Tool: route_and_execute
Params: { task_prompt, task_type, complexity, max_cost }
Returns: { model_used, response, cost, latency }
```

### 产出

- ✅ 真正可以调用 GPT-4o、DeepSeek、通义千问
- ✅ 你的 `model-capability-matrix.md`（7维模型评分）成为路由决策的真实数据源
- ✅ 故障转移自动生效

---

## Phase 4：知识库向量化（4-6 周）

### 目标

把 `memory/` 目录的 Markdown 文件变成可语义检索的知识库。

### 方案

```
memory/*.md (现有 12 个文件 + 持续增长)
      │
      ▼
  Embedding (text-embedding-3-small 或本地 BGE)
      │
      ▼
  Chroma / Milvus Lite (向量数据库)
      │
      ▼
  MCP Tool: search_knowledge(query) → 相关经验
```

### 实施步骤

**Step 1**：写索引脚本

```python
# knowledge_base/indexer.py
def index_all_memory_files():
    for md_file in Path("memory").glob("*.md"):
        chunks = split_markdown(md_file)
        embeddings = embed(chunks)
        chroma_collection.add(embeddings, metadata, chunks)
```

**Step 2**：写检索 MCP Tool

```python
# 暴露给 Claude Code 的 MCP 工具
def search_knowledge(query: str, top_k: int = 5):
    """
    语义搜索所有历史经验和知识
    返回最相关的经验片段
    """
    embedding = embed(query)
    results = chroma_collection.query(embedding, n_results=top_k)
    return results
```

**Step 3**：在 Agent 提示词中引用

```markdown
## 知识检索
在启动任何新任务前，先调用 `search_knowledge` 检查历史经验。
特别是 [[trap-patterns]] 中记录的已知陷阱。
```

### 产出

- ✅ memory-learning Agent 的「RAG 经验检索」从概念变为现实
- ✅ 「陷阱模式预警」真正可用——新项目启动时自动检索已知陷阱
- ✅ 知识不会随着 memory 文件增多而淹没

---

## Phase 5：流水线引擎（6-8 周）

### 目标

把「10 步流水线」从 Markdown 描述变成程序化的状态机。

### 方案

```
Pipeline Engine (Python)
      │
      ├── State Machine: 管理流水线步骤和状态转换
      ├── Task Queue:    管理待执行任务
      ├── Agent Pool:    管理可用 Agent 和它们的负载
      └── Dashboard API: 实时状态查询
```

### 核心设计

```python
# pipeline/engine.py

class PipelineState(Enum):
    REQUIREMENT = 1     # 需求理解
    ANALYSIS = 2        # 分析拆解
    RESEARCH = 3        # 研究检索
    PLANNING = 4        # 规划架构
    TEAM_BUILD = 5      # 组建团队
    ASSIGN = 6          # 分配任务
    EXECUTE = 7         # 监督执行
    QA_REVIEW = 8       # 质量审核
    FAILURE_ANALYSIS = 8.5  # 反失败（条件触发）
    SUMMARIZE = 9       # 总结学习
    EVOLVE = 10         # 能力进化

class PipelineEngine:
    def __init__(self):
        self.state = PipelineState.REQUIREMENT
        self.transitions = {
            PipelineState.REQUIREMENT: [PipelineState.ANALYSIS],
            PipelineState.QA_REVIEW: [PipelineState.SUMMARIZE, PipelineState.FAILURE_ANALYSIS],
            # ...
        }
    
    def advance(self, trigger: str):
        """状态转换 + 自动触发对应 Agent"""
        next_state = self.transitions[self.state][0]
        if next_state == PipelineState.RESEARCH:
            spawn_agent("skill-hunter")  # 自动触发 Skill Hunter
        elif next_state == PipelineState.QA_REVIEW:
            spawn_agent("qa-agent")      # 自动触发 QA
        self.state = next_state
```

### 与 Claude Code 的集成

```
用户 → Claude Code → MCP Tool: pipeline.advance()
                   → MCP Tool: pipeline.get_dashboard()
                   → MCP Tool: pipeline.spawn_agent()
```

### 产出

- ✅ 「10 步流水线不可跳过任何一步」从提示词约束变成代码强制
- ✅ Step 8.5 反失败机制自动触发（QA 连续否决 → 自动启动 Failure Analysis）
- ✅ Dashboard 实时更新（不再是每次手工输出 Markdown 表格）

---

## Phase 6：评分与进化系统（长期）

### 目标

Agent 5 维评分从人工判断变成半自动化。

### 方案

```
评分引擎（Python）
  ├── 自动化维度：代码质量(linter)、测试覆盖率(coverage)、安全漏洞(scanner)
  ├── 半自动维度：功能正确性(人工QA + 测试结果)、可维护性(复杂度分析)
  └── 输出：评分报告 → 写入 Agent Registry → D 级自动标记淘汰
```

### 实施

```python
# scoring/engine.py
def score_agent_output(agent_id, task_id, output):
    return {
        "functionality": auto_test_pass_rate(output),  # 自动化
        "code_quality": lint_score(output),             # 自动化
        "security": vuln_scan(output),                  # 自动化
        "performance": benchmark(output),               # 自动化
        "maintainability": complexity_analysis(output), # 自动化
        "total": weighted_score(...)
    }
```

---

## 时间线总览

```
2  │ ████████ 前置：解决 TopAgent/Delivery-Director 冲突 + 统一模板
4  │ ████████ Phase 1：夯实基础（清理 frontmatter、标注能力边界）
8  │ ████████████████ Phase 2：MCP Bridge 上线运行
14 │ ██████████████████████████ Phase 3：模型路由器
16│ ██████████████████████████ Phase 4：知识库向量化（可与 Phase 3 并行）
24│ ████████████████████████████████████ Phase 5：流水线引擎
+  │ ████████████████████████████████████████████ Phase 6：评分与进化
```

## 最小可行版本（MVP）

如果你不想等那么久，这是**最少步骤让体系「活起来」**的方案：

1. **解决 TopAgent 冲突**（1 小时）— 合并为单一指挥链
2. **清理 Agent frontmatter**（1 小时）— 删掉不可用的 model_requirements
3. **启动 MCP Bridge**（1 天）— 让 Agent 间能发消息
4. **写一个最简单的模型路由脚本**（1 天）— 先只接 DeepSeek API（因为当前就用 deepseek-v4-pro）

做完这 4 步，你就有了：
- 一个清晰的指挥体系
- Agent 间消息传递
- 至少可以切换 2 个真实模型

这是从「纯文档」到「真实系统」的关键一跃。

---

## 下一步

你确认哪条路线？
- **A**：先解决前置问题（合并 TopAgent/Delivery-Director）+ 清理 frontmatter（今天就能完成）
- **B**：A + 立即启动 MCP Bridge
- **C**：告诉我你最先想要哪个能力，我帮你排优先级

