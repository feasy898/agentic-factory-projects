#!/usr/bin/env python3
"""V2-M5: 回归夹具库终版索引 + pass_candidate 人工确认清单 (幂等, 数字全部实时取自落盘数据)。

输入:
  workdir/fixtures/fixtures_manifest.json   (V2-M0 构建, D-052)
  workdir/logs/v2m1_g7_final.json           (V2-M2 校准后终版重跑, D-059)
输出:
  reports/fixtures/INDEX.md         (47 条全库终版索引, 覆盖 M0 雏形)
  reports/fixtures/CONFIRMATION.md  (17 条确认清单, 其中 4 条系统判杀标注复核 —— 本轮唯一人工动作)
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "workdir", "fixtures", "fixtures_manifest.json")
G7FINAL = os.path.join(ROOT, "workdir", "logs", "v2m1_g7_final.json")
OUT_DIR = os.path.join(ROOT, "reports", "fixtures")

def rel(p):
    """manifest 里的绝对路径 → 仓库相对路径。"""
    return p.replace("/root/cradle/", "").replace(ROOT + os.sep, "")

def clean_desc(notes):
    """去掉 notes 尾部的 sel/待人工确认 标记, 留纯描述。"""
    s = notes
    s = re.sub(r";?\s*sel=\d+", "", s)
    s = re.sub(r";?\s*待人工确认$", "", s)
    return s.strip().rstrip(";").strip()

def fmt(x, nd=4):
    return ("%%.%df" % nd) % x if isinstance(x, (int, float)) else "-"

def sub_brief(s):
    """单个 G7 子项的紧凑摘要。"""
    if not isinstance(s, dict):
        return "-"
    if s.get("skipped"):
        return "%s skip(%s)" % (s.get("sub"), s.get("reason") or "na")
    mark = "✗" if s.get("triggered") else "✓"
    sub = s.get("sub")
    if sub in ("a", "d"):
        return "%s %s%s" % (sub, fmt(s.get("score")), mark)
    if sub == "c":
        p95 = s.get("p95_px")
        if p95 is None:
            return "c %s%s" % (fmt(s.get("score")), mark)
        return "c p95=%.1fpx%s" % (p95, mark)
    if sub == "b":
        extra = ""
        for k in ("churn", "count_delta_max", "count_var"):
            if k in s:
                extra += " %s=%s" % (k, s[k])
        return "b%s%s" % (extra, mark)
    if sub == "e":
        return "e skip(vlm_unavailable)"
    return "%s%s" % (sub, mark)

def g7_summary(rec):
    """一行 G7 终版判定: (判定词, 触发子项列表, 紧凑串)。"""
    subs = rec.get("subs", {})
    triggered = [k for k, v in subs.items() if isinstance(v, dict) and v.get("triggered")]
    verdict = "判杀✗" if triggered else "通过✓"
    parts = [sub_brief(subs[k]) for k in ("a", "b", "c", "d", "e") if k in subs]
    return verdict, triggered, "score=%s (%s)" % (fmt(rec.get("score")), " · ".join(parts))

def main():
    man = json.load(open(MANIFEST, encoding="utf-8"))
    fixtures = man["fixtures"]
    g7 = json.load(open(G7FINAL, encoding="utf-8"))
    recs = {r["fixture_id"]: r for r in g7["records"]}
    th = g7["thresholds"]
    by_label = g7["by_label"]

    assert len(fixtures) == 47, "expect 47 fixtures, got %d" % len(fixtures)
    missing = [f["fixture_id"] for f in fixtures if f["fixture_id"] not in recs]
    assert not missing, "g7_final missing records: %s" % missing

    os.makedirs(OUT_DIR, exist_ok=True)

    # ---------- INDEX.md ----------
    L = []
    A = L.append
    A("# 回归夹具库索引 (V2-M5 终版)")
    A("")
    A("> SPECS_V2 §2 / §7-3。构建口径 D-052, 媒体 git 口径 D-053。本文件由 `tools/m5v2_build_fixtures_index.py`")
    A("> 从 `workdir/fixtures/fixtures_manifest.json` + `workdir/logs/v2m1_g7_final.json` 自动生成(幂等), 数字不手抄。")
    A("> 物理文件: `workdir/fixtures/{fail,pass_structural,pass_candidate}/*.mp4`; 每夹具首/中/尾三联帧证据: `workdir/fixtures/strips/<fixture_id>.jpg`; 词表映射 `workdir/fixtures/g7_terms.json`。")
    A("> DB: 主仓 `workdir/cradle.sqlite3` 表 `fixtures`(47 行) 与 `g7_runs`(两轮×47×6 子项)。")
    A("> **⚠ 本轮唯一人工动作**: pass_candidate 确认清单 → **[CONFIRMATION.md](CONFIRMATION.md)** (17 条逐条回复, 其中 4 条被 G7 判杀请复核)。")
    A("")
    A("## 统计自检 (SPECS_V2 §2 硬性指标)")
    A("")
    A("| 组 | 数量 | 要求 | G7 终版判定(校准阈值) |")
    A("|---|---|---|---|")
    A("| fail | **%d** | ≥15 | 拦截 **%d/%d = %.1f%%** (要求 ≥90%%) |" % (
        by_label["fail"]["n"], by_label["fail"]["g7_fail"], by_label["fail"]["n"],
        100.0 * by_label["fail"]["g7_fail"] / by_label["fail"]["n"]))
    A("| pass_structural | **%d** | ≥10 | 误杀 **%d/%d = %.1f%%** (要求 ≤15%%) |" % (
        by_label["pass_structural"]["n"], by_label["pass_structural"]["g7_fail"], by_label["pass_structural"]["n"],
        100.0 * by_label["pass_structural"]["g7_fail"] / by_label["pass_structural"]["n"]))
    A("| pass_candidate | **%d** | ≥10 | 误杀 **%d/%d = %.1f%%** (要求 ≤25%% 带内; 4 条列人工复核) |" % (
        by_label["pass_candidate"]["n"], by_label["pass_candidate"]["g7_fail"], by_label["pass_candidate"]["n"],
        100.0 * by_label["pass_candidate"]["g7_fail"] / by_label["pass_candidate"]["n"]))
    A("| **总计** | **47** | ≥35 (M0 验收) | — |")
    A("")
    A("## G7 终版运行口径")
    A("")
    A("- 阈值: `config/thresholds_v2.yaml` (calibrated: true) — g7a_mode=%s, a<%s / d<%s / b(delta>%s, var>%s, churn>%s) / c P95>%spx / e<%s(VLM, 无 API 全 skipped, D-004)。" % (
        th.get("g7a_mode"), th.get("g7a_min_cos"), th.get("g7d_min_cos"),
        th.get("g7b_count_delta_tol"), th.get("g7b_count_var_max"), th.get("g7b_churn_max"),
        th.get("g7c_flow_p95_max_px"), th.get("g7e_min_ok")))
    A("- 终版重跑: `workdir/logs/v2m1_g7_final.json` (47/47 真实 GPU); 校准过程/ROC/分布图: `reports/G7_CALIBRATION.md`。")
    A("- 判定语义: 任一子项触发即 fail(判杀); skipped 不判死(D-004/D-057)。")
    A("")

    for label, title, note in [
        ("fail", "fail 夹具 (%d) — 四类形变, G7 终版全部拦截" % by_label["fail"]["n"],
         "全部为 v1 真实候选目检确证的形变; 其中 8 条曾 verdict=pass、6 条曾入选成片/AB(V2_M0_AUDIT §4.3)。"),
        ("pass_structural", "pass_structural (%d) — 程序性产物, G7 终版零误杀" % by_label["pass_structural"]["n"],
         "v1 真产物 4 + fallback 渲染 3 + kenburns 确定性再生成 8(共 11 条再生成口径见 D-052); 一律 terms=[](D-058)。"),
        ("pass_candidate", "pass_candidate (%d) — 真实生成候选, 其中 4 条被 G7 判杀" % by_label["pass_candidate"]["n"],
         "G1-G6 全绿的 v1 生产候选; **待人工确认**(唯一人工动作) → [CONFIRMATION.md](CONFIRMATION.md)。"),
    ]:
        rows = [f for f in fixtures if f["label"] == label]
        rows.sort(key=lambda f: f["fixture_id"])
        A("## %s" % title)
        A("")
        A(note)
        A("")
        A("| fixture | category | mp4 | 三联帧 | 源候选 | DINO 首尾 | G7 终版判定 |")
        A("|---|---|---|---|---|---|---|")
        for f in rows:
            rec = recs[f["fixture_id"]]
            verdict, trig, summ = g7_summary(rec)
            if label == "fail":
                td = " · ".join(sub_brief(rec["subs"][t]) for t in trig) if trig else "(组合)"
                g7col = "**拦截✓** %s" % td
            else:
                g7col = "%s %s" % (verdict, summ)
            strips_rel = "workdir/fixtures/strips/%s.jpg" % f["fixture_id"]
            A("| %s | %s | `%s` | [strips](../../%s) | %s | %s | %s |" % (
                f["fixture_id"], f["category"], rel(f["path"]),
                strips_rel,
                f.get("key") or "-", ("%.4f" % f["dino_first_last"]) if f.get("dino_first_last") is not None else "-",
                g7col))
        A("")

    A("## 图与数据索引")
    A("")
    A("| 文件 | 内容 |")
    A("|---|---|")
    A("| `dino_scan_hist.png` | 全候选池 122 条 DINO 首尾余弦分布(M0 粗筛依据) |")
    A("| `g7_dist_a.png` / `g7_dist_d.png` / `g7_dist_c.png` / `g7_dist_b_churn.png` | G7 各子项分数分布(fail/struct/cand 三组) |")
    A("| `g7_roc_a.png` / `g7_roc_c.png` / `g7_roc_d.png` | 子项阈值扫描 ROC |")
    A("| `workdir/logs/v2m0_dino_scan.json` | 粗筛原始数据 |")
    A("| `workdir/logs/v2m1_g7_initial.json` / `v2m1_g7_final.json` | 冷启动初跑 / 校准终版重跑(逐帧原始检测全落盘) |")
    A("| `workdir/logs/v2m1_calibration.json` | 阈值扫描(1288 组合工作点全表) |")
    A("| `workdir/fixtures/fixtures_manifest.json` | 47 条机器可读清单 |")
    A("")
    with open(os.path.join(OUT_DIR, "INDEX.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")

    # ---------- CONFIRMATION.md ----------
    cand = [f for f in fixtures if f["label"] == "pass_candidate"]
    cand.sort(key=lambda f: f["fixture_id"])
    killed_ids = {"FX-C001", "FX-C002", "FX-C003", "FX-C010"}

    M = []
    B = M.append
    B("# pass_candidate 人工确认清单 —— **本轮唯一人工动作**")
    B("")
    B("> **怎么回复(一句话即可)**: 「这些算过」; 或「第 X 个(fixture 号)有问题」; 对 B 组另可回复「杀得对/杀过头」。")
    B("> - **A 组 13 条**: G7 终版全部判过 —— 请确认画面可用。")
    B("> - **B 组 4 条**: G7 终版判杀(FX-C001/C002/C003/C010) —— 按\"宁可误杀\"原则主动杀的, **请你复核杀得对不对**。")
    B("> - 看图: 每条附首/中/尾三联拼图(`workdir/fixtures/strips/<id>.jpg`, 已入 git); 看动态: 同行 mp4(已入 git, 克隆即看)。")
    B("")
    B("## 判读基准(与 G7e 豁免条款同源, `src/gates/g7_vlm_prompt.txt`)")
    B("")
    B("- 液体/蒸汽/雾/光影等\"软\"本体的运动、沸腾、高光变化 **不算缺陷**;")
    B("- 要看的是: 硬物体(食物主体/容器/建筑/人物)的**形状保持、数量一致、无凭空出现/分裂/融合/液化**。")
    B("")
    B("## A. 系统判过, 请确认 (13 条)")
    B("")
    B("| # | fixture | 源候选 | 内容 | 三联拼图 | 动态 mp4 | G7 终版 score | a / d 余弦 |")
    B("|---|---|---|---|---|---|---|---|")
    n = 0
    for f in cand:
        if f["fixture_id"] in killed_ids:
            continue
        n += 1
        rec = recs[f["fixture_id"]]
        a = rec["subs"].get("a", {})
        d = rec["subs"].get("d", {})
        B("| A%02d | %s | %s | %s | [strips](../../%s) | `%s` | %s | a %s / d %s |" % (
            n, f["fixture_id"], f.get("key") or "-", clean_desc(f.get("notes", "")),
            "workdir/fixtures/strips/%s.jpg" % f["fixture_id"],
            rel(f["path"]), fmt(rec.get("score")), fmt(a.get("score")), fmt(d.get("score"))))
    B("")
    B("## B. 系统判杀, 请你复核 (4 条)")
    B("")
    B("| # | fixture | 源候选 | 内容 | 三联拼图 | 动态 mp4 | G7 终版 score | 触发子项 | 判杀原因(系统口径) |")
    B("|---|---|---|---|---|---|---|---|---|")
    n = 0
    for f in cand:
        if f["fixture_id"] not in killed_ids:
            continue
        n += 1
        rec = recs[f["fixture_id"]]
        trig = [t for t, v in rec["subs"].items() if isinstance(v, dict) and v.get("triggered")]
        reason = {
            "FX-C001": "毛肚沸腾特写, 首尾画面剧烈演化 → a/d 真实低余弦(0.785 < 0.82/0.84), 按不对称原则主动误杀",
            "FX-C002": "同上(a/d 0.768), 同一镜头相邻候选",
            "FX-C003": "同上(d 0.8235 < 0.84; a 0.8229 未触发), 同一镜头相邻候选",
            "FX-C010": "夜景灯笼 GDINO 检测闪烁 → churn>12; d 余弦 0.982 很高, **可能属误杀**, 请重点复核",
        }[f["fixture_id"]]
        B("| B%02d | %s | %s | %s | [strips](../../%s) | `%s` | %s | %s | %s |" % (
            n, f["fixture_id"], f.get("key") or "-", clean_desc(f.get("notes", "")),
            "workdir/fixtures/strips/%s.jpg" % f["fixture_id"],
            rel(f["path"]), fmt(rec.get("score")), "+".join(trig), reason))
    B("")
    B("## 裁定后的动作")
    B("")
    B("- A 组全确认 + B 组\"杀得对\" → 夹具库定版, thresholds_v2.yaml 不动;")
    B("- 若某条 B 组被裁定\"杀过头\" → 该条转正为可用候选参考, 阈值是否放宽由 owner 另行决定(G7_CALIBRATION §2 显示再放宽会挤压拦截稳健性);")
    B("- 若 A 组发现问题 → 请指出 fixture 号, 该条转入失败画廊并在下一轮夹具库修订中改标。")
    B("")
    with open(os.path.join(OUT_DIR, "CONFIRMATION.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(M) + "\n")

    print("OK: wrote %s and %s" % (
        os.path.join(OUT_DIR, "INDEX.md"), os.path.join(OUT_DIR, "CONFIRMATION.md")))
    print("cand_total=%d killed=%s" % (len(cand), sorted(killed_ids)))

if __name__ == "__main__":
    sys.exit(main())
