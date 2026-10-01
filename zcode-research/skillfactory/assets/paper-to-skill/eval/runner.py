#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval/runner.py — paper-to-skill 确定性评测器（机器可判，无随机/无网络）

用法：
    python eval/runner.py <被测输出目录> <参照输出目录>
    例：python eval/runner.py package/out oracle/out           # 评被测实现（spec 例）
        python eval/runner.py package/out-blog oracle/out-blog # blog 例
        python eval/runner.py oracle/out oracle/out            # 自校验（应 exit 0）

- 单次评测一对目录：被测/参照目录各含 outline.json（+ draft_skill/SKILL.md）。
- SKILL.md 结构检查对象解析序（contract §5 冻结）：
    ① 被测目录的兄弟 example/SKILL.md（package/out → package/example/SKILL.md）；
    ② 兜底：被测目录内 draft_skill/SKILL.md（自校验/ad-hoc 模式）。
- 固定 3 项检查，全部通过 exit 0 并打印 JSON；任一失败 exit 1：
  1) example_skill_md_complete   SKILL.md 存在且五要素齐全（front-matter/触发描述/分步方法/常见坑/来源引用）
  2) steps_actionable            分步方法节内编号步骤 ≥2，且每步含可判定标记
                                 （原文 L数字 / 成对反引号命令路径 / 产物文件扩展名）
  3) outline_stats_within_30pct  被测 outline.json 全部数值统计与参照偏差 ≤30%
- 判定均为正则/数值比较；扫描标题与步骤时跳过围栏代码块内的行；无随机、无网络、无时间依赖。
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_PATH = os.path.join(HERE, "golden.json")

STATS_TOLERANCE = 0.30  # 数值统计相对偏差上限（|被测-参照| / max(|参照|,1)）

HEADING_RE = re.compile(r"^#{1,6}\s+\S")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
STEP_RE = re.compile(r"^\s*\d+[.、)]\s+\S")
# 分步方法各要素的识别正则（contract §3 冻结口径）
STEPS_HEADING_RE = re.compile(r"分步|步骤|steps", re.I)
PITFALL_HEADING_RE = re.compile(r"坑|注意|pitfalls?|caveats?", re.I)
SOURCE_HEADING_RE = re.compile(r"来源|引用|参考|sources?|references?", re.I)
# 步骤可判定标记（contract §3 冻结口径）
TRACE_RE = re.compile(r"原文\s*L\s*\d+", re.I)
ARTIFACT_EXT_RE = re.compile(r"\.(py|md|json|txt|csv|docx|pptx|xlsx)\b", re.I)
BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?$")


def read_lines(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().splitlines()


def is_fenced(lines, idx):
    """第 idx 行（0 起）是否处于围栏代码块内：扫描到 idx 为止的围栏开合计数。"""
    inside = False
    for i in range(idx):
        m = FENCE_RE.match(lines[i])
        if m:
            inside = not inside
    return inside


def split_frontmatter(lines):
    """返回 (fm_lines, body_start_idx)；无合法 front-matter 返回 (None, 0)。"""
    if not lines or lines[0].strip() != "---":
        return None, 0
    for i in range(1, min(30, len(lines))):
        if lines[i].strip() == "---":
            return lines[1:i], i + 1
    return None, 0


def description_value(fm_lines):
    """提取 description 值（支持块标量），去引号去空白后返回字符串；找不到返回 None。"""
    for i, line in enumerate(fm_lines):
        stripped = line.strip()
        if not stripped.startswith("description:"):
            continue
        value = stripped[len("description:"):].strip()
        if BLOCK_SCALAR_RE.match(value):  # YAML 块标量：取后续缩进行
            rest = []
            for ln in fm_lines[i + 1:]:
                if not ln.strip() or re.match(r"^\S", ln):
                    break
                rest.append(ln.strip())
            value = " ".join(rest)
        return value.strip("\"'").strip()
    return None


def headings(lines):
    """返回 [(行号 0 起, 标题行文本)]，跳过围栏内行。"""
    out = []
    inside = False
    for i, line in enumerate(lines):
        if FENCE_RE.match(line):
            inside = not inside
            continue
        if inside:
            continue
        if HEADING_RE.match(line):
            out.append((i, line))
    return out


def numbered_steps(lines, start, end):
    """[start, end) 行区间内的编号步骤行（0 起行号），跳过围栏内行。"""
    out = []
    inside = False
    for i in range(start, min(end, len(lines))):
        line = lines[i]
        if FENCE_RE.match(line):
            inside = not inside
            continue
        if inside:
            continue
        if STEP_RE.match(line):
            out.append((i, line.strip()))
    return out


def check_skill_md_structure(path):
    """五要素检查（contract §3）。返回 (ok, detail)。"""
    try:
        lines = read_lines(path)
    except Exception as exc:  # noqa: BLE001 - 报告原始错误
        return False, "无法读取 %s: %s" % (path, exc)
    if not lines:
        return False, "%s 为空文件" % path

    problems = []

    # 要素 1：front-matter（含 name/description）
    fm_lines, _ = split_frontmatter(lines)
    if fm_lines is None:
        problems.append("缺 front-matter（首行 --- 且前 30 行内有闭合 ---）")
        desc_ok, desc_len = False, 0
    else:
        has_name = any(l.strip().startswith("name:") and l.strip()[len("name:"):].strip()
                       for l in fm_lines)
        if not has_name:
            problems.append("front-matter 缺非空 name:")
        desc = description_value(fm_lines)
        desc_ok = bool(desc) and len(desc) >= 20
        desc_len = len(desc) if desc else 0
        if not desc_ok:
            problems.append("触发描述不足：description 值长度 %d < 20" % desc_len)

    # 要素 3/4/5：三个标题
    hs = headings(lines)
    steps_h = next(((i, t) for i, t in hs if STEPS_HEADING_RE.search(t)), None)
    pitfall_h = any(PITFALL_HEADING_RE.search(t) for _, t in hs)
    source_h = any(SOURCE_HEADING_RE.search(t) for _, t in hs)
    if steps_h is None:
        problems.append("缺「分步方法」标题（须匹配 分步|步骤|steps）")
    if not pitfall_h:
        problems.append("缺「常见坑」标题（须匹配 坑|注意|pitfalls?|caveats?）")
    if not source_h:
        problems.append("缺「来源引用」标题（须匹配 来源|引用|参考|sources?|references?）")

    detail = ("五要素齐全：front-matter(name+description) ✓ 触发描述 %d 字 ✓ 分步方法 ✓ "
              "常见坑 ✓ 来源引用 ✓（%s）" % (desc_len, os.path.basename(path))
              if not problems else "; ".join(problems))
    return not problems, detail


def check_steps_actionable(path):
    """步骤可判定检查。返回 (ok, detail)。"""
    try:
        lines = read_lines(path)
    except Exception as exc:  # noqa: BLE001 - 报告原始错误
        return False, "无法读取 %s: %s" % (path, exc)

    hs = headings(lines)
    steps_h = next(((i, t) for i, t in hs if STEPS_HEADING_RE.search(t)), None)
    if steps_h is None:
        return False, "未找到「分步方法」节，无法检查步骤可判定性"
    start = steps_h[0] + 1
    end = next((i for i, _ in hs if i > steps_h[0]), len(lines))
    steps = numbered_steps(lines, start, end)

    if len(steps) < 2:
        return False, "「分步方法」节内编号步骤仅 %d 条（须 ≥2）" % len(steps)

    bad = []
    for lineno, text in steps:
        markers = []
        if TRACE_RE.search(text):
            markers.append("原文行号")
        if text.count("`") >= 2:
            markers.append("命令/路径")
        if ARTIFACT_EXT_RE.search(text):
            markers.append("产物文件")
        if not markers:
            bad.append("L%d: %s" % (lineno + 1, text[:50]))
    if bad:
        return False, "%d/%d 步骤缺可判定标记（须含 原文L数字/成对反引号/产物扩展名 之一）-> %s" % (
            len(bad), len(steps), "; ".join(bad[:3]))
    return True, "%d 条编号步骤全部可判定（均含溯源/命令/产物标记之一，%s）" % (
        len(steps), os.path.basename(path))


def load_stats(path):
    """读取 outline.json 的 stats；返回 (dict, err)。"""
    if not os.path.isfile(path):
        return None, "缺 %s" % path
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001 - 报告原始错误
        return None, "%s 解析失败: %s" % (path, exc)
    stats = data.get("stats") if isinstance(data, dict) else None
    if not isinstance(stats, dict):
        return None, "%s 缺 stats 对象" % path
    return stats, None


def numeric_keys(stats):
    return sorted(k for k, v in stats.items()
                  if isinstance(v, (int, float)) and not isinstance(v, bool))


def check_outline_stats(cand_dir, ref_dir):
    """统计偏差 ≤30% 检查。返回 (ok, detail)。"""
    cand_stats, cand_err = load_stats(os.path.join(cand_dir, "outline.json"))
    if cand_err:
        return False, "被测: %s" % cand_err
    ref_stats, ref_err = load_stats(os.path.join(ref_dir, "outline.json"))
    if ref_err:
        return False, "参照: %s" % ref_err

    keys = numeric_keys(ref_stats)
    missing = [k for k in keys if k not in cand_stats]
    if missing:
        return False, "被测 stats 缺数值键: %s" % ", ".join(missing)

    overs, worst = [], ("", 0.0)
    for k in keys:
        dev = abs(cand_stats[k] - ref_stats[k]) / max(abs(ref_stats[k]), 1)
        if dev > worst[1]:
            worst = (k, dev)
        if dev > STATS_TOLERANCE + 1e-9:
            overs.append("%s: 被测 %s vs 参照 %s（偏差 %.1f%%）"
                         % (k, cand_stats[k], ref_stats[k], dev * 100))
    if overs:
        return False, "%d/%d 项统计超容差±%d%% -> %s" % (
            len(overs), len(keys), int(STATS_TOLERANCE * 100), "; ".join(overs))
    return True, "%d 项数值统计偏差均 ≤%d%%（最大 %s %.1f%%）" % (
        len(keys), int(STATS_TOLERANCE * 100), worst[0], worst[1] * 100)


def resolve_skill_md(cand_dir):
    """contract §5 解析序：兄弟 example/SKILL.md → 目录内 draft_skill/SKILL.md。"""
    cand_abs = os.path.abspath(cand_dir)
    parent = os.path.dirname(cand_abs)
    example = os.path.join(parent, "example", "SKILL.md")
    if os.path.isfile(example):
        return example, "example"
    draft = os.path.join(cand_abs, "draft_skill", "SKILL.md")
    if os.path.isfile(draft):
        return draft, "draft_skill"
    return None, None


def match_case(ref_dir, golden):
    """参照目录与 golden.eval_inputs[].output 匹配则返回 case 名，否则 ad-hoc。"""
    ref_abs = os.path.abspath(ref_dir)
    for item in golden.get("eval_inputs", []):
        if os.path.abspath(os.path.join(HERE, "..", item["output"])) == ref_abs:
            return item["case"]
    return "ad-hoc"


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    cand_dir, ref_dir = argv[1], argv[2]

    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        golden = json.load(f)
    case = match_case(ref_dir, golden)

    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    skill_path, skill_kind = resolve_skill_md(cand_dir)
    if skill_path is None:
        miss = ("找不到 SKILL.md（解析序：① %s/example/SKILL.md ② %s/draft_skill/SKILL.md）"
                % (os.path.dirname(os.path.abspath(cand_dir)), os.path.abspath(cand_dir)))
        add("example_skill_md_complete", False, miss)
        add("steps_actionable", False, miss)
    else:
        ok1, d1 = check_skill_md_structure(skill_path)
        add("example_skill_md_complete", ok1,
            "%s [判定对象=%s]" % (d1, skill_kind))
        ok2, d2 = check_steps_actionable(skill_path)
        add("steps_actionable", ok2, "%s [判定对象=%s]" % (d2, skill_kind))

    ok3, d3 = check_outline_stats(cand_dir, ref_dir)
    add("outline_stats_within_30pct", ok3, d3)

    ok = all(c["pass"] for c in checks)
    print(json.dumps({"ok": ok, "case": case, "checks": checks},
                     ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 非 tty 场景可能不支持
        pass
    sys.exit(main(sys.argv))
