"""契约 fixture 构造器：每个 schema 一个确定性合法样例。

用法（仓库根）::

    python -c "import sys; sys.path[:0]=['.','tests']; import _fixture_builders as fb; fb.write_all('tests/fixtures')"

所有取值相互一致（severity_rank 与 configs/taxonomy.yaml 默认序对齐、
obs_id=mask_id、final_* 与两面观测一致、defect_counts 与逐粒直方一致、
primary/secondary_count 与 taxonomy 主次归属一致、bean_count=豆列表长度、
color_lab 统一 lab8 标度三通道 0-255——W13 契约校验器配套）。
"""

from __future__ import annotations

import json
from pathlib import Path

from beaneye.schemas import (
    AgentReport,
    BatchResult,
    BeanMask,
    BeanObservation,
    CalibResult,
    CauseItem,
    GradingDecision,
    Measurements,
    PairedBean,
    PassportReport,
    SegResult,
    StatsSummary,
    TrayScan,
)

# severity_order 默认序（configs/taxonomy.yaml）:
# normal=0 broken=1 faded=2 brocade=3 immature=4 peaberry=5 shell=6
# elephant=7 insect=8 dried=9 sour=10 mold=11 black=12
RANK_NORMAL = 0
RANK_BROKEN = 1
RANK_BLACK = 12

SCAN_ID = "scan_synth_0001"
SAMPLE_ID = "sample_001"
TRAY_ID = "tray_01"
RESULT_ID = "6f1c0d2a-9b3e-4f57-8a21-4c9d7e501ab2"
STANDARD_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def bean_mask_top_017() -> BeanMask:
    return BeanMask(
        mask_id="top_017",
        side="top",
        polygon=[[10.0, 20.0], [12.5, 22.0], [14.0, 25.5], [11.0, 27.0], [8.5, 23.5]],
        bbox_mm=(8.5, 20.0, 14.0, 27.0),
        area_mm2=28.3,
        centroid_mm=(11.2, 23.6),
        source="classic",
        conf=0.97,
    )


def bean_mask_top_002() -> BeanMask:
    return BeanMask(
        mask_id="top_002",
        side="top",
        polygon=[[30.0, 40.0], [33.0, 41.5], [34.5, 44.5], [31.5, 46.0], [29.0, 43.0]],
        bbox_mm=(29.0, 40.0, 34.5, 46.0),
        area_mm2=26.4,
        centroid_mm=(31.6, 43.0),
        source="classic",
        conf=0.95,
    )


def seg_result() -> SegResult:
    return SegResult(
        scan_id=SCAN_ID,
        side="top",
        masks=[bean_mask_top_017(), bean_mask_top_002()],
        runtime_s=1.23,
    )


def bean_observation_top_017() -> BeanObservation:
    return BeanObservation(
        obs_id="top_017",
        side="top",
        defect="black",
        defect_conf=0.92,
        severity_rank=RANK_BLACK,
        crop_path=f"out/crops/{SCAN_ID}/top_017.png",
        mask=bean_mask_top_017(),
        color_lab=(89.8, 146.4, 137.1),
        eq_diameter_mm=6.0,
    )


def bean_observation_bottom_017() -> BeanObservation:
    return BeanObservation(
        obs_id="bottom_017",
        side="bottom",
        defect="normal",
        defect_conf=0.99,
        severity_rank=RANK_NORMAL,
        crop_path=f"out/crops/{SCAN_ID}/bottom_017.png",
        mask=BeanMask(
            mask_id="bottom_017",
            side="bottom",
            polygon=[[10.2, 20.3], [12.6, 22.1], [13.9, 25.4], [11.1, 26.9], [8.7, 23.6]],
            bbox_mm=(8.7, 20.3, 13.9, 26.9),
            area_mm2=27.9,
            centroid_mm=(11.3, 23.7),
            source="classic",
            conf=0.96,
        ),
        color_lab=(132.6, 117.8, 148.1),
        eq_diameter_mm=5.96,
    )


def paired_bean_b0001() -> PairedBean:
    """top=black(12) 胜 bottom=normal(0) → final black / worst_side=top。"""
    return PairedBean.from_sides(
        "b0001",
        bean_observation_top_017(),
        bean_observation_bottom_017(),
        pairing_cost=1.8,
    )


def paired_bean_b0002() -> PairedBean:
    """两面同为 broken(1) 平级 → 取 conf 高者(0.90)，worst_side=both。"""
    top = BeanObservation(
        obs_id="top_002",
        side="top",
        defect="broken",
        defect_conf=0.70,
        severity_rank=RANK_BROKEN,
        crop_path=f"out/crops/{SCAN_ID}/top_002.png",
        mask=bean_mask_top_002(),
        color_lab=(140.5, 136.2, 146.7),
        eq_diameter_mm=5.8,
    )
    bottom = BeanObservation(
        obs_id="bottom_002",
        side="bottom",
        defect="broken",
        defect_conf=0.90,
        severity_rank=RANK_BROKEN,
        crop_path=f"out/crops/{SCAN_ID}/bottom_002.png",
        mask=BeanMask(
            mask_id="bottom_002",
            side="bottom",
            polygon=[[30.1, 40.2], [33.1, 41.6], [34.4, 44.4], [31.6, 45.9], [29.2, 43.1]],
            bbox_mm=(29.2, 40.2, 34.4, 45.9),
            area_mm2=26.1,
            centroid_mm=(31.7, 43.1),
            source="classic",
            conf=0.94,
        ),
        color_lab=(139.2, 135.9, 146.2),
        eq_diameter_mm=5.77,
    )
    return PairedBean.from_sides("b0002", top, bottom, pairing_cost=2.4)


def paired_bean_b0003() -> PairedBean:
    """单面豆（仅 bottom，normal）→ pairing_cost=-1。"""
    bottom = BeanObservation(
        obs_id="bottom_003",
        side="bottom",
        defect="normal",
        defect_conf=0.98,
        severity_rank=RANK_NORMAL,
        crop_path=f"out/crops/{SCAN_ID}/bottom_003.png",
        mask=BeanMask(
            mask_id="bottom_003",
            side="bottom",
            polygon=[[60.0, 70.0], [62.8, 71.2], [64.0, 74.0], [61.2, 75.4], [58.8, 72.6]],
            bbox_mm=(58.8, 70.0, 64.0, 75.4),
            area_mm2=27.2,
            centroid_mm=(61.4, 72.6),
            source="classic",
            conf=0.93,
        ),
        color_lab=(131.1, 118.2, 147.6),
        eq_diameter_mm=5.89,
    )
    return PairedBean.from_sides("b0003", None, bottom, pairing_cost=-1.0)


def calib_result() -> CalibResult:
    return CalibResult(
        px_per_mm=6.8267,  # 2048 px / 300 mm
        H_top=[[6.8267, 0.0, 12.0], [0.0, 6.8267, 8.0], [0.0, 0.0, 1.0]],
        H_bottom=[[6.8267, 0.0, 10.0], [0.0, 6.8267, 9.0], [0.0, 0.0, 1.0]],
        marker_ids=[0, 1, 2, 3],
        reproj_err_px=0.42,
    )


def tray_scan() -> TrayScan:
    return TrayScan(
        scan_id=SCAN_ID,
        sample_id=SAMPLE_ID,
        tray_id=TRAY_ID,
        top_image=f"data/synth/batch_0001/top_0001.png",
        bottom_image=f"data/synth/batch_0001/bottom_0001.png",
        calibration=calib_result(),
        captured_at="2026-09-28T10:00:00+08:00",
        source="synth",
    )


def stats_summary() -> StatsSummary:
    return StatsSummary(min=5.1, max=8.2, mean=6.4, median=6.3)


def measurements() -> Measurements:
    return Measurements(
        bean_count=350,
        sieve_hist={"13": 120, "14": 150, "15": 60, "16": 20},
        sieve_pass=True,
        eq_diameter_mm_stats=stats_summary(),
        color_lab_mean=(132.9, 117.5, 148.3),
        delta_e_mean=3.2,
        delta_e_hist={"0-2": 90, "2-4": 160, "4-8": 100},
        est_weight_g=196.0,
        weight_model="area_linear:v1",
    )


def grading_decision() -> GradingDecision:
    """与 batch_result 的 beans 直方一致：black=1, broken=1。"""
    return GradingDecision(
        standard_id="cqi_fine_robusta",
        grade="Fine",
        passed=True,
        primary_count=1,
        secondary_count=1,
        defect_counts={"black": 1, "broken": 1},
        reasons=[
            "grading.reason.primary_over_limit",
            "grading.reason.secondary_within_limit",
        ],
        standard_yaml_sha=STANDARD_SHA,
    )


def cause_item() -> CauseItem:
    return CauseItem(
        defect="black",
        stage="干燥",
        likelihood=0.72,
        evidence_summary="3 粒黑豆且色差远超参考色，指向干燥温度过高或堆闷。",
    )


def agent_report() -> AgentReport:
    return AgentReport(
        lang="zh",
        causes=[cause_item()],
        advice=[
            "降低干燥温度并摊薄铺晒",
            "采收后 24h 内完成脱果脱胶",
        ],
        citations=["cqi_fine_robusta#full_black", "kb:chunk-012"],
        backend="template",
    )


def measurements_for_batch() -> Measurements:
    """与 batch_result 的 3 粒豆列表一致的计量（bean_count=本盘粒数口径，W13 契约校验）。"""
    return Measurements(
        bean_count=3,
        sieve_hist={"14": 2, "15": 1},
        sieve_pass=True,
        eq_diameter_mm_stats=stats_summary(),
        color_lab_mean=(132.9, 117.5, 148.3),
        delta_e_mean=3.2,
        delta_e_hist={"2-4": 3},
        est_weight_g=19.6,
        weight_model="area_linear:v1",
    )


def batch_result() -> BatchResult:
    beans = [paired_bean_b0001(), paired_bean_b0002(), paired_bean_b0003()]
    return BatchResult(
        result_id=RESULT_ID,
        sample_id=SAMPLE_ID,
        scan_ids=[SCAN_ID],
        beans=beans,
        measurements=measurements_for_batch(),
        grading=grading_decision(),
        agent_report=agent_report(),
        timings_s={"segment": 0.9, "classify": 0.2, "pairing": 0.05, "metrology": 0.1},
        pipeline_versions={
            "segment": "classic",
            "classify": "rules_v0",
            "standard": "cqi_fine_robusta",
        },
    )


def passport_report() -> PassportReport:
    return PassportReport(
        report_id=RESULT_ID,
        langs=["zh", "en", "vi"],
        html_paths={
            "zh": "out/reports/6f1c0d2a.zh.html",
            "en": "out/reports/6f1c0d2a.en.html",
            "vi": "out/reports/6f1c0d2a.vi.html",
        },
        qr_payload=f"https://verify.beaneye.example/r/{RESULT_ID}|{STANDARD_SHA}",
        sha256=STANDARD_SHA,
    )


def all_fixtures() -> dict[str, object]:
    return {
        "calib_result": calib_result,
        "bean_mask": bean_mask_top_017,
        "seg_result": seg_result,
        "bean_observation": bean_observation_top_017,
        "paired_bean": paired_bean_b0001,
        "tray_scan": tray_scan,
        "stats_summary": stats_summary,
        "measurements": measurements,
        "grading_decision": grading_decision,
        "cause_item": cause_item,
        "agent_report": agent_report,
        "batch_result": batch_result,
        "passport_report": passport_report,
    }


def write_all(outdir: str | Path) -> list[Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, builder in all_fixtures().items():
        model = builder()
        text = json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2)
        path = out / f"{name}.json"
        path.write_text(text + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":  # pragma: no cover
    for p in write_all("tests/fixtures"):
        print(f"wrote {p}")
