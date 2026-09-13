#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
top-agent-orchestrator.py — TopAgent 流水线确定性编排器
========================================================

把 10 步流水线从「提示词散文」变成「可执行程序 + 强制门禁」。
流程不再依赖模型"自觉"，由本程序拦截：门禁不过，advance 拒绝。

════════════════════════════════════════════════════════════════
质量门禁（质量体系权限 — 强制两级独立审核）
════════════════════════════════════════════════════════════════
每个步骤产物进入下一步之前，必须依次通过两级独立门禁：

   产物 → ① 独立溯源验证 (fact-check-agent: 三层验证+溯源, 可信度 ≥70)
            ↓ 通过后才可以
         ② 独立质量审核 (qa-agent: 5维评分, 总分 ≥85)
            ↓ 通过后才可以
         进入下一步

  · 独立   : 验证者 ≠ 生产者。产出 agent 不能自己验自己。
  · 溯源   : 产物缺溯源(URL/文件路径/命令输出) → submit 即被拒，不进入任何验证。
  · 顺序   : 先溯源验证，通过后才允许提交质量审核。次序由本程序强制。
  · 联动   : 同一 agent 连续2次<60 或 安全红线 → Step 8.6 触发淘汰换新重训。

用法:
  python orchestrator/top-agent-orchestrator.py init --requirement "..." [--run-id X]
  python orchestrator/top-agent-orchestrator.py status
  python orchestrator/top-agent-orchestrator.py next
  python orchestrator/top-agent-orchestrator.py submit <step> <output_file>
  python orchestrator/top-agent-orchestrator.py prompt <step> fact_check|qa
  python orchestrator/top-agent-orchestrator.py record <step> fact_check <verdict.json>
  python orchestrator/top-agent-orchestrator.py record <step> qa <verdict.json>
  python orchestrator/top-agent-orchestrator.py record <step> verdict <verdict.json>
  python orchestrator/top-agent-orchestrator.py confirm <step>
  python orchestrator/top-agent-orchestrator.py override <step> --reason <理由>
  python orchestrator/top-agent-orchestrator.py escalate <step> --resolution <概述>
  python orchestrator/top-agent-orchestrator.py advance <step>
  python orchestrator/top-agent-orchestrator.py revoke <step> --reason <原因>   # 撤销误置信号

⚠️ 权限模型（能力层）: Agent(含主LLM) 只能「执行 + 登记产物」(init/submit)，无权「盖章/推进」。
   record / confirm / override / escalate / advance / revoke 属于推进/盖章级命令 ——
   仅真人终端可执行（stdin 须为交互终端 + 真人交互键入 step id）。无 --bypass 开关。

状态存于 orchestrator/state/<run_id>.json，产物存 orchestrator/outputs/<run_id>/。
"""
from __future__ import print_function

import argparse
import hashlib
import json
import os
import re
import sys
import datetime

ORCH_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_FILE = os.path.join(ORCH_DIR, "pipeline.json")
STATE_DIR = os.path.join(ORCH_DIR, "state")
OUTPUTS_DIR = os.path.join(ORCH_DIR, "outputs")

# ────────────────────────────── 工具 ──────────────────────────────

def load_pipeline():
    with open(PIPELINE_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def state_path(run_id):
    return os.path.join(STATE_DIR, run_id + ".json")


def load_state(run_id):
    p = state_path(run_id)
    if not os.path.isfile(p):
        die("状态不存在: %s （先运行 init）" % p)
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(state["run_id"]), "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def die(msg, code=1):
    print("❌ %s" % msg, file=sys.stderr)
    sys.exit(code)


def ok(msg):
    print("✅ %s" % msg)


# ─────────────────────── 能力层: 推进/盖章级命令 — 仅限真人终端 ───────────────────────
# 权限模型: Agent(含主LLM) 只能「执行 + 登记产物」(init/submit)，无权「盖章/推进」。
# record/confirm/override/escalate/advance/revoke 属于推进/盖章级 —— 默认仅真人终端可执行，
# 无 --bypass 开关。两道闸(需同时满足):
#   ① stdin 必须是交互终端 TTY  (阻止管道注入: echo x | python ...)
#   ② 必须真人交互键入目标 step id (阻止非交互执行: 裸 bash → stdin EOF → 拒绝)
# 残留风险(诚实声明): winpty/pty 模拟器可伪造终端 → 只防「Agent 顺手调用」类，
#   不防刻意构造终端的恶意操作者(后者本就能直接改代码)。
HUMAN_ONLY_COMMANDS = {"record", "confirm", "override", "escalate", "advance", "revoke"}


def _now():
    return datetime.datetime.now().isoformat()


def human_user():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def require_human(action_desc, token):
    """两因素真人闸门。失败 → die(退出码1, 不写 state)。"""
    if not sys.stdin.isatty():
        die("仅限真人终端: %s 属于推进/盖章级命令，只能由真人手动执行。\n"
            "  检测到 stdin 非交互(管道/重定向) → 拒绝。自动化/LLM 无法执行本命令。"
            % action_desc)
    print("⚠️ 真人确认 — %s" % action_desc)
    print("   检测: stdin 是交互终端 ✓")
    try:
        answer = input("   请真人输入「%s」确认执行（防误触）: " % token).strip()
    except EOFError:
        die("仅限真人终端: 检测到无交互输入(stdin EOF) → 判定为自动化调用，拒绝执行 %s。" % action_desc)
    if answer != token:
        die("确认失败: 输入 %r ≠ 期望 %r → 已中止，state 未改动。" % (answer, token))
    return human_user()


def audit(state, command, step, user, detail):
    """追加式审计（只能 append，由本程序保证；历史不可被命令路径改写）。"""
    state.setdefault("audit_log", [])
    state["audit_log"].append({
        "at": _now(), "command": command, "step": step,
        "channel": "human_tty", "user": user, "detail": detail,
    })


def ensure_step(state, pipeline, step_id):
    if step_id not in pipeline["steps"]:
        die("未知步骤: %s（可用: %s）" % (step_id, ", ".join(pipeline["steps_order"])))
    if step_id not in state["steps"]:
        die("步骤 %s 尚未初始化" % step_id)


def fresh_gate(gdef, max_retries=3):
    """按 gate 定义生成初始门禁状态。"""
    t = gdef.get("type", "none")
    base = {"type": t, "passed": False}
    if t == "two_stage":
        base.update({
            "fact_check_min": gdef.get("fact_check_min", 70),
            "qa_min": gdef.get("qa_min", 85),
            "user_confirm_after": gdef.get("user_confirm_after", False),
            "requires_cost_estimate": gdef.get("requires_cost_estimate", False),
            "cost_estimate": None,
            "max_retries": max_retries,
            "fact_check": {"status": "pending", "verdict_file": None, "confidence": None,
                           "attempts": 0, "last_verdict": None},
            "qa": {"status": "pending", "verdict_file": None, "score": None,
                   "attempts": 0, "last_verdict": None},
            "user_confirm": False,
            "escalated": False,
            "escalation": None,
            "override": {"active": False, "reason": None, "at": None},
        })
    elif t == "user_confirm":
        base["confirmed"] = False
        base["requires_cost_estimate"] = gdef.get("requires_cost_estimate", False)
        base["cost_estimate"] = None
    elif t == "verdict":
        base["status"] = "pending"
        base["verdict_file"] = None
        base["attempts"] = 0
        base["max_retries"] = max_retries
        base["escalated"] = False
        base["escalation"] = None
        base["override"] = {"active": False, "reason": None, "at": None}
    return base


# ────────────────────────── 结构级溯源检查 ──────────────────────────

_SRC_MARK = re.compile(r'(溯源|来源|Source|source)\s*[:：]')
_URL = re.compile(r'https?://[^\s)\]】》"\']+')
_VERIFY_MARK = re.compile(r'(验证|验证状态|Verification)\s*[:：]')
_VERIFY_STATE = re.compile(r'[⬜✅⚠️❌]|待验证|已验证|待核实|已核实')


def check_traceability(text):
    """确定性溯源检查（不依赖 LLM 判断）。返回 (ok, 问题列表, 来源计数)。"""
    problems = []
    urls = _URL.findall(text)
    # 行内溯源标记
    src_lines = [ln.strip() for ln in text.splitlines() if _SRC_MARK.search(ln)]
    # 文件路径 / 命令输出 / 反引号引用
    refs = re.findall(
        r'(?:[A-Za-z]:\\[^\s,;)\]]+|\./[^\s,;)\]]+\.(?:md|json|py|yaml|toml|log|txt)'
        r'|`[^`]{2,}`|命令输出|命令[:\s])', text)
    total_src = len(urls) + len(src_lines) + len(refs)
    if total_src == 0:
        problems.append("无任何溯源（URL/文件路径/命令输出/溯源标记）→ 判为「推测」，不得作为决策依据")
    return (len(problems) == 0), problems, total_src


def check_verification(text):
    """确定性验证状态检查。返回 (ok, 问题列表)。"""
    if not _VERIFY_MARK.search(text):
        return False, ["缺少「验证:」标记（统一输出协议要求每条产出带验证状态）"]
    if not _VERIFY_STATE.search(text):
        return False, ["「验证:」标记存在但无状态值（⬜待验证/✅/⚠️/❌ 至少一项）"]
    return True, []


# ────────────────────────── 门禁判定 ──────────────────────────

def gate_passed(gate):
    """当前 gate 是否全部通过（用于 advance 判定）。"""
    if gate.get("override", {}).get("active"):
        return True
    t = gate["type"]
    if t == "none":
        return True
    if t == "user_confirm":
        cost_ok = (not gate.get("requires_cost_estimate")) or gate.get("cost_estimate")
        return gate.get("confirmed", False) and cost_ok
    if t == "verdict":
        return gate.get("status") == "passed"
    if t == "two_stage":
        f = gate["fact_check"]["status"] == "passed"
        q = gate["qa"]["status"] == "passed"
        # 用户确认必须带真人来源记录（user_confirm_source 仅由 confirm 通过真人闸门后写入）
        # → 历史误置的裸 user_confirm=True 无法放行
        cost_ok = (not gate.get("requires_cost_estimate")) or gate.get("cost_estimate")
        u = (not gate["user_confirm_after"]) or (
            gate.get("user_confirm", False) and gate.get("user_confirm_source") and cost_ok)
        return f and q and u
    return False


def gate_block_reasons(gate):
    reasons = []
    t = gate["type"]
    if t == "user_confirm" and not gate.get("confirmed", False):
        reasons.append("等待用户确认 (confirm %s)" % ("<step>"))
    if t == "user_confirm" and gate.get("requires_cost_estimate") and not gate.get("cost_estimate"):
        reasons.append("审批缺少预计费用文件 (--cost-estimate <json>)")
    elif t == "verdict":
        if gate.get("escalated") and not gate.get("escalation"):
            reasons.append("已升级（第 %d 次打回）— 先 escalate <step> --resolution <处理概述>" % gate.get("attempts", 0))
        else:
            reasons.append("verdict 状态: %s（需 record ... verdict；已尝试 %d 次）" % (gate.get("status"), gate.get("attempts", 0)))
    elif t == "two_stage":
        if gate.get("escalated") and not gate.get("escalation"):
            reasons.append("已升级（连续打回）— 先 escalate <step> --resolution <处理概述> 记录升级处理，再重提")
        fc = gate["fact_check"]["status"]
        qa = gate["qa"]["status"]
        if fc != "passed":
            reasons.append("① 独立溯源验证未通过（当前 %s，需 ≥%d；已尝试 %d/%d 次）" % (
                fc, gate["fact_check_min"], gate["fact_check"].get("attempts", 0), gate.get("max_retries", 3)))
        else:
            if qa != "passed":
                reasons.append("② 独立质量审核未通过（当前 %s，需 ≥%d；已尝试 %d/%d 次）" % (
                    qa, gate["qa_min"], gate["qa"].get("attempts", 0), gate.get("max_retries", 3)))
        if gate["user_confirm_after"] and not (
                gate.get("user_confirm", False) and gate.get("user_confirm_source")):
            reasons.append("等待真人确认架构方案 (confirm %s) — 若存在历史误置的裸 user_confirm，先 revoke %s --reason <原因> 再重确认" % ("<step>", "<step>"))
        if gate.get("user_confirm_after") and gate.get("requires_cost_estimate") and not gate.get("cost_estimate"):
            reasons.append("架构审批缺少预计费用文件 (--cost-estimate <json>)")
    return reasons


def load_cost_estimate(path):
    """读取审批费用说明；只验证信息完整性，不设置预算或自动停止条件。"""
    if not path:
        die("本审批必须携带 --cost-estimate <json>，其中包含预计费用、依据和不确定性")
    full_path = os.path.abspath(path)
    if not os.path.isfile(full_path):
        die("预计费用文件不存在: %s" % full_path)
    try:
        raw = open(full_path, "rb").read()
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        die("预计费用文件无法读取或不是有效 JSON: %s" % exc)
    required = ("currency", "estimated_cost", "billing_basis", "uncertainty")
    missing = [key for key in required if data.get(key) in (None, "", [])]
    if missing:
        die("预计费用文件缺少字段: %s" % ", ".join(missing))
    if data["uncertainty"] not in ("low", "medium", "high", "低", "中", "高"):
        die("uncertainty 必须是 low/medium/high 或 低/中/高")
    return {
        "path": full_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "currency": data["currency"],
        "estimated_cost": data["estimated_cost"],
        "billing_basis": data["billing_basis"],
        "uncertainty": data["uncertainty"],
        "unpriced_items": data.get("unpriced_items", []),
        "recorded_at": _now(),
    }


# ────────────────────────── 命令实现 ──────────────────────────

def cmd_init(args):
    pipeline = load_pipeline()
    run_id = args.run_id or ("run-%s" % datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    if os.path.isfile(state_path(run_id)):
        die("运行 %s 已存在，换一个 --run-id" % run_id)
    state = {
        "run_id": run_id,
        "requirement": args.requirement,
        "created_at": datetime.datetime.now().isoformat(),
        "pipeline_version": pipeline["version"],
        "current_step": pipeline["steps_order"][0],
        "steps": {},
    }
    for sid in pipeline["steps_order"]:
        sdef = pipeline["steps"][sid]
        state["steps"][sid] = {
            "name": sdef["name"],
            "status": "pending",
            "outputs": [],
            "output_hash": None,
            "gate": fresh_gate(sdef["gate"], pipeline.get("max_retries", 3)),
        }
    save_state(state)
    ok("运行 %s 已初始化" % run_id)
    ok("需求: %s" % args.requirement)
    print("首步: %s" % describe_step(state, pipeline, state["current_step"]))


def describe_step(state, pipeline, step_id):
    sdef = pipeline["steps"][step_id]
    gate = state["steps"][step_id]["gate"]
    gname = {"two_stage": "两级门禁(溯源→QA)", "user_confirm": "用户确认", "verdict": "结构化裁决", "none": "无"}[gate["type"]]
    spawn = ", ".join(s["agent"] for s in sdef["spawn"]) or "TopAgent 直接处理"
    return "Step %s「%s」→ 执行: %s | 门禁: %s" % (
        step_id.replace("step_", ""), sdef["name"], spawn, gname)


def cmd_status(args):
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    print("运行: %s  需求: %s" % (state["run_id"], state["requirement"]))
    print("进度: %s  |  创建: %s" % (state["current_step"], state["created_at"]))
    print("-" * 78)
    for sid in pipeline["steps_order"]:
        st = state["steps"][sid]
        cur = "▶" if sid == state["current_step"] else " "
        mark = {"done": "✅", "produced": "⬜", "gate_pending": "🕐", "pending": "⏳"}.get(st["status"], "·")
        g = st["gate"]
        extra = ""
        if g["type"] == "two_stage":
            extra = "  溯源:%s(%d/%d) QA:%s(%d/%d)" % (
                g["fact_check"]["status"][:4], g["fact_check"].get("attempts", 0), g.get("max_retries", 3),
                g["qa"]["status"][:4], g["qa"].get("attempts", 0), g.get("max_retries", 3))
        elif g["type"] == "verdict":
            extra = "  %s(%d/%d)" % (g.get("status", "pending"), g.get("attempts", 0), g.get("max_retries", 3))
        if g.get("escalated"):
            extra += " ⚠️升级"
        if g.get("override", {}).get("active"):
            extra += " ⏭️人工override"
        print("%s %s %s. %-12s %-18s%s" % (cur, mark, sid.replace("step_", ""), st["name"], st["status"], extra))
    print("-" * 78)
    print("当前 → %s" % describe_step(state, pipeline, state["current_step"]))


def cmd_next(args):
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    step_id = state["current_step"]
    sdef = pipeline["steps"][step_id]
    st = state["steps"][step_id]
    print("▶ 当前步骤: %s「%s」" % (step_id, sdef["name"]))
    print("  说明: %s" % sdef["desc"])
    if sdef["spawn"]:
        print("  产出 Agent:")
        for s in sdef["spawn"]:
            print("    - Agent(%s): %s" % (s["agent"], s["task"]))
        print("  执行序列:")
        print("    1) 并行启动上述 Agent，产出保存到 orchestrator/outputs/%s/%s-<agent>.md" % (args.run_id, step_id))
        print("    2) python orchestrator/top-agent-orchestrator.py submit %s <output_file>" % step_id)
        print("    3) python orchestrator/top-agent-orchestrator.py prompt %s fact_check  → 启动 fact-check-agent 验证" % step_id)
        print("    4) python orchestrator/top-agent-orchestrator.py record %s fact_check <verdict.json>" % step_id)
        print("    5) python orchestrator/top-agent-orchestrator.py prompt %s qa  → 启动 qa-agent 审核" % step_id)
        print("    6) python orchestrator/top-agent-orchestrator.py record %s qa <verdict.json>" % step_id)
        print("    7) python orchestrator/top-agent-orchestrator.py advance %s" % step_id)
    else:
        if st["gate"]["type"] == "user_confirm":
            print("  本步由 TopAgent 直接完成。完成并确认后: confirm %s" % step_id)
        else:
            print("  本步由 TopAgent 直接完成。产出保存后: submit %s <output_file>，再过两级门禁" % step_id)


def cmd_submit(args):
    import hashlib
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    ensure_step(state, pipeline, args.step)
    st = state["steps"][args.step]
    out_path = args.output
    if not os.path.isfile(out_path):
        die("产物文件不存在: %s" % out_path)
    with open(out_path, encoding="utf-8") as fh:
        text = fh.read()
    if st["status"] == "done":
        die("步骤 %s 已完成，不能重复提交" % args.step)
    gate = st["gate"]
    # ── 升级中 / 未记录升级处理 → 拒绝重提 ──
    if gate.get("escalated") and not gate.get("escalation"):
        die("步骤 %s 已升级（连续打回）— 先运行 escalate %s --resolution <处理概述> 记录升级处理，再重新 submit" % (args.step, args.step))
    # ── 循环检测：同一内容重复提交 → 拒绝（未修正）──
    cur_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    last_rejected = (gate.get("fact_check", {}).get("status") == "rejected"
                     or gate.get("status") == "rejected"
                     or gate.get("qa", {}).get("status") == "rejected")
    if st.get("output_hash") == cur_hash and last_rejected:
        die("循环检测: 产物内容与上次被驳回时完全相同 → 未修正，禁止重复提交。请修正溯源/质量缺陷后重提。")
    st["output_hash"] = cur_hash
    # ── 结构级门禁（确定性，不依赖 LLM）──
    ok_t, prob_t, n_src = check_traceability(text)
    ok_v, prob_v = check_verification(text)
    if not ok_t or not ok_v:
        print("❌ 门禁拦截 — 产物未通过结构校验（缺溯源/验证即拒，不进入任何独立验证）:")
        for p in prob_t + prob_v:
            print("    - %s" % p)
        die("submit 拒绝。请补充溯源+验证后重提。")
    if gate["type"] == "two_stage":
        # 保留 attempts（跨提交累计打回次数，到上限触发升级）；仅重置状态
        fc = gate["fact_check"]; fc["status"] = "awaiting"; fc["verdict_file"] = None; fc["confidence"] = None
        q = gate["qa"]; q["status"] = "pending"; q["verdict_file"] = None; q["score"] = None
        st["status"] = "gate_pending"
    elif gate["type"] == "verdict":
        gate["status"] = "awaiting"
        st["status"] = "gate_pending"
    elif gate["type"] == "none":
        gate["passed"] = True
        st["status"] = "produced"
    else:
        st["status"] = "produced"
    st["outputs"].append(out_path)
    save_state(state)
    ok("产物已登记: %s（溯源来源 %d 处，验证状态齐全）" % (out_path, n_src))
    if gate["type"] == "two_stage":
        print("下一步: prompt %s fact_check 启动独立溯源验证" % args.step)
    elif gate["type"] == "verdict":
        print("下一步: prompt %s verdict 启动结构化裁决" % args.step)


def _verdict_prompt(state, pipeline, step_id, verifier):
    sdef = pipeline["steps"][step_id]
    st = state["steps"][step_id]
    gate = st["gate"]
    if gate["type"] == "two_stage":
        if verifier == "fact_check":
            return ("你是独立事实溯源验证者 fact-check-agent（不代表任何产出方）。\n"
                    "对 Step %s「%s」的产物逐条做三层验证（知识库→互联网→可信度评级），"
                    "每条结论必须能溯源（URL/文件路径/命令输出），无源=⚫无法验证=推测。\n"
                    "输出 JSON 到文件：\n"
                    "{\"verifier\":\"fact-check-agent\",\"step\":\"%s\",\"confidence\":<0-100整数>,\n"
                    " \"passed\":<confidence>=%d,\"sources\":[<≥1个来源>],\n"
                    " \"failing_claims\":[<未通过溯源的结论>],\"notes\":\"\"}\n"
                    "confidence 低于 %d → passed=false，产物打回。") % (
                step_id.replace("step_", ""), sdef["name"], step_id, gate["fact_check_min"], gate["fact_check_min"])
        if verifier == "qa":
            return ("你是独立质量审核师 qa-agent（最高审核权，不代表任何产出方）。\n"
                    "对 Step %s「%s」的产物做5维独立质量审核（正确率30/代码质量20/执行效率20/创新能力10/稳定性20）。\n"
                    "该产物已通过独立溯源验证，现在做质量审核。\n"
                    "输出 JSON 到文件：\n"
                    "{\"verifier\":\"qa-agent\",\"step\":\"%s\",\"score\":<0-100整数>,\n"
                    " \"passed\":<score>=%d,\"verdict\":\"approve|rework|reject\",\n"
                    " \"dimensions\":{\"correctness\":0,\"code_quality\":0,\"efficiency\":0,\"innovation\":0,\"stability\":0},\n"
                    " \"notes\":\"\"}\n"
                    "score 低于 %d → passed=false，重做后重审；安全红线 → 立即否决。") % (
                step_id.replace("step_", ""), sdef["name"], step_id, gate["qa_min"], gate["qa_min"])
    if gate["type"] == "verdict":
        agent = sdef["spawn"][0]["agent"]
        return ("你是 %s（%s 的独立执行者）。\n"
                "按要求完成 %s 任务并输出**结构化 JSON 裁决**到文件，必须携带溯源(sources 至少1项)：\n"
                "{\"verifier\":\"%s\",\"step\":\"%s\",\"passed\":true,\n"
                " \"sources\":[<来源URL/文件路径/命令输出>],\n"
                " \"data\":{...任务产出...},\"notes\":\"\"}\n"
                "sources 为空视为无效裁决。") % (agent, step_id, sdef["name"], agent, step_id)
    die("步骤 %s 门禁类型 %s 不支持 verifier %s" % (step_id, gate["type"], verifier))


def cmd_prompt(args):
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    ensure_step(state, pipeline, args.step)
    print(_verdict_prompt(state, pipeline, args.step, args.verifier))


def _load_json(path):
    if not os.path.isfile(path):
        die("裁决文件不存在: %s" % path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        die("裁决文件不是合法 JSON: %s（%s）" % (path, e))


def cmd_record(args):
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    ensure_step(state, pipeline, args.step)
    st = state["steps"][args.step]
    gate = st["gate"]
    # ── 前置门禁：必须先 submit（结构校验通过，output_hash 已落）才能记录裁决 ──
    if gate["type"] in ("two_stage", "verdict") and not st.get("output_hash"):
        die("顺序门禁拦截: 必须先 submit %s <产物文件> 通过结构校验（缺溯源即拒），才能记录裁决 — 禁止跳过 submit 硬推" % args.step)
    v = _load_json(args.verdict)

    # ── 独立性校验：裁决者必须是指定的独立 agent ──
    expected = {"fact_check": "fact-check-agent", "qa": "qa-agent", "verdict": None}
    if args.verifier == "verdict":
        expected["verdict"] = pipeline["steps"][args.step]["spawn"][0]["agent"]
    if v.get("verifier") != expected[args.verifier]:
        die("独立校验拒绝: 裁决 verifier=%r 应为 %r（验证者≠生产者）" % (
            v.get("verifier"), expected[args.verifier]))

    if args.verifier == "fact_check":
        if gate["type"] != "two_stage":
            die("步骤 %s 无 fact_check 门禁" % args.step)
        conf = int(v.get("confidence", -1))
        passed = v.get("passed", False)
        if not v.get("sources"):
            die("fact-check 裁决缺 sources → 无效")
        if passed != (conf >= gate["fact_check_min"]):
            die("fact-check 裁决自相矛盾: confidence=%d 与 passed=%s 不符" % (conf, passed))
        fc = gate["fact_check"]
        fc["attempts"] = fc.get("attempts", 0) + 1
        fc["verdict_file"] = args.verdict
        fc["confidence"] = conf
        fc["last_verdict"] = "passed" if passed else "rejected"
        if passed:
            fc["status"] = "passed"
            save_state(state)
            ok("① 独立溯源验证通过（confidence=%d ≥ %d，第 %d 次）" % (conf, gate["fact_check_min"], fc["attempts"]))
            print("→ 现在可以提交质量审核: prompt %s qa" % args.step)
        else:
            fc["status"] = "rejected"
            if fc["attempts"] >= gate.get("max_retries", 3):
                gate["escalated"] = True
                st["status"] = "escalated"
                save_state(state)
                print("❌ ① 独立溯源验证第 %d 次未通过 — 达到上限，流程暂停，触发升级:" % fc["attempts"])
                print("   1) Agent(failure-analysis-agent) 分析反复失败的根因")
                print("   2) Agent(eval-benchmark-agent) 给该产出Agent评分 → 连续2次<60 → 淘汰令")
                print("   3) Agent(agent-forge-agent) 换新重训（重写Prompt/换模型/补训练数据）")
                print("   4) 完成后: escalate %s --resolution <处理概述> 记录，然后重新 submit" % args.step)
                die("流程暂停：升级处理完成前禁止继续（不是死循环，是升级阶梯）")
            save_state(state)
            die("① 独立溯源验证未通过（confidence=%d < %d，第 %d/%d 次）→ 产物打回，修正后重提" % (
                conf, gate["fact_check_min"], fc["attempts"], gate.get("max_retries", 3)))

    elif args.verifier == "qa":
        if gate["type"] != "two_stage":
            die("步骤 %s 无 qa 门禁" % args.step)
        # ── 顺序门禁：先溯源通过，才允许质量审核 ──
        if gate["fact_check"]["status"] != "passed":
            die("顺序门禁拦截: 必须先在独立溯源验证通过后才能提交质量审核（当前 fact_check=%s）"
                % gate["fact_check"]["status"])
        score = int(v.get("score", -1))
        passed = v.get("passed", False)
        if passed != (score >= gate["qa_min"]):
            die("qa 裁决自相矛盾: score=%d 与 passed=%s 不符" % (score, passed))
        q = gate["qa"]
        q["attempts"] = q.get("attempts", 0) + 1
        q["verdict_file"] = args.verdict
        q["score"] = score
        q["last_verdict"] = "passed" if passed else "rejected"
        if passed:
            q["status"] = "passed"
            if gate["user_confirm_after"]:
                save_state(state)
                ok("② 独立质量审核通过（score=%d ≥ %d，第 %d 次），但本步还需用户确认架构方案: confirm %s" % (score, gate["qa_min"], q["attempts"], args.step))
            else:
                gate["passed"] = True
                st["status"] = "gate_passed"
                save_state(state)
                ok("② 独立质量审核通过（score=%d ≥ %d）→ 两级门禁全部通过，可 advance %s" % (score, gate["qa_min"], args.step))
        else:
            q["status"] = "rejected"
            if q["attempts"] >= gate.get("max_retries", 3):
                gate["escalated"] = True
                st["status"] = "escalated"
                save_state(state)
                print("❌ ② 独立质量审核第 %d 次未通过 — 达到上限，流程暂停，触发升级:" % q["attempts"])
                print("   1) Agent(failure-analysis-agent) 分析反复失败的根因")
                print("   2) Agent(eval-benchmark-agent) 给该产出Agent评分 → 连续2次<60 → 淘汰令")
                print("   3) Agent(agent-forge-agent) 换新重训（重写Prompt/换模型/补训练数据）")
                print("   4) 完成后: escalate %s --resolution <处理概述> 记录，然后重新 submit" % args.step)
                die("流程暂停：升级处理完成前禁止继续（不是死循环，是升级阶梯）")
            save_state(state)
            die("② 独立质量审核未通过（score=%d < %d，第 %d/%d 次）→ 修复后重审" % (
                score, gate["qa_min"], q["attempts"], gate.get("max_retries", 3)))

    elif args.verifier == "verdict":
        if gate["type"] != "verdict":
            die("步骤 %s 门禁类型不是 verdict" % args.step)
        if not v.get("sources"):
            die("verdict 裁决缺 sources → 无效（溯源是硬要求）")
        gate["attempts"] = gate.get("attempts", 0) + 1
        gate["verdict_file"] = args.verdict
        if v.get("passed"):
            gate["status"] = "passed"
            gate["passed"] = True
            st["status"] = "gate_passed"
            save_state(state)
            ok("verdict 通过（携带 %d 项来源，第 %d 次）→ 可 advance %s" % (len(v["sources"]), gate["attempts"], args.step))
        else:
            gate["status"] = "rejected"
            if gate["attempts"] >= gate.get("max_retries", 3):
                gate["escalated"] = True
                st["status"] = "escalated"
                save_state(state)
                print("❌ verdict 第 %d 次未通过 — 达到上限，流程暂停，触发升级（反失败分析 + 评分淘汰 + 换新重训）" % gate["attempts"])
                die("流程暂停：升级处理完成前禁止继续（不是死循环，是升级阶梯）")
            save_state(state)
            die("verdict 未通过（第 %d/%d 次）→ 修正后重提" % (gate["attempts"], gate.get("max_retries", 3)))


def cmd_confirm(args):
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    ensure_step(state, pipeline, args.step)
    step_id = args.step
    u = getattr(args, "human_user", None) or human_user()
    gate = state["steps"][step_id]["gate"]
    cost_estimate = None
    if gate.get("requires_cost_estimate"):
        cost_estimate = load_cost_estimate(args.cost_estimate)
    src = {"channel": "human_tty", "user": u, "at": _now()}
    if gate["type"] == "user_confirm":
        gate["confirmed"] = True
        gate["user_confirm_source"] = src
        gate["cost_estimate"] = cost_estimate
        gate["passed"] = True
        state["steps"][step_id]["status"] = "gate_passed"
        audit(state, "confirm", step_id, u, "confirmed=True; cost_estimate=%s" % (
            cost_estimate["sha256"] if cost_estimate else "not_required"))
        save_state(state)
        ok("用户已确认（真人终端 %s）→ 可 advance %s" % (u, step_id))
    elif gate["type"] == "two_stage" and gate["user_confirm_after"]:
        gate["user_confirm"] = True
        gate["user_confirm_source"] = src
        gate["cost_estimate"] = cost_estimate
        audit(state, "confirm", step_id, u, "user_confirm=True; cost_estimate=%s" % (
            cost_estimate["sha256"] if cost_estimate else "not_required"))
        if gate_passed(gate):
            gate["passed"] = True
            state["steps"][step_id]["status"] = "gate_passed"
            save_state(state)
            ok("用户已确认架构方案（真人终端 %s）→ 两级门禁全部通过，可 advance %s" % (u, step_id))
        else:
            save_state(state)
            ok("用户已确认架构方案（真人终端 %s），仍缺: %s" % (u, " / ".join(gate_block_reasons(gate))))
    else:
        die("步骤 %s 无需用户确认" % step_id)


def cmd_escalate(args):
    """记录升级处理（反失败→评分淘汰→换新重训之后），解除升级，允许重提。"""
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    ensure_step(state, pipeline, args.step)
    st = state["steps"][args.step]
    gate = st["gate"]
    if not gate.get("escalated"):
        die("步骤 %s 未处于升级状态（没有连续打回到上限）" % args.step)
    if not args.resolution or not args.resolution.strip():
        die("必须提供 --resolution <处理概述>（升级处理结果，需含溯源，将写入审计记录）")
    u = getattr(args, "human_user", None) or human_user()
    gate["escalation"] = {
        "resolution": args.resolution.strip(),
        "at": datetime.datetime.now().isoformat(),
        "channel": "human_tty",
        "by": u,
    }
    gate["escalated"] = False
    for key in ("fact_check", "qa"):
        sub = gate.get(key)
        if isinstance(sub, dict):
            sub["status"] = "pending"
            sub["attempts"] = 0
            sub["verdict_file"] = None
            sub["confidence"] = None
            sub["score"] = None
    gate["status"] = "pending"
    gate["attempts"] = 0
    st["status"] = "pending"
    st["output_hash"] = None
    audit(state, "escalate", args.step, u, "escalation 已记录: %s" % gate["escalation"]["resolution"])
    save_state(state)
    ok("升级处理已记录（%s）— 重新 submit %s 提交修正产物，重新走两级门禁" % (gate["escalation"]["resolution"], args.step))


def cmd_override(args):
    """显式人工裁决 — 唯一的前进通道。必须带理由，写入审计，绝非静默硬推。"""
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    ensure_step(state, pipeline, args.step)
    st = state["steps"][args.step]
    gate = st["gate"]
    if not args.reason or not args.reason.strip():
        die("override 必须提供 --reason <理由>（人工裁决依据，将写入审计记录）")
    u = getattr(args, "human_user", None) or human_user()
    gate["override"] = {
        "active": True,
        "reason": args.reason.strip(),
        "at": datetime.datetime.now().isoformat(),
        "channel": "human_tty",
        "by": u,
    }
    gate["passed"] = True
    st["status"] = "overridden"
    audit(state, "override", args.step, u, "override=True: %s" % gate["override"]["reason"])
    save_state(state)
    print("⏭️ 人工 override 已记录: 步骤 %s 由人工裁决放行（理由: %s，时间: %s）" % (
        args.step, gate["override"]["reason"], gate["override"]["at"]))
    print("   → advance %s" % args.step)


def cmd_revoke(args):
    """撤销误置的人类/推进信号（仅真人终端）。用于纠正被错误写入的 user_confirm/confirmed/override。"""
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    ensure_step(state, pipeline, args.step)
    step_id = args.step
    if not args.reason or not args.reason.strip():
        die("revoke 必须提供 --reason <原因>（为何撤销，将写入审计）")
    u = getattr(args, "human_user", None) or human_user()
    st = state["steps"][step_id]
    gate = st["gate"]
    # 复位所有"人类/推进"信号
    if gate["type"] == "two_stage":
        gate["user_confirm"] = False
        gate["user_confirm_source"] = None
        gate["cost_estimate"] = None
    elif gate["type"] == "user_confirm":
        gate["confirmed"] = False
        gate["user_confirm_source"] = None
        gate["cost_estimate"] = None
    gate["override"] = {"active": False, "reason": None, "at": None, "channel": None, "by": None}
    gate["passed"] = False
    if st["status"] in ("gate_passed", "overridden"):
        st["status"] = "gate_pending"
    audit(state, "revoke", step_id, u, "撤销信号: %s" % args.reason.strip())
    save_state(state)
    ok("已撤销 %s 的人类/推进信号（原因: %s，真人 %s）— 需重新走真人确认/门禁" % (step_id, args.reason.strip(), u))


def cmd_advance(args):
    pipeline = load_pipeline()
    state = load_state(args.run_id)
    ensure_step(state, pipeline, args.step)
    step_id = args.step
    if step_id != state["current_step"]:
        die("顺序门禁: 当前步骤是 %s，不能 advance %s" % (state["current_step"], step_id))
    st = state["steps"][step_id]
    if not gate_passed(st["gate"]):
        print("❌ advance 被拒绝 — 门禁未通过:")
        for r in gate_block_reasons(st["gate"]):
            print("    - " + r)
        die("流程被拦截：产物未通过独立溯源验证 + 独立质量审核，禁止进入下一步")
    if st["gate"].get("override", {}).get("active"):
        print("⏭️ 人工 override 推进（理由: %s）" % st["gate"]["override"]["reason"])
    st["status"] = "done"
    st["gate"]["passed"] = True
    order = pipeline["steps_order"]
    idx = order.index(step_id)
    if idx + 1 >= len(order):
        save_state(state)
        ok("🏁 流水线全部完成（%d 步）" % len(order))
        return
    state["current_step"] = order[idx + 1]
    save_state(state)
    ok("Step %s「%s」门禁通过，进入下一步" % (step_id.replace("step_", ""), st["name"]))
    print("▶ %s" % describe_step(state, pipeline, state["current_step"]))


# ────────────────────────── 入口 ──────────────────────────

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="TopAgent 流水线确定性编排器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化一次运行")
    p.add_argument("--requirement", required=True)
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_init)

    for name in ["status", "next"]:
        p = sub.add_parser(name)
        p.add_argument("--run-id", default=None)
        p.set_defaults(func=cmd_status if name == "status" else cmd_next)

    p = sub.add_parser("submit")
    p.add_argument("step")
    p.add_argument("output")
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("prompt")
    p.add_argument("step")
    p.add_argument("verifier", choices=["fact_check", "qa", "verdict"])
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("record")
    p.add_argument("step")
    p.add_argument("verifier", choices=["fact_check", "qa", "verdict"])
    p.add_argument("verdict")
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("confirm")
    p.add_argument("step")
    p.add_argument("--run-id", default=None)
    p.add_argument(
        "--cost-estimate",
        help="审批费用估算 JSON；需要人工确认的步骤必须提供",
    )
    p.set_defaults(func=cmd_confirm)

    p = sub.add_parser("escalate", help="记录升级处理（连续打回后），解除升级，允许重提")
    p.add_argument("step")
    p.add_argument("--resolution", required=True, help="升级处理结果（含溯源，写入审计）")
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_escalate)

    p = sub.add_parser("override", help="显式人工裁决（唯一前进通道，必须带理由，写入审计）")
    p.add_argument("step")
    p.add_argument("--reason", required=True, help="人工裁决依据")
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_override)

    p = sub.add_parser("revoke", help="撤销误置的人类/推进信号（仅真人终端，必须带原因）")
    p.add_argument("step")
    p.add_argument("--reason", required=True, help="撤销原因（写入审计）")
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_revoke)

    p = sub.add_parser("advance")
    p.add_argument("step")
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_advance)

    args = ap.parse_args()

    # ── 能力层: 推进/盖章级命令 — 仅限真人终端（先闸后行，无 --bypass）──
    if args.cmd in HUMAN_ONLY_COMMANDS:
        _desc = {"record": "记录独立验证裁决(通过戳)", "confirm": "用户确认",
                 "override": "人工放行", "escalate": "记录升级处理",
                 "advance": "推进到下一步", "revoke": "撤销误置信号"}.get(args.cmd, args.cmd)
        args.human_user = require_human(_desc, getattr(args, "step", None) or args.cmd)

    if args.cmd in ("status", "next", "submit", "prompt", "record", "confirm",
                    "escalate", "override", "advance", "revoke"):
        if not getattr(args, "run_id", None):
            # 默认取 state 目录下最新一个运行
            if not os.path.isdir(STATE_DIR):
                die("尚无运行状态，先 init")
            runs = sorted(f for f in os.listdir(STATE_DIR) if f.endswith(".json"))
            if not runs:
                die("尚无运行状态，先 init")
            args.run_id = runs[-1][:-5]

    # 审计入口（追加式）：每个推进/盖章级命令被真人触发
    if args.cmd in HUMAN_ONLY_COMMANDS:
        st = load_state(args.run_id)
        audit(st, args.cmd, getattr(args, "step", None), getattr(args, "human_user", "?"),
              "真人闸门通过，进入命令")
        save_state(state=st)

    args.func(args)


if __name__ == "__main__":
    main()
