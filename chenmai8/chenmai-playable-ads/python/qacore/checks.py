"""检查项定义（M8 规划十项；当前实装 CHK01/03/04/05/07/08/09）。

判定状态取值：pass / fail / skip。
- pass/fail：由本次无头打开过程真实测得；
- skip：检查项尚未实装（CHK02/06/10）或本产物不具备判定前提（如无 PF 桥、
  无 --autoplay），不做任何假定结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Check:
    id: str
    name: str
    status: str  # pass | fail | skip
    detail: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status, "detail": self.detail}


def skip(id_: str, name: str, detail: str) -> Check:
    return Check(id=id_, name=name, status="skip", detail=detail)


def _clip(text: str, n: int = 5) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def evaluate(facts: dict[str, Any]) -> list[Check]:
    """根据本次（双视口 + 可选自动试玩）采集的事实逐项判定。"""
    checks: list[Check] = []

    # CHK01 包体大小 ≤ 渠道上限（channel-rules；未知渠道不判定）
    limit = facts.get("channel_max_bytes")
    if limit is None:
        checks.append(skip("CHK01", "包体大小 ≤ 渠道上限",
                           f"规则库无渠道 {facts.get('channel')!r} 的上限，不判定"))
    elif facts["artifact_bytes"] <= limit:
        checks.append(Check("CHK01", "包体大小 ≤ 渠道上限", "pass",
                            f"{facts['artifact_bytes']} B ≤ 上限 {limit} B"))
    else:
        checks.append(Check("CHK01", "包体大小 ≤ 渠道上限", "fail",
                            f"{facts['artifact_bytes']} B > 上限 {limit} B"))

    checks.append(skip("CHK02", "文件数 ≤ 渠道上限", "未实装（当前输入为单 HTML 文件，无目录清点）"))

    # CHK03 零外网请求（横竖屏两趟合并判定）
    external = facts["external_requests"]
    if external:
        shown = "；".join(_clip(u) for u in external[:5])
        more = f"（另 {len(external) - 5} 条略）" if len(external) > 5 else ""
        checks.append(Check("CHK03", "零外网请求", "fail",
                            f"发现 {len(external)} 条非本机请求，已拦截：{shown}{more}"))
    else:
        checks.append(Check("CHK03", "零外网请求", "pass",
                            f"两趟共 {facts['request_count']} 条请求均指向本地伺服地址，无外网请求"))

    # CHK04 首交互前静音 + 首交互后允许出声（依赖 window.PF 与自动试玩）
    pf_present = facts.get("pf_present")
    auto = facts.get("autoplay") or {}
    if not pf_present:
        checks.append(skip("CHK04", "首交互前静音", "页面未装配 window.PF 桥，无可判定对象"))
    else:
        first_muted = auto.get("firstMutedBeforeInteraction")
        audio_running = auto.get("audioRunningBeforeInteraction")
        after = auto.get("mutedAfterFirstGesture")
        problems: list[str] = []
        if first_muted is not True:
            problems.append(f"首交互前 PF.isMuted()={first_muted}")
        if facts.get("autoplay_enabled") and audio_running not in (0, None):
            problems.append(f"首交互前存在 running AudioContext（{audio_running}）")
        if facts.get("autoplay_enabled") and after is not False:
            problems.append(f"首交互后 PF.isMuted()={after}（应为 False，即解除静音）")
        if problems:
            checks.append(Check("CHK04", "首交互前静音", "fail", "；".join(problems)))
        else:
            detail = "首交互前 PF.isMuted()=true"
            if facts.get("autoplay_enabled"):
                detail += f"，无 running AudioContext，首交互后 isMuted()=false（已解除静音，gestures={auto.get('gestures')}）"
            else:
                detail += "（未开自动试玩，仅判首交互前）"
            checks.append(Check("CHK04", "首交互前静音", "pass", detail))

    # CHK05 横竖屏渲染非空白（画布像素方差阈值）
    shots = facts.get("viewport_shots") or {}
    if not shots.get("portrait", {}).get("has_canvas") and not shots.get("landscape", {}).get("has_canvas"):
        checks.append(skip("CHK05", "横竖屏渲染非空白", "页面无画布，跳过渲染判定"))
    else:
        threshold = float(facts.get("variance_threshold", 30.0))
        problems: list[str] = []
        for orient in ("portrait", "landscape"):
            shot = shots.get(orient) or {}
            if not shot.get("has_canvas"):
                problems.append(f"{orient}: 无画布")
                continue
            v = shot.get("variance")
            if v is None:
                problems.append(f"{orient}: 未取得截图方差")
            elif v < threshold:
                problems.append(f"{orient}: 像素方差 {v:.1f} < 阈值 {threshold:.0f}（疑似空白）")
        if problems:
            checks.append(Check("CHK05", "横竖屏渲染非空白", "fail", "；".join(problems)))
        else:
            vp = shots.get("portrait", {}).get("variance")
            vl = shots.get("landscape", {}).get("variance")
            checks.append(Check("CHK05", "横竖屏渲染非空白", "pass",
                                f"390×844 与 844×390 双仿真像素方差 {vp:.0f}/{vl:.0f} ≥ 阈值 {threshold:.0f}"))

    checks.append(skip("CHK06", "渠道退出接口调用", "未实装（渠道 stub 注入属 M8 后续里程碑）"))

    # CHK07 自动试玩到结束页（pf:end 真实触发 + 结束页可见）
    if not facts.get("autoplay_enabled"):
        checks.append(skip("CHK07", "自动试玩到结束页", "未开启 --autoplay，不驱动试玩"))
    elif not auto.get("qcHooksPresent"):
        checks.append(Check("CHK07", "自动试玩到结束页", "fail",
                            "页面未暴露 __PF_QC__（hint/state），无法自动试玩"))
    else:
        timeout = float(facts.get("autoplay_timeout_sec", 45.0))
        end_ms = auto.get("pfEndMs")
        problems: list[str] = []
        if not auto.get("pfEndFired") or end_ms is None:
            problems.append("pf:end 未触发")
        elif end_ms > timeout * 1000:
            problems.append(f"pf:end 于 {end_ms:.0f}ms 触发，超出 {timeout * 1000:.0f}ms 预算")
        if auto.get("reachedState") != "end":
            problems.append(f"最终 state={auto.get('reachedState')!r}（应为 end）")
        if auto.get("endScreenVisible") is not True:
            problems.append(f"结束页可见性={auto.get('endScreenVisible')}")
        if problems:
            checks.append(Check("CHK07", "自动试玩到结束页", "fail", "；".join(problems)))
        else:
            checks.append(Check("CHK07", "自动试玩到结束页", "pass",
                                f"pf:end 于 {end_ms:.0f}ms 触发（win={auto.get('pfEndWin')}，"
                                f"gestures={auto.get('gestures')}），结束页可见"))

    # CHK08 控制台零错误（两趟合并）
    console_errors = facts["console_errors"]
    if console_errors:
        shown = " | ".join(_clip(e, 160) for e in console_errors[:3])
        more = f"（另 {len(console_errors) - 3} 条略）" if len(console_errors) > 3 else ""
        checks.append(Check("CHK08", "控制台零错误", "fail",
                            f"{len(console_errors)} 条 error/pageerror：{shown}{more}"))
    else:
        checks.append(Check("CHK08", "控制台零错误", "pass", "两趟均无 console error 与 pageerror"))

    # CHK09 本地加载时长
    load_ms = facts["load_ms"]
    max_load_sec = facts["max_load_sec"]
    if load_ms <= max_load_sec * 1000:
        checks.append(Check("CHK09", f"本地加载 ≤{max_load_sec:g}s", "pass",
                            f"load 耗时 {load_ms:.0f}ms"))
    else:
        checks.append(Check("CHK09", f"本地加载 ≤{max_load_sec:g}s", "fail",
                            f"load 耗时 {load_ms:.0f}ms 超过阈值 {max_load_sec * 1000:.0f}ms"))

    checks.append(skip("CHK10", "多语言与 RTL", "未实装（locale 仿真属 M8 后续里程碑）"))
    return checks
