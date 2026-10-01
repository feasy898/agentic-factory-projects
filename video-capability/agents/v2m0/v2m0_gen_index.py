#!/usr/bin/env python
"""V2-M0: generate reports/fixtures/INDEX.md + DINO scan histogram from the fixture manifest."""
import json, os, sqlite3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FIX_ROOT = "/root/cradle/workdir/fixtures"
MAN = json.load(open(os.path.join(FIX_ROOT, "fixtures_manifest.json")))
SCAN = {r["key"]: r for r in json.load(open("/root/cradle/workdir/logs/v2m0_dino_scan.json"))}
OUT_DIR = "/root/cradle/reports/fixtures"
os.makedirs(OUT_DIR, exist_ok=True)

fx = MAN["fixtures"]
st = MAN["stats"]

# histogram of the coarse screen
vals = [r["dino_first_last"] for r in SCAN.values() if r.get("status") == "ok"]
fig, ax = plt.subplots(figsize=(8, 4.2))
ax.hist(vals, bins=30, color="#c44e52", edgecolor="white")
ax.axvline(0.80, color="black", ls="--", lw=1)
ax.axvline(0.88, color="black", ls=":", lw=1)
ax.text(0.795, ax.get_ylim()[1] * 0.95, "目检嫌疑线 0.80", ha="right", fontsize=9)
ax.text(0.885, ax.get_ylim()[1] * 0.95, "borderline线 0.88", fontsize=9)
ax.set_xlabel("DINOv2 ViT-L/14 first-vs-last cosine (fp16)")
ax.set_ylabel("候选数")
ax.set_title("v1 候选池 DINO 首尾相似度分布 (n=%d, median=%.3f)" % (len(vals), sorted(vals)[len(vals) // 2]))
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "dino_scan_hist.png"), dpi=130)


def row(f):
    src = SCAN.get(f.get("key") or "", {})
    return "| %s | %s | %s | %s | %s | %s |" % (
        f["fixture_id"], f["category"] or "-", f.get("key", "-"),
        ("%s/%s" % (src.get("verdict", "-"), src.get("score", "-"))) if src else "-",
        ("%.4f" % f["dino_first_last"]) if f.get("dino_first_last") is not None else "-",
        f["notes"])


lines = []
lines.append("# 回归夹具库索引 (V2-M0 雏形, M5 终版)\n")
lines.append("> SPECS_V2 §2。物理文件: `workdir/fixtures/{fail,pass_structural,pass_candidate}/`,每夹具三联帧证据在 `workdir/fixtures/strips/`。")
lines.append("数据库: 主仓 `workdir/cradle.sqlite3` 表 `fixtures(fixture_id, path, label, category, human_source, notes)`。")
lines.append("媒体合计 %.1f MB < 50MB 门槛(D-049 先例) → 全量随 git 入库,克隆即看。\n" % (sum(os.path.getsize(f["path"]) for f in fx) / 1e6))
lines.append("## 统计自检(硬性指标)\n")
lines.append("- fail: **%d** (要求 ≥15) — fluid_melt %d / split_merge %d / count_drift %d / object_flow %d(四类全覆盖)" % (
    st["fail"], st["fail_categories"]["fluid_melt"], st["fail_categories"]["split_merge"],
    st["fail_categories"]["count_drift"], st["fail_categories"]["object_flow"]))
lines.append("- pass_structural: **%d** (要求 ≥10) — v1 真产物 4 + 确定性再生成 11" % st["pass_structural"])
lines.append("- pass_candidate: **%d** (要求 ≥10) — 全部标注**待人工确认**" % st["pass_candidate"])
lines.append("- 总计 **%d** 条(M0 验收 ≥35)\n" % st["total"])
lines.append("## 构建方法\n")
lines.append("1. **粗筛**: DINOv2 ViT-L/14 fp16 对全候选池 122 条(主仓 62 + 沙箱 60)抽首/尾帧算余弦相似度,分布见 `dino_scan_hist.png`(median 0.972;<0.80 共 17 条列嫌疑,<0.88 再加 9 条 borderline);")
lines.append("2. **精筛**: 对嫌疑候选抽首/中/尾三帧,由 V2-M0 子代理逐条目检(G7e 对读协议:形状保持/数量一致/无液化/无分裂),按四类归类;把握不足者标 borderline 备注后按不对称原则(宁可误杀)收录;")
lines.append("3. v1 画廊 24 例属 G5 启发式偏差型(画面正常),不整体混入;其中目检确认真形变的 1 例(SB_S15_52 红油溢锅)收录为 FX-F005;")
lines.append("4. pass_structural = v1 S12 产物 + 3 个 fallback 渲染(fallback 车道=ken_burns)+ 对 11 张 v1 资产以 src/gen/kenburns.py 确定性再生成(zoompan 无 RNG);")
lines.append("5. pass_candidate = G1-G6 全绿候选中按 G7e 对读预审无明显形变者,**待人工确认**(最终报告请用户逐条裁定,这是唯一人工动作)。\n")
lines.append("## fail 夹具 (%d)\n" % st["fail"])
lines.append("| fixture_id | category | 源候选 | v1判定/分 | dino首尾 | 现象 |")
lines.append("|---|---|---|---|---|---|")
for f in fx:
    if f["label"] == "fail":
        lines.append(row(f))
lines.append("")
lines.append("## pass_structural (%d)\n" % st["pass_structural"])
lines.append("| fixture_id | category | 源候选 | v1判定/分 | dino首尾 | 说明 |")
lines.append("|---|---|---|---|---|---|")
for f in fx:
    if f["label"] == "pass_structural":
        lines.append(row(f))
lines.append("")
lines.append("## pass_candidate (%d) — ⚠ 待人工确认\n" % st["pass_candidate"])
lines.append("| fixture_id | category | 源候选 | v1判定/分 | dino首尾 | 预审说明 |")
lines.append("|---|---|---|---|---|---|")
for f in fx:
    if f["label"] == "pass_candidate":
        lines.append(row(f))
lines.append("")
lines.append("## 用户确认清单(唯一人工动作)\n")
lines.append("请对以下 %d 条逐条回复\"确认/否决\"(一句话即可):%s" % (st["pass_candidate"],
    ", ".join(f["fixture_id"] for f in fx if f["label"] == "pass_candidate")))
with open(os.path.join(OUT_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("INDEX_DONE", os.path.join(OUT_DIR, "INDEX.md"))
