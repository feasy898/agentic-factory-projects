"""pfcore.spec_model — pydantic 类型化表示层（校验第 3 阶段，code="model"）。

spec-contract §3：extra="forbid"、camelCase alias、typed_params 按 template 合并默认值
（{**DEFAULTS, **params} 一次性构建）。本层只在 schema + 不变式全过之后运行。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .invariants import TEMPLATE_PARAM_DEFAULTS, typed_params


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Meta(_Strict):
    project_id: str = Field(alias="projectId", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str | None = None
    seed: int = Field(ge=0)


class DurationBudgetSec(_Strict):
    target: float = Field(ge=0)
    max: float = Field(ge=0, le=30)


class Difficulty(_Strict):
    target_level: float | None = Field(default=None, alias="targetLevel", ge=0, le=1)


class Attract(_Strict):
    near_win: bool = Field(default=False, alias="nearWin")
    fail_bait: bool = Field(default=False, alias="failBait")
    first_click_succeed: bool = Field(default=True, alias="firstClickSucceed")


class Game(_Strict):
    template: str
    params: dict[str, Any] = Field(default_factory=dict)
    difficulty: Difficulty | None = None
    attract: Attract | None = None
    duration_budget_sec: DurationBudgetSec | None = Field(default=None, alias="durationBudgetSec")

    @property
    def typed_params(self) -> dict[str, Any]:
        """按 template 合并默认值后的参数（一次性 {**DEFAULTS, **params} 构建）。"""
        return typed_params(self.template, self.params)


class Tutorial(_Strict):
    enabled: bool = True
    gesture: str = "drag"
    max_sec: float | None = Field(default=None, alias="maxSec", ge=0)


class EndScreen(_Strict):
    show_score: bool = Field(default=True, alias="showScore")
    cta_key: str = Field(default="cta", alias="ctaKey")
    landing_url: str = Field(alias="landingUrl", pattern=r"^https?://\S+$", max_length=512)


class Flow(_Strict):
    tutorial: Tutorial | None = None
    end_screen: EndScreen = Field(alias="endScreen")


class Assets(_Strict):
    background: str | None = None
    sprites: dict[str, str | None] = Field(default_factory=dict)
    audio: dict[str, str | None] = Field(default_factory=dict)
    font_subset: str | None = Field(default=None, alias="fontSubset")


class LocaleStrings(_Strict):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    cta: str
    tutorial: str
    win: str
    lose: str
    score: str


class I18n(_Strict):
    default_locale: str = Field(alias="defaultLocale", min_length=1)
    locales: list[str] = Field(min_length=1)
    strings: dict[str, LocaleStrings]
    rtl: list[str] = Field(default_factory=list)


class ChannelOverride(_Strict):
    max_bytes: float | None = Field(default=None, alias="maxBytes", ge=0)
    cta_style: str | None = Field(default=None, alias="ctaStyle")


class Channels(_Strict):
    targets: list[str] = Field(min_length=1)
    orientation: str | None = None
    overrides: dict[str, ChannelOverride] = Field(default_factory=dict)

    @field_validator("targets")
    @classmethod
    def _known_targets(cls, value: list[str]) -> list[str]:
        from .invariants import CHANNELS

        unknown = [t for t in value if t not in CHANNELS]
        if unknown:
            raise ValueError(f"unknown channel target(s): {unknown}")
        return value


class Variant(_Strict):
    id: str = Field(min_length=1)
    seed: int = Field(default=0, ge=0)
    palette: str | None = None


class Qc(_Strict):
    max_load_sec: float = Field(default=2.0, alias="maxLoadSec", ge=0.5, le=10)
    autoplay_timeout_sec: float = Field(default=45.0, alias="autoplayTimeoutSec", ge=5, le=120)


class PlayableSpec(_Strict):
    spec_version: str = Field(alias="specVersion")
    meta: Meta
    game: Game
    flow: Flow
    assets: Assets
    i18n: I18n
    channels: Channels
    qc: Qc
    variants: list[Variant] = Field(default_factory=list)

    @field_validator("spec_version")
    @classmethod
    def _version_frozen(cls, value: str) -> str:
        if value != "1.0.0":
            raise ValueError(f"specVersion must be '1.0.0', got {value!r}")
        return value


def build_model(spec: dict[str, Any]) -> PlayableSpec:
    """类型化解析入口：dict → PlayableSpec（失败抛 pydantic.ValidationError，由 validation 层归一）。"""
    return PlayableSpec.model_validate(spec)


__all__ = [
    "PlayableSpec",
    "build_model",
    "typed_params",
    "TEMPLATE_PARAM_DEFAULTS",
    # 子模型再导出（类型消费方用）
    "Meta",
    "Game",
    "Flow",
    "Assets",
    "I18n",
    "Channels",
    "Qc",
    "Variant",
]
