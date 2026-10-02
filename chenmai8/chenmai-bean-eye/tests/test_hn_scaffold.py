"""HN-Robusta v0.1 采集脚手架 eval：目录/模板存在性 + sorting_log 列头完整性。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_hn_scaffold.py -q

覆盖（采集操作卡线交付件，离线、无硬件依赖）：
- data/datasets/hn_robusta/v0.1/ 下 images/masks/meta 三目录与逐类子目录
  （类 key 以 configs/taxonomy.yaml 为唯一真源，13 类）存在；
- 三份 README 与 meta/sorting_log.md、meta/photo_log.md 模板存在；
- sorting_log 模板列头含操作卡要求的最小列集（日期/操作人/类key/粒数/疑难点），
  且 13 个 taxonomy key 逐个出现在模板预置行中（防类 key 抄错/漏行）；
- 操作卡 docs/采集操作卡-v0.1.md 在位。
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "datasets" / "hn_robusta" / "v0.1"
TAXONOMY = ROOT / "configs" / "taxonomy.yaml"
SORTING_LOG = DATASET / "meta" / "sorting_log.md"


def _taxonomy_keys() -> list[str]:
    """从 configs/taxonomy.yaml 取全部类 key（契约单一真源）。"""
    cfg = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    keys = list(cfg["classes"].keys())
    assert len(keys) == 13, f"taxonomy 类数应为 13，得到 {len(keys)}"
    return keys


def test_scaffold_directories_exist() -> None:
    """images/masks/meta 三目录 + 逐类子目录（images 含 size_trays）全在位。"""
    for sub in ("images", "masks", "meta"):
        assert (DATASET / sub).is_dir(), f"缺目录 {sub}/"
    keys = _taxonomy_keys()
    for key in keys:
        assert (DATASET / "images" / key).is_dir(), f"缺 images/{key}/"
        assert (DATASET / "masks" / key).is_dir(), f"缺 masks/{key}/"
    assert (DATASET / "images" / "size_trays").is_dir(), "缺 images/size_trays/（大中小全盘照）"


def test_template_files_exist() -> None:
    """三份目录 README + 分堆/拍摄台账模板 + 操作卡在位。"""
    for rel in (
        "images/README.md",
        "masks/README.md",
        "meta/README.md",
        "meta/sorting_log.md",
        "meta/photo_log.md",
    ):
        assert (DATASET / rel).is_file(), f"缺模板文件 {rel}"
    assert (ROOT / "docs" / "采集操作卡-v0.1.md").is_file(), "缺 docs/采集操作卡-v0.1.md"


def test_sorting_log_header_columns() -> None:
    """sorting_log 模板表头含最小列集：日期/操作人/类key/粒数/疑难点。"""
    header = next(
        line for line in SORTING_LOG.read_text(encoding="utf-8").splitlines() if line.startswith("| 日期")
    )
    cells = [c.strip() for c in header.strip("|").split("|")]
    for required in ("日期", "操作人", "类key", "粒数", "疑难点"):
        assert required in cells, f"sorting_log 表头缺列「{required}」，实际列：{cells}"


def test_sorting_log_lists_all_taxonomy_keys() -> None:
    """13 个 taxonomy key 逐个出现在 sorting_log 预置行（防 key 抄错/漏行）。"""
    text = SORTING_LOG.read_text(encoding="utf-8")
    for key in _taxonomy_keys():
        assert f"| {key} |" in text, f"sorting_log 缺类 key「{key}」的预置行"
