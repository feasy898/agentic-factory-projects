#!/usr/bin/env python3
"""V2-M5: reports/gallery_failures_v2 构建 (幂等)。

v2 期漏网 = 0 (校准 fail 15/15 拦截; 生产 25/25 全过 + 21 帧目检 0 形变), 故本目录
收录的是**误杀/审计拒绝侧**的透明档案:
  ① overlay 审计 FAIL 4 例 (3 个物理失败文件 + 1 个重生替换历史);
  ② G7 校准期判杀的 4 条 pass_candidate (FX-C001/C002/C003/C010)。
所有媒体已在 git 库内 (D-053 夹具 / M3 overlay 入库), 案例目录引用相对路径, 不复制文件。

输入:
  assets/overlays/manifest.json
  workdir/logs/v2m1_g7_final.json
输出: reports/gallery_failures_v2/ (INDEX.md + 8 个案例目录 + 3 张 overlay 抽帧网格)
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "reports", "gallery_failures_v2")
OVERLAY_MANIFEST = os.path.join(ROOT, "assets", "overlays", "manifest.json")
G7FINAL = os.path.join(ROOT, "workdir", "logs", "v2m1_g7_final.json")
KILLED = ["FX-C001", "FX-C002", "FX-C003", "FX-C010"]

OVERLAY_CASES = [
    {
        "dir": "ov_steam_dense", "file": "ov_steam_dense.mp4", "kind": "蒸汽(浓)",
        "attribution": "浓雾团中帧爆发, masked 背景首尾 DINO 余弦 0.5176 ≪ 0.84 —— 浓蒸汽的光渗透会**真实抬亮**底片暗区, screen 混合将污染产品图底。FAIL 对产线是正确保护, 非误杀。",
        "note": "prompt 已含 'pure black background/fixed camera'; 失败源于素材类型本体(浓雾)与'不污染底片'要求的固有冲突, 未再重生(D-069, 不对称原则)。",
    },
    {
        "dir": "ov_fog_low", "file": "ov_fog_low.mp4", "kind": "雾(贴地浓雾)",
        "attribution": "borderline 0.8265 < 0.84 —— 贴地浓雾整幅渗透, 静态暗底被雾光持续改写; c' 光度差仅 0.0043(近黑低纹理 RAFT 伪光流 p95=150px 已按光度/SSIM 复核豁免), 但 d' 语义漂移超阈。",
        "note": "c'/d' 分裂正是 D-066 口径的设计行为: 低纹理伪光流不冤枉它, 背景语义漂移照样拦。",
    },
    {
        "dir": "ov_bokeh_dust", "file": "ov_bokeh_dust.mp4", "kind": "光斑(暗金粒子)",
        "attribution": "两轮审计 0.5499 → 亮化重生后 0.71 仍 < 0.84 —— 暗色粒子低于亮度阈值使动态区不可分, 且粒子本性持续运动(masked 背景被粒子占据); ssim 0.630 同步低。",
        "note": "亮化重生(+1 Wan, D-069)改善未达标即停, 不再投入; 与浓雾类同属素材类型×产线要求固有张力。",
    },
    {
        "dir": "ov_mist_cool_v1", "file": None, "kind": "雾(首版, 已重生替换)",
        "attribution": "首版雾团中帧爆发, masked_bg_cos 0.7272 < 0.84 (FAIL) → prompt 改'限域淡雾'重生后 0.9427 **PASS**(现网 ov_mist_cool.mp4)。",
        "note": "本例是 4 例中唯一的**重生成功对照**: 同类素材 prompt 收敛可行; 首版原件已被重生版覆盖, 无独立视频留档, 数字出处 D-069 与 assets/overlays/manifest.json 现值(0.9427)。",
    },
]

KILL_REASON = {
    "FX-C001": "毛肚沸腾特写: 首尾画面剧烈演化属**真实低余弦**(a 0.7852/d 0.7852 < 0.82/0.84), 非检测器噪声 —— 按\"宁可误杀\"主动判杀; 是否过严 → CONFIRMATION.md B 组请用户复核。",
    "FX-C002": "同 FX-C001 的相邻候选(a/d 0.7679), 同口径主动判杀。",
    "FX-C003": "同上(a 0.8229 未触发, d 0.8235 < 0.84 触发), 主动判杀。",
    "FX-C010": "夜景灯笼 GDINO 检测闪烁 → churn>12 触发 G7b; d 余弦 0.9818 很高, **误杀可能性最大**的一例 → 请用户重点复核。",
}

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)

def make_grid(mp4, out_png, times=(0.2, 2.0, 3.8)):
    """首/中/尾三帧横向拼图 (JPEG q85)。"""
    import tempfile
    frames = []
    with tempfile.TemporaryDirectory() as td:
        for i, t in enumerate(times):
            p = os.path.join(td, "f%d.png" % i)
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t),
                                "-i", mp4, "-frames:v", "1", p], capture_output=True)
            if r.returncode != 0 or not os.path.exists(p):
                return False
            frames.append(p)
        from PIL import Image, ImageDraw
        ims = [Image.open(p) for p in frames]
        h = 640
        ims = [im.resize((int(im.width * h / im.height), h)) for im in ims]
        W = sum(im.width for im in ims) + 8 * (len(ims) + 1)
        canvas = Image.new("RGB", (W, h + 34), (18, 18, 18))
        x = 8
        dr = ImageDraw.Draw(canvas)
        for i, im in enumerate(ims):
            canvas.paste(im, (x, 26))
            dr.text((x, 6), "f%02d  t=%.1fs" % (i + 1, times[i]), fill=(240, 240, 240))
            x += im.width + 8
        canvas.save(out_png, quality=85)
    return True

def overlay_case_dir(case, ent):
    d = os.path.join(OUT, "overlay_audit_fail", case["dir"])
    audit = ent["g7_audit"]
    c, dd = audit.get("c", {}), audit.get("d", {})
    write(os.path.join(d, "gate_json.json"),
          json.dumps(ent, ensure_ascii=False, indent=1))
    L = []
    A = L.append
    A("# 案例 OV: %s — overlay 审计 FAIL (%s)" % (case["file"] or case["dir"], case["kind"]))
    A("")
    A("- **审计口径**: D-066 — c'(硬) 静态暗底区稳定(RAFT P95≤30px, 低纹理以光度差≤0.08 ∧ SSIM≥0.60 复核) ∧ d'(硬) masked 背景首尾 DINO 余弦≥0.84; a/b 按 D-064 豁免仅记录。")
    A("- **审计结论**: **FAIL** — d' masked_bg_cos = **%s** (< 0.84)" % dd.get("masked_bg_cos"))
    A("- **c' 明细**: p95=%spx (阈 30), basis=%s, photo_diff=%s, ssim=%s → %s" % (
        c.get("p95_px"), c.get("basis"), c.get("photo_diff_max"), c.get("ssim_min"),
        "PASS" if c.get("passed") else "FAIL"))
    A("- **d' 明细**: masked_bg_cos=%s (阈 0.84) → %s" % (
        dd.get("masked_bg_cos"), "PASS" if dd.get("passed") else "FAIL"))
    if case["file"]:
        A("- **视频**: [../../../assets/overlays/%s](../../../assets/overlays/%s) (4s@16fps 480×832, 已入 git)" % (case["file"], case["file"]))
        A("- **抽帧网格**: grid.jpg (首/中/尾三帧)")
        A("- **静态区 mask**: [../../../assets/overlays/masks/%s.static.png](../../../assets/overlays/masks/%s.static.png)" % (case["file"], case["file"]))
    A("- **归因**: %s" % case["attribution"])
    A("- **备注**: %s" % case["note"])
    A("- **对产线的影响**: 无 —— `pick_overlay` 只挑 passed=true 素材; 本轮 9 条成片使用的 overlay 全部来自 3 条过审素材(steam_thin/mist_cool/light_warm)。")
    A("- **原始审计 JSON**: gate_json.json (assets/overlays/manifest.json 对应条目副本)")
    A("")
    write(os.path.join(d, "case.md"), "\n".join(L) + "\n")
    if case["file"]:
        ok = make_grid(os.path.join(ROOT, "assets", "overlays", case["file"]),
                       os.path.join(d, "grid.jpg"))
        return ok
    return True

def kill_case_dir(rec):
    fid = rec["fixture_id"]
    d = os.path.join(OUT, "g7_calibration_killed", fid)
    write(os.path.join(d, "gate_json.json"), json.dumps(rec, ensure_ascii=False, indent=1))
    trig = [t for t, v in rec["subs"].items() if isinstance(v, dict) and v.get("triggered")]
    a = rec["subs"].get("a", {})
    dd = rec["subs"].get("d", {})
    b = rec["subs"].get("b", {})
    L = []
    A = L.append
    A("# 案例 G7-KILL: %s (源候选 %s) — G7 校准期 pass_candidate 判杀" % (fid, rec.get("source_key")))
    A("")
    A("- **组别**: pass_candidate(v1 真实生产候选, v1 六门禁 G1-G6 全绿, M0 目检预审无明显形变)")
    A("- **G7 终版判定**: **判杀** — score=%s, 触发子项: %s" % (round(rec.get("score", 0), 4), "+".join(trig)))
    A("- **子项明细**: a=%s(阈 0.82%s) · d=%s(阈 0.84%s) · b churn=%s(阈 12) · c 未触发 · e skipped(无 API, D-004)" % (
        round(a.get("score", 0), 4), "✗" if a.get("triggered") else "✓",
        round(dd.get("score", 0), 4), "✗" if dd.get("triggered") else "✓",
        b.get("churn", "-")))
    A("- **视频**: [../../../workdir/fixtures/pass_candidate/%s.mp4](../../../workdir/fixtures/pass_candidate/%s.mp4)(已入 git)" % (fid, fid))
    A("- **首/中/尾三联帧**: [../../../workdir/fixtures/strips/%s.jpg](../../../workdir/fixtures/strips/%s.jpg)" % (fid, fid))
    A("- **归因**: %s" % KILL_REASON[fid])
    A("- **定位**: 该例属于夹具库 pass_candidate 组(本组语义=待人工确认), 校准把它算进误杀率 4/17=23.5%(≤25% 带内); 人工复核入口 → [reports/fixtures/CONFIRMATION.md](../../fixtures/CONFIRMATION.md) B 组。")
    A("- **原始 G7 记录**: gate_json.json (workdir/logs/v2m1_g7_final.json 该条完整副本)")
    A("")
    write(os.path.join(d, "case.md"), "\n".join(L) + "\n")

def main():
    os.makedirs(OUT, exist_ok=True)
    ovman = json.load(open(OVERLAY_MANIFEST, encoding="utf-8"))
    byfile = {e["file"]: e for e in ovman}
    g7 = json.load(open(G7FINAL, encoding="utf-8"))
    recs = {r["fixture_id"]: r for r in g7["records"]}

    ok_all = True
    for case in OVERLAY_CASES:
        ent = byfile[case["file"]] if case["file"] else None
        if ent is None:
            # mist_cool v1: 用现网(重生版)条目作对照数据源, case.md 内注明
            ent = byfile["ov_mist_cool.mp4"]
        if not overlay_case_dir(case, ent):
            ok_all = False
            print("WARN: grid failed for", case["dir"])
    for fid in KILLED:
        kill_case_dir(recs[fid])

    # ---------------- INDEX.md ----------------
    L = []
    A = L.append
    A("# gallery_failures_v2 — v2 期失败/误杀案例索引 (V2-M5)")
    A("")
    A("> 构建脚本 `tools/m5v2_build_gallery_v2.py`(幂等); 媒体全部已在 git 库内(夹具 D-053 / overlay M3 入库), 案例目录引用相对路径不复制文件。")
    A("")
    A("## 0. 本轮漏网 = 0 (如实声明)")
    A("")
    A("v2 全程**未发生任何形变漏网**: 校准集 fail 夹具拦截 **15/15 = 100%**; 生产 25/25 候选 G7 全过(0 触发, score ∈ [0.9758, 0.9983]) + 21 帧目检 0 形变 + 主控 VLM 抽帧终检通过(v2_t1_seeding_v2)。")
    A("")
    A("因此本目录不是\"漏网画廊\", 而是**不对称原则(宁误杀, 不漏网)的代价侧档案** —— 系统拒收了什么、为什么拒、拒得对不对。素材来源说明: 生产首轮 100% 良率 → 产线零被杀样本, 本目录案例全部来自 **overlay 素材审计** 与 **G7 校准期夹具运行**, 而非生产期。")
    A("")
    A("## 1. overlay 审计 FAIL (4 例; 审计 FAIL 判定共 5 次/物理失败文件 3 个)")
    A("")
    A("| 案例 | 素材类型 | 审计分 d' (阈 0.84) | 一句话归因 |")
    A("|---|---|---|---|")
    rows = [
        ("ov_steam_dense", "蒸汽(浓)", "0.5176", "浓雾光渗透真实抬亮暗底, screen 混合将污染产品图底 —— 正确保护"),
        ("ov_fog_low", "雾(贴地)", "0.8265", "贴地浓雾整幅渗透, c' 低纹理伪光流已豁免但 d' 背景语义漂移超阈"),
        ("ov_bokeh_dust", "光斑(暗粒子)", "0.5499 → 0.71(亮化重生后)", "暗粒子低于亮度阈值动态区不可分 + 粒子本性动; 重生仍不达标即停"),
        ("ov_mist_cool_v1", "雾(首版)", "0.7272 → 重生后 **0.9427 PASS**", "唯一重生成功对照: prompt 限域收敛可行; 原件已被替换无独立视频"),
    ]
    for r in rows:
        A("| [%s](overlay_audit_fail/%s/case.md) | %s | %s | %s |" % (r[0], r[0], r[1], r[2], r[3]))
    A("")
    A("物理解释(D-066/D-069): 蒸汽/浓雾类的\"雾光渗透\"不是检测器误报 —— screen 混合模式下素材亮区会叠加到产品底图上, 底片暗区被真实抬亮属**物理污染**; 暗色粒子类则是审计口径的已知可分性局限(低于亮度阈值的本体无法与背景分离), 两者都不以放宽阈值解决(不对称原则)。")
    A("")
    A("## 2. G7 校准期判杀的 pass_candidate (4 例, 误杀率 4/17=23.5% 带内)")
    A("")
    A("| 案例 | 源候选 | G7 score | 触发子项 | 一句话归因 |")
    A("|---|---|---|---|---|")
    for fid in KILLED:
        rec = recs[fid]
        trig = [t for t, v in rec["subs"].items() if isinstance(v, dict) and v.get("triggered")]
        brief = {
            "FX-C001": "毛肚沸腾特写首尾剧烈演化, a/d 真实低余弦 —— 主动\"宁误杀\"",
            "FX-C002": "同上相邻候选(a/d 0.768)",
            "FX-C003": "同上(d 0.8235 触发, a 未触发)",
            "FX-C010": "夜景 GDINO 检测闪烁 churn>12; d=0.982 很高, 误杀可能性最大",
        }[fid]
        A("| [%s](g7_calibration_killed/%s/case.md) | %s | %.4f | %s | %s |" % (
            fid, fid, rec.get("source_key"), rec.get("score"), "+".join(trig), brief))
    A("")
    A("4 条均为 v1 六门禁全绿的真实生产候选; 前 3 条(毛肚)属画面真实剧烈演化、系统按不对称原则主动杀, FX-C010 属检测器噪声触发。**是否杀过头由用户裁定** → [CONFIRMATION.md](../fixtures/CONFIRMATION.md) B 组(本轮唯一人工动作)。")
    A("")
    A("## 3. 与 v1 画廊的关系")
    A("")
    A("- v1 画廊 [../gallery_failures/](../gallery_failures/)(24 例) = **G5 启发式偏差型**(画面正常被判拒, CLIP 口径局限的实证);")
    A("- 本目录 = **G7 物体恒存口径的拒绝侧**(overlay 素材审计 + 校准期主动误杀), 两目录互补, 共同构成门禁完整行为档案;")
    A("- v1 的 15 条真形变已收编为夹具库 fail 组(`workdir/fixtures/fail/`), 不在本目录重复列出。")
    A("")
    write(os.path.join(OUT, "INDEX.md"), "\n".join(L) + "\n")
    print("OK: gallery_failures_v2 built (grids_ok=%s)" % ok_all)

if __name__ == "__main__":
    sys.exit(main())
