"""一键产出：build_all(seed, outdir) → 评测集 + 夹具 + 确定性 manifest。

manifest 即「seed 固定 → 字节级可复现」的凭据：记录 seed、规模分布与全部
产物的 sha256；evals.m8_generator 以两次独立构建的 manifest 全等做复现断言。
manifest 自身不含时间戳/绝对路径，只含相对路径。
"""
from __future__ import annotations

import json
from pathlib import Path

from benchmark.generator import cases as cases_mod
from benchmark.generator import fixtures as fixtures_mod
from benchmark.generator import templates as tpl
from benchmark.generator.personas import Personas

#: 评测集文件名（任务口径的产出路径）
CASES_FILENAME = "rule_cases.jsonl"
#: 规则层 eval 约定路径（§6 M2）的镜像目录
CASES_MIRROR_SUBDIR = "cases"
FIXTURES_SUBDIR = "fixtures"
MANIFEST_FILENAME = "generation_manifest.json"

_INDENT2 = dict(ensure_ascii=False, sort_keys=True, indent=2)


def _dump_cases(cases: list[dict]) -> str:
    return "".join(
        json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for case in cases)


def build_all(seed: int, outdir: str | Path, config_path: str | None = None) -> dict:
    """产出全部工件并写 manifest，返回 manifest dict（不修改 data/ 之外的目录）。"""
    out = Path(outdir)
    (out / CASES_MIRROR_SUBDIR).mkdir(parents=True, exist_ok=True)
    fixtures_dir = out / FIXTURES_SUBDIR

    cases = cases_mod.build_cases(seed, config_path)
    cases_bytes = _dump_cases(cases).encode("utf-8")
    cases_path = out / CASES_FILENAME
    cases_path.write_bytes(cases_bytes)
    (out / CASES_MIRROR_SUBDIR / CASES_FILENAME).write_bytes(cases_bytes)  # 同字节镜像

    fixtures = fixtures_mod.build_fixtures(seed ^ fixtures_mod.FIXTURE_SEED_SALT,
                                           fixtures_dir, config_path)

    files: dict[str, str] = {
        CASES_FILENAME: _sha(cases_bytes),
        f"{CASES_MIRROR_SUBDIR}/{CASES_FILENAME}": _sha(cases_bytes),
    }
    for entry in fixtures:
        path = out / entry["filename"]
        files[entry["filename"]] = _sha(path.read_bytes())

    manifest = {
        "seed": seed,
        "generator": "benchmark.generator",
        "counts": cases_mod.summarize(cases),
        "files": dict(sorted(files.items())),
        "fixtures": fixtures,
    }
    text = json.dumps(manifest, **_INDENT2) + "\n"
    (out / MANIFEST_FILENAME).write_text(text, encoding="utf-8")
    return manifest


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def canonical_paths(outdir: str | Path) -> dict[str, Path]:
    """规范产出路径（eval 校验用）。"""
    out = Path(outdir)
    return {
        "cases": out / CASES_FILENAME,
        "cases_mirror": out / CASES_MIRROR_SUBDIR / CASES_FILENAME,
        "fixtures": out / FIXTURES_SUBDIR,
        "manifest": out / MANIFEST_FILENAME,
    }


def make_kit(seed: int, config_path: str | None = None) -> tpl.GenKit:
    """供 eval/演示复用的独立 kit（随机流与 build_all 无耦合）。"""
    import random

    return tpl.GenKit(random.Random(seed), Personas(seed, config_path))
