#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py — 验收检查（全部实际执行）：

V1  8 个 out/<platform>/caseN/ 目录均存在，且恰含非空 骨架.md 与 structure.json
V2  structure.json 可解析，顶层必备键齐全，element_count == len(elements)
V3  每个 element 的 placeholder_count 与 open_placeholders 与其 text 重新正则计数一致；
    placeholder_stats.by_element 求和 == total_open；分元素计数与 elements 一致
V4  骨架.md 含主题词、四平台结构名与「占位符统计」节；video 平台含分镜表表头与时间轴
V5  确定性：每份样例用 gen.py 复跑到临时目录，两份产物与 out/ 内逐字节一致
V6  失败路径：非法 platform 退出码为 2 且不建产物目录

用法：python verify.py   （退出码 0=全部通过，1=有失败）
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "gen.py")
PLATFORMS = ["dy", "xhs", "wx", "video"]
PLACEHOLDER_RE = re.compile(r"【占位:([^】]*)】")
REQUIRED_KEYS = {"template_version", "platform", "platform_name", "structure_name",
                 "topic", "points_input_count", "points_used", "points_unused",
                 "element_count", "elements", "placeholder_stats"}
STRUCTURE_NAMES = {
    "dy": "3秒钩子 + 痛点 + 价值点×3 + CTA",
    "xhs": "标题带数字 + emoji规则 + 正文分块 + 标签组",
    "wx": "引子 + 三段论 + 金句收尾",
    "video": "分镜表：时间轴/画面/口播/字幕",
}

failures = []


def check(label, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", label, (" | " + detail) if detail else ""))
    if not cond:
        failures.append(label)


def iter_cases():
    for platform in PLATFORMS:
        case_dir = os.path.join(HERE, "inputs", platform)
        for name in sorted(os.listdir(case_dir)):
            if name.endswith(".json"):
                yield platform, os.path.splitext(name)[0], os.path.join(case_dir, name)


def main():
    # V1 存在性
    for platform, case_id, case_path in iter_cases():
        outdir = os.path.join(HERE, "out", platform, case_id)
        md = os.path.join(outdir, "骨架.md")
        sj = os.path.join(outdir, "structure.json")
        ok = os.path.isfile(md) and os.path.isfile(sj) and \
            os.path.getsize(md) > 0 and os.path.getsize(sj) > 0
        check("V1 %s/%s 产物存在且非空" % (platform, case_id), ok, outdir)

    tmp = tempfile.mkdtemp(prefix="oracle-verify-")
    try:
        for platform, case_id, case_path in iter_cases():
            outdir = os.path.join(HERE, "out", platform, case_id)
            sj_path = os.path.join(outdir, "structure.json")
            md_path = os.path.join(outdir, "骨架.md")
            with open(sj_path, "r", encoding="utf-8") as f:
                sj = json.load(f)
            with open(md_path, "r", encoding="utf-8") as f:
                md = f.read()

            # V2 顶层键与计数
            check("V2 %s/%s 顶层键齐全" % (platform, case_id), REQUIRED_KEYS <= set(sj),
                  str(sorted(REQUIRED_KEYS - set(sj))))
            check("V2 %s/%s element_count 自洽" % (platform, case_id),
                  sj["element_count"] == len(sj["elements"]))
            check("V2 %s/%s platform/结构名一致" % (platform, case_id),
                  sj["platform"] == platform and sj["structure_name"] == STRUCTURE_NAMES[platform])

            # V3 占位符计数自洽
            v3 = True
            detail = ""
            for el in sj["elements"]:
                n = len(PLACEHOLDER_RE.findall(el["text"]))
                toks = list(dict.fromkeys(PLACEHOLDER_RE.findall(el["text"])))
                if n != el["placeholder_count"] or toks != el["open_placeholders"]:
                    v3, detail = False, "element=%s 计数不符" % el["id"]
                    break
            check("V3 %s/%s 分元素占位符计数与文本一致" % (platform, case_id), v3, detail)
            stats = sj["placeholder_stats"]
            check("V3 %s/%s by_element 求和==total_open" % (platform, case_id),
                  sum(stats["by_element"].values()) == stats["total_open"])
            check("V3 %s/%s by_element 与 elements 一致" % (platform, case_id),
                  stats["by_element"] == {el["id"]: el["placeholder_count"] for el in sj["elements"]})

            # V4 骨架.md 内容抽查
            v4 = sj["topic"] in md and STRUCTURE_NAMES[platform] in md and "占位符统计" in md
            if platform == "video":
                v4 = v4 and "| 时间轴" in md and "00:00-00:03" in md
            check("V4 %s/%s 骨架.md 抽查" % (platform, case_id), v4)

            # V5 确定性复跑
            rerun_dir = os.path.join(tmp, "%s-%s" % (platform, case_id))
            proc = subprocess.run(
                [sys.executable, GEN, "--platform", platform,
                 "--topic", sj["topic"], "--points", case_path, "--outdir", rerun_dir],
                capture_output=True, text=True, encoding="utf-8")
            if proc.returncode != 0:
                check("V5 %s/%s 复跑成功" % (platform, case_id), False, proc.stderr.strip())
                continue
            same = True
            for fname in ("骨架.md", "structure.json"):
                with open(os.path.join(rerun_dir, fname), "rb") as f1, \
                     open(os.path.join(outdir, fname), "rb") as f2:
                    if f1.read() != f2.read():
                        same, diff_file = False, fname
                        break
            check("V5 %s/%s 复跑逐字节一致" % (platform, case_id), same)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # V6 失败路径：非法 platform -> 退出码 2 且不建目录
    bad_dir = os.path.join(HERE, "out", "_v6_must_not_exist")
    if os.path.isdir(bad_dir):
        shutil.rmtree(bad_dir)
    proc = subprocess.run(
        [sys.executable, GEN, "--platform", "bilibili", "--topic", "x",
         "--points", "[]", "--outdir", bad_dir],
        capture_output=True, text=True, encoding="utf-8")
    check("V6 非法 platform 退出码=2", proc.returncode == 2, proc.stderr.strip()[:120])
    check("V6 非法 platform 不建产物目录", not os.path.isdir(bad_dir))

    total = 0
    print("")
    if failures:
        print("verify 失败 %d 项：%s" % (len(failures), "；".join(failures)))
        sys.exit(1)
    print("verify 全部通过")


if __name__ == "__main__":
    main()
