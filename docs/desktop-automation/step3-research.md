# Step 3 研究检索书 — 桌面识别+自主点击应用

> 运行ID: `desktop-automation-001` | 步骤: Step 3 研究检索 | 状态: 待两级门禁
> 编制: TopAgent (合并 skill-hunter + memory-learning-agent 报告) | 日期: 2026-08-09
> 输入: step1-requirements.md, step2-analysis.md, fact-check/qa 裁决
> 子报告: orchestrator/outputs/desktop-automation-001/step_3-skill-hunter.md (21条溯源URL) + step_3-memory-learning.md (23条结论，全部文件溯源)

## 1. 核心结论：推荐技术栈（可直接实施）

```
mss (物理像素截图, import 必须在 pyautogui 之前)
  → Pillow 缩放到 API 限制内 (≤1024×768 / 1080p)
    → JPEG 60% 压缩 → base64
      → 视觉模型 (走 router/ 网关: qwen3-vl-plus 主 / siliconflow 备)
        → 返回结构化 JSON [element, 相对坐标, confidence, action, risk_level]
          → vision_client 输出 schema 校验（必需字段+类型；空/NaN/格式错 → 退避阶梯: 重试→切备模型→跳过本轮→人工介入）
            → coord_mapper 相对→物理像素 + 合理性校验(拒绝越界/NaN/Inf) + 边界clamp
              → 危险操作风险评级(SAFE|CAUTION|DANGER) + 元素类型白名单(button|link|checkbox|menu-item|input) + DANGER二次确认(--allow-dangerous)
                → pyautogui 移动+点击 (FAILSAFE=True)
                  → 点击前后截图 diff 校验
                    → 循环 → 日志审计 (JSONL + 截图存档 + API token/费用记录)
                      → 预算上限(max_steps×单价) + 费用超阈值暂停询问
```

## 2. 关键发现（带溯源）

### 2.1 坐标格式与映射（跨方案对比）

| 方案 | 坐标格式 | 映射方式 | 来源 |
|------|---------|---------|------|
| Claude Computer Use | `[x,y]` 整数，`display_width_px`×`display_height_px` 像素空间 | 返回坐标 ÷ 缩放因子 = 真实屏幕像素 | https://platform.claude.com/docs/en/docs/agents-and-tools/computer-use |
| OmniParser | 归一化比例 `[x1,y1,w,h]` 0-1 float | 直接×屏幕尺寸即可 | https://huggingface.co/microsoft/OmniParser/discussions/36 |
| pyautogui | 主屏幕物理像素整数 | import 时自动 SetProcessDPIAware() | https://github.com/asweigart/pyautogui/issues/663 |
| mss | 物理像素整数 | 无内置DPI，需注意 import 顺序 | https://github.com/BoboTiG/python-mss (README DPI 警告) |
| uiautomation | 绝对屏幕像素 Rect | BoundingRectangleProperty/CenterPoint | https://github.com/yinkaisheng/Python-UIAutomation-for-Windows |

**结论**: 本项目采用「物理像素」全链路 — mss 物理像素截图 → 降采样发送 → 模型返回坐标 → 按缩放因子映射回物理像素 → pyautogui(物理像素) 执行。全程不使用逻辑坐标，规避 DPI 歧义。
溯源: [对比表] → step_3-skill-hunter.md 第4节 | [DPI警告] → https://github.com/BoboTiG/python-mss

### 2.2 关键工程陷阱（必须遵守）

| # | 陷阱 | 严重度 | 缓解 | 来源 |
|---|------|:---:|------|------|
| T1 | `import mss` 必须早于 `import pyautogui`（后者 import 时调用 SetProcessDPIAware 造成 DPI 冲突） | 🔴高 | 模块加载顺序硬约束，写入代码规范 | https://github.com/BoboTiG/python-mss README |
| T2 | Windows 控制台中文乱码（GBK） | 🔴高 | 入口 `sys.stdout.reconfigure(encoding="utf-8")` | docs/code-reading-guide.md L139-141 |
| T3 | 主备模型坐标格式可能不一致 | 🟡中 | vision_client.py 用适配器模式按 platform 解析 | step_3-memory-learning.md §6.3 |
| T4 | 4K 截图 base64 超限 | 🟡中 | 降采样 ≤1920px + JPEG60% | step_2-qa.json L21 |
| T5 | UAC/UIPI 隔离：非提权进程无法控制管理员窗口 | 🟡中 | M1 检测目标进程权限，提权则警告/要求管理员运行 | step_3-memory-learning.md §6.1 |
| T6 | 锁屏/屏保截图返回纯色画面 | 🟡中 | 截图后 stddev≈0 判定无效，暂停等待解锁 | step_3-memory-learning.md §6.2 |
| T7 | 死循环/无进展 | 🔴高 | 三维检测(坐标不变+截图hash不变+步数上限) + 升级阶梯 | git f40c2ac 编排器循环防护经验 |
| T8 | 模型返回空/NaN/格式错误坐标（QA S3） | 🔴高 | vision_client 输出 JSON schema 校验（必需字段存在性+类型）；coord_mapper 合理性校验（0≤归一化≤1 / 像素正整数，拒绝 NaN/Inf）；退避阶梯：重试1次→切换备模型→跳过本轮→人工介入 | orchestrator/outputs/desktop-automation-001/step_3-qa.json |

### 2.3 模型选型（router/ 现状）

| 模型 | 平台 | 多模态分 | 推理分 | 角色 | 来源 |
|------|------|:---:|:---:|------|------|
| qwen3-vl-plus | 百炼DashScope | 95 | 80 | **主模型**（vision 路由 primary） | router/config.yaml L55-58 |
| Qwen/Qwen3-VL-32B-Instruct | 硅基SiliconFlow | — | — | 故障转移（fallback，自动切换） | router/config.yaml L55-58 |
| qwen3-vl-flash | 百炼 | 88 | 70 | 快速预筛选（界面变化检测） | model-capability-matrix.md L48-54 |

**注意**: 知识库中**无任何视觉模型坐标输出精度评分** — 坐标能力需 Step 4 设计实测评估。
超时约定: 60s；默认 dry_run=true 防误扣费；max_tokens=2000（复杂可调4000）。
溯源: [超时] → router/config.yaml L10,20,24 | [dry_run] → router/server.py L79-115 | [坐标能力空白] → step_3-memory-learning.md §1.3

### 2.4 可参考的开源项目（推荐/备选/不推荐）

| 级别 | 项目 | 亮点 | 来源 |
|------|------|------|------|
| **推荐** | Clacky (Raynan00/clacky) | 最接近本项目：Windows原生 + Claude视觉 + Esc急停 + 可逆操作 | https://github.com/Raynan00/clacky |
| **推荐** | anthropic-quickstarts computer-use-demo | 官方 agent loop + 坐标缩放参考实现 | https://github.com/anthropics/anthropic-quickstarts |
| **备选** | OmniParser (microsoft) | YOLO 预标注编号框 → 模型只回"点#5"，大幅降坐标误差 | https://github.com/microsoft/OmniParser |
| **备选** | GUI-Agent-Harness | 迭代缩放(≤8轮) + 视觉记忆(按钮模板缓存) | https://github.com/Fzkuji/GUI-Agent-Harness |
| **备选** | uiautomation | UIA 树获取元素精确矩形，作视觉点击验证基准 | https://github.com/yinkaisheng/Python-UIAutomation-for-Windows |
| **不推荐** | Docker/Xvfb 虚拟桌面 | 本项目目标是 Windows 原生，非 Linux 容器 | skill-hunter §不推荐 |
| **不推荐** | 纯 OCR 定位（不含 VLM） | 复杂 UI 布局精度远低于 VLM | skill-hunter §不推荐 |

### 2.5 安全护栏（综合多项目最佳实践 + QA 修正 S1-S3）

**基础护栏（机械层）**
1. `pyautogui.FAILSAFE=True` — 鼠标甩四角立即抛异常急停（内建机制）
2. 全局热键 Esc 中断 agent loop
3. 点击前坐标边界验证（窗口内 + 屏幕虚拟桌面范围）
4. 每轮点击前后截图 diff 验证是否生效
5. 高危区域黑名单（任务栏/开始菜单/系统托盘禁点）
6. 最大迭代次数限制（默认50轮）
7. 危险动作词黑名单（删除/关闭/确认删除等拦截）
8. 操作审计日志（每步时间/坐标/截图/结果）

**全自主模式增强护栏（QA S1 修正 — 文本黑名单不足，需语义+类型层）**
9. **危险操作风险评级**：视觉模型 Prompt 强制要求每步输出 `risk_level: SAFE|CAUTION|DANGER`。模型在返回 action 前先评估目标元素是否危险（删除/清空/关闭/付款/发送/覆盖保存等），DANGER 级默认拒绝执行
10. **DANGER 二次确认**：默认拒绝 DANGER 级操作，除非用户显式 `--allow-dangerous` 开启（防纯视觉危险按钮如红色X/无文字删除图标被误点）
11. **元素类型白名单**：只允许点击 `button|link|checkbox|menu-item|input` 类型元素；模型无法识别类型的区域默认拒绝点击（降误点率）

**API 费用护栏（QA S2 修正 — 成本失控）**
12. **预算上限**：运行前按 `max_steps × 单次估算费用` 计算预算并提示用户；累计费用超阈值 → 暂停并询问是否继续
13. **费用审计**：日志审计记录每次 API 调用的 token 消耗与估算费用

溯源: [FAILSAFE] → https://github.com/asweigart/pyautogui | [Esc急停] → https://github.com/Raynan00/clacky | [进程白名单] → https://lobehub.com/mcp/theyoungtoxic-go-to-work | [Anthropic安全建议] → https://platform.claude.com/docs/en/docs/agents-and-tools/computer-use (Security considerations) | [S1-S3修正来源] → orchestrator/outputs/desktop-automation-001/step_3-qa.json（qa-agent 第1轮 80分打回，3项问题）

## 3. 留给 Step 4 架构师的决策输入

| # | 决策 | 研究发现 | 倾向建议 |
|---|------|---------|---------|
| D1 | 视觉调用走 **router/ 网关 (qwen3-vl)** vs **Anthropic Computer Use API (Claude)** | skill-hunter 发现 Anthropic Computer Use 坐标格式最清晰、有官方参考；但项目约束 D6 要求走 router/，且 qwen3-vl-plus 已可用 | **主：router/ qwen3-vl-plus**（符合项目约束）；若实测坐标精度不足，评估 Anthropic 直连作为备选（记录 ADR） |
| D2 | 坐标格式：相对像素 vs 归一化比例 | 两方案都成熟；归一化更抗窗口尺寸变化，相对像素更直观 | **归一化比例**（0-1），coord_mapper 统一处理，兼容主备模型差异 |
| D3 | 循环节奏 | 固定间隔 vs 状态驱动；Anthropic 建议文本指令放图片前 + 滚动缓冲 | 首版单轮loop + 点击后等待0.5-1s反应 + 文本前置于图片 |
| D4 | 效果验证 | 前后截图 diff（轻量）vs 视觉模型二次确认（贵但准） | 首版截图 diff + 可选二次确认开关 |
| D5 | 坐标精度评估 | 知识库无评分 | 架构中加入「坐标精度测评集」（真实截图+人工标注 vs 模型返回），Phase 1 跑一次并回填知识库 |

## 4. Agent 分工建议（供 Step 5 参考）

| 任务模块 | 建议 Agent | 原因 |
|---------|-----------|------|
| M3 视觉识别 Prompt 工程 + M10 网关 | **AI工程师 Agent** | LLM调用/Prompt/结构化输出（ai-engineer-agent.md L34-43） |
| M1/M4/M5 窗口+坐标+鼠标 | **后端 Agent** | Windows API/系统层/pyautogui |
| M7 任务循环 + M9 急停 | **TopAgent 调度模式** | 循环/状态机/升级阶梯模式 |

---
✅ 本步骤产物 — 研究检索书 v1.1（QA 第1轮 80分打回 → 修复 S1-S3 后重提）
验证:  ⬜ 待验证 → 交 fact-check-agent 溯源验证 + qa-agent 质量审核（第2轮）
溯源:  [开源项目] → step_3-skill-hunter.md 21条URL | [知识库经验] → step_3-memory-learning.md 23条文件路径溯源 | [模型路由实测] → `python router/server.py --route vision` (dashscope qwen3-vl-plus → siliconflow fallback) | [边缘风险] → step_2-fact-check.json / step_2-qa.json | [需求约束] → step1-requirements.md D6