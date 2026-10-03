#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval/runner.py — hot-templates（四平台爆款内容结构模板）确定性评测器（机器可判，无随机/无网络）

用法：
    python eval/runner.py <被测产物根> <参照产物根>
    例：python eval/runner.py package/out oracle/out     # 评被测实现
        python eval/runner.py oracle/out oracle/out      # 自校验（应 exit 0）

- 用例清单读本脚本同目录 golden.json 的 eval_inputs（8 例：dy/xhs/wx/video × case1/case2，
  case 值即产物根下的子目录路径，如 dy/case1）。
- 每个用例的样例输入（platform/topic/points）按 golden.json 的 input 路径定位（相对资产根）。
- 每用例固定 5 项检查，全部通过 exit 0 并打印 JSON；任一失败 exit 1：
  1) artifacts_present                      两份产物（骨架.md + structure.json）存在且非空、JSON 可解析
  2) structure_json_self_consistent         structure.json 顶层/要素/统计三层的键与计数自洽
  3) platform_template_complete             平台模板冻结要素齐备：dy 钩子+CTA（6 要素）；xhs 标题含
                                            数字与 emoji、标签数 3-8（7 要素）；wx 三段论标记（5 要素）；
                                            video 四列分镜表头+冻结时间轴（6 镜）；含卖点规整
                                            （缺失槽位落【占位:价值点N】、超出截断入 points_unused）
  4) sample_data_filled_no_template_residue 样例数据（主题/卖点）全部被填充，无 {{ }} 模板残留
  5) structure_consistency_with_reference   与参照产物逐项比对，结构一致率 ≥90%
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN_PATH = os.path.join(HERE, "golden.json")
ASSET_ROOT = os.path.dirname(HERE)  # 资产根 hot-templates/（golden 的 input 路径基准）

MD_NAME = "骨架.md"
SJ_NAME = "structure.json"
PLACEHOLDER_RE = re.compile(r"【占位:([^】]*)】")
CONSISTENCY_THRESHOLD = 0.9

REQUIRED_TOP_KEYS = {"template_version", "platform", "platform_name", "structure_name",
                     "topic", "points_input_count", "points_used", "points_unused",
                     "element_count", "elements", "placeholder_stats"}
REQUIRED_ELEMENT_KEYS = {"id", "name", "order", "required", "text", "placeholder_count",
                         "open_placeholders", "filled_from_input", "meta"}
REQUIRED_STATS_KEYS = {"total_open", "total_filled_from_input", "by_element",
                       "open_tokens_unique", "filled_slots"}

# 平台模板冻结（与 oracle/gen.py BUILDERS 一一对应）
PLATFORM_STRUCTURE_NAMES = {
    "dy": "3秒钩子 + 痛点 + 价值点×3 + CTA",
    "xhs": "标题带数字 + emoji规则 + 正文分块 + 标签组",
    "wx": "引子 + 三段论 + 金句收尾",
    "video": "分镜表：时间轴/画面/口播/字幕",
}
PLATFORM_ELEMENT_IDS = {
    "dy": ["hook_3s", "pain_point", "value_1", "value_2", "value_3", "cta"],
    "xhs": ["title", "hook_block", "point_block_1", "point_block_2", "point_block_3",
            "summary_block", "tag_group"],
    "wx": ["lead_in", "thesis_what", "thesis_why", "thesis_how", "golden_ending"],
    "video": ["shot_1", "shot_2", "shot_3", "shot_4", "shot_5", "shot_6"],
}
# 卖点槽位 i(1-3) 所在要素 id（wx 三个抓手同居 thesis_how）
VALUE_SLOT_ELEMENT = {
    "dy": lambda i: "value_%d" % i,
    "xhs": lambda i: "point_block_%d" % i,
    "wx": lambda i: "thesis_how",
    "video": lambda i: "shot_%d" % (2 + i),
}
# video 分镜时间轴（3/7/10/10/10/5 秒共 45 秒，冻结）
VIDEO_TIMELINE = ["00:00-00:03", "00:03-00:10", "00:10-00:20",
                  "00:20-00:30", "00:30-00:40", "00:40-00:45"]
VIDEO_TABLE_HEADER = "| 序号 | 时间轴 | 画面 | 口播 | 字幕 |"
# xhs emoji 映射（point_block_* 统一 💡）
XHS_EMOJI = {"title": "🔥", "hook_block": "✅", "summary_block": "📌", "tag_group": "🏷️"}


def load_text(path):
    """读文本文件；返回 (text, err)。"""
    if not os.path.isfile(path):
        return None, "缺文件: %s" % path
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read(), None
    except OSError as exc:
        return None, "无法读取 %s: %s" % (path, exc)


def load_json(path):
    """读 JSON 文件；返回 (data, err)。"""
    text, err = load_text(path)
    if err:
        return None, err
    if not text.strip():
        return None, "空文件: %s" % path
    try:
        return json.loads(text), None
    except ValueError as exc:
        return None, "JSON 解析失败 %s: %s" % (path, exc)


def case_subdir(root, case):
    """case（如 dy/case1）映射为产物根下的子目录。"""
    return os.path.join(root, *case.split("/"))


def norm_points(raw_points):
    """样例卖点规整：strip 全部项；返回 (pts, err)。"""
    if not isinstance(raw_points, list) or not all(isinstance(p, str) for p in raw_points):
        return None, "样例输入 points 不是字符串列表"
    return [p.strip() for p in raw_points], None


def slot_provided(pts, i):
    """卖点槽位 i(1-3) 是否有非空样例值。"""
    return i <= len(pts) and bool(pts[i - 1])


def count_placeholders(text):
    """返回（出现次数, 去重保序 token 列表）——与 oracle/gen.py 口径一致。"""
    toks = PLACEHOLDER_RE.findall(text)
    return len(toks), list(dict.fromkeys(toks))


def md_headings(md_text):
    """骨架.md 的全部小节标题行（## 开头），保序。"""
    return [ln.strip() for ln in md_text.splitlines() if ln.startswith("## ")]


# ---------------------------------------------------------------- 检查 1-2

def check_artifacts(case, cand_case):
    """检查 1：两份产物存在、非空、可解析。返回 (checks, ctx)。"""
    name = "%s/artifacts_present" % case
    md_path = os.path.join(cand_case, MD_NAME)
    sj_path = os.path.join(cand_case, SJ_NAME)
    if not os.path.isdir(cand_case):
        pre = "被测用例目录不存在: %s" % cand_case
    else:
        md_raw, err = load_text(md_path)
        if err:
            pre = "%s: %s" % (MD_NAME, err)
        else:
            sj_raw, err2 = load_text(sj_path)
            if err2:
                pre = "%s: %s" % (SJ_NAME, err2)
            elif not md_raw.strip():
                pre = "%s 为空" % MD_NAME
            else:
                sj, err3 = load_json(sj_path)
                if err3:
                    pre = err3
                else:
                    pre = None
                    ctx = {"md_raw": md_raw, "sj_raw": sj_raw, "sj": sj,
                           "md_path": md_path, "sj_path": sj_path}
                    return [{"name": name, "pass": True,
                             "detail": "%s（%d 字符）+ %s（%d 字符）均存在且可解析"
                                       % (MD_NAME, len(md_raw), SJ_NAME, len(sj_raw))}], ctx
    checks = []
    for suffix in ("artifacts_present", "structure_json_self_consistent",
                   "platform_template_complete",
                   "sample_data_filled_no_template_residue",
                   "structure_consistency_with_reference"):
        checks.append({"name": "%s/%s" % (case, suffix), "pass": False, "detail": pre})
    return checks, None


def check_self_consistent(case, sj, points, platform):
    """检查 2：structure.json 键与计数自洽（schema 见 spec R5/R6）。"""
    name = "%s/structure_json_self_consistent" % case
    problems = []
    missing_top = sorted(REQUIRED_TOP_KEYS - set(sj))
    if missing_top:
        problems.append("顶层缺键: %s" % "、".join(missing_top))
    if sj.get("platform") != platform:
        problems.append("platform=%r 与样例 %r 不符" % (sj.get("platform"), platform))
    if sj.get("structure_name") != PLATFORM_STRUCTURE_NAMES[platform]:
        problems.append("structure_name=%r 与冻结模板不符" % (sj.get("structure_name"),))
    if sj.get("topic") != str(sj.get("topic", "")).strip() or not str(sj.get("topic", "")).strip():
        problems.append("topic 为空或未规整")
    if sj.get("points_input_count") != len(points):
        problems.append("points_input_count=%r != 样例卖点数 %d"
                        % (sj.get("points_input_count"), len(points)))
    if not isinstance(sj.get("points_used"), list) or len(sj.get("points_used", [])) != 3:
        problems.append("points_used 不是长度 3 的列表")
    else:
        for i, v in enumerate(sj["points_used"], 1):
            if v is not None and not isinstance(v, str):
                problems.append("points_used 第 %d 项既非字符串也非 null" % i)
    if not isinstance(sj.get("points_unused"), list) or \
            not all(isinstance(p, str) for p in sj.get("points_unused", [])):
        problems.append("points_unused 不是字符串列表")
    elements = sj.get("elements")
    if not isinstance(elements, list) or not elements:
        problems.append("elements 缺失或为空")
    else:
        if sj.get("element_count") != len(elements):
            problems.append("element_count=%r != len(elements)=%d"
                            % (sj.get("element_count"), len(elements)))
        ids = [el.get("id") for el in elements]
        if len(set(ids)) != len(ids):
            problems.append("要素 id 有重复")
        if [el.get("order") for el in elements] != list(range(1, len(elements) + 1)):
            problems.append("order 不是从 1 连续递增")
        for el in elements:
            missing_el = REQUIRED_ELEMENT_KEYS - set(el)
            if missing_el:
                problems.append("要素 %r 缺键: %s" % (el.get("id"), "、".join(sorted(missing_el))))
                continue
            if el["required"] is not True:
                problems.append("要素 %s 的 required 不为 true" % el["id"])
            n, toks = count_placeholders(el["text"])
            if n != el["placeholder_count"] or toks != el["open_placeholders"]:
                problems.append("要素 %s 占位符计数/清单与 text 重计数不符" % el["id"])
            if not isinstance(el["meta"], dict):
                problems.append("要素 %s 的 meta 不是对象" % el["id"])
    stats = sj.get("placeholder_stats")
    if not isinstance(stats, dict):
        problems.append("placeholder_stats 缺失或不是对象")
    else:
        missing_stats = REQUIRED_STATS_KEYS - set(stats)
        if missing_stats:
            problems.append("placeholder_stats 缺键: %s" % "、".join(sorted(missing_stats)))
        elif isinstance(elements, list) and elements:
            if stats["by_element"] != {el["id"]: el["placeholder_count"] for el in elements}:
                problems.append("by_element 与分要素 placeholder_count 不一致")
            if sum(stats["by_element"].values()) != stats["total_open"]:
                problems.append("by_element 求和 != total_open")
            filled = []
            for el in elements:
                filled.extend(el["filled_from_input"])
            if stats["filled_slots"] != filled:
                problems.append("filled_slots 与各要素 filled_from_input 拼接不一致")
            if stats["total_filled_from_input"] != len(filled):
                problems.append("total_filled_from_input 与 filled_slots 长度不一致")
            uniq = []
            for el in elements:
                for t in count_placeholders(el["text"])[1]:
                    if t not in uniq:
                        uniq.append(t)
            if stats["open_tokens_unique"] != uniq:
                problems.append("open_tokens_unique 与重算去重清单不一致")
    return {"name": name, "pass": not problems,
            "detail": "schema 与计数全部自洽（%d 要素）" % len(elements) if not problems
            else "; ".join(problems[:6])}


# ---------------------------------------------------------------- 检查 3

def check_platform_template(case, sj, md_raw, pts, platform):
    """检查 3：平台模板冻结要素齐备 + 卖点规整（缺失槽位/截断）。"""
    name = "%s/platform_template_complete" % case
    problems = []
    elements = {el["id"]: el for el in sj["elements"]}
    if [el["id"] for el in sj["elements"]] != PLATFORM_ELEMENT_IDS[platform]:
        problems.append("要素 id 序列 %s 与冻结模板 %s 不符"
                        % ([el["id"] for el in sj["elements"]], PLATFORM_ELEMENT_IDS[platform]))
    for el in sj["elements"]:
        if not str(el.get("name", "")).strip():
            problems.append("要素 %s 的 name 为空" % el["id"])

    # 卖点规整（四平台通用，spec R4）：恰 3 槽位；缺失落【占位:价值点N】；超出截断入 points_unused
    expected_used = [pts[i] if slot_provided(pts, i + 1) else None for i in range(3)]
    if sj["points_used"] != expected_used:
        problems.append("points_used=%r 与规整策略期望 %r 不符" % (sj["points_used"], expected_used))
    if sj["points_unused"] != pts[3:]:
        problems.append("points_unused=%r 与截断期望 %r 不符" % (sj["points_unused"], pts[3:]))
    for i in range(1, 4):
        el = elements.get(VALUE_SLOT_ELEMENT[platform](i))
        if el is None:
            continue  # id 序列缺失已在上方记录
        if slot_provided(pts, i):
            if "point#%d" % i not in el["filled_from_input"]:
                problems.append("槽位 %d 已给卖点，但 %s 的 filled_from_input 不含 point#%d"
                                % (i, el["id"], i))
        else:
            token = "【占位:价值点%d】" % i
            if token not in el["text"]:
                problems.append("槽位 %d 缺失，但 %s 的 text 未落 %s" % (i, el["id"], token))

    if platform == "dy":
        for must in ("hook_3s", "cta"):
            if must in elements and not str(elements[must]["text"]).strip():
                problems.append("dy 必备要素 %s 的 text 为空" % must)
    elif platform == "xhs":
        title = elements.get("title", {}).get("text", "")
        if not re.search(r"\d", title):
            problems.append("xhs 标题不含数字")
        if XHS_EMOJI["title"] not in title:
            problems.append("xhs 标题不含 🔥")
        for el_id, emoji in [("hook_block", "✅"), ("summary_block", "📌"), ("tag_group", "🏷️")]:
            if elements.get(el_id, {}).get("meta", {}).get("emoji") != emoji:
                problems.append("xhs 要素 %s 的 meta.emoji 不是 %s" % (el_id, emoji))
        for i in (1, 2, 3):
            pb = elements.get("point_block_%d" % i, {})
            if pb.get("meta", {}).get("emoji") != "💡":
                problems.append("xhs point_block_%d 的 meta.emoji 不是 💡" % i)
        tag_text = elements.get("tag_group", {}).get("text", "")
        n_tags = len(re.findall(r"#[^\s#]+", tag_text))
        if not 3 <= n_tags <= 8:
            problems.append("xhs 标签数为 %d，不在 3-8 区间" % n_tags)
    elif platform == "wx":
        for el_id, marker in [("thesis_what", "一、是什么"), ("thesis_why", "二、为什么"),
                              ("thesis_how", "三、怎么办")]:
            text = elements.get(el_id, {}).get("text", "")
            if not text.startswith(marker):
                problems.append("wx 要素 %s 的 text 未以「%s」开头" % (el_id, marker))
        if "共勉" not in elements.get("golden_ending", {}).get("text", ""):
            problems.append("wx 金句收尾缺「共勉」")
    elif platform == "video":
        if VIDEO_TABLE_HEADER not in md_raw:
            problems.append("骨架.md 缺四列分镜表头「%s」" % VIDEO_TABLE_HEADER)
        if "共 45 秒" not in md_raw:
            problems.append("骨架.md 缺「共 45 秒」总时长标记")
        for idx, expect in enumerate(VIDEO_TIMELINE, 1):
            shot = elements.get("shot_%d" % idx, {})
            if shot.get("meta", {}).get("time_range") != expect:
                problems.append("分镜 %d 时间轴 %r 与冻结值 %s 不符"
                                % (idx, shot.get("meta", {}).get("time_range"), expect))
    return {"name": name, "pass": not problems,
            "detail": "%s 模板要素齐备（%d 要素，卖点 %d 条入正文/%d 条截断）"
                      % (platform, len(sj["elements"]), min(len(pts), 3), max(len(pts) - 3, 0))
                      if not problems else "; ".join(problems[:6])}


# ---------------------------------------------------------------- 检查 4

def check_sample_data(case, ctx, topic, pts):
    """检查 4：样例数据（主题/卖点）全部填充；无 {{ }} 模板残留。"""
    name = "%s/sample_data_filled_no_template_residue" % case
    problems = []
    md_raw, sj, sj_raw = ctx["md_raw"], ctx["sj"], ctx["sj_raw"]
    if sj.get("topic") != topic:
        problems.append("structure.json topic=%r != 样例主题 %r" % (sj.get("topic"), topic))
    if topic not in md_raw:
        problems.append("骨架.md 未出现样例主题「%s」" % topic)
    all_text = "\n".join(el["text"] for el in sj["elements"])
    for i, p in enumerate(pts[:3], 1):
        if p and p not in all_text:
            problems.append("卖点 %d「%s」未填充进任何要素 text" % (i, p))
    for p in pts[3:]:
        if p not in sj.get("points_unused", []):
            problems.append("截断卖点「%s」未记入 points_unused" % p)
    for label, raw in ((MD_NAME, md_raw), (SJ_NAME, sj_raw)):
        if "{{" in raw or "}}" in raw:
            problems.append("%s 存在 {{ }} 模板残留" % label)
    return {"name": name, "pass": not problems,
            "detail": "主题与 %d 条卖点全部落位，无 {{ }} 残留" % len(pts) if not problems
            else "; ".join(problems[:6])}


# ---------------------------------------------------------------- 检查 5

def structure_items(cand_sj, cand_md, ref_sj, ref_md):
    """逐项结构比对清单：返回 [(label, matched), ...]。"""
    items = []
    cand_els, ref_els = cand_sj["elements"], ref_sj["elements"]
    cand_by_id = {el["id"]: el for el in cand_els}
    ref_ids = [el["id"] for el in ref_els]
    items.append(("element_ids(顺序)", [el["id"] for el in cand_els] == ref_ids))
    for ref_el in ref_els:
        el = cand_by_id.get(ref_el["id"])
        for key in ("name", "order", "placeholder_count", "open_placeholders"):
            items.append(("el[%s].%s" % (ref_el["id"], key),
                          el is not None and el.get(key) == ref_el.get(key)))
    for key in ("element_count", "template_version", "platform", "structure_name",
                "points_used", "points_unused"):
        items.append((key, cand_sj.get(key) == ref_sj.get(key)))
    for key in ("total_open", "total_filled_from_input", "by_element"):
        items.append(("placeholder_stats.%s" % key,
                      cand_sj.get("placeholder_stats", {}).get(key)
                      == ref_sj.get("placeholder_stats", {}).get(key)))
    items.append(("md_headings", md_headings(cand_md) == md_headings(ref_md)))
    return items


def check_consistency(case, cand_root, ref_root, ctx):
    """检查 5：与参照产物结构一致率 ≥90%。"""
    name = "%s/structure_consistency_with_reference" % case
    ref_case = case_subdir(ref_root, case)
    ref_sj, err = load_json(os.path.join(ref_case, SJ_NAME))
    if err:
        return {"name": name, "pass": False, "detail": "参照产物不可用: %s" % err}
    ref_md, err = load_text(os.path.join(ref_case, MD_NAME))
    if err:
        return {"name": name, "pass": False, "detail": "参照产物不可用: %s" % err}
    items = structure_items(ctx["sj"], ctx["md_raw"], ref_sj, ref_md)
    matched = sum(1 for _, ok in items if ok)
    rate = matched / len(items) if items else 0.0
    misses = [label for label, ok in items if not ok]
    return {"name": name, "pass": rate >= CONSISTENCY_THRESHOLD,
            "rate": round(rate, 4),
            "detail": "结构一致率 %.1f%%（%d/%d，阈值 %.0f%%）%s"
                      % (rate * 100, matched, len(items), CONSISTENCY_THRESHOLD * 100,
                         "" if not misses else "；不一致项: " + "、".join(misses[:8]))}


# ---------------------------------------------------------------- 主流程

def check_case(case, item, cand_root, ref_root):
    """对单个 case 执行固定 5 项检查，返回 checks 列表。"""
    cand_case = case_subdir(cand_root, case)
    checks, ctx = check_artifacts(case, cand_case)
    if ctx is None:
        return checks

    sample, err = load_json(os.path.join(ASSET_ROOT, item["input"]))
    if err or not isinstance(sample, dict):
        pre = "样例输入不可读: %s" % (err or "不是 JSON 对象")
        for suffix in ("structure_json_self_consistent", "platform_template_complete",
                       "sample_data_filled_no_template_residue"):
            checks.append({"name": "%s/%s" % (case, suffix), "pass": False, "detail": pre})
        checks.append(check_consistency(case, cand_root, ref_root, ctx))
        return checks
    platform = sample.get("platform") or case.split("/")[0]
    topic = str(sample.get("topic", "")).strip()
    pts, err = norm_points(sample.get("points", []))
    if err:
        checks.append({"name": "%s/structure_json_self_consistent" % case, "pass": False,
                       "detail": err})
        checks.append({"name": "%s/platform_template_complete" % case, "pass": False,
                       "detail": err})
        checks.append({"name": "%s/sample_data_filled_no_template_residue" % case,
                       "pass": False, "detail": err})
        checks.append(check_consistency(case, cand_root, ref_root, ctx))
        return checks

    checks.append(check_self_consistent(case, ctx["sj"], pts, platform))
    checks.append(check_platform_template(case, ctx["sj"], ctx["md_raw"], pts, platform))
    checks.append(check_sample_data(case, ctx, topic, pts))
    checks.append(check_consistency(case, cand_root, ref_root, ctx))
    return checks


def main(argv):
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    cand_dir, ref_dir = argv[1], argv[2]
    golden, err = load_json(GOLDEN_PATH)
    if err:
        print("golden.json 不可读: %s" % err, file=sys.stderr)
        return 2
    eval_inputs = golden.get("eval_inputs", [])
    if not eval_inputs:
        print("golden.json eval_inputs 为空", file=sys.stderr)
        return 2

    checks = []
    for item in eval_inputs:
        checks.extend(check_case(item["case"], item, cand_dir, ref_dir))

    failed = [c for c in checks if not c["pass"]]
    rates = [c["rate"] for c in checks
             if c["name"].endswith("structure_consistency_with_reference") and "rate" in c]
    result = {
        "ok": not failed,
        "summary": {
            "cases": len(eval_inputs),
            "checks_total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "consistency_threshold": CONSISTENCY_THRESHOLD,
            "consistency_min": min(rates) if rates else None,
        },
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 非 tty 场景可能不支持
        pass
    sys.exit(main(sys.argv))
