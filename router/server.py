"""
🔀 Model Router MCP Server — 前台窗口
==================================
这是整个模型网关的"前台窗口", 提供三种入口:

  1. MCP (stdio JSON-RPC) — 配置进 .claude/settings.json 后, Claude Code 可当工具调
     · route_and_execute : 跨平台执行 + 故障转移 (默认 dry_run 防误扣费)
     · route_decision    : 只查路由决策, 不执行
  2. CLI 诊断 — 不花一分钱
     · python router/server.py --test             # 打印路由矩阵 + Key 状态 + 平台可达性
     · python router/server.py --route code_gen   # 查单个任务类型的路由决策
  3. CLI 执行 — 真实调用 (注意会产生 API 费用)
     · python router/server.py --execute fast_text --prompt "你好" [--dry-run]
     · python router/server.py --execute vision --prompt "描述这张图" --image ./test.png
     · python router/server.py --execute image_gen --image-prompt "一只猫" --image-n 1
     · python router/server.py --execute tts --text "你好" [--voice Cherry]

安全: MCP 默认 dry_run=True, 避免误扣费; CLI --execute 默认真实执行, 可用 --dry-run 只做决策。
"""
import json
import os
import socket
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import router as router_engine

# Windows GBK 控制台无法打印 emoji/中文, 强制 UTF-8 (MCP stdio 协议本身也要求 UTF-8)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VERSION = "0.2.0"


# ==================== MCP 工具实现 ====================

def tool_route_and_execute(params: dict) -> dict:
    """route_and_execute 工具: 跨平台执行 + 故障转移 (默认干跑)"""
    task_type = params.get("task_type", cfg.DEFAULT_TASK_TYPE)
    prompt = params.get("prompt", "")
    dry_run = bool(params.get("dry_run", True))  # 默认干跑 (安全)
    if not prompt and not dry_run:
        return {"ok": False, "error": "非干跑模式下 prompt 不能为空"}
    return router_engine.route_and_execute(
        task_type=task_type,
        prompt=prompt,
        complexity=params.get("complexity", "medium"),
        system=params.get("system"),
        temperature=params.get("temperature", 0.7),
        max_tokens=params.get("max_tokens", 2000),
        dry_run=dry_run,
        # 媒体/多模态参数
        image=params.get("image"),
        audio=params.get("audio"),
        image_prompt=params.get("image_prompt"),
        image_size=params.get("image_size"),
        image_n=int(params.get("image_n") or 1),
        negative_prompt=params.get("negative_prompt"),
        text=params.get("text"),
        voice=params.get("voice"),
    )


def tool_route_decision(params: dict) -> dict:
    """route_decision 工具: 只查路由决策, 不执行"""
    return router_engine.route_task(
        params.get("task_type", cfg.DEFAULT_TASK_TYPE),
        params.get("complexity", "medium"),
    )


# 工具注册表: 名字 → 实现 + 描述 + 参数 schema (给 Claude Code 的 MCP 声明)
TOOLS = {
    "route_and_execute": {
        "fn": tool_route_and_execute,
        "desc": "跨平台模型路由执行: 按任务类型选最优模型, 失败自动故障转移。默认干跑(dry_run=true)。",
        "schema": {
            "type": "object",
            "properties": {
                "task_type": {"type": "string", "description": "architecture|code_gen|vision|chinese|long_context|agent_coordination|fast_text|general|multimodal|image_gen|asr|tts"},
                "prompt": {"type": "string", "description": "任务内容 (文本任务必填)"},
                "complexity": {"type": "string", "description": "low|medium|high|critical"},
                "system": {"type": "string", "description": "可选的系统提示词"},
                "dry_run": {"type": "boolean", "description": "true=只做路由决策不真调API(默认); false=真实执行"},
                "image": {"type": "string", "description": "图片输入: 本地路径/URL/base64 (vision/multimodal 用)"},
                "audio": {"type": "string", "description": "音频输入: 本地路径/URL/base64 (asr/multimodal 用)"},
                "image_prompt": {"type": "string", "description": "图像生成提示词 (image_gen 用)"},
                "image_size": {"type": "string", "description": "图像分辨率, 如 1024*1024 (image_gen 用)"},
                "image_n": {"type": "integer", "description": "生成图片张数, 默认1 (image_gen 用)"},
                "negative_prompt": {"type": "string", "description": "反向提示词 (image_gen 用)"},
                "text": {"type": "string", "description": "要合成的文本 (tts 用)"},
                "voice": {"type": "string", "description": "TTS 音色 (tts 用, 如 Cherry)"},
            },
            "required": ["prompt"],
        },
    },
    "route_decision": {
        "fn": tool_route_decision,
        "desc": "查询路由决策(不执行调用)",
        "schema": {
            "type": "object",
            "properties": {
                "task_type": {"type": "string", "description": "任务类型"},
                "complexity": {"type": "string", "description": "low|medium|high|critical"},
            },
            "required": ["task_type"],
        },
    },
}


# ==================== MCP 协议处理 (stdio JSON-RPC) ====================

def handle_request(req: dict) -> dict | None:
    """处理一条 JSON-RPC 请求 (MCP 协议)"""
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "topagent-model-router", "version": VERSION},
                "capabilities": {"tools": {}},
            },
        }

    elif method == "tools/list":
        tools = [
            {"name": name, "description": info["desc"], "inputSchema": info["schema"]}
            for name, info in TOOLS.items()
        ]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    elif method == "tools/call":
        name = req.get("params", {}).get("name", "")
        args = req.get("params", {}).get("arguments", {})
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"}}
        try:
            result = TOOLS[name]["fn"](args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
            }
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": str(e)}}

    elif method == "notifications/initialized":
        return None

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


# ==================== 诊断与 CLI ====================

def _dns_ok(base_url: str) -> bool:
    """检测平台域名是否可解析 (快速健康检查)"""
    try:
        host = urlparse(base_url).hostname
        socket.getaddrinfo(host, 443)
        return True
    except (socket.gaierror, TypeError):
        return False


def run_test() -> int:
    """--test 诊断: 打印 Key 状态 + 平台可达性 + 全部路由链 (不发请求)"""
    print(f"== 🔀 Model Router MVP v{VERSION} 干跑测试 ==")
    print(f"配置文件: {cfg.CONFIG_FILE}")
    print(f"API Key 状态: " + ", ".join(f"{k}={'✅' if v else '❌缺失'}" for k, v in cfg.key_status().items()))
    print(f"平台可达性: " + ", ".join(
        f"{k}={'✅' if _dns_ok(pf['base_url']) else '❌DNS失败'}"
        for k, pf in cfg.PLATFORMS.items()))
    print()
    print("路由决策矩阵:")
    for t in sorted(cfg.ROUTING.keys()):
        d = router_engine.route_task(t)
        chain = " -> ".join(f"{h['platform']}/{h['model']}" for h in d["full_chain"])
        print(f"  {t:<18} {chain}")
    print()
    print("干跑 route_and_execute (code_gen):")
    r = router_engine.route_and_execute("code_gen", "写一个hello world", dry_run=True)
    print("  " + json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def _arg(argv, name, default=None):
    """从 argv 里取 --name value 形式参数的简单解析器"""
    if name in argv:
        i = argv.index(name)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def run_execute() -> int:
    """--execute CLI: 真实执行一次路由调用 (默认 dry_run=False)

    例:
      python router/server.py --execute fast_text --prompt "你好" --dry-run
      python router/server.py --execute vision --prompt "描述图片" --image ./test.png
      python router/server.py --execute image_gen --image-prompt "一只猫" --image-n 1
      python router/server.py --execute tts --text "你好" --voice Cherry
    """
    args = sys.argv
    task_type = _arg(args, "--execute", cfg.DEFAULT_TASK_TYPE)
    result = router_engine.route_and_execute(
        task_type=task_type,
        prompt=_arg(args, "--prompt", "") or "",
        system=_arg(args, "--system"),
        image=_arg(args, "--image"),
        audio=_arg(args, "--audio"),
        image_prompt=_arg(args, "--image-prompt"),
        image_size=_arg(args, "--image-size"),
        image_n=int(_arg(args, "--image-n", "1") or 1),
        negative_prompt=_arg(args, "--negative-prompt"),
        text=_arg(args, "--text"),
        voice=_arg(args, "--voice"),
        dry_run="--dry-run" in args,   # CLI 默认真实执行; 显式 --dry-run 才只做决策
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


def main() -> int:
    """入口: 按命令行参数分流 (--test / --route / --execute / MCP stdio)"""
    if "--test" in sys.argv:
        return run_test()

    if "--execute" in sys.argv:
        return run_execute()

    route_arg = None
    if "--route" in sys.argv:
        i = sys.argv.index("--route")
        if i + 1 < len(sys.argv):
            route_arg = sys.argv[i + 1]
    if route_arg:
        d = router_engine.route_task(route_arg)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0

    # MCP stdio 主循环: 一行一条 JSON-RPC 请求, 响应写回 stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            if resp:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            pass
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": str(e)}}
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
