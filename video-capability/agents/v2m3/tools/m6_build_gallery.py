# -*- coding: utf-8 -*-
"""M6 失败案例画廊构建脚本 (PROJECT CRADLE).

从主仓库 (M2 LTX 34 个被拒候选) 与沙箱 /root/cradle_m5 (M5 生产 2 个边缘 fail)
精选 24 例, 每例生成: video.mp4 + gate_json.json + grid.jpg (5x2 抽帧) + case.md,
并汇总 reports/gallery_failures/INDEX.md。
"""
import json
import shutil
import sqlite3
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CRADLE = Path("/root/cradle")
SANDBOX = Path("/root/cradle_m5")
MAIN_DB = CRADLE / "workdir/cradle.sqlite3"
SB_DB = SANDBOX / "workdir/cradle.sqlite3"
OUT = CRADLE / "reports/gallery_failures"
REEVAL = CRADLE / "workdir/logs/m5_reeval_g5.json"
CARDS = CRADLE / "templates/shotcards"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ---- 精选名单 (类型A: 22; 类型B: 2) ----
TYPE_A = (
    ["S08_a0_0", "S08_a0_1", "S08_a0_2", "S08_a1_0", "S08_a1_1", "S08_a1_2", "S08_a2_1"]
    + ["S09_a0_0", "S09_a0_1", "S09_a0_2", "S09_a1_0", "S09_a1_1", "S09_a1_2", "S09_a2_0"]
    + ["S11_a0_0", "S11_a0_1", "S11_a0_2", "S11_a0_3", "S11_a1_0", "S11_a2_1", "S11_a2_3", "S11_a3_0"]
)
TYPE_B = ["S14_a0_0", "S15_a0_0"]

# m5_calibration.md §1.1 目检覆盖到的候选 (引用其结论)
INSPECT_NOTES = {
    "S08_a0_0": "红灯笼门头+湿路反光, 构图完整, 无变形/乱码/闪烁, 氛围到位 → 画质良好 (m5_calibration.md §1.1)",
    "S08_a1_1": "红灯笼门头+湿路反光, 构图完整, 无变形/乱码/闪烁, 氛围到位 → 画质良好 (m5_calibration.md §1.1)",
    "S09_a0_0": "雨珠+暖光散景, 层次分明, 无缺陷 → 画质良好 (m5_calibration.md §1.1)",
    "S09_a1_2": "雨珠+暖光散景, 层次分明, 无缺陷 → 画质良好 (m5_calibration.md §1.1)",
    "S11_a0_0": "单人背影走廊, 无正脸(合规), 透视自然 → 画质良好 (m5_calibration.md §1.1)",
    "S11_a2_3": "单人背影走廊, 无正脸(合规), 透视自然 → 画质良好 (m5_calibration.md §1.1)",
}

RETRY_NOTE = {
    0: "首轮生成 (attempt 0, 原始 negative/guidance)",
    1: "重试轮 1 (attempt 1, 加强 negative + guidance-0.5 的重试钩子)",
    2: "重试轮 2 (attempt 2, 同上钩子)",
    3: "重试轮 3 (attempt 3, S11 中风险 retry_max=3)",
}

SHOT_LABEL = {
    "S08": "S08 门头夜景",
    "S09": "S09 雨窗氛围",
    "S11": "S11 无人背影(中风险)",
    "S14": "S14 冰镇酸梅汤(offer 变体)",
    "S15": "S15 红汤浇锅底(evidence 变体)",
}


def stable_seed(shot_id: str) -> int:
    return zlib.crc32(shot_id.encode("utf-8")) & 0x7FFFFFFF


def parse_name(name: str):
    stem = name.replace(".mp4", "")
    shot, rest = stem.split("_a", 1)
    attempt, idx = rest.split("_")
    return shot, int(attempt), int(idx)


def load_fails(db_path: Path):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, shot_id, path, overall_score, verdict, selected, gate_json FROM candidates WHERE verdict='fail'"
    ).fetchall()
    out = {}
    for r in rows:
        out[Path(r["path"]).name.replace(".mp4", "")] = {
            "id": r["id"],
            "db_path": r["path"],
            "overall": r["overall_score"],
            "gate_json": json.loads(r["gate_json"]),
        }
    db.close()
    return out


def load_task_meta(db_path: Path, shot: str):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    r = db.execute(
        "SELECT seed, steps, vram_peak_mb, attempts, status FROM tasks WHERE shot_id=?", (shot,)
    ).fetchone()
    db.close()
    return dict(r) if r else {}


def make_grid(frames_dir: Path, out_jpg: Path, cols: int = 5):
    frames = sorted(frames_dir.glob("frame_*.png"))[: cols * 2]
    assert len(frames) == 10, f"expect 10 frames, got {len(frames)} in {frames_dir}"
    ims = [Image.open(f).convert("RGB") for f in frames]
    w, h = ims[0].size
    gutter = 6
    label_h = 34
    W = cols * w + (cols + 1) * gutter
    H = 2 * (h + label_h) + 3 * gutter
    canvas = Image.new("RGB", (W, H), (16, 16, 16))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(FONT, 24)
    for i, im in enumerate(ims):
        col, row = i % cols, i // cols
        x = gutter + col * (w + gutter)
        y = gutter + row * (h + label_h + gutter)
        canvas.paste(im, (x, y + label_h))
        draw.rectangle([x, y, x + 92, y + label_h - 4], fill=(200, 30, 30))
        draw.text((x + 8, y + 4), f"f{i+1:02d}", fill=(255, 255, 255), font=font)
    canvas.save(out_jpg, "JPEG", quality=85, optimize=True)
    return canvas.size


def gates_table(gj: dict):
    thr = {
        "G1": "时长±0.5s/分辨率/fps/无全黑全白帧",
        "G2": "4 项缺陷各<0.3 (vlm_defect_max=0.2)",
        "G3": "每帧 vs 首帧参考 ≥0.65",
        "G4": "相邻帧 CLIP ≥0.85",
        "G5": "overall≥0.70 且 defect≤0.2",
        "G6": "合成级逐字校验 (候选级占位, D-011)",
    }
    lines = ["| 门禁 | 判据(冷启动) | score | passed |", "|---|---|---|---|"]
    for k in ["G1", "G2", "G3", "G4", "G5", "G6"]:
        g = gj.get(k, {})
        mark = "✓" if g.get("passed") else "**✗ ← 失败门禁**"
        lines.append(f"| {k} | {thr[k]} | {g.get('score')} | {mark} |")
    return "\n".join(lines)


def write_case(case_dir: Path, name: str, ctype: str, rec: dict, reeval_row, card: dict, task_meta, origin: str):
    shot, attempt, idx = parse_name(name)
    gj = rec["gate_json"]
    g5 = gj["G5"]["detail"]
    seed = stable_seed(shot) + attempt * 1000 + idx
    asset = card.get("first_frame_asset", "?")
    cam = card.get("camera", {})
    case_no = CASE_NO[name]
    md = []
    md.append(f"# 案例 {case_no}: {name} — {ctype}")
    md.append("")
    md.append(f"- **失败类型**: {ctype}")
    md.append(f"- **镜头**: {SHOT_LABEL.get(shot, shot)} ({shot}, attempt {attempt}, 候选 i={idx})")
    md.append(f"- **画面**: 见同目录 `grid.jpg` (2×5 抽帧网格, f01-f10); 动态见 `video.mp4`")
    md.append(f"- **门禁明细**: 同目录 `gate_json.json` (六门禁原始 JSON 副本)")
    md.append("")
    md.append("## 1. 镜头卡与候选信息")
    md.append("")
    md.append("| 项 | 值 |")
    md.append("|---|---|")
    md.append(f"| 镜头卡 | `{shot}` — {card.get('subject', {}).get('desc_zh', '?')} |")
    md.append(f"| 首帧资产 | `{asset}` (SDXL 832×1216, D-029) |")
    md.append(f"| 车道 / 运镜 | {card.get('lane')} / scale={cam.get('scale')}, angle={cam.get('angle')}, motion={cam.get('motion')}, depth={cam.get('depth')} |")
    md.append(f"| n_best / retry_max | {card.get('n_best')} / {card.get('retry_max')} |")
    md.append(f"| 生成轮次 | attempt {attempt} — {RETRY_NOTE.get(attempt, '?')} |")
    md.append(f"| 候选 seed | {seed} (D-031 公式: stable_seed({shot})+{attempt}*1000+{idx}) |")
    if origin.startswith("M2"):
        md.append(f"| 生成规格 | LTX-Video 2B 调试车道, 384×512, 25帧@16fps=1.5625s, steps 12 (D-024/D-025) |")
    else:
        md.append(f"| 生成规格 | Wan2.1-Fun-1.3B-InP 生产车道, 480×832, 81帧@16fps=5.0625s, steps {task_meta.get('steps')}, 显存峰值 {task_meta.get('vram_peak_mb')}MB (D-019/D-028/D-039/D-044) |")
    md.append(f"| 原始位置 | `{rec['db_path']}` ({origin}) |")
    md.append(f"| DB 候选 id | {rec['id']} (库: {'主仓库 M2' if origin.startswith('M2') else '沙箱 cradle_m5 M5'}) |")
    md.append("")
    md.append("## 2. 六门禁分数")
    md.append("")
    md.append(gates_table(gj))
    md.append("")
    md.append(
        f"G5 详情: overall_score=**{g5.get('overall_score')}**, overall_defect={g5.get('overall_defect')}, "
        f"aesthetic={g5.get('aesthetic')}, verdict=\"{g5.get('verdict')}\", "
        f"main_issue=\"{g5.get('main_issue')}\" (启发式口径, D-009/D-026)"
    )
    md.append("")
    if ctype.startswith("类型A"):
        defects = (gj.get("G2", {}).get("detail", {}) or {}).get("defects", {})
        max_defect = max(defects.values()) if defects else 0.0
        if reeval_row["new_verdict"] == "pass":
            tail = "校准后按 scene 锚重评即入 pass 带 —— **属启发式问题, 非画面问题**。"
        else:
            tail = (
                f"校准后重评 {reeval_row['new_g5']} **仍 borderline** (S09 最弱带, 全库 59 个 M2 候选中仅 2 例) "
                "—— 即便换锚, 阈值边缘带依然真实存在。"
            )
        md.append("## 3. 校准后重评 (D-041 双锚分锚, 离线重评未重新生成)")
        md.append("")
        md.append("| 项 | 值 |")
        md.append("|---|---|")
        md.append(f"| M2 旧 G5 (单美食锚, D-026) | {reeval_row['m2_g5_score']} |")
        md.append(f"| 校准后 G5 (双锚 max, scene 锚生效) | **{reeval_row['new_g5']}** (appeal_basis={reeval_row['appeal_basis']}) |")
        md.append(f"| 重评判定 | **{reeval_row['new_verdict']}** |")
        md.append("")
        md.append(
            f"> **要点**: 该候选 G1-G4 全过、G2 各缺陷分最大仅 {max_defect:.3f} (<0.3 判据), 画面本身无变形/乱码/闪烁; 被拒纯因 CLIP 启发式的"
            "美食 appeal 锚对夜景/雨窗/背影类资产系统性打低 (分数恒定 0.62-0.64, 换 seed/重试钩子完全无效)。"
            f"{tail}"
        )
        if name in INSPECT_NOTES:
            md.append("")
            md.append(f"**人工目检引用**: {INSPECT_NOTES[name]}")
    else:
        md.append("## 3. 生产期背景 (D-041 双锚已生效后的边缘带)")
        md.append("")
        md.append(
            "> **要点**: 该候选产生于 M5 Wan 量产 (双锚分锚已上线), 其余四门禁全过, G5 仅差阈值 "
            f"{'0.0068' if name.startswith('S14') else '0.0087'} (0.70 - {g5.get('overall_score')}), "
            "属启发式 borderline 带; 同任务 n_best 的下一候选即 pass 并被选中, **任务级零损失** "
            "(重试机制按设计恢复, m5_yield_report.md §5)。"
        )
    md.append("")
    md.append("## 4. 入选理由")
    md.append("")
    md.append(REASON[name])
    md.append("")
    (case_dir / "case.md").write_text("\n".join(md), encoding="utf-8")


# ---- 入选理由 (逐案例) ----
REASON = {}
# S08: 9 选 7, 覆盖 3 个重试轮, 展示分数恒定 0.64
_s08 = {
    "S08_a0_0": "S08 首轮第 1 候选; m5_calibration §1.1 目检样本之一 (画质良好), 是\"启发式打低非画面问题\"的直接证据。",
    "S08_a0_1": "与 S08_a0_0 同轮不同 seed, G5 分数完全相同 (0.64) —— 分数恒定现象的最小对照。",
    "S08_a0_2": "首轮第 3 seed, 分数仍 0.64; 同轮 3 seed 分数零波动, 证明失败由资产类型决定而非生成质量波动。",
    "S08_a1_0": "重试轮 1 (加强 negative + guidance-0.5) 后分数仍 0.64 —— 重试钩子对启发式 G5 完全无效的证据。",
    "S08_a1_1": "重试轮 1 候选, 且为 m5_calibration §1.1 目检样本 (画质良好); 校准后重评 0.85 (S08 最高带)。",
    "S08_a1_2": "重试轮 1 第 3 seed, 分数恒定 0.64; 校准后重评 0.85, 反差最大案例之一。",
    "S08_a2_1": "重试轮 2 (第 7 个 seed) 分数仍 0.64 —— 3 轮 9 候选分数恒定, 34 个生成量中 9 个空转的典型 (M2 §5: 重试 0 收益)。",
}
for k, v in _s08.items():
    REASON[k] = v
# S09: 9 选 7, 分数带 0.621-0.633 最宽 + 2 个校准后仍 borderline
_s09 = {
    "S09_a0_0": "S09 最弱候选 (M2 G5 0.6214 全库最低); 校准后重评 0.6914 仍 borderline —— 双锚校准后仍未过 0.70 的 2 例之一, 是\"阈值边缘带真实存在\"的样本。",
    "S09_a0_1": "首轮第 2 seed, M2 分 0.633 / 校准后 0.773 —— S09 内部分数差异最大的一对 (0.6214 vs 0.633), 展示该镜头并非完全恒定但有界。",
    "S09_a0_2": "首轮第 3 seed, 校准后 0.7733 pass 带; 与 a0_0 对照说明同镜头候选间真实质量差异被旧锚压缩到 0.01 内。",
    "S09_a1_0": "重试轮 1; 校准后重评 0.698 仍 borderline (<0.70) —— 另一例\"校准后仍不过\", 与 a0_0 同为 S09 最弱带。",
    "S09_a1_1": "重试轮 1, 校准后 0.7718 pass; m5_calibration §1.1 目检镜头样本组。",
    "S09_a1_2": "重试轮 1 第 3 seed; m5_calibration §1.1 目检样本 (雨珠+暖光散景层次分明, 画质良好), 校准后 0.7728。",
    "S09_a2_0": "重试轮 2, 校准后 0.7693; 展示重试轮产出的候选校准后基本都入 pass 带, 进一步支持\"旧锚系统性偏差\"结论。",
}
for k, v in _s09.items():
    REASON[k] = v
# S11: 16 选 8, n_best=4 / retry_max=3 (4 轮), 16 候选全 borderline
_s11 = {
    "S11_a0_0": "S11 首轮第 1 候选; m5_calibration §1.1 目检样本 (背影走廊无正脸合规, 画质良好); 中风险卡 n_best=4 的首轮代表。",
    "S11_a0_1": "首轮第 2 seed, 分数 0.64 与同轮其余 3 seed 恒定。",
    "S11_a0_2": "首轮第 3 seed, 校准后重评 0.85 (最高带) vs M2 0.64 —— 反差最大的案例之一。",
    "S11_a0_3": "首轮第 4 seed (n_best=4), 分数仍恒定 0.64; 展示中风险卡放大 n_best 也无法逃出启发式偏差。",
    "S11_a1_0": "重试轮 1 第 1 seed, 校准后 0.85。",
    "S11_a2_1": "全部 34 个 M2 失败候选中唯一非 0.64 的第 2 例 (0.6255), 校准后 0.7655 —— S11 分数带的下界样本。",
    "S11_a2_3": "重试轮 2; m5_calibration §1.1 目检样本 (透视自然, 画质良好)。",
    "S11_a3_0": "重试轮 3 (retry_max=3 的最后轮) 第 1 seed, 分数仍 0.64 —— S11 共 4 轮 16 候选 0 收益空转的收尾证据 (M2 §5: 建议稳定-borderline 短路的直接动因, 后落地为 D-042)。",
}
for k, v in _s11.items():
    REASON[k] = v
# 类型B
REASON["S14_a0_0"] = (
    "M5 生产期 2 个 fail 之一 (全收): G5=0.6932 距阈值 0.0068, 其余四门禁全过; 双锚校准已上线仍落入边缘带, "
    "说明 0.70 阈值下 borderline 带不可避免; 同任务第 2 候选 (id=50, 0.9196) pass 并被选中 —— n_best 冗余按设计吸收单候选失败的实证。"
)
REASON["S15_a0_0"] = (
    "M5 生产期 2 个 fail 之一 (全收): G5=0.6913 距阈值 0.0087; 同任务第 3 候选 (id=54, 0.9273) pass 并被选中; "
    "与 S14 合计构成生产期唯一的 2 例候选级失败 (50 候选 48 pass), 是良率 96% 与任务良率 100% 之间差距的全部来源。"
)

CASE_NO = {}


def main():
    fails_main = load_fails(MAIN_DB)
    fails_sb = load_fails(SB_DB)
    print(f"main fails={len(fails_main)}, sandbox fails={len(fails_sb)}")
    reeval = {Path(r["path"]).name.replace(".mp4", ""): r for r in json.load(open(REEVAL))["rows"]}

    cards = {}
    for name in TYPE_A + TYPE_B:
        shot, _, _ = parse_name(name)
        if shot not in cards:
            found = list(CARDS.glob(f"{shot}_*.json"))
            cards[shot] = json.load(open(found[0]))

    if OUT.exists():
        shutil.rmtree(OUT)
    typeA_dir = OUT / "typeA_g5_scene_bias"
    typeB_dir = OUT / "typeB_g5_edge"
    typeA_dir.mkdir(parents=True)
    typeB_dir.mkdir(parents=True)

    order = TYPE_A + TYPE_B
    for i, name in enumerate(order, 1):
        CASE_NO[name] = f"A{i:02d}" if name in TYPE_A else f"B{i - len(TYPE_A):02d}"

    total = 0
    for name in order:
        shot, attempt, idx = parse_name(name)
        is_a = name in TYPE_A
        ctype = "类型A: 校准前 G5 启发式场景偏差" if is_a else "类型B: 生产期 G5 边缘"
        rec = fails_main[name] if is_a else fails_sb[name]
        dbp = MAIN_DB if is_a else SB_DB
        case_dir = (typeA_dir if is_a else typeB_dir) / name
        case_dir.mkdir()
        # 1. mp4 实体拷贝
        shutil.copy2(rec["db_path"], case_dir / "video.mp4")
        # 2. gate_json 副本
        (case_dir / "gate_json.json").write_text(
            json.dumps(rec["gate_json"], ensure_ascii=False, indent=1), encoding="utf-8"
        )
        # 3. 2×5 网格图 (帧缓存 → JPEG)
        frames_dir = Path(rec["db_path"] + ".frames")
        size = make_grid(frames_dir, case_dir / "grid.jpg")
        # 4. case.md
        tm = load_task_meta(SB_DB if not is_a else MAIN_DB, shot)
        write_case(case_dir, name, ctype, rec, reeval.get(name), cards[shot], tm,
                   "M2 LTX 调试车道 (主仓库)" if is_a else "M5 Wan 生产 (沙箱 cradle_m5)")
        total += sum(f.stat().st_size for f in case_dir.iterdir())
        print(f"{CASE_NO[name]} {name}: grid={size}, files={len(list(case_dir.iterdir()))}")

    print(f"gallery media total: {total/1e6:.1f} MB")


if __name__ == "__main__":
    main()
