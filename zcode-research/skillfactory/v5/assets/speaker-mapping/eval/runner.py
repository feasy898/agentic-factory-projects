#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval/runner.py — speaker-mapping 资产确定性评测器（机器可判，无随机/无网络/无时间戳）

用法：
    python eval/runner.py [<被测产物根> <参照产物根>]
  - 两参数：被测产物根在前，参照（oracle）产物根在后。
  - 零参数：两者均取内置缺省 <本文件>/../oracle/out（自校验：应全过 exit 0）。
  - 其它参数个数：用法错误，exit 2（信息走 stderr）。

产物根布局（冻结，目录平铺 24 个文件，与 oracle/out 同构）：
    {normal,partial,empty}__{m_full,m_partial,m_empty}.txt        9 个映射产物
    {normal,partial,empty}__{m_full,m_partial,m_empty}.stderr.txt 9 个警告存档
    discover__{normal,partial,empty}.json                          3 个扫描草稿
产出约定：在 oracle/ 目录为 cwd、以相对路径 --out 运行（contract.md §3），
否则 stderr INFO 行与 discover transcript 字段的路径回显会与基线不同。

固定 4 项检查（全部通过 exit 0 并打印 JSON；任一失败 exit 1）：
  1) replacement_line_by_line    9 个映射产物逐字节等于期望常量（全文见 spec.md 附录 A）
  2) unmapped_warnings           9 个 stderr 存档的 WARNING 集合与期望一致（未映射标签×次数；
                                 empty 组另查「映射键未出现」）
  3) discover_stats              3 个 discover JSON 的说话人清单（含首次出现顺序）、
                                 total_utterances、draft_mapping 正确
  4) reference_agreement_100pct  12 个主产物（9 txt + 3 json）与参照产物逐字节一致，要求 12/12

输出：stdout 打印 {"ok": bool, "summary": {total, pass, fail, tested_root, reference_root},
"checks": [{name, pass, detail}]}；无时间戳，同输入同输出（确定性）。
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.normpath(os.path.join(HERE, "..", "oracle", "out"))

TRANSCRIPTS = ("normal", "partial", "empty")
MAPPINGS = ("m_full", "m_partial", "m_empty")
MAP_COMBOS = [(t, m) for t in TRANSCRIPTS for m in MAPPINGS]
PRIMARY_FILES = ["%s__%s.txt" % (t, m) for (t, m) in MAP_COMBOS] + \
                ["discover__%s.json" % t for t in TRANSCRIPTS]

UNMAPPED_RE = re.compile(r'WARNING: 未映射说话人标签 "([^"]+)"，出现 (\d+) 次')
UNUSED_RE = re.compile(r'WARNING: 映射键 "([^"]+)" 在转写稿中未出现')

# ---------------------------------------------------------------------------
# 期望常量（oracle 实测基线；全文同步列于 spec.md 附录 A —— 增补条款 A-1）
# ---------------------------------------------------------------------------

# 9 个映射产物的期望全文（逐字节；UTF-8 / LF 行尾 / 结尾带换行）
EXPECTED_TXT = {
"normal__m_full.txt": (
"[00:00:05] 王总: 各位下午好，现在开始本周的项目例会，先同步一下进度。\n"
"[00:00:18] 李工: 好的。本周我们完成了用户调研，回收有效问卷 412 份。\n"
"[00:00:31] 赵秘书: 我补充一下，问卷的交叉分析报告已经放到共享目录了。\n"
"[00:00:47] 王总: 很好。下一个议题是新版本的排期，还有两个模块没有联调。\n"
"[00:01:03] 李工: 支付模块这边还差对账接口，我预计周四可以提测。\n"
"[00:01:20] 赵秘书: 消息推送模块的压测结果出来了，P99 延迟 230 毫秒，达标。\n"
"[00:01:38] 王总: 那就按这个节奏推进。风险方面有什么要提前报备的吗？\n"
"[00:01:52] 李工: 有一个：第三方短信通道月底要涨价，预算需要追加 2000 元。\n"
"[00:02:07] 赵秘书: 这笔我记到下周的评审议程里了。\n"
"[00:02:15] 王总: 好，今天的会就到这里，散会。\n"
),
"normal__m_partial.txt": (
"[00:00:05] 王总: 各位下午好，现在开始本周的项目例会，先同步一下进度。\n"
"[00:00:18] 李工: 好的。本周我们完成了用户调研，回收有效问卷 412 份。\n"
"[00:00:31] SPEAKER_02: 我补充一下，问卷的交叉分析报告已经放到共享目录了。\n"
"[00:00:47] 王总: 很好。下一个议题是新版本的排期，还有两个模块没有联调。\n"
"[00:01:03] 李工: 支付模块这边还差对账接口，我预计周四可以提测。\n"
"[00:01:20] SPEAKER_02: 消息推送模块的压测结果出来了，P99 延迟 230 毫秒，达标。\n"
"[00:01:38] 王总: 那就按这个节奏推进。风险方面有什么要提前报备的吗？\n"
"[00:01:52] 李工: 有一个：第三方短信通道月底要涨价，预算需要追加 2000 元。\n"
"[00:02:07] SPEAKER_02: 这笔我记到下周的评审议程里了。\n"
"[00:02:15] 王总: 好，今天的会就到这里，散会。\n"
),
"normal__m_empty.txt": (
"[00:00:05] SPEAKER_00: 各位下午好，现在开始本周的项目例会，先同步一下进度。\n"
"[00:00:18] SPEAKER_01: 好的。本周我们完成了用户调研，回收有效问卷 412 份。\n"
"[00:00:31] SPEAKER_02: 我补充一下，问卷的交叉分析报告已经放到共享目录了。\n"
"[00:00:47] SPEAKER_00: 很好。下一个议题是新版本的排期，还有两个模块没有联调。\n"
"[00:01:03] SPEAKER_01: 支付模块这边还差对账接口，我预计周四可以提测。\n"
"[00:01:20] SPEAKER_02: 消息推送模块的压测结果出来了，P99 延迟 230 毫秒，达标。\n"
"[00:01:38] SPEAKER_00: 那就按这个节奏推进。风险方面有什么要提前报备的吗？\n"
"[00:01:52] SPEAKER_01: 有一个：第三方短信通道月底要涨价，预算需要追加 2000 元。\n"
"[00:02:07] SPEAKER_02: 这笔我记到下周的评审议程里了。\n"
"[00:02:15] SPEAKER_00: 好，今天的会就到这里，散会。\n"
),
"partial__m_full.txt": (
"[00:00:04] 王总: 现在开始验收评审，请各位对照清单过一遍。\n"
"[00:00:19] SPEAKER_03: 大家好，我是新来的测试负责人，今天旁听加补位。\n"
"[00:00:33] 李工: 第一项，登录模块的回归用例 86 条全部通过。\n"
"[00:00:48] 赵秘书: 性能基线也复测了，和上周比没有回退。\n"
"[00:01:02] SPEAKER_03: 我这边发现一个低概率的空指针，已经提了缺陷单 BUG-1042。\n"
"[00:01:17] 王总: 严重级别评的什么？\n"
"[00:01:25] SPEAKER_03: P2，触发路径需要连续快速切换账号，建议下个迭代修。\n"
"[00:01:40] 李工: 同意，我排进迭代 14。\n"
"[00:01:52] 赵秘书: 那验收结论就是有条件通过，遗留一项 P2。\n"
"[00:02:03] 王总: 记录在案，散会。\n"
),
"partial__m_partial.txt": (
"[00:00:04] 王总: 现在开始验收评审，请各位对照清单过一遍。\n"
"[00:00:19] SPEAKER_03: 大家好，我是新来的测试负责人，今天旁听加补位。\n"
"[00:00:33] 李工: 第一项，登录模块的回归用例 86 条全部通过。\n"
"[00:00:48] SPEAKER_02: 性能基线也复测了，和上周比没有回退。\n"
"[00:01:02] SPEAKER_03: 我这边发现一个低概率的空指针，已经提了缺陷单 BUG-1042。\n"
"[00:01:17] 王总: 严重级别评的什么？\n"
"[00:01:25] SPEAKER_03: P2，触发路径需要连续快速切换账号，建议下个迭代修。\n"
"[00:01:40] 李工: 同意，我排进迭代 14。\n"
"[00:01:52] SPEAKER_02: 那验收结论就是有条件通过，遗留一项 P2。\n"
"[00:02:03] 王总: 记录在案，散会。\n"
),
"partial__m_empty.txt": (
"[00:00:04] SPEAKER_00: 现在开始验收评审，请各位对照清单过一遍。\n"
"[00:00:19] SPEAKER_03: 大家好，我是新来的测试负责人，今天旁听加补位。\n"
"[00:00:33] SPEAKER_01: 第一项，登录模块的回归用例 86 条全部通过。\n"
"[00:00:48] SPEAKER_02: 性能基线也复测了，和上周比没有回退。\n"
"[00:01:02] SPEAKER_03: 我这边发现一个低概率的空指针，已经提了缺陷单 BUG-1042。\n"
"[00:01:17] SPEAKER_00: 严重级别评的什么？\n"
"[00:01:25] SPEAKER_03: P2，触发路径需要连续快速切换账号，建议下个迭代修。\n"
"[00:01:40] SPEAKER_01: 同意，我排进迭代 14。\n"
"[00:01:52] SPEAKER_02: 那验收结论就是有条件通过，遗留一项 P2。\n"
"[00:02:03] SPEAKER_00: 记录在案，散会。\n"
),
"empty__m_full.txt": (
"会议纪要（口述整理稿）\n"
"\n"
"本节为自由口述片段，未经过说话人分离处理。\n"
"[00:00:02] 会议在下午三点开始，地点是三号会议室。\n"
"全体与会人员先签署了保密协议，随后进入正题。\n"
"[00:01:30] 随后进入自由讨论环节，没有指定发言顺序。\n"
"记录完毕。\n"
),
"empty__m_partial.txt": (
"会议纪要（口述整理稿）\n"
"\n"
"本节为自由口述片段，未经过说话人分离处理。\n"
"[00:00:02] 会议在下午三点开始，地点是三号会议室。\n"
"全体与会人员先签署了保密协议，随后进入正题。\n"
"[00:01:30] 随后进入自由讨论环节，没有指定发言顺序。\n"
"记录完毕。\n"
),
"empty__m_empty.txt": (
"会议纪要（口述整理稿）\n"
"\n"
"本节为自由口述片段，未经过说话人分离处理。\n"
"[00:00:02] 会议在下午三点开始，地点是三号会议室。\n"
"全体与会人员先签署了保密协议，随后进入正题。\n"
"[00:01:30] 随后进入自由讨论环节，没有指定发言顺序。\n"
"记录完毕。\n"
),
}

# 9 组 stderr 存档的期望 WARNING：未映射标签 -> 出现次数（与顺序无关，比集合）
EXPECTED_WARNINGS = {
    "normal__m_full": {},
    "normal__m_partial": {"SPEAKER_02": 3},
    "normal__m_empty": {"SPEAKER_00": 4, "SPEAKER_01": 3, "SPEAKER_02": 3},
    "partial__m_full": {"SPEAKER_03": 3},
    "partial__m_partial": {"SPEAKER_03": 3, "SPEAKER_02": 2},
    "partial__m_empty": {"SPEAKER_00": 3, "SPEAKER_03": 3, "SPEAKER_01": 2, "SPEAKER_02": 2},
    "empty__m_full": {},
    "empty__m_partial": {},
    "empty__m_empty": {},
}

# 「映射键在转写稿中未出现」警告（仅 empty 转写稿会触发）
EXPECTED_UNUSED = {
    "empty__m_full": ["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"],
    "empty__m_partial": ["SPEAKER_00", "SPEAKER_01"],
    "empty__m_empty": [],
}

# discover__<t>.json 的期望统计（speakers 按首次出现顺序，顺序参与判定）
EXPECTED_DISCOVER = {
    "normal": {"total": 10,
               "speakers": [("SPEAKER_00", 4), ("SPEAKER_01", 3), ("SPEAKER_02", 3)]},
    "partial": {"total": 10,
                "speakers": [("SPEAKER_00", 3), ("SPEAKER_03", 3),
                             ("SPEAKER_01", 2), ("SPEAKER_02", 2)]},
    "empty": {"total": 0, "speakers": []},
}


def read_bytes(path):
    """读文件字节；不存在/不可读返回 (None, 原因)。"""
    if not os.path.isfile(path):
        return None, "缺少 %s" % path
    try:
        with open(path, "rb") as f:
            return f.read(), None
    except Exception as exc:  # noqa: BLE001
        return None, "无法读取 %s (%s)" % (path, exc)


def first_diff(expect_bytes, actual_bytes):
    """返回首个差异的行号与两侧行内容摘要；无差异返回 None。"""
    exp = expect_bytes.decode("utf-8", errors="replace").splitlines()
    act = actual_bytes.decode("utf-8", errors="replace").splitlines()
    for i in range(max(len(exp), len(act))):
        e = exp[i] if i < len(exp) else "<缺行>"
        a = act[i] if i < len(act) else "<缺行>"
        if e != a:
            return "第%d行 期望=%r 实测=%r" % (i + 1, e[:80], a[:80])
    return "仅行尾/编码差异（第%d字节附近）" % next(
        (k for k in range(min(len(expect_bytes), len(actual_bytes)))
         if expect_bytes[k] != actual_bytes[k]), 0)


def check1_replacement(root, checks):
    """C1：9 个映射产物逐字节等于期望常量（替换正确 + 未映射原样 + 时间戳/冒号/正文不动）。"""
    bad = []
    for (t, m) in MAP_COMBOS:
        name = "%s__%s.txt" % (t, m)
        data, err = read_bytes(os.path.join(root, name))
        if err:
            bad.append("%s: %s" % (name, err))
            continue
        expect = EXPECTED_TXT[name].encode("utf-8")
        if data == expect:
            continue
        bad.append("%s: %s" % (name, first_diff(expect, data)))
    ok = not bad
    detail = ("9 组映射产物逐字节等于期望常量（含替换正确、未映射标签原样保留、"
              "时间戳/冒号/正文逐字节不动）" if ok
              else "不一致 %d/9: " % len(bad) + "; ".join(bad))
    checks.append({"name": "replacement_line_by_line", "pass": ok, "detail": detail})


def check2_warnings(root, checks):
    """C2：9 个 stderr 存档的 WARNING 集合与期望一致（未映射标签×次数 + empty 组映射键未出现）。"""
    bad = []
    for (t, m) in MAP_COMBOS:
        key = "%s__%s" % (t, m)
        name = key + ".stderr.txt"
        data, err = read_bytes(os.path.join(root, name))
        if err:
            bad.append("%s: %s" % (name, err))
            continue
        lines = data.decode("utf-8", errors="replace").splitlines()
        unmapped, unused, stray = {}, [], []
        for line in lines:
            w = UNMAPPED_RE.search(line)
            if w:
                unmapped[w.group(1)] = unmapped.get(w.group(1), 0) + int(w.group(2))
                continue
            u = UNUSED_RE.search(line)
            if u:
                unused.append(u.group(1))
                continue
            if "WARNING" in line:
                stray.append(line[:80])
        issues = []
        if unmapped != EXPECTED_WARNINGS[key]:
            issues.append("未映射警告 期望=%s 实测=%s" % (EXPECTED_WARNINGS[key], unmapped))
        if sorted(unused) != sorted(EXPECTED_UNUSED.get(key, [])):
            issues.append("映射键未出现警告 期望=%s 实测=%s"
                          % (EXPECTED_UNUSED.get(key, []), sorted(unused)))
        if stray:
            issues.append("无法识别的 WARNING 行: %s" % "; ".join(stray))
        if issues:
            bad.append("%s: %s" % (name, "; ".join(issues)))
    ok = not bad
    detail = ("9 组 stderr 存档的 WARNING 与期望逐一相符（未映射标签原样保留且有警告；"
              "empty+m_full 另有 3 条映射键未出现警告）" if ok
              else "警告不一致 %d/9: " % len(bad) + "; ".join(bad))
    checks.append({"name": "unmapped_warnings", "pass": ok, "detail": detail})


def check3_discover(root, checks):
    """C3：3 个 discover JSON 的说话人清单（含首次出现顺序）/总条数/草稿映射正确。"""
    bad = []
    for t in TRANSCRIPTS:
        name = "discover__%s.json" % t
        path = os.path.join(root, name)
        data, err = read_bytes(path)
        if err:
            bad.append("%s: %s" % (name, err))
            continue
        try:
            doc = json.loads(data.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            bad.append("%s: JSON 无法解析 (%s)" % (name, exc))
            continue
        exp = EXPECTED_DISCOVER[t]
        issues = []
        if not isinstance(doc, dict):
            issues.append("顶层不是 JSON 对象")
        else:
            got = [(s.get("label"), s.get("utterances")) for s in doc.get("speakers", [])
                   if isinstance(s, dict)]
            if got != exp["speakers"]:
                issues.append("speakers 期望=%s 实测=%s（含顺序）" % (exp["speakers"], got))
            if doc.get("total_utterances") != exp["total"]:
                issues.append("total_utterances 期望=%s 实测=%r"
                              % (exp["total"], doc.get("total_utterances")))
            draft = doc.get("draft_mapping")
            want_draft = {lbl: "" for lbl, _n in exp["speakers"]}
            if draft != want_draft:
                issues.append("draft_mapping 期望=%s 实测=%s" % (want_draft, draft))
            tr = doc.get("transcript")
            if not isinstance(tr, str) or not tr.endswith("%s.txt" % t):
                issues.append("transcript 字段须为以 %s.txt 结尾的字符串，实测=%r" % (t, tr))
        if issues:
            bad.append("%s: %s" % (name, "; ".join(issues)))
    ok = not bad
    detail = ("3 个 discover JSON 统计正确: normal 3人(4/3/3)、partial 4人(3/3/2/2，"
              "SPEAKER_03 按首次出现排第2)、empty 0人；draft_mapping 与清单一致" if ok
              else "不一致 %d/3: " % len(bad) + "; ".join(bad))
    checks.append({"name": "discover_stats", "pass": ok, "detail": detail})


def check4_agreement(root, ref_root, checks):
    """C4：12 个主产物（9 txt + 3 json）与参照产物逐字节一致，要求 12/12（本工具必须确定性）。"""
    diff, ref_broken = [], []
    for name in PRIMARY_FILES:
        t_data, t_err = read_bytes(os.path.join(root, name))
        r_data, r_err = read_bytes(os.path.join(ref_root, name))
        if t_err:
            diff.append("%s: 被测侧 %s" % (name, t_err))
            continue
        if r_err:
            ref_broken.append("%s: 参照侧 %s" % (name, r_err))
            continue
        if t_data != r_data:
            diff.append("%s: %s" % (name, first_diff(r_data, t_data)))
    pairs = len(PRIMARY_FILES)
    match = pairs - len(diff)
    ok = not diff and not ref_broken and match == pairs
    detail = "与参照产物逐字节一致 %d/%d（100%%，确定性要求）" % (match, pairs)
    if diff:
        detail += "，不一致: " + "; ".join(diff)
    if ref_broken:
        detail += "；参照产物缺失/损坏: " + "; ".join(ref_broken)
    checks.append({"name": "reference_agreement_100pct", "pass": ok, "detail": detail})


def main(argv):
    if len(argv) not in (0, 2):
        print("用法：python eval/runner.py [<被测产物根> <参照产物根>]"
              "（缺省两者均为 %s）" % DEFAULT_ROOT, file=sys.stderr)
        return 2
    tested, reference = (argv[0], argv[1]) if argv else (DEFAULT_ROOT, DEFAULT_ROOT)

    checks = []
    check1_replacement(tested, checks)
    check2_warnings(tested, checks)
    check3_discover(tested, checks)
    check4_agreement(tested, reference, checks)

    n_ok = sum(1 for c in checks if c["pass"])
    result = {
        "ok": n_ok == len(checks),
        "summary": {
            "total": len(checks),
            "pass": n_ok,
            "fail": len(checks) - n_ok,
            "tested_root": os.path.abspath(tested),
            "reference_root": os.path.abspath(reference),
        },
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
