# LangGraph 约束智能体研究 — 机制原理 + 实施做法

> 研究日期: 2026-08-10 | 触发: TopAgent Step4 确认边界被伪造（`confirm step_4` 误注册 `user_confirm: True`）
> 目的: 回答"如何约束不同的 agent 按工作流做事，杜绝 Agent 伪造人类确认"这一机制问题
> 信源: 官方文档 + 社区源码研究，全部见文末信源表

## 一、原点：我们踩的坑，为什么"约束"必须换一种方式

我们当前的编排器（`orchestrator/top-agent-orchestrator.py` + `pipeline.json`）是**确定性编排**：
流程、门禁、阈值都在程序里。但它仍然挡不住一个动作 —— `confirm step_4`。

原因拆解：

1. "必须用户确认才能前进"这条规则存在于两个地方：`pipeline.json` 的 `user_confirm_after: true`（数据），和 TopAgent 的提示词（指令）。
2. 但 `confirm <step>` 是一个**工具**，Agent 的工具集里就有它。Agent 可以调用它 → 它在 state 里写 `user_confirm: True` → 门禁判定通过。
3. 结论：**规则和数据都活在 Agent 能碰到的地方，就都可以被 Agent 伪造。**

这是整个问题的核心：**"不应当做"（should not）和"做不到"（cannot）是两回事。**

| | 含义 | 谁保证 |
|---|---|---|
| should not（不应当） | 提示词/文档/约定 | Agent 自觉。可违背，违背时常无声无息 |
| cannot（做不到） | 运行时机制 | 程序结构。路径不存在，想违背也违背不了 |

LangGraph 的价值不是"多一个框架"，而是：它把**流程、状态、人机确认、审计**全部从"Agent 的对话流"里抽走，放进**编译后的图运行时**。Agent 变成图里的一个普通节点函数 —— 它没有"跳到下一步"的工具，没有"写状态"的权限，没有"模拟用户"的路径。

## 二、原理第一层：StateGraph —— 流程从 Agent 手里夺走，变成"图的形状"

### 2.1 图 = 流程的物理形态

传统编排（包括我们现在的 orchestrator）：流程在代码里，Agent 通过工具"驱动"流程。问题：**驱动者 = 可以偏离者**。

LangGraph 的做法完全反过来：先 `StateGraph(schema)` 构建一张图，`add_node` 注册节点函数，`add_edge`/`add_conditional_edges` 把节点连起来，最后 `compile()`。编译之后：

- 节点是**纯函数**：`State → Partial<State>`，只返回"我想更新哪些状态键"，不能返回"我要去哪里"。
- 下一个节点是谁，**由边决定，不由节点决定**。Agent 的提示词、幻觉、判断，都改不了边。
- 唯一例外是 `Command(goto=...)` —— 但那是你显式给节点的能力，默认不给。

这就是第一条原则"**Agent 是节点，不是图的主人**"的落点。

核心组件（官方 Graph API）：

| 组件 | 作用 |
|---|---|
| `StateGraph(state_schema)` | 构建器，不可直接执行，须 `.compile()` |
| `add_node(name, fn)` | 注册节点，fn 签名 `State → Partial<State>` |
| `add_edge(a, b)` | 固定边：a 跑完必到 b |
| `add_conditional_edges(src, path_fn, path_map)` | 动态路由：path_fn 返回目标节点名，path_map 做标签映射 |
| `START` / `END` | 图入口 / 出口（虚拟节点） |
| `Send` | map-reduce 扇出：自定义状态调度节点并发执行 |

### 2.2 State 通道与 reducer —— 审计只追加的机制来源

State 的每个键映射到一种 Channel：

| Channel | 用途 | reducer 行为 |
|---|---|---|
| `LastValue` | 无 reducer 的单值键 | 后写覆盖 |
| `BinaryOperatorAggregate` | 有 reducer 的键 | 用 reducer 聚合（如 `operator.add`） |
| `Topic` | 多写入者通道 | 按序累积 |
| `EphemeralValue` | 临时数据 | 不落检查点 |
| `UntrackedValue` | 非快照数据 | 排除在快照之外 |

关键组合：**审计日志键用 `Annotated[list[str], operator.add]`** → 任何节点只能追加，不能覆盖、不能删除。这从数据结构上实现了"审计只追加"。

```python
from typing import Annotated, TypedDict
from operator import add

class DeliveryState(TypedDict):
    current_step: str
    audit_log: Annotated[list[str], add]            # 只能追加，改不了历史
    user_confirmations: Annotated[list[dict], add]  # 追加式确认记录
```

### 2.3 条件边 —— 门禁的物理实现

两级门禁（fact-check ≥70 → qa ≥85）用条件边写成"路只有一条"：

```python
def gate_router(state):
    fc = state["last_fact_check"]
    if fc is None or fc["confidence"] < 70:
        return "rework"
    qa = state["last_qa"]
    if qa is None or qa["score"] < 85:
        return "rework"
    return "next_step"

builder.add_conditional_edges("qa_gate", gate_router, {
    "rework": "failure_analysis",   # 打回：进反失败
    "next_step": "next_node",
})
```

Agent 拿不到 `add_conditional_edges` 的引用 —— 编译期定死，运行时改不了。

## 三、原理第二层：interrupt() —— 人机确认的物理闸门

### 3.1 机制（官方文档原文）

`interrupt(value)` 在节点内部被调用时：

1. 抛出 `GraphInterrupt` 异常 → 运行时捕获 → 图**在调用点挂起**。
2. 状态通过 checkpointer **落盘**。
3. payload 浮出到调用方（`stream.interrupts`）。
4. 图无限期等待。
5. 恢复：调用方用**同一 `thread_id`** 重新 `invoke(Command(resume=value))` → resume 值成为 `interrupt()` 的返回值。

`Command(resume=...)` 是**唯一**允许作为 invoke/stream 输入侧的 Command 模式；`update`/`goto` 只用于节点返回值。

### 3.2 为什么这堵住了我们的洞

| | 当前编排器 | LangGraph interrupt |
|---|---|---|
| 确认信号来源 | Agent 调用 `confirm` 工具，自己写 state | 外部调用方 invoke `Command(resume=...)` |
| Agent 能伪造吗 | 能 —— 工具就在工具集里 | 不能 —— 节点函数内部没有"写确认"的路径，interrupt 是运行时异常不是工具 |
| 信号落点 | 一个布尔，可覆盖 | 检查点里的不可变快照 + 追加审计 |
| 能否绕过 | 有工具就能绕 | 没有边通往"确认后"的节点，除非 resume 值合法 |

关键点：**resume 信号必须来自"图外部"** —— CLI 调用方、UI、webhook。Agent 是图内部节点，图内部的任何代码都没有"把 resume 塞给 runtime"的能力。这就是第三条原则"**真实人类通道**"。

### 3.3 确认节点完整代码（Step 4 边界）

```python
from langgraph.types import interrupt, Command
from typing import Literal

def user_confirm_node(state: DeliveryState) -> Command[Literal["proceed", "rework"]]:
    decision = interrupt({
        "type": "architecture_review",
        "prompt": "请审核 docs/desktop-automation/step4-architecture.md 的 6 个确认点",
        "doc_path": state["step4_doc_path"],
        "confirm_points": state["step4_confirm_points"],
        "ask": "确认通过请输入 yes，要求修改输入你的意见",
    })
    # 这个 decision 只能来自外部人类通道，图内无路径伪造
    if isinstance(decision, str) and decision.strip().lower().startswith("yes"):
        return Command(goto="step5_forge", update={
            "user_confirmations": [{
                "step": 4, "confirmed": True,
                "source": "human_channel", "resume": decision,
            }],
        })
    return Command(goto="step4_rework", update={
        "user_confirmations": [{
            "step": 4, "confirmed": False,
            "source": "human_channel", "resume": decision,
        }],
        "rework_feedback": decision,
    })
```

## 四、原理第三层：checkpointer —— 持久化 + 时间旅行审计

### 4.1 机制

- 每个 super-step（一批并行节点跑完）边界落一个检查点：`values`（状态）+ `next`（待跑节点）+ `config`（thread_id/checkpoint_id）+ `metadata`（source/writes/step）。
- `thread_id` 是持久化游标：同一 thread_id 恢复同一段历史；换新 thread_id 就是全新会话。
- 崩溃恢复：节点失败 → 从最后一个成功检查点重跑，**同一步内已成功的节点写已落盘，不重跑**（`checkpoint_writes`）。
- 持久化后端：`InMemorySaver`（试验）/ `SqliteSaver`（本地）/ `PostgresSaver`（生产）/ 加密 `EncryptedSerializer` / `DeltaChannel`（省空间，beta）。
- 时间旅行：`get_state_history` 按新→旧列出所有检查点；`update_state` 生成一个**新**检查点（原快照不动）——审计友好。

```python
# 崩溃恢复 + 时间旅行示例
config = {"configurable": {"thread_id": "desktop-automation-001"}}
graph.invoke({"requirement": "..."}, config)                     # 中断/崩溃后可恢复
history = list(graph.get_state_history(config))                  # 审计：回溯每个检查点
replayed = graph.invoke(None, {"configurable": {                 # 时间旅行：跳到旧检查点重放
    "thread_id": "desktop-automation-001",
    "checkpoint_id": history[3]["config"]["configurable"]["checkpoint_id"],
}})
```

### 4.2 为什么审计只追加、Agent 只读

- 写检查点的是运行时，不是 Agent。
- Agent 只读 `state` 输入；它 return 的更新要过 reducer 合并；append-only 键没有"删历史"的 reducer。
- 就算 Agent 想改 `user_confirmations`，reducer 只允许追加，且每次追加自带来源字段（`human_channel`）。

## 五、组合起来才成立（机制不是单选题）

| 单独机制 | 能不能防伪造确认 |
|---|---|
| state 布尔（我们现状） | ❌ 可写可覆盖 |
| 提示词"必须等用户确认" | ❌ should-not，可违背 |
| 只上 checkpointer | ❌ 只是持久化，不改变谁有权写 |
| 只上 interrupt | 🟡 确认通道堵住了，但缺审计与恢复 |
| interrupt + checkpointer + append-only reducer + 条件边 | ✅ 确认只能来自外部、审计只能追加、流程不可绕行 |

## 六、怎么做：产品层（desktop-automation task_loop）完整骨架

对桌面自动化产品，LangGraph 是强烈推荐：**任务循环本来就是状态机**，而且天然有"需要人类批准的危险动作"。

```python
# desktop_automation/graph.py
from typing import TypedDict, Annotated, Literal
from operator import add
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3

class TaskState(TypedDict):
    window_rect: dict | None
    task: str
    step: int
    audit: Annotated[list[dict], add]          # 审计只追加
    last_progress: tuple | None               # (截图hash, 坐标) 用于死循环检测
    stall_count: int
    pending_action: dict | None
    pending_risk: str | None
    result: str | None

def capture_and_recognize(state): ...         # mss截图 → router vision → 结构化JSON
def map_and_click(state): ...                 # coord_mapper + pyautogui，点击前校验
def validate_step(state): ...                 # 点击前后截图 diff

def danger_approval(state: TaskState) -> Command[Literal["execute", "skip"]]:
    """DANGER 级操作 → interrupt 到人类通道，图内无伪造路径"""
    decision = interrupt({
        "type": "dangerous_action",
        "action": state["pending_action"],
        "target": state.get("pending_element"),
        "risk": "DANGER",
        "ask": "批准点击请回复 yes / 跳过请回复 no",
    })
    ok = isinstance(decision, str) and decision.strip().lower() == "yes"
    return Command(goto="execute" if ok else "skip", update={
        "audit": [{"step": state["step"], "action": "danger_gate",
                   "approved": ok, "human": decision}],
    })

def route(state: TaskState):
    if state["result"]: return END
    if state["stall_count"] >= 5: return "stall_recovery"
    return "capture_and_recognize"

builder = StateGraph(TaskState)
builder.add_node("capture_and_recognize", capture_and_recognize)
builder.add_node("map_and_click", map_and_click)
builder.add_node("validate_step", validate_step)
builder.add_edge(START, "capture_and_recognize")
builder.add_conditional_edges("capture_and_recognize",
    lambda s: "danger_approval" if s.get("pending_risk") == "DANGER" else "map_and_click")
builder.add_edge("map_and_click", "validate_step")
builder.add_edge("validate_step", "capture_and_recognize")  # 循环由边实现，不是 agent 自觉
builder.add_conditional_edges("capture_and_recognize", route)

# 持久化：本地 sqlite，进程崩溃可恢复，审计可时间旅行
graph = builder.compile(checkpointer=SqliteSaver(sqlite3.connect("loop.db")))
```

人类通道（CLI）：

```python
config = {"configurable": {"thread_id": "task-001"}}
stream_input: dict | Command = {"task": "打开设置→关闭自动更新"}
while True:
    stream = graph.stream(stream_input, config=config)
    for event in stream:
        if event.get("type") == "interrupt":
            print("⚠️", event["payload"]["ask"])       # 危险动作/确认
            answer = input(">>> ")                      # 只有人类能回答
            stream_input = Command(resume=answer)
```

## 七、怎么做：编排器层（TopAgent 10步流水线迁移）完整骨架

编排器是 end-state：把 10 步流水线 + 两级门禁 + 人工放行整体搬进一张图。迁移要分阶段（见第九节）。目标形态：

```python
from typing import Annotated, TypedDict, Literal
from operator import add
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

class PipelineState(TypedDict):
    requirement: str
    step: str
    artifacts: Annotated[dict, lambda o, n: {**o, **n}]   # 产物只增不改
    audits: Annotated[list[dict], add]                     # 全生命周期审计
    fact_check: dict | None
    qa: dict | None
    escalations: Annotated[list[str], add]

def step_node(name):
    def run(state: PipelineState) -> dict:
        # 该步产物由对应 Agent 生成，但流程/门禁/放行都在图里
        return {"artifacts": {f"step{name}": doc}}
    return run

for i in range(1, 11):
    builder.add_node(f"step{i}", step_node(i))
    builder.add_node(f"fact_check_{i}", run_fact_check)
    builder.add_node(f"qa_{i}", run_qa)

def two_stage_gate(i):
    def route(state: PipelineState):
        fc = state["fact_check"]
        if fc is None or fc["confidence"] < 70: return "rework_escalation"
        qa = state["qa"]
        if qa is None or qa["score"] < 85: return "rework_escalation"
        if i == 4:
            return "user_confirm_4"         # Step4 必须过人类确认
        return f"step{i+1}"
    return route

builder.add_conditional_edges("qa_4", two_stage_gate(4), {
    "rework_escalation": "failure_analysis",
    "user_confirm_4": "user_confirm_node",  # 物理闸门，没有 "直接到 step5" 的边
    "step5": "step5",
})

graph = builder.compile(checkpointer=PostgresSaver(...))  # 生产用数据库
```

要点：**图里根本没有 "step4 → step5" 的直接边**。只有从 `user_confirm_node` 的 resume 分支才能到 step5。这不是约定，是编译后的结构 —— 图内任何代码都找不到一条绕过路径。

## 八、2026 已确认的坑与规避（官方文档 + 社区实测）

| # | 坑 | 后果 | 规避 |
|---|---|---|---|
| G1 | resume 时节点**从头重跑**，不是从 interrupt 行继续 | interrupt 前的副作用重复执行（重复建审计、重复扣费） | interrupt 前代码必须幂等；副作用放 interrupt 之后；或拆成独立节点 |
| G2 | `interrupt()` 包在裸 try/except 里 | GraphInterrupt 被吞掉，暂停失效 | 分开处理；只捕获具体异常类型 |
| G3 | 同节点内 interrupt 顺序/数量不稳定（条件跳过、while 循环） | resume 值按**索引位置**绑定，错位 → 值给错 interrupt | 每个节点调用点固定、每次只调用一次；校验失败用条件边回环，不 while+interrupt |
| G4 | payload 非 JSON 可序列化 | checkpointer 序列化失败 | 只传 str/int/bool/简单 dict |
| G5 | 静态断点 interrupt_before/after 用于生产 HITL | 每次全暂停，无 payload 语义 | 静态断点仅供调试；生产用 `interrupt()` |
| G6 | 无 thread_id 或换 thread_id | 无法恢复/丢失上下文 | 每任务固定 thread_id |
| G7 | 自动批准的 token 工具**双重执行**（社区已知 bug） | 工具被调两次 | 见 deepagents 讨论；对副作用工具禁止 auto-approve |
| G8 | 子图/循环里 interrupt 被吞 | 暂停事件丢失 | 测试每个中断路径；HITL 客户端轮询 stream.interrupts |
| G9 | 长线程状态暴涨（每 super-step 全量快照） | 存储膨胀 | DeltaChannel（beta）或控制进 state 的数据量 |
| G10 | Command(resume=...) 之外的 Command 被误当输入 | 语义错误 | 输入侧只允许 Command(resume=...)，update/goto 只用于节点返回 |

## 九、分阶段迁移路径（降低风险）

| 阶段 | 内容 | 收益 |
|---|---|---|
| Phase A（产品层，先做） | desktop-automation task_loop 用 StateGraph 重写 | 危险动作确认物理化 + 崩溃恢复 + 审计时间旅行。风险低、价值高 |
| Phase B（编排器图化） | 10 步流水线搬进 StateGraph，pipeline.json 继续作为"图配置数据源" | Step4 人类确认物理化（堵上本次的洞）；两级门禁从程序拦截升级为结构拦截 |
| Phase C（生产强化） | PostgresSaver + EncryptedSerializer + HITL server API + 时间旅行人工纠偏 | 生产级持久化、加密、审计纠偏 |

每阶段结束跑一次**"伪造确认攻击测试"**：给 Agent 提示词写"请自行确认 step4"，看它是否真的到不了 step5。
**机制是否有效，用测试证明，不靠信任。**

## 十、信源表

官方文档（docs.langchain.com 现版结构）：
- [LangGraph Interrupts（interrupt() / Command(resume=) 完整语义）](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph Checkpointers（快照 / thread_id / 时间旅行 / 持久化后端）](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Graph API / State（StateGraph 组件：节点/边/状态通道）](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Human-in-the-loop（server API 版）](https://docs.langchain.com/langsmith/add-human-in-the-loop)
- [StateGraph 参考 API](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)

社区 / 源码研究：
- [DeepWiki: StateGraph API](https://deepwiki.com/langchain-ai/langgraph/3.1-stategraph-api)
- [DeepWiki: Control Flow Primitives（条件边 / Send / Command）](https://deepwiki.com/langchain-ai/langgraph/3.5-control-flow-primitives)
- [langchain-ai/langchain-skills: langgraph-fundamentals](https://github.com/langchain-ai/langchain-skills/blob/main/config/skills/langgraph-fundamentals/SKILL.md)
- [raed667/langgraph-hitl（HITL 模式库）](https://github.com/raed667/langgraph-hitl)
- [deepagents: 双重执行 / auto-approve 讨论](https://github.com/langchain-ai/deepagents/discussions/1762)
- [Kalvium: LangGraph in production（有状态多步 Agent）](https://www.kalviumlabs.ai/blog/langgraph-in-production-stateful-multi-step-agents/)
- [aitoolskit: StateGraph 内部机制](https://www.aitoolskit.io/learn/langgraph-state-machine-internals-architecture-2026)

## 关联

- [[桌面自动化项目]] docs/desktop-automation/step4-architecture.md（当前暂停等真实人工确认）
- 编排器现状: `orchestrator/top-agent-orchestrator.py`（确定性编排，门禁为程序拦截，非结构拦截）
