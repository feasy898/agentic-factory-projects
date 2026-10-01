"""W12b · 铺盘合成器配置（configs/synth.yaml 的加载与校验）。

``configs/synth.yaml`` 是 compose 合成器的**标准 YAML 输入格式**（schema 见
该文件头注释）；:func:`load_compose_config` 严格校验（未知键拒绝、区间越界
拒绝、类权重键必须在 taxonomy 缺陷类内），错误信息带文件路径与键路径。
:func:`config_to_dict` 输出同一 schema 的规范化映射——write_batch 落盘的
batch manifest 即用它记录实际生效参数，回读后可直接再驱动一次合成
（manifest.yaml ⇄ ComposeConfig 往返恒等，种子固定则字节级复现）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from beaneye.taxonomy import load_taxonomy

__all__ = ["DEFAULT_SYNTH_CONFIG_PATH", "SynthConfigError", "ComposeConfig",
           "load_compose_config", "config_to_dict"]

DEFAULT_SYNTH_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "synth.yaml"


class SynthConfigError(ValueError):
    """合成配置缺失 / YAML 非法 / 字段越界或自相矛盾。"""


@dataclass(frozen=True)
class ComposeConfig:
    """铺盘合成器配置（_immutable_，合成全程只读）。字段语义见 synth.yaml 头注释。"""

    version: int
    width_px: int
    height_px: int
    margin_mm: float
    n_beans_min: int
    n_beans_max: int
    defect_rate: float
    class_weights: dict[str, float] = field(default_factory=dict)
    contact_min: int = 0
    contact_max: int = 0
    overlap_depth: float = 0.82
    free_factor: float = 1.06
    layout_margin_mm: float | None = None
    scale_jitter: float = 0.10
    angle_jitter: float = 180.0
    pair_jitter_mm: float = 0.6
    mirror_bottom: bool = True
    shadow_enabled: bool = True
    shadow_offset_mm: tuple[float, float] = (1.0, 2.2)
    shadow_blur_px: float = 5.0
    shadow_strength: float = 0.30
    light_gain: tuple[float, float] = (0.94, 1.06)
    light_gamma: tuple[float, float] = (0.96, 1.04)
    vignette_strength: float = 0.10
    specular_streaks: bool = True
    background_bgr: tuple[int, int, int] = (200, 203, 208)
    grain_sigma: float = 3.0
    per_class: int = 24
    library_seed: int = 20260929


def _num(raw: dict, key: str, where: str, *, lo: float, hi: float) -> float:
    v = raw.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SynthConfigError(f"{where}: `{key}` 必须是数值，得到 {v!r}")
    v = float(v)
    if not (lo <= v <= hi):
        raise SynthConfigError(f"{where}: `{key}` 必须在 [{lo}, {hi}]，得到 {v}")
    return v


def _pair(raw: dict, key: str, where: str, *, lo: float, hi: float) -> tuple[float, float]:
    v = raw.get(key)
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise SynthConfigError(f"{where}: `{key}` 必须是二元区间 [min, max]，得到 {v!r}")
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not (lo <= float(x) <= hi):
            raise SynthConfigError(f"{where}: `{key}` 各元素必须是 [{lo}, {hi}] 内数值，得到 {v!r}")
        out.append(float(x))
    if out[0] > out[1]:
        raise SynthConfigError(f"{where}: `{key}` 区间须 min<=max，得到 {out}")
    return (out[0], out[1])


def load_compose_config(path: str | Path | None = None) -> ComposeConfig:
    """加载并校验合成配置；``path=None`` 用仓库默认 ``configs/synth.yaml``。"""
    p = Path(path) if path is not None else DEFAULT_SYNTH_CONFIG_PATH
    if not p.is_file():
        raise SynthConfigError(f"合成配置文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SynthConfigError(f"合成配置 YAML 解析失败 {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SynthConfigError(f"{p}: 顶层必须是映射，得到 {type(raw).__name__}")
    where = f"{p}"

    allowed_top = {"version", "canvas", "layout", "render", "library"}
    unknown = sorted(set(raw) - allowed_top)
    if unknown:
        raise SynthConfigError(f"{where}: 未知顶层键 {unknown}（允许: {sorted(allowed_top)}）")

    version = raw.get("version")
    if version != 1:
        raise SynthConfigError(f"{where}: `version` 必须是 1，得到 {version!r}")

    canvas = raw.get("canvas", {})
    if not isinstance(canvas, dict):
        raise SynthConfigError(f"{where}: `canvas` 必须是映射")
    unknown = sorted(set(canvas) - {"width_px", "height_px", "margin_mm"})
    if unknown:
        raise SynthConfigError(f"{where}: canvas 未知键 {unknown}")

    def _int(node: dict, key: str, w: str, lo: int, hi: int) -> int:
        v = node.get(key)
        if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi):
            raise SynthConfigError(f"{w}: `{key}` 必须是 [{lo}, {hi}] 内整数，得到 {v!r}")
        return v

    width = _int(canvas, "width_px", where, 256, 8192)
    height = _int(canvas, "height_px", where, 256, 8192)
    margin = _num(canvas, "margin_mm", where, lo=0.0, hi=100.0)

    layout = raw.get("layout", {})
    if not isinstance(layout, dict):
        raise SynthConfigError(f"{where}: `layout` 必须是映射")
    unknown = sorted(set(layout) - {
        "n_beans", "defect_rate", "class_weights", "contact_target",
        "overlap_depth", "free_factor", "margin_mm",
    })
    if unknown:
        raise SynthConfigError(f"{where}: layout 未知键 {unknown}")

    n_beans = layout.get("n_beans")
    if not isinstance(n_beans, dict) or set(n_beans) != {"min", "max"}:
        raise SynthConfigError(f"{where}: `layout.n_beans` 必须是 {{min, max}}，得到 {n_beans!r}")
    n_min = _int(n_beans, "min", where, 1, 2000)
    n_max = _int(n_beans, "max", where, 1, 2000)
    if n_min > n_max:
        raise SynthConfigError(f"{where}: layout.n_beans 区间须 min<=max，得到 ({n_min}, {n_max})")

    defect_rate = _num(layout, "defect_rate", where, lo=0.0, hi=1.0)

    tax_keys = set(load_taxonomy().keys())
    defect_keys = tax_keys - {"normal"}
    weights_raw = layout.get("class_weights", {})
    if not isinstance(weights_raw, dict):
        raise SynthConfigError(f"{where}: `layout.class_weights` 必须是映射")
    unknown = sorted(set(weights_raw) - defect_keys)
    if unknown:
        raise SynthConfigError(
            f"{where}: layout.class_weights 键必须是 taxonomy 缺陷类（normal 除外），"
            f"非法键 {unknown}"
        )
    weights: dict[str, float] = {}
    for k, v in weights_raw.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0.0 <= float(v) <= 100.0):
            raise SynthConfigError(f"{where}: class_weights[{k!r}] 必须是 [0,100] 内数值，得到 {v!r}")
        weights[str(k)] = float(v)

    contact = layout.get("contact_target", {"min": 0, "max": 0})
    if not isinstance(contact, dict) or set(contact) != {"min", "max"}:
        raise SynthConfigError(f"{where}: `layout.contact_target` 必须是 {{min, max}}，得到 {contact!r}")
    c_min = _int(contact, "min", where, 0, 2000)
    c_max = _int(contact, "max", where, 0, 2000)
    if c_min > c_max:
        raise SynthConfigError(f"{where}: contact_target 区间须 min<=max，得到 ({c_min}, {c_max})")
    if c_max > n_max:
        raise SynthConfigError(
            f"{where}: contact_target.max({c_max}) 不得超过 n_beans.max({n_max})"
        )

    overlap_depth = _num(layout, "overlap_depth", where, lo=0.05, hi=0.999)
    free_factor = _num(layout, "free_factor", where, lo=1.001, hi=3.0)
    layout_margin = layout.get("margin_mm")
    layout_margin_f: float | None = None
    if layout_margin is not None:
        layout_margin_f = _num(layout, "margin_mm", where, lo=0.0, hi=150.0)

    render = raw.get("render", {})
    if not isinstance(render, dict):
        raise SynthConfigError(f"{where}: `render` 必须是映射")
    unknown = sorted(set(render) - {
        "scale_jitter", "angle_jitter", "pair_jitter_mm", "mirror_bottom", "shadow",
        "light", "vignette", "specular_streaks", "background_bgr", "grain_sigma",
    })
    if unknown:
        raise SynthConfigError(f"{where}: render 未知键 {unknown}")

    scale_jitter = _num(render, "scale_jitter", where, lo=0.0, hi=0.5)
    angle_jitter = _num(render, "angle_jitter", where, lo=0.0, hi=180.0)
    pair_jitter = _num(render, "pair_jitter_mm", where, lo=0.0, hi=10.0)
    mirror = render.get("mirror_bottom", True)
    if not isinstance(mirror, bool):
        raise SynthConfigError(f"{where}: `render.mirror_bottom` 必须是布尔，得到 {mirror!r}")

    shadow = render.get("shadow", {})
    if not isinstance(shadow, dict):
        raise SynthConfigError(f"{where}: `render.shadow` 必须是映射")
    unknown = sorted(set(shadow) - {"enabled", "offset_mm", "blur_px", "strength"})
    if unknown:
        raise SynthConfigError(f"{where}: render.shadow 未知键 {unknown}")
    sh_enabled = shadow.get("enabled", True)
    if not isinstance(sh_enabled, bool):
        raise SynthConfigError(f"{where}: `render.shadow.enabled` 必须是布尔，得到 {sh_enabled!r}")
    sh_off = _pair(shadow, "offset_mm", where, lo=0.0, hi=10.0)
    sh_blur = _num(shadow, "blur_px", where, lo=0.0, hi=50.0)
    sh_strength = _num(shadow, "strength", where, lo=0.0, hi=1.0)

    light = render.get("light", {})
    if not isinstance(light, dict):
        raise SynthConfigError(f"{where}: `render.light` 必须是映射")
    unknown = sorted(set(light) - {"gain", "gamma"})
    if unknown:
        raise SynthConfigError(f"{where}: render.light 未知键 {unknown}")
    gain = _pair(light, "gain", where, lo=0.5, hi=1.5)
    gamma = _pair(light, "gamma", where, lo=0.5, hi=1.5)

    vignette_node = render.get("vignette", {})
    if not isinstance(vignette_node, dict) or set(vignette_node) - {"strength"}:
        raise SynthConfigError(f"{where}: `render.vignette` 必须是只含 strength 的映射")
    vignette = _num(vignette_node, "strength", where, lo=0.0, hi=0.5)

    streaks = render.get("specular_streaks", True)
    if streaks in (0, 1):
        streaks = bool(streaks)
    if not isinstance(streaks, bool):
        raise SynthConfigError(f"{where}: `render.specular_streaks` 必须是布尔/0/1，得到 {streaks!r}")

    bg = render.get("background_bgr", [200, 203, 208])
    if not isinstance(bg, (list, tuple)) or len(bg) != 3 or any(
        isinstance(x, bool) or not isinstance(x, int) or not (0 <= x <= 255) for x in bg
    ):
        raise SynthConfigError(f"{where}: `render.background_bgr` 必须是 3 个 0-255 整数，得到 {bg!r}")
    grain = _num(render, "grain_sigma", where, lo=0.0, hi=30.0)

    library = raw.get("library", {})
    if not isinstance(library, dict):
        raise SynthConfigError(f"{where}: `library` 必须是映射")
    unknown = sorted(set(library) - {"per_class", "seed"})
    if unknown:
        raise SynthConfigError(f"{where}: library 未知键 {unknown}")
    per_class = _int(library, "per_class", where, 20, 200)
    lib_seed = _int(library, "seed", where, 0, 2**31 - 1)

    return ComposeConfig(
        version=1,
        width_px=width,
        height_px=height,
        margin_mm=margin,
        n_beans_min=n_min,
        n_beans_max=n_max,
        defect_rate=defect_rate,
        class_weights=weights,
        contact_min=c_min,
        contact_max=c_max,
        overlap_depth=overlap_depth,
        free_factor=free_factor,
        layout_margin_mm=layout_margin_f,
        scale_jitter=scale_jitter,
        angle_jitter=angle_jitter,
        pair_jitter_mm=pair_jitter,
        mirror_bottom=mirror,
        shadow_enabled=sh_enabled,
        shadow_offset_mm=sh_off,
        shadow_blur_px=sh_blur,
        shadow_strength=sh_strength,
        light_gain=gain,
        light_gamma=gamma,
        vignette_strength=vignette,
        specular_streaks=streaks,
        background_bgr=(int(bg[0]), int(bg[1]), int(bg[2])),
        grain_sigma=grain,
        per_class=per_class,
        library_seed=lib_seed,
    )


def config_to_dict(cfg: ComposeConfig) -> dict:
    """ComposeConfig → synth.yaml schema 的规范化映射（manifest 落盘/回读用）。"""
    return {
        "version": 1,
        "canvas": {
            "width_px": cfg.width_px,
            "height_px": cfg.height_px,
            "margin_mm": cfg.margin_mm,
        },
        "layout": {
            "n_beans": {"min": cfg.n_beans_min, "max": cfg.n_beans_max},
            "defect_rate": cfg.defect_rate,
            "class_weights": dict(cfg.class_weights),
            "contact_target": {"min": cfg.contact_min, "max": cfg.contact_max},
            "overlap_depth": cfg.overlap_depth,
            "free_factor": cfg.free_factor,
            **({"margin_mm": cfg.layout_margin_mm} if cfg.layout_margin_mm is not None else {}),
        },
        "render": {
            "scale_jitter": cfg.scale_jitter,
            "angle_jitter": cfg.angle_jitter,
            "pair_jitter_mm": cfg.pair_jitter_mm,
            "mirror_bottom": cfg.mirror_bottom,
            "shadow": {
                "enabled": cfg.shadow_enabled,
                "offset_mm": list(cfg.shadow_offset_mm),
                "blur_px": cfg.shadow_blur_px,
                "strength": cfg.shadow_strength,
            },
            "light": {"gain": list(cfg.light_gain), "gamma": list(cfg.light_gamma)},
            "vignette": {"strength": cfg.vignette_strength},
            "specular_streaks": 1 if cfg.specular_streaks else 0,
            "background_bgr": list(cfg.background_bgr),
            "grain_sigma": cfg.grain_sigma,
        },
        "library": {"per_class": cfg.per_class, "seed": cfg.library_seed},
    }
