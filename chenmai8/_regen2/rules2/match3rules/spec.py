# -*- coding: utf-8 -*-
"""spec.ts 宽容归一镜像（卡面 §1）+ makeT 三级回退 + spriteKeys 取键。

normalizeSpec 做宽容归一（LLM 只填偏差项也能跑），钳制范围与 schema 范围不完全一致
（模板更宽，如实记录）。seed 参数序（回炉消歧）：int(meta.seed, 1, 0, 0x7fffffff)——
缺省 1、下界 0、上界 0x7fffffff，非数值/非有限数取缺省，Math.round 后钳制。
"""

from .jsnum import js_int

DEFAULT_SPRITE_KEYS = ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"]  # 回炉钉死键名


def _clamp_number(v, default, lo, hi):
    """连续量归一：非数值/非有限取缺省，否则原值钳制（不做取整）。"""
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        return float(default)
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return float(default)
    return max(float(lo), min(float(hi), f))


def normalize_spec(raw):
    """卡面 §1 宽容归一表（模板列）。

    qc 缺省：冻结 eval pin 归一输出缺省 None（其冻结时点卡面未给缺省值）；卡面回炉后
    钉死的缺省（maxLoadSec=2、autoplayTimeoutSec=45）以 constants.QC_*_DEFAULT 留作消费侧。
    """
    raw = dict(raw or {})
    attract = raw.get("attract") or {}
    difficulty = raw.get("difficulty") or {}
    tutorial = raw.get("tutorial") or {}
    qc = raw.get("qc") or {}

    max_load = qc.get("maxLoadSec")
    autoplay_timeout = qc.get("autoplayTimeoutSec")

    return {
        "cols": js_int(raw.get("cols"), 6, 3, 9),
        "rows": js_int(raw.get("rows"), 6, 3, 9),
        "moves": js_int(raw.get("moves"), 15, 1, 60),
        "colors": js_int(raw.get("colors"), 5, 2, 7),
        "goalCount": js_int(raw.get("goalCount"), 30, 1, 400),
        "goalType": "score" if raw.get("goalType") == "score" else "clear-jelly",
        "spriteKeys": _normalize_sprite_keys(raw.get("spriteKeys")),
        "seed": js_int(raw.get("seed"), 1, 0, 0x7FFFFFFF),
        "difficulty": {"targetLevel": _clamp_number(difficulty.get("targetLevel"), 0.5, 0.0, 1.0)},
        "attract": {
            "nearWin": bool(attract.get("nearWin", False)),  # 回炉补位：缺省 False
            "firstClickSucceed": bool(attract.get("firstClickSucceed", True)),
        },
        "tutorial": {"gesture": "tap" if tutorial.get("gesture") == "tap" else "drag"},
        "qc": {
            "maxLoadSec": None if max_load is None else js_int(max_load, 2, 1, 10),
            "autoplayTimeoutSec": None if autoplay_timeout is None else js_int(autoplay_timeout, 45, 5, 300),
        },
    }


def _normalize_sprite_keys(keys):
    """§1：>=1 个即可；缺省/空表恰为 ["piece-0".."piece-4"]（回炉钉死键名）。"""
    if isinstance(keys, list) and len(keys) >= 1:
        return list(keys)
    return list(DEFAULT_SPRITE_KEYS)


def make_t(texts, lang, default_lang="en"):
    """§1 文案查找 makeT：当前语言 -> 默认语言 -> en -> 键名本身（三级回退）。"""

    def t(key):
        for source in (texts.get(lang) if isinstance(texts, dict) else None,
                       texts.get(default_lang) if isinstance(texts, dict) else None,
                       texts.get("en") if isinstance(texts, dict) else None):
            if isinstance(source, dict) and key in source:
                return source[key]
        return key

    return t


def sprite_key_for(index, sprite_keys):
    """§1：贴图按 i % spriteKeys.length 取键。"""
    return sprite_keys[index % len(sprite_keys)]
