"""合成层 (SPECS §5.6) — 零生成, 纯程序。

- 硬切: 各镜头 trim 到叙事模板幕时长后 concat(filter_complex, 时间轴精确); 短素材
  (调试口径 LTX 1.5625s) 用 tpad=stop_mode=clone hold-last-frame 补齐幕时长 (D-033)。
- 口播: 每幕 TTS, 自适应语速保证不超幕时长(D-032, 基准 -10%), atrim/apad 对齐幕时长;
  BGM 可选(程序合成 build_bgm_argv) + sidechaincompress ducking(≈-12dB, D-006)。
- 字幕: ASS 生成(默认 Noto Sans CJK) + ffmpeg burn-in, 时间轴与 TTS 对齐。
- G6 合成级硬校验(D-011): 烧录的 ASS Dialogue 与模板渲染文本逐字比对(硬性);
  可选 TTS→ASR 回转 CER≤5%(normalize_for_cer 归一化后计算)。
- 数字强制: 价格/优惠等数字只出现在模板 numbers 字段 → 只进字幕/贴片, 绝不进生成画面
  (compose 的文本仅来自模板 narration/numbers, 不接触镜头卡 prompt 字段)。
- 输出 H.264 竖版 1088×1920 (横版备选 1920×1088)。
- 所有 ffmpeg 命令构建为纯函数返回 argv, 可 dry-run 单测。
"""

from __future__ import annotations

import html
import inspect
import json
import math
import re
import subprocess

PORTRAIT_OUT = (1088, 1920)
LANDSCAPE_OUT = (1920, 1088)
DEFAULT_FONT = "Noto Sans CJK SC"
DEFAULT_FONT_SIZE = 64
DUCK_DB_DEFAULT = -12.0
DEFAULT_RATE = "-10%"          # SPECS §5.6 口播基准语速
RATE_FLOOR = -10.0             # 自适应语速下限(不慢于基准)
RATE_CEIL = 100.0              # 自适应语速上限(快于 +100% 视为模板文案与幕时长不可调和)


def out_size(orientation: str) -> tuple[int, int]:
    if orientation == "portrait":
        return PORTRAIT_OUT
    if orientation == "landscape":
        return LANDSCAPE_OUT
    raise ValueError(f"orientation 只支持 portrait/landscape, 收到 {orientation!r}")


# ---------------- 文本/时间轴 ----------------

def render_narration(scenes: list[dict], variables: dict, numbers: dict) -> list[str]:
    """渲染每幕口播文本。占位符只允许 variables∪numbers 中已定义的字段。"""
    allowed = {**{k: str(v) for k, v in (variables or {}).items()},
               **{k: str(v) for k, v in (numbers or {}).items()}}
    out = []
    for sc in scenes:
        try:
            out.append(str(sc["narration"]).format_map(allowed))
        except KeyError as e:
            raise KeyError(f"模板 narration 引用了未定义变量: {e} (数字只可来自 numbers 字段)") from e
    return out


def build_cues(scene_durations: list[float], texts: list[str]) -> list[tuple[float, float, str]]:
    """按幕时长累加得到字幕时间轴 [(start, end, text)]。"""
    cues = []
    t = 0.0
    for d, text in zip(scene_durations, texts):
        cues.append((round(t, 3), round(t + float(d), 3), text))
        t += float(d)
    return cues


# ---------------- 自适应语速 (D-032) ----------------

def parse_rate(rate: str) -> float:
    """edge-tts 语速串 '+12%'/'-10%' → 百分数 float。"""
    return float(str(rate).strip().rstrip("%"))


def format_rate(v: float) -> str:
    return f"{int(round(v)):+d}%"


def _supports_rate_kwarg(tts_fn) -> bool:
    try:
        sig = inspect.signature(tts_fn)
    except (TypeError, ValueError):  # builtin 无签名
        return False
    for p in sig.parameters.values():
        if p.kind == inspect.Parameter.VAR_KEYWORD or p.name == "rate":
            return True
    return False


def fit_tts_to_scene(
    tts_fn,
    text: str,
    out_path: str,
    scene_dur: float,
    probe_fn=None,
    base_rate: str = DEFAULT_RATE,
    margin: float = 0.10,
    max_iters: int = 6,
) -> dict:
    """生成单幕口播并自适应语速, 保证音频时长 ≤ 幕时长-margin(避免 atrim 截字)。

    语速-时长近似线性(dur ∝ 1/(1+rate/100)), 每轮按实测解方程预测下一档语速,
    最多 max_iters 轮; 触顶仍超长则保留最快档并标记 truncated=True (如实上报)。
    tts_fn 不支持 rate 形参时退化为单次调用(atrim 兜底)。
    返回 {"path","rate","duration_s","truncated","attempts":[{rate,duration_s}]}。
    """
    if probe_fn is None:
        probe_fn = probe_media_duration
    supports = _supports_rate_kwarg(tts_fn)
    attempts: list[dict] = []
    rate = base_rate
    last_dur = None

    for _ in range(max_iters):
        if supports:
            tts_fn(text, out_path, rate=rate)
        else:
            tts_fn(text, out_path)
        try:
            last_dur = float(probe_fn(out_path))
        except Exception:  # noqa: BLE001 — 探测失败则交由 atrim 兜底
            last_dur = None
            break
        attempts.append({"rate": rate, "duration_s": round(last_dur, 3)})
        if last_dur <= float(scene_dur) - margin:
            return {"path": out_path, "rate": rate, "duration_s": round(last_dur, 3),
                    "truncated": False, "attempts": attempts}
        if not supports:
            break  # 旧契约无法调速, 只跑一次, 交由 atrim 兜底
        # 预测: normal = dur * speed_now; 需要 need → rate_pct = ceil((normal/need-1)*100)+1
        speed_now = 1.0 + parse_rate(rate) / 100.0
        normal = last_dur * speed_now
        need = max(0.1, float(scene_dur) - margin)
        pred = float(math.ceil((normal / need - 1.0) * 100.0) + 1)
        pred = max(RATE_FLOOR, min(RATE_CEIL, pred))
        new_rate = format_rate(pred)
        if new_rate == rate:
            break  # 已触顶仍超长
        rate = new_rate
    return {"path": out_path, "rate": rate, "duration_s": last_dur, "truncated": True,
            "attempts": attempts}


# ---------------- CER 归一化 (D-034) ----------------

_ZH_DIGITS = "零一二三四五六七八九"


def _int_to_zh(n: int) -> str:
    """阿拉伯整数 → 中文读法 (0..9999 精确, 更大逐位, 覆盖口播数字量级)。"""
    if n < 0:
        return "负" + _int_to_zh(-n)
    if n < 10:
        return _ZH_DIGITS[n]
    if n < 20:
        return "十" + (_ZH_DIGITS[n % 10] if n % 10 else "")
    if n < 100:
        return _ZH_DIGITS[n // 10] + "十" + (_ZH_DIGITS[n % 10] if n % 10 else "")
    if n < 1000:
        s = _ZH_DIGITS[n // 100] + "百"
        r = n % 100
        if r == 0:
            return s
        if r < 10:
            return s + "零" + _ZH_DIGITS[r]
        return s + _int_to_zh(r)
    if n < 10000:
        s = _ZH_DIGITS[n // 1000] + "千"
        r = n % 1000
        if r == 0:
            return s
        if r < 100:
            return s + "零" + _int_to_zh(r)
        return s + _int_to_zh(r)
    return "".join(_ZH_DIGITS[int(c)] for c in str(n))


def _num_to_zh(m: re.Match) -> str:
    s = m.group(0)
    if "." in s:
        ip, fp = s.split(".", 1)
        frac = "".join(_ZH_DIGITS[int(c)] for c in fp if c.isdigit())
        return _int_to_zh(int(ip)) + ("点" + frac if frac else "")
    return _int_to_zh(int(s))


def normalize_for_cer(text: str) -> str:
    """ASR 回转比对归一化: 阿拉伯数字→中文读法(与 TTS 朗读一致), 去标点/空白/符号, casefold。"""
    s = re.sub(r"\d+(?:\.\d+)?", _num_to_zh, str(text))
    s = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", s)
    return s.casefold()


def ass_time(sec: float) -> str:
    """ASS 时间格式 H:MM:SS.CC (厘秒, 四舍五入带进位)。"""
    total_cs = int(round(max(0.0, float(sec)) * 100))
    h = total_cs // 360000
    m = (total_cs % 360000) // 6000
    s = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass_lines(
    cues: list[tuple[float, float, str]],
    width: int = PORTRAIT_OUT[0],
    height: int = PORTRAIT_OUT[1],
    font: str = DEFAULT_FONT,
    font_size: int = DEFAULT_FONT_SIZE,
) -> list[str]:
    """生成 ASS 文件行(不落盘), 便于单测。"""
    lines = [
        "[Script Info]",
        "; Generated by PROJECT CRADLE compose",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,2,1,2,60,60,140,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, text in cues:
        safe = html.escape(str(text), quote=False).replace("\n", "\\N")
        lines.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{safe}"
        )
    return lines


def write_ass(cues, path: str, width: int, height: int, font: str = DEFAULT_FONT, font_size: int = DEFAULT_FONT_SIZE) -> str:
    lines = build_ass_lines(cues, width, height, font, font_size)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def parse_ass_dialogues(path: str) -> list[str]:
    """按序回读 ASS Dialogue 文本(G6 合成级逐字比对用)。Text 为第 10 个逗号字段。"""
    out: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("Dialogue:"):
                continue
            parts = line[len("Dialogue:"):].split(",", 9)
            text = parts[9] if len(parts) == 10 else ""
            out.append(html.unescape(text.replace("\\N", "\n")))
    return out


def escape_ass_filter_path(path: str) -> str:
    """ffmpeg filter 参数中路径转义 (ass=filename)。"""
    p = path.replace("\\", "/")
    p = p.replace(":", "\\:").replace("'", "\\'")
    return p


# ---------------- ffmpeg 命令构建(纯函数) ----------------

def build_scale_chain(w: int, h: int) -> str:
    """归一化画幅: 等比缩放+pad 补边(硬切不变形)。"""
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"
    )


def build_compose_argv(
    video_paths: list[str],
    scene_durations: list[float],
    voice_path: str,
    ass_path: str,
    out_path: str,
    orientation: str = "portrait",
    fps: int = 16,
    bgm_path: str | None = None,
    duck_db: float = DUCK_DB_DEFAULT,
    crf: int = 20,
    video_durations: list[float | None] | None = None,
) -> list[str]:
    """终混 argv: 视频 trim→(tpad 补齐)→concat→scale/pad→ass 烧录; 音频 trim/pad→concat→(bgm ducking)→mix。

    video_paths 条目为文件路径, 或 "color:<ffmpeg颜色>" 哨兵(程序渲染纯色贴片段, 如 CTA 字卡)。
    video_durations 与 video_paths 对齐(条目可为 None=未知/不补): 素材短于幕时长时用
    tpad=stop_mode=clone hold-last-frame 补齐(D-033); 长于幕时长仍由 trim 硬切。
    """
    w, h = out_size(orientation)
    n = len(video_paths)
    if n == 0:
        raise ValueError("没有可合成的镜头")
    if len(scene_durations) != n:
        raise ValueError(f"镜头数 {n} 与幕时长数 {len(scene_durations)} 不一致")
    if video_durations is not None and len(video_durations) != n:
        raise ValueError(f"video_durations 长度 {len(video_durations)} 与镜头数 {n} 不一致")

    inputs: list[str] = []
    for p, dur in zip(video_paths, scene_durations):
        if p.startswith("color:"):
            inputs += ["-f", "lavfi", "-i",
                       f"color=c={p[6:]}:s={w}x{h}:r={fps}:d={float(dur):.3f}"]
        else:
            inputs += ["-i", p]
    inputs += ["-i", voice_path]
    voice_idx = n
    bgm_idx = None
    if bgm_path:
        bgm_idx = n + 1
        inputs += ["-i", bgm_path]

    parts = []
    for i, dur in enumerate(scene_durations):
        chain = f"[{i}:v]trim=duration={float(dur):.3f},setpts=PTS-STARTPTS"
        vd = video_durations[i] if video_durations else None
        if not video_paths[i].startswith("color:") and vd is not None:
            pad = float(dur) - float(vd)
            if pad > 1e-3:
                chain += (f",tpad=stop_mode=clone:stop_duration={pad:.3f},"
                          f"trim=duration={float(dur):.3f},setpts=PTS-STARTPTS")
        parts.append(chain + f",{build_scale_chain(w,h)}[v{i}]")
    vcat = "".join(f"[v{i}]" for i in range(n))
    parts.append(f"{vcat}concat=n={n}:v=1:a=0[vcat]")
    parts.append(f"[vcat]ass={escape_ass_filter_path(ass_path)}[vout]")

    if bgm_path is None:
        total = sum(scene_durations)
        parts.append(
            f"[{voice_idx}:a]atrim=duration={total:.3f},asetpts=PTS-STARTPTS,apad=whole_dur={total:.3f}[aout]"
        )
    else:
        lin = 10 ** (float(duck_db) / 20.0)
        parts.append(
            f"[{bgm_idx}:a]volume={lin:.4f}[bg0];"
            f"[bg0][{voice_idx}:a]sidechaincompress=threshold=0.03:ratio=12:attack=25:release=400[bgd];"
            f"[{voice_idx}:a][bgd]amix=inputs=2:duration=first:normalize=0[aout]"
        )

    argv = ["ffmpeg", "-y", "-hide_banner", "-nostats", *inputs,
            "-filter_complex", ";".join(parts),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-c:a", "aac", "-b:a", "160k",
            "-shortest", "-movflags", "+faststart",
            out_path]
    return argv


def build_probe_duration_argv(path: str) -> list[str]:
    return ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]


def probe_media_duration(path: str, runner=subprocess.run) -> float | None:
    """音频/视频通用的时长探测(仅 format.duration); 失败返回 None。

    g1_tech.probe_duration 要求视频流, 对 mp3/wav 纯音频会抛异常, 故此处独立实现。
    """
    try:
        cp = runner(build_probe_duration_argv(path), capture_output=True, text=True, timeout=120)
        if cp.returncode != 0:
            return None
        return float(json.loads(cp.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001 — 探测失败按未知处理
        return None


# ---------------- 编排计划 ----------------

def plan_compose(template: dict, video_by_slot: dict[str, str], variables: dict | None = None,
                 numbers: dict | None = None) -> dict:
    """依据叙事模板与「narrative_slot 或 scene.slot → 视频路径」构建合成计划。

    - 带 background 的幕(如 CTA 字卡/优惠字卡)为程序渲染纯色贴片段, 不需要镜头视频,
      数字只经 numbers 字段进入字幕 (SPECS §5.6 硬性)。
    - 钩子段(0-3s)允许 1s 短镜头。
    - 同 narrative_slot 可复用/替换镜头卡 —— 变体能力的来源 (SPECS §5.7)。
    """
    scenes = template["scenes"]

    def resolve(sc: dict):
        return video_by_slot.get(sc["slot"]) or video_by_slot.get(sc["narrative_slot"])

    missing = [sc["slot"] for sc in scenes if not sc.get("background") and resolve(sc) is None]
    if missing:
        raise ValueError(f"缺少 narrative_slot 对应的已验收镜头: {missing}")

    durations = [float(sc["duration_sec"]) for sc in scenes]
    texts = render_narration(scenes, variables if variables is not None else template.get("variables", {}),
                             numbers if numbers is not None else template.get("numbers", {}))
    cues = build_cues(durations, texts)
    video_paths = []
    for sc in scenes:
        bg = sc.get("background")
        if bg:
            video_paths.append(f"color:{bg.get('color', 'black')}")
        else:
            video_paths.append(resolve(sc))
    return {
        "template_id": template["template_id"],
        "orientation": template["orientation"],
        "slots": [sc["narrative_slot"] for sc in scenes],
        "video_paths": video_paths,
        "scene_durations": durations,
        "narration": texts,
        "cues": cues,
        "total_duration": round(sum(durations), 3),
        "numbers_used": dict(numbers if numbers is not None else template.get("numbers", {})),
    }


def build_bgm_argv(duration_sec: float, out_path: str, sample_rate: int = 44100) -> list[str]:
    """程序合成简单 BGM argv: G 大三和弦正弦叠加 + 慢 tremolo + 低通(无版权风险, D-035)。

    成片终混时再经 -12dB 预衰减 + sidechaincompress ducking (D-006)。
    """
    d = f"{float(duration_sec):.3f}"
    sr = f":sample_rate={int(sample_rate)}"
    fc = "[0:a][1:a][2:a]amix=inputs=3:normalize=1," \
         "tremolo=f=0.4:d=0.35,lowpass=f=1500,volume=0.9[aout]"
    return ["ffmpeg", "-y", "-hide_banner", "-nostats",
            "-f", "lavfi", "-i", f"sine=frequency=196{sr}:duration={d}",
            "-f", "lavfi", "-i", f"sine=frequency=246.94{sr}:duration={d}",
            "-f", "lavfi", "-i", f"sine=frequency=293.66{sr}:duration={d}",
            "-filter_complex", fc, "-map", "[aout]",
            "-c:a", "aac", "-b:a", "128k", out_path]


def compose_g6(
    plan: dict,
    ass_path: str,
    media_path: str,
    asr_fn=None,
    runner=subprocess.run,
    cer_max: float = 0.05,
) -> dict:
    """G6 合成级硬校验(D-011): ① 烧录 ASS vs 模板渲染文本逐字比对(硬性);
    ② 可选 TTS→ASR 回转: 从成片提取音轨 → asr_fn() → normalize_for_cer 归一化后 CER。
    asr_fn 未提供/异常 → 跳过 CER 并记录(asr_skipped/asr_error), 不阻塞(硬性仅逐字项)。
    """
    from .gates import make_gate
    from .gates.g6_business import cer as cer_fn, check_subtitle_exact

    expected = list(plan["narration"])
    actual = parse_ass_dialogues(ass_path)
    sub_ok, sub_detail = check_subtitle_exact(expected, actual)

    cer_val = None
    asr_skipped = True
    asr_error = None
    hyp_raw = None
    hyp_norm = None
    if asr_fn is not None:
        try:
            wav = f"{media_path}.g6audio.wav"
            argv = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", media_path,
                    "-vn", "-ac", "1", "-ar", "16000", wav]
            cp = runner(argv, capture_output=True, text=True, timeout=300)
            if cp.returncode != 0:
                raise RuntimeError(f"音轨提取失败: {cp.stderr[-200:]}")
            hyp_raw = str(asr_fn(wav)).strip()
            ref_norm = normalize_for_cer("".join(expected))
            hyp_norm = normalize_for_cer(hyp_raw)
            cer_val = cer_fn(ref_norm, hyp_norm)
            asr_skipped = False
        except Exception as e:  # noqa: BLE001 — ASR 不可用跳过并记录(SPECS §2)
            asr_error = str(e)[:300]

    cer_ok = True if cer_val is None else cer_val <= float(cer_max)
    passed = bool(sub_ok and cer_ok)
    score = 1.0 if passed else (round(max(0.0, 1.0 - (cer_val or 0.0)), 4) if sub_ok else 0.0)
    return make_gate(
        "G6", passed, score,
        stage="compose",
        subtitle_exact=sub_ok, subtitle_detail=sub_detail,
        cer=cer_val, cer_max=cer_max, asr_skipped=asr_skipped,
        asr_error=asr_error, asr_hyp_raw=hyp_raw, asr_hyp_normalized=hyp_norm,
        expected_narration="".join(expected),
    )


def compose_group(
    plan: dict,
    out_path: str,
    ass_path: str,
    tts_fn,
    runner=subprocess.run,
    bgm_path: str | None = None,
    probe_fn=None,
    asr_fn=None,
    base_rate: str = DEFAULT_RATE,
    run_g6: bool = True,
    cer_max: float = 0.05,
) -> dict:
    """执行合成: 每幕自适应语速 TTS → 拼音轨 → 终混 → G6 合成级硬校验。

    - TTS: fit_tts_to_scene 保证每幕口播不超幕时长(D-032); tts_fn 支持 rate 形参才启用。
    - 视频: 逐幕探测素材时长, 短素材 tpad hold-last-frame 补齐(D-033), 色卡幕不探测。
    - G6(D-011): ASS Dialogue 与模板渲染文本逐字比对(硬性); asr_fn 提供时做
      TTS→ASR 回转 CER(归一化 D-034), asr 异常/未提供 → 跳过并记录, 不阻塞合成。
    返回 dict 含 path/ass/total_duration/tts(逐幕)/g6。
    """
    if probe_fn is None:
        probe_fn = probe_media_duration

    tts_info = []
    voice_files = []
    for i, text in enumerate(plan["narration"]):
        p = f"{out_path}.voice{i}.mp3"
        info = fit_tts_to_scene(tts_fn, text, p, plan["scene_durations"][i],
                                probe_fn=probe_fn, base_rate=base_rate)
        tts_info.append({"scene": i, "text": text, **{k: v for k, v in info.items() if k != "path"}})
        voice_files.append(p)
    voice_all = f"{out_path}.voice.m4a"
    if len(voice_files) == 1:
        voice_all = voice_files[0]
    else:
        argv = build_voice_concat_argv(voice_files, voice_all, scene_durations=plan["scene_durations"])
        cp = runner(argv, capture_output=True, text=True, timeout=600)
        if cp.returncode != 0:
            raise RuntimeError(f"口播音轨合成失败: {cp.stderr[-300:]}")

    w, h = out_size(plan["orientation"])
    write_ass(plan["cues"], ass_path, w, h)

    video_durations: list[float | None] = []
    for p in plan["video_paths"]:
        if p.startswith("color:"):
            video_durations.append(None)
            continue
        try:
            video_durations.append(float(probe_fn(p)))
        except Exception:  # noqa: BLE001 — 探测失败按未知处理(不 tpad)
            video_durations.append(None)

    argv = build_compose_argv(
        plan["video_paths"], plan["scene_durations"], voice_all, ass_path, out_path,
        orientation=plan["orientation"], bgm_path=bgm_path,
        video_durations=video_durations,
    )
    cp = runner(argv, capture_output=True, text=True, timeout=1800)
    if cp.returncode != 0:
        raise RuntimeError(f"终混失败: {cp.stderr[-400:]}")

    result = {"path": out_path, "ass": ass_path, "total_duration": plan["total_duration"],
              "tts": tts_info, "video_durations": video_durations}

    g6: dict = {}
    if run_g6:
        g6 = compose_g6(plan, ass_path, out_path, asr_fn=asr_fn, runner=runner, cer_max=cer_max)
    result["g6"] = g6
    return result


def build_voice_concat_argv(audio_paths: list[str], out_path: str, scene_durations: list[float]) -> list[str]:
    """多幕 TTS → 每段 atrim/apad 到幕时长 → concat a=1 (时间轴精确)。"""
    n = len(audio_paths)
    if n != len(scene_durations):
        raise ValueError("TTS 段数与幕时长数不一致")
    inputs: list[str] = []
    for p in audio_paths:
        inputs += ["-i", p]
    parts = []
    for i, dur in enumerate(scene_durations):
        parts.append(
            f"[{i}:a]atrim=duration={float(dur):.3f},asetpts=PTS-STARTPTS,apad=whole_dur={float(dur):.3f}[a{i}]"
        )
    cat = "".join(f"[a{i}]" for i in range(n))
    parts.append(f"{cat}concat=n={n}:v=0:a=1[aout]")
    return ["ffmpeg", "-y", "-hide_banner", "-nostats", *inputs,
            "-filter_complex", ";".join(parts),
            "-map", "[aout]", "-c:a", "aac", "-b:a", "160k", out_path]
