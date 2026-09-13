from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from topagent.core.models import ExecutionRequest
from topagent.registry.agents import AgentSpec


@dataclass
class ExecutorOutput:
    status: str = "succeeded"
    structured_output: dict[str, Any] = field(default_factory=dict)
    produced_files: list[tuple[str, str]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    verifier_identity: dict[str, Any] | None = None


class Executor(Protocol):
    backend: str

    def execute(
        self,
        request: ExecutionRequest,
        agent: AgentSpec,
        workspace: Path,
    ) -> ExecutorOutput: ...


class FakeExecutor:
    """确定性测试执行器；不会调用任何模型或网络。"""

    backend = "fake"

    def execute(
        self, request: ExecutionRequest, agent: AgentSpec, workspace: Path
    ) -> ExecutorOutput:
        return ExecutorOutput(
            structured_output={
                "ok": True,
                "agent": agent.agent_id,
                "task": request.task,
                "input_artifacts": [item.artifact_id for item in request.inputs],
            },
            metrics={"executor": "fake", "paid_call": False},
        )


class SubprocessExecutor:
    """受约束的本地进程执行器；命令必须以字符串数组显式提供。"""

    backend = "subprocess"

    def execute(
        self, request: ExecutionRequest, agent: AgentSpec, workspace: Path
    ) -> ExecutorOutput:
        command = request.constraints.metadata.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) for part in command
        ):
            raise ValueError("subprocess executor 要求 constraints.metadata.command 为字符串数组")
        started = time.monotonic()
        result = subprocess.run(
            command,
            input=request.task,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=workspace,
            capture_output=True,
            timeout=request.constraints.timeout_seconds,
            shell=False,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"process exited {result.returncode}: {result.stderr[-2000:]}"
            )
        return ExecutorOutput(
            structured_output={
                "ok": True,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            metrics={
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "paid_call": False,
            },
        )


class ClaudeCodeExecutor:
    """Claude Code CLI 适配器；默认质量优先，free-only 时拒绝。"""

    backend = "claude"

    def __init__(self, command: str = "claude"):
        self.command = command

    def execute(
        self, request: ExecutionRequest, agent: AgentSpec, workspace: Path
    ) -> ExecutorOutput:
        if not request.constraints.allow_paid_calls:
            raise PermissionError("Claude executor 未执行：allow_paid_calls=false")
        command = [
            self.command,
            "-p",
            request.task,
            "--agent",
            agent.agent_id,
            "--output-format",
            "json",
            "--max-turns",
            str(request.constraints.max_turns),
        ]
        started = time.monotonic()
        result = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=workspace,
            capture_output=True,
            timeout=request.constraints.timeout_seconds,
            shell=False,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"claude exited {result.returncode}: {result.stderr[-2000:]}"
            )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {"response": result.stdout}
        return ExecutorOutput(
            structured_output=payload,
            metrics={
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "paid_call": True,
            },
        )


class RouterExecutor:
    """现有 router 的兼容适配器，沿用其 provider fallback 契约。"""

    backend = "router"

    def execute(
        self, request: ExecutionRequest, agent: AgentSpec, workspace: Path
    ) -> ExecutorOutput:
        if not request.constraints.allow_paid_calls:
            raise PermissionError("Router executor 未执行：allow_paid_calls=false")
        from router.router import route_and_execute

        meta = request.constraints.metadata
        output = route_and_execute(
            task_type=str(meta.get("task_type", "general")),
            prompt=request.task,
            complexity=str(meta.get("complexity", "medium")),
            system=meta.get("system"),
            temperature=float(meta.get("temperature", 0.7)),
            max_tokens=int(meta.get("max_tokens", 2000)),
            dry_run=bool(meta.get("dry_run", False)),
        )
        if not output.get("ok"):
            raise RuntimeError(json.dumps(output, ensure_ascii=False))
        return ExecutorOutput(
            structured_output=output,
            metrics={
                "paid_call": not bool(output.get("dry_run")),
                "fallback_used": bool(output.get("fallback_used")),
            },
        )


class CodexExecutor:
    """Codex CLI 适配器。

    使用当前Codex账户与本机CLI，不要求OpenAI API Key。Agent提示词会和任务一起
    传入非交互式 ``codex exec``；最终文本、事件数量和模型写入TopAgent审计产物。
    """

    backend = "codex"

    def __init__(self, command: str = "codex"):
        self.command = command

    def _command_prefix(self) -> list[str]:
        """返回可被 ``subprocess(shell=False)`` 安全执行的Codex入口。"""
        if os.name != "nt":
            return [self.command]
        wrapper = shutil.which("codex.cmd")
        node = shutil.which("node.exe") or shutil.which("node")
        if wrapper and node:
            script = (
                Path(wrapper).parent
                / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            )
            if script.is_file():
                return [node, str(script)]
        executable = shutil.which("codex.exe")
        if executable:
            return [executable]
        raise FileNotFoundError(
            "Windows未找到可供subprocess执行的Codex CLI入口"
        )

    def execute(
        self, request: ExecutionRequest, agent: AgentSpec, workspace: Path
    ) -> ExecutorOutput:
        prompt_path = Path(agent.prompt_path)
        agent_prompt = prompt_path.read_text(
            encoding="utf-8-sig", errors="replace"
        ) if prompt_path.is_file() else ""
        combined_prompt = (
            f"{agent_prompt}\n\n"
            "## 当前TopAgent任务\n"
            f"{request.task}\n\n"
            "输出必须包含：结论、依据/来源、验证状态、风险与下一步。"
        )
        output_file = workspace / "codex-final.md"
        command = [
            *self._command_prefix(),
            "-a", "never",
            "-s", "workspace-write",
            "--search",
        ]
        if agent.model:
            command.extend(["-m", agent.model])
        command.extend([
            "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "-C", str(workspace),
            "-o", str(output_file),
            "-",
        ])
        started = time.monotonic()
        result = subprocess.run(
            command,
            input=combined_prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=workspace,
            capture_output=True,
            timeout=request.constraints.timeout_seconds,
            shell=False,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"codex exited {result.returncode}: {result.stderr[-4000:]}"
            )
        events = []
        for line in result.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        final_text = output_file.read_text(
            encoding="utf-8", errors="replace"
        ) if output_file.is_file() else result.stdout
        return ExecutorOutput(
            structured_output={
                "response": final_text,
                "event_count": len(events),
                "billing": {
                    "mode": "codex_account_or_subscription",
                    "estimated_external_api_cost_cny": 0,
                    "marginal_cost_cny": None,
                    "note": "Codex CLI未向本执行器提供可换算的边际人民币费用",
                },
            },
            produced_files=[(str(output_file), "text/markdown")]
            if output_file.is_file() else [],
            metrics={
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "executor": "codex",
                "model": agent.model,
                "paid_call": None,
                "event_count": len(events),
            },
        )
