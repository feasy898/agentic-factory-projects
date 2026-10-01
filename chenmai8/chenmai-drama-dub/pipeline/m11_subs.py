"""M11 字幕擦除 + 目标语渲染（规划 §4 M11，【本机】CPU 验收）。

Spec（§4 M11）：
  ① 擦除：消费 M2 检出的字幕行（``03_ocr/ocr_merged.jsonl``，bbox=全片像素）
     → 每行 bbox 外扩 ``expand_px`` → 裁剪进 ``erase_band`` 擦除带 →
     **排除 label_zone AI 标识区**（configs/pipeline.yaml）→ 按行起止时间窗
     逐条擦除：
       - ``delogo``：ffmpeg delogo 滤镜按时间窗插值填充（轻量默认路径，
         本机离线可用；产物用无损 x264，保证擦除带外像素零改动）；
       - ``inpaint``：cv2 inpaint 按帧掩膜修复（TELEA，慢一档、质量高）；
       - ``vsr``：重型路线（models.yaml cap-clean 所指上游类）**接口预留、
         不安装**——选中即如实报错并提示轻量路径，不静默降级。
  ② 渲染：C2 句窗 × C4 选定译文 → 目标语 ASS（en/es 左下对齐、
     ar 右对齐 RTL；字体 Noto Sans / 微软雅黑 / Noto Naskh Arabic）→
     ``ffmpeg -vf ass=`` 压制（libass+fribidi+harfbuzz，阿语由
     libass 渲染期做 bidi+shaping，**本模块不做预反转/预整形**）→
     ``12_out/<ep>.<lang>.mp4``；源语 ``10_subs/src.ass`` 由 C2 生成
     （人工审校回看口径）。

契约与边界（B1 冻结规则 9：只通过契约交换）：
  - 只读：01_media 视频、03_ocr/ocr_merged.jsonl、06_mt/translations.jsonl、
    04_dial/utterances.jsonl；不写任何冻结契约（C2/C4 一律只读）。
  - 写入：01_media/video_1080x1920_25fps_clean.mp4（擦除基带）、
    10_subs/{src.ass,tgt.<lang>.ass}、12_out/<ep>.<lang>.mp4。
  - OCR 行 bbox 视为全片像素坐标；``run`` 按帧几何（configs media）裁剪，
    越界/出带区域如实计入 summary 统计（不静默吞）。

中性名纪律：引擎中性名 cap-ocr（OCR 输入）、cap-clean（重型擦除后端，
models.yaml 登记、本批仅接口）；上游真名不入公开文本（同 B1 纪律）。

CLI（规划 §4 冻结形态）::

    python -m pipeline.m11_subs --ep ep01 --lang ar [--skip-erase]
    python -m pipeline.m11_subs --ep ep01 --lang en --engine inpaint [--no-burn]

退出码：0 成功；1 输入/产物/执行错误；2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.scaffold import ep_dir

__all__ = [
    "M11Error",
    "EraseRegion",
    "EraseInputLine",
    "AssEvent",
    "SubStyle",
    "label_zone_rect",
    "expand_rect",
    "clip_to_band",
    "subtract_label_zone",
    "build_erase_regions",
    "delogo_chain",
    "DelogoBackend",
    "InpaintBackend",
    "VsrCleanBackend",
    "get_backend",
    "ass_timestamp",
    "resolve_font",
    "style_for_lang",
    "sanitize_ass_text",
    "subtitle_events",
    "build_ass",
    "burn_ass",
    "run",
    "main",
]

# ---------------------------------------------------------------------------
# 冻结常量与模块局部模型（非冻结契约，仅供本模块与 M15 消费）
# ---------------------------------------------------------------------------

#: 可用的擦除引擎（heavy 路线接口预留不安装）
ENGINES = ("delogo", "inpaint", "vsr")
#: 轻量默认引擎（本机离线可用；cap-clean 重型后端未部署时的生产路径）
DEFAULT_ENGINE = "delogo"
#: 支持的目标语（冻结槽位 10_subs/tgt.<lang>.ass）
SUPPORTED_LANGS = ("en", "es", "ar")

#: 源语 ASS 样式名与目标语样式名（[V4+ Styles] Name 字段）
SRC_STYLE = "ZH"
TGT_STYLE = "TGT"

#: delogo 擦除产物质检默认值：无损（保住下游口型/压制的像素底座）
#: 代价是体积，换来"擦除带外像素零改动"的可判定性（label_zone 哈希断言）
LOSSLESS_CRF = 0
#: 压制（12_out 成片）编码档：CRF18 + medium，与 pipeline 成片口径一致
BURN_CRF = 18

#: 目标语字体族候选（规划 §4 M11：Noto Sans / 微软雅黑 / Noto Naskh Arabic）；
#: 由 :func:`resolve_font` 按存在性取首个（找不到时交 libass 兜底）
_TGT_FONT_FAMILIES = {
    "en": ("Noto Sans", "Microsoft YaHei", "Arial"),
    "es": ("Noto Sans", "Microsoft YaHei", "Arial"),
    "ar": ("Noto Naskh Arabic", "Tahoma", "Arial"),
}

#: 字体族 → Windows 字体目录候选文件名（解析用于启动自检，非渲染必需）
_FONT_FILES = {
    "Noto Sans": ("NotoSans-Bold.ttf", "NotoSans-Regular.ttf"),
    "Microsoft YaHei": ("msyhbd.ttc", "msyh.ttc"),
    "Noto Naskh Arabic": ("NotoNaskhArabic-Bold.ttf", "NotoNaskhArabic-Regular.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "Arial": ("arial.ttf", "arialbd.ttf"),
}

#: [V4+ Styles] 行模板（Style 格式冻结，见 §8 素材字幕样式口径）
_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
    "Effect, Text"
)
#: 白字黑边（Primary 白 / Outline 黑 / Back 半透明黑）；Bold=-1 与源字幕同字重
_COLOR_PRIMARY = "&H00FFFFFF"
_COLOR_SECONDARY = "&H000000FF"
_COLOR_OUTLINE = "&H00000000"
_COLOR_BACK = "&H80000000"


class M11Error(RuntimeError):
    """M11 输入/引擎/执行错误（携带可行动的修复提示）。"""


class EraseInputLine(BaseModel):
    """``03_ocr/ocr_merged.jsonl`` 一行中 M11 消费的字段（bbox + 时间窗）。

    M2 的 ``OcrLineRecord`` 超集兼容（extra 字段忽略）；自建模型避免
    M11 import M2 引擎链（torch 导入只发生在真正跑 OCR 的进程）。
    """

    model_config = ConfigDict(extra="ignore")

    start: float
    end: float
    x0: int
    y0: int
    x1: int
    y1: int


class EraseRegion(BaseModel):
    """单个擦除矩形（全片像素坐标）及其作用时间窗 [t0, t1]（秒）。"""

    model_config = ConfigDict(extra="forbid")

    t0: float
    t1: float
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0


class AssEvent(BaseModel):
    """一条字幕事件（起止秒 + 文本 + 样式名）。"""

    model_config = ConfigDict(extra="forbid")

    start: float
    end: float
    text: str
    style: str = TGT_STYLE


class SubStyle(BaseModel):
    """ASS 样式参数（对应一条 [V4+ Styles] 行）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    font: str
    fontsize: int
    align: int = 2                    # numpad：1 左下 / 2 下中 / 3 右下
    margin_l: int = 60
    margin_r: int = 60
    margin_v: int = 220
    outline: int = 3
    shadow: int = 2

    def style_line(self) -> str:
        return (
            f"Style: {self.name},{self.font},{self.fontsize},{_COLOR_PRIMARY},"
            f"{_COLOR_SECONDARY},{_COLOR_OUTLINE},{_COLOR_BACK},"
            f"-1,0,0,0,100,100,0,0,1,{self.outline},{self.shadow},"
            f"{self.align},{self.margin_l},{self.margin_r},{self.margin_v},1"
        )


# ---------------------------------------------------------------------------
# 几何原语（纯函数；标签区排除 / 出带裁剪全部可单测）
# ---------------------------------------------------------------------------

def label_zone_rect(cfg: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int]:
    """label_zone → (x0,y0,x1,y1) 全宽顶部条（M12 显式标识绘制区）。

    默认 ``position: top-center``、``top_px: 60``、``height_px: 120`` → 条带
    y∈[60,180)，x 取全宽（宁可多保护一点也不让擦除掩码蹭到标识）。
    """
    lz = cfg.get("label_zone") or {}
    top = int(lz.get("top_px", 60))
    h = int(lz.get("height_px", 120))
    y0 = max(0, min(height, top))
    y1 = max(0, min(height, top + h))
    return 0, y0, width, y1


def expand_rect(
    rect: tuple[int, int, int, int], expand_px: int, width: int, height: int
) -> tuple[int, int, int, int]:
    """bbox 四边外扩 ``expand_px`` 并裁剪进画面；退化矩形原样返回（由调用方判定）。"""
    x0, y0, x1, y1 = rect
    return (
        max(0, x0 - expand_px),
        max(0, y0 - expand_px),
        min(width, x1 + expand_px),
        min(height, y1 + expand_px),
    )


def _nonempty(rect: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = rect
    return x1 > x0 and y1 > y0


def clip_to_band(
    rect: tuple[int, int, int, int], band: tuple[int, int, int, int]
) -> Optional[tuple[int, int, int, int]]:
    """把矩形裁剪进擦除带（band 为全宽条 (x0,y0,x1,y1)）；无交集返回 None。"""
    ix0 = max(rect[0], band[0])
    iy0 = max(rect[1], band[1])
    ix1 = min(rect[2], band[2])
    iy1 = min(rect[3], band[3])
    if not _nonempty((ix0, iy0, ix1, iy1)):
        return None
    return ix0, iy0, ix1, iy1


def subtract_label_zone(
    rect: tuple[int, int, int, int], label: tuple[int, int, int, int]
) -> list[tuple[int, int, int, int]]:
    """矩形减去标识区 → 0/1/2 个子矩形（覆盖中部时上下剖分）。

    标识区全宽，故只需按 y 方向剖分：完全包含 → 上段/下段；不相交 → 原样。
    """
    if not (
        rect[0] < label[2] and rect[2] > label[0]
        and rect[1] < label[3] and rect[3] > label[1]
    ):
        return [rect] if _nonempty(rect) else []
    out: list[tuple[int, int, int, int]] = []
    top = (rect[0], rect[1], rect[2], min(rect[3], label[1]))
    bottom = (rect[0], max(rect[1], label[3]), rect[2], rect[3])
    if _nonempty(top):
        out.append(top)
    if _nonempty(bottom):
        out.append(bottom)
    return out


def build_erase_regions(
    lines: list[EraseInputLine],
    *,
    width: int,
    height: int,
    band: tuple[int, int, int, int],
    label: tuple[int, int, int, int],
    expand_px: int,
) -> tuple[list[EraseRegion], dict[str, int]]:
    """OCR 字幕行 → 擦除区域列表（外扩 → 裁剪进带 → 排除标识区）。

    返回 (regions, stats)；stats 记录 n_lines/n_regions/n_out_of_band/
    n_label_split/n_degenerate，供 summary 如实报告（不静默吞区域）。
    """
    regions: list[EraseRegion] = []
    stats = {"n_lines": len(lines), "n_regions": 0, "n_out_of_band": 0,
             "n_label_split": 0, "n_degenerate": 0}
    for ln in lines:
        rect = expand_rect((ln.x0, ln.y0, ln.x1, ln.y1), expand_px, width, height)
        if not _nonempty(rect):
            stats["n_degenerate"] += 1
            continue
        in_band = clip_to_band(rect, band)
        if in_band is None:
            stats["n_out_of_band"] += 1
            continue
        before = subtract_label_zone(in_band, label)
        if len(before) == 2 or (len(before) == 1 and before[0] != in_band):
            stats["n_label_split"] += 1
        if not before:
            stats["n_degenerate"] += 1
            continue
        for part in before:
            regions.append(EraseRegion(t0=ln.start, t1=ln.end,
                                       x0=part[0], y0=part[1],
                                       x1=part[2], y1=part[3]))
    stats["n_regions"] = len(regions)
    regions.sort(key=lambda r: (r.t0, r.y0, r.x0))
    return regions, stats


def delogo_chain(regions: list[EraseRegion]) -> str:
    """擦除区域 → ffmpeg delogo 滤镜链（按时间窗 enable，窗外不动像素）。

    每区域一条 ``delogo=x=..:y=..:w=..:h=..:enable='between(t,a,b)'``；
    单引号为滤镜语法的一部分（经 argv 直传，不经 shell，须原样保留）。
    """
    parts = []
    for r in regions:
        parts.append(
            f"delogo=x={r.x0}:y={r.y0}:w={r.w}:h={r.h}"
            f":enable='between(t,{r.t0:.3f},{r.t1:.3f})'"
        )
    return ",".join(parts)


# ---------------------------------------------------------------------------
# 擦除后端（delogo / inpaint / vsr 接口）
# ---------------------------------------------------------------------------

def _ffmpeg_run(cmd: list[str], *, cwd: Optional[Path] = None, timeout_s: float = 3600.0,
                stdin_bytes: Any = None) -> None:
    """执行 ffmpeg（utf-8，失败抛 M11Error，stderr 尾部入消息）。"""
    if shutil.which(cmd[0]) is None:
        raise M11Error(f"未找到可执行文件 {cmd[0]!r}（请确认 ffmpeg 已安装并在 PATH）")
    try:
        r = subprocess.run(
            cmd, capture_output=True, input=stdin_bytes, timeout=timeout_s,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise M11Error(f"ffmpeg 超时（>{timeout_s:.0f}s）: {' '.join(cmd[:8])}...") from exc
    if r.returncode != 0:
        tail = (r.stderr or b"")[-2000:].decode("utf-8", "replace")
        raise M11Error(f"ffmpeg 失败（rc={r.returncode}）: {tail}")


class DelogoBackend:
    """轻量默认路径：ffmpeg delogo 按时间窗插值填充，产物无损 x264。"""

    name = "delogo"

    def __init__(self, *, crf: int = LOSSLESS_CRF, preset: str = "veryfast") -> None:
        self.crf = int(crf)
        self.preset = preset

    def erase(self, video_in: Path, video_out: Path, regions: list[EraseRegion],
              *, width: int, height: int, fps: float) -> None:
        if not regions:
            shutil.copyfile(video_in, video_out)  # 无字幕区 → 基带=原片副本
            return
        chain = delogo_chain(regions)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(video_in),
               "-vf", chain,
               "-c:v", "libx264", "-crf", str(self.crf), "-preset", self.preset,
               "-pix_fmt", "yuv420p", "-c:a", "copy", str(video_out)]
        _ffmpeg_run(cmd)


class InpaintBackend:
    """轻量备选路径：cv2 inpaint（TELEA）逐帧修复，掩码=当帧生效区域并集。

    无 CUDA 依赖；与 delogo 的差别：修复式填充而非边框插值，质量高、
    速度慢一档（约 10 倍帧数级外推，视 CPU 负载；生产仅小批量用）。
    """

    name = "inpaint"

    INPAINT_RADIUS = 3
    _EPS = 1e-6

    def erase(self, video_in: Path, video_out: Path, regions: list[EraseRegion],
              *, width: int, height: int, fps: float) -> None:
        import cv2
        import numpy as np

        if not regions:
            shutil.copyfile(video_in, video_out)
            return

        cap = cv2.VideoCapture(str(video_in))
        try:
            if not cap.isOpened():
                raise M11Error(f"视频无法打开: {video_in}")
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "rawvideo", "-pix_fmt", "bgr24",
                   "-s", f"{width}x{height}", "-r", f"{fps}", "-i", "-",
                   "-i", str(video_in),
                   "-map", "0:v", "-map", "1:a?", "-c:a", "copy",
                   "-c:v", "libx264", "-crf", str(LOSSLESS_CRF),
                   "-preset", "veryfast", "-pix_fmt", "yuv420p", str(video_out)]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            try:
                idx = 0
                while True:
                    ok, frame = cap.read()
                    if not ok:
                        break
                    t = idx / fps
                    mask = None
                    for r in regions:
                        if (r.t0 - self._EPS) <= t <= (r.t1 + self._EPS):
                            if mask is None:
                                mask = np.zeros((height, width), dtype=np.uint8)
                            mask[r.y0:r.y1, r.x0:r.x1] = 255
                    if mask is not None:
                        frame = cv2.inpaint(frame, mask, self.INPAINT_RADIUS,
                                            cv2.INPAINT_TELEA)
                    if proc.stdin is not None:
                        proc.stdin.write(frame.tobytes())
                    idx += 1
                if proc.stdin is not None:
                    proc.stdin.close()
            finally:
                rc = proc.wait()
                if rc != 0:
                    raise M11Error(f"ffmpeg 退出码 {rc}（rawvideo 管道写入失败？）")
        finally:
            cap.release()


class VsrCleanBackend:
    """重型擦除后端（models.yaml cap-clean 所指上游路线）：**接口预留、未安装**。

    设计取舍：重型路线体积/依赖/许可核验成本高，MVP 只用轻量 delogo/inpaint
    路径；本类固定 select registry 入口，安装后即可经 ``--engine vsr``
    启用。未安装时选中它必须**如实报错**，不静默降到别的引擎。
    """

    name = "vsr"

    def available(self) -> bool:
        return False

    def erase(self, *args: Any, **kwargs: Any) -> None:
        raise M11Error(
            "擦除引擎 vsr 未安装（重型路线接口预留：models.yaml cap-clean "
            "volta_status=pending；生产请用 --engine delogo 轻量路径，"
            "或 --engine inpaint 备选）" )


_BACKENDS: dict[str, Any] = {
    DelogoBackend.name: DelogoBackend,
    InpaintBackend.name: InpaintBackend,
    VsrCleanBackend.name: VsrCleanBackend,
}


def get_backend(engine: Optional[str] = None, cfg: Optional[dict[str, Any]] = None) -> Any:
    """按名构造擦除后端；默认取 pipeline.yaml ``erase.engine``（缺省 delogo）。"""
    name = (engine
            or (cfg or {}).get("erase", {}).get("engine")
            or DEFAULT_ENGINE).strip().lower()
    if name not in _BACKENDS:
        raise M11Error(f"未知擦除引擎 {engine!r}（可用：{', '.join(ENGINES)}）")
    return _BACKENDS[name]()


# ---------------------------------------------------------------------------
# ASS 生成（libass 渲染期做 bidi/shaping；此处逻辑序直书）
# ---------------------------------------------------------------------------

def ass_timestamp(t: float) -> str:
    """秒 → ASS ``H:MM:SS.CC``（百分秒四舍五入；负值按 0）。"""
    cs_total = int(round(max(0.0, t) * 100))
    h, rem = divmod(cs_total, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def resolve_font(families: tuple[str, ...], fonts_dir: Optional[Path] = None) -> tuple[str, Optional[Path]]:
    """字体族候选 → (族名, 字体文件路径|None)：首个在 Windows 字体目录存在的族。

    路径仅用于启动自检/摘要报告；ASS 只含族名，最终解析交 libass
    （fontconfig）。都不存在时返回首个族名（libass 兜底），由渲染回归发现。
    """
    root = fonts_dir or Path(f"{Path().drive or 'C:'}\\Windows\\Fonts")
    for fam in families:
        for fname in _FONT_FILES.get(fam, ()):
            p = root / fname
            if p.is_file():
                return fam, p
    return families[0], None


def style_for_lang(cfg: dict[str, Any], lang: str) -> tuple[SubStyle, Optional[Path]]:
    """目标语样式：en/es 左下（Alignment 1）、ar 右对齐 RTL（Alignment 3）。

    对齐来源 = ``channels.<lang>.subs_align``（right-rtl → 3 右下、
    left-bottom → 1 左下、其他 → 2 下中）；字体走
    :data:`_TGT_FONT_FAMILIES` 候选解析。
    """
    align_map = {"right-rtl": 3, "left-bottom": 1, "bottom-center": 2}
    align = align_map.get((cfg.get("channels", {}).get(lang, {}) or {}).get("subs_align", ""), 2)
    subs_cfg = cfg.get("subs") or {}
    family, font_path = resolve_font(_TGT_FONT_FAMILIES.get(lang, _TGT_FONT_FAMILIES["en"]))
    style = SubStyle(
        name=TGT_STYLE,
        font=family,
        fontsize=int(subs_cfg.get("font_size", 62)),
        align=align,
        margin_l=int(subs_cfg.get("margin_h_px", 60)),
        margin_r=int(subs_cfg.get("margin_h_px", 60)),
        margin_v=int(subs_cfg.get("margin_v_px", 220)),
        outline=int(subs_cfg.get("outline", 3)),
        shadow=int(subs_cfg.get("shadow", 2)),
    )
    return style, font_path


def sanitize_ass_text(text: str) -> str:
    """字幕文本 → ASS 安全文本：换行转 \\N、剥离 override 标签与控制字符。

    不做任何 bidi/整形处理（阿语以逻辑序直书，渲染责任归 libass+fribidi）。
    """
    s = text.replace("\r\n", " ").replace("\r", " ").replace("\n", "\\N")
    s = s.replace("{", "").replace("}", "")
    return "".join(ch for ch in s if ch >= " " or ch == "\\")


def subtitle_events(
    utts: list[C.Utterance], translations: list[C.Translation], lang: str
) -> tuple[list[AssEvent], dict[str, int]]:
    """C2 句窗 × C4 (utt_id,lang) 行 → 字幕事件（跳过无译文/无候选译文的句子）。

    统计：n_events / n_skipped_no_translation / n_skipped_no_candidate。
    """
    by_key = {f"{t.utt_id}|{t.tgt}": t for t in translations}
    events: list[AssEvent] = []
    stats = {"n_events": 0, "n_skipped_no_translation": 0, "n_skipped_no_candidate": 0}
    for u in utts:
        row = by_key.get(f"{u.utt_id}|{lang}")
        if row is None:
            stats["n_skipped_no_translation"] += 1
            continue
        if row.chosen is None or row.chosen >= len(row.candidates):
            stats["n_skipped_no_candidate"] += 1
            continue
        text = sanitize_ass_text(row.candidates[row.chosen].text)
        if not text:
            stats["n_skipped_no_candidate"] += 1
            continue
        start = max(0.0, u.start)
        end = max(start + 0.01, u.end)
        events.append(AssEvent(start=start, end=end, text=text))
    stats["n_events"] = len(events)
    events.sort(key=lambda e: (e.start, e.end))
    return events, stats


def build_ass(events: list[AssEvent], *, style: SubStyle,
              play_w: int = 1080, play_h: int = 1920) -> str:
    """字幕事件 → ASS 文档字符串（[V4+ Styles] 单样式；UTF-8 无 BOM）。"""
    header = (
        "[Script Info]\n"
        "; Generated by pipeline.m11_subs（目标语字幕；文本为逻辑序，bidi/shaping 由 libass 完成）\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_w}\n"
        f"PlayResY: {play_h}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        f"{_STYLE_FORMAT}\n"
        f"{style.style_line()}\n"
        "\n"
        "[Events]\n"
        f"{_EVENT_FORMAT}\n"
    )
    lines = [header]
    for e in events:
        lines.append(
            f"Dialogue: 0,{ass_timestamp(e.start)},{ass_timestamp(e.end)},"
            f"{e.style},,0,0,0,,{e.text}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 压制
# ---------------------------------------------------------------------------

def burn_ass(video: Path, ass_path: Path, out: Path, *, crf: int = BURN_CRF) -> None:
    """ffmpeg 压制：目标语 ASS 叠加到基带视频 → 12_out 成片。

    ``ass=`` 内只传相对文件名并以 10_subs/ 为 cwd —— Windows 滤镜串对
    盘符/反斜杠/非 ASCII 路径敏感（过滤图两级转义陷阱），cwd 相对引用
    可绕开（T8 实测口径，同 M2 drawtext textfile 手法）。
    """
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(video),
           "-vf", f"ass={ass_path.name}",
           "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
           str(out)]
    _ffmpeg_run(cmd, cwd=ass_path.parent, timeout_s=3600.0)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _media_geometry(cfg: dict[str, Any]) -> tuple[int, int, float]:
    media = {**{"width": 1080, "height": 1920, "fps": 25}, **(cfg.get("media") or {})}
    return int(media["width"]), int(media["height"]), float(media["fps"])


def _video_duration(video: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if r.returncode != 0:
        raise M11Error(f"ffprobe 失败: {(r.stderr or '').strip()[:300]}")
    return float(json.loads(r.stdout)["format"]["duration"])


def _load_lines(path: Path) -> list[EraseInputLine]:
    rows: list[EraseInputLine] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(EraseInputLine.model_validate(json.loads(line)))
    return rows


def run(
    ep: str,
    lang: str,
    *,
    skip_erase: bool = False,
    engine: Optional[str] = None,
    burn: bool = True,
    jobs_root: Optional[str | Path] = None,
) -> dict[str, Any]:
    """M11 主流程：擦除（可选）→ src/tgt ASS → 压制，返回摘要 dict。

    幂等：重跑同语种覆盖 10_subs 与 12_out 产物；擦除非跳过时重做基带。
    """
    t_start = time.time()
    if lang not in SUPPORTED_LANGS:
        raise M11Error(f"目标语 {lang!r} 未登记（支持：{', '.join(SUPPORTED_LANGS)}）")
    cfg = load_pipeline_config()
    root = ep_dir(ep, Path(jobs_root) if jobs_root else Path(cfg["paths"]["jobs_dir"]))
    width, height, fps = _media_geometry(cfg)

    media_dir = root / "01_media"
    video = media_dir / f"video_{width}x{height}_{int(fps)}fps.mp4"
    if not video.is_file():
        raise M11Error(
            f"M1 产物不存在: {video}（先跑 python -m pipeline.m1_ingest --ep {ep} …）")
    dur = _video_duration(video)

    band_cfg = cfg.get("erase_band") or {}
    band = (0, int(band_cfg.get("y0_px", 1440)), width, int(band_cfg.get("y1_px", 1780)))
    label = label_zone_rect(cfg, width, height)
    expand_px = int(band_cfg.get("expand_px", 4))

    # ---- ① 擦除（消费 M2 OCR 字幕行 bbox）----
    ocr_path = root / "03_ocr" / "ocr_merged.jsonl"
    if not ocr_path.is_file():
        raise M11Error(
            f"OCR 产品不存在: {ocr_path}（先跑 python -m pipeline.m2_ocr --ep {ep} …）")
    lines = _load_lines(ocr_path)
    regions, region_stats = build_erase_regions(
        lines, width=width, height=height, band=band, label=label,
        expand_px=expand_px)

    clean = media_dir / f"video_{width}x{height}_{int(fps)}fps_clean.mp4"
    engine_used = "skip"
    if skip_erase:
        base = clean if clean.is_file() else video
    else:
        backend = get_backend(engine, cfg)
        backend.erase(video, clean, regions, width=width, height=height, fps=fps)
        base = clean
        engine_used = backend.name

    # ---- ② 源语 ASS（C2 原文，人工审校回看口径；缺 C2 时跳过）----
    utt_path = root / "04_dial" / "utterances.jsonl"
    subs_dir = root / "10_subs"
    subs_dir.mkdir(parents=True, exist_ok=True)
    src_ass: Optional[Path] = None
    n_src_events = 0
    if utt_path.is_file():
        utts = list(C.load_jsonl(utt_path, C.UtteranceTable).root)
        src_events, _ = subtitle_events(
            utts, [
                C.Translation(
                    utt_id=u.utt_id, tgt=lang,
                    budget=C.Budget(orig_dur=round(u.end - u.start, 3),
                                    lo=0.001, hi=round(u.end - u.start, 3) + 0.001),
                    candidates=[C.Candidate(text=u.text, syl=len(u.text),
                                           est_dur=0.0, src="c2", q=1.0)],
                    chosen=0)
                for u in utts
            ], lang)
        zh_style = SubStyle(name=SRC_STYLE, font="Microsoft YaHei",
                            fontsize=62, align=2, margin_v=220)
        src_ass = subs_dir / "src.ass"
        src_ass.write_text(build_ass(src_events, style=zh_style), encoding="utf-8")
        n_src_events = len(src_events)
    else:
        utts = []

    # ---- ③ 目标语 ASS（C2 句窗 × C4 选定译文；--no-burn 时缺 C4 可跳过）----
    trans_path = root / "06_mt" / "translations.jsonl"
    translations: list[C.Translation] = []
    if trans_path.is_file():
        translations = list(C.load_jsonl(trans_path, C.TranslationTable).root)
    tgt_events, evt_stats = subtitle_events(utts, translations, lang)
    tgt_ass: Optional[Path] = None
    tgt_font: Optional[str] = None
    if not tgt_events and burn:
        raise M11Error(
            f"lang={lang} 无可用译文（{evt_stats}）——06_mt/translations.jsonl 缺 "
            "(utt_id,tgt) 行或 chosen 缺候选（先跑 python -m pipeline.m6_translate "
            "--ep … --lang …；或 --no-burn 只做擦除）")
    if tgt_events:
        tgt_style, font_path = style_for_lang(cfg, lang)
        tgt_font = str(font_path) if font_path else tgt_style.font
        tgt_ass = subs_dir / f"tgt.{lang}.ass"
        tgt_ass.write_text(build_ass(tgt_events, style=tgt_style), encoding="utf-8")

    # ---- ④ 压制 ----
    out_path = root / "12_out" / f"{ep}.{lang}.mp4"
    if burn:
        burn_ass(base, tgt_ass, out_path)
    burned_dur = _video_duration(out_path) if burn and out_path.is_file() else dur

    elapsed = round(time.time() - t_start, 2)
    return {
        "ep": ep, "lang": lang,
        "base_video": str(base), "engine": engine_used,
        "erase": region_stats,
        "erase_band": list(band), "label_zone": list(label),
        "duration_s": dur, "burned_duration_s": burned_dur,
        "n_src_events": n_src_events, "src_ass": str(src_ass) if src_ass else None,
        "n_tgt_events": evt_stats["n_events"],
        "n_skipped_no_translation": evt_stats["n_skipped_no_translation"],
        "n_skipped_no_candidate": evt_stats["n_skipped_no_candidate"],
        "tgt_ass": str(tgt_ass) if tgt_ass else None,
        "tgt_font": tgt_font,
        "out": str(out_path) if burn else None,
        "elapsed_s": elapsed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.m11_subs",
        description="M11 字幕擦除 + 目标语 ASS 渲染（--skip-erase 可只渲染压制）",
    )
    ap.add_argument("--ep", required=True, help="集 ID，如 ep01")
    ap.add_argument("--lang", required=True, choices=list(SUPPORTED_LANGS),
                    help="目标语种（冻结槽位 en/es/ar）")
    ap.add_argument("--skip-erase", action="store_true",
                    help="跳过擦除（基带取已擦除产物，无则原片）")
    ap.add_argument("--engine", default=None, choices=list(ENGINES),
                    help=f"擦除引擎（默认取 pipeline.yaml erase.engine，缺省 {DEFAULT_ENGINE}；"
                         "vsr=重型路线接口、未安装会报错）")
    ap.add_argument("--no-burn", action="store_true", help="只生成 ASS 不压制")
    ap.add_argument("--jobs-dir", default=None, help="jobs 根目录（默认取 configs）")
    args = ap.parse_args(argv)

    try:
        s = run(
            args.ep, args.lang,
            skip_erase=args.skip_erase, engine=args.engine,
            burn=not args.no_burn, jobs_root=args.jobs_dir,
        )
    except (M11Error, FileNotFoundError, ValueError) as exc:
        print(f"FAIL m11_subs: {exc}")
        return 1
    print(
        f"OK m11_subs ep={s['ep']} lang={s['lang']} engine={s['engine']} "
        f"regions={s['erase']['n_regions']}(out_of_band={s['erase']['n_out_of_band']}) "
        f"events={s['n_tgt_events']} dur={s['duration_s']}s "
        f"-> {s['out']} ({s['elapsed_s']}s)"
    )
    print(f"   基带: {s['base_video']}")
    print(f"   ASS: {s['src_ass']} / {s['tgt_ass']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
