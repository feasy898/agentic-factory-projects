"""检查项判定（spec §6 判定表 + §6.1 规则数值；状态机 pass|fail|skip，冻结）。

skip 是显式声明"未测"，报告中保留 skip 字样，严禁标成 pass；skip 不算过（§2 退出码）。
"""

from __future__ import annotations

CHECK_NAMES = {
    "CHK01": "包体大小 ≤ 渠道上限",
    "CHK02": "文件数",
    "CHK03": "零外网",
    "CHK04": "首交互前静音",
    "CHK05": "横竖屏",
    "CHK06": "退出接口",
    "CHK07": "自动试玩到结束页",
    "CHK08": "控制台零错误",
    "CHK09": "本地加载",
    "CHK10": "多语言文案与素材上屏",
}


def _entry(cid: str, status: str, detail: str) -> dict:
    return {"id": cid, "name": CHECK_NAMES[cid], "status": status, "detail": detail}


def _chk01(f: dict) -> dict:
    """CHK01：artifact_bytes <= 规则库 maxBytes；规则库无该渠道/不可读 → skip（不假定）。"""
    max_bytes = f.get("channel_max_bytes")
    if max_bytes is None:
        return _entry("CHK01", "skip", "规则库不可读或无该渠道 maxBytes，不假定（spec §6.1）")
    size = f["artifact_bytes"]
    if size <= max_bytes:
        return _entry("CHK01", "pass", f"{size} 字节 ≤ 上限 {max_bytes} 字节")
    return _entry("CHK01", "fail", f"{size} 字节 > 渠道上限 {max_bytes} 字节")


def _chk02(_f: dict) -> dict:
    # 未实装（当前输入为单文件）——显式声明"未测"
    return _entry("CHK02", "skip", "未实装：当前输入为单文件 HTML，无文件数可清点（spec §1/§6）")


def _chk03(f: dict) -> dict:
    """CHK03：两趟合并——HTTP route abort 记账 + WebSocket 阻断记账 + SW 整体禁注册 +
    RTCPeerConnection 构造计数（不经过网络层拦截）。"""
    problems = []
    external = f.get("external_requests") or []
    websockets = f.get("websocket_urls") or []
    rtc = int(f.get("rtc_total") or 0)
    if external:
        problems.append(f"外网请求被拦截 {len(external)} 笔：{external[:3]}"
                        + ("…" if len(external) > 3 else ""))
    if websockets:
        problems.append(f"WebSocket 连接被阻断 {len(websockets)} 笔：{websockets[:3]}"
                        + ("…" if len(websockets) > 3 else ""))
    if rtc > 0:
        problems.append(f"RTCPeerConnection 构造 {rtc} 次（不经网络层拦截，直接违规）")
    if problems:
        return _entry("CHK03", "fail", "；".join(problems))
    return _entry(
        "CHK03", "pass",
        f"两趟合计 {f.get('request_count', 0)} 笔请求全部本地放行，"
        f"0 外网 / 0 WebSocket / 0 WebRTC（SW 已整体禁注册）",
    )


def _chk04(f: dict) -> dict:
    """CHK04：渠道要求静音（muteBeforeFirstInteraction，缺省 true）时逐项核验；
    无 window.PF 或探针未装 → fail（无法证明静音合规即违规，不再 skip）。"""
    if not f.get("mute_required"):
        return _entry("CHK04", "skip", "渠道未强制首交互前静音（spec §6/§6.1）")
    if not f.get("pf_present"):
        return _entry("CHK04", "fail", "页面无 window.PF 桥，无法证明首交互前静音合规")
    if not f.get("probe_installed"):
        return _entry("CHK04", "fail", "探针未安装，无法证明首交互前静音合规")
    shot = (f.get("viewport_shots") or {}).get("portrait") or {}
    problems = []
    first_muted = shot.get("firstMutedBeforeInteraction")
    if first_muted is not True:
        problems.append(f"首交互前 isMuted={first_muted}（须 true）")
    audio_running = shot.get("audioRunningBeforeInteraction")
    if audio_running is None or int(audio_running) > 0:
        problems.append(f"首交互前 running AudioContext={audio_running}（须 0）")
    media = (shot.get("probe") or {}).get("media") or {}
    if int(media.get("unmuted") or 0) > 0:
        problems.append(f"存在未静音媒体元素（重采样最坏值 {media.get('unmuted')} 个）")
    if int(media.get("playsBeforeFirst") or 0) > 0:
        problems.append(f"首交互前媒体 play() {media.get('playsBeforeFirst')} 次")
    if f.get("autoplay_enabled"):
        after = shot.get("mutedAfterFirstGesture")
        if after is not False:
            problems.append(f"首手势后 isMuted={after}（autoplay 须已解除静音=false）")
    if problems:
        return _entry("CHK04", "fail", "；".join(problems))
    detail = "首交互前静音合规（无出声上下文/未静音媒体/提前播放）"
    if f.get("autoplay_enabled"):
        detail += "；autoplay 首手势后已解除静音"
    return _entry("CHK04", "pass", detail)


def _chk05(f: dict) -> dict:
    """CHK05：无 canvas → skip；有 canvas：两趟方差均 ≥ 阈值（空白判定 64×64 灰度方差）。"""
    shots = f.get("viewport_shots") or {}
    portrait = shots.get("portrait") or {}
    landscape = shots.get("landscape") or {}
    if not (portrait.get("has_canvas") and landscape.get("has_canvas")):
        return _entry("CHK05", "skip", "页面无 canvas，横竖屏方差判定不适用")
    threshold = float(f.get("variance_threshold") or 0.0)
    pv = portrait.get("variance")
    lv = landscape.get("variance")
    if pv is not None and lv is not None and pv >= threshold and lv >= threshold:
        return _entry("CHK05", "pass", f"两趟 64×64 灰度方差 {pv:.1f}/{lv:.1f} 均 ≥ {threshold}")
    return _entry("CHK05", "fail", f"两趟方差 {pv}/{lv} 未同时 ≥ {threshold}（疑空白/横竖屏异常）")


def _chk06(_f: dict) -> dict:
    # 未实装（stub 注入属后续；期望值与真实 API 冲突，修正候选见 channel-adapters §3）
    return _entry("CHK06", "skip", "未实装：渠道退出 stub 注入属后续（spec §1/§6）")


def _chk07(f: dict) -> dict:
    """CHK07：无 __PF_QC__ → fail；需 pf:end 已触发且 ≤ 预算、终态=end、结束页可见，三者齐备。"""
    if not f.get("autoplay_enabled"):
        return _entry("CHK07", "skip", "未开启 --autoplay，未执行自动试玩（未测，不算通过）")
    shot = (f.get("viewport_shots") or {}).get("portrait") or {}
    if not shot.get("hasQcHook"):
        return _entry("CHK07", "fail", "页面无 __PF_QC__ 钩子，无法自动试玩驱动")
    budget_ms = float(f.get("autoplay_timeout_sec") or 0.0) * 1000.0
    problems = []
    if not shot.get("pfEndFired"):
        problems.append("pf:end 未触发")
    end_ms = shot.get("pfEndMs")
    if not isinstance(end_ms, (int, float)) or float(end_ms) > budget_ms:
        problems.append(f"pf:end={end_ms}ms 超预算（≤{budget_ms:.0f}ms）")
    if shot.get("reachedState") != "end":
        problems.append(f"终态={shot.get('reachedState')}（须 end）")
    if shot.get("endScreenVisible") is not True:
        problems.append(f"结束页可见性={shot.get('endScreenVisible')}（null=未证明可见）")
    if problems:
        return _entry("CHK07", "fail", "；".join(problems))
    return _entry("CHK07", "pass",
                  f"pf:end 于 {end_ms:.0f}ms 触发（≤{budget_ms:.0f}ms），终态=end，结束页可见")


def _chk08(f: dict) -> dict:
    """CHK08：两趟合并，console.error 或 pageerror 任一 → fail；
    网络源日志噪声（来源 URL ∈ 本次 abort 记账 blocked 集合）不计入——该违规归 CHK03。"""
    errors = f.get("console_errors") or []
    if errors:
        return _entry("CHK08", "fail", f"控制台错误 {len(errors)} 条：{errors[:3]}"
                                      + ("…" if len(errors) > 3 else ""))
    return _entry("CHK08", "pass", f"两趟合并 0 条页内 console.error/pageerror"
                                   f"（网络源噪声已按 blocked 归属过滤，spec §4）")


def _chk09(f: dict) -> dict:
    """CHK09：竖屏 load_ms ≤ max_load_sec×1000（加载计时只取竖屏趟）。"""
    load_ms = f.get("load_ms")
    limit_ms = float(f.get("max_load_sec") or 0.0) * 1000.0
    if load_ms is None:
        return _entry("CHK09", "fail", "竖屏 load 耗时缺失")
    if float(load_ms) <= limit_ms:
        return _entry("CHK09", "pass", f"竖屏 load {load_ms}ms ≤ {limit_ms:.0f}ms")
    return _entry("CHK09", "fail", f"竖屏 load {load_ms}ms > {limit_ms:.0f}ms")


def _chk10(f: dict) -> dict:
    """CHK10：--require-text 每条须 page_texts 子串命中 且 text_states 有 active+visible 采样
    证据（无 textStates 钩子 → 从严 fail）；--require-sprite 每键须 asset_audit replaced=true；
    两者都未提供 → skip（无判定对象不算通过）。"""
    required_texts = list(f.get("required_texts") or [])
    required_sprites = list(f.get("required_sprites") or [])
    if not required_texts and not required_sprites:
        return _entry("CHK10", "skip", "未提供 --require-text/--require-sprite，无判定对象"
                                       "（不算通过，spec §6）")
    problems = []
    if required_texts:
        if not f.get("text_states_hook"):
            problems.append("模板无 __PF_QC__.textStates 钩子：可见性无证据（从严 fail，spec §5.1）")
        else:
            known = {s.get("text"): bool(s.get("everVisible"))
                     for s in (f.get("text_states") or []) if isinstance(s, dict)}
            page_texts = [str(t) for t in (f.get("page_texts") or [])]
            for text in required_texts:
                if not any(str(text) in pt for pt in page_texts):
                    problems.append(f"文案未上屏：{text}")
                elif not known.get(str(text), False):
                    problems.append(f"文案无采样时刻 active+visible 证据：{text}")
    if required_sprites:
        audit = [a for a in (f.get("asset_audit") or []) if isinstance(a, dict)]
        for key in required_sprites:
            hit = any(a.get("spriteKey") == key and a.get("replaced") for a in audit)
            if not hit:
                if not audit:
                    problems.append(f"替换素材 {key}：页面未上报像素对账结果")
                else:
                    problems.append(f"替换素材 {key}：像素对账未判 replaced=true")
    if problems:
        return _entry("CHK10", "fail", "；".join(problems))
    return _entry("CHK10", "pass",
                  f"要求文案 {len(required_texts)} 条全部上屏且有可见性证据；"
                  f"要求素材 {len(required_sprites)} 键全部像素对账 replaced=true")


_ORDER = [_chk01, _chk02, _chk03, _chk04, _chk05, _chk06, _chk07, _chk08, _chk09, _chk10]


def build_checks(judgment: dict) -> list:
    """按 CHK01..CHK10 顺序判定。judgment = report.facts ∪ 内部判定输入
    （mute_required/probe_installed/rtc_total/websocket_urls）。"""
    return [fn(judgment) for fn in _ORDER]
