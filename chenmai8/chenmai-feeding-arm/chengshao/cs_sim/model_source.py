"""机械模型文件定位与回退链解析（开发指令 §5.1 回退链）。

回退链（逐级降级，不阻塞）：
  1) ``mjcf``          —— 本地参考件库中的 MJCF 机械模型文件（由本引擎直接加载）；
  2) ``urdf_mujoco``   —— 同目录 URDF（由本引擎按 URDF 子集直接加载）；
  3) ``chain_builtin`` —— 内置名义运动学链（ikpy 链，常数内置于本模块，
                          无需任何模型文件，最后手段）。

定位纪律（命名检查相关）：本模块代码中不出现任何上游参考件的项目/型号名；
发现一律通过中性通配与通用规则完成（``Simulation/*/`` 目录下优先
``*_new_calib`` 且非 scene/camera 变体的文件）。上游版本锁定见
``reports/upstream_lock.md``。

发现的候选根：当前工作目录及各级上级目录中的 ``_vendor/`` 本地参考件目录
（gitignore，不入库）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "DEFAULT_MODEL_SOURCE",
    "MODEL_TIER_MJCF",
    "MODEL_TIER_URDF",
    "MODEL_TIER_CHAIN_BUILTIN",
    "VENDOR_DIR_NAME",
    "ModelResolution",
    "file_sha256_prefix",
    "discover_model_file",
]

# "auto"：触发回退链自动发现（冻结签名 load_arm(physics_model_path: str) 的缺省语义）
DEFAULT_MODEL_SOURCE = "auto"

MODEL_TIER_MJCF = "mjcf"
MODEL_TIER_URDF = "urdf_mujoco"
MODEL_TIER_CHAIN_BUILTIN = "chain_builtin"

VENDOR_DIR_NAME = "_vendor"


class ModelResolution(NamedTuple):
    """回退链解析结果。``path`` 为 None 表示使用内置名义链（tier 3）。"""

    tier: str
    path: Path | None
    note: str


def file_sha256_prefix(path: Path, n: int = 16) -> str:
    """文件内容 SHA-256 前 n 位十六进制（用于报告中无泄漏地锁定模型版本）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def _candidate_roots() -> list[Path]:
    """可能的 _vendor 根：包所在目录向上、当前工作目录向上（各至多 4 级），
    加上工作区外的集中参考目录（安全门禁要求克隆移出工作区后的官方新址）。"""
    roots: list[Path] = []
    here = Path(__file__).resolve()
    for base in [here.parents[1], Path.cwd().resolve()]:  # 包根(chengshao/) 与 cwd
        cur = base
        for _ in range(4):
            roots.append(cur / VENDOR_DIR_NAME)
            if cur.parent == cur:
                break
            cur = cur.parent
    # 工作区外集中参考目录（存在才加入）
    for external in (Path("D:/upstream-refs/robot-vendor"),
                     Path("D:/upstream-refs/robot-vendor/_vendor")):
        if external.is_dir():
            roots.append(external)
    # 环境变量显式覆盖（最高优先，放最前）
    import os
    env_root = os.environ.get("CS_VENDOR_ROOT")
    if env_root:
        roots.insert(0, Path(env_root))
    # 去重保序
    seen: set[Path] = set()
    uniq: list[Path] = []
    for r in roots:
        key = r.resolve()
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def _score(name: str) -> tuple[int, int, int, str]:
    """候选文件评分（值越小越优先）：new_calib > 旧标定；非 camera 变体优先；名定序。"""
    return (
        0 if "new_calib" in name else (1 if "calib" in name else 2),
        1 if "camera" in name else 0,
        1 if "leader" in name else 0,
        name,
    )


def _pick(candidates: list[Path]) -> Path | None:
    """从候选中选机械臂模型文件：排除 scene 汇总与参数表，其余按评分取最优。"""
    usable = [
        p
        for p in candidates
        if not p.name.startswith("scene") and "joints_properties" not in p.name
    ]
    if not usable:
        return None
    return sorted(usable, key=lambda p: _score(p.name))[0]


def discover_model_file() -> ModelResolution:
    """按回退链在本地参考件目录中发现机械模型文件。

    返回 ``(tier, path|None, note)``；前两级都失败时返回内置名义链。
    """
    for vendor in _candidate_roots():
        if not vendor.is_dir():
            continue
        # 优先参考件库的标准布局：_vendor/<库>/Simulation/<型号>/<文件>
        for pattern, tier in [
            ("*/Simulation/*/*.xml", MODEL_TIER_MJCF),
            ("*/Simulation/*/*.urdf", MODEL_TIER_URDF),
        ]:
            candidates = sorted(vendor.glob(pattern))
            pick = _pick(candidates)
            if pick is not None:
                return ModelResolution(
                    tier=tier,
                    path=pick,
                    note=f"discovered under {VENDOR_DIR_NAME}/ (neutral glob: {pattern})",
                )
    return ModelResolution(
        tier=MODEL_TIER_CHAIN_BUILTIN,
        path=None,
        note="no local vendor model found; falling back to built-in nominal chain",
    )
