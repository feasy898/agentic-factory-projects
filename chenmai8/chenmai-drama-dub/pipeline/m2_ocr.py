"""M2 硬字幕 OCR + OCR↔ASR 校对（规划 §4 M2，【本机】CPU 验收）。

Spec（§4 M2）：
  1. 按帧采样（每 0.2s）只扫字幕区（默认取 configs/pipeline.yaml ``erase_band``，
     与 M11 擦除带同源），字幕变化处合并去重 → ``03_ocr/ocr_raw.jsonl``（帧级
     原始检出）+ ``03_ocr/ocr_merged.jsonl``（字幕行：起止时间/文本/置信/bbox）；
  2. 与 M4 的 ASR（``04_dial/utterances.jsonl``，C2 行）按时间重叠 ≥60% 做对齐
     投票：**OCR 置信 ≥0.9 时以 OCR 为准，否则 ASR**；OCR↔ASR 归一化文本一致
     时 ``agree=True``，产出口径写进 C2 ``ocr.agree``；
  3. ASR 缺席（utterances.jsonl 不存在/为空，或 --no-asr）时**退化为纯 OCR**：
     文本即 OCR 文本、``agree=False``（未经 ASR 确认）；
  4. 出口 = 契约 C2 对齐的字幕行（起止时间/文本），经
     :func:`pipeline.contracts.upsert_jsonl` 原子替换写入
     ``04_dial/utterances.jsonl``（utt_id 唯一、整表契约校验后落盘）。

B1 冻结衔接（pipeline/contracts.py 冻结规则 7/8）：
  - 本模块的 ``ocr_merged.jsonl`` 字幕区间即 C2 句窗第 ① 优先级来源；
  - 与 ASR 行融合时按 ① 重切句窗：命中行窗口改为 OCR 区间、字级时间戳夹取进
    新窗（契约字级校验保持成立）；命中行的 ``utt_id`` 保持 M4 稳定公式不变
    （它是替换键，改 id 会破坏断点续跑与幂等）。

依赖与硬约束（docs/setup_windev.md §3，T0 实测，违反即崩）：
  引擎构造一律经 :mod:`pipeline.ocr_wrap`（B1 修订后的 M2 唯一许可入口）：
  ``bootstrap()`` 保证同进程 torch 先于 OCR 引擎包导入（libiomp5md.dll 冲突），
  ``ocr_kwargs()`` 强制 ``enable_mkldnn=False``（PIR/oneDNN 执行器不支持），
  外部同名覆盖一律被忽略。本模块不得绕过该入口自行 import/构造。

中性名纪律：引擎以内部台账中性名 **cap-ocr** 指代；真实上游包名只出现在
requirements.txt（依赖安装记录），由 ocr_wrap 拼接构造动态加载（公开文本零
上游名，同 scripts/gate_b0.py 手法）。

CLI（规划 §4 冻结形态）::

    python -m pipeline.m2_ocr --ep ep01
    python -m pipeline.m2_ocr --ep ep01 --interval 0.2 --lang zh [--no-asr]

退出码：0 成功；1 输入/产物缺失或契约校验失败；2 用法错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.ocr_wrap import create_ocr
from pipeline.scaffold import ep_dir

__all__ = [
    "M2Error",
    "OcrFrameRecord",
    "OcrLineRecord",
    "SubtitleOcr",
    "vote_text",
    "overlap_ratio",
    "merge_ocr_asr",
    "merge_frames_to_lines",
    "edit_distance",
    "cer",
    "run",
    "main",
]

# ---------------------------------------------------------------------------
# 冻结常量（§4 M2 原文口径；改行为先改 eval）
# ---------------------------------------------------------------------------

#: 采样间隔（§4 M2：每 0.2s）
OCR_SAMPLE_INTERVAL_S = 0.2
#: 投票高置信线（§4 M2：OCR 置信 ≥0.9 时以 OCR 为准）
OCR_HIGH_CONF = 0.9
#: 对齐投票的最小时间重叠率（§4 M2：≥60%，分母 = OCR 行时长）
ASR_OVERLAP_MIN = 0.6

#: 帧内检出框保留的最低识别置信（过滤台标/时间码等噪声框）
_REC_SCORE_MIN = 0.30
#: 采样子带降采样系数（cap-ocr 推理禁 mkldnn 后的 CPU 吞吐档，T6 实测 1.7s/帧@0.5，
#: 全尺寸 5.5s/帧；0.5 下识别质量不降反稳，见 tests/test_m2.py eval）
_SAMPLE_SCALE = 0.5
#: 帧内多框并行的行聚类阈值（y 中心间距 > 行高×该系数 → 视为第二行）
_ROW_SPLIT_RATIO = 0.7
#: 合并去重允许的最大采样断裂（=2 个采样步，桥掉单帧 OCR 抖动）
_MERGE_GAP_STEPS = 2
#: shot_id 占位（与 M4 同值；M5 镜头表就绪后回填真实镜头）
PLACEHOLDER_SHOT = "s0000"
#: 连写（无空格）语种：多行/多框拼接时不加空格
_NO_SPACE_LANGS = {"zh", "yue", "ja"}

#: 真实上游包名统一由 pipeline/ocr_wrap 拼接构造动态加载（中性名纪律，见模块 docstring）


class M2Error(RuntimeError):
    """M2 输入/引擎/产物错误（携带可行动的修复提示）。"""


# ---------------------------------------------------------------------------
# 模块本地记录模型（03_ocr/*.jsonl；非冻结契约，仅供本模块与 M11 消费）
# ---------------------------------------------------------------------------

class OcrFrameRecord(BaseModel):
    """``ocr_raw.jsonl`` 一行：单个采样帧的原始检出（只记非空帧）。"""

    model_config = ConfigDict(extra="forbid")

    t: float                       # 采样帧时间戳（秒，全片绝对）
    text: str                      # 帧级拼接文本（多行以 \n 连接）
    conf: float                    # 帧级置信（= 帧内各框最小值）
    boxes: list[list[int]]         # 每框 [x1, y1, x2, y2]（全片像素坐标）


class OcrLineRecord(BaseModel):
    """``ocr_merged.jsonl`` 一行：合并去重后的字幕行（M11 擦除带 bbox 供消费）。"""

    model_config = ConfigDict(extra="forbid")

    start: float                   # 行起点（首帧采样时刻 − 半步；秒 3 位）
    end: float                     # 行终点（末帧采样时刻 + 半步；秒 3 位）
    text: str
    conf: float                    # 行置信（= 各帧 conf 均值）
    frames: int                    # 命中采样帧数
    x0: int = 0                    # bbox（全片像素，多帧取并集；M11 擦除带）
    y0: int = 0
    x1: int = 0
    y1: int = 0


# ---------------------------------------------------------------------------
# 文本工具（归一化 / 编辑距离 / CER —— M15 回听指标复用）
# ---------------------------------------------------------------------------

# fullwidth CJK punct + curly quotes + ASCII punct; curly quotes via chr()
# to keep string delimiters unambiguous
_PUNCT_CHARS = (
    "，。！？…、：；（）【】《》—～·"
    + chr(0x201C) + chr(0x201D) + chr(0x2018) + chr(0x2019)
    + ",.!?;:()[]<>-_/\\|@#$%^&*+="
)
_PUNCT_TABLE = dict.fromkeys(map(ord, _PUNCT_CHARS), None)


def normalize_text(s: str) -> str:
    """OCR↔ASR 一致性比较口径：去空白与中英文标点，仅留实义字符。"""
    return "".join(ch for ch in s.translate(_PUNCT_TABLE) if not ch.isspace())


def edit_distance(a: str, b: str) -> int:
    """字符级 Levenshtein 距离（动态规划，O(len_a×len_b)）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    """字符错误率 = edit_distance(ref, hyp) / len(ref)；ref 为空时返回 0/1。"""
    ref_n, hyp_n = normalize_text(ref), normalize_text(hyp)
    if not ref_n:
        return 0.0 if not hyp_n else 1.0
    return edit_distance(ref_n, hyp_n) / len(ref_n)


# ---------------------------------------------------------------------------
# 投票原语（纯函数，单测覆盖；不触引擎与 IO）
# ---------------------------------------------------------------------------

def vote_text(
    ocr_text: str,
    ocr_conf: float,
    asr_text: str,
    *,
    high_conf: float = OCR_HIGH_CONF,
) -> tuple[str, str, bool]:
    """§4 M2 对齐投票：返回 ``(chosen_text, source, agree)``。

    - ``ocr_conf ≥ high_conf``（且 OCR 文本非空）→ 以 OCR 为准（source="ocr"）；
    - 否则以 ASR 为准（source="asr"）；ASR 文本为空时兜底回 OCR（source="ocr"）；
    - ``agree`` = OCR 与 ASR 归一化文本一致（ASR 缺席 → False，即"未经确认"）。
    """
    has_asr = bool((asr_text or "").strip())
    agree = has_asr and normalize_text(ocr_text) == normalize_text(asr_text)
    use_ocr = (ocr_conf >= high_conf and bool(ocr_text.strip())) or not has_asr
    if use_ocr:
        return ocr_text, "ocr", agree
    return asr_text, "asr", agree


def overlap_ratio(
    line: tuple[float, float], window: tuple[float, float]
) -> float:
    """时间重叠率 = 交集时长 / OCR 行时长（行时长≤0 时记 0）。"""
    inter = min(line[1], window[1]) - max(line[0], window[0])
    dur = line[1] - line[0]
    if dur <= 0:
        return 0.0
    return max(0.0, inter) / dur


def _clip_words_into_window(
    words: list[C.Word], start: float, end: float
) -> list[C.Word]:
    """字级时间戳夹取进新句窗（契约校验：utt.start ≤ w.s ≤ w.e ≤ utt.end 且有序）。"""
    eps = 0.001
    kept: list[C.Word] = []
    for w in sorted(words, key=lambda w: w.s):
        mid = (w.s + w.e) / 2.0
        if not (start - eps <= mid <= end + eps):
            continue
        s = round(max(w.s, start), 3)
        e = round(min(w.e, end), 3)
        if e <= s:
            continue
        kept.append(C.Word(w=w.w, s=s, e=e))
    return kept


def merge_ocr_asr(
    ep: str,
    lines: list[OcrLineRecord],
    utts: list[C.Utterance],
    *,
    lang: str = "zh",
    high_conf: float = OCR_HIGH_CONF,
    overlap_min: float = ASR_OVERLAP_MIN,
) -> list[C.Utterance]:
    """OCR 字幕行 × M4 utterances → 融合后的 C2 行列表（纯函数）。

    匹配：全部 (行, 句) 对中重叠率 ≥ ``overlap_min`` 者，按重叠率降序贪心
    1:1 配对（避免多行抢一句 / 一句抢多行）。命中句按 B1 冻结规则 8① 以
    OCR 区间重切句窗、字级时间戳夹取，文本经 :func:`vote_text` 定稿，
    ``ocr`` 事实与 ``agree`` 落 C2；未命中行生成纯 OCR 新句
    （``utt_id = contracts.make_utt_id(ep, 行起点)``，``agree=False``）；
    未命中句原样保留。已知边界：一条 OCR 行横跨多条 ASR 句且对任何单句重叠率
    都不足 ``overlap_min`` 时，三方共存（OCR 新句 + 原 ASR 句），句级去重归
    M5/M14 融合批次。返回按起点排序的全集。
    """
    pairs: list[tuple[float, int, int]] = []
    for li, ln in enumerate(lines):
        for ui, u in enumerate(utts):
            r = overlap_ratio((ln.start, ln.end), (u.start, u.end))
            if r >= overlap_min:
                pairs.append((r, li, ui))
    pairs.sort(key=lambda p: (-p[0], lines[p[1]].start, utts[p[2]].start))

    matched_line: dict[int, int] = {}
    matched_utt: dict[int, int] = {}
    for _r, li, ui in pairs:
        if li in matched_line or ui in matched_utt:
            continue
        matched_line[li] = ui
        matched_utt[ui] = li

    out: list[C.Utterance] = []
    for ui, u in enumerate(utts):
        if ui not in matched_utt:
            out.append(u)
            continue
        ln = lines[matched_utt[ui]]
        start = round(ln.start, 3)
        end = round(max(ln.end, start + 0.001), 3)  # 契约要求 end > start
        chosen, _src, agree = vote_text(ln.text, ln.conf, u.text, high_conf=high_conf)
        out.append(
            C.Utterance(
                **{
                    **u.model_dump(),
                    "start": start,
                    "end": end,
                    "text": chosen,
                    "ocr": C.OcrFact(text=ln.text, conf=round(min(ln.conf, 1.0), 4),
                                     agree=agree),
                    "words": _clip_words_into_window(u.words, start, end),
                }
            )
        )
    for li, ln in enumerate(lines):
        if li in matched_line:
            continue
        out.append(
            C.Utterance(
                utt_id=C.make_utt_id(ep, ln.start),
                shot_id=PLACEHOLDER_SHOT,
                start=round(ln.start, 3),
                end=round(max(ln.end, ln.start + 0.001), 3),
                lang=lang,
                text=ln.text,
                ocr=C.OcrFact(text=ln.text, conf=round(min(ln.conf, 1.0), 4), agree=False),
            )
        )
    out.sort(key=lambda u: (u.start, u.utt_id))
    return out


def _agree_of(line: OcrLineRecord, asr_text: str) -> bool:
    """OCR 行与 ASR 文本的归一化一致（ASR 空 → False）。

    兼容辅助：与 :func:`vote_text` 的 agree 口径一致，供独立复检。
    """
    return bool((asr_text or "").strip()) and (
        normalize_text(line.text) == normalize_text(asr_text)
    )


# ---------------------------------------------------------------------------
# OCR 引擎封装（cap-ocr；构造唯一入口 pipeline/ocr_wrap.create_ocr）
# ---------------------------------------------------------------------------

class SubtitleOcr:
    """字幕区 OCR 引擎封装（懒初始化，经 :func:`pipeline.ocr_wrap.create_ocr` 构造）。

    实测（T6，windev CPU）：引擎默认即 PP-OCRv6 medium det/rec（本机官方仓缓存），
    全尺寸字幕带 5.5s/帧、0.5 降采样 1.7s/帧且识别质量不降 —— ``scale=0.5`` 为默认。
    """

    def __init__(
        self,
        *,
        scale: float = _SAMPLE_SCALE,
        min_conf: float = _REC_SCORE_MIN,
        det_model: Optional[str] = None,
        rec_model: Optional[str] = None,
    ) -> None:
        self.scale = float(scale)
        self.min_conf = float(min_conf)
        self._det_model = det_model
        self._rec_model = rec_model
        self._eng: Any = None

    def _ensure(self) -> Any:
        if self._eng is None:
            kwargs: dict[str, Any] = dict(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
            if self._det_model:
                kwargs["text_detection_model_name"] = self._det_model
            if self._rec_model:
                kwargs["text_recognition_model_name"] = self._rec_model
            try:
                # enable_mkldnn=False 由 ocr_wrap.ocr_kwargs 强制注入且不可覆盖
                self._eng = create_ocr(**kwargs)
            except ImportError as exc:
                raise M2Error(
                    "OCR 运行时不可用（依赖未装？安装见 requirements.txt 与 "
                    "docs/setup_windev.md）"
                ) from exc
        return self._eng

    def read_band(self, band_bgr: Any) -> list[dict[str, Any]]:
        """单帧字幕带（BGR ndarray）→ 检出列表 [{text, conf, x0,y0,x1,y1}]（带内坐标）。

        输入应为**未缩放**的字幕带；内部按 ``self.scale`` 降采样推理后还原坐标。
        """
        import cv2

        eng = self._ensure()
        small = band_bgr
        if self.scale < 1.0:
            small = cv2.resize(
                band_bgr, None, fx=self.scale, fy=self.scale,
                interpolation=cv2.INTER_AREA,
            )
        rows = eng.predict(small)
        if not rows:
            return []
        r = rows[0]
        texts = list(r.get("rec_texts") or [])
        scores = list(r.get("rec_scores") or [])
        boxes = r.get("rec_boxes")
        inv = 1.0 / self.scale
        out: list[dict[str, Any]] = []
        for i, txt in enumerate(texts):
            conf = float(scores[i]) if i < len(scores) else 0.0
            if not str(txt).strip() or conf < self.min_conf:
                continue
            x1, y1, x2, y2 = [int(round(v * inv)) for v in boxes[i]]
            out.append({"text": str(txt), "conf": conf,
                        "x0": x1, "y0": y1, "x1": x2, "y1": y2})
        return out


# ---------------------------------------------------------------------------
# 帧采样 → 帧级文本 → 字幕行合并
# ---------------------------------------------------------------------------

def sample_band(
    video: str | Path,
    *,
    y0: int,
    y1: int,
    interval_s: float = OCR_SAMPLE_INTERVAL_S,
) -> Iterator[tuple[float, Any]]:
    """视频等间隔采样（每 ``interval_s``）→ (t, 字幕带 BGR) 迭代器。

    顺序解码取帧（cv2 逐帧 grab、命中采样点才 retrieve），时间戳 = 帧号/fps，
    不经 seek（H.264 seek 抖动会污染字幕行起止时间）。产出**未缩放**字幕带，
    推理降采样属引擎职责（:meth:`SubtitleOcr.read_band`）。
    """
    import cv2

    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise M2Error(f"视频无法打开: {video}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or n_frames <= 0:
            raise M2Error(f"视频 fps/帧数读取失败（fps={fps}, frames={n_frames}）: {video}")
        step = max(1, int(round(interval_s * fps)))
        idx = 0
        while True:
            ok = cap.grab()
            if not ok:
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                t = round(idx / fps, 3)
                yield t, frame[int(y0):int(y1), :, :]
            idx += 1
    finally:
        cap.release()


def _frame_caption(dets: list[dict[str, Any]], *, lang: str) -> tuple[str, float, list[list[int]]]:
    """帧内检出框 → (帧级文本, 帧级置信, 框列表)。

    多框按 y 中心聚行（行距 > 行高×:data:`_ROW_SPLIT_RATIO` 分行），行内按 x 排序
    拼接（连写语种不加空格），多行以 \\n 连接；帧置信 = 各框最小值。
    """
    if not dets:
        return "", 0.0, []
    dets = sorted(dets, key=lambda d: ((d["y0"] + d["y1"]) / 2.0, d["x0"]))
    rows: list[list[dict[str, Any]]] = [[dets[0]]]
    for d in dets[1:]:
        prev = rows[-1]
        prev_h = max(p["y1"] - p["y0"] for p in prev)
        gap = (d["y0"] + d["y1"]) / 2.0 - max(
            (p["y0"] + p["y1"]) / 2.0 for p in prev
        )
        if gap > prev_h * _ROW_SPLIT_RATIO:
            rows.append([d])
        else:
            prev.append(d)
    sep = "" if lang in _NO_SPACE_LANGS else " "
    text = sep.join(sep.join(x["text"] for x in sorted(row, key=lambda x: x["x0"]))
                    for row in rows)
    conf = min(d["conf"] for d in dets)
    boxes = [[d["x0"], d["y0"], d["x1"], d["y1"]] for d in dets]
    return text, conf, boxes


def merge_frames_to_lines(
    frames: list[OcrFrameRecord],
    *,
    interval_s: float = OCR_SAMPLE_INTERVAL_S,
    lang: str = "zh",
    video_dur: Optional[float] = None,
) -> list[OcrLineRecord]:
    """帧级检出 → 字幕行（§4 M2：字幕变化处合并去重）。

    相邻采样帧归一化文本相同（允许 ≤:data:`_MERGE_GAP_STEPS` 个采样步的断裂，
    桥掉单帧识别抖动）合并为一行；行起止 = 首/末命中采样时刻 ∓ 半步
    （采样粒度 0.2s 下的中心化修正，实测误差 ≤0.1s，通过线 0.3s）。
    """
    sep = "" if lang in _NO_SPACE_LANGS else " "
    lines: list[OcrLineRecord] = []
    cur: dict[str, Any] | None = None
    max_gap = interval_s * _MERGE_GAP_STEPS + 1e-6

    def close(c: dict[str, Any] | None) -> None:
        if not c:
            return
        start = max(0.0, round(c["first_t"] - interval_s / 2.0, 3))
        end = round(c["last_t"] + interval_s / 2.0, 3)
        if video_dur is not None:
            end = min(end, round(float(video_dur), 3))
        if end <= start:
            end = round(start + interval_s / 2.0, 3)
        lines.append(
            OcrLineRecord(
                start=start, end=end, text=c["text"],
                conf=round(c["conf_sum"] / c["n"], 4), frames=c["n"],
                x0=min(b[0] for b in c["boxes"]), y0=min(b[1] for b in c["boxes"]),
                x1=max(b[2] for b in c["boxes"]), y1=max(b[3] for b in c["boxes"]),
            )
        )

    for fr in frames:
        key = normalize_text(fr.text)
        if cur is not None and key == cur["key"] and fr.t - cur["last_t"] <= max_gap:
            cur["last_t"] = fr.t
            cur["n"] += 1
            cur["conf_sum"] += fr.conf
            cur["boxes"].extend(fr.boxes)
            continue
        close(cur)
        cur = {
            "key": key, "text": fr.text.replace("\n", sep), "first_t": fr.t,
            "last_t": fr.t, "n": 1, "conf_sum": fr.conf, "boxes": list(fr.boxes),
        }
    close(cur)
    lines.sort(key=lambda ln: (ln.start, ln.end))
    return lines


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _video_dur(video: str | Path) -> float:
    import json
    import subprocess

    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    if r.returncode != 0:
        raise M2Error(f"ffprobe 失败: {(r.stderr or '').strip()[:300]}")
    return float(json.loads(r.stdout)["format"]["duration"])


def resolve_band(
    cfg: dict[str, Any] | None = None,
    *,
    band_y0: Optional[int] = None,
    band_y1: Optional[int] = None,
    full_frame: bool = False,
) -> tuple[int, int]:
    """字幕区（默认 = pipeline.yaml ``erase_band``，与 M11 擦除带同源）。"""
    cfg = cfg if cfg is not None else load_pipeline_config()
    erase = cfg.get("erase_band") or {}
    if full_frame:
        media = {**{"height": 1920}, **(cfg.get("media") or {})}
        return 0, int(media["height"])
    y0 = int(band_y0 if band_y0 is not None else erase.get("y0_px", 1440))
    y1 = int(band_y1 if band_y1 is not None else erase.get("y1_px", 1780))
    if not (0 <= y0 < y1):
        raise M2Error(f"字幕区非法: y0={y0} ≥ y1={y1}")
    return y0, y1


def run(
    ep: str,
    *,
    lang: str = "zh",
    interval_s: float = OCR_SAMPLE_INTERVAL_S,
    scale: float = _SAMPLE_SCALE,
    min_conf: float = _REC_SCORE_MIN,
    band_y0: Optional[int] = None,
    band_y1: Optional[int] = None,
    full_frame: bool = False,
    det_model: Optional[str] = None,
    rec_model: Optional[str] = None,
    no_asr: bool = False,
    jobs_root: str | Path | None = None,
    engine: Optional[SubtitleOcr] = None,
) -> dict[str, Any]:
    """M2 主流程：01_media 视频 → 03_ocr 两件产物 + 04_dial/utterances.jsonl 融合。

    纯 OCR 模式（ASR 缺席 / --no-asr）：C2 行全部来自 OCR 行（agree=False）。
    返回摘要 dict（含各产物路径与计数）。
    """
    cfg = load_pipeline_config()
    root = ep_dir(ep, Path(jobs_root) if jobs_root else Path(cfg["paths"]["jobs_dir"]))
    media = {**{"width": 1080, "height": 1920, "fps": 25}, **(cfg.get("media") or {})}
    video = root / "01_media" / f"video_{int(media['width'])}x{int(media['height'])}_{int(media['fps'])}fps.mp4"
    if not video.is_file():
        raise M2Error(f"M1 产物不存在: {video}（先跑 python -m pipeline.m1_ingest --ep {ep} …）")

    y0, y1 = resolve_band(cfg, band_y0=band_y0, band_y1=band_y1, full_frame=full_frame)
    dur = _video_dur(video)
    ocr = engine if engine is not None else SubtitleOcr(scale=scale, min_conf=min_conf,
                                                        det_model=det_model, rec_model=rec_model)

    # ① 逐帧采样 + OCR（只记非空帧）
    raw: list[OcrFrameRecord] = []
    n_sampled = 0
    for t, band in sample_band(video, y0=y0, y1=y1, interval_s=interval_s):
        n_sampled += 1
        text, conf, boxes = _frame_caption(ocr.read_band(band), lang=lang)
        if text:
            y_off = 0 if full_frame else y0
            gboxes = [[b[0], b[1] + y_off, b[2], b[3] + y_off] for b in boxes]
            raw.append(OcrFrameRecord(t=t, text=text, conf=round(conf, 4), boxes=gboxes))

    # ② 合并去重 → 字幕行
    lines = merge_frames_to_lines(raw, interval_s=interval_s, lang=lang, video_dur=dur)
    ocr_dir = root / "03_ocr"
    C.dump_jsonl(ocr_dir / "ocr_raw.jsonl", raw)
    C.dump_jsonl(ocr_dir / "ocr_merged.jsonl", lines)

    # ③ OCR↔ASR 投票融合 → C2 出口（ASR 缺席退化为纯 OCR）
    dial = root / "04_dial"
    utt_path = dial / "utterances.jsonl"
    asr_utts: list[C.Utterance] = []
    if not no_asr and utt_path.is_file():
        asr_utts = list(C.load_jsonl(utt_path, C.UtteranceTable).root)
    merged = merge_ocr_asr(ep, lines, asr_utts, lang=lang)
    asr_ids = {u.utt_id for u in asr_utts}
    n_matched = sum(1 for u in merged if u.utt_id in asr_ids)
    C.upsert_jsonl(utt_path, merged, container=C.UtteranceTable)

    return {
        "ep": ep,
        "video": str(video),
        "band": [y0, y1],
        "duration_s": dur,
        "n_frames_sampled": n_sampled,
        "n_frames_with_text": len(raw),
        "n_lines": len(lines),
        "n_asr_utts": len(asr_utts),
        "n_matched": n_matched,
        "n_ocr_only": len(lines) - n_matched,
        "ocr_raw": str(ocr_dir / "ocr_raw.jsonl"),
        "ocr_merged": str(ocr_dir / "ocr_merged.jsonl"),
        "utterances": str(utt_path),
        "texts": [ln.text for ln in lines],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.m2_ocr",
        description="M2 硬字幕 OCR + OCR↔ASR 校对（纯 OCR 可独立跑）",
    )
    ap.add_argument("--ep", required=True, help="集 ID，如 ep01")
    ap.add_argument("--lang", default="zh", help="字幕语种（默认 zh；连写语种拼接无空格）")
    ap.add_argument("--interval", type=float, default=OCR_SAMPLE_INTERVAL_S,
                    help=f"采样间隔秒（冻结默认 {OCR_SAMPLE_INTERVAL_S}）")
    ap.add_argument("--scale", type=float, default=_SAMPLE_SCALE,
                    help=f"字幕带推理降采样系数（默认 {_SAMPLE_SCALE}，1.0=全尺寸）")
    ap.add_argument("--min-conf", type=float, default=_REC_SCORE_MIN,
                    help="帧内检出框保留的最低置信")
    ap.add_argument("--band-y0", type=int, default=None, help="字幕区上沿 px（默认取 erase_band）")
    ap.add_argument("--band-y1", type=int, default=None, help="字幕区下沿 px（默认取 erase_band）")
    ap.add_argument("--full-frame", action="store_true", help="扫全画幅（默认只扫字幕区）")
    ap.add_argument("--det-model", default=None, help="检测模型名（默认引擎内置）")
    ap.add_argument("--rec-model", default=None, help="识别模型名（默认引擎内置）")
    ap.add_argument("--no-asr", action="store_true", help="跳过 ASR 投票（强制纯 OCR 模式）")
    ap.add_argument("--jobs-dir", default=None, help="jobs 根目录（默认取 configs）")
    args = ap.parse_args(argv)

    try:
        summary = run(
            args.ep,
            lang=args.lang,
            interval_s=args.interval,
            scale=args.scale,
            min_conf=args.min_conf,
            band_y0=args.band_y0,
            band_y1=args.band_y1,
            full_frame=args.full_frame,
            det_model=args.det_model,
            rec_model=args.rec_model,
            no_asr=args.no_asr,
            jobs_root=args.jobs_dir,
        )
    except (M2Error, FileNotFoundError, ValidationError) as exc:
        print(f"FAIL m2_ocr: {exc}")
        return 1
    print(
        f"OK m2_ocr ep={summary['ep']} band={summary['band']} dur={summary['duration_s']}s "
        f"frames={summary['n_frames_sampled']}(hit={summary['n_frames_with_text']}) "
        f"lines={summary['n_lines']} asr={summary['n_asr_utts']} "
        f"matched={summary['n_matched']} ocr_only={summary['n_ocr_only']}"
    )
    for ln in summary["texts"]:
        print(f"   [{ln}]")
    print(f"   03_ocr/ocr_raw.jsonl / ocr_merged.jsonl / 04_dial/utterances.jsonl 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
