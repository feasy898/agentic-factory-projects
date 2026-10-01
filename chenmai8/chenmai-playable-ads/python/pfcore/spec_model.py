"""PlayableSpec v1 的 pydantic 模型（校验权威之外的类型化表示层）。

分工：结构校验权威是 ``playable-spec.schema.json``（经 jsonschema），语义不变式
权威是 :mod:`pfcore.invariants`；本模块把已通过二者校验的 spec 映射为强类型
对象，供 orchestrator/模板构建等下游代码使用（默认值在此具象化）。
字段名与 schema 一一对应（camelCase alias，Python 侧用 snake_case）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .invariants import (
    MATCH3_DEFAULTS,
    MERGE_DEFAULTS,
    PULLPIN_DEFAULTS,
    SORT_DEFAULTS,
    REQUIRED_STRING_KEYS,
)

Template = Literal["match3", "merge", "pullpin", "sort"]
Channel = Literal["applovin", "unity", "google", "meta", "tiktok", "mintegral"]
Gesture = Literal["tap", "drag"]
Orientation = Literal["portrait", "landscape", "both"]
Palette = Literal["A", "B", "C"]


class _Frozen(BaseModel):
    """公共配置：禁止 schema 之外的多余字段，别名优先（camelCase JSON）。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------- 顶层分片

class MetaInfo(_Frozen):
    project_id: str = Field(alias="projectId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1, max_length=80)
    seed: int = Field(ge=0)


class Difficulty(_Frozen):
    target_level: float = Field(alias="targetLevel", ge=0, le=1)


class Attract(_Frozen):
    near_win: bool = Field(default=False, alias="nearWin")
    fail_bait: bool = Field(default=False, alias="failBait")
    first_click_succeed: bool = Field(default=True, alias="firstClickSucceed")


class DurationBudgetSec(_Frozen):
    target: int = Field(default=20, ge=5, le=30)
    max: int = Field(default=30, ge=5, le=30)


# ---------------------------------------------------------------- 模板 params

class Match3Params(_Frozen):
    cols: int = Field(default=6, ge=4, le=9)
    rows: int = Field(default=6, ge=4, le=9)
    moves: int = Field(default=15, ge=3, le=60)
    colors: int = Field(default=5, ge=3, le=5)
    goal_type: Literal["clear-jelly", "score"] = Field(default="clear-jelly", alias="goalType")
    goal_count: int = Field(default=30, ge=1, le=999, alias="goalCount")
    sprite_keys: list[str] = Field(
        default=MATCH3_DEFAULTS["spriteKeys"], alias="spriteKeys",
        min_length=5, max_length=5)


class MergeParams(_Frozen):
    cols: int = Field(default=5, ge=3, le=9)
    rows: int = Field(default=5, ge=3, le=9)
    max_tier: int = Field(default=5, ge=2, le=8, alias="maxTier")
    spawn_tier_max: int = Field(default=2, ge=1, le=8, alias="spawnTierMax")
    goal_tier: int = Field(default=4, ge=2, le=8, alias="goalTier")
    sprite_keys: list[str] = Field(
        default=MERGE_DEFAULTS["spriteKeys"], alias="spriteKeys", min_length=1)


class PullpinParams(_Frozen):
    levels: int = Field(default=3, ge=1, le=10)
    pins_per_level: int = Field(default=3, ge=3, le=5, alias="pinsPerLevel")
    hazard: Literal["lava", "spike"] = "lava"
    rescuee: Literal["character"] = "character"
    order_solution: list[list[int]] = Field(alias="orderSolution", min_length=1)


class SortParams(_Frozen):
    rods: int = Field(default=4, ge=3, le=8)
    layers_per_rod: int = Field(default=4, ge=2, le=6, alias="layersPerRod")
    colors: int = Field(default=4, ge=2, le=6)
    screw_mode: bool = Field(default=False, alias="screwMode")
    move_limit: int | None = Field(default=None, ge=1, alias="moveLimit")


# ---------------------------------------------------------------- flow / assets

class Tutorial(_Frozen):
    enabled: bool = True
    gesture: Gesture = "tap"
    max_sec: float = Field(default=3, ge=0, le=10, alias="maxSec")


class EndScreen(_Frozen):
    show_score: bool = Field(default=True, alias="showScore")
    cta_key: str = Field(alias="ctaKey", min_length=1)
    landing_url: str = Field(alias="landingUrl", pattern=r"^https?://\S+$", max_length=512)


class Flow(_Frozen):
    tutorial: Tutorial
    end_screen: EndScreen = Field(alias="endScreen")


class Assets(_Frozen):
    background: str = Field(min_length=1)
    sprites: dict[str, str] = Field(min_length=1)
    audio: dict[str, str | None]
    font_subset: str | None = Field(default=None, alias="fontSubset")

    @field_validator("audio")
    @classmethod
    def _audio_keys(cls, v: dict[str, str | None]) -> dict[str, str | None]:
        unknown = set(v) - {"tap", "win"}
        if unknown:
            raise ValueError(f"audio 仅允许 tap/win 键，多余：{sorted(unknown)}")
        return v


# ---------------------------------------------------------------- i18n

class LocaleStrings(_Frozen):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    cta: str = Field(min_length=1)
    tutorial: str = Field(min_length=1)
    win: str = Field(min_length=1)
    lose: str = Field(min_length=1)
    score: str = Field(min_length=1)


class I18n(_Frozen):
    default_locale: str = Field(alias="defaultLocale", min_length=1)
    locales: list[str] = Field(min_length=1)
    strings: dict[str, LocaleStrings]
    rtl: list[str] = Field(default_factory=list)

    @field_validator("strings")
    @classmethod
    def _required_keys(cls, v: dict[str, LocaleStrings]) -> dict[str, LocaleStrings]:
        # LocaleStrings 模型已强制五个键存在；这里把缺失键翻译成稳定错误信息。
        return v


# ---------------------------------------------------------------- channels / qc

class ChannelOverride(_Frozen):
    max_bytes: int | None = Field(default=None, ge=0, alias="maxBytes")
    cta_style: str | None = Field(default=None, alias="ctaStyle", min_length=1)


class Channels(_Frozen):
    targets: list[Channel] = Field(min_length=1)
    orientation: Orientation
    overrides: dict[str, ChannelOverride] = Field(default_factory=dict)


class Variant(_Frozen):
    id: str = Field(min_length=1)
    seed: int | None = Field(default=None, ge=0)
    palette: Palette | None = None


class QC(_Frozen):
    max_load_sec: float = Field(default=2.0, ge=0.5, le=10, alias="maxLoadSec")
    autoplay_timeout_sec: float = Field(default=45, ge=5, le=120, alias="autoplayTimeoutSec")


# ---------------------------------------------------------------- 根模型

class Game(_Frozen):
    template: Template
    params: dict[str, Any]
    difficulty: Difficulty | None = None
    attract: Attract = Field(default_factory=Attract)
    duration_budget_sec: DurationBudgetSec = Field(alias="durationBudgetSec")

    _typed_params: Match3Params | MergeParams | PullpinParams | SortParams | None = None

    @property
    def typed_params(self) -> Match3Params | MergeParams | PullpinParams | SortParams:
        """按 template 把 params dict 映射为对应强类型模型（一次性构建）。"""
        if self._typed_params is None:
            model = {
                "match3": Match3Params,
                "merge": MergeParams,
                "pullpin": PullpinParams,
                "sort": SortParams,
            }[self.template]
            self._typed_params = model.model_validate(
                {**_defaults_for(self.template), **self.params})
        return self._typed_params  # type: ignore[return-value]


def _defaults_for(template: str) -> dict[str, Any]:
    return {
        "match3": MATCH3_DEFAULTS,
        "merge": MERGE_DEFAULTS,
        "pullpin": PULLPIN_DEFAULTS,
        "sort": SORT_DEFAULTS,
    }[template]


class PlayableSpec(_Frozen):
    """PlayableSpec v1.0.0 根模型（schema + 不变式通过后的类型化形态）。"""

    spec_version: Literal["1.0.0"] = Field(alias="specVersion")
    meta: MetaInfo
    game: Game
    flow: Flow
    assets: Assets
    i18n: I18n
    channels: Channels
    variants: list[Variant] = Field(default_factory=list)
    qc: QC


def parse_spec(data: dict[str, Any]) -> PlayableSpec:
    """dict -> PlayableSpec；校验失败抛 pydantic.ValidationError。

    调用时机：schema 校验与不变式检查通过之后（本模型是表示层而非权威）。
    """
    return PlayableSpec.model_validate(data)


__all__ = [
    "PlayableSpec", "Game", "MetaInfo", "Flow", "Assets", "I18n", "Channels",
    "Variant", "QC", "Match3Params", "MergeParams", "PullpinParams", "SortParams",
    "LocaleStrings", "REQUIRED_STRING_KEYS", "parse_spec", "ValidationError",
]
