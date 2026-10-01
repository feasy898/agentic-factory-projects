#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selfcheck_ab002.py — ab-002 treatment 成品 SKILL.md 的 rubric 自查（可原样复跑）。

判定依据 = golden.json ab_tasks[ab-002-weekly-report].rubric 五条 + paper-to-skill 方法论验收：
- 五要素与步骤可判定两项直接复用官方评测器 eval/runner.py 的同名检查函数（与 CLI 同一代码路径）；
- 其余为 rubric 专项（name 规范、description 触发场景与长度、三小节与空节规则、溯源红线、坑≥2、来源引用）。

用法：python _probe/selfcheck_ab002.py   （在本 treatment 目录内运行）
全部通过退出码 0 并打印 JSON；任一失败退出码 1。
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
SKILL = os.path.join(os.path.dirname(HERE), "SKILL.md")

# 官方评测器（其 SKILL.md 两项检查函数与 CLI 完全同代码路径）
spec = importlib.util.spec_from_file_location(
    "p2s_runner", os.path.join(ASSET_ROOT, "eval", "runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

# ---- rubric 专项正则（口径注释在每条旁） ----
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")          # agentskills.io name 规范
STEP_RE = re.compile(r"^\s*\d+[.、)]\s+\S")                 # 与 runner.py STEP_RE 同款
PITFALL_H_RE = re.compile(r"^#+\s*.*坑")                    # 常见坑节
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

checks = []


def add(name, ok, detail):
    checks.append({"name": name, "pass": bool(ok), "detail": detail})


with open(SKILL, "r", encoding="utf-8-sig") as fh:
    lines = fh.read().splitlines()

# ---------- 1) 官方五要素 + 步骤可判定（eval/runner.py 原函数，作用于最终交付文件） ----------
ok1, d1 = runner.check_skill_md_structure(SKILL)
add("runner_five_elements", ok1, d1)
ok2, d2 = runner.check_steps_actionable(SKILL)
add("runner_steps_actionable", ok2, d2)

# ---------- 2) front-matter 解析 ----------
assert lines[0].strip() == "---", "首行不是 ---"
close = next(i for i in range(1, 30) if lines[i].strip() == "---")
fm, body = lines[1:close], lines[close + 1:]


def fm_scalar(key):
    for ln in fm:
        s = ln.strip()
        if s.startswith(key + ":"):
            v = s[len(key) + 1:].strip()
            return v.strip("\"'")
    return None


name = fm_scalar("name")
desc_line = next((ln for ln in fm if ln.strip().startswith("description:")), "")
desc_raw = desc_line.strip()[len("description:"):].strip()
desc = desc_raw.strip("\"'")

# name 规范：小写字母/数字/连字符、≤64、无首尾/连续连字符
add("fm_name_spec", bool(NAME_RE.match(name or "")) and len(name) <= 64,
    "name=%r len=%d regex_ok=%s" % (name, len(name or ""), bool(NAME_RE.match(name or ""))))

# description：单行标量（非块标量）、≤1024 字符、含触发场景（每周五/周期性汇报）、≥3 个「」触发短语
block_scalar = bool(re.match(r"^[|>][+-]?$", desc_raw))
triggers = re.findall(r"「([^」]+)」", desc)
trig_ok = len(triggers) >= 3
scenario_ok = ("每周五" in desc) and ("周期性汇报" in desc)
add("fm_description_spec",
    (not block_scalar) and 0 < len(desc) <= 1024 and scenario_ok and trig_ok,
    "len=%d block_scalar=%s 每周五/周期性汇报=%s 触发短语%d个=%s"
    % (len(desc), block_scalar, scenario_ok, len(triggers), triggers[:6]))

# ---------- 3) 输出结构：固定三小节 + 空节规则 ----------
# 模板围栏内必须同时出现三个 H2 小节标题；正文必须有空节保留标题标注「无」的规则
inside, template_headings = False, []
for ln in body:
    if FENCE_RE.match(ln):
        inside = not inside
        continue
    if inside and re.match(r"^##\s+", ln):
        template_headings.append(ln.strip())
three = ["## 本周完成", "## 下周计划", "## 风险与求助"]
tpl_ok = all(any(h.startswith(t) for h in template_headings) for t in three)
body_text = "\n".join(body)
empty_rule_ok = ("空节处理" in body_text) and ("保留该节标题" in body_text) and ("无" in body_text)
add("structure_three_sections_and_empty_rule", tpl_ok and empty_rule_ok,
    "模板三小节=%s 空节规则(保留标题+无)=%s 模板标题=%s" % (tpl_ok, empty_rule_ok, template_headings))

# ---------- 4) 分步方法：≥3 条编号步骤（官方函数已验可判定标记，这里补数量下限） ----------
hs = runner.headings(lines)
steps_h = next(((i, t) for i, t in hs if runner.STEPS_HEADING_RE.search(t)), None)
end = next((i for i, _ in hs if steps_h and i > steps_h[0]), len(lines))
steps = runner.numbered_steps(lines, steps_h[0] + 1, end) if steps_h else []
add("steps_at_least_3", len(steps) >= 3, "编号步骤=%d 条（须 ≥3）" % len(steps))

# ---------- 5) 溯源红线：每条进展须对应输入记录、不得编造 ----------
redline_ok = ("溯源红线" in body_text and "不得编造" in body_text
              and "对应到输入中的某条记录" in body_text)
add("traceability_redline", redline_ok,
    "权威规则含【溯源红线】＋「不得编造」＋「对应到输入中的某条记录」=%s" % redline_ok)

# ---------- 6) 常见坑 ≥2 条，且每条含 现象→原因→正确做法 ----------
pit_h = next(((i, t) for i, t in hs if PITFALL_H_RE.search(t)), None)
pit_end = next((i for i, _ in hs if pit_h and i > pit_h[0]), len(lines))
pits, inside = [], False
for i in range((pit_h[0] + 1) if pit_h else 0, pit_end):
    ln = lines[i]
    if FENCE_RE.match(ln):
        inside = not inside
        continue
    if not inside and ln.startswith("- ") and not ln.startswith("- ["):
        pits.append(ln)
pit_ok = len(pits) >= 2 and all(
    ("现象" in p and "原因" in p and "正确做法" in p) for p in pits)
add("pitfalls_at_least_2", pit_ok, "常见坑=%d 条，均含现象/原因/正确做法=%s" % (len(pits), pit_ok))

# ---------- 7) 来源引用：注明 capability 简报 + 输入记录引用方式 ----------
src_h = next(((i, t) for i, t in hs if runner.SOURCE_HEADING_RE.search(t)), None)
src_end = next((i for i, _ in hs if src_h and i > src_h[0]), len(lines))
src_text = "\n".join(lines[src_h[0]:src_end]) if src_h else ""
src_ok = ("weekly-report-brief.md" in src_text) and ("输入记录的引用方式" in src_text)
add("sources_brief_and_input_citation", src_ok,
    "来源引用节含简报路径=%s、含输入记录引用方式=%s"
    % ("weekly-report-brief.md" in src_text, "输入记录的引用方式" in src_text))

# ---------- 汇总 ----------
ok = all(c["pass"] for c in checks)
print(json.dumps({"ok": ok, "skill_md": os.path.relpath(SKILL, ASSET_ROOT),
                  "checks": checks}, ensure_ascii=False, indent=2))
sys.exit(0 if ok else 1)
