"""
Provider 适配器 — 统一调用各家模型 API 的"接线员"
============================================
总机比喻里, 这里的每个类就是一个"接线员": 真正向各家模型 API 发 HTTP 请求、收响应。

支持的接线员:
  - OpenAICompatProvider      : OpenAI /chat/completions 兼容平台 (百炼/DeepSeek/CSDN/硅基)
                               支持 纯文本 / 视觉图片输入 / 音频输入 (多模态)
  - AnthropicProvider         : Anthropic Messages API (Claude 直连, 仅文本)
  - DashScopeImageGenProvider : 阿里百炼图像生成 (原生 aigc 接口, 文生图)
  - DashScopeAudioProvider    : 阿里百炼音频 (原生 speech-synthesis 接口, 文字转语音)

核心全部用标准库 urllib, 零第三方运行时依赖。
"""
import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse


class ProviderError(Exception):
    """API 调用失败 (网络/HTTP/响应格式异常)"""


# ==================== 通用小工具 ====================

def _strip_base(url: str) -> str:
    """去掉 base_url 末尾多余的 '/'"""
    return url.rstrip("/")


def _post_json(url: str, payload: dict, timeout: int = 60, headers: dict | None = None) -> dict:
    """统一的 POST JSON 请求工具: 发请求 → 拿响应 JSON
    网络错误 / HTTP 错误码统一归一化成 ProviderError, 方便上层故障转移判断。
    headers: 额外请求头 (如 Authorization / x-api-key 等)
    """
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=req_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}") from e
    except urllib.error.URLError as e:
        raise ProviderError(f"网络错误: {e.reason if hasattr(e, 'reason') else e}") from e


def _get_json(url: str, timeout: int = 60, headers: dict | None = None) -> dict:
    """统一的 GET JSON 请求工具 (异步任务轮询时用)"""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:500]}") from e
    except urllib.error.URLError as e:
        raise ProviderError(f"网络错误: {e.reason if hasattr(e, 'reason') else e}") from e


def _media_to_url(value: str, kind: str) -> str:
    """把图片/音频参数转成 OpenAI 兼容消息里的 url 字段值 (data URI 或 http 链接)

    支持三种输入:
      1. 已带 data: 前缀的 data URI   → 原样返回
      2. http/https 远程链接          → 原样返回
      3. 本地文件路径                 → 读文件 → base64 → data:<mime>;base64,<数据>
    """
    if value.startswith("data:"):
        return value
    if value.startswith(("http://", "https://")):
        return value
    # 本地文件: 先按扩展名判断 MIME 类型
    mime, _ = mimetypes.guess_type(value)
    if not mime:
        ext = os.path.splitext(value)[1].lower().lstrip(".")
        fallback = {
            "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
            "wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
        }
        mime = fallback.get(ext, "image/jpeg" if kind == "image" else "audio/wav")
    with open(value, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _audio_to_data_url(value: str) -> str:
    """把音频参数转成 OpenAI input_audio.data 所需的**完整 Data URL**

    实测 (2026-08-09): 百炼 compatible-mode 的 qwen3-asr-flash / qwen3.5-omni-plus
    要求 input_audio.data 是完整 Data URL (data:<mime>;base64,<数据>),
    **不是** 裸 base64 + 单独 format 字段。
    裸 base64 会报 "The provided URL does not appear to be valid"; 走原生
    multimodal-generation 端点的 qwen-audio-3.0-asr-flash 则一直报 "format is empty"。
    """
    if value.startswith("data:"):                        # 已是 Data URL → 原样返回
        return value
    if value.startswith(("http://", "https://")):        # 远程 → 下载后转 Data URL
        data = _download_bytes(value)
        mime = _file_mime(value)
    else:                                                # 本地文件 → 读成 base64
        with open(value, "rb") as f:
            data = f.read()
        mime = _file_mime(value)
    return f"data:{mime};base64,{base64.b64encode(data).decode('utf-8')}"


def _file_mime(value: str) -> str:
    """推断本地文件/URL 的 MIME 类型 (供音频格式判断)"""
    mime, _ = mimetypes.guess_type(value)
    if not mime:
        ext = os.path.splitext(value)[1].lower().lstrip(".")
        fallback = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
                    "flac": "audio/flac", "ogg": "audio/ogg"}
        mime = fallback.get(ext, "audio/wav")
    return mime


def _build_content(text: str, image=None, audio=None):
    """构造 OpenAI 兼容的多模态 content 字段

    - 纯文本 (无图无音频) 时返回普通字符串 → 兼容老接口/老模型
    - 有图/音频时返回结构化数组:
      [ {type:image_url,image_url:{url:...}},
        {type:input_audio,input_audio:{data:<base64>,format:<fmt>}},
        {type:text,text:...} ]
    """
    if image is None and audio is None:
        return text
    parts = []
    if image is not None:
        parts.append({"type": "image_url", "image_url": {"url": _media_to_url(image, "image")}})
    if audio is not None:
        # data 必须是完整 Data URL (实测: 裸 base64 + format 字段会报错)
        parts.append({"type": "input_audio", "input_audio": {"data": _audio_to_data_url(audio)}})
    if text:
        parts.append({"type": "text", "text": text})
    return parts


def _download(url: str, path: str, timeout: int = 120) -> None:
    """把 URL 内容下载保存到本地文件 (图像/音频 URL 一般有时效, 需尽快落盘)"""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(path, "wb") as f:
        f.write(resp.read())


def _download_bytes(url: str, timeout: int = 120) -> bytes:
    """下载 URL 内容并直接返回字节 (供 TTS 先拿到数据再判断格式)"""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _detect_audio_ext(source, data: bytes) -> str:
    """判断音频文件的真实扩展名 (TTS 返回的格式可能与预期不符)

    优先看 URL 路径扩展名; 拿不到就看文件头 magic bytes:
      RIFF → .wav   |   ID3 或 0xFF 0xFB → .mp3   |   ftyp → .mp4
    """
    if isinstance(source, str) and source.startswith("http"):
        ext = os.path.splitext(urlparse(source).path)[1].lower()
        if ext in (".wav", ".mp3", ".mp4", ".flac", ".ogg", ".pcm", ".m4a"):
            return ext
    if data[:4] == b"RIFF":
        return ".wav"
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        return ".mp3"
    if data[4:8] == b"ftyp":
        return ".mp4"
    return ".mp3"


def _url_ext(url: str, default: str = ".png") -> str:
    """从 URL 里提取文件扩展名, 取不到就返回默认值"""
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp") else default


# ==================== 1. OpenAI 兼容平台 ====================

class OpenAICompatProvider:
    """OpenAI 兼容平台适配器 — DeepSeek / 百炼 / CSDN / 硅基 都走这个格式

    这些平台都提供 /v1/chat/completions 接口, 请求/响应结构一致,
    所以一个适配器就能通吃四家 (只是 base_url 和 Key 不同)。
    """

    def __init__(self, base_url: str, api_key: str, timeout_s: int = 60):
        self.base_url = _strip_base(base_url)   # 例如 https://dashscope.aliyuncs.com/compatible-mode/v1
        self.api_key = api_key
        self.timeout = timeout_s

    def chat(self, model, messages, temperature=0.7, max_tokens=2000, image=None, audio=None) -> str:
        """聊天/推理调用, 返回模型回复文本

        参数:
          - messages : [{role:system|user, content:str}, ...] 标准消息列表
          - image    : 可选。图片 (本地路径 / URL / base64 data URI), 传给多模态模型
          - audio    : 可选。音频 (本地路径 / URL / base64 data URI), 传给多模态模型
        """
        # 传了图片/音频 → 把最后一条 user 消息升级成多模态 content 数组
        if image is not None or audio is not None:
            messages = self._inject_media(messages, image=image, audio=audio)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = _post_json(
            f"{self.base_url}/chat/completions",
            payload,
            self.timeout,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ProviderError(f"响应格式异常: {json.dumps(resp, ensure_ascii=False)[:500]}") from e

    @staticmethod
    def _inject_media(messages: list, image=None, audio=None) -> list:
        """把图片/音频塞进最后一条 user 消息, 把它变成多模态 content 数组"""
        for m in reversed(messages):
            if m.get("role") == "user":
                text = m.get("content", "")
                if not isinstance(text, str):   # 已是数组则视为无文本
                    text = ""
                m["content"] = _build_content(text, image=image, audio=audio)
                break
        return messages


# ==================== 2. Anthropic 平台 ====================

class AnthropicProvider:
    """Anthropic Messages API 适配器 (Claude 直连, 仅文本)

    与 OpenAI 格式不同: 需要 x-api-key 头 + anthropic-version 头,
    请求体用 messages/system 结构, 响应取 content[].text。
    """
    def __init__(self, base_url: str, api_key: str, timeout_s: int = 60, api_version: str = "2023-06-01"):
        self.base_url = _strip_base(base_url)
        self.api_key = api_key
        self.timeout = timeout_s
        self.api_version = api_version

    def chat(self, model, messages, temperature=0.7, max_tokens=2000, image=None, audio=None) -> str:
        """聊天调用 (目前仅文本; 图片/音频暂不支持)"""
        if image is not None or audio is not None:
            raise ProviderError("AnthropicProvider 暂不支持图片/音频输入, 请改用 OpenAI 兼容平台 (百炼/硅基)")

        # 把 system 消息单独抽出来 (Anthropic 协议 system 是顶层字段, 不在 messages 里)
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user_messages = [m for m in messages if m["role"] != "system"]
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system:
            payload["system"] = system

        resp = _post_json(
            f"{self.base_url}/v1/messages",
            payload,
            self.timeout,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.api_version,
            },
        )
        try:
            return "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise ProviderError(f"响应格式异常: {json.dumps(resp, ensure_ascii=False)[:500]}") from e


# ==================== 3. 百炼图像生成 ====================

class DashScopeImageGenProvider:
    """阿里百炼图像生成适配器 (文生图)

    百炼官方**不用** OpenAI 的 /v1/images/generations,
    而是走原生接口: POST .../api/v1/services/aigc/multimodal-generation/generation
    返回图片 URL (约 24 小时有效, 必须立刻下载保存)。
    """

    # 异步任务的查询端点 (生成返回 task_id 时轮询这个地址)
    TASK_QUERY_URL = "https://dashscope.aliyuncs.com/api/v1/tasks"

    def __init__(self, base_url: str, api_key: str, timeout_s: int = 120):
        # 注意: config.yaml 里该平台 base_url 就是完整的"生成"端点
        self.endpoint = _strip_base(base_url)
        self.api_key = api_key
        self.timeout = timeout_s

    def generate(self, model: str, prompt: str, n: int = 1, size: str | None = None,
                 negative_prompt: str | None = None) -> list[str]:
        """文生图: 返回生成图片的 URL 列表"""
        parameters = {}
        if n and n > 1:
            parameters["n"] = n
        if size:
            parameters["size"] = size
        if negative_prompt:
            parameters["negative_prompt"] = negative_prompt

        payload = {
            "model": model,
            "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
            "parameters": parameters,
        }
        resp = _post_json(
            self.endpoint,
            payload,
            self.timeout,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return self._extract_urls(resp)

    def generate_and_save(self, model: str, prompt: str, out_dir: str, n: int = 1,
                          size: str | None = None, negative_prompt: str | None = None,
                          prefix: str = "img") -> list[str]:
        """生成图片并立刻下载保存到本地 (URL 24h 过期, 必须马上落盘), 返回文件路径列表"""
        os.makedirs(out_dir, exist_ok=True)
        urls = self.generate(model, prompt, n=n, size=size, negative_prompt=negative_prompt)
        saved = []
        for i, url in enumerate(urls):
            ext = _url_ext(url)
            path = os.path.join(out_dir, f"{prefix}_{i}{ext}")
            _download(url, path, self.timeout)
            saved.append(path)
        return saved

    @staticmethod
    def _extract_urls_from_output(output: dict) -> list[str]:
        """从 output 字段里提取图片 URL 列表 (兼容两种真实返回格式)

        - 格式1: output.results[].url
        - 格式2: output.choices[].message.content[].image  ← qwen-image-3.0-pro 实测返回这种
        """
        urls = [r["url"] for r in output.get("results", []) if r.get("url")]
        if urls:
            return urls
        for choice in output.get("choices", []):
            message = choice.get("message") or {}
            for part in message.get("content", []):
                if isinstance(part, dict) and part.get("image"):
                    urls.append(part["image"])
        return urls

    def _extract_urls(self, resp: dict) -> list[str]:
        """从完整响应里取出图片 URL 列表

        两种情况:
          - 同步返回: output 里直接带 results 或 choices
          - 异步返回: output.task_status + output.task_id → 轮询到完成
        """
        output = resp.get("output", {})
        urls = self._extract_urls_from_output(output)
        if urls:
            return urls
        task_id = output.get("task_id")
        if task_id:
            return self._poll_task(task_id)
        raise ProviderError(f"图像生成响应异常: {json.dumps(resp, ensure_ascii=False)[:500]}")

    def _poll_task(self, task_id: str, max_wait: int = 180) -> list[str]:
        """轮询异步生成任务直到完成, 返回图片 URL 列表"""
        url = f"{self.TASK_QUERY_URL}/{task_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.time() + max_wait
        while time.time() < deadline:
            data = _get_json(url, self.timeout, headers=headers)
            output = data.get("output", {})
            status = output.get("task_status", "")
            if status == "SUCCEEDED":
                return self._extract_urls_from_output(output)
            if status in ("FAILED", "CANCELED"):
                raise ProviderError(f"图像生成任务{status}: {json.dumps(data, ensure_ascii=False)[:300]}")
            time.sleep(3)   # 任务还没完成, 等 3 秒再查
        raise ProviderError("图像生成任务超时")


# ==================== 4. 百炼音频 (TTS) ====================

class DashScopeAudioProvider:
    """阿里百炼音频适配器 — 文字转语音 TTS

    实测要点 (2026-08-09):
      · qwen3-tts-instruct-flash 与图像生成走**同一个端点**
        POST .../api/v1/services/aigc/multimodal-generation/generation
      · voice 是**必填**参数 (默认用 Cherry)
      · 返回音频文件 URL (约 24h 有效), 必须立刻下载保存

    注: 语音识别 (ASR) **不**走这里 — 它走 OpenAI 兼容 chat 接口的音频输入,
    复用 OpenAICompatProvider (见 config.yaml 的 asr 路由 → dashscope 平台)。
    本类只负责 TTS。
    """

    DEFAULT_VOICE = "Cherry"   # 未指定音色时的默认值 (中文女声)

    def __init__(self, base_url: str, api_key: str, timeout_s: int = 120):
        # base_url 形如 .../api/v1/services/aigc/multimodal-generation/generation
        self.endpoint = _strip_base(base_url)
        self.api_key = api_key
        self.timeout = timeout_s

    def tts(self, model: str, text: str, voice: str | None = None, out_path: str | None = None) -> str:
        """文字转语音: 保存到本地, 返回实际文件路径 (扩展名按内容自动判断)"""
        payload = {
            "model": model,
            "input": {
                "text": text,
                "voice": voice or self.DEFAULT_VOICE,   # voice 必填
            },
        }
        resp = _post_json(
            self.endpoint,
            payload,
            self.timeout,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        # 取音频值 (URL 或 base64) → 先转成字节
        audio_value = self._extract_audio(resp)
        if audio_value.startswith("http"):
            data = _download_bytes(audio_value, self.timeout)
        elif audio_value.startswith("data:"):
            data = base64.b64decode(audio_value.split(",", 1)[1])
        else:
            data = base64.b64decode(audio_value)

        # 按真实格式定扩展名, 避免 .mp3 实际是 WAV 的问题
        ext = _detect_audio_ext(audio_value, data)
        final_path = f"{out_path}{ext}" if out_path else f"tts_{int(time.time())}{ext}"
        with open(final_path, "wb") as f:
            f.write(data)
        return final_path

    @staticmethod
    def _extract_audio(resp: dict) -> str:
        """从响应里提取音频值 (URL 或 base64 data)

        实测返回格式: output.choices[].message.content[].audio
        """
        output = resp.get("output", {})
        for choice in output.get("choices", []):
            message = choice.get("message") or {}
            for part in message.get("content", []):
                if isinstance(part, dict) and part.get("audio"):
                    return part["audio"]
        audio = output.get("audio")
        if isinstance(audio, dict) and audio.get("url"):
            return audio["url"]
        if isinstance(audio, str):
            return audio
        raise ProviderError(f"TTS 响应格式异常: {json.dumps(resp, ensure_ascii=False)[:500]}")
