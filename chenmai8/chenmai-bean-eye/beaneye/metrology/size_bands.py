"""M8 计量 · 大中小筛段（轨2）：配置加载 + 逐粒归属 + 直方图聚合。

数据源 ``configs/size_bands.yaml``（口径与来源见该文件头）::

    bands: [{key: large, min_screen: 17, max_screen: null, ...}, ...]

**双域语义（重要）**：配置按**整目数**含上、下界声明（15-16 目 = medium）；
加载器校验整目数域相接（下一段 ``min == 上一段 max + 1``）后，换算为连续
目数域的**左闭右开**区间 ``[min, max+1)``（首段 -inf 起、尾段 +inf 止）。
因此连续目数 16.99 → medium、17.00 → large，整目数 16 → medium、17 →
large——逐粒归属传整目数（与 ``sieve_hist`` 同源），边界语义可直接测。

入口：
- :func:`load_size_bands`：加载并校验筛段配置；
- :func:`band_of_screen`：目数（int 或 float）→ 筛段 key；
- :func:`size_band_histogram`：逐粒归属 + 分段计数 + 占比（"每粒归属+占比"）；
  逐粒目数用与 ``core.measure`` 完全相同的口径（两面 ``eq_diameter_mm``
  均值 → ``screen_of``），因此分段直方与 ``Measurements.sieve_hist``
  聚合结果恒一致（有测试钉住）；
- :func:`aggregate_sieve_hist`：把既有 ``sieve_hist`` 直接聚合成筛段直方
  （供精品/普通判定层从 Measurements 出发消费，无需逐粒重算）。

契约兼容：本模块是**新增输出**，不改 ``Measurements`` 既有字段语义；
直方图可独立消费，也可（在契约增补分支下）作为新字段挂到 Measurements。
只依赖 PyYAML 与标准库；失败抛 :class:`SizeBandError`。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

from beaneye.metrology.core import screen_of
from beaneye.schemas import PairedBean

__all__ = [
    "DEFAULT_SIZE_BANDS_PATH",
    "SizeBandError",
    "SizeBand",
    "SizeBands",
    "SizeBandHistogram",
    "load_size_bands",
    "band_of_screen",
    "size_band_histogram",
    "aggregate_sieve_hist",
]

DEFAULT_SIZE_BANDS_PATH = Path(__file__).resolve().parents[2] / "configs" / "size_bands.yaml"

_BAND_KEYS = ("key", "min_screen", "max_screen", "zh", "en", "vi")


class SizeBandError(ValueError):
    """筛段配置缺失 / 非法 / 区间不无缝时抛出。"""


@dataclass(frozen=True)
class SizeBand:
    """单个筛段。

    ``min_screen``/``max_screen`` 是配置里的**整目数含界**声明（None = 该侧
    开，只允许首/尾段）；``lo``/``hi`` 是换算后的连续目数域**左闭右开**界
    （``[min, max+1)``；首段 lo=-inf、尾段 hi=+inf）。
    """

    key: str
    min_screen: int | None
    max_screen: int | None
    zh: str
    en: str
    vi: str
    lo: float
    hi: float  # 连续域右开边界

    def contains(self, screen: float) -> bool:
        """目数是否落在本段（连续域左闭右开 [lo, hi)）。"""
        return self.lo <= screen < self.hi


@dataclass(frozen=True)
class SizeBands:
    """一份已校验的筛段配置（区间无缝且互不重叠，覆盖全部目数域）。"""

    bands: tuple[SizeBand, ...]
    source: str = "configs/size_bands.yaml"
    screen_mm_table: dict[int, float] | None = None  # ICO 公称孔径对照（展示用）

    def band_of(self, screen: float) -> str:
        """目数 → 筛段 key；无命中时抛 :class:`SizeBandError`（配置应无缝）。"""
        for b in self.bands:
            if b.contains(screen):
                return b.key
        raise SizeBandError(f"目数 {screen!r} 未落入任何筛段（配置区间未无缝覆盖？source={self.source}）")

    def keys(self) -> list[str]:
        """筛段 key 列表（配置序）。"""
        return [b.key for b in self.bands]


@dataclass(frozen=True)
class SizeBandHistogram:
    """大中小直方图：逐粒归属 + 分段计数 + 占比。

    ``per_bean[i]`` 与输入豆列表按序对齐（"每粒归属"；双面皆 None 的占位豆
    记 ""）；``frac`` 为 0-1 占比（总和为 1，空盘为全 0）；``bean_count``
    只计有效观测粒（与 ``Measurements.bean_count`` 同口径）。
    """

    per_bean: tuple[str, ...]
    hist: dict[str, int]
    frac: dict[str, float]
    bean_count: int


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def _int_or_none(v: object, where: str) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise SizeBandError(f"{where} 必须是整数或 null，得到 {v!r}")
    return int(v)


def load_size_bands(path: str | Path | None = None) -> SizeBands:
    """加载筛段配置（缺省读 ``configs/size_bands.yaml``）。

    校验：bands 非空、键集合合法、key 唯一、min/max 为整目数（两侧开只允许
    出现在首/尾段）、整目数域相接（下一段 min = 上一段 max + 1）；非法抛
    :class:`SizeBandError`。
    """
    p = Path(path) if path is not None else DEFAULT_SIZE_BANDS_PATH
    if not p.is_file():
        raise SizeBandError(f"筛段配置文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise SizeBandError(f"筛段 YAML 解析失败: {p}\n{e}") from e
    if not isinstance(raw, dict):
        raise SizeBandError(f"筛段 YAML 顶层必须是映射: {p}")

    bands_raw = raw.get("bands")
    if not isinstance(bands_raw, list) or not bands_raw:
        raise SizeBandError(f"`bands` 必须是非空列表（source={p}）")

    bands: list[SizeBand] = []
    seen: set[str] = set()
    for i, item in enumerate(bands_raw):
        if not isinstance(item, dict):
            raise SizeBandError(f"bands[{i}] 必须是映射（source={p}）")
        missing = [k for k in _BAND_KEYS if k not in item]
        if missing:
            raise SizeBandError(f"bands[{i}] 缺少键: {missing}（source={p}）")
        extra = [k for k in item if k not in _BAND_KEYS]
        if extra:
            raise SizeBandError(f"bands[{i}] 存在未知键: {extra}（source={p}）")
        key = item["key"]
        if not isinstance(key, str) or not key.strip():
            raise SizeBandError(f"bands[{i}].key 必须是非空字符串（source={p}）")
        if key in seen:
            raise SizeBandError(f"bands[{i}].key 重复: {key!r}（source={p}）")
        seen.add(key)
        lo = _int_or_none(item["min_screen"], f"bands[{i}].min_screen (source={p})")
        hi = _int_or_none(item["max_screen"], f"bands[{i}].max_screen (source={p})")
        if lo is not None and hi is not None and lo > hi:
            raise SizeBandError(f"bands[{i}] 区间倒置: [{lo}, {hi}]（source={p}）")
        bands.append(
            SizeBand(
                key=key,
                min_screen=lo,
                max_screen=hi,
                zh=str(item["zh"]),
                en=str(item["en"]),
                vi=str(item["vi"]),
                lo=float("-inf") if lo is None else float(lo),
                hi=float("inf") if hi is None else float(hi + 1),  # 整域含界 → 连续域右开
            )
        )

    # 整目数域必须从 -inf 无缝相接到 +inf：恰一段 min 为 null（-inf 起）、
    # 恰一段 max 为 null（+inf 止）、按 min 排序后相邻两段
    # 「下一段 min == 上一段 max + 1」（目数是整数，相接即无洞）。
    # 配置文件可按任意顺序书写（本仓从大到小），校验在排序视图上做。
    ordered = sorted(bands, key=lambda b: (b.min_screen is not None, b.min_screen or 0))
    n_open_lo = sum(1 for b in bands if b.min_screen is None)
    n_open_hi = sum(1 for b in bands if b.max_screen is None)
    if n_open_lo != 1 or ordered[0].min_screen is not None:
        raise SizeBandError(f"必须恰有一段 min_screen 为 null（覆盖 -inf），得到 {n_open_lo} 段（source={p}）")
    if n_open_hi != 1 or ordered[-1].max_screen is not None:
        raise SizeBandError(f"必须恰有一段 max_screen 为 null（覆盖 +inf），得到 {n_open_hi} 段（source={p}）")
    for a, b in zip(ordered, ordered[1:]):
        if a.max_screen is None:
            raise SizeBandError(f"段 {a.key!r} max_screen 为开，后续段 {b.key!r} 不可达（source={p}）")
        if b.min_screen is None or b.min_screen != a.max_screen + 1:
            raise SizeBandError(
                f"筛段整目数域不无缝：{a.key!r} 上界 {a.max_screen} 与 {b.key!r} "
                f"下界 {b.min_screen} 不相接（应相差 1，source={p}）"
            )

    table_raw = raw.get("screen_mm_table")
    table: dict[int, float] | None = None
    if table_raw is not None:
        if not isinstance(table_raw, dict):
            raise SizeBandError(f"`screen_mm_table` 必须是映射（source={p}）")
        table = {}
        for k, v in table_raw.items():
            try:
                sk = int(k)
            except (TypeError, ValueError):
                raise SizeBandError(f"`screen_mm_table` 键必须是目数整数: {k!r}（source={p}）") from None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or v <= 0:
                raise SizeBandError(f"`screen_mm_table[{k}]` 必须是正数（source={p}）")
            table[sk] = float(v)

    source_note = raw.get("source", str(p))
    return SizeBands(bands=tuple(bands), source=str(source_note), screen_mm_table=table)


# ---------------------------------------------------------------------------
# 归属与直方
# ---------------------------------------------------------------------------


def band_of_screen(screen: float, bands: SizeBands | None = None) -> str:
    """目数 → 筛段 key（连续域左闭右开：16.99→medium，17.00→large）。

    ``bands`` 缺省加载仓库默认配置；``screen`` 接受 float 以便边界语义
    可测（逐粒归属传 int 目数，与 ``sieve_hist`` 同源）。
    """
    if not math.isfinite(screen):
        raise SizeBandError(f"目数必须是有限数，得到 {screen!r}")
    sb = bands if bands is not None else load_size_bands()
    return sb.band_of(screen)


def _bean_screen(bean: PairedBean) -> int:
    """逐粒目数：两面 ``eq_diameter_mm`` 均值 → ``screen_of``（与 core.measure 同口径）。"""
    sides = [o for o in (bean.top, bean.bottom) if o is not None]
    if not sides:
        raise SizeBandError(f"占位豆（双面皆 None）不参与筛段归属: {bean.bean_id!r}")
    d_mm = sum(o.eq_diameter_mm for o in sides) / len(sides)
    return screen_of(d_mm)


def size_band_histogram(beans, bands: SizeBands | None = None) -> SizeBandHistogram:
    """逐粒归属 + 大中小直方（每粒归属 + 占比）。

    双面皆 None 的占位豆不进统计（与 ``Measurements.bean_count`` 同口径），
    但 ``per_bean`` 仍与其在输入列表中的位置对齐（占位豆记 ""，不落段）。
    """
    sb = bands if bands is not None else load_size_bands()
    keys = sb.keys()
    per_bean: list[str] = []
    counts = {k: 0 for k in keys}
    n = 0
    for b in beans:
        sides = [o for o in (b.top, b.bottom) if o is not None]
        if not sides:
            per_bean.append("")
            continue
        k = sb.band_of(_bean_screen(b))
        per_bean.append(k)
        counts[k] += 1
        n += 1
    frac = {k: (counts[k] / n if n else 0.0) for k in keys}
    return SizeBandHistogram(per_bean=tuple(per_bean), hist=counts, frac=frac, bean_count=n)


def aggregate_sieve_hist(sieve_hist: dict[str, int], bands: SizeBands | None = None) -> dict[str, int]:
    """把 ``Measurements.sieve_hist``（目数→粒数）聚合成筛段直方。

    键必须是目数整数字符串（与引擎 ``_below_sieve_count`` 同一约定）；
    本函数是纯聚合——整目数输入下结果与逐粒 :func:`size_band_histogram` 恒一致。
    """
    sb = bands if bands is not None else load_size_bands()
    out = {k: 0 for k in sb.keys()}
    for key, n in sieve_hist.items():
        try:
            screen = int(key)
        except (TypeError, ValueError):
            raise SizeBandError(f"sieve_hist 键 {key!r} 不是目数整数字符串") from None
        out[sb.band_of(screen)] += int(n)
    return out
