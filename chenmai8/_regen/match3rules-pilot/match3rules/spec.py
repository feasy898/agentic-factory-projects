# -*- coding: utf-8 -*-
"""宽容归一与文案查找——SPEC.md §1 逐项复刻。

模板归一钳制范围（比 schema 宽，卡如实记录者按卡）：
  cols/rows 3-9 默认6；moves 1-60 默认15；colors 2-7 默认5；goalCount 1-400 默认30；
  goalType 非 "score" 一律 clear-jelly；spriteKeys >=1 缺省 5 个 piece-*（贴图按 i%len 取键）；
  seed int(v,1,0,0x7fffffff) 缺省1；targetLevel 0-1 缺省0.5（无玩法消费）；
  firstClickSucceed 缺省 true（无玩法消费）；gesture 非 "tap" 一律 "drag"；
  qc.maxLoadSec 1-10 / autoplayTimeoutSec 5-300（卡未给缺省值 -> 缺省保留 None）。

makeT 三级回退：当前语言 -> 默认语言 -> en -> 键名本身。
"""

from .jsnum import js_round  # noqa: F401  (re-export 便利)

DEFAULT_COLS = 6
DEFAULT_ROWS = 6
DEFAULT_MOVES = 15
DEFAULT_COLORS = 5
DEFAULT_GOAL_COUNT = 30
DEFAULT_SEED = 1
DEFAULT_TARGET_LEVEL = 0.5

DEFAULT_SPRITE_KEYS = ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"]

SEED_MIN = 0
SEED_MAX = 0x7FFFFFFF


def _clamp_int(v, lo, hi, default):
    if v is None:
        return default
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _clamp_float(v, lo, hi, default):
    if v is None:
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def normalize_spec(raw: dict) -> dict:
    """SPEC §1 宽容归一：LLM 只填偏差项也能跑。"""
    raw = raw or {}
    attrs = raw.get("attract") or {}
    diff = raw.get("difficulty") or {}
    tut = raw.get("tutorial") or {}
    qc = raw.get("qc") if isinstance(raw.get("qc"), dict) else {}

    sprite_keys = raw.get("spriteKeys")
    if not (isinstance(sprite_keys, list) and len(sprite_keys) >= 1):
        sprite_keys = list(DEFAULT_SPRITE_KEYS)

    # 卡面 "int(v, 1, 0, 0x7fffffff)"：按 (v, default=1, min=0, max=0x7fffffff) 读。
    seed = _clamp_int(raw.get("seed"), SEED_MIN, SEED_MAX, DEFAULT_SEED)

    max_load = qc.get("maxLoadSec")
    autoplay_to = qc.get("autoplayTimeoutSec")

    return {
        "cols": _clamp_int(raw.get("cols"), 3, 9, DEFAULT_COLS),
        "rows": _clamp_int(raw.get("rows"), 3, 9, DEFAULT_ROWS),
        "moves": _clamp_int(raw.get("moves"), 1, 60, DEFAULT_MOVES),
        "colors": _clamp_int(raw.get("colors"), 2, 7, DEFAULT_COLORS),
        "goalCount": _clamp_int(raw.get("goalCount"), 1, 400, DEFAULT_GOAL_COUNT),
        # 非 "score" 一律 clear-jelly
        "goalType": "score" if raw.get("goalType") == "score" else "clear-jelly",
        "spriteKeys": sprite_keys,
        "seed": seed,
        "difficulty": {"targetLevel": _clamp_float(diff.get("targetLevel"), 0.0, 1.0, DEFAULT_TARGET_LEVEL)},
        "attract": {
            "firstClickSucceed": attrs.get("firstClickSucceed", True),
            "nearWin": bool(attrs.get("nearWin", False)),
        },
        "tutorial": {"gesture": "tap" if tut.get("gesture") == "tap" else "drag"},
        "qc": {
            "maxLoadSec": _clamp_float(max_load, 1.0, 10.0, None),
            "autoplayTimeoutSec": _clamp_float(autoplay_to, 5.0, 300.0, None),
        },
        "rtl": raw.get("rtl") or [],
    }


def make_t(texts: dict, lang: str, default_lang: str = "en"):
    """SPEC §1 makeT：当前语言 -> 默认语言 -> en -> 键名本身。"""

    def t(key: str) -> str:
        for l in (lang, default_lang, "en"):
            table = texts.get(l) or {}
            if key in table:
                return table[key]
        return key

    return t


def sprite_key_for(i: int, sprite_keys: list) -> str:
    """SPEC §1：贴图按 i % spriteKeys.length 取键。"""
    return sprite_keys[i % len(sprite_keys)]


def score_mode_jelly_count(cols: int, rows: int) -> int:
    """SPEC §2：score 模式果冻数 = min(cols*rows, max(6, round(cols*rows*0.25)))。"""
    n = cols * rows
    return min(n, max(6, js_round(n * 0.25)))
