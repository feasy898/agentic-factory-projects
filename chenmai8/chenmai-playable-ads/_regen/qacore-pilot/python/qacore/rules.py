"""渠道规则库（qacore 判定输入：CHK01 体积上限 / CHK04 静音要求 / 运行时注入桩）。

数据结构对齐 docs/assets CONTRACTS §C4（rulesVersion 1.0.0）；
数值取自 channel-adapters §1 适配器总表（preview/applovin/meta/mintegral maxBytes）。
原实现读仓库 channel-rules JSON；本试点按"只凭 spec 再生"约束把规则库内嵌为包数据
（SPEC qacore.md 只约定消费语义：规则库无该渠道 → CHK01 skip、静音默认 true）。
"""

RULES = {
    "rulesVersion": "1.0.0",
    "defaults": {
        "externalUrlPolicy": "forbid",
        "allowedUrlSchemes": ["data:", "blob:"],
        "muteBeforeFirstInteraction": True,
        "allowRelativeRuntimeScripts": True,
    },
    "channels": {
        "preview": {
            "label": "Preview",
            "package": {"format": "single-html", "entry": "index.html"},
            "maxBytes": 5242880,
            "maxFiles": 1,
            "exit": {"protocol": "window-open", "call": "window.open(url)", "waitReadyBeforeRender": False},
            "runtime": {"muteBeforeFirstInteraction": True, "injectRelativeScripts": [], "forbidMraid": False},
        },
        "applovin": {
            "label": "AppLovin",
            "package": {"format": "single-html", "entry": "index.html"},
            "maxBytes": 5242880,
            "maxFiles": 1,
            "exit": {"protocol": "mraid", "call": "mraid.open(url)", "waitReadyBeforeRender": True},
            "runtime": {"muteBeforeFirstInteraction": True, "injectRelativeScripts": ["mraid.js"], "forbidMraid": False},
        },
        "meta": {
            "label": "Meta",
            "package": {"format": "single-html", "entry": "index.html"},
            "maxBytes": 3145728,
            "maxFiles": 1,
            "exit": {"protocol": "meta", "call": "FbPlayableAd.onComplete()", "waitReadyBeforeRender": True},
            "runtime": {"muteBeforeFirstInteraction": True, "injectRelativeScripts": [], "forbidMraid": True},
        },
        "mintegral": {
            "label": "Mintegral",
            "package": {"format": "zip", "entry": "Template.html"},
            "maxBytes": 5242880,
            "maxFiles": 100,
            "exit": {"protocol": "mraid", "call": "mraid.open(url)", "waitReadyBeforeRender": True},
            "runtime": {"muteBeforeFirstInteraction": True, "injectRelativeScripts": ["mraid.js"], "forbidMraid": False},
        },
    },
}


def channel_rules(channel: str):
    """取渠道规则；规则库无该渠道 → None（调用方按"不假定"处理）。"""
    return RULES["channels"].get(channel)


def mute_required(channel: str) -> bool:
    """CHK04 静音要求：渠道 runtime 覆盖 > defaults（默认 true）。"""
    ch = channel_rules(channel)
    if ch:
        runtime = ch.get("runtime") or {}
        if "muteBeforeFirstInteraction" in runtime:
            return bool(runtime["muteBeforeFirstInteraction"])
    return bool(RULES["defaults"]["muteBeforeFirstInteraction"])


def runtime_stubs(channel: str) -> list:
    """渠道容器运行时脚本（相对引用，如 mraid.js）——本地缺失时以空 JS 桩应答。"""
    ch = channel_rules(channel)
    if not ch:
        return []
    return list((ch.get("runtime") or {}).get("injectRelativeScripts") or [])
