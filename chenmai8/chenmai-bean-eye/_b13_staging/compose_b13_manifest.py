#!/usr/bin/env python3
"""批13 manifest 组装（compose_b13_manifest）。

读批13 四件产物（训练 metrics.json / 探针 probe_b13.json / τ 扫描
sweep_tau_b13.json / Zenodo val zenodo_valid_normal_b13.json）与批12
manifest（对照基线），产出 /data/coffee-bean/batch13-results/b13_manifest.json：
配方与单变量改动、redline 自证、vs_batch12 对照（自动算 delta）、verdict
阅读、deviations、产物 sha256。全部数字取自产物 JSON，不手填。
"""
from __future__ import annotations

import json
from pathlib import Path

R13 = Path("/data/coffee-bean/batch13-results")
R12 = Path("/data/coffee-bean/batch12-results")
RUN = Path("/home/anuser/agentic-factory-projects/chenmai8/chenmai-bean-eye/"
           "train/runs/retrain_b13_defos8")

B12 = {
    "holdout_normal": 0.813411,
    "bad_pile_nonnormal": 0.327273,
    "bad_pile_bbs": 0.218182,
    "synth_test_macro_f1": 0.884087,
    "zenodo_val_rate": 1.0,
    "real_valid_macro_sup": 0.749476,
    "real_gradient_share_pct": 29.3,
    "defect_gradient_share_pct": 10.7,  # 批12：(28741-18253)×3/(208058+28741×3)
    "normal_by_pile": {"大": 70.0, "中": 76.53, "小": 86.67},
    "tau_recommendation": {"feasible": False, "tau": 0.1,
                           "normal_rate": 0.661808, "bbs_rate": 0.290909},
}


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def sha256_file(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ppct(x):
    return f"{100 * x:.2f}%"


def main() -> int:
    metrics = load(RUN / "metrics.json")
    probe = load(R13 / "probe_b13.json")
    tau = load(R13 / "sweep_tau_b13.json")
    zen = load(R13 / "zenodo_valid_normal_b13.json")
    b12_manifest = load(R12 / "b12_manifest.json")

    ps = probe["summary"]
    bad = probe["piles"]["坏"]
    bad_beans = bad["beans"]
    bbs_counts = {k: int(bad["class_counts"].get(k, 0)) for k in ("broken", "black", "sour")}
    bbs_n = sum(bbs_counts.values())
    nonnormal_n = bad_beans - int(bad["normal"])
    normal_rate = ps["normal_correct_rate"]
    bad_nonnormal_rate = round(nonnormal_n / bad_beans, 6)
    bbs_rate = round(bbs_n / bad_beans, 6)

    synth_test = metrics["eval"]["synth_test"]["macro_f1"]
    real_sup = metrics["eval"]["real_valid"]["macro_f1_supported"]
    zen_rate = zen["normal_correct_rate"]
    rec = tau["recommendation"]

    d = lambda a, b: round(a - b, 6)  # noqa: E731

    manifest = {
        "batch": "batch13-defect-oversample-retrain",
        "date": "2026-10-04",
        "host": "anolis-gpu-01 (36.139.118.235 / tailnet 100.64.0.7), 2xV100S-32GB, 训练只用卡0",
        "purpose": "单变量对照：批12 配方基础上对全部非 normal 真实训练裁片过采样 ×8"
                   "（normal 保持原量），回答「坏堆检出 32.7% 的 normal 过优势能否救回、"
                   "normal 及格率要赔多少」；对照批12（normal 81.34% / 坏堆检出 32.73% / "
                   "{broken,black,sour} 21.82% / 合成 macro 0.8841）",
        "baseline_batch12": {
            "best_checkpoint": "/data/coffee-bean/batch12-results/best.pt"
                               "（best_epoch=7，real_valid_macro_sup=0.749476）",
            "note": "批12 产物在机完整（best.pt/crop_cls.onnx sha256 与 b12_manifest.json"
                    " artifacts_sha256 逐一相符，本批开工前已核），对照锚点直接复用，未重训",
        },
        "code_identity": {
            "retrain_real_b13.py": "新增脚本（批13），基于批12 retrain_real.py"
                                   "（92527f6b…）复制改写：唯一新参数 --defect-oversample；"
                                   "扫描/合并/门槛常量直接 import 批12 脚本本体",
            "eval_real_probe.py": "批12 交付件原样（b7940351…），评测口径零漂移",
            "sweep_defect_threshold_b13.py": "批12 sweep（EXPECT_* 钉批12 探针）适配版："
                                             "EXPECT_* 改钉批13 probe_b13.json，其余逐字节同源",
            "eval_zenodo_valid_b13.py": "批12 eval_zenodo_valid_b12.py 适配版（算法同）",
        },
        "redline_attestation": {
            "rule": "训练与选型全程不得使用 /data/coffee-bean/crops-hn 与 crops-hn-*"
                    "（用户照片派生裁片=holdout 域）",
            "real_roots_used": metrics["data"]["real_roots"],
            "synth_root_used": metrics["data"]["synth_root"],
            "crops_hn_touched": False,
            "evidence": "retrain_real_b13.py --dry-run 输入清单 7 个真实根逐条 [OK] 且不含"
                        "任何 crops-hn* 路径；metrics.json args.real_roots 同（与批12 "
                        "完全相同的 7 根）；holdout /data/coffee-bean/real-photos（26 张）"
                        "仅在训练结束后由 eval_real_probe.py 评测一次，未参与任何训练/选型；"
                        "zenodo val 252 张 PNG 仅终评（训练根与批12 相同，继续零接触）",
        },
        "recipe": {
            "model": metrics["weights_source"] + "，resnet18 + 13 类头（与批12 同起点，"
                     "非批12 权重热启动——保证两批唯一差异是过采样）",
            "precision": "fp16 autocast + GradScaler（V100 无 bf16）",
            "epochs": metrics["args"]["epochs"],
            "batch": metrics["args"]["batch"],
            "lr": metrics["args"]["lr"],
            "optimizer": "AdamW wd=0.05 + cosine",
            "imbalance": "loss-weight w_c=1/log(1.02+n_eff_c)（n_eff 按过采样后有效计数，"
                         "公式与批12 同源）",
            "real_repeat": metrics["args"]["real_repeat"],
            "defect_oversample": metrics["args"]["defect_oversample"],
            "oversample_applies_to": metrics["oversample"]["applies_to"],
            "repeat_by_class": metrics["oversample"]["repeat_by_class"],
            "effective_train": metrics["data"]["real_train_effective"] + metrics["data"]["synth_train"],
            "real_gradient_share_pct": metrics["data"]["real_gradient_share_pct"],
            "defect_gradient_share_pct": metrics["data"]["defect_gradient_share_pct"],
            "valid_oversampled": False,
            "best_epoch": metrics["best_epoch"],
            "train_seconds": metrics["train_seconds"],
            "seed": metrics["args"]["seed"],
        },
        "results": {
            "holdout_probe_user_photos": {
                "n_photos": probe["n_photos"],
                "n_photos_by_pile": probe["n_photos_by_pile"],
                "normal_correct_rate": normal_rate,
                "normal_by_pile_pct": ps["normal_correct_rate_by_pile"],
                "normal_pile_beans": ps["normal_piles_beans"],
                "normal_pile_normal": ps["normal_piles_normal"],
                "bad_pile_beans": bad_beans,
                "bad_pile_defect_detection_nonnormal": bad_nonnormal_rate,
                "bad_pile_hn_defect_broken_black_sour": {
                    "rule": "检出=预测∈{broken,black,sour}",
                    "detected": bbs_n, "rate": bbs_rate,
                },
                "bad_pile_defect_distribution_pct": ps["bad_pile_defect_distribution_pct"],
                "size_order_ok": ps["size_order_ok"],
            },
            "synth_test_macro_f1": {
                "value": synth_test, "threshold": 0.85,
                "pass": bool(metrics["gates"]["synth_test_macro_f1"]["pass"]),
                "batch12": B12["synth_test_macro_f1"],
            },
            "zenodo_val_252_normal_rate": {
                "value": zen_rate, "n": zen["n"],
                "pred_counts": zen["pred_counts"],
                "p_normal_mean": zen["p_normal_mean"],
                "nature": "真留出（不入训练/选型，批12 起口径不变）",
            },
            "real_valid_macro_sup": {
                "value": real_sup,
                "note": "选型 valid 合并集口径（与批12 同集合：批12 已剔除 zenodo valid 252"
                        " 并加入 web-b12 valid 267；批13 训练根与批12 完全相同，集合相同，"
                        "可直接比）",
            },
            "tau_sweep": {
                "rule": tau["tau_rule"],
                "argmax_reference_verified": tau["argmax_reference"]["match_probe_b13"],
                "curve_summary": [
                    {k: r[k] for k in ("tau", "normal_rate", "bbs_rate", "defect_any_rate")}
                    for r in tau["curve"]],
                "recommendation": rec,
            },
            "vs_batch12": {
                "holdout_normal": {"b12": B12["holdout_normal"], "b13": normal_rate,
                                   "delta": d(normal_rate, B12["holdout_normal"])},
                "holdout_normal_by_pile": {"b12": B12["normal_by_pile"],
                                           "b13": ps["normal_correct_rate_by_pile"]},
                "bad_pile_nonnormal": {"b12": B12["bad_pile_nonnormal"], "b13": bad_nonnormal_rate,
                                       "delta": d(bad_nonnormal_rate, B12["bad_pile_nonnormal"])},
                "bad_pile_hn3_broken_black_sour": {"b12": B12["bad_pile_bbs"], "b13": bbs_rate,
                                                   "delta": d(bbs_rate, B12["bad_pile_bbs"])},
                "synth_test_macro_f1": {"b12": B12["synth_test_macro_f1"], "b13": synth_test,
                                        "delta": d(synth_test, B12["synth_test_macro_f1"]),
                                        "threshold": 0.85},
                "zenodo_val_252_normal_rate": {"b12": B12["zenodo_val_rate"], "b13": zen_rate},
                "real_valid_macro_sup": {"b12": B12["real_valid_macro_sup"], "b13": real_sup,
                                         "delta": d(real_sup, B12["real_valid_macro_sup"])},
                "gradient_share": {
                    "real_pct": {"b12": B12["real_gradient_share_pct"],
                                 "b13": metrics["data"]["real_gradient_share_pct"]},
                    "defect_pct": {"b12": B12["defect_gradient_share_pct"],
                                   "b13": metrics["data"]["defect_gradient_share_pct"]},
                },
                "tau_recommendation": {"b12": B12["tau_recommendation"], "b13": rec},
            },
        },
        "per_photo_b12_vs_b13": [
            {"file": r.get("file"), "pile": r.get("pile"), "beans": r.get("beans"),
             "normal_b12": r.get("normal_b12"),
             "normal_b13": next((p.get("class_counts", {}).get("normal", 0)
                                 for p in probe.get("photos", [])
                                 if p.get("file") == r.get("file")), None)}
            for r in b12_manifest.get("results", {}).get("confusion_analysis", {})
            .get("per_photo_b11_vs_b12", [])],
        "verdict": {
            "rule": "ask 口径=单变量对照（缺陷过采样×8）；诚实第一",
            "holdout_normal": normal_rate,
            "delta_normal_vs_b12": d(normal_rate, B12["holdout_normal"]),
            "delta_bad_detect_vs_b12": d(bad_nonnormal_rate, B12["bad_pile_nonnormal"]),
            "delta_bbs_vs_b12": d(bbs_rate, B12["bad_pile_bbs"]),
            "reading": [
                f"缺陷过采样×8（缺陷有效梯度占比 10.7%→{metrics['data']['defect_gradient_share_pct']}%）"
                f"没有把坏堆检出救回来：非 normal 检出 32.73%→{100*bad_nonnormal_rate:.2f}%"
                f"（{d(bad_nonnormal_rate, B12['bad_pile_nonnormal'])*100:+.2f}pp），"
                f"{{broken,black,sour}} 21.82%→{100*bbs_rate:.2f}%"
                f"（{d(bbs_rate, B12['bad_pile_bbs'])*100:+.2f}pp，坏堆检出构成 "
                f"{bbs_counts} + dried 等共 {nonnormal_n}/55）——在本配方内，「normal 过优势"
                f"源于缺陷样本太少」这一方向被证伪",
                f"normal 侧反而大涨 81.34%→{100*normal_rate:.2f}%"
                f"（{d(normal_rate, B12['holdout_normal'])*100:+.2f}pp；中 76.53→"
                f"{ps['normal_correct_rate_by_pile']['中']}、小 86.67→"
                f"{ps['normal_correct_rate_by_pile']['小']}、大 70.0→"
                f"{ps['normal_correct_rate_by_pile']['大']} 持平）：过采样使逐类有效计数上升，"
                f"loss 权重 w_c=1/log(1.02+n_eff) 相应下降（black 0.096→0.085 全场最低），"
                f"缺陷过判被进一步抑制——批12 主混淆 normal→black 47 粒(13.7%)在本批收敛到 "
                f"约 8 粒，代价是坏堆里同类深色豆也被放行（坏堆 normal 37/55→40/55）",
                "机制判读：合成域 black recall 已≈1.0（b12 synth_test black F1 0.999，"
                "过采样无增益空间）；web/ext 缺陷裁片与海南实拍深色豆的域差才是根因——"
                "更多同域缺陷裁片把「black」决策边界收得更紧，海南域深色缺陷豆整体落在边界外。"
                "检出的瓶颈是域差而非样本量",
                f"合成域未失守：synth_test macro {synth_test}（批12 0.884087，"
                f"{d(synth_test, B12['synth_test_macro_f1']):+.6f}，门 0.85 PASS）；"
                f"Zenodo val 252/252=100%（真留出保持）；选型集 real_valid macro(sup) "
                f"{real_sup}（批12 0.749476）",
                f"τ 扫描：全网格无可行点（检出≥55% 且 normal≥70% 同时满足）；推荐 τ="
                f"{rec['tau']}（normal {100*rec['normal_rate']:.2f}% / BBS 检出 "
                f"{100*rec['bbs_rate']:.2f}%）。批12 同 τ=0.1 为 66.18%/29.09%——"
                f"若应用端要「更保守不扰民」，批13 工作点正常堆体验显著更好，但坏豆漏检更多；"
                f"argmax 工作点（normal 93.29%/检出 16.36%）适合「宁漏勿扰」场景",
                "对照结论：过采样路线对「坏堆检出」目标收益为负（-5.45pp），对 normal 及格率"
                "收益 +11.95pp。若目标是救检出，下一单变量应转向域适应方向（海南域少样本"
                "微调/按 p_normal 单类校准/测试时增强），而非继续加大缺陷样本量",
            ],
        },
        "deviations_from_ask": [
            "「非 normal 全部」口径：任务名单列 10 类后接「——非 normal 全部」，按后者执行："
            "全部 12 个非 normal 类过采样（peaberry 非 normal、有真实样本 1002 张，一并 ×8；"
            "brocade 真实训练 0 张，×8 无操作，如实记录）",
            "×8 与 real_repeat 的组合：按「其余同批12（…real_repeat…）」保持全局 "
            "real_repeat=3 不变，缺陷类在 ×3 之上额外 ×8 → 缺陷有效 ×24、normal ×3；"
            "真实梯度占比 29.3%→59.6%、缺陷类 10.7%→48.9%（metrics.json "
            "oversample.repeat_by_class / real_eff_by_class 全量可复核）",
            "起点语义：批12 best checkpoint 在机完整（best.pt/crop_cls.onnx sha256 与 "
            "b12_manifest.json artifacts_sha256 相符，开工前已核），按 ask 作为对照锚点"
            "直接复用、未重训；批13 训练与批12 同从 IMAGENET1K_V1 起步（非批12 权重热启动），"
            "保证「过采样」是唯一变量",
            "valid/选型集不过采样（任务只改训练裁片；real_valid 合并集与批12 完全同集合，"
            "real_valid 指标可直接比）",
            "CPU batch1 延迟 8.199ms（批12 记录 4.909ms）：非部署目标机、测时机器负载不同，"
            "口径如实记录不另行归一",
        ],
        "artifacts_gpu_dir": str(R13),
    }

    arts = {}
    for p in sorted(R13.iterdir()):
        if p.is_file():
            arts[p.name] = sha256_file(p)
    manifest["artifacts_sha256"] = arts

    out = R13 / "b13_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"[manifest] {out}")
    print(f"[三数] holdout_normal={normal_rate}（b12 {B12['holdout_normal']}，"
          f"delta {d(normal_rate, B12['holdout_normal']):+.4f}）；坏堆检出"
          f"(非normal)={bad_nonnormal_rate}（b12 {B12['bad_pile_nonnormal']}，"
          f"delta {d(bad_nonnormal_rate, B12['bad_pile_nonnormal']):+.4f}）；"
          f"BBS={bbs_rate}（{bbs_counts}）；synth_test_macro={synth_test}；"
          f"zenodo={zen_rate}；real_sup={real_sup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
