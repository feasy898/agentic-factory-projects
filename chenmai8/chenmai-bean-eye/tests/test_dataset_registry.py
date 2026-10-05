#!/usr/bin/env python3
"""数据集入库线 · 离线体检（tests/test_dataset_registry.py）。

纯离线（无网络/无摄像头），校验 data/datasets/ 的入库纪律与产物完整性：

  ① 登记册存在且只用中性代号（四集代号齐全、红线指针指到外部登记文件；
     中性名扫描复用 scripts/gate_d3.py 的上游名模式——本文件自身是 git
     跟踪文件，绝不内嵌上游专有名词字面量，与 gate_d3/D9 同一套清单）；
  ② 四份 mapping.yaml：结构对齐 train/prepare_coco.py --mapping-yaml 语义
     （顶层键=中性代号，内层 {上游类: taxonomy key|null}），所有非 null
     目标键 ∈ configs/taxonomy.yaml 的 13 类；
  ③ 已下载数据集（以 manifest.json 存在为准）：目录结构完整
     （content/ + _annotations.coco.json + SHA256SUMS + manifest）、
     manifest 图数与磁盘图片文件数逐 split 一致、manifest 小文件抽查过
     SHA256SUMS、通用 Universe 模式 manifest 只持中性代号（不含上游坐标键）、
     映射表覆盖数据集实际全部类别（防类别漂移静默丢标注）；
  ④ 下载器 --only universe 通用模式参数可离线解析（协议本体走真实网络
     时不在本测试范围）。

数据未下载的集：结构检查自动 skip（数据本体按 .gitignore 不入库，
manifest 缺失 = 该机未下载，不是错误）；登记册与四份 mapping.yaml 是本线
交付物，缺失按 FAIL 处理。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = REPO_ROOT / "data" / "datasets"
REGISTRY_PATH = DATASETS_DIR / "dataset_registry.md"
TAXONOMY_PATH = REPO_ROOT / "configs" / "taxonomy.yaml"
DOWNLOAD_SCRIPT = REPO_ROOT / "scripts" / "download_datasets.py"

# 四集中性代号（数据集入库线约定；真实坐标只在外部登记文件）
EXT_CODES = ("ext-main", "ext-rseg", "ext-rgreen", "ext-scaa17")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# 通用 Universe 模式 manifest 里不得出现的上游坐标键（中性名纪律）；
# ext-main 走 --only dcv 既有模式，其 manifest 的来源键为既定行为（豁免，
# 且数据本体/manifest 本就按 .gitignore 不入库）。
UNIVERSE_MANIFEST_FORBIDDEN_KEYS = {"api_workspace", "api_project", "source_url"}


def _load_taxonomy_keys() -> set[str]:
    data = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    keys = set((data.get("classes") or {}).keys())
    assert len(keys) == 13, f"taxonomy classes 应为 13 类，得到 {len(keys)}"
    return keys


TAXONOMY_KEYS = _load_taxonomy_keys()


def _load_gate_d3():
    """导入 scripts/gate_d3.py 复用其上游名模式（本测试文件不内嵌字面量）。"""
    spec = importlib.util.spec_from_file_location(
        "beaneye_gate_d3_for_registry_test", DOWNLOAD_SCRIPT.parent / "gate_d3.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GATE_D3 = _load_gate_d3()
_NEUTRAL_SCAN_RE = re.compile("|".join(_GATE_D3.UPSTREAM_NAME_PATTERNS), re.IGNORECASE)


def _mapping_path(code: str) -> Path:
    return DATASETS_DIR / code / "mapping.yaml"


def _load_mapping(code: str) -> dict:
    data = yaml.safe_load(_mapping_path(code).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{code}/mapping.yaml 顶层必须是映射"
    assert code in data, f"{code}/mapping.yaml 缺顶层来源键 {code!r}（现有: {sorted(data)}）"
    return data[code]


def _coco_jsons(content_dir: Path) -> list[Path]:
    return sorted(content_dir.rglob("_annotations.coco.json"))


def _image_files(split_dir: Path) -> int:
    return sum(
        1 for p in split_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    ) if split_dir.is_dir() else 0


# ---------------------------------------------------------------------------
# ① 登记册
# ---------------------------------------------------------------------------


def test_registry_exists_with_redline_and_neutral_codes():
    assert REGISTRY_PATH.is_file(), f"登记册缺失: {REGISTRY_PATH}（数据集入库线交付物）"
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    for code in EXT_CODES:
        assert code in text, f"登记册缺中性代号 {code}"
    # 红线指针：真实 URL/账号只登记在外部登记文件（按文件名指认，不含上游名）
    assert "dataset_sources.txt" in text, "登记册缺外部登记文件红线指针"
    assert "PENDING" in text or "待生成" in text or "待" in text  # 状态标记存在（宽松）
    hits = _NEUTRAL_SCAN_RE.findall(text)
    assert not hits, f"登记册出现上游名（违中性名纪律）: {hits[:10]}"


# ---------------------------------------------------------------------------
# ② mapping.yaml（四份均为本线交付物，缺失按 FAIL）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", EXT_CODES)
def test_mapping_yaml_targets_in_taxonomy(code):
    node = _load_mapping(code)
    assert isinstance(node, dict) and node, f"{code} 映射为空"
    unmapped = [k for k, v in node.items() if v is None]
    mapped = {k: v for k, v in node.items() if v is not None}
    assert mapped, f"{code} 映射没有任何非 null 目标（全排除集无法并入训练）"
    for upstream, target in mapped.items():
        assert target in TAXONOMY_KEYS, (
            f"{code}: 上游 {upstream!r} 的目标 {target!r} 不在 taxonomy 13 类内"
        )
    # null 与非 null 不冲突；null 数量记录即可（理由在注释里，不做内容断言）
    assert len(node) == len(mapped) + len(unmapped)


@pytest.mark.parametrize("code", EXT_CODES)
def test_mapping_yaml_neutral_naming(code):
    text = _mapping_path(code).read_text(encoding="utf-8")
    hits = _NEUTRAL_SCAN_RE.findall(text)
    assert not hits, f"{code}/mapping.yaml 出现上游名: {hits[:10]}"


# ext-main 页面实抓类别表（2026-10-02 web_reader，西语原样；类名是数据词表
# 而非上游项目名，可入 tracked 测试）。守护点：映射键必须逐字对齐——曾发生按
# 旧 README 英译记录配键（broca 误译 brocade）导致 11/12 键不命中。
# 2026-10-03 下载实测：导出 v8 比页面类表多一个容器类 coffee-beans（已 null 映射）。
EXT_MAIN_PAGE_CLASSES = frozenset({
    "agrio", "broca", "caracolillo", "coffee-beans", "concha", "elefante",
    "helado", "negro", "normal", "oreja", "partido", "seca", "triangulo",
})


def test_ext_main_mapping_keys_match_page_classes():
    node = _load_mapping("ext-main")
    assert set(node) == EXT_MAIN_PAGE_CLASSES, (
        "ext-main 映射键须与页面核验的西语类表逐字一致 "
        f"（缺: {sorted(EXT_MAIN_PAGE_CLASSES - set(node))}，"
        f"多: {sorted(set(node) - EXT_MAIN_PAGE_CLASSES)}）"
    )


# ---------------------------------------------------------------------------
# ③ 已下载数据集结构与一致性（未下载自动 skip）
# ---------------------------------------------------------------------------


def _require_downloaded(code: str) -> tuple[Path, dict]:
    ds_dir = DATASETS_DIR / code
    manifest_path = ds_dir / "manifest.json"
    if not manifest_path.is_file():
        pytest.skip(f"{code} 未在本机下载（无 manifest.json）——数据本体不入库")
    return ds_dir, json.loads(manifest_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("code", EXT_CODES)
def test_downloaded_dataset_structure_and_counts(code):
    ds_dir, manifest = _require_downloaded(code)
    content = ds_dir / "content"
    assert content.is_dir(), f"{code}: 缺 content/"
    ann_jsons = _coco_jsons(content)
    assert ann_jsons, f"{code}: content/ 下无 _annotations.coco.json"

    # manifest 中性代号一致性（internal_name 必须=目录名=登记代号）
    assert manifest.get("internal_name") == code, (
        f"{code}: manifest.internal_name={manifest.get('internal_name')!r} 与目录名不符"
    )
    # 通用 Universe 模式 manifest 不得携带上游坐标键（ext-main 走 dcv 既有模式，豁免）
    if code != "ext-main":
        bad_keys = UNIVERSE_MANIFEST_FORBIDDEN_KEYS & set(manifest)
        assert not bad_keys, f"{code}: manifest 出现上游坐标键 {bad_keys}（违中性名纪律）"

    # SHA256SUMS 抽查：manifest.json + mapping.yaml + 各 _annotations.coco.json
    sums_path = ds_dir / "SHA256SUMS"
    assert sums_path.is_file(), f"{code}: 缺 SHA256SUMS"
    sums: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, rel = line.split("  ", 1)
            sums[rel] = digest
    spot = [ds_dir / "manifest.json", _mapping_path(code), *ann_jsons]
    for p in spot:
        rel = p.relative_to(ds_dir).as_posix()
        assert rel in sums, f"{code}: SHA256SUMS 缺条目 {rel}"
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual == sums[rel], f"{code}: SHA256 不符 {rel}"

    # 逐 split：manifest 图数 == COCO json 图数 == 磁盘图片文件数
    validation_splits = (manifest.get("coco_validation") or {}).get("splits") or {}
    total_from_manifest = 0
    for ann_path in ann_jsons:
        split = ann_path.parent.name or "."
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        n_images = len(data.get("images", []))
        on_disk = _image_files(ann_path.parent)
        m_split = validation_splits.get(split) or {}
        assert m_split.get("images", n_images) == n_images, (
            f"{code}/{split}: manifest 图数 {m_split.get('images')} != COCO json {n_images}"
        )
        assert on_disk == n_images, (
            f"{code}/{split}: 磁盘图片 {on_disk} 张 != COCO json {n_images} 张"
        )
        total_from_manifest += n_images
    totals = manifest.get("totals") or {}
    assert totals.get("images", total_from_manifest) == total_from_manifest, (
        f"{code}: manifest.totals.images={totals.get('images')} != 逐 split 和 {total_from_manifest}"
    )


@pytest.mark.parametrize("code", EXT_CODES)
def test_downloaded_dataset_categories_all_in_mapping(code):
    """防类别漂移：数据集实际类别必须全部出现在映射表键里。

    映射缺失的类别会在 merge 时被静默跳过（只进 stats.skipped_categories）；
    若确要整类排除，也应在 mapping.yaml 显式写 null 行，让排除有据可查。
    """
    ds_dir, _manifest = _require_downloaded(code)
    mapping = _load_mapping(code)
    actual_cats: set[str] = set()
    for ann_path in _coco_jsons(ds_dir / "content"):
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        actual_cats |= {str(c.get("name")) for c in data.get("categories", [])}
    missing = sorted(actual_cats - set(mapping))
    assert not missing, f"{code}: 数据集实际类别未入映射表（将静默跳过）: {missing}"


# ---------------------------------------------------------------------------
# ④ 下载器 --only universe 通用模式（离线参数解析）
# ---------------------------------------------------------------------------


def _load_downloader():
    spec = importlib.util.spec_from_file_location(
        "beaneye_download_datasets_for_test", DOWNLOAD_SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_downloader_universe_mode_arg_parsing():
    dl = _load_downloader()
    parser = dl.build_parser()
    args = parser.parse_args(
        ["--only", "universe", "--universe", "some-ws/some-project",
         "--out", "data/datasets/some-code", "--format", "coco"]
    )
    assert args.only == "universe" and args.universe == "some-ws/some-project"
    assert dl.parse_universe_arg(args.universe) == ("some-ws", "some-project")
    # 非法形态必须被拒绝（SystemExit）
    for bad in ("only-ws", "a/b/c", "ws/ has space/x", ""):
        with pytest.raises(SystemExit):
            dl.parse_universe_arg(bad)
    # universe 模式缺 --out 必须报用法错误
    args_no_out = parser.parse_args(["--only", "universe", "--universe", "a/b"])
    with pytest.raises(SystemExit):
        dl.download_universe(args_no_out)


def test_dcv_mode_internal_name_follows_out_dir():
    """HIGH 复核修复回归：dcv 模式显式 --out 时 internal_name=目录名，
    使 ext-main 的 manifest 一致性断言（internal_name==目录名）可满足；
    缺省（无 --out）保持 v1 的 dcv 命名。"""
    dl = _load_downloader()
    out_dir, internal, sample_dir = dl.resolve_dcv_layout(
        argparse.Namespace(out="data/datasets/ext-main")
    )
    assert internal == "ext-main" and out_dir.name == "ext-main"
    assert sample_dir.name == "ext-main_sample"
    out_dir2, internal2, sample_dir2 = dl.resolve_dcv_layout(argparse.Namespace(out=None))
    assert internal2 == "dcv" and out_dir2.name == "dcv"
    assert sample_dir2.name == "dcv_sample"
