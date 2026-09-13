"""
路由决策引擎 — 调度员
===================
总机比喻里, 这里是"调度员": 根据任务类型查路由表选线路, 沿故障链执行,
第一条线不通就自动换下一条 (这就是"故障转移")。

- route_task         : 只做路由决策 (选主模型 + 故障链), 不发请求
- route_and_execute  : 按路由真实执行, 失败自动切换 fallback
"""
from pathlib import Path

try:
    from . import config as cfg
    from .providers import (
        AnthropicProvider,
        DashScopeAudioProvider,
        DashScopeImageGenProvider,
        OpenAICompatProvider,
        ProviderError,
    )
except ImportError:  # 兼容 python router/router.py 的直接脚本模式
    import config as cfg
    from providers import (
        AnthropicProvider,
        DashScopeAudioProvider,
        DashScopeImageGenProvider,
        OpenAICompatProvider,
        ProviderError,
    )

# 平台 -> provider 实例的缓存 (惰性初始化, 避免重复创建)
_providers = {}

# 输出目录: 图像 / 音频落盘位置
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs"
IMAGES_DIR = OUTPUTS_DIR / "images"
AUDIO_DIR = OUTPUTS_DIR / "audio"


def _get_provider(platform_name: str):
    """按平台名创建 (并缓存) 对应的 Provider 实例

    根据 config.yaml 里该平台的 type 字段分发:
      openai_compat → OpenAICompatProvider    (文本/视觉/多模态/ASR)
      anthropic     → AnthropicProvider       (Claude 直连)
      image_gen     → DashScopeImageGenProvider (图像生成)
      audio         → DashScopeAudioProvider  (TTS)
    """
    if platform_name in _providers:
        return _providers[platform_name]
    pf = cfg.PLATFORMS[platform_name]
    api_key = cfg.get_api_key(pf["api_key_env"])
    if not api_key:
        raise ProviderError(f"平台 {platform_name} 缺少 API Key (环境变量 {pf['api_key_env']})")

    ptype = pf.get("type", "openai_compat")
    timeout = pf.get("timeout_s", 60)
    if ptype == "anthropic":
        provider = AnthropicProvider(pf["base_url"], api_key, timeout)
    elif ptype == "image_gen":
        provider = DashScopeImageGenProvider(pf["base_url"], api_key, timeout)
    elif ptype == "audio":
        provider = DashScopeAudioProvider(pf["base_url"], api_key, timeout)
    else:
        provider = OpenAICompatProvider(pf["base_url"], api_key, timeout)

    _providers[platform_name] = provider
    return provider


def _route_for(task_type: str) -> dict:
    """取某任务类型的路由规则; 未知类型回落到默认类型 (general)"""
    return cfg.ROUTING.get(task_type) or cfg.ROUTING[cfg.DEFAULT_TASK_TYPE]


def route_task(task_type: str, complexity: str = "medium") -> dict:
    """路由决策 (不执行调用): 返回主模型 + 故障链"""
    route = _route_for(task_type)
    return {
        "task_type": task_type,
        "complexity": complexity,
        "primary": route["primary"],
        "fallback_chain": route.get("fallback", []),
        "full_chain": [route["primary"]] + route.get("fallback", []),
    }


def route_and_execute(
    task_type: str,
    prompt: str = "",
    complexity: str = "medium",
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    dry_run: bool = False,
    # ---- 媒体/多模态参数 (M2-M4 新增) ----
    image: str | None = None,              # 图片输入: 本地路径 / URL / base64 (视觉/多模态)
    audio: str | None = None,              # 音频输入: 本地路径 / URL / base64 (ASR/多模态)
    image_prompt: str | None = None,       # 图像生成提示词 (没传则用 prompt)
    image_size: str | None = None,         # 图像生成分辨率, 如 "1024*1024"
    image_n: int = 1,                      # 生成图片张数
    negative_prompt: str | None = None,    # 图像生成反向提示词
    text: str | None = None,               # TTS 要合成的文本 (没传则用 prompt)
    voice: str | None = None,              # TTS 音色
) -> dict:
    """按路由真实执行; 主模型失败自动切换 fallback; dry_run=True 时只返回决策不发请求"""
    decision = route_task(task_type, complexity)
    errors = []

    # 沿完整链路 (主模型 + 所有 fallback) 依次尝试, 第一条成功就返回
    for i, hop in enumerate(decision["full_chain"]):
        platform = hop["platform"]
        model = hop["model"]

        # 路由指向 Claude Code 自身 (local): 本服务不代理, 交还调用方执行
        if platform == "local":
            errors.append("local: 指向 Claude Code 自身, 需由调用方(当前会话)执行")
            continue

        pf = cfg.PLATFORMS[platform]
        ptype = pf.get("type", "openai_compat")

        try:
            # 干跑模式: 不发真实请求, 直接返回决策 (省费用/防误扣)
            if dry_run:
                return {
                    "ok": True, "dry_run": True,
                    "task_type": task_type, "complexity": complexity,
                    "platform": platform, "model": model,
                    "message": "干跑模式: 未发起真实 API 调用",
                }
            provider = _get_provider(platform)

            # ---- ① 图像生成 (原生 aigc 接口) ----
            if ptype == "image_gen":
                img_prompt = image_prompt or prompt or ""
                saved = provider.generate_and_save(
                    model, img_prompt, str(IMAGES_DIR),
                    n=image_n, size=image_size, negative_prompt=negative_prompt,
                )
                return {
                    "ok": True, "task_type": task_type,
                    "platform": platform, "model": model,
                    "images_saved": saved, "fallback_used": i > 0,
                }

            # ---- ② 音频: TTS(合成)。注意: ASR 不走这里 —
            # ASR 路由到 dashscope(openai_compat), 由下方 ③ 的 chat 分支用 input_audio 处理;
            # audio 类型平台 (dashscope_audio) 只负责 TTS。
            if ptype == "audio":
                tts_text = text or prompt or ""
                AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                # 注意: 不写死扩展名, 由 provider 按真实音频格式自动补 (可能 .wav/.mp3)
                out_base = str(AUDIO_DIR / f"tts_{model.replace('/', '_')}")
                saved = provider.tts(model, tts_text, voice=voice, out_path=out_base)
                return {
                    "ok": True, "task_type": task_type,
                    "platform": platform, "model": model,
                    "audio_saved": saved, "fallback_used": i > 0,
                }

            # ---- ③ 文本 / 视觉 / 多模态 / ASR (chat 接口) ----
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            content = provider.chat(
                model, messages,
                temperature=temperature, max_tokens=max_tokens,
                image=image, audio=audio,
            )
            return {
                "ok": True, "platform": platform, "model": model,
                "task_type": task_type, "complexity": complexity,
                "response": content, "fallback_used": i > 0,
                "fallback_chain": decision["full_chain"],
            }

        except ProviderError as e:
            # 当前线路失败 → 记录原因, 换下一条线路 (故障转移的核心)
            errors.append(f"{platform}/{model}: {e}")
            continue

    # 所有线路都失败
    return {"ok": False, "errors": errors, "decision": decision}
