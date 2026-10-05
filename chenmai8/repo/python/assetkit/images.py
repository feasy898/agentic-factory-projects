"""assetkit 压图：sharp 多编码竞标（有损 WebP / 近无损 WebP / 量化 PNG / 常规 PNG）。

"竞标取最小、永不增大"：全部候选都打不过原始字节时保留原图（复制进输出目录，
报告里 encoding="original"，如实不算优化成果）。输出平面文件名，重名自动加序号。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .nodehelper import run_helper


class _NamePool:
    """输出平面命名池：stem 冲突时追加 -2/-3…（同 stem 不同扩展也算冲突，
    避免不同目录同名素材在 optmap 指向上产生歧义）。"""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.used: set[str] = set()

    def base(self, stem: str) -> Path:
        cand = stem
        i = 2
        while cand.lower() in self.used:
            cand = f"{stem}-{i}"
            i += 1
        self.used.add(cand.lower())
        return self.out_dir / cand


def optimize_images(
    materials: list,
    out_dir: Path,
    quality: int = 75,
    max_edge: int = 0,
) -> list[dict]:
    """压图全部 image 素材，返回逐素材结果条目（含原始/优化字节数）。"""
    images = [m for m in materials if m.kind == "image"]
    if not images:
        return []
    pool = _NamePool(out_dir)
    jobs = []
    bases: list[Path] = []
    metas = []
    for m in images:
        base = pool.base(m.src.stem)
        bases.append(base)
        jobs.append({
            "id": len(jobs),
            "src": str(m.src),
            "outBase": str(base),
        })
        metas.append(m)

    payload = {"quality": int(quality), "maxEdge": int(max_edge), "jobs": jobs}
    resp = run_helper(payload)
    by_id = {r.get("id"): r for r in resp.get("results", [])}

    entries: list[dict] = []
    for i, m in enumerate(metas):
        r = by_id.get(i)
        if r is None:
            entries.append({"key": m.key, "src": str(m.src), "kind": "image",
                            "status": "failed", "note": "助手无该 job 结果"})
            continue
        if not r.get("ok"):
            entries.append({"key": m.key, "src": str(m.src), "kind": "image",
                            "status": "failed", "note": r.get("reason", "未知失败")})
            continue
        chosen = r["chosen"]
        if chosen["bytes"] >= r["originalBytes"]:
            # 竞标全输：保留原图（复制进输出目录，保持自包含），如实记录。
            out_file = Path(str(bases[i]) + m.src.suffix.lower())
            shutil.copyfile(m.src, out_file)
            entries.append({
                "key": m.key, "src": str(m.src), "kind": "image",
                "status": "kept-original",
                "out": out_file.name, "encoding": "original",
                "originalBytes": r["originalBytes"], "optimizedBytes": r["originalBytes"],
                "reductionPct": 0.0,
                "width": r.get("width"), "height": r.get("height"),
                "candidates": r.get("candidates", []),
                "note": "全部候选编码不小于原始字节，保留原图" + (f"；{'；'.join(r.get('notes') or [])}" if r.get("notes") else ""),
            })
            continue
        reduction = round((1 - chosen["bytes"] / r["originalBytes"]) * 100, 1)
        entries.append({
            "key": m.key, "src": str(m.src), "kind": "image",
            "status": "optimized",
            "out": Path(chosen["out"]).name, "encoding": chosen["encoding"],
            "originalBytes": r["originalBytes"], "optimizedBytes": chosen["bytes"],
            "reductionPct": reduction,
            "width": r.get("width"), "height": r.get("height"),
            "alpha": r.get("alpha"),
            "candidates": r.get("candidates", []),
            "note": "；".join(r.get("notes") or []),
        })
    return entries
