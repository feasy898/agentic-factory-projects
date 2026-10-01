# -*- coding: utf-8 -*-
"""selfcheck_ab001.py — ab-001-rename/treatment 产物的 rubric 自检（本会话真实运行）。

复用资产自带评测器 eval/runner.py 的两个冻结检查函数（contract §3/§5 口径），
外加 rubric 逐条正则自检。运行：python selfcheck_ab001.py
"""
import re
import sys

EVAL = r"D:\workspace\zcode研究\skillfactory\assets\paper-to-skill\eval"
sys.path.insert(0, EVAL)
import runner  # noqa: E402

SKILL = r"D:\workspace\zcode研究\skillfactory\assets\paper-to-skill\tests\ab\ab-001-rename\treatment\SKILL.md"

results = []


def add(tag, ok, detail):
    results.append(bool(ok))
    runner_tags = {"structure", "steps"}
    print("[%s] %s : %s — %s" % ("runner" if tag in runner_tags else "rubric",
                                 tag, "PASS" if ok else "FAIL", detail))


# --- runner.py 冻结检查（原样调用，未改判定逻辑） ---
ok1, d1 = runner.check_skill_md_structure(SKILL)
add("structure", ok1, d1)
ok2, d2 = runner.check_steps_actionable(SKILL)
add("steps", ok2, d2)

lines = runner.read_lines(SKILL)
fm, _body_start = runner.split_frontmatter(lines)

# --- rubric: name 规范 ---
name = None
for l in fm:
    s = l.strip()
    if s.startswith("name:"):
        name = s[len("name:"):].strip()
ok3 = bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name or "")) and len(name or "") <= 64
add("name", ok3, "%s（%d 字符，正则 ^[a-z0-9]+(-[a-z0-9]+)*$ %s）"
    % (name, len(name or ""), "通过" if ok3 else "未通过"))

# --- rubric: description 单行标量、≤1024、含触发语 ---
desc = runner.description_value(fm)
raw = next(l for l in fm if l.strip().startswith("description:"))
is_block = bool(runner.BLOCK_SCALAR_RE.match(raw.split(":", 1)[1].strip()))
triggers = ["批量重命名", "整理目录内文件名"]
ok4 = desc is not None and not is_block and len(desc) <= 1024 and all(t in desc for t in triggers)
add("desc", ok4, "单行标量=%s，%d 字符 ≤1024，触发语齐=%s"
    % (not is_block, len(desc or ""), all(t in (desc or "") for t in triggers)))

# --- rubric: 分步方法 ≥3 条 ---
hs = runner.headings(lines)
steps_h = next((i for i, t in hs if runner.STEPS_HEADING_RE.search(t)), None)
end = next((i for i, _ in hs if i > steps_h), len(lines))
steps = runner.numbered_steps(lines, steps_h + 1, end)
add("steps_count", len(steps) >= 3, "%d 条编号步骤（≥3）" % len(steps))

# --- rubric: 常见坑 ≥2 条 ---
pit_idx = next((i for i, t in hs if runner.PITFALL_HEADING_RE.search(t)), None)
pit_end = next((i for i, _ in hs if i > pit_idx), len(lines))
pits = [l for l in lines[pit_idx + 1:pit_end] if l.strip().startswith("- ")]
add("pitfalls", len(pits) >= 2, "%d 条（≥2）" % len(pits))

# --- rubric: 来源引用含简报路径与 mv/rename 行为依据 ---
src_idx = next((i for i, t in hs if runner.SOURCE_HEADING_RE.search(t)), None)
src_end = next((i for i, _ in hs if i > src_idx), len(lines))
src_text = "\n".join(lines[src_idx + 1:src_end])
ok7 = ("batch-rename-brief.md" in src_text) and ("mv" in src_text) and ("rename" in src_text)
add("source", ok7, "含 batch-rename-brief.md 与 mv/os.rename/rename(2) 行为依据=%s" % ok7)

# --- rubric: 安全红线（dry-run 先行、重名跳过绝不覆盖）在正文显式成文 ---
body = "\n".join(lines)
ok8 = ("dry-run 先行" in body) and ("绝不覆盖" in body) and ("skipped" in body)
add("redline", ok8, "正文显式含「dry-run 先行」+「绝不覆盖」+ skipped 状态=%s" % ok8)

# --- rubric: 分步方法覆盖主流程四阶段（pattern 匹配→模板展开→dry-run→apply）---
steps_text = "\n".join(lines[steps_h + 1:next((i for i, _ in hs if i > steps_h), len(lines))])
stages = {"pattern 匹配": "匹配" in steps_text,
          "模板展开": ("模板" in steps_text and "序号" in steps_text),
          "dry-run 预览": "dry-run" in steps_text,
          "apply 执行": "apply" in steps_text}
ok9 = all(stages.values())
add("coverage", ok9, "主流程四阶段覆盖=%s" % stages)

print("RESULT: %d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
