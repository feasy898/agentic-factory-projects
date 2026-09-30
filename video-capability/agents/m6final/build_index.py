# -*- coding: utf-8 -*-
"""M6 失败画廊 INDEX.md 生成器 (数据从 DB/重评 JSON 实时取数, 保证表格数字准确)."""
import json
import sqlite3
import zlib
from pathlib import Path

CRADLE = Path("/root/cradle")
SANDBOX = Path("/root/cradle_m5")
OUT = CRADLE / "reports/gallery_failures/INDEX.md"
REEVAL = CRADLE / "workdir/logs/m5_reeval_g5.json"

TYPE_A = (
    ["S08_a0_0", "S08_a0_1", "S08_a0_2", "S08_a1_0", "S08_a1_1", "S08_a1_2", "S08_a2_1"]
    + ["S09_a0_0", "S09_a0_1", "S09_a0_2", "S09_a1_0", "S09_a1_1", "S09_a1_2", "S09_a2_0"]
    + ["S11_a0_0", "S11_a0_1", "S11_a0_2", "S11_a0_3", "S11_a1_0", "S11_a2_1", "S11_a2_3", "S11_a3_0"]
)
TYPE_B = ["S14_a0_0", "S15_a0_0"]
SHOT_LABEL = {"S08": "S08 门头夜景", "S09": "S09 雨窗氛围", "S11": "S11 无人背影", "S14": "S14 酸梅汤", "S15": "S15 红汤浇锅"}
RETRY_NOTE = {0: "首轮", 1: "重试1", 2: "重试2", 3: "重试3"}


def seed_of(name):
    shot, rest = name.replace(".mp4", "").split("_a", 1)
    a, i = rest.split("_")
    return zlib.crc32(shot.encode()) & 0x7FFFFFFF, int(a), int(i)


def load(dbp):
    db = sqlite3.connect(dbp)
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT path, overall_score, gate_json FROM candidates WHERE verdict='fail'").fetchall()
    db.close()
    return {Path(r["path"]).name.replace(".mp4", ""): (r["overall_score"], json.loads(r["gate_json"])) for r in rows}


def main():
    fm, fs = load(CRADLE / "workdir/cradle.sqlite3"), load(SANDBOX / "workdir/cradle.sqlite3")
    reeval = {Path(r["path"]).name.replace(".mp4", ""): r for r in json.load(open(REEVAL))["rows"]}

    L = []
    L.append("# 失败案例画廊 (gallery_failures) — 索引")
    L.append("")
    L.append("- 日期: 2026-09-08 (M6 收尾, 执行 M6-FINAL)")
    L.append("- 用途: **用户校准阈值的主要材料** (SPECS §7.3)。每案例 = `case.md`(镜头卡+六门禁+归因) + `video.mp4`(实体) + `grid.jpg`(2×5 抽帧网格) + `gate_json.json`(门禁原始 JSON)。")
    L.append("- 数据源: 主仓库 `workdir/candidates/` (M2 LTX 时期被拒候选 34 个) + 沙箱 `/root/cradle_m5/workdir/candidates/` (M5 生产边缘 fail 2 个) —— 全库 36 个拒绝候选, 收录 24 例。")
    L.append("- ⚠️ **口径警示**: 该批 G2/G5 分数为 CLIP ViT-L/14 本地启发式 VLM 替代口径, **未经 API VLM 审核** (D-004 标注义务)。\"G5 分数\"应理解为启发式代理分。")
    L.append("- 媒体说明: 画廊媒体总量 ≈14.4MB (<50MB), `*.mp4`/`*.jpg` **随 git 入库**, 用户可直接在本仓库查看; 原始候选另存于服务器 `~/cradle/workdir/candidates/` 与 `/root/cradle_m5/workdir/candidates/`。")
    L.append("")
    L.append("## 总览")
    L.append("")
    L.append("| 类型 | 定义 | 库存量 | 收录 | 共同特征 |")
    L.append("|---|---|---|---|---|")
    L.append("| **A 校准前 G5 启发式场景偏差** | M2 LTX 调试期, 美食 appeal 锚 (D-026) 对夜景/雨窗/背影类资产系统性打低 | 34 (S08×9 / S09×9 / S11×16) | **22** | G1-G4 与 G2 缺陷分全过, 唯 G5 borderline; 换 seed/重试分数恒定 |")
    L.append("| **B 生产期 G5 边缘** | M5 Wan 量产期 (双锚分锚 D-041 已上线), G5 距阈值 ≤0.009 的边缘 fail | 2 (S14/S15 各 1) | **2 (全收)** | 其余四门禁全过; 同任务 n_best 下一候选即 pass, 任务零损失 |")
    L.append("")
    L.append("> **附注 (如实说明)**: 全部 36 个拒绝候选均为 **G5 单门禁失败** —— 失败候选上 G1/G2/G3/G4 的通过率为 100%, G6 为合成级占位 (D-011, 成片级逐字 9/9 全过)。**本管线未出现 G1(技术)/G3(一致性)/G4(稳定性)/G6(业务) 类失败**, 因此画廊只有 G5 两类。这与 M2 报告 §3 (34/34 纯 G5 卡点) 与 M5 报告 §5 (2/2 G5 边缘) 一致。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 类型A: 校准前 G5 启发式场景偏差 (22 例)")
    L.append("")
    L.append("**现象 (为什么这类失败值得看)**:")
    L.append("")
    L.append("1. **分数恒定**: 同一镜头全部候选的 G5 分数几乎不动 (S08=0.640 全部 9 个; S11=0.640 除 1 个 0.6255; S09=0.621-0.633), defects 全部 ≈0.0 —— 分数由**资产类型**决定, 不是视频质量波动 (M2 报告 §3)。")
    L.append("2. **重试无效**: 换 seed / 加强 negative / 降 guidance 的重试钩子对 G5 完全无效 (M2 用 34/59=58% 的生成量换来 0 收益) —— 该现象直接催生了 stable-borderline 短路机制 (D-042)。")
    L.append("3. **校准后重评 (D-041)**: 换 scene 锚双锚取 max 离线重评 (不重新生成), 34 个中 32 个翻入 pass 带, 2 个 S09 仍 borderline (0.6914/0.698) —— 证明**这是启发式问题, 非画面问题** (m5_calibration.md §1.1 目检佐证)。")
    L.append("")
    L.append("| # | 案例 | 镜头 | 轮次 | 候选 seed | M2 G5 (旧锚) | 校准后 G5 (D-041) | 重评判定 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for i, name in enumerate(TYPE_A, 1):
        base_seed, a, idx = seed_of(name)
        shot = name.split("_a")[0]
        rr = reeval[name]
        L.append(
            f"| A{i:02d} | [{name}](typeA_g5_scene_bias/{name}/case.md) | {SHOT_LABEL[shot]} | {RETRY_NOTE[a]} | {base_seed + a*1000 + idx} | "
            f"{rr['m2_g5_score']} | **{rr['new_g5']}** ({rr['appeal_basis']}) | {rr['new_verdict']} |"
        )
    L.append("")
    L.append("精选逻辑: S08 7/9 (3 个重试轮全覆盖, 展示分数恒定), S09 7/9 (分数带最宽 0.621-0.633 + 含 2 个**校准后仍 borderline** 的 a0_0/a1_0), S11 8/16 (n_best=4×4 轮全覆盖, 含分数下界 0.6255 与短路机制动因 a3_0)。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 类型B: 生产期 G5 边缘 (2 例, 全收)")
    L.append("")
    L.append("| # | 案例 | 镜头 | 车道 | G5 | 距阈值 | overall_defect | 恢复路径 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for i, name in enumerate(TYPE_B, 1):
        base_seed, a, idx = seed_of(name)
        shot = name.split("_a")[0]
        _, gj = fs[name]
        g5 = gj["G5"]
        gap = 0.70 - g5["score"]
        rec = "同任务第 2 候选 id=50 pass (0.9196) 被选中" if shot == "S14" else "同任务第 3 候选 id=54 pass (0.9273) 被选中"
        L.append(
            f"| B{i:02d} | [{name}](typeB_g5_edge/{name}/case.md) | {SHOT_LABEL[shot]} | Wan 生产 480×832×81帧 | {g5['score']} | -{gap:.4f} | {g5['detail']['overall_defect']:.4f} | {rec} |"
        )
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 给阈值校准者的要点 (据本画廊 + M2/M5 数据)")
    L.append("")
    L.append("1. **G5 0.70 在启发式口径下曾是\"资产类型门\"** (M2): 若继续用 CLIP 启发式, 场景类资产需单独基线 (D-041 双锚即此解); 根治方案是接入真实 VLM 复审 (API 预算 1500 次 1 次未用)。")
    L.append("2. **边缘带真实存在** (类型B): 0.70 阈值下必有 0.69±0.01 的边缘候选; M5 靠 n_best=3 冗余吸收 (任务良率仍 100%)。若把 G5 降到 0.69, 类型B 全过, 但类型A 校准前形态 (0.62-0.64) 依然过不了 —— **调阈值解决不了锚偏差**, 两者的 remediation 不同。")
    L.append("3. **分数恒定 ⇒ 重试无用** (类型A): 同镜头候选 G5 极差 <0.02 时应短路 (已实现 `route.is_stable_borderline`, D-042), 省下的生成量是纯利润 (M2 时期 58% 生成量 0 收益)。")
    L.append("4. **G1-G4/G6 阈值在本任务面内未产生过失败**, 校准他们的紧迫性低; M2 建议的 G3→0.80 / G4→0.95 上调已被 M5 试点否决 (Wan 长片分数更低, m5_calibration §5), 维持冷启动值。")
    L.append("")
    (OUT).write_text("\n".join(L), encoding="utf-8")
    print("INDEX.md written:", OUT)


if __name__ == "__main__":
    main()
