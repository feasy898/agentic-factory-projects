"""检查项判定（SPEC qacore.md §6 判定表）。

状态机取值 pass|fail|skip；skip 是显式声明"未测"，报告中保留 skip 字样，严禁标成 pass。
判定输入 ev 为报告 facts + 试玩取证 assembled dict（见 cli._cmd_run 组装）。
"""

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


def _check(cid: str, status: str, detail: str) -> dict:
    return {"id": cid, "name": CHECK_NAMES[cid], "status": status, "detail": detail}


def evaluate(ev: dict) -> list:
    """返回 CHK01..CHK10 十项判定（固定顺序）。"""
    return [
        _chk01(ev), _chk02(ev), _chk03(ev), _chk04(ev), _chk05(ev),
        _chk06(ev), _chk07(ev), _chk08(ev), _chk09(ev), _chk10(ev),
    ]


def _chk01(ev):
    mx = ev.get("channel_max_bytes")
    if mx is None:
        return _check("CHK01", "skip", "规则库无该渠道，不假定体积上限")
    n = int(ev.get("artifact_bytes") or 0)
    if n <= mx:
        return _check("CHK01", "pass", f"{n} B ≤ 渠道上限 {mx} B")
    return _check("CHK01", "fail", f"{n} B 超过渠道上限 {mx} B")


def _chk02(ev):
    return _check("CHK02", "skip", "未实装（当前输入为单文件）")


def _chk03(ev):
    ext = ev.get("external_requests") or []
    rtc = int(ev.get("rtc_count") or 0)
    if not ext and rtc == 0:
        return _check("CHK03", "pass", "两趟零外网请求/WebSocket/WebRTC")
    parts = []
    if ext:
        shown = "; ".join(ext[:3]) + ("…" if len(ext) > 3 else "")
        parts.append(f"拦截外网/WS {len(ext)} 条：{shown}")
    if rtc:
        parts.append(f"RTCPeerConnection 构造 {rtc} 次")
    return _check("CHK03", "fail", "；".join(parts))


def _chk04(ev):
    if not ev.get("mute_required"):
        if ev.get("pf_present"):
            return _check("CHK04", "pass", "渠道未强制静音，桥存在，无违例判定对象")
        return _check("CHK04", "skip", "渠道未强制静音且无桥")
    if not ev.get("pf_present") or not ev.get("probe_present"):
        return _check("CHK04", "fail", "无 window.PF 或探针未装：无法证明静音合规即违规")
    problems = []
    if ev.get("muted_before_first_interaction") is not True:
        problems.append("首交互前 isMuted!=true")
    if int(ev.get("audio_running_before_interaction") or 0) > 0:
        problems.append("首交互前存在 running AudioContext")
    if int(ev.get("media_unmuted_before_first") or 0) > 0:
        problems.append("首交互前存在未静音媒体元素")
    if int(ev.get("plays_before_first") or 0) > 0:
        problems.append("首交互前发生媒体 play()")
    if ev.get("autoplay_enabled") and ev.get("muted_after_first_gesture") is not False:
        problems.append("首手势后未解除静音")
    if problems:
        return _check("CHK04", "fail", "；".join(problems))
    detail = "首交互前静音合规"
    if ev.get("autoplay_enabled"):
        detail += "；首手势后已解除静音"
    return _check("CHK04", "pass", detail)


def _chk05(ev):
    shots = ev.get("viewport_shots") or {}
    p = shots.get("portrait") or {}
    l = shots.get("landscape") or {}
    if not (p.get("has_canvas") or l.get("has_canvas")):
        return _check("CHK05", "skip", "页面无 canvas")
    thr = float(ev.get("variance_threshold") or 30.0)
    vp, vl = p.get("variance"), l.get("variance")
    if vp is None or vl is None:
        return _check("CHK05", "fail", "截屏方差缺失")
    if vp >= thr and vl >= thr:
        return _check("CHK05", "pass", f"竖屏方差 {vp:.1f} / 横屏方差 {vl:.1f} ≥ 阈值 {thr}")
    return _check("CHK05", "fail", f"竖屏方差 {vp:.1f} / 横屏方差 {vl:.1f}，低于阈值 {thr}")


def _chk06(ev):
    return _check("CHK06", "skip", "未实装（退出接口 stub 注入属后续）")


def _chk07(ev):
    if not ev.get("autoplay_enabled"):
        return _check("CHK07", "skip", "未请求自动试玩")
    if not ev.get("has_qc_hook"):
        return _check("CHK07", "fail", "页面无 __PF_QC__ 钩子")
    fired = bool(ev.get("pf_end_fired"))
    ms = ev.get("pf_end_ms")
    budget = float(ev.get("autoplay_timeout_sec") or 45.0) * 1000.0
    state = ev.get("reached_state")
    vis = ev.get("end_screen_visible")
    problems = []
    if not fired:
        problems.append("pf:end 未触发")
    elif ms is None or float(ms) > budget:
        problems.append(f"pf:end 超预算（{ms}ms > {budget:.0f}ms）")
    if state != "end":
        problems.append(f"终态={state} ≠ end")
    if vis is not True:
        problems.append("结束页可见性无证据" if vis is None else "结束页不可见")
    if problems:
        return _check("CHK07", "fail", "；".join(problems))
    return _check("CHK07", "pass", f"pf:end 于 {ms:.0f}ms 触发（win={ev.get('pf_end_win')}），终态 end，结束页可见")


def _chk08(ev):
    errs = ev.get("console_errors") or []
    if errs:
        shown = "; ".join(errs[:3]) + ("…" if len(errs) > 3 else "")
        return _check("CHK08", "fail", f"控制台错误 {len(errs)} 条：{shown}")
    return _check("CHK08", "pass", "两趟 console.error / pageerror 均为零")


def _chk09(ev):
    lm = ev.get("load_ms")
    budget = float(ev.get("max_load_sec") or 2.0) * 1000.0
    if lm is None:
        return _check("CHK09", "fail", "未取得竖屏趟 load 耗时")
    if float(lm) <= budget:
        return _check("CHK09", "pass", f"竖屏 load {lm:.0f}ms ≤ {budget:.0f}ms")
    return _check("CHK09", "fail", f"竖屏 load {lm:.0f}ms 超过 {budget:.0f}ms")


def _chk10(ev):
    req_t = ev.get("required_texts") or []
    req_s = ev.get("required_sprites") or []
    if not req_t and not req_s:
        return _check("CHK10", "skip", "未提供 --require-text/--require-sprite，无判定对象")
    problems = []
    texts = ev.get("page_texts") or []
    states = {d.get("text"): d for d in (ev.get("text_states") or []) if isinstance(d, dict)}
    for t in req_t:
        if not any(t in s for s in texts):
            problems.append(f"文案未上屏：{t}")
        elif not states.get(t, {}).get("everVisible"):
            # 模板无 __PF_QC__.textStates 时无证据即 fail，从严（SPEC §6 CHK10）
            problems.append(f"文案无可见性自证证据：{t}")
    audit = {d.get("spriteKey"): d for d in (ev.get("asset_audit") or []) if isinstance(d, dict)}
    for k in req_s:
        d = audit.get(k)
        if not (isinstance(d, dict) and d.get("replaced") is True):
            problems.append(f"替换素材 {k}：页面未上报像素对账结果")
    if problems:
        return _check("CHK10", "fail", "；".join(problems))
    return _check("CHK10", "pass", f"文案 {len(req_t)} 条全部命中且有可见性证据；素材 {len(req_s)} 键像素对账 replaced 全真")
