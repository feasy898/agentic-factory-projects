"""CLI：python -m benchmark.generator [--seed N] [--outdir DIR] [--config PATH]。

默认在仓库根产出 data/（评测集 + 15 份夹具 + manifest）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchmark.generator import DEFAULT_SEED, build
from common.config import REPO_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="合成测评集/夹具生成器（M8·T1.1）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"随机种子（默认 {DEFAULT_SEED}，固定即可复现）")
    parser.add_argument("--outdir", default=str(REPO_ROOT / "data"),
                        help="输出目录（默认 <repo>/data）")
    parser.add_argument("--config", default=None,
                        help="合成语料依赖坐标配置（默认 config/synthetic_corpus.yaml）")
    args = parser.parse_args(argv)

    manifest = build.build_all(args.seed, Path(args.outdir), args.config)
    counts = manifest["counts"]
    print(f"seed={manifest['seed']} outdir={Path(args.outdir).resolve()}")
    print(f"cases={counts['cases_total']} "
          f"by_grading={counts['cases_by_grading']} "
          f"templates={len(counts['templates'])} "
          f"perturbations={len(counts['perturbations'])}")
    print(f"whitelist_cases={counts['whitelist_cases']} "
          f"reject_cases={counts['reject_cases']} "
          f"classification_cases={counts['classification_cases']}")
    print(f"files={len(manifest['files'])} fixtures={len(manifest['fixtures'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
