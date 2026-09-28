"""检查项定义（M8 规划十项；当前实装 CHK01/03/04/05/07/08/09/10）。

判定状态取值：pass / fail / skip。
- pass/fail：由本次无头打开过程真实测得；
- skip：检查项尚未实装（CHK02/06）或产物/配置不具备判定前提
  （如无 PF 桥且渠道未强制静音、无 --autoplay、CHK10 未提供
  --require-text/--require-sprite），不做任何假定结论。
  注意：渠道要求静音时（muteBeforeFirstInteraction 默认 true），
  CHK04 缺 PF 桥/探针不是 skip 而是 fail——无法证明静音合规即违规。
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

    # CHK03 零外网连接（横竖屏两趟合并判定）：
    # HTTP 请求由 route 拦截记账；WebSocket 由 route_web_socket 关闭并记账
    # （条目前缀 websocket:）；WebRTC 不经过网络层，由页面探针计数 RTCPeerConnection。
    external = facts["external_requests"]
    rtc = int(facts.get("rtc_connections") or 0)
    if external or rtc:
        shown = "；".join(_clip(u) for u in external[:5])
        more = f"（另 {len(external) - 5} 条略）" if len(external) > 5 else ""
        problems: list[str] = []
        if external:
            problems.append(f"发现 {len(external)} 条非本机请求/WebSocket，已拦截：{shown}{more}")
        if rtc:
            problems.append(f"页面构造了 {rtc} 次 RTCPeerConnection（WebRTC 外联尝试）")
        checks.append(Check("CHK03", "零外网请求", "fail", "；".join(problems)))
    else:
        checks.append(Check("CHK03", "零外网请求", "pass",
                            f"两趟共 {facts['request_count']} 条请求均指向本地伺服地址，"
                            "无外网请求、无外部 WebSocket、无 WebRTC 构造"))

    # CHK04 首交互前静音 + 首交互后允许出声（依赖 window.PF 与自动试玩）。
    # 渠道要求静音时（channel-rules muteBeforeFirstInteraction，默认 True）：
    # 缺 window.PF 或探针未安装一律 fail——没有桥/没有探针就无法证明静音合规，
    # 绝不放行；无音频页面改为断言"不存在未静音的媒体元素"（<audio>/<video>），
    # 而不是"缺少 AudioContext"，同时覆盖首交互前的媒体 play() 调用。
    pf_present = facts.get("pf_present")
    probe_installed = facts.get("probe_installed")
    mute_required = facts.get("channel_mute_required")
    auto = facts.get("autoplay") or facts.get("muteLoadTime") or {}
    if not pf_present:
        if mute_required:
            checks.append(Check(
                "CHK04", "首交互前静音", "fail",
                "渠道要求首交互前静音，但页面未装配 window.PF 桥，无法证明静音合规"))
        else:
            checks.append(skip("CHK04", "首交互前静音",
                               "页面未装配 window.PF 桥且渠道未强制静音，无可判定对象"))
    elif mute_required and probe_installed is not True:
        checks.append(Check(
            "CHK04", "首交互前静音", "fail",
            "渠道要求首交互前静音，但 qacore 探针未安装（__pfprobe 缺失），无法采证"))
    else:
        first_muted = auto.get("firstMutedBeforeInteraction")
        audio_running = auto.get("audioRunningBeforeInteraction")
        media_unmuted = int(auto.get("mediaUnmutedBeforeInteraction") or 0)
        media_plays = int(auto.get("mediaPlaysBeforeInteraction") or 0)
        after = auto.get("mutedAfterFirstGesture")
        problems: list[str] = []
        if first_muted is not True:
            problems.append(f"首交互前 PF.isMuted()={first_muted}")
        if audio_running not in (0, None):
            problems.append(f"首交互前存在 running AudioContext（{audio_running}）")
        if media_unmuted > 0:
            problems.append(f"存在 {media_unmuted} 个未静音的媒体元素（<audio>/<video>）")
        if media_plays > 0:
            problems.append(f"首交互前发生了 {media_plays} 次媒体播放调用（play()/autoplay）")
        if facts.get("autoplay_enabled") and after is not False:
            problems.append(f"首交互后 PF.isMuted()={after}（应为 False，即解除静音）")
        if problems:
            checks.append(Check("CHK04", "首交互前静音", "fail", "；".join(problems)))
        else:
            detail = "首交互前 PF.isMuted()=true，无未静音媒体元素"
            if facts.get("autoplay_enabled"):
                detail += (f"，无 running AudioContext，首交互后 isMuted()=false"
                           f"（已解除静音，gestures={auto.get('gestures')}）")
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

    # CHK10 多语言文案与素材上屏（2026-09-29 实装，扩展自规划项"多语言/RTL"；
    # 同日自证补强：字符串命中之外还须采样核验文案对象 active+visible）：
    # - required_texts：每条都须出现在页面渲染文案集合（画布文字不进 DOM，
    #   由模板经 __PF_QC__.texts() 上报；子串命中即算，如"得分"命中"得分 120"），
    #   且在 facts.text_states 中有"曾在采样时刻 active+visible"的证据——
    #   字符串登记后即销毁/隐藏的虚报（自证漏洞）由此堵死；教程等退场浮层
    #   由 qacore 在其在屏相位（自动试玩循环内）采样取证。模板未提供
    #   __PF_QC__.textStates 时可见性无证据，从严判 fail（同 CHK04 哲学：
    #   无法证明合规即不合规）。
    # - required_sprites：每键都须页面内像素对账通过（渲染贴图 vs 构建期内联
    #   用户 PNG，16×16 平均绝对差 ≤ 模板侧阈值，证据在 facts.asset_audit）。
    # 两者都未提供时保持 skip（无判定对象，不算通过）。判定通过≠人眼复核：
    #   演示上场前仍须对照报告截图人眼过一遍（docs/demo-checklist.md §3）。
    required_texts = [str(s) for s in (facts.get("required_texts") or []) if str(s)]
    required_sprites = [str(s) for s in (facts.get("required_sprites") or []) if str(s)]
    if not required_texts and not required_sprites:
        checks.append(skip("CHK10", "多语言文案与素材上屏",
                           "未提供 --require-text/--require-sprite，无判定对象（locale 仿真属后续）"))
    else:
        texts = facts.get("page_texts") or []
        states_hook = facts.get("text_states_hook")
        state_map = {s.get("text"): s for s in (facts.get("text_states") or [])
                     if isinstance(s, dict)}
        audit = {a.get("spriteKey"): a
                 for a in (facts.get("asset_audit") or []) if isinstance(a, dict)}
        problems: list[str] = []
        missing = [s for s in required_texts if not any(s in t for t in texts)]
        if missing:
            shown = "、".join(_clip(m, 24) for m in missing[:6])
            more = f"（另 {len(missing) - 6} 条略）" if len(missing) > 6 else ""
            problems.append(
                f"渲染文案集合（{len(texts)} 条）中未找到：{shown}{more}"
                + ("" if texts else "；页面未上报任何渲染文案（无 __PF_QC__.texts？）"))
        if states_hook is False:
            problems.append(
                "模板未提供 __PF_QC__.textStates()，文案可见性无法自证"
                "（上屏证据只有字符串登记，缺 active+visible 采样核验）")
        elif required_texts:
            never_visible = [
                s for s in required_texts
                if not any(s in t and v.get("everVisible") is True
                           for t, v in state_map.items() if isinstance(t, str))]
            if never_visible:
                shown = "、".join(_clip(m, 24) for m in never_visible[:6])
                more = f"（另 {len(never_visible) - 6} 条略）" if len(never_visible) > 6 else ""
                problems.append(
                    f"这些文案在全部采样（驱动前/自动试玩各相位/结束页）中从未处于 "
                    f"active+visible 状态：{shown}{more}")
        for key in required_sprites:
            a = audit.get(key)
            if a is None:
                problems.append(
                    f"替换素材 {key}：页面未上报像素对账结果（无 __PF_QC__.assets 或该键未嵌入）")
            elif a.get("replaced") is not True:
                problems.append(f"替换素材 {key}：像素对账未通过（{a.get('reason') or '平均差 ' + str(a.get('mad'))}）")
        if problems:
            checks.append(Check("CHK10", "多语言文案与素材上屏", "fail", "；".join(problems)))
        else:
            vis_note = ("，active+visible 采样核验通过" if states_hook else "")
            checks.append(Check(
                "CHK10", "多语言文案与素材上屏", "pass",
                f"渲染文案命中 {len(required_texts)}/{len(required_texts)}"
                f"（集合共 {len(texts)} 条{vis_note}）"
                + (f"；替换素材像素对账通过 {len(required_sprites)}/{len(required_sprites)}"
                   if required_sprites else "")))
    return checks
