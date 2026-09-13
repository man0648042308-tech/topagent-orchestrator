# 🔀 Model Router v0.2 — 跨平台模型路由网关

让 Claude Code 具备**真正的跨平台模型切换 + 图文音多模态**能力。
路由决策 + 跨平台执行 + 自动故障转移，核心零第三方运行时依赖（标准库 urllib，仅配置需要 PyYAML）。

> 📖 代码阅读指南：`docs/code-reading-guide.md`（总机比喻 + 检索路线 + 调用追踪）

## 已接入平台

| 平台 | 类型 | 状态 (2026-08-09 实测) |
|------|------|------------------------|
| 阿里百炼 (DashScope) | OpenAI兼容 | ✅ 可用（文本/视觉/音频/多模态） |
| 百炼图像生成 (dashscope_image) | 原生 aigc | ✅ 可用（文生图，已实测落盘） |
| 百炼音频 TTS (dashscope_audio) | 原生 aigc | ✅ 可用（文字转语音，已实测落盘） |
| DeepSeek 直连 | OpenAI兼容 | ✅ 可用 |
| 硅基流动 (SiliconFlow) | OpenAI兼容 | ✅ 可用（文本/视觉/Omni） |
| CSDN (`api.csdn.net`) | OpenAI兼容 | ❌ **DNS解析失败**，故障链自动绕过 |
| Anthropic 直连 | Anthropic API | ⚠️ 需 `ANTHROPIC_API_KEY`（未配置） |

> ⚠️ **CSDN 注意**：`model-config.md` 里 CSDN 是多个任务类型的首选（约5折），但当前环境 DNS 解析失败。
> 故障转移链会自动绕过它切到备选平台，**功能不受影响**。恢复后无需改代码，重新 `--test` 即可确认。

## API Key 解析

按顺序查找：

1. **环境变量**：`DASHSCOPE_API_KEY` / `CSDN_API_KEY` / `DEEPSEEK_API_KEY` / `SILICONFLOW_API_KEY` / `ANTHROPIC_API_KEY`
2. **`runtime/secrets.enc`**：Windows 当前用户 DPAPI vault

设置本机 vault 时使用 `python -m topagent secrets set <NAME>`，输入值不会进入命令历史。

## 快速开始

```bash
# 干跑测试(不发真实请求): 打印路由矩阵 + Key 状态 + 平台可达性
python router/server.py --test

# 查询单个任务类型的路由决策
python router/server.py --route image_gen

# 真实调用(会花 API 费用, 按路由矩阵走故障转移)
python router/server.py --execute fast_text --prompt "你好"

# 视觉: 描述一张图
python router/server.py --execute vision --prompt "描述这张图" --image ./test.png

# 多模态: 图文音同传 (qwen3.5-omni-plus)
python router/server.py --execute multimodal --prompt "这是什么?" --image ./a.png --audio ./b.wav

# 文生图: 生成并保存到 outputs/images/
python router/server.py --execute image_gen --image-prompt "一只猫" --image-size 768*768 --image-n 1

# 语音转文字 (ASR)
python router/server.py --execute asr --audio ./语音.mp3

# 文字转语音 (TTS) → outputs/audio/
python router/server.py --execute tts --text "你好，我是 TopAgent" --voice Cherry

# 只决策不真调 (防误扣费)
python router/server.py --execute asr --audio ./语音.mp3 --dry-run
```

> 输出目录：图像 → `outputs/images/`，音频 → `outputs/audio/`（自动建目录）。

## 接入 Claude Code (MCP)

已在 `.claude/settings.json` 的 `mcpServers` 注册：

```json
{
  "mcpServers": {
    "topagent-model-router": {
      "type": "stdio",
      "command": "python",
      "args": ["C:/AI_Project/router/server.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

重启 Claude Code 后即可调用 MCP 工具：

- **`route_and_execute`** — 跨平台执行 + 故障转移。默认 `dry_run=true`（只决策不发请求，防误扣费）。
  参数：`task_type` `prompt` `system` `dry_run` `image`（图片输入） `audio`（音频输入）
  `image_prompt` `image_size` `image_n` `negative_prompt`（文生图） `text` `voice`（TTS）
- **`route_decision`** — 只查路由决策，不执行。

## 任务类型 (12 种)

| task_type | 首选 | 故障转移 |
|-----------|------|---------|
| `architecture` | dashscope/qwen3.7-max | csdn → deepseek-reasoner |
| `code_gen` | csdn/claude-sonnet-4-6 | dashscope/qwen3-coder-plus → csdn/deepseek-v4-flash |
| `vision` | dashscope/qwen3-vl-plus | siliconflow/Qwen3-VL-32B |
| `chinese` | csdn/glm-5.1 | dashscope/qwen3.7-max → deepseek-chat |
| `long_context` | csdn/kimi-k2.6 | dashscope/qwen3.6-max-preview → csdn/deepseek-v4-pro |
| `agent_coordination` | local (Claude Code 自身) | csdn/claude-opus-4-7 → dashscope/qwen3.7-max |
| `fast_text` | csdn/deepseek-v4-flash | deepseek-chat → siliconflow/DeepSeek-V3 |
| `general` | csdn/deepseek-v4-pro | dashscope/qwen3.7-max → deepseek-chat |
| `multimodal` | dashscope/qwen3.5-omni-plus | siliconflow/Qwen3-Omni-30B |
| `image_gen` | dashscope_image/qwen-image-3.0-pro | dashscope_image/wan2.7-image-pro |
| `asr` | dashscope/qwen3-asr-flash | — |
| `tts` | dashscope_audio/qwen3-tts-instruct-flash | — |

## 实测要点（2026-08-09）

- **ASR 必须用 `qwen3-asr-flash` + OpenAI 兼容 chat 接口**，且 `input_audio.data` 传**完整 Data URL**
  （`data:audio/mpeg;base64,...`），不是裸 base64 + format。`qwen-audio-3.0-asr-flash` 走原生端点会一直报 `"format is empty"`。
- **文生图 URL 24h 过期** → 生成后立刻下载落盘（`generate_and_save`）。
- **TTS 返回内容可能是 WAV 却带 .mp3 名** → 按文件头 magic bytes 自动补真实扩展名。
- **wan2.7-image-pro 最小分辨率 768×768**（512×512 会拒绝）。

## 安全

- **默认 `dry_run=true`**（MCP 侧）— 防止误扣费；CLI `--execute` 默认真实执行，需 `--dry-run` 才只决策。
- API Key 不硬编码在代码、Markdown 或脚本里（从环境变量或 DPAPI vault 解析）。
- 真实调用会向第三方平台发送你的 prompt，注意敏感数据。

## 目录结构

```
router/
├── server.py      # MCP Server (stdio JSON-RPC) + --test/--route/--execute
├── router.py      # 路由决策引擎 + 故障转移执行
├── providers.py   # 适配器: OpenAI兼容(文本/视觉/音频) + Anthropic + 文生图 + TTS
├── config.py      # 配置加载 + API Key 解析
├── config.yaml    # 平台定义 + 12类任务路由矩阵
└── README.md      # 本文件
```

## 后续路线

- [ ] HTTP API 模式 (FastAPI，供非 MCP 客户端调用)
- [ ] 成本追踪 / 延迟记录 → 动态优化路由
- [ ] 更多 provider 适配器 (OpenAI 直连、本地 Ollama)
- [ ] 更长音频的异步 filetrans 转写（当前走同步 chat 接口）
- [ ] CSDN 域名恢复后更新路由矩阵优先级
