#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_human_gate.py — 能力层真人闸门回归测试（伪造攻击测试）
============================================================
验证 record/confirm/override/escalate/advance/revoke 仅限真人终端：

  · 负向(真实子进程) : 裸跑 / 管道注入 两种伪造路径必须被拒，state 不变
  · 正向(打桩 input) : 模拟真人 TTY 键入 step id → 通过并写入来源+审计
  · 惰性验证         : 历史误置的裸 user_confirm=True（无 user_confirm_source）
                       即使以"真人"身份 advance 也必须被门禁拒绝

用法:
  python orchestrator/test_human_gate.py
  （要求先 init 一个 guard-test-001 运行；结束会清理它）
"""
import builtins
import json
import os
import subprocess
import sys

ORCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "top-agent-orchestrator.py")
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
TEST_RUN = "guard-test-001"
COST_FILE = os.path.join(STATE_DIR, "guard-test-cost.json")

PASS = 0
FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✅ PASS %s%s" % (label, ("  " + extra) if extra else ""))
    else:
        FAIL += 1
        print("  ❌ FAIL %s%s" % (label, ("  " + extra) if extra else ""))


def state_of(run_id):
    with open(os.path.join(STATE_DIR, run_id + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def real(argv, stdin_data=None, expect_code=1):
    """真实子进程执行编排器命令。stdin_data 为 None 表示不提供输入(裸跑)。"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, ORCH] + argv, input=stdin_data,
                       capture_output=True, encoding="utf-8", errors="replace",
                       env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "").strip()


# ── 加载模块（import 不会触发 main）──
import importlib.util
_spec = importlib.util.spec_from_file_location("orch", ORCH)
orch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orch)


def run_mock(argv, answer):
    """打桩 builtins.input = answer，模拟真人在交互终端里键入了 step id。"""
    old_input, old_argv, old_stdin = builtins.input, sys.argv, sys.stdin
    class FakeTTY:
        def isatty(self):
            return True
    def fake_input(prompt=""):
        sys.stdout.write(prompt)
        sys.stdout.flush()
        return answer
    builtins.input = fake_input
    sys.stdin = FakeTTY()
    sys.argv = ["orch"] + argv
    try:
        orch.main()
        return 0
    except SystemExit as e:
        return e.code or 0
    finally:
        builtins.input, sys.argv, sys.stdin = old_input, old_argv, old_stdin


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("══ 能力层真人闸门 — 伪造攻击测试 ══")

    # ── 0. 准备（清掉可能的残留测试运行）──
    old_test = os.path.join(STATE_DIR, TEST_RUN + ".json")
    if os.path.isfile(old_test):
        os.remove(old_test)
    code, _ = real(["init", "--requirement", "能力层闸门测试", "--run-id", TEST_RUN], None, 0)
    check("init 可执行(执行者权限)", code == 0, "exit=%d" % code)
    with open(COST_FILE, "w", encoding="utf-8") as fh:
        json.dump({
            "currency": "CNY",
            "estimated_cost": "外部API增量预计¥0；订阅额度无法折算",
            "billing_basis": "测试使用本机执行器",
            "uncertainty": "medium",
            "unpriced_items": ["订阅额度"],
        }, fh, ensure_ascii=False)

    # ── 1. 负向: 裸跑 confirm（LLM Bash 场景）→ 必须被拒 ──
    before = state_of(TEST_RUN)
    code, out = real(["confirm", "step_1", "--run-id", TEST_RUN], None)
    after = state_of(TEST_RUN)
    check("负向·裸跑 confirm 被拒(exit!=0)", code != 0, "exit=%d" % code)
    check("负向·裸跑 confirm 不写 state",
          after["steps"]["step_1"]["gate"].get("confirmed") is False
          and after["steps"]["step_1"]["gate"].get("user_confirm_source") is None,
          out.splitlines()[-1] if out else "")

    # ── 2. 负向: 管道注入 confirm → 必须被拒 ──
    before = state_of(TEST_RUN)
    code, out = real(["confirm", "step_1", "--run-id", TEST_RUN], "step_1\n")
    after = state_of(TEST_RUN)
    check("负向·管道注入 confirm 被拒(exit!=0)", code != 0, "exit=%d" % code)
    check("负向·管道注入 confirm 不写 state",
          after["steps"]["step_1"]["gate"].get("confirmed") is False)

    # ── 3. 负向: 真人确认但缺预计费用 → 必须被拒 ──
    code = run_mock(["confirm", "step_1", "--run-id", TEST_RUN], "step_1")
    st = state_of(TEST_RUN)
    check("负向·缺预计费用仍被拒", code != 0 and not st["steps"]["step_1"]["gate"].get("confirmed"))

    # ── 4. 正向: 真人键入 step_1 且提供预计费用 → confirm 通过 ──
    code = run_mock([
        "confirm", "step_1", "--run-id", TEST_RUN,
        "--cost-estimate", COST_FILE,
    ], "step_1")
    st = state_of(TEST_RUN)
    g = st["steps"]["step_1"]["gate"]
    check("正向·confirm 通过(exit=0)", code == 0, "exit=%d" % code)
    check("正向·confirmed=True 且带真人来源",
          g.get("confirmed") is True and g.get("user_confirm_source", {}).get("channel") == "human_tty",
          json.dumps(g.get("user_confirm_source"), ensure_ascii=False))
    check("正向·预计费用带哈希写入门禁",
          bool(g.get("cost_estimate", {}).get("sha256")),
          json.dumps(g.get("cost_estimate"), ensure_ascii=False))
    check("正向·审计追加", any(e.get("command") == "confirm" for e in st.get("audit_log", [])),
          "audit_log=%d条" % len(st.get("audit_log", [])))

    # ── 5. 正向: revoke（撤销误置信号）→ 复位 ──
    code = run_mock(["revoke", "step_1", "--reason", "测试清理", "--run-id", TEST_RUN], "step_1")
    st = state_of(TEST_RUN)
    g = st["steps"]["step_1"]["gate"]
    check("正向·revoke 通过(exit=0)", code == 0, "exit=%d" % code)
    check("正向·revoke 复位 confirmed",
          g.get("confirmed") is False and g.get("user_confirm_source") is None
          and g.get("cost_estimate") is None)

    # ── 6. 惰性验证: 在隔离测试运行中伪造裸 user_confirm=True，仍不可 advance ──
    # 不再借用或修改任何真实运行的 state，避免回归测试污染生产审计记录。
    forged = state_of(TEST_RUN)
    forged["current_step"] = "step_4"
    forged_gate = forged["steps"]["step_4"]["gate"]
    forged_gate["fact_check"]["status"] = "passed"
    forged_gate["qa"]["status"] = "passed"
    forged_gate["user_confirm"] = True
    forged_gate["user_confirm_source"] = None
    forged_gate["cost_estimate"] = None
    forged_gate["passed"] = False
    forged["steps"]["step_4"]["status"] = "gate_pending"
    with open(os.path.join(STATE_DIR, TEST_RUN + ".json"), "w", encoding="utf-8") as fh:
        json.dump(forged, fh, ensure_ascii=False, indent=2)
    code = run_mock(["advance", "step_4", "--run-id", TEST_RUN], "step_4")
    after = state_of(TEST_RUN)
    after_cur = after["current_step"]
    after_gate = after["steps"]["step_4"]["gate"]
    check("惰性·伪造 user_confirm=True 无法 advance(exit!=0)", code != 0, "exit=%d" % code)
    check("惰性·current_step 未被推进", after_cur == "step_4", "cur=%s" % after_cur)
    check("惰性·无真人来源及费用不可放行",
          after_gate.get("user_confirm") is True
          and after_gate.get("user_confirm_source") is None
          and after_gate.get("cost_estimate") is None)

    # ── 7. 只读命令仍可用 ──
    code, out = real(["status", "--run-id", TEST_RUN], None, 0)
    check("只读·status 仍可执行(执行者权限)", code == 0, "exit=%d" % code)

    # ── 8. 清理测试运行 ──
    try:
        os.remove(os.path.join(STATE_DIR, TEST_RUN + ".json"))
        check("清理 guard-test-001", True)
    except OSError as e:
        check("清理 guard-test-001", False, str(e))
    try:
        os.remove(COST_FILE)
        check("清理费用测试文件", True)
    except OSError as e:
        check("清理费用测试文件", False, str(e))

    print("══ 结果: %d 通过 / %d 失败 ══" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
