#!/usr/bin/env python3
"""批12 真实池构建（build_b12_real_pools.py）。

1) allvar-normal-jpg/train/normal/：allvar-normal/train 下 **13 个 Arabica
   品种目录**（A-001..A-013）全部 PNG 拍平为 normal 单类，PNG→JPG(q95)
   （retrain_real.py scan_real_root 只接受 .jpg）。
   **R-001-Robusta 1006 张剔除**：经 md5 全量比对与
   b12-dl/robusta_b12/train 1006 张逐一相同（1006/1006），由
   zenodo-robusta-normal-b12 根单独入训，避免同一批图双计（计数/loss 权重）。
   已验证 allvar 全部 14367 张与 robusta val 252 张 md5 零重叠 → zenodo
   holdout 干净。
2) zenodo-robusta-normal-b12/{train,valid}/normal/：train = 复用
   zenodo-normal-b11/train/normal 的 1006 张 JPG(q95)（同源 tarball
   sha256=4e83f37a…）；**valid/normal 置空** —— val 252 张留作 zenodo
   holdout，不入训练、不入选型 valid（批11 曾入，本批排除，如实注记）。

输出各池计数；期望 allvar=13361 / robusta-train=1006，不符 exit 2。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image

ALLVAR_SRC = Path("/data/coffee-bean/allvar-normal/train")
ALLVAR_DST = Path("/data/coffee-bean/allvar-normal-jpg")
ROB_JPG_SRC = Path("/data/coffee-bean/zenodo-normal-b11/train/normal")
ROB_DST = Path("/data/coffee-bean/zenodo-robusta-normal-b12")
EXPECT_ALLVAR = 13361
EXPECT_ROB = 1006


def build_allvar() -> int:
    out = ALLVAR_DST / "train" / "normal"
    if out.exists():
        shutil.rmtree(ALLVAR_DST)
    out.mkdir(parents=True)
    varieties = sorted(d for d in ALLVAR_SRC.iterdir()
                       if d.is_dir() and d.name.startswith("A-"))
    n = 0
    for var in varieties:
        for png in sorted(var.glob("*.png")):
            im = Image.open(png).convert("RGB")
            im.save(out / (png.stem + ".jpg"), quality=95)
            n += 1
    # 空 valid/normal：retrain_real.py 扫描要求 split 目录存在；该池不参与选型 valid
    (ALLVAR_DST / "valid" / "normal").mkdir(parents=True)
    print(f"[allvar] 品种 {len(varieties)} 个 → {out} → {n} 张 JPG（期望 {EXPECT_ALLVAR}）")
    return n


def build_robusta() -> int:
    if ROB_DST.exists():
        shutil.rmtree(ROB_DST)
    tr = ROB_DST / "train" / "normal"
    va = ROB_DST / "valid" / "normal"
    tr.mkdir(parents=True)
    va.mkdir(parents=True)
    n = 0
    for jpg in sorted(ROB_JPG_SRC.glob("*.jpg")):
        shutil.copy2(jpg, tr / jpg.name)
        n += 1
    print(f"[robusta] train {n} 张 JPG（期望 {EXPECT_ROB}）；valid/normal 置空（val 252 留作 holdout）")
    return n


def main() -> int:
    n_allvar = build_allvar()
    n_rob = build_robusta()
    ok = (n_allvar == EXPECT_ALLVAR and n_rob == EXPECT_ROB)
    print(f"[总计] allvar-jpg {n_allvar} + robusta-train {n_rob}"
          f" → {'OK' if ok else 'MISMATCH'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
