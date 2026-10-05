"""train/ 训练脚本线冒烟（六脚本 --dry-run 逐个 exit 0，纯离线）。

运行（仓库根）::

    pytest tests/test_train_smoke.py -q

覆盖：
1. 六脚本逐个 ``--dry-run``：退出码 0、打印 ``[DRY-RUN 结果] PASS``；
   纯离线——无网络/无 GPU/无 NN 栈（检测分割 NN 包/torch 未安装，若 dry-run
   触发导入会直接 ImportError；另以 ``-X importtime`` 断言未导入 NN 栈模块）；
2. 结构性错误必须显式失败：种子区间重叠（防泄漏红线，**双向**）→ exit 2；
   评测对象二选一冲突 → exit 2（dry-run 不做摆设校验）；
3. 合成引擎 → COCO RLE 端到端（真实模式小样本，离线）：
   ``prepare_coco.py --emit-sample`` 产出 512² 小盘对 + COCO json，
   用**独立实现的 RLE 解码**交叉验证 bbox/area/类别/上下配对
   （不依赖 beaneye，防「自己验自己」）；
4. 复核回归项：跨类重叠不得计 TP（:func:`prf_from_matches` 类别一致匹配）、
   粒数相对误差量纲（逐盘口径，非总体 MAE÷标注总数）、外部主源合并
   一图多粒的 image 条目去重。

测试不产生仓库内残留（emit-sample 落 tmp_path）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TRAIN = REPO_ROOT / "train"

SCRIPTS = [
    "prepare_coco.py",
    "det_finetune.py",
    "eval_seg.py",
    "eval_ablation.py",
    "domain_mix.py",
    "export_onnx_quant.py",
]

# dry-run 路径禁止出现的重量级模块（NN 栈；中性名纪律见 train/_common.py）
FORBIDDEN_IMPORTS = ("torch", "torchvision", "".join(("rf", "detr")), "onnxruntime")


def _run_train(args: list[str], timeout: float = 300) -> subprocess.CompletedProcess:
    """以仓库根为 cwd 跑 train/ 脚本（UTF-8 捕获，与 gate 脚本同约定）。"""
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# ① 六脚本 --dry-run exit 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SCRIPTS)
def test_dry_run_exit_zero(name: str) -> None:
    """--dry-run：exit 0 + PASS 标记 + 不导入 NN 栈（单次 -X importtime 子进程）。"""
    env = {**os.environ, "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, "-X", "importtime", str(TRAIN / name), "--dry-run"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"{name} --dry-run 退出码 {proc.returncode}（要求 0）\n"
        f"--- stdout ---\n{proc.stdout[-3000:]}\n--- stderr ---\n{proc.stderr[-2000:]}"
    )
    assert "[DRY-RUN 结果] PASS" in proc.stdout, (
        f"{name} 未打印 dry-run 通过标记\n{proc.stdout[-2000:]}"
    )
    # -X importtime 的导入清单在 stderr：dry-run 不得触碰 NN 栈
    for mod in FORBIDDEN_IMPORTS:
        hit = [
            ln for ln in proc.stderr.splitlines()
            if ln.endswith("import " + mod) or f"| {mod}" in ln
        ]
        assert not hit, (
            f"{name} --dry-run 导入了 NN 栈模块 {mod!r}（违反惰性导入约定）:\n"
            + "\n".join(hit[:5])
        )


# ---------------------------------------------------------------------------
# ② 结构性错误必须显式失败（dry-run 不是无脑 exit 0）
# ---------------------------------------------------------------------------


def test_dry_run_rejects_seed_overlap() -> None:
    """训练/holdout 种子区间重叠 = 防泄漏红线被破坏 → exit 2（holdout 落入 train）。"""
    proc = _run_train(
        [str(TRAIN / "prepare_coco.py"), "--dry-run",
         "--holdout-seed0", "860100"]  # 落在默认训练区间 [860001, 870001) 内
    )
    assert proc.returncode == 2, f"种子重叠应 exit 2，得到 {proc.returncode}"
    assert "重叠" in proc.stdout


def test_dry_run_rejects_reverse_seed_overlap() -> None:
    """反向重叠（train 区间落入 holdout 区间）同样拒绝——复核发现的逃逸方向。"""
    proc = _run_train(
        [str(TRAIN / "prepare_coco.py"), "--dry-run",
         "--train-seed0", "960100", "--train-pairs", "100",
         "--holdout-seed0", "960000", "--holdout-pairs", "500"]
    )
    assert proc.returncode == 2, (
        f"反向种子重叠应 exit 2，得到 {proc.returncode}\n{proc.stdout[-2000:]}"
    )
    assert "重叠" in proc.stdout


def test_dry_run_rejects_conflicting_model_args() -> None:
    """--checkpoint 与 --onnx 同时给出 → exit 2（二选一约束）。"""
    proc = _run_train(
        [str(TRAIN / "eval_seg.py"), "--dry-run",
         "--checkpoint", "x.pth", "--onnx", "x.onnx"]
    )
    assert proc.returncode == 2, f"模型二选一冲突应 exit 2，得到 {proc.returncode}"


# ---------------------------------------------------------------------------
# ③ 合成引擎 → COCO RLE 端到端（真实模式小样本，离线，独立解码交叉验证）
# ---------------------------------------------------------------------------


def _rle_decode_independent(rle: dict) -> "object":
    """独立实现的 COCO 列主序（Fortran）未压缩 RLE 解码（不 import beaneye）。"""
    import numpy as np

    h, w = rle["size"]
    flat = np.zeros(h * w, np.uint8)
    pos, val = 0, 0
    for c in rle["counts"]:
        if val:
            flat[pos : pos + c] = 1
        pos += c
        val = 1 - val
    return flat.reshape((w, h)).T


def test_prepare_coco_emit_sample_rle(tmp_path: Path) -> None:
    out = tmp_path / "sample"
    proc = _run_train(
        [str(TRAIN / "prepare_coco.py"),
         "--emit-sample", str(out), "--seg-format", "rle"],
        timeout=600,  # 含 beaneye.synth 冷导入（实测 ~40s 量级）
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]

    import numpy as np

    data = json.loads((out / "_annotations.coco.json").read_text(encoding="utf-8"))
    # 类别表：taxonomy 13 类，id 1..13 连续
    cats = data["categories"]
    assert len(cats) == 13
    assert [c["id"] for c in cats] == list(range(1, 14))
    assert {c["name"] for c in cats} >= {"normal", "black", "mold", "sour"}
    # 成对图像：top + bottom 各 1，512²
    assert len(data["images"]) == 2
    assert {i["side"] for i in data["images"]} == {"top", "bottom"}
    assert all(i["width"] == 512 and i["height"] == 512 for i in data["images"])
    # 标注：RLE 结构 + 独立解码交叉验证 bbox/area
    anns = data["annotations"]
    assert anns, "小样本必须有标注"
    for ann in anns:
        seg = ann["segmentation"]
        assert isinstance(seg, dict) and seg["size"] == [512, 512]
        assert ann["iscrowd"] == 0
        assert 1 <= ann["category_id"] <= 13
        assert ann["bean_id"]
        mask = _rle_decode_independent(seg)
        area = int(mask.sum())
        assert area > 0
        assert int(round(ann["area"])) == area, (
            f"area({ann['area']}) != 掩码像素数({area})——口径不一致"
        )
        ys, xs = np.nonzero(mask)
        x0, y0, w, h = ann["bbox"]
        assert abs(xs.min() - x0) <= 2 and abs(ys.min() - y0) <= 2
        assert abs((xs.max() - xs.min() + 1) - w) <= 3
        assert abs((ys.max() - ys.min() + 1) - h) <= 3
    # 上下两面共享 bean_id（成对真值）
    ids_top = {a["bean_id"] for a in anns if a["image_id"] == 1}
    ids_bot = {a["bean_id"] for a in anns if a["image_id"] == 2}
    assert ids_top and ids_top == ids_bot


# ---------------------------------------------------------------------------
# ④ 复核回归：度量口径（train/_metrics 单元；导入 numpy/cv2/scipy 重量级放最后）
# ---------------------------------------------------------------------------


def _load_metrics():
    """导入 train/_metrics（重量级模块；测试内惰性导入，控制套件前置成本）。"""
    import sys as _sys

    if str(TRAIN) not in _sys.path:
        _sys.path.insert(0, str(TRAIN))
    import _metrics

    return _metrics


def test_prf_rejects_cross_class_matches() -> None:
    """跨类同掩码（IoU=1.0）不得计 TP——复核实测旧口径给出 tp=1/f1=1.0。"""
    import numpy as np

    m = _load_metrics()
    gt = [m.Instance(category_id=1, score=1.0,
                     crop=np.ones((10, 10), dtype=bool), offset=(0, 0))]
    pred = [m.Instance(category_id=5, score=0.9,
                       crop=np.ones((10, 10), dtype=bool), offset=(0, 0))]
    r = m.prf_from_matches(gt, pred)
    assert r["tp"] == 0 and r["fp"] == 1 and r["fn"] == 1
    assert r["f1"] == 0.0
    # 同类同掩码仍应计 TP（不因修复误伤正常匹配）
    pred_ok = [m.Instance(category_id=1, score=0.9,
                          crop=np.ones((10, 10), dtype=bool), offset=(0, 0))]
    r_ok = m.prf_from_matches(gt, pred_ok)
    assert r_ok["tp"] == 1 and r_ok["f1"] == 1.0


def test_counting_mae_relative_error_is_per_tray() -> None:
    """相对误差量纲 = 逐盘 |err|/该盘 gt 数（均值）；总体 MAE÷标注总数是错的。"""
    m = _load_metrics()

    def _tray(n: int, cat: int = 1):
        return [m.Instance(category_id=cat, score=1.0,
                           crop=None, offset=(0, 0)) for _ in range(n)]

    gts = [_tray(300), _tray(300), _tray(300)]
    preds = [_tray(297), _tray(297), _tray(297)]
    # crop=None 仅用于计数统计（不解码掩码）；Instance 契约允许任意 crop
    out = m.counting_mae(gts, preds, bucket_split=300)
    assert out["mae_overall"] == 3.0
    assert out["rel_err_mean"] == pytest.approx(0.01)  # 3/300 每盘；旧错口径为 3/900
    assert out["rel_err_max"] == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# ⑤ 复核回归：外部主源合并一图多粒 → image 条目去重（真实模式小合成，离线）
# ---------------------------------------------------------------------------


def test_prepare_coco_ext_merge_dedup(tmp_path: Path) -> None:
    """1 张外部图 × 3 标注 → 合并后恰 1 条 ext image 记录、3 标注同 image_id。"""
    import cv2
    import numpy as np
    import yaml

    ext_root = tmp_path / "ext"
    ext_root.mkdir()
    cv2.imwrite(str(ext_root / "tray1.png"), np.full((64, 64, 3), 200, np.uint8))
    ext_json = {
        "images": [{"id": 1, "file_name": "tray1.png", "width": 64, "height": 64}],
        "annotations": [
            {"id": k, "image_id": 1,
             "category_id": 1 if k == 1 else 2,
             "segmentation": [[10.0, 10.0, 20.0, 10.0, 20.0, 20.0, 10.0, 20.0]],
             "bbox": [10, 10, 10, 10], "area": 100.0, "iscrowd": 0}
            for k in (1, 2, 3)
        ],
        "categories": [{"id": 1, "name": "normal"}, {"id": 2, "name": "black"}],
    }
    (ext_root / "annotations.json").write_text(
        json.dumps(ext_json, ensure_ascii=False), encoding="utf-8"
    )
    mapping = {"main": {"normal": "normal", "black": "black"}}
    (tmp_path / "mapping.yaml").write_text(
        yaml.safe_dump(mapping, allow_unicode=True), encoding="utf-8"
    )

    out = tmp_path / "ds"
    proc = _run_train(
        [str(TRAIN / "prepare_coco.py"),
         "--ext-coco-json", str(ext_root / "annotations.json"),
         "--ext-image-root", str(ext_root),
         "--mapping-yaml", str(tmp_path / "mapping.yaml"),
         "--mapping-source", "main",
         "--out", str(out),
         "--train-pairs", "1", "--holdout-pairs", "1", "--seg-format", "polygon"],
        timeout=600,  # 含 beaneye.synth 冷导入（~40s 量级）+ 2 对 2048² 合成
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-2000:]

    data = json.loads((out / "train" / "_annotations.coco.json").read_text("utf-8"))
    ext_imgs = [i for i in data["images"] if str(i.get("side", "")) == "ext"]
    assert len(ext_imgs) == 1, (
        f"1 图×3 标注应去重为 1 条 image 记录，得到 {len(ext_imgs)}"
    )
    ext_anns = [a for a in data["annotations"] if a.get("source") == "ext"]
    assert len(ext_anns) == 3
    assert {a["image_id"] for a in ext_anns} == {ext_imgs[0]["id"]}, (
        "ext 标注应全部回指同一条 image 记录"
    )
    # 真实模式（非 dry-run）也复检种子区间：本命令区间不重叠才走到这里
    assert "重叠" not in proc.stdout
