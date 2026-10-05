"""webui specgen —— 表单字段 → PlayableSpec v1 组装器（M10）。

职责：把界面表单（选模板 / 填文案 / 上传 PNG 素材 / 少量高级项）组装成一份
能通过 pfcore 校验（schema v1 + 不变式 I1-I5）的 PlayableSpec dict：

- 文案：每语言内置一组可改缺省（与 specs-eval/golden、demo-zh 的字符串表同源），
  用户只填偏差项；任意键留空都回退缺省，保证 I5（每语言五键齐全）恒可满足。
- seed：表单可留空 → 随机取；match3 用 pfcore.invariants 的规范生成器预检
  I3（初始盘面存在可行步），不可行自动换 seed，提交即过校验。
- pullpin：orderSolution 由 seed 经 ``pullpin_level_roles`` 实算（中性针升序 +
  救援针收尾，与 golden-pullpin 的约定一致），并用 ``pullpin_simulate`` 复核可解
  （I1）——校验算法只此一份权威实现（pfcore.invariants），本模块不复制算法。
- 素材：上传 PNG 按文件名主干匹配模板槽位键（如 piece-0 / tier-2 / pin），
  未匹配的按槽位顺序顺延填入；路径相对 spec 文件目录（模板构建器同规）。
- landingUrl：仅接受 http/https（schema pattern 同规）；服务端从不访问该 URL。

本模块不做任何网络请求。
"""
from __future__ import annotations

import re
import secrets

from pfcore.invariants import (
    match3_board,
    match3_find_move,
    pullpin_level_roles,
    pullpin_simulate,
)

# 与 pfcore.make.TEMPLATE_BUILDERS 对齐：只有接了真实构建器的模板才可入表
TEMPLATES = ("match3", "merge", "pullpin")

TEMPLATE_LABELS = {"match3": "三消", "merge": "合成", "pullpin": "拔针救援"}
TEMPLATE_TITLES = {
    "match3": "宝石三消（试玩）",
    "merge": "合成大冒险（试玩）",
    "pullpin": "拔针救援（试玩）",
}
TEMPLATE_GESTURE = {"match3": "drag", "merge": "drag", "pullpin": "tap"}

#: 各模板可上传替换的精灵槽位键（与模板源码的替换键约定一致）。
SPRITE_SLOTS = {
    "match3": ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4", "jelly"],
    "merge": ["tier-1", "tier-2", "tier-3", "tier-4", "tier-5"],
    "pullpin": ["pin", "rescuee", "hazard"],
}

LOCALES = ("zh", "en", "ja", "ko", "pt-BR", "de", "ar")
RTL_LOCALES = ("ar",)

DEFAULT_LANDING_URL = "https://example.com/playable-lp"
DEFAULT_CHANNELS = ["applovin", "meta", "mintegral"]

#: I5 必填五键（pfcore.invariants.REQUIRED_STRING_KEYS 的展示顺序）。
STRING_KEYS = ("cta", "tutorial", "win", "lose", "score")

# ---------------------------------------------------------------- 文案缺省表

# cta/win/lose/score 的每语言缺省（与 specs-eval golden 字符串表同源，可改）。
_GENERIC_STRINGS: dict[str, dict[str, str]] = {
    "zh": {"cta": "立即下载", "win": "通关啦！", "lose": "再试一次！", "score": "得分"},
    "en": {"cta": "Play Now", "win": "You Win!", "lose": "Try Again!", "score": "Score"},
    "ja": {"cta": "今すぐ遊ぶ", "win": "クリア！", "lose": "もう一度！", "score": "スコア"},
    "ko": {"cta": "지금 플레이", "win": "성공!", "lose": "다시 도전!", "score": "점수"},
    "pt-BR": {"cta": "Jogue Agora", "win": "Você Venceu!", "lose": "Tente de Novo!", "score": "Pontos"},
    "de": {"cta": "Jetzt Spielen", "win": "Gewonnen!", "lose": "Nochmal versuchen!", "score": "Punkte"},
    "ar": {"cta": "العب الآن", "win": "لقد فزت!", "lose": "حاول مجدداً!", "score": "النقاط"},
}

# 教程文案按模板区分（zh/en 全量，其余语言回退 en——表单可改）。
_TUTORIALS: dict[str, dict[str, str]] = {
    "match3": {
        "zh": "拖动宝石，三个同色连成一线！", "en": "Drag to match 3 gems!",
        "ja": "ドラッグして3つ揃えよう！", "ko": "드래그해서 3개를 맞춰요!",
        "pt-BR": "Arraste para juntar 3!", "de": "Ziehe und kombiniere 3!",
        "ar": "اسحب لمطابقة 3 جواهر!",
    },
    "merge": {
        "zh": "拖动同类物品，合成升级！", "en": "Drag to merge and upgrade!",
    },
    "pullpin": {
        "zh": "点击拔出别针，救出小伙伴！", "en": "Tap to pull the pin and rescue!",
    },
}


def locale_defaults(template: str, locale: str) -> dict[str, str]:
    """某模板某语言的五键缺省文案（界面预填用；用户覆盖任意子集）。"""
    generic = _GENERIC_STRINGS.get(locale) or _GENERIC_STRINGS["en"]
    tutorials = _TUTORIALS.get(template) or _TUTORIALS["match3"]
    tutorial = tutorials.get(locale) or tutorials["en"]
    return {**generic, "tutorial": tutorial}


def defaults_table() -> dict[str, dict[str, dict[str, str]]]:
    """全量缺省表 {template: {locale: {title + 5 键}}}（/api/meta 一次下发）。"""
    return {t: {loc: {"title": TEMPLATE_TITLES[t], **locale_defaults(t, loc)}
                for loc in LOCALES} for t in TEMPLATES}


# ---------------------------------------------------------------- 组装

class SpecBuildError(Exception):
    """表单不合法：message 列表面向界面直接展示。"""

    def __init__(self, messages: list[str]):
        super().__init__("；".join(messages))
        self.messages = messages


def sanitize_project_id(raw: str, template: str) -> str:
    """projectId 清洗为 ^[a-z0-9][a-z0-9-]{0,63}$（schema pattern）；洗空用默认。"""
    fallback = f"webui-{template}"
    cleaned = re.sub(r"[^a-z0-9-]+", "-", (raw or "").strip().lower()).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)[:64]
    if not cleaned or not re.match(r"^[a-z0-9]", cleaned):
        return fallback
    return cleaned


def _normalize_landing_url(raw: str) -> str:
    url = (raw or "").strip()
    if not url:
        return DEFAULT_LANDING_URL
    if len(url) > 512 or re.search(r"\s", url) or not re.match(r"^https?://\S+$", url):
        raise SpecBuildError([f"landingUrl 须为 http/https 绝对地址且不含空白：{url!r}"])
    return url


def _match3_seed(rows: int, cols: int, colors: int, want: int | None) -> int:
    """取一个满足 I3（初始盘面存在可行步）的 seed；指定 seed 不合规则报错。"""
    if want is not None:
        if match3_find_move(match3_board(want, rows, cols, colors)) is None:
            raise SpecBuildError(
                [f"seed={want} 生成的 match3 初始盘面无可行步（不变式 I3），请换 seed 或留空随机"])
        return want
    for _ in range(100):
        seed = secrets.randbelow(2**31)
        if match3_find_move(match3_board(seed, rows, cols, colors)) is not None:
            return seed
    raise SpecBuildError(["随机 seed 100 次均无可行步（不应发生，请手填 seed）"])


def _pullpin_order(seed: int, levels: int, pins: int) -> list[list[int]]:
    """由 seed 实算每关拔针顺序：中性针升序在前、救援针收尾（golden 同约定），
    并用模拟复核可解（I1）。"""
    order: list[list[int]] = []
    for rescuee, hazard in pullpin_level_roles(seed, levels, pins):
        level_order = [p for p in range(pins) if p not in (rescuee, hazard)] + [rescuee]
        solved, reason = pullpin_simulate(level_order, rescuee, hazard)
        if not solved:  # 实算 + 复核双保险（不应发生；发生即组装 bug，宁可失败不可假绿）
            raise SpecBuildError([f"pullpin orderSolution 复核不可解：{reason}"])
        order.append(level_order)
    return order


def assemble_spec(
    template: str,
    *,
    project_id: str = "",
    title: str = "",
    locale: str = "zh",
    texts: dict[str, str] | None = None,
    seed: int | None = None,
    landing_url: str = "",
    near_win: bool = True,
    sprite_slots: dict[str, str] | None = None,
) -> dict:
    """组装一份 PlayableSpec v1 dict；表单不合法抛 SpecBuildError。

    sprite_slots：{槽位键: 相对 spec 文件的素材路径}（上传文件落盘后由调用方传入）。
    """
    if template not in TEMPLATES:
        raise SpecBuildError([f"未知模板：{template!r}（可选：{', '.join(TEMPLATES)}）"])
    if locale not in LOCALES:
        raise SpecBuildError([f"不支持的语言：{locale!r}（可选：{', '.join(LOCALES)}）"])
    texts = {k: (v or "").strip() for k, v in (texts or {}).items()}
    for key, value in texts.items():
        if key not in STRING_KEYS:
            raise SpecBuildError([f"未知文案键：{key!r}"])

    pid = sanitize_project_id(project_id, template)
    final_title = title.strip() or TEMPLATE_TITLES[template]
    if len(final_title) > 80:
        raise SpecBuildError(["标题超过 80 字符（schema 上限）"])

    # match3 参数固定走冻结默认（6×6/15 步/5 色/清果冻 30）——界面只做最小表单，
    # 参数级微调走 spec 上传或 pfcore CLI。
    rows, cols, colors = 6, 6, 5
    final_seed = _match3_seed(rows, cols, colors, seed) if template == "match3" \
        else (seed if seed is not None else secrets.randbelow(2**31))

    slots = dict(sprite_slots or {})
    for key, rel in slots.items():
        if not isinstance(rel, str) or not rel:
            raise SpecBuildError([f"素材槽位 {key!r} 路径为空"])
    for key in SPRITE_SLOTS[template]:
        slots.setdefault(key, f"assets/theme-a/{key}.png")  # 缺省指向主题路径（缺失→程序化贴图）

    strings = {**locale_defaults(template, locale), **{k: v for k, v in texts.items() if v}}
    rtl = [loc for loc in RTL_LOCALES if loc in (locale,)]

    spec: dict = {
        "specVersion": "1.0.0",
        "meta": {"projectId": pid, "title": final_title, "seed": final_seed},
        "game": {
            "template": template,
            "params": (
                {
                    "cols": cols, "rows": rows, "moves": 15, "colors": colors,
                    "goalType": "clear-jelly", "goalCount": 30,
                    "spriteKeys": SPRITE_SLOTS["match3"][:5],
                } if template == "match3" else
                {
                    "cols": 5, "rows": 5, "maxTier": 5, "spawnTierMax": 2, "goalTier": 4,
                    "spriteKeys": SPRITE_SLOTS["merge"],
                } if template == "merge" else
                {
                    "levels": 3, "pinsPerLevel": 3, "hazard": "lava", "rescuee": "character",
                    "orderSolution": _pullpin_order(final_seed, 3, 3),
                }
            ),
            "difficulty": {"targetLevel": 0.4},
            "attract": {"nearWin": bool(near_win), "failBait": False, "firstClickSucceed": True},
            "durationBudgetSec": {"target": 20, "max": 30},
        },
        "flow": {
            "tutorial": {"enabled": True, "gesture": TEMPLATE_GESTURE[template], "maxSec": 3},
            "endScreen": {"showScore": True, "ctaKey": "cta", "landingUrl": _normalize_landing_url(landing_url)},
        },
        "assets": {
            "background": "assets/theme-a/bg-portrait.png",
            "sprites": slots,
            "audio": {"tap": None, "win": None},
        },
        "i18n": {
            "defaultLocale": locale,
            "locales": [locale],
            "strings": {locale: strings},
            "rtl": rtl,
        },
        "channels": {
            "targets": list(DEFAULT_CHANNELS),
            "orientation": "portrait",
            "overrides": {
                "applovin": {"maxBytes": 5242880, "ctaStyle": "banner"},
                "meta": {"maxBytes": 3145728, "ctaStyle": "endcard"},
            },
        },
        "qc": {"maxLoadSec": 3.0, "autoplayTimeoutSec": 45},
    }
    return spec
