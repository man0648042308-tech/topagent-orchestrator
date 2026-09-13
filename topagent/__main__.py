from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from topagent.api.server import main as serve
from topagent.core.database import db
from topagent.core.models import ExecutionConstraints, ExecutionRequest
from topagent.registry.builder import build_all
from topagent.runtime.dispatcher import Dispatcher
from topagent.runtime.orchestrator import RuntimeOrchestrator
from topagent.runtime.scheduler import Scheduler
from topagent.secrets.vault import SecretResolver, WindowsDPAPIVault, migrate_legacy
from topagent.settings import settings


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="python -m topagent")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="初始化数据库并重建 Agent/Skill/Capability Registry")
    dashboard = commands.add_parser("serve", help="启动本地 Control Center")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)

    dispatch = commands.add_parser("dispatch", help="通过统一执行接口调用 Agent")
    dispatch.add_argument("agent")
    dispatch.add_argument("task")
    paid = dispatch.add_mutually_exclusive_group()
    paid.add_argument(
        "--allow-paid-calls", dest="allow_paid_calls", action="store_true",
        help="兼容旧脚本；付费/订阅额度调用现在默认允许",
    )
    paid.add_argument(
        "--free-only", dest="allow_paid_calls", action="store_false",
        help="本次执行显式禁止付费Provider",
    )
    dispatch.set_defaults(allow_paid_calls=True)
    dispatch.add_argument("--run-id")
    dispatch.add_argument(
        "--timeout-seconds", type=int, default=300,
        help="本次执行超时秒数；复杂联网研究可显式提高",
    )
    verify = commands.add_parser("verify", help="由独立 Agent 验证既有 execution")
    verify.add_argument("verifier_agent")
    verify.add_argument("subject_execution_id")
    verify.add_argument("task")
    paid = verify.add_mutually_exclusive_group()
    paid.add_argument(
        "--allow-paid-calls", dest="allow_paid_calls", action="store_true",
        help="兼容旧脚本；付费/订阅额度调用现在默认允许",
    )
    paid.add_argument(
        "--free-only", dest="allow_paid_calls", action="store_false",
        help="本次验证显式禁止付费Provider",
    )
    verify.set_defaults(allow_paid_calls=True)
    verify.add_argument(
        "--timeout-seconds", type=int, default=300,
        help="本次验证超时秒数",
    )

    run_create = commands.add_parser("run-create")
    run_create.add_argument("requirement")
    run_step = commands.add_parser("run-step")
    run_step.add_argument("run_id")
    run_step.add_argument("step_id")
    paid = run_step.add_mutually_exclusive_group()
    paid.add_argument(
        "--allow-paid-calls", dest="allow_paid_calls", action="store_true",
        help="兼容旧脚本；付费/订阅额度调用现在默认允许",
    )
    paid.add_argument(
        "--free-only", dest="allow_paid_calls", action="store_false",
        help="本次步骤显式禁止付费Provider",
    )
    run_step.set_defaults(allow_paid_calls=True)
    run_step.add_argument(
        "--timeout-seconds", type=int, default=300,
        help="本步骤内每个Agent执行的超时秒数",
    )
    run_status = commands.add_parser("run-status")
    run_status.add_argument("run_id")

    tick = commands.add_parser("scheduler-tick")
    tick.add_argument("agent")
    tick.add_argument("--limit", type=int, default=1)

    secrets = commands.add_parser("secrets")
    secret_commands = secrets.add_subparsers(dest="secret_command", required=True)
    migrate = secret_commands.add_parser("migrate")
    migrate.add_argument("--source", action="append", type=Path)
    status = secret_commands.add_parser("status")
    status.add_argument("names", nargs="+")
    secret_set = secret_commands.add_parser("set")
    secret_set.add_argument("name")
    secret_set.add_argument("--from-env")
    secret_delete = secret_commands.add_parser("delete")
    secret_delete.add_argument("name")
    return root


def print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    # Windows 控制台常默认为 GBK；审计 JSON 可能包含 ¥ 等字符。
    # 显式使用 UTF-8，避免一次成功执行仅因打印阶段编码失败。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args()
    settings.ensure_runtime()
    db.initialize()
    if args.command == "init":
        print_json(build_all(db))
    elif args.command == "serve":
        serve(args.host, args.port)
    elif args.command == "dispatch":
        result = Dispatcher(database=db).dispatch(
            ExecutionRequest(
                agent_id=args.agent, task=args.task,
                run_id=args.run_id,
                constraints=ExecutionConstraints(
                    timeout_seconds=args.timeout_seconds,
                    allow_paid_calls=args.allow_paid_calls,
                ),
            )
        )
        print_json(result.to_dict())
    elif args.command == "verify":
        result = Dispatcher(database=db).verify(
            verifier_agent_id=args.verifier_agent,
            subject_execution_id=args.subject_execution_id,
            task=args.task,
            constraints=ExecutionConstraints(
                timeout_seconds=args.timeout_seconds,
                allow_paid_calls=args.allow_paid_calls,
            ),
        )
        print_json(result.to_dict())
    elif args.command == "run-create":
        print_json({"run_id": RuntimeOrchestrator(database=db).create_run(args.requirement)})
    elif args.command == "run-step":
        print_json(RuntimeOrchestrator(database=db).run_step(
            args.run_id, args.step_id,
            allow_paid_calls=args.allow_paid_calls,
            timeout_seconds=args.timeout_seconds,
        ).__dict__)
    elif args.command == "run-status":
        print_json(RuntimeOrchestrator(database=db).status(args.run_id))
    elif args.command == "scheduler-tick":
        print_json(Scheduler(database=db).tick(args.agent, limit=args.limit).__dict__)
    elif args.command == "secrets" and args.secret_command == "migrate":
        sources = args.source or [
            settings.root / "memory" / "api-keys.md",
            settings.root / "setup.sh",
            settings.root / "setup.bat",
        ]
        names = migrate_legacy(sources)
        print_json({"ok": True, "migrated_names": names, "values_exposed": False})
    elif args.command == "secrets" and args.secret_command == "status":
        print_json(SecretResolver().status(args.names))
    elif args.command == "secrets" and args.secret_command == "set":
        value = os.environ.get(args.from_env) if args.from_env else getpass.getpass(
            f"{args.name}: "
        )
        if not value:
            raise SystemExit("未提供密钥值")
        WindowsDPAPIVault().set(args.name, value)
        print_json({"ok": True, "name": args.name, "value_exposed": False})
    elif args.command == "secrets" and args.secret_command == "delete":
        deleted = WindowsDPAPIVault().delete(args.name)
        print_json({"ok": True, "name": args.name, "deleted": deleted})


if __name__ == "__main__":
    main()
