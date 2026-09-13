# 🔀 TopAgent 确定性编排器

> **v3 兼容层说明**：本目录继续负责人工确认、产物提交和两级门禁状态机；Agent 的
> 真实执行、消息、产物、身份和 trace 由 `topagent/runtime/` 与
> `runtime/topagent.db` 负责。完整入口见 `python -m topagent`。

把 10 步流水线从「提示词散文」变成「可执行程序 + 强制门禁」。流程不再依赖模型"自觉"——
**门禁不过，advance 拒绝**，与 CI/CD 中「pytest 挂了拒绝部署」同理。

```
orchestrator/
├── top-agent-orchestrator.py   # 状态机 + 门禁执行器（本程序）
├── pipeline.json               # 数据驱动的步骤/门禁定义（权威）
├── state/                      # 运行状态（gitignore）
└── outputs/                    # 各步骤产物 + 裁决（gitignore）
```

## 质量门禁（质量体系权限）

每个步骤产物进入下一步之前，必须**依次**通过两级独立门禁：

```
产物 → ① 独立溯源验证 fact-check-agent（三层验证+溯源，可信度 ≥70）
          ↓ 通过后才可以
       ② 独立质量审核 qa-agent（5维评分，总分 ≥85）
          ↓ 通过后才可以
       进入下一步
```

- **独立**：验证者 ≠ 生产者，裁决 JSON 必须声明 `verifier: fact-check-agent` / `qa-agent`，否则拒绝
- **溯源**：产物缺 URL/文件路径/命令输出 → `submit` 直接拒绝，不进入任何验证
- **顺序**：先溯源验证，通过后才允许提交质量审核——次序由程序强制
- **结构校验是确定性的**：不依赖 LLM 判断，代码直接判

## 用法

```bash
# 1. 初始化一次运行
python orchestrator/top-agent-orchestrator.py init --requirement "一句话生成15秒AI漫剧网站" --run-id manju-001

# 2. 看当前步骤 + 该做什么
python orchestrator/top-agent-orchestrator.py next
python orchestrator/top-agent-orchestrator.py status

# 3. 每个产出步骤循环：
python orchestrator/top-agent-orchestrator.py submit <step> <output_file>     # 结构门禁（缺溯源即拒）
python orchestrator/top-agent-orchestrator.py prompt <step> fact_check        # 生成独立溯源验证提示词
#   → 启动 fact-check-agent，把裁决存 JSON
python orchestrator/top-agent-orchestrator.py record <step> fact_check <verdict.json>
python orchestrator/top-agent-orchestrator.py prompt <step> qa                # 生成独立质量审核提示词
#   → 启动 qa-agent，把裁决存 JSON
python orchestrator/top-agent-orchestrator.py record <step> qa <verdict.json>
python orchestrator/top-agent-orchestrator.py advance <step>                  # 门禁不过会被拒绝
```

需要真人确认的 Step 1 和 Step 4 还必须携带费用估算：

```bash
python orchestrator/top-agent-orchestrator.py confirm <step> --cost-estimate <cost.json>
```

`cost.json` 至少包含：

```json
{
  "currency": "CNY",
  "estimated_cost": "外部API增量预计¥0；订阅额度无法折算",
  "billing_basis": "当前使用已登录的Codex账号和公开网页",
  "uncertainty": "medium",
  "unpriced_items": ["Codex账号/订阅额度"]
}
```

费用记录用于知情审批和审计，不自动生成预算上限、费用告警、模型降级或停止条件。

## 循环防护（打回不会死循环，而是升级阶梯）

| 情况 | 行为 |
|------|------|
| 产物与上次被打回时**完全相同** | 🔁 `submit` 拒绝：未修正，禁止重复提交（内容哈希检测） |
| **连续 3 次**被溯源/质量验证打回 | ⚠️ 流程暂停，触发升级：failure-analysis 根因 → eval-benchmark 评分 → 连续2次<60 淘汰 → agent-forge 换新重训 |
| 升级处理完成后 | `escalate <step> --resolution <处理概述>` 记录并解除升级，重新 submit |
| 确有合理理由需要人工放行 | ⏭️ `override <step> --reason <理由>` —— **唯一的前进通道，必须带理由，时间戳写入审计**，绝非静默硬推 |

```
python orchestrator/top-agent-orchestrator.py escalate <step> --resolution "failure-analysis:...; eval:58分; forge:已换新v2"
python orchestrator/top-agent-orchestrator.py override <step> --reason "人工裁决依据..."
```

`record` 强制前置 `submit`（结构校验通过，output_hash 已落），禁止跳过 submit 直接记裁决硬推。

## 裁决 JSON 格式

fact-check（溯源验证）:
```json
{
  "verifier": "fact-check-agent",
  "step": "step_3",
  "confidence": 82,
  "passed": true,
  "sources": ["https://gitee.com/xxx"],
  "failing_claims": [],
  "notes": ""
}
```

qa（质量审核）:
```json
{
  "verifier": "qa-agent",
  "step": "step_3",
  "score": 88,
  "passed": true,
  "verdict": "approve",
  "dimensions": {"correctness": 90, "code_quality": 88, "efficiency": 85, "innovation": 80, "stability": 90},
  "notes": ""
}
```

## 与流水线的对应

| 步骤 | 执行 | 门禁 |
|------|------|------|
| Step 1 理解需求 | TopAgent 直接 | 用户确认 |
| Step 2 分析拆解 | TopAgent 直接 | 两级门禁 |
| Step 3 研究检索 | skill-hunter + memory-learning-agent | 两级门禁 |
| Step 4 规划架构 | architect-agent | 两级门禁 + 用户确认 |
| Step 5 组建团队 | agent-forge-agent | 两级门禁 |
| Step 6 分配任务 | TopAgent 直接 | 无 |
| Step 7 监督执行 | frontend/backend/ai-engineer/test | 两级门禁 |
| Step 8 质量终审 | qa-agent | 结构化裁决 |
| Step 8.5 反失败 | failure-analysis-agent | 结构化裁决 |
| Step 8.6 评分淘汰 | eval-benchmark-agent | 结构化裁决 |
| Step 9 总结学习 | data-curator-agent | 两级门禁 |
| Step 10 能力进化 | eval-benchmark-agent | 结构化裁决 |

> 说明：原 Step 3.5 研究验证门已折叠进 Step 3 的**两级门禁**（溯源验证层即原 fact-check 门）。
> 现在每一步都有独立溯源验证，比只有 Step 3.5 一道门更强。
