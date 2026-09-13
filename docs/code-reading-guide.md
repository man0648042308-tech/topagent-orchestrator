# 📖 router/ 代码阅读指南

> 配套文档：本文件解释"模型网关 router/"怎么读、怎么运转。
> 先读这篇，再回头看代码，事半功倍。

---

## 一、这套系统怎么运转（"总机调度中心"比喻）

把整个 router/ 想成一个**总机调度中心**，Claude Code（或命令行）是它的客户：

```
你要做的任务（"写代码""看一张图""生成一张图""语音转文字"）
        │  ① 交任务类型 + 内容
        ▼
┌─────────────────────────────────────────────────────┐
│ server.py ── 前台窗口（怎么找到它、怎么投递）            │
│   · MCP 接口：Claude Code 当工具调（route_and_execute） │
│   · CLI 接口：命令行 --execute 直接调                   │
│   · 诊断：--test / --route 查看状态                    │
└───────────────────────┬─────────────────────────────┘
        │  ② 转给调度员
        ▼
┌─────────────────────────────────────────────────────┐
│ router.py ── 调度员（路由决策 + 故障转移）               │
│   · 查路由表：这个任务该走哪条线                        │
│   · 执行：沿故障链调线路，第一条不通自动换下一条         │
└───────────────────────┬─────────────────────────────┘
        │  ③ 告诉接线员拨哪个号
        ▼
┌─────────────────────────────────────────────────────┐
│ providers.py ── 接线员（真正调各家 API）                │
│   · OpenAICompatProvider：文本/视觉/音频（百炼/DeepSeek/硅基/CSDN）│
│   · AnthropicProvider：Claude 直连（仅文本）            │
│   · DashScopeImageGenProvider：文生图                   │
│   · DashScopeAudioProvider：文字转语音 TTS              │
└───────────────────────┬─────────────────────────────┘
        │  ④ 用钥匙开门（API Key）
        ▼
┌─────────────────────────────────────────────────────┐
│ config.py ── 钥匙管理员                                │
│   · 读 config.yaml（电话簿：平台地址/超时/路由矩阵）     │
│   · 找 API Key：先看环境变量，没有就解密本机 DPAPI vault       │
└─────────────────────────────────────────────────────┘
```

**核心心智模型**：`config.yaml` 是"电话簿"（数据），四个 `.py` 是"人"（逻辑）。
改路由只改电话簿，不用改人。

---

## 二、6 个核心文件速查表

| 文件 | 一句话作用 | 关键函数 / 入口 |
|------|-----------|----------------|
| `router/config.yaml` | **电话簿/路由表** | `platforms`（平台定义）、`routing`（12类任务的首选+故障链）。改路由只改这里。 |
| `router/config.py` | **钥匙管理员** | `_load_config()` 读 yaml；`get_api_key()` 按环境变量→DPAPI vault 解析；`key_status()` 诊断用。 |
| `router/providers.py` | **接线员** | `OpenAICompatProvider.chat()`(205) 文本/视觉/音频；`DashScopeImageGenProvider.generate()`(312) 文生图；`DashScopeAudioProvider.tts()`(424) 文字转语音。 |
| `router/router.py` | **调度员** | `route_task()`(66) 只做决策；`route_and_execute()`(78) 执行+故障转移；`_get_provider()`(30) 按平台类型建接线员。 |
| `router/server.py` | **前台窗口** | `tool_route_and_execute()`(43) MCP工具；`run_execute()`(208) CLI执行；`run_test()`(178) 诊断；`main()`(237) 入口分流。 |
| `router/README.md` | **使用说明书** | 怎么装、怎么调、任务类型清单、实测状态。 |

配套文件：
- `.claude/settings.json` — **MCP 注册表**，Claude Code 启动时按它连接 `topagent-model-router`。
- `CLAUDE.md` — 项目总纲，架构图 + 文件索引 + 网关使用说明。

---

## 三、检索路线（推荐阅读顺序）

**自顶向下、先数据后逻辑**。每步只找"这个文件最关键的 3 件事"：

| 顺序 | 文件 | 读的时候找什么 |
|------|------|--------------|
| 1️⃣ | `config.yaml` | `platforms` 里有哪些平台/类型；`routing` 里 12 类任务各自首选+fallback |
| 2️⃣ | `config.py` | `PLATFORMS`/`ROUTING` 怎么从 yaml 来的；`get_api_key` 的查找顺序 |
| 3️⃣ | `providers.py` | `chat()` 怎么组请求体/发请求/解析响应/报错；`_build_content()`(130) 怎么拼多模态 |
| 4️⃣ | `router.py` | `route_and_execute`(78) 的 for 循环——这就是"故障转移"的实现 |
| 5️⃣ | `server.py` | `TOOLS` 字典（对外暴露哪些工具）；`main()`(237) 三种入口怎么分流 |
| 6️⃣ | `README.md` | 总览：已接入平台、实测状态、后续路线 |

---

## 四、一次调用的完整追踪（`--execute` 示例）

以 `python router/server.py --execute asr --audio 语音.mp3` 为例，看代码怎么流动：

```
① server.py:208  run_execute()        解析 --execute/--audio 参数
② server.py:219  → router_engine.route_and_execute(task_type="asr", audio="语音.mp3", ...)
③ router.py:78   route_and_execute()  查路由: route_task("asr")
④ router.py:66   route_task()         从 config.yaml 的 routing.asr 取 primary=dashscope/qwen3-asr-flash
⑤ router.py:101  for 循环             沿 full_chain 依次尝试（这就是故障转移）
⑥ router.py:114  _get_provider("dashscope") → 创建 OpenAICompatProvider（type=openai_compat）
⑦ router.py:165  provider.chat(model, messages, audio=audio)   ← 走默认 chat 分支
⑧ providers.py:205  chat()            传了 audio → _inject_media() 升级成多模态 content
⑨ providers.py:235  _inject_media()   把最后一条 user 消息换成 content 数组
⑩ providers.py:130  _build_content()  拼 [{"type":"input_audio","input_audio":{"data":<完整DataURL>}}]
⑪ providers.py:36   _post_json()      发 POST → 兼容端点 /chat/completions
⑫ providers.py:229  取 choices[0].message.content → 返回转写文本
⑬ router.py:170    返回 {"ok":True, "response":"...", "platform":"dashscope", ...}
⑭ server.py:233    print(JSON)        打印给用户
```

**故障转移在哪？** `router.py:101` 的 `for i, hop in enumerate(decision["full_chain"])`：
主模型失败 → 记录原因到 errors → `continue` 换下一条线路 → 全失败才返回 `ok:false`。

---

## 五、多模态三件套的"接线"方式（M2-M4 新增）

| 能力 | 平台(type) | 模型 | 走什么接口 | 关键代码 |
|------|-----------|------|-----------|---------|
| 视觉看图片 | `dashscope`(openai_compat) | qwen3-vl-plus | OpenAI 兼容 chat + `image_url` | `_build_content()`(130) |
| 文生图 | `dashscope_image`(image_gen) | qwen-image-3.0-pro → wan2.7-image-pro | 百炼原生 multimodal-generation | `DashScopeImageGenProvider.generate_and_save()`(336) |
| 语音转文字 | `dashscope`(openai_compat) | **qwen3-asr-flash** | OpenAI 兼容 chat + `input_audio.data`(完整DataURL) | `_build_content()`(130) 音频分支 |
| 文字转语音 | `dashscope_audio`(audio) | qwen3-tts-instruct-flash | 百炼原生 multimodal-generation（voice必填） | `DashScopeAudioProvider.tts()`(424) |

---

## 六、踩过的坑（实测记录，改了别踩回去）

### 🕳️ ASR "format is empty"（已解决）
- **错误现象**：`qwen-audio-3.0-asr-flash` + 原生 multimodal-generation 端点，7 种请求结构全报 `"format is empty"`。
- **根因**：该模型走原生接口时服务端拿不到音频（接口要求/文档已过期）。
- **正确做法**（2026-08-09 实测）：**换 `qwen3-asr-flash` + OpenAI 兼容 chat 接口**，且 `input_audio.data` 必须是**完整 Data URL**（`data:audio/mpeg;base64,...`）。
  - ❌ 裸 base64 + `format` 字段 → 报 "The provided URL does not appear to be valid"
  - ❌ `input_audio.url` 填远程链接 → 兼容端点不支持，报缺 `image_url.url`
- **代码对应**：`providers.py:98` `_audio_to_data_url()` 专门做"本地/URL → 完整 Data URL"。

### 🕳️ 图片生成 URL 24h 过期
- 百炼文生图返回的图片 URL 约 24 小时有效，**必须立刻下载落盘**。
- 代码对应：`generate_and_save()`(336) 生成后立即 `_download()` 到 `outputs/images/`。

### 🕳️ TTS 扩展名是假的
- qwen3-tts 返回的内容是 WAV 但命名可能带 .mp3。
- 代码对应：`_detect_audio_ext()`(166) 用 magic bytes（RIFF→.wav 等）判断真实格式，`tts()`(424) 按真实格式补扩展名。

### 🕳️ Windows 控制台中文乱码
- GBK 控制台打 emoji/中文乱码，但数据本身没错。
- 代码对应：`server.py:32` 强制 `sys.stdout.reconfigure(encoding="utf-8")`；命令行加 `PYTHONIOENCODING=utf-8`。

---

## 七、怎么验证（不花钱的干跑）

```bash
python router/server.py --test              # 全平台 Key 状态 + 可达性 + 12类路由链
python router/server.py --route image_gen   # 单任务路由决策（JSON）
python router/server.py --execute asr --audio 语音.mp3 --dry-run  # 只决策不真调
```

> ⚠️ 真调会花钱：`--execute` 默认真实执行；MCP 工具默认 `dry_run=true`。
