#!/usr/bin/env python3
"""批12 台账组装（compose_b12_manifest.py）：读 batch12-results 下四个结果 JSON
与批11 manifest 基线，产出 b12_manifest.json（诚实对照 + 数据溯源 + 红线声明）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

R = Path("/data/coffee-bean/batch12-results")
B11 = Path("/data/coffee-bean/batch11-results/b11_manifest.json")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    metrics = json.loads((R / "metrics.json").read_text(encoding="utf-8"))
    probe = json.loads((R / "probe_b12.json").read_text(encoding="utf-8"))
    conf = json.loads((R / "probe_b12_conf.json").read_text(encoding="utf-8"))
    zen = json.loads((R / "zenodo_valid_normal_b12.json").read_text(encoding="utf-8"))
    b11 = json.loads(B11.read_text(encoding="utf-8"))
    b11r = b11["results"]["holdout_probe_user_photos"]
    b11synth = b11["results"]["synth_test_macro_f1"]
    b11zen = b11["results"]["zenodo_valid_normal"]
    b11probe = json.loads(
        Path("/data/coffee-bean/batch11-results/probe_b11_clean.json").read_text(encoding="utf-8"))

    s = probe["summary"]
    bad_cc = probe["piles"]["坏"]["class_counts"]
    hn3 = bad_cc["broken"] + bad_cc["black"] + bad_cc["sour"]
    hn3_rate = round(hn3 / probe["piles"]["坏"]["beans"], 6) if probe["piles"]["坏"]["beans"] else None

    hist = metrics["history"]
    best_epoch = metrics["best_epoch"]

    # 正常堆误判对比：批12 vs 批11（正常堆→black 是批11 主混淆）
    nm = conf["normal_misclass_by_pred"]
    black_now = nm.get("black", {})

    # 逐照片对照（b11 vs b12；分割粒数应一致=控制变量）
    per_photo = []
    seg_identical = True
    for p11, p12 in zip(b11probe["photos"], probe["photos"]):
        assert p11["file"] == p12["file"], "照片顺序不一致"
        if p11["beans"] != p12["beans"]:
            seg_identical = False
        per_photo.append({
            "file": p11["file"], "pile": p11["pile"],
            "beans": p11["beans"],
            "normal_b11": p11["class_counts"].get("normal", 0),
            "normal_b12": p12["class_counts"].get("normal", 0),
        })

    # 诚实判定与归因
    d_normal = round(s["normal_correct_rate"] - b11r["normal_correct_rate"], 6)
    d_detect = round((s["defect_detection_rate"] or 0) - (b11r["bad_pile_defect_detection_nonnormal"] or 0), 6)
    bad_full_11 = next(p for p in b11probe["photos"] if p["file"].startswith("坏（全）"))
    bad_full_12 = next(p for p in probe["photos"] if p["file"].startswith("坏（全）"))
    verdict = {
        "rule": "ask 口径：holdout normal 对照批11 63.3%，升级≥70% 为达标；坏堆检出对照 56.4%；诚实第一",
        "holdout_normal": s["normal_correct_rate"],
        "upgrade_ge_70pct": bool(s["normal_correct_rate"] >= 0.70),
        "delta_normal_vs_b11": d_normal,
        "delta_bad_detect_vs_b11": d_detect,
        "reading": [
            "正常堆 normal 判对率 63.27%→81.34%（+18.07pp，三堆 全升：大 58.0→70.0、中 50.0→76.53、小 71.28→86.67），"
            "越过 70% 升级线；批11 主混淆『正常豆→black』117 粒(34.1%)→47 粒(13.7%)，高置信段(0.9+)从 30 粒降到 9 粒",
            "代价：坏堆非 normal 检出 56.36%→32.73%（-23.6pp），{broken,black,sour} 口径 41.82%→21.82%——"
            "批11 manifest 已预言『检出率的改善部分由 black 过判贡献，同一枚硬币的两面』，本批硬币翻回了另一面："
            "black 过判消退的同时，坏堆里深色缺陷豆也被放行为 normal",
            "逐照片分解：改善与回退都集中在四张『（全）』堆照——中（全）24→50、小（全）96→129、大（全）11→19；"
            "坏（全）22→36（39 粒中 36 粒判 normal，占坏堆回退的绝大部分）。其余 22 张照片判对几乎不变（±1-2 粒）；"
            "两批分割粒数逐一相同（seg_identical=True），差异纯来自分类头",
            "坏堆 12/55 的新检出构成：black 11 + broken 1；dried 5 粒不在 {broken,black,sour} 口径内但属缺陷预测；"
            "正常堆误判里 dried 13 粒(3.8%)是新第二混淆（批11 只有 4 粒）——『深色/老化外观』在 black 与 dried"
            " 两个缺陷类间摆动，是网页黑豆样张与海南实拍深色豆域差的延续",
            "归因（与 ask 三个候选假说对照）：①『全品种 normal 稀释海南深色特征』方向成立但非稀释——allvar 13 个"
            " Arabica 品种真实生豆把『深色但正常』的外观重新拉回 normal 流形，主混淆大幅收敛；②网页域噪声：二轮网页"
            "裁片 2427 粒(正常 2369)进一步加宽网页 normal 覆盖，同向贡献；③批次效应：训练/评测代码 sha256 与批11"
            "逐一相同、分割粒数一致，可排除代码与分割批次效应。剩余 47 粒 black 误判 + 坏堆欠检表明：网页/公开域"
            "与海南实拍深色豆的域差仍在，纯网页域路线到此收益率已明显递减",
            "合成 test macro 0.8841（批11 0.8689，门 0.85 PASS）；真实梯度占比 16.01%→29.30%（全量 allvar 入池"
            "如实记录），合成域未失守。Zenodo val 252 张本批为真留出（不入训练/选型）252/252=100%",
        ],
    }

    manifest = {
        "batch": "batch12-web-expansion-retrain",
        "date": "2026-10-04",
        "host": "anolis-gpu-01 (36.139.118.235 / tailnet 100.64.0.7), 2xV100S-32GB, 训练只用卡0",
        "purpose": "网页域二轮扩张（2427 粒）+ Zenodo 全品种 normal 池（13361 张 Arabica）后的强化重训；"
                   "holdout 探针对照批11（normal 63.3% / 坏堆检出 56.4% / 合成 macro 0.8689）",
        "code_identity": "retrain_real.py / eval_real_probe.py / _probe_conf_analysis.py 与批11 "
                         "sha256 逐一相同（92527f6b… / b7940351… / 260cb120…）——同代码同口径，唯一变量是数据",
        "redline_attestation": {
            "rule": "训练与选型全程不得使用 /data/coffee-bean/crops-hn 与 crops-hn-*（用户照片派生裁片=holdout 域）",
            "real_roots_used": [
                "/data/coffee-bean/crops-web-b12",
                "/data/coffee-bean/crops-web-b11",
                "/data/coffee-bean/allvar-normal-jpg",
                "/data/coffee-bean/zenodo-robusta-normal-b12",
                "/data/coffee-bean/crops-ext/ext-main",
                "/data/coffee-bean/crops-ext/ext-scaa17",
                "/data/coffee-bean/crops-ext/ext-rgreen",
            ],
            "synth_root_used": "/data/coffee-bean/crops",
            "crops_hn_touched": False,
            "evidence": "retrain_real.py --dry-run 输入清单 7 个真实根逐条 [OK] 且不含任何 crops-hn* 路径；"
                        "metrics.json args.real_roots 同；holdout /data/coffee-bean/real-photos（26 张）"
                        "仅在训练结束后由 eval_real_probe.py 评测一次，未参与任何训练/选型",
        },
        "recipe": {
            "model": "resnet18 + 13 类头，IMAGENET1K_V1 起点（torchvision 预训练，BSD）",
            "precision": "fp16 autocast + GradScaler（V100 无 bf16）",
            "epochs": metrics["args"]["epochs"], "batch": metrics["args"]["batch"],
            "lr": metrics["args"]["lr"],
            "optimizer": "AdamW wd=0.05 + cosine",
            "imbalance": "loss-weight w_c=1/log(1.02+n_eff_c)",
            "real_repeat": metrics["args"]["real_repeat"],
            "effective_train": metrics["data"]["synth_train"]
            + metrics["data"]["real_train_effective"],
            "real_gradient_share_pct": metrics["data"]["real_gradient_share_pct"],
            "best_epoch": best_epoch,
            "train_seconds": metrics["train_seconds"],
            "seed": metrics["args"]["seed"],
        },
        "data_provenance": {
            "crops-web-b12": {
                "source": "COS everything-1476163454 beaneye-batch12/crops_web_b12.tar.gz"
                          "（2,316,333 bytes，sha256 6b045f267d1e69e27ed7c293038a653ffde462812d12826920ef033972773366）",
                "counts": "train 2160 + valid 267 = 2427（normal 2369 / black 27 / broken 17 / "
                          "insect 7 / sour 3 / shell 2 / immature 2，与任务给定一致；labels.csv 为 "
                          "class,count 汇总 8 行，训练不读 csv）",
            },
            "crops-web-b11": {
                "source": "复用 /data/coffee-bean/crops-web-b11（批11 已验）；本批以 b12-dl 重下的"
                          " tarball 做文件清单 diff：1016 文件逐一一致（B11-IDENTICAL）",
                "counts": "train 874 + valid 141 = 1015",
            },
            "allvar-normal": {
                "source": "COS beaneye-datasets/zenodo-allvar/allvar_normal.tar.gz"
                          "（183,543,560 bytes，sha256 a04af004c5635a2cc8e293a8e7ce69e8095189875142ad16965d2a81658f287d）"
                          "→ /data/coffee-bean/allvar-normal（allvar_out/train，14367 PNG）",
                "varieties": "14 目录：A-001..A-013（13 个 Arabica 品种，13361 张）+ R-001-Robusta（1006 张）",
                "dedup_decision": "R-001-Robusta 经 md5 全量比对与 zenodo_robusta_1258 train 1006 张"
                                  "逐一相同（1006/1006）→ 从 allvar 池剔除，由 zenodo-robusta-normal-b12"
                                  " 根单独入训，避免同一批图双计（计数/loss 权重）",
                "holdout_clean": "allvar 全部 14367 张（R-001 与 Arabica 各查一次）与 robusta val 252 张"
                                 "md5 零重叠 → zenodo holdout 干净；allvar 内部 md5 无重复",
                "build": "13 个 Arabica 品种 PNG→JPG(q95) 拍平 → allvar-normal-jpg/train/normal 13361 张"
                         "（build_b12_real_pools.py）；valid/normal 置空——该池不入选型 valid",
            },
            "zenodo-robusta-normal-b12": {
                "source": "复用 zenodo-normal-b11/train/normal 的 1006 张 JPG(q95)（同源 tarball"
                          " sha256 4e83f37a2d01bc20d1a0a5cc41530ef5e4dcf6f5fb1432461c6537ff52e3d314）",
                "holdout_discipline": "valid/normal 置空：val 252 张不入训练、也不入选型 valid"
                                      "（批11 曾入选型合并集；批12 排除，参考指标由 in-domain 参考升级为真留出）",
            },
            "crops-ext": "ext-main / ext-scaa17 / ext-rgreen（机器已有，批5/b11 同款三集）",
            "synth": "/data/coffee-bean/crops 全量回放 208058（valid/test 同批4 口径）",
        },
        "results": {
            "holdout_probe_user_photos": {
                "n_photos": probe["n_photos"],
                "n_photos_by_pile": probe["n_photos_by_pile"],
                "normal_correct_rate": s["normal_correct_rate"],
                "normal_by_pile_pct": s["normal_correct_rate_by_pile"],
                "normal_pile_beans": s["normal_piles_beans"],
                "normal_pile_normal": s["normal_piles_normal"],
                "bad_pile_beans": s["bad_pile_beans"],
                "bad_pile_defect_detection_nonnormal": s["defect_detection_rate"],
                "bad_pile_hn_defect_broken_black_sour": {
                    "rule": "检出=预测∈{broken,black,sour}", "detected": hn3, "rate": hn3_rate},
                "bad_pile_defect_distribution_pct": s["bad_pile_defect_distribution_pct"],
                "size_order_ok": s["size_order_ok"],
                "eq_d_median_px": s["eq_d_median_px"],
            },
            "vs_batch11": {
                "holdout_normal": {"b11": b11r["normal_correct_rate"], "b12": s["normal_correct_rate"],
                                   "delta": round(s["normal_correct_rate"] - b11r["normal_correct_rate"], 6)},
                "holdout_normal_by_pile": {
                    "b11": b11r["normal_by_pile_pct"], "b12": s["normal_correct_rate_by_pile"]},
                "bad_pile_nonnormal": {"b11": b11r["bad_pile_defect_detection_nonnormal"],
                                       "b12": s["defect_detection_rate"],
                                       "delta": round((s["defect_detection_rate"] or 0) - (b11r["bad_pile_defect_detection_nonnormal"] or 0), 6)},
                "bad_pile_hn3_broken_black_sour": {"b11": b11r["bad_pile_hn_defect_broken_black_sour"]["rate"],
                                                   "b12": hn3_rate},
                "synth_test_macro_f1": {"b11": b11synth["value"],
                                        "b12": metrics["eval"]["synth_test"]["macro_f1"],
                                        "threshold": b11synth["threshold"],
                                        "pass": metrics["gates"]["synth_test_macro_f1"]["pass"]},
                "zenodo_val_252_normal_rate": {"b11": b11zen["rate"], "b12": zen["normal_correct_rate"],
                                               "b12_nature": "真留出（不入训练/选型）；b11 为 in-domain 参考",
                                               "b12_pred_counts": zen["pred_counts"],
                                               "b12_p_normal_mean": zen["p_normal_mean"]},
                "real_valid_macro_sup": {"b11": 0.74391,
                                         "b12": metrics["eval"]["real_valid"]["macro_f1_supported"],
                                         "note": "选型 valid 合并集口径，b12 已剔除 zenodo valid 252（-252）并"
                                                 "加入 web-b12 valid 267，两批集合不同，只作参考"},
            },
            "confusion_analysis": {
                "normal_pile_pred_counts": conf["normal_pred_counts"],
                "normal_misclass_detail": nm,
                "normal_pred_conf_mean": conf["normal_pred_conf_mean"],
                "bad_pile_pred_counts": conf["bad_pile_hn_defect_new_rule"]["pred_counts"],
                "b11_black_reference": b11["results"]["confusion_analysis"]["normal_misclass_detail"].get("black", {}),
                "per_photo_b11_vs_b12": per_photo,
                "segmentation_identical": seg_identical,
            },
        },
        "verdict": verdict,
        "deviations_from_ask": [
            "allvar-normal 实际入池 13361 张（任务给 14367）：R-001-Robusta 1006 张经 md5 比对与"
            " zenodo_robusta_1258 train 逐一全同，剔除以免同一批图经两个根重复入训（计数/loss 权重双计）；"
            "robusta 由 zenodo-robusta-normal-b12 根独立入训，总量不损",
            "zenodo val 252 张除不入训练外，也**不入选型 valid 合并集**（批11 曾入）：ask 说『留作 zenodo "
            "holdout 不入训练』，选型是训练管线的一环，一并排除后该 252 张成为真留出，参考指标性质由 "
            "in-domain 参考升级为留出考试",
            "全量 allvar + real_repeat=3 → 真实梯度占比 29.30%（批11 16.01%）：ask 预授权『抽样或全量，"
            "若全量导致合成占比过低则按 real_repeat 权衡，如实记录』——合成仍占 70.66% 未失守，未调 repeat",
            "epochs=8（ask 允许 8-10）：取下限以与批11 逐项对齐（同代码同超参，唯一变量=数据），best_epoch=7",
            "retrain_real.py 不在 /data/coffee-bean/train：与批11 相同，实际位于 repo "
            "/home/anuser/agentic-factory-projects/chenmai8/chenmai-bean-eye/train/（脚本 sha256 与批11"
            " 交付件逐一相同：92527f6b…/b7940351…/260cb120…）",
            "训练 env = repo .venv（torch 2.14.0+cu126，批11 同）；/data/night/venv 补装 onnx/onnxruntime"
            " 未用上（训练与评测最终均走 repo .venv）",
        ],
        "artifacts_gpu_dir": str(R),
    }
    out = R / "b12_manifest.json"
    manifest["artifacts_sha256"] = {
        f.name: sha256_file(f) for f in sorted(R.iterdir())
        if f.is_file() and f.name != "b12_manifest.json"
    }
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[manifest] {out}")
    print(json.dumps({
        "holdout_normal": {"b11": b11r["normal_correct_rate"], "b12": s["normal_correct_rate"],
                           "delta": d_normal},
        "bad_detect": {"b11": b11r["bad_pile_defect_detection_nonnormal"],
                       "b12": s["defect_detection_rate"], "delta": d_detect},
        "hn3": {"b11": b11r["bad_pile_hn_defect_broken_black_sour"]["rate"], "b12": hn3_rate},
        "synth_test": {"b11": b11synth["value"], "b12": metrics["eval"]["synth_test"]["macro_f1"]},
        "zenodo252_true_holdout": {"b11_in_sample": b11zen["rate"], "b12": zen["normal_correct_rate"]},
        "verdict_reading_head": verdict["reading"][0][:80],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
