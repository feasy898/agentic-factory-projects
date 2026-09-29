"""M11 字幕擦除 + 目标语渲染 eval（规划 §4 M11；任务 T8 冻结口径）。

冻结 eval 命令::

    pytest tests/test_m11.py

§4 M11 原文通过线（自验收口径按任务 T8：drawtext 压中文字幕的样本）：
  ① 擦除后重跑 M2 OCR：**中文字符命中 = 0**（§4 原文：3 段素材各一遍）；
  ② AI 标识区像素 diff = 0（擦除前后裁剪区哈希一致；lossless 基带保证
     带外像素零改动，delogo 只动字幕窗内像素）；
  ③ ar 字幕：RTL 方向与字母连接正确（libass+fribidi 生效）——
     程序断言用"孤立字形探针"（ا ب ت 三簇，窄簇 alef 必在最右），
     截图目测由人工/任务 agent 复核（tmp/m11_frames/*.png）；
  ④ 60s 素材擦除+渲染 ≤40 分钟 CPU（记录实测，不设断言——合成样本量级）。

覆盖面：
  ① 冻结 eval（合成中文硬字幕 → 擦除 → 重跑 OCR 零中文命中；delogo/inpaint
     双轻量引擎各一遍 + 第三段 delogo 素材）；label_zone 哈希一致性；
  ② ASS 生成与 C2×C4 装配（en 左下/ar 右下 RTL；ar 文本逻辑序直书）；
  ③ ffmpeg 压制：en/ar 成片抽帧断言（en 贴左边距、ar 贴右边距；
     ar 方向探针三簇窄字在右）+ 时长校验；
  ④ 几何纯函数（外扩/入带裁剪/标识区剖分/滤镜链/统计）；
  ⑤ 引擎注册表（默认 delogo、未知报错、vsr 接口预留选中即报错不降级）；
  ⑥ CLI 真实子进程（全流程 + --skip-erase + vsr 报错 + 缺失输入报错）。

素材：0x303030 深灰底 + 白色中文硬字幕（drawtext，y≈1560，字体 msyhbd，
字号 62，落在 erase_band 1440–1780）+ 顶部 AI 标识文本（label_zone
60–180 内，验证擦除不蹭标识区）。行间 ≥0.4s 空档。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from pipeline import contracts as C
from pipeline import m11_subs as M
from pipeline.config import REPO_ROOT, load_pipeline_config
from pipeline.m1_ingest import FFMPEG, main as m1_main
from pipeline.m2_ocr import OcrLineRecord, main as m2_main, normalize_text

# ---------------------------------------------------------------------------
# 素材与人工标注（压制时刻即真值）
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc",
                    "C:/Windows/Fonts/simhei.ttf")


def _cn_font() -> str | None:
    for f in _FONT_CANDIDATES:
        if Path(f).is_file():
            return f
    return None


FONT = _cn_font()

#: 主素材：5 行台词（起, 止, 文本）+ 全程 AI 标识文本
GT_LINES: list[tuple[float, float, str]] = [
    (0.8, 2.6, "你到底想怎么样？把话说清楚。"),
    (3.0, 4.8, "三年了，哪一样不是我做的？"),
    (5.2, 7.0, "那你就可以这样对我吗！"),
    (7.4, 9.2, "我以为你至少会信我。"),
    (9.6, 11.4, "海南孤岛，也有明月。"),
]
MAIN_DUR = 12.0
#: 第三段素材（delogo，③-1）
COMP_LINES: list[tuple[float, float, str]] = [
    (0.6, 2.0, "程氏的项目不能倒。"),
    (2.4, 3.8, "预算超了，档期不能动。"),
]
#: inpaint 引擎素材（③-2）
INPAINT_LINES: list[tuple[float, float, str]] = [
    (0.7, 1.9, "海南孤岛，也有明月。"),
    (2.1, 3.3, "琼州的海，也是故乡。"),
]
#: CLI 子进程素材（全流程，含擦除）
CLI_LINES: list[tuple[float, float, str]] = [
    (0.6, 2.0, "程氏的项目不能倒。"),
]
CLI_DUR = 3.5

AI_LABEL_TEXT = "本内容由AI生成"

#: 目标语译文（主素材 5 句，与 GT_LINES 一一对应）
EN_TRANSLATIONS = [
    "What do you actually want? Say it clearly.",
    "Three years. Which part of it was not built by me?",
    "How could you treat me like this!",
    "I thought you would believe me.",
    "Even a lonely island has its moon.",
]
ES_TRANSLATIONS = [
    "¿Qué es lo que realmente quieres? Habla claro.",
    "Tres años. ¿Qué parte no construí yo?",
    "¡Cómo pudiste tratarme así!",
    "Pensé que al menos me creerías.",
    "Hasta una isla solitaria tiene su luna.",
]
AR_TRANSLATIONS = [
    "ماذا تريد أن تفعل حقاً؟ تكلم بوضوح.",
    "ثلاث سنوات، أي جزء لم أبنه بنفسي؟",
    "كيف تستطيع أن تعاملني هكذا!",
    "كنت أعتقد أنك ستصدقني.",
    "حتى الجزيرة المعزولة لها قمرها.",
]

#: ar RTL 方向探针：孤立字母（空格断开连接，避免 shaping 干扰宽度判定）
AR_PROBE_TEXT = "ا ب ت"
#: ar shaping 探针：词形直连（1 个连通簇）vs 空格断开（4 个孤立簇）——
#: 上下文成形是否生效的判据（ZWNJ 亦可断连接但零宽不产生间隙，簇分析不可见）
AR_JOIN_WORD = "سلام"
AR_JOIN_SPACED = " ".join(AR_JOIN_WORD)

EP = "ep01"
BAND = (1440, 1780)          # 与 configs/pipeline.yaml erase_band 同源
LABEL_ZONE = (0, 60, 1080, 180)   # 与 pipeline.yaml label_zone 同源
TEXT_Y = 1560
FONTSIZE = 62
VIDEO_SIZE = (1080, 1920)
FPS = 25

FRAMES_DIR = REPO_ROOT / "tmp" / "m11_frames"   # gitignored：ar 截图目测产物

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

pytestmark = pytest.mark.skipif(FONT is None, reason=f"无中文字体（{_FONT_CANDIDATES}）")


# ---------------------------------------------------------------------------
# 素材合成与抽取工具
# ---------------------------------------------------------------------------

def _burn_clip(dst: Path, gt: list[tuple[float, float, str]], dur: float) -> Path:
    """drawtext 压中文硬字幕 + 顶部 AI 标识文本（textfile 写 UTF-8，无 BOM）。"""
    work = dst.parent
    work.mkdir(parents=True, exist_ok=True)
    font_esc = FONT.replace(":", "\\:")
    chain = []
    for i, (a, b, text) in enumerate(gt):
        tf = work / f"sub{i}.txt"
        tf.write_text(text, encoding="utf-8")
        chain.append(
            f"drawtext=fontfile='{font_esc}':textfile=sub{i}.txt:"
            f"fontcolor=white:borderw=3:bordercolor=black@0.85:fontsize={FONTSIZE}:"
            f"x=(w-text_w)/2:y={TEXT_Y}:enable='between(t,{a},{b})'"
        )
    tf = work / "label.txt"
    tf.write_text(AI_LABEL_TEXT, encoding="utf-8")
    chain.append(
        f"drawtext=fontfile='{font_esc}':textfile=label.txt:"
        f"fontcolor=white:borderw=3:bordercolor=black@0.85:fontsize=44:"
        f"x=(w-text_w)/2:y=70:enable='between(t,0,{dur})'"
    )
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi",
           "-i", f"color=c=0x303030:size=1080x1920:rate=25:duration={dur}",
           "-vf", ",".join(chain), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)]
    subprocess.run(cmd, check=True, timeout=600, capture_output=True, text=True,
                   cwd=str(work), encoding="utf-8", errors="replace")
    assert dst.is_file() and dst.stat().st_size > 0
    return dst


def _extract_frame(video: Path, t: float, out: Path) -> np.ndarray:
    """按时间抽帧（输出端精确 seek）→ PNG 落盘并返回 BGR ndarray。

    imread 走 np.fromfile+imdecode：cv2.imread 不支持非 ASCII 路径
    （T7 实测口径；本仓路径含中文）。
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
           "-ss", str(t), "-frames:v", "1", str(out)]
    subprocess.run(cmd, check=True, timeout=120, capture_output=True,
                   text=True, encoding="utf-8", errors="replace")
    import cv2
    assert out.is_file(), f"ffmpeg 未产出抽帧文件: {out}"
    img = cv2.imdecode(np.fromfile(str(out), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.size > 0
    return img


def _band_ink(img: np.ndarray, *, y0: int = 1500, y1: int = 1680) -> tuple[int, int, int, int]:
    """字幕带内亮像素（白字黑边）统计 → (左半 ink, 右半 ink, 最左 ink x, 最右 ink x)。"""
    crop = img[y0:y1, :, :]
    gray = crop.mean(axis=2)
    mask = gray > 140
    left = int(mask[:, : mask.shape[1] // 2].sum())
    right = int(mask[:, mask.shape[1] // 2:].sum())
    cols = np.nonzero(mask.any(axis=0))[0]
    if len(cols) == 0:
        return left, right, -1, -1
    return left, right, int(cols.min()), int(cols.max())


def _glyph_clusters(mask: np.ndarray, *, min_gap: int = 8) -> list[tuple[int, int]]:
    """列墨迹 → 字形簇（>min_gap 空列分簇）→ [(x_start,x_end)] 按 x 排序。"""
    col_ink = mask.any(axis=0)
    clusters: list[tuple[int, int]] = []
    run: list[int] | None = None
    gap = 0
    for x, v in enumerate(col_ink):
        if v:
            run = [x, x] if run is None else [run[0], x]
            gap = 0
        elif run is not None:
            gap += 1
            if gap >= min_gap:
                clusters.append((run[0], run[1]))
                run, gap = None, 0
    if run is not None:
        clusters.append((run[0], run[1]))
    return clusters


def _render_probe(text: str, *, lang: str = "ar", out_dir: Path, tag: str) -> np.ndarray:
    """用生产 ASS 样式渲染单行探针 → 抽 1 帧（1s 深灰底 + ``ass=`` 滤镜）。

    ``ass=`` 只传相对文件名并以 out_dir 为 cwd（同生产 burn_ass 的
    Windows 滤镜串转义口径）。
    """
    cfg = load_pipeline_config()
    style, _ = M.style_for_lang(cfg, lang)
    out_dir.mkdir(parents=True, exist_ok=True)
    ass_path = out_dir / f"probe_{tag}.ass"
    ass_path.write_text(M.build_ass([M.AssEvent(start=0.0, end=2.0, text=text)],
                                    style=style), encoding="utf-8")
    clip = out_dir / f"probe_{tag}_bg.mp4"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=0x303030:size=1080x1920:rate=25:duration=1.0",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                   check=True, timeout=120, capture_output=True, text=True)
    png = out_dir / f"probe_{tag}.png"
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(clip), "-vf", f"ass={ass_path.name}",
           "-ss", "0.5", "-frames:v", "1", str(png)]
    subprocess.run(cmd, check=True, timeout=120, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", cwd=str(out_dir))
    import cv2
    assert png.is_file(), f"ass 渲染未产出抽帧: {png}"
    img = cv2.imdecode(np.fromfile(str(png), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.size > 0
    return img


def _write_translations(path: Path, utts: list[C.Utterance], texts: list[str],
                        lang: str) -> None:
    """按 C2 行序构造 C4 翻译表并落盘（测试装配口径，非 M6 产物）。"""
    rows = []
    for u, text in zip(utts, texts):
        d = round(u.end - u.start, 3)
        rows.append(C.Translation(
            utt_id=u.utt_id, tgt=lang, context=[],
            budget=C.Budget(orig_dur=d, lo=0.001, hi=d + 0.001),
            candidates=[C.Candidate(text=text, syl=len(text), est_dur=d,
                                    src="eval-fixed", q=1.0)],
            chosen=0, policy="in-budget-first"))
    C.dump_jsonl(path, C.TranslationTable.model_validate(rows))


def _load_ocr_lines(path: Path) -> list[OcrLineRecord]:
    """M2 的 OcrLineRecord 是普通模型（非 RootModel 容器）→ 直接返回列表。"""
    return list(C.load_jsonl(path, OcrLineRecord))


def _reocr_cjk_residual(jobs: Path, ep: str, video_to_ocr: Path) -> tuple[int, list[str]]:
    """把待检视频放回 M2 输入位并重跑 OCR → (中文字符命中行数, 命中文本)。

    快照 01_media 视频 + 03_ocr 两件 + C2 utterances，跑完一律还原
    （残留测量只取当次 ocr_merged.jsonl 读数，不污染后续用例的擦除前
    素材与 C2 口径）。
    """
    media = jobs / ep / "01_media"
    target = media / "video_1080x1920_25fps.mp4"
    def _snap(path: Path) -> bytes:
        return path.read_bytes() if path.stat().st_size else b""

    snapshot = {
        "video": target.read_bytes(),
        "ocr_raw": _snap(jobs / ep / "03_ocr" / "ocr_raw.jsonl"),
        "ocr_merged": _snap(jobs / ep / "03_ocr" / "ocr_merged.jsonl"),
        "utterances": _snap(jobs / ep / "04_dial" / "utterances.jsonl"),
    }
    try:
        shutil.copyfile(video_to_ocr, target)
        rc = m2_main(["--ep", ep, "--jobs-dir", str(jobs)])
        assert rc == 0
        lines = _load_ocr_lines(jobs / ep / "03_ocr" / "ocr_merged.jsonl")
    finally:
        target.write_bytes(snapshot["video"])
        (jobs / ep / "03_ocr" / "ocr_raw.jsonl").write_bytes(snapshot["ocr_raw"])
        (jobs / ep / "03_ocr" / "ocr_merged.jsonl").write_bytes(snapshot["ocr_merged"])
        (jobs / ep / "04_dial" / "utterances.jsonl").write_bytes(snapshot["utterances"])
    hits = [ln.text for ln in lines if _CJK_RE.search(ln.text)]
    return len(hits), hits


# ---------------------------------------------------------------------------
# fixtures（module 级：一次合成 + 一次 M1 + 一次 M2 + 一次擦除）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def main_clip(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("m11_clip")
    return _burn_clip(d / "ep01_raw.mp4", GT_LINES, MAIN_DUR)


@pytest.fixture(scope="module")
def main_jobs(tmp_path_factory, main_clip) -> Path:
    d = tmp_path_factory.mktemp("m11_jobs")
    assert m1_main(["--ep", EP, "--in", str(main_clip), "--jobs-dir", str(d)]) == 0
    assert m2_main(["--ep", EP, "--jobs-dir", str(d)]) == 0   # 真实 OCR（自拍素材口径）
    return d


@pytest.fixture(scope="module")
def main_job(main_jobs) -> dict:
    """主素材一次擦除（delogo，基带=01_media/video_…_clean.mp4）+ 原始 OCR 行。

    原始 OCR 行读入内存固化（残留用例覆写 03_ocr 后仍可断言擦除前口径）。
    """
    original_lines = _load_ocr_lines(main_jobs / EP / "03_ocr" / "ocr_merged.jsonl")
    summary = M.run(EP, "en", skip_erase=False, burn=False, jobs_root=main_jobs)  # type: ignore[arg-type]
    assert summary["engine"] == "delogo"
    clean = main_jobs / EP / "01_media" / "video_1080x1920_25fps_clean.mp4"
    assert clean.is_file()
    return {"jobs": main_jobs, "lines": original_lines, "clean": clean,
            "summary": summary}


@pytest.fixture(scope="module")
def main_burned(main_jobs, main_job) -> dict:
    """目标语 ASS + en/ar 压制（基带=主素材擦除产物；C4 一次写 en+ar 复合表）。"""
    jobs = main_jobs
    utts = list(C.load_jsonl(jobs / EP / "04_dial" / "utterances.jsonl",
                             C.UtteranceTable).root)
    assert len(utts) == len(GT_LINES), f"C2 行数 {len(utts)} != 标注 {len(GT_LINES)}"
    rows = []
    for u, en, es, ar in zip(utts, EN_TRANSLATIONS, ES_TRANSLATIONS, AR_TRANSLATIONS):
        d = round(u.end - u.start, 3)
        for lang, text in (("en", en), ("es", es), ("ar", ar)):
            rows.append(C.Translation(
                utt_id=u.utt_id, tgt=lang, context=[],
                budget=C.Budget(orig_dur=d, lo=0.001, hi=d + 0.001),
                candidates=[C.Candidate(text=text, syl=len(text), est_dur=d,
                                    src="eval-fixed", q=1.0)],
                chosen=0, policy="in-budget-first"))
    C.dump_jsonl(jobs / EP / "06_mt" / "translations.jsonl",
                 C.TranslationTable.model_validate(rows))
    en_sum = M.run(EP, "en", skip_erase=True, burn=True, jobs_root=jobs)  # type: ignore[arg-type]
    ar_sum = M.run(EP, "ar", skip_erase=True, burn=True, jobs_root=jobs)  # type: ignore[arg-type]
    return {"en": en_sum, "ar": ar_sum, "utts": utts, "jobs": jobs}


@pytest.fixture(scope="module")
def clean_job(tmp_path_factory) -> dict:
    """第三段素材：delogo 擦除 + 重跑 OCR 残留（冻结线：中文命中=0）。"""
    d = tmp_path_factory.mktemp("m11_clip3")
    clip = _burn_clip(d / "ep03_raw.mp4", COMP_LINES, 4.0)
    jobs = tmp_path_factory.mktemp("m11_jobs3")
    assert m1_main(["--ep", "ep03", "--in", str(clip), "--jobs-dir", str(jobs)]) == 0
    assert m2_main(["--ep", "ep03", "--jobs-dir", str(jobs)]) == 0
    s = M.run("ep03", "en", skip_erase=False, burn=False, jobs_root=jobs)  # type: ignore[arg-type]
    assert s["engine"] == "delogo"
    video = jobs / "ep03" / "01_media" / "video_1080x1920_25fps.mp4"
    clean = jobs / "ep03" / "01_media" / "video_1080x1920_25fps_clean.mp4"
    assert clean.is_file()
    hits, texts = _reocr_cjk_residual(jobs, "ep03", clean)
    return {"jobs": jobs, "video": video, "clean": clean, "cjk_hits": hits,
            "cjk_texts": texts, "summary": s}


@pytest.fixture(scope="module")
def inpaint_job(tmp_path_factory) -> dict:
    """第三段素材（inpaint 引擎）：cv2 TELEA 修复 + 重跑 OCR 残留。"""
    d = tmp_path_factory.mktemp("m11_clip4")
    clip = _burn_clip(d / "ep04_raw.mp4", INPAINT_LINES, 4.0)
    jobs = tmp_path_factory.mktemp("m11_jobs4")
    assert m1_main(["--ep", "ep04", "--in", str(clip), "--jobs-dir", str(jobs)]) == 0
    assert m2_main(["--ep", "ep04", "--jobs-dir", str(jobs)]) == 0
    s = M.run("ep04", "en", engine="inpaint", skip_erase=False, burn=False,
              jobs_root=jobs)  # type: ignore[arg-type]
    assert s["engine"] == "inpaint"
    clean = jobs / "ep04" / "01_media" / "video_1080x1920_25fps_clean.mp4"
    assert clean.is_file()
    hits, texts = _reocr_cjk_residual(jobs, "ep04", clean)
    return {"jobs": jobs, "clean": clean, "cjk_hits": hits, "cjk_texts": texts,
            "summary": s}


# ---------------------------------------------------------------------------
# ① 冻结 eval：擦除后重跑 OCR 中文字符命中 = 0（3 段素材各一遍）
# ---------------------------------------------------------------------------

def test_erase_delogo_no_cjk_residual_third_clip(clean_job):
    assert clean_job["cjk_hits"] == 0, f"delogo 擦除后仍检出中文: {clean_job['cjk_texts']}"
    assert clean_job["summary"]["erase"]["n_regions"] >= len(COMP_LINES)


def test_erase_inpaint_no_cjk_residual(inpaint_job):
    assert inpaint_job["cjk_hits"] == 0, (
        f"inpaint 擦除后仍检出中文: {inpaint_job['cjk_texts']}")


def test_erase_main_clip_delogo_no_cjk_residual(main_jobs, main_job):
    """主素材（5 行）：delogo 重跑 OCR 中文命中=0（§4 M11 ① 主线样本）。"""
    jobs, lines = main_jobs, main_job["lines"]
    assert len(lines) == len(GT_LINES), f"擦除前 OCR 行 {len(lines)} != 标注 {len(GT_LINES)}"
    video = jobs / EP / "01_media" / "video_1080x1920_25fps.mp4"
    clean = jobs / EP / "01_media" / "video_1080x1920_25fps_clean.mp4"
    assert video.is_file() and clean.is_file()
    hits, texts = _reocr_cjk_residual(jobs, EP, clean)
    assert hits == 0, f"主素材擦除后仍检出中文: {texts}"


# ---------------------------------------------------------------------------
# ② AI 标识区：擦除前后像素零改动（哈希一致）+ 字幕带确被擦动（非空操作）
# ---------------------------------------------------------------------------

def test_label_zone_untouched_and_band_changed(main_jobs, main_job):
    video = main_jobs / EP / "01_media" / "video_1080x1920_25fps.mp4"
    clean = main_jobs / EP / "01_media" / "video_1080x1920_25fps_clean.mp4"
    for t in (1.5, 6.0):   # 两个不同字幕行时刻，各采一次
        pre = _extract_frame(video, t, FRAMES_DIR / f"pre_{t}.png")
        post = _extract_frame(clean, t, FRAMES_DIR / f"post_{t}.png")
        pre_zone = pre[LABEL_ZONE[1]:LABEL_ZONE[3], LABEL_ZONE[0]:LABEL_ZONE[2], :]
        post_zone = post[LABEL_ZONE[1]:LABEL_ZONE[3], LABEL_ZONE[0]:LABEL_ZONE[2], :]
        assert np.array_equal(pre_zone, post_zone), (
            f"t={t}: AI 标识区（label_zone {LABEL_ZONE}）像素被擦除改动")
        # 字幕带在字幕行时刻必须确被擦动（防"什么都没做也哈希一致"）
        pre_band = pre[1500:1700, 250:830, :]
        post_band = post[1500:1700, 250:830, :]
        assert not np.array_equal(pre_band, post_band), (
            f"t={t}: 字幕带区域未被改动（擦除无效）")


# ---------------------------------------------------------------------------
# ③ ASS 装配：C2×C4 → ar 文本逻辑序直书 + en/es 左对齐 / ar 右对齐
# ---------------------------------------------------------------------------

def test_ass_en_es_ar_alignment_and_logical_order(main_burned):
    cfg = load_pipeline_config()

    # 样式：en/es 左下（1）、ar 右下（3）；字体候选解析
    st_en, font_en = M.style_for_lang(cfg, "en")
    st_es, _ = M.style_for_lang(cfg, "es")
    st_ar, font_ar = M.style_for_lang(cfg, "ar")
    assert (st_en.align, st_es.align) == (1, 1)
    assert st_ar.align == 3
    assert st_ar.font == "Noto Naskh Arabic"
    assert font_en is not None and font_ar is not None
    assert font_ar.name == "NotoNaskhArabic-Bold.ttf"
    assert st_ar.margin_v == 220 and st_en.margin_v == 220

    # ar 文件内容：逻辑序直书（不预反转/不预整形），样式头与事件数
    tgt_ass = Path(main_burned["ar"]["tgt_ass"])
    raw = tgt_ass.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in raw and "PlayResY: 1920" in raw
    assert f"Style: TGT,Noto Naskh Arabic,62," in raw
    assert raw.count("Dialogue: 0,") == len(AR_TRANSLATIONS)
    for text in AR_TRANSLATIONS:      # 原样携带（含标点），未经反转
        assert text in raw, f"ar 文本非逻辑序或丢失: {text!r}"
    # en 同样直书
    tgt_en = Path(main_burned["en"]["tgt_ass"]).read_text(encoding="utf-8")
    assert "Style: TGT,Noto Sans,62," in tgt_en
    for text in EN_TRANSLATIONS:
        assert text in tgt_en

    # es 渲染：C4 es 行 → 全装配（es 与 en 同侧样式，样式行已断言，不重复压制）
    utts = main_burned["utts"]
    translations = list(C.load_jsonl(main_burned["jobs"] / EP / "06_mt" / "translations.jsonl",
                                     C.TranslationTable).root)
    events, stats = M.subtitle_events(utts, translations, "es")
    assert stats["n_events"] == len(utts) and stats["n_skipped_no_translation"] == 0
    assert events[0].text == ES_TRANSLATIONS[0], events[0].text


def test_ass_timestamp_and_sanitize():
    assert M.ass_timestamp(0) == "0:00:00.00"
    assert M.ass_timestamp(2.6) == "0:00:02.60"
    assert M.ass_timestamp(3723.456) == "1:02:03.46"
    assert M.ass_timestamp(-1) == "0:00:00.00"
    assert M.sanitize_ass_text("a\nb") == "a\\Nb"
    assert M.sanitize_ass_text("a{b}override") == "aboverride"


def test_subtitle_events_skips_missing():
    u = C.Utterance(utt_id="epX-u0001", shot_id="s0000", start=1.0, end=2.0,
                    lang="zh", text="甲")
    no_row = M.subtitle_events([u], [], "en")[1]
    assert no_row["n_skipped_no_translation"] == 1 and no_row["n_events"] == 0
    t = C.Translation(utt_id="epX-u0001", tgt="en",
                      budget=C.Budget(orig_dur=1.0, lo=0.1, hi=1.0),
                      candidates=[C.Candidate(text="A", syl=1, est_dur=1.0, src="x", q=1.0)],
                      chosen=None)
    ev, st = M.subtitle_events([u], [t], "en")
    assert st["n_skipped_no_candidate"] == 1
    t2 = t.model_copy(update={"chosen": 0})
    ev, st = M.subtitle_events([u], [t2], "en")
    assert st["n_events"] == 1 and ev[0].text == "A"
    assert (round(ev[0].start, 3), round(ev[0].end, 3)) == (1.0, 2.0)


def test_build_ass_structure():
    style = M.SubStyle(name="TGT", font="Noto Sans", fontsize=62)
    doc = M.build_ass([M.AssEvent(start=0.8, end=2.6, text="你好")], style=style)
    assert doc.startswith("[Script Info]")
    assert "ScriptType: v4.00+" in doc and "WrapStyle: 0" in doc
    assert "[V4+ Styles]" in doc and "[Events]" in doc
    assert "Dialogue: 0,0:00:00.80,0:00:02.60,TGT,,0,0,0,,你好" in doc
    empty = M.build_ass([], style=style)
    assert "[Events]" in empty and "Dialogue" not in empty


# ---------------------------------------------------------------------------
# ④ 几何纯函数（外扩 / 入带裁剪 / 标识区排除 / 滤镜链 / 统计）
# ---------------------------------------------------------------------------

def test_geometry_pure():
    assert M.expand_rect((100, 1530, 900, 1640), 4, 1080, 1920) == (96, 1526, 904, 1644)
    # 越界裁剪进画面
    assert M.expand_rect((0, 0, 1080, 1920), 4, 1080, 1920) == (0, 0, 1080, 1920)
    # 出带被丢弃（带边界外）
    assert M.clip_to_band((0, 100, 100, 200), (0, 1440, 1080, 1780)) is None
    assert M.clip_to_band((0, 1440, 100, 1900), (0, 1440, 1080, 1780)) == (0, 1440, 100, 1780)
    # 标识区剖分：不相交 → 原样；覆盖中部 → 只留下段（本矩形上沿低于标识上沿）；
    # 上凸型矩形 → 只留上段；完全包含 → 空
    assert M.subtract_label_zone((0, 1500, 1080, 1700), (0, 60, 1080, 180)) == [
        (0, 1500, 1080, 1700)]
    assert M.subtract_label_zone((0, 120, 1080, 300), (0, 60, 1080, 180)) == [
        (0, 180, 1080, 300)]
    assert M.subtract_label_zone((0, 0, 1080, 100), (0, 60, 1080, 180)) == [
        (0, 0, 1080, 60)]
    assert M.subtract_label_zone((0, 60, 1080, 180), (0, 60, 1080, 180)) == []


def test_build_erase_regions_stats_and_chain():
    lines = [
        M.EraseInputLine(start=0.8, end=2.6, x0=100, y0=1530, x1=900, y1=1640),      # 正常
        M.EraseInputLine(start=3.0, end=4.0, x0=10, y0=100, x1=400, y1=500),        # 出带（顶部）
        M.EraseInputLine(start=5.0, end=6.0, x0=200, y0=1520, x1=400, y1=1620),      # 带内
    ]
    regions, stats = M.build_erase_regions(
        lines, width=1080, height=1920, band=(0, 1440, 1080, 1780),
        label=(0, 60, 1080, 180), expand_px=4)
    assert stats["n_lines"] == 3 and stats["n_out_of_band"] == 1
    assert stats["n_label_split"] == 0 and stats["n_degenerate"] == 0
    assert stats["n_regions"] == 2

    # 标识区与擦除带相交的构造性场景（默认配置两者不相交；此处显式覆盖）
    lines2 = [
        M.EraseInputLine(start=0.8, end=2.6, x0=100, y0=120, x1=900, y1=300),       # 横跨标识区
        M.EraseInputLine(start=3.0, end=4.0, x0=100, y0=1530, x1=900, y1=1640),     # 正常
    ]
    regions2, stats2 = M.build_erase_regions(
        lines2, width=1080, height=1920, band=(0, 100, 1080, 1700),
        label=(0, 60, 1080, 180), expand_px=4)
    assert stats2["n_label_split"] == 1 and stats2["n_out_of_band"] == 0
    assert stats2["n_regions"] == 2      # 行1 剖出的下段 + 行2 整段
    assert all(r.y0 >= 180 for r in regions2 if r.t0 < 1), "横跨标识区的行只能留下段"
    r0 = regions[0]
    assert (r0.x0, r0.y0, r0.x1, r0.y1) == (96, 1526, 904, 1644)
    chain = M.delogo_chain(regions)
    assert chain.startswith("delogo=x=96:y=1526:w=808:h=118")
    assert "enable='between(t,0.800,2.600)'" in chain
    assert chain.count("delogo=") == 2 and "enable" in chain


def test_label_zone_rect_from_config():
    cfg = load_pipeline_config()
    assert M.label_zone_rect(cfg, 1080, 1920) == (0, 60, 1080, 180)
    cfg2 = dict(cfg); cfg2["label_zone"] = {"top_px": 0, "height_px": 500, "position": "top"}
    assert M.label_zone_rect(cfg2, 1080, 1920) == (0, 0, 1080, 500)


# ---------------------------------------------------------------------------
# ⑤ 引擎注册表：默认 delogo / 未知报错 / vsr 接口预留不降级
# ---------------------------------------------------------------------------

def test_backend_registry():
    cfg = load_pipeline_config()
    assert M.get_backend(None, cfg).name == "delogo"
    assert M.get_backend("inpaint").name == "inpaint"
    with pytest.raises(M.M11Error, match="未知擦除引擎"):
        M.get_backend("lama-magic")
    vsr = M.get_backend("vsr")
    assert vsr.available() is False
    with pytest.raises(M.M11Error, match="未安装"):
        vsr.erase("x", "y", [], width=1, height=1, fps=1)


def test_resolve_font_and_fonts_dir():
    fam, path = M.resolve_font(("Noto Sans",))
    assert fam == "Noto Sans" and path is not None and path.is_file()
    fam2, p2 = M.resolve_font(("NoSuchFont", "Tahoma"))
    assert fam2 == "Tahoma" and p2 is not None
    fam3, p3 = M.resolve_font(("NoSuchFont",), fonts_dir=Path("Z:/nonexistent"))
    assert fam3 == "NoSuchFont" and p3 is None


# ---------------------------------------------------------------------------
# ⑥ ffmpeg 压制：en 贴左边距、ar 贴右边距（12_out 抽帧）
# ---------------------------------------------------------------------------

def test_burn_en_left_aligned(main_burned):
    out = Path(main_burned["en"]["out"])
    assert out.is_file()
    img = _extract_frame(out, 1.5, FRAMES_DIR / "en_burn.png")
    left, right, xl, xr = _band_ink(img)
    assert left > 500 and right > 500, f"en 字幕未渲染（ink left/right={left}/{right}）"
    assert xl < 200, f"en 左下对齐未贴左边距（最左墨迹 x={xl}）"
    assert main_burned["en"]["burned_duration_s"] == pytest.approx(MAIN_DUR, abs=0.5)
    assert main_burned["en"]["n_tgt_events"] == len(EN_TRANSLATIONS)
    assert main_burned["en"]["n_skipped_no_translation"] == 0


def test_burn_ar_right_aligned_towards_margin(main_burned):
    out = Path(main_burned["ar"]["out"])
    img = _extract_frame(out, 1.5, FRAMES_DIR / "ar_burn.png")
    left, right, xl, xr = _band_ink(img)
    assert right > 500, f"ar 字幕未渲染（ink right={right}）"
    # 右对齐：整条字幕贴右边距（right margin=60 → 最右墨迹≈1020），左侧为净底
    assert xr > VIDEO_SIZE[0] - 200, f"ar 右对齐未贴右边距（最右墨迹 x={xr}）"
    assert left == 0 or left < right, f"ar 应偏右分布（left/right={left}/{right}）"


# ---------------------------------------------------------------------------
# ⑦ ar RTL 方向与连接断言（libass+fribidi 生效）
# ---------------------------------------------------------------------------

def test_ar_rtl_direction_probe_isolation():
    """孤立字母探针：逻辑首字母 ا（窄竖笔）应出现在**最右**簇 —— 证明 bidi 生效。"""
    img = _render_probe(AR_PROBE_TEXT, lang="ar", out_dir=FRAMES_DIR, tag="rtl_probe")
    band = img[1500:1700, :, :]
    mask = (band.mean(axis=2) > 140).astype(np.uint8)
    clusters = _glyph_clusters(mask, min_gap=8)
    widths = [x1 - x0 for x0, x1 in clusters]
    assert len(clusters) == 3, f"探针应得 3 个字形簇，得 {len(clusters)}: {clusters}"
    narrow_idx = int(np.argmin(widths))
    assert widths[narrow_idx] <= 0.6 * min(w for i, w in enumerate(widths) if i != narrow_idx), (
        f"最窄簇不显著窄（非 alef 竖笔？宽度={widths}）")
    assert narrow_idx == 2, (
        f"窄字形（逻辑首字母 ا）不在最右簇，RTL 方向错误：clusters={clusters}")


def test_ar_rtl_letter_joining_screenshot():
    """shaping 连接断言 + 截图目测件（任务 agent 复核 tmp/m11_frames/*.png）。

    同一词形直连（1 个连通簇）vs 空格断开（4 个孤立簇）—— 证明 harfbuzz
    上下文成形生效（连字/首中末形切换，不是 4 个等宽孤立形直排）。
    """
    def _n_clusters(text: str, tag: str) -> int:
        img = _render_probe(text, lang="ar", out_dir=FRAMES_DIR, tag=f"join_{tag}")
        band = img[1500:1700, :, :]
        mask = (band.mean(axis=2) > 140).astype(np.uint8)
        return len(_glyph_clusters(mask, min_gap=6))

    joined = _n_clusters(AR_JOIN_WORD, "word")
    spaced = _n_clusters(AR_JOIN_SPACED, "spaced")
    assert spaced == 4, f"空格断开应得 4 个孤立簇，得 {spaced}（渲染异常？）"
    assert joined == 1, f"直连词形应连通为 1 簇，得 {joined}（上下文成形未生效？）"

    # 目测件：真实 ar 译句正向渲染帧（RTL 方向由 test_ar_rtl_direction_probe 断言）
    _render_probe(AR_TRANSLATIONS[0], lang="ar", out_dir=FRAMES_DIR, tag="ar_sentence")


def test_m11_fixture_products_written(main_job, main_burned):
    """冻结槽位产物齐套：10_subs/{src,tgt} + 12_out + 01_media 擦除基带。"""
    jobs = main_job["jobs"]
    assert (jobs / EP / "10_subs" / "src.ass").is_file()
    assert (jobs / EP / "10_subs" / "tgt.en.ass").is_file()
    assert (jobs / EP / "10_subs" / "tgt.ar.ass").is_file()
    assert (jobs / EP / "12_out" / "ep01.en.mp4").is_file()
    assert (jobs / EP / "12_out" / "ep01.ar.mp4").is_file()
    assert (jobs / EP / "01_media" / "video_1080x1920_25fps_clean.mp4").is_file()
    src = (jobs / EP / "10_subs" / "src.ass").read_text(encoding="utf-8")
    assert "Style: ZH,Microsoft YaHei,62," in src
    assert src.count("Dialogue: 0,") == len(GT_LINES)


# ---------------------------------------------------------------------------
# ⑧ CLI 真实子进程（全流程 / --skip-erase / vsr 报错 / 缺失输入报错）
# ---------------------------------------------------------------------------

def _cli_jobs(tmp: Path, clip: Path, ep: str) -> Path:
    jobs = tmp / f"jobs_{ep}"
    assert m1_main(["--ep", ep, "--in", str(clip), "--jobs-dir", str(jobs)]) == 0
    assert m2_main(["--ep", ep, "--jobs-dir", str(jobs)]) == 0
    utts = list(C.load_jsonl(jobs / ep / "04_dial" / "utterances.jsonl",
                             C.UtteranceTable).root)
    _write_translations(jobs / ep / "06_mt" / "translations.jsonl", utts,
                        EN_TRANSLATIONS[:1] if ep == "epcli" else EN_TRANSLATIONS, "en")
    return jobs


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "pipeline.m11_subs", *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, env=env,
    )


def test_cli_full_flow(tmp_path):
    """§4 M11 CLI 冻结形态：全流程（擦除+ASS+压制）真实子进程。"""
    clip = _burn_clip(tmp_path / "cli_raw.mp4", CLI_LINES, CLI_DUR)
    jobs = _cli_jobs(tmp_path, clip, "epcli")
    r = _run_cli(["--ep", "epcli", "--lang", "en", "--jobs-dir", str(jobs)])
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "OK m11_subs ep=epcli lang=en engine=delogo" in r.stdout
    out = jobs / "epcli" / "12_out" / "epcli.en.mp4"
    assert out.is_file() and out.stat().st_size > 0
    assert (jobs / "epcli" / "10_subs" / "src.ass").is_file()
    assert (jobs / "epcli" / "01_media" / "video_1080x1920_25fps_clean.mp4").is_file()
    # 抽帧目测件（左对齐 + 目标语文本）
    img = _extract_frame(out, 1.2, FRAMES_DIR / "en_cli.png")
    left, right, xl, xr = _band_ink(img)
    assert left > 100 and xl < 200, f"CLI 成片 en 字幕未贴左边距（ink={left},{right} x={xl}）"


def test_cli_skip_erase_reuses_existing_clean(tmp_path):
    clip = _burn_clip(tmp_path / "cli2_raw.mp4", CLI_LINES, CLI_DUR)
    jobs = _cli_jobs(tmp_path, clip, "epcli2")
    r = _run_cli(["--ep", "epcli2", "--lang", "en", "--jobs-dir", str(jobs)])
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    mtime = (jobs / "epcli2" / "01_media" / "video_1080x1920_25fps_clean.mp4").stat().st_mtime
    out1 = jobs / "epcli2" / "12_out" / "epcli2.en.mp4"
    r2 = _run_cli(["--ep", "epcli2", "--lang", "en", "--skip-erase", "--jobs-dir", str(jobs)])
    assert r2.returncode == 0, f"stdout={r2.stdout}\nstderr={r2.stderr}"
    assert "engine=skip" in r2.stdout
    mtime2 = (jobs / "epcli2" / "01_media" / "video_1080x1920_25fps_clean.mp4").stat().st_mtime
    assert mtime2 == mtime, "--skip-erase 不应重做擦除基带"
    assert out1.is_file()


def test_cli_vsr_engine_reports_not_installed(tmp_path):
    clip = _burn_clip(tmp_path / "cli3_raw.mp4", CLI_LINES, CLI_DUR)
    jobs = _cli_jobs(tmp_path, clip, "epcli3")
    r = _run_cli(["--ep", "epcli3", "--lang", "en", "--engine", "vsr",
                  "--jobs-dir", str(jobs)])
    assert r.returncode == 1
    assert "FAIL m11_subs" in r.stdout and "未安装" in r.stdout
    assert "重型路线接口预留" in r.stdout
    assert not (jobs / "epcli3" / "01_media" / "video_1080x1920_25fps_clean.mp4").is_file()


def test_cli_missing_inputs(tmp_path):
    """M1 缺失 / OCR 缺失 → 可读 FAIL 提示 + 退出码 1。"""
    (tmp_path / "epX" / "01_media").mkdir(parents=True)
    r = _run_cli(["--ep", "epX", "--lang", "en", "--jobs-dir", str(tmp_path)])
    assert r.returncode == 1 and "M1 产物不存在" in r.stdout

    # M1 就绪但未跑 M2 → 报 OCR 缺失（引导先跑 m2_ocr）
    clip = _burn_clip(tmp_path / "cli4_raw.mp4", CLI_LINES, CLI_DUR)
    jobs = tmp_path / "jobs_epcli4"
    assert m1_main(["--ep", "epcli4", "--in", str(clip), "--jobs-dir", str(jobs)]) == 0
    r = _run_cli(["--ep", "epcli4", "--lang", "en", "--jobs-dir", str(jobs)])
    assert r.returncode == 1 and "OCR 产品不存在" in r.stdout and "m2_ocr" in r.stdout


def test_cli_missing_translations(tmp_path):
    clip = _burn_clip(tmp_path / "cli5_raw.mp4", CLI_LINES, CLI_DUR)
    jobs = tmp_path / "jobs_epcli5"
    assert m1_main(["--ep", "epcli5", "--in", str(clip), "--jobs-dir", str(jobs)]) == 0
    assert m2_main(["--ep", "epcli5", "--jobs-dir", str(jobs)]) == 0
    r = _run_cli(["--ep", "epcli5", "--lang", "en", "--jobs-dir", str(jobs)])
    assert r.returncode == 1 and "translations.jsonl" in r.stdout and "m6_translate" in r.stdout


def test_cli_unsupported_lang(tmp_path):
    clip = _burn_clip(tmp_path / "cli6_raw.mp4", CLI_LINES, CLI_DUR)
    jobs = _cli_jobs(tmp_path, clip, "epcli6")
    r = _run_cli(["--ep", "epcli6", "--lang", "ja", "--jobs-dir", str(jobs)])
    assert r.returncode == 2   # argparse choices 拒绝
