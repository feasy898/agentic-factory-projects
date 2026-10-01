#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端冒烟断言集（规划 §7 ``check_e2e.py``；任务 T22）。

用法（repo/.venv 解释器，repo 根为 cwd；由 scripts/e2e_smoke.sh 调用，也可手动跑）::

    python tests/check_e2e.py --ep e2e01 --langs en,es,ar [--jobs-dir <dir>] [--src clip.mp4]

断言集（每语种逐条打印 [PASS]/[FAIL]，任何 FAIL → 退出码 1）：
  1) 成片存在：12_out/<ep>.<lang>.mp4 存在（M9 合成必过）；09_lip/done 口型成片
     存在时以它为"最终成片"（M10 回贴在其上）。
  2) 成片时长 ≈ 原片：|dur(final) − dur(src)| ≤ 5%（规划 §7 冻结线）。
  3) 字幕区目标语渲染：
     - 重跑 OCR（cap-ocr，M2 同引擎同字幕带）：中文字符命中 = 0（§7 冻结线；
       同时覆盖"擦除残留=0"与"目标语字幕不含源语"）；
     - en/es：字幕带 OCR 检出非空文本 ≥1 行（目标语在位）；
     - ar：cap-ocr 对阿拉伯文识别不可靠（zh 引擎），改为双断言——
       a) 10_subs/tgt.ar.ass 样式 Alignment=3（右对齐，configs channels.ar
          subs_align=right-rtl）且事件文本与 C4 chosen 一致、含阿拉伯字母；
       b) 渲染像素在位且偏右：成片字幕带 vs 擦除基带同帧差分（墨迹占比）的
          水平质心落在右半幅（en/es 反向断言质心偏左，防样式串语种）。
     - 阿语字形方向/连接的正确性（fribidi shaping）由 M11 eval 人工抽检口径
       覆盖（规划 §4 M11 eval ③），本脚本只断言右对齐渲染在位，不重复实现。
  4) AI 标识在位（显式+元数据）：
     - 元数据：ffprobe 读成片 format tags，XMP:aiGeneratedContent 与
       11_labels/labels.json（C7）implicit.value 精确一致；
     - 显式：片头 3s 文字提示（drawtext，label_zone 顶部区）——t=1.0s 标识区
       墨迹在位（vs 擦除基带差分）且 OCR 命中"AI"字样，t>3.2s 标识区墨迹
       消失（仅片头 3s）。
  5) metrics 六项出数：12_out/metrics.<lang>.json 六项 status=ok
     （e2e_smoke 在每语种 m15 后快照的副本；本体 metrics.json 只留最后一语种）。
  6) 非口型帧不变：
     - 口型成片存在时：抽样窗外帧与 12_out 成片逐字节一致（M10 回贴无损透传
       的独立复核，不信任其自带 verify）；
     - 无口型成片（SKIP-LIP/空计划）时：最终成片=12_out 成片，抽样帧在
       "预期改动区"（字幕带 ∪ 片头标识区）之外与擦除基带一致（容差吸收
       压制噪声，阈值实测冻结于 THRESH）；
     - 两口径都断言成片帧数 = 母带帧数（帧级时长守恒）。
  7) C2 音轨铺满：C2 每个非 keep-original 句窗内 08_mix/dubbed.<lang>.wav
     非静音（静音句窗占比 <2%，§7 冻结线——3 句样本即全部句窗必须有声）。

阈值口径（THRESH）：e2e01 首跑实测冻结（2026-09-30，见 scripts/e2e_smoke.sh
运行日志）；CRF18 两代压制在平坦合成背景上的带外噪声实测 ≤0.37 灰阶均值，
阈值留 ≥8× 余量；墨迹/静音为量纲断言不依赖噪声底。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from pipeline.config import load_pipeline_config  # noqa: E402
from pipeline.m1_ingest import FFPROBE  # noqa: E402
from pipeline.scaffold import ep_dir  # noqa: E402

#: 断言阈值（e2e01 首跑实测冻结，2026-09-30：字幕带墨迹 en 0.024-0.039 /
#: es 0.026-0.035 / ar 0.010-0.012，标识区 0.31、片尾标识区 0.0000，
#: 预期改动区外 mean|Δ|≤0.37、强差 0——阈值取实测的 2~8 倍余量）
THRESH = {
    "dur_ratio": 0.05,            # §7：成片时长 |Δ|/dur(src) ≤5%
    "ink_min_ratio": 0.004,       # 字幕带/标识区"有字"：|Δ|>8 像素占比 ≥0.4%（实测最小 ar 0.0097）
    "ink_max_ratio": 0.60,        # 墨迹占比上限（防整带错帧等异常）
    "quiet_mean_abs": 3.0,        # 预期改动区之外灰阶均值差 ≤3.0（实测 CRF18×2 ≤0.37）
    "quiet_ink_ratio": 0.002,     # 预期改动区之外 |Δ|>16 像素占比 ≤0.2%（实测 0）
    "label_gone_ink_ratio": 0.001,  # 片尾静默帧标识区墨迹占比 ≤0.1%（实测 0.00004）
    "ar_centroid_right": 0.55,    # ar 字幕墨迹水平质心 > 0.55×宽（右对齐）
    "ltrl_centroid_left": 0.45,   # en/es 字幕墨迹水平质心 < 0.45×宽（左下）
    "silence_rms_dbfs": -50.0,    # 句窗静音判定（RMS 下限）
    "silence_frac_max": 0.02,     # §7：静音句窗占比 <2%
}

_METRIC_KEYS = (
    "speaker_similarity", "emotion_similarity", "listen_wer",
    "duration_alignment_rate", "lip_score", "cost_per_minute",
)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_AR_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdcf\ufe70-\ufeff]")


class _Cnt:
    def __init__(self) -> None:
        self.pass_n = 0
        self.fail_n = 0

    def rec(self, ok: bool, title: str, detail: str = "") -> bool:
        print(f"[{'PASS' if ok else 'FAIL'}] {title}")
        for ln in str(detail).splitlines():
            print(f"       {ln}")
        if ok:
            self.pass_n += 1
        else:
            self.fail_n += 1
        return ok


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {path}: {(r.stderr or '')[:200]}")
    return float(json.loads(r.stdout)["format"]["duration"])


def ffprobe_tags(path: Path) -> dict[str, str]:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format_tags",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {path}: {(r.stderr or '')[:200]}")
    return dict(json.loads(r.stdout).get("format", {}).get("tags", {}) or {})


def frame_count(path: Path) -> int:
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"视频无法打开: {path}")
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    finally:
        cap.release()


def read_frames(path: Path, indices: list[int]) -> dict[int, np.ndarray]:
    """顺序解码取指定帧号（无 seek；与 m2.sample_band 同口径）。"""
    import cv2

    want = sorted(set(int(i) for i in indices))
    out: dict[int, np.ndarray] = {}
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"视频无法打开: {path}")
        idx = 0
        wi = 0
        while wi < len(want):
            if not cap.grab():
                break
            if idx == want[wi]:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                out[want[wi]] = frame
                wi += 1
            idx += 1
    finally:
        cap.release()
    missing = [i for i in want if i not in out]
    if missing:
        raise RuntimeError(f"{path.name} 缺帧 {missing[:5]}（共取 {idx} 帧）")
    return out


def frame_md5(frame: np.ndarray) -> str:
    return hashlib.md5(np.ascontiguousarray(frame).tobytes()).hexdigest()


def diff_stats(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """两帧（同尺寸 BGR）→ 灰阶差分统计：mean |Δ| / 墨迹占比(|Δ|>8) / 强差占比(>16)。"""
    g1 = a.mean(axis=2)
    g2 = b.mean(axis=2)
    d = np.abs(g1 - g2)
    n = d.size
    return {
        "mean_abs": round(float(d.mean()), 3),
        "ink_ratio": round(float((d > 8).sum()) / n, 5),
        "strong_ratio": round(float((d > 16).sum()) / n, 5),
    }


def ink_centroid_x(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    """差分墨迹（|Δ|>8）的水平质心（0=左缘，1=右缘）；墨迹过少返回 None。"""
    d = np.abs(a.mean(axis=2) - b.mean(axis=2))
    ys, xs = np.nonzero(d > 8)
    if xs.size < 50:
        return None
    return float(xs.mean()) / float(a.shape[1])


# ---------------------------------------------------------------------------
# 各断言项
# ---------------------------------------------------------------------------

def check_duration(cnt: _Cnt, final: Path, src: Path) -> None:
    try:
        d_fin, d_src = ffprobe_duration(final), ffprobe_duration(src)
        ratio = abs(d_fin - d_src) / d_src if d_src > 0 else 9e9
        ok = ratio <= THRESH["dur_ratio"]
        cnt.rec(ok, f"② 成片时长≈原片（±{THRESH['dur_ratio']:.0%}）",
                f"final={d_fin:.3f}s src={d_src:.3f}s |Δ|/src={ratio:.4f}")
    except Exception as exc:  # noqa: BLE001
        cnt.rec(False, "② 成片时长≈原片", f"执行异常: {exc}")


def check_subs(cnt: _Cnt, ws: Path, lang: str, final: Path, clean: Path,
               band: tuple[int, int], utt_mids: list[float], fps: float,
               ocr: Any) -> None:
    """③ 字幕区目标语渲染（OCR 无中文 + 目标语在位 + ar 右对齐渲染）。"""
    y0, y1 = band
    try:
        # ---- a) 重跑 OCR：中文字符命中 = 0 ----
        from pipeline.m2_ocr import SubtitleOcr, sample_band

        cjk_hits: list[str] = []
        n_ocr_text = 0
        for _t, band_bgr in sample_band(final, y0=y0, y1=y1, interval_s=0.5):
            dets = ocr.read_band(band_bgr)
            for d in dets:
                if d["conf"] >= 0.5 and d["text"].strip():
                    n_ocr_text += 1
                    if _CJK_RE.search(d["text"]):
                        cjk_hits.append(d["text"])
        ok = not cjk_hits
        cnt.rec(ok, "③a 字幕带重跑 OCR：中文字符命中=0",
                f"检出文本行 {n_ocr_text} 条，中文命中 {len(cjk_hits)}"
                + (f"：{cjk_hits[:5]}" if cjk_hits else "（擦除残留=0 且目标语字幕不含源语）"))

        # ---- b) en/es 目标语在位（OCR 非空）/ ar ASS+像素 ----
        if lang in ("en", "es"):
            ok = n_ocr_text >= 1
            cnt.rec(ok, f"③b 字幕带 OCR 目标语（{lang}）非空",
                    f"检出 {n_ocr_text} 行（cap-ocr zh 引擎读拉丁文，行数>0 即在位）")
        else:
            ass_ok, ass_detail = _check_ar_ass(ws, lang)
            cnt.rec(ass_ok, f"③b-ar ASS 右对齐样式与事件文本（{lang}）", ass_detail)

        # ---- c) 渲染像素在位 + 对齐质心 ----
        mids_f = [min(int(t * fps), frame_count(final) - 1) for t in utt_mids]
        fr_fin = read_frames(final, mids_f)
        fr_cln = read_frames(clean, mids_f)
        inks, cents = [], []
        for f in mids_f:
            st = diff_stats(fr_fin[f][y0:y1], fr_cln[f][y0:y1])
            inks.append(st["ink_ratio"])
            c = ink_centroid_x(fr_fin[f][y0:y1], fr_cln[f][y0:y1])
            if c is not None:
                cents.append(c)
        ink_ok = inks and min(inks) >= THRESH["ink_min_ratio"]
        cnt.rec(bool(ink_ok), "③c 字幕带渲染墨迹在位（vs 擦除基带差分）",
                f"句中帧墨迹占比 {inks}（阈值 ≥{THRESH['ink_min_ratio']}）")
        if lang == "ar":
            ok = bool(cents) and min(cents) > THRESH["ar_centroid_right"]
            cnt.rec(ok, "③d-ar RTL 渲染质心偏右",
                    f"各句中帧质心 {['%.2f' % c for c in cents]}（阈值 >{THRESH['ar_centroid_right']}）")
        else:
            ok = bool(cents) and max(cents) < THRESH["ltrl_centroid_left"]
            cnt.rec(ok, f"③d 左下对齐渲染质心偏左（{lang}）",
                    f"各句中帧质心 {['%.2f' % c for c in cents]}（阈值 <{THRESH['ltrl_centroid_left']}）")
    except Exception as exc:  # noqa: BLE001
        cnt.rec(False, "③ 字幕区目标语渲染", f"执行异常: {exc}")


def _check_ar_ass(ws: Path, lang: str) -> tuple[bool, str]:
    """ar ASS：Alignment=3（右对齐）、事件含阿语字母、文本与 C4 chosen 一致。"""
    from pipeline import contracts as C

    ass = ws / "10_subs" / f"tgt.{lang}.ass"
    if not ass.is_file():
        return False, f"ASS 不存在: {ass}"
    style_align: Optional[str] = None
    n_event, ar_chars = 0, 0
    ev_texts: list[str] = []
    for ln in ass.read_text(encoding="utf-8").splitlines():
        if ln.startswith("Style:") and style_align is None:
            parts = ln.split(",")  # ASS v4+ Style：Alignment 为第 19 域（索引 18）
            style_align = parts[18].strip() if len(parts) > 18 else None
        if ln.startswith("Dialogue:"):
            n_event += 1
            txt = ln.split(",", 9)[-1]
            ar_chars += len(_AR_RE.findall(txt))
            ev_texts.append(txt)
    if style_align is None:
        return False, "Style 行缺失/不可解析"
    if style_align != "3":
        return False, f"Alignment={style_align}（期望 3=右下，right-rtl）"
    if n_event == 0 or ar_chars == 0:
        return False, f"事件 {n_event} 条/阿语字符 {ar_chars}（期望非空阿语事件）"
    rows = C.load_jsonl(ws / "06_mt" / "translations.jsonl", C.TranslationTable).root
    chosen: set[str] = set()
    for t in rows:
        if t.tgt != lang or not t.candidates:
            continue
        idx = t.chosen if t.chosen is not None else 0
        if idx < len(t.candidates):
            chosen.add(t.candidates[idx].text.strip())
    matched = sum(1 for t in ev_texts if t.strip() in chosen)
    return (matched == n_event), (
        f"Alignment=3；事件 {n_event} 条、阿语字符 {ar_chars}；与 C4 chosen 一致 {matched}/{n_event}")


def check_labels(cnt: _Cnt, ws: Path, final: Path, clean: Path,
                 label_zone: tuple[int, int], fps: float, n_frames: int,
                 ocr: Any) -> None:
    """④ AI 标识在位：元数据（ffprobe==C7 implicit）+ 显式（片头 3s drawtext）。"""
    y0, y1 = label_zone
    try:
        labels_path = ws / "11_labels" / "labels.json"
        if not labels_path.is_file():
            cnt.rec(False, "④ AI 标识", f"C7 缺失: {labels_path}")
            return
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
        field = labels["implicit"]["metadata_field"]
        want = labels["implicit"]["value"]
        tags = ffprobe_tags(final)
        got = tags.get(field)
        cnt.rec(got == want, f"④a 元数据标识位 {field} 精确一致",
                f"成片 tag={got!r}（期望 {want!r}，来源 C7 labels.json）")

        # 显式标识只在片头 3s（enable lte(t,3)）：素材首句 3.2s 起、尾段 1.0s
        # 静默（见 e2e_smoke 素材布局），t_off 取片尾静默帧——保证不在任何口型窗/
        # 字幕窗内，差分只反映标识消失。
        f_on = min(int(1.0 * fps), n_frames - 1)
        f_off = max(0, n_frames - 3)
        fr_fin = read_frames(final, [f_on, f_off])
        fr_cln = read_frames(clean, [f_on, f_off])
        on = diff_stats(fr_fin[f_on][y0:y1], fr_cln[f_on][y0:y1])
        off = diff_stats(fr_fin[f_off][y0:y1], fr_cln[f_off][y0:y1])
        cnt.rec(on["ink_ratio"] >= THRESH["ink_min_ratio"],
                "④b 显式标识片头墨迹在位（t=1.0s 标识区）",
                f"墨迹占比 {on['ink_ratio']}（阈值 ≥{THRESH['ink_min_ratio']}）")
        cnt.rec(off["ink_ratio"] <= THRESH["label_gone_ink_ratio"],
                f"④c 显式标识仅片头 3s（片尾静默帧 {f_off} 标识区无墨迹）",
                f"墨迹占比 {off['ink_ratio']}（阈值 ≤{THRESH['label_gone_ink_ratio']}）")
        # 显式标识文本 OCR（信息性强化断言：含 "AI" 字样）
        zone = fr_fin[f_on][y0:y1]
        dets = ocr.read_band(zone)
        joined = "".join(d["text"] for d in dets)
        cnt.rec("AI" in joined.upper(), "④d 显式标识文本 OCR 命中 AI 字样",
                f"OCR 文本: {joined!r}（检出 {len(dets)} 段）")
    except Exception as exc:  # noqa: BLE001
        cnt.rec(False, "④ AI 标识在位", f"执行异常: {exc}")


def check_metrics(cnt: _Cnt, ws: Path, lang: str) -> None:
    """⑤ metrics 六项出数（e2e_smoke 每语种快照 metrics.<lang>.json）。"""
    try:
        p = ws / "12_out" / f"metrics.{lang}.json"
        if not p.is_file():
            cnt.rec(False, "⑤ metrics 六项出数", f"快照缺失: {p}")
            return
        m = json.loads(p.read_text(encoding="utf-8"))
        if int(m.get("n_metrics_total") or 0) != 6:
            cnt.rec(False, "⑤ metrics 六项出数", f"n_metrics_total={m.get('n_metrics_total')}（期望 6）")
            return
        missing = [k for k in _METRIC_KEYS
                   if m["metrics"].get(k, {}).get("status") != "ok"]
        vals = {k: m["metrics"].get(k, {}).get("value") for k in _METRIC_KEYS}
        cnt.rec(not missing and bool(m.get("all_measured")),
                "⑤ metrics 六项出数", f"缺失/未出数: {missing or '无'}；值: {vals}")
    except Exception as exc:  # noqa: BLE001
        cnt.rec(False, "⑤ metrics 六项出数", f"执行异常: {exc}")


def check_non_lip_frames(cnt: _Cnt, ws: Path, ep: str, lang: str,
                         final: Path, out12: Path, clean: Path, master: Path,
                         band: tuple[int, int], label_zone: tuple[int, int]) -> None:
    """⑥ 非口型帧不变（独立复核，不信任 m10 自带 verify）。"""
    y0b, y1b = band
    y0l, y1l = label_zone
    try:
        lip = ws / "09_lip" / "done" / f"{ep}.{lang}.lip.mp4"
        n_fin = frame_count(final)
        n_base = frame_count(master)
        cnt.rec(n_fin == n_base, "⑥a 帧数守恒（成片=母带帧数）",
                f"final={n_fin}fr master={n_base}fr")

        def _quiet_st(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
            """预期改动区之外（标识区下沿→字幕带上沿的整幅横带）差分。"""
            y_hi = min(y1l, y0b)
            return diff_stats(a[y_hi:y0b], b[y_hi:y0b])

        if lip.is_file():
            cover: list[list[int]] = []
            rep = ws / "09_lip" / f"lip_report.{lang}.json"
            if rep.is_file():
                r = json.loads(rep.read_text(encoding="utf-8"))
                cover = [list(i["frames"]) for i in r.get("items", [])
                         if i.get("status") == "done"]
            # 回贴基线 = 口型前的 12_out 成片快照（e2e_smoke 在 m10 前留存；
            # 缺快照回落当前 12_out 成片——封口后与其互为重封装，等价）。
            prelip = ws / "12_out" / f".prelip.{ep}.{lang}.mp4"
            base12 = prelip if prelip.is_file() else out12
            n = n_fin
            outside = [i for i in range(0, n, max(1, n // 10)) if i < n
                       and not any(a <= i < b for a, b in cover)]
            f12 = read_frames(base12, outside)
            flip = read_frames(lip, outside)
            bad = [(i, frame_md5(f12[i]), frame_md5(flip[i]))
                   for i in outside if not np.array_equal(f12[i], flip[i])]
            cnt.rec(not bad, f"⑥b 口型窗外帧逐字节不变（vs 口型前成片快照，{len(outside)} 帧抽样）",
                    (f"不一致帧: {bad[:3]}" if bad else
                     f"窗外 {len(outside)} 帧全部一致（口型窗 {cover}，基线={base12.name}）"))
        else:
            # 无口型成片：最终=12_out 成片；帧在预期改动区（字幕带∪标识区）外
            # 应与擦除基带一致（容差吸收两代 CRF18 压制噪声）。
            n = n_fin
            probes = [i for i in range(0, n, max(1, n // 8)) if i < n]
            fc = read_frames(clean, probes)
            ff = read_frames(final, probes)
            sts = [_quiet_st(ff[i], fc[i]) for i in probes]
            bad_mean = [s["mean_abs"] for s in sts if s["mean_abs"] > THRESH["quiet_mean_abs"]]
            bad_ink = [s["strong_ratio"] for s in sts if s["strong_ratio"] > THRESH["quiet_ink_ratio"]]
            cnt.rec(not bad_mean and not bad_ink,
                    f"⑥b 预期改动区之外帧与擦除基带一致（{len(probes)} 帧抽样，容差口径）",
                    f"mean|Δ| 范围 [{min(s['mean_abs'] for s in sts):.2f},"
                    f" {max(s['mean_abs'] for s in sts):.2f}]"
                    f"（阈值 ≤{THRESH['quiet_mean_abs']}）；"
                    f"强差占比范围 [{min(s['strong_ratio'] for s in sts):.4f},"
                    f" {max(s['strong_ratio'] for s in sts):.4f}]"
                    f"（阈值 ≤{THRESH['quiet_ink_ratio']}）")
    except Exception as exc:  # noqa: BLE001
        cnt.rec(False, "⑥ 非口型帧不变", f"执行异常: {exc}")


def check_dub_coverage(cnt: _Cnt, ws: Path, lang: str) -> None:
    """⑦ C2 非保留句窗内配音轨非静音（静音句窗占比 <2%）。"""
    try:
        import soundfile as sf

        from pipeline import contracts as C

        dubbed = ws / "08_mix" / f"dubbed.{lang}.wav"
        if not dubbed.is_file():
            cnt.rec(False, "⑦ C2 音轨配音铺满", f"配音轨缺失: {dubbed}")
            return
        utts = C.load_jsonl(ws / "04_dial" / "utterances.jsonl", C.UtteranceTable).root
        data, sr = sf.read(str(dubbed), dtype="float32")
        data = np.asarray(data).squeeze()
        total = silent = 0
        detail: list[str] = []
        for u in utts:
            plan = u.utt_id
            keep = False
            plan_path = ws / "07_synth" / f"synth_plan.{lang}.jsonl"
            if plan_path.is_file():
                for ln in plan_path.read_text(encoding="utf-8").splitlines():
                    if ln.strip():
                        row = json.loads(ln)
                        if row.get("utt_id") == u.utt_id:
                            keep = bool(row.get("keep_original"))
            if keep:
                continue
            a, b = int(u.start * sr), min(int(u.end * sr), len(data))
            if b <= a:
                continue
            total += 1
            seg = data[a:b]
            rms = float(np.sqrt((seg.astype(np.float64) ** 2).mean())) if seg.size else 0.0
            db = 20 * np.log10(max(rms, 1e-10))
            if db < THRESH["silence_rms_dbfs"]:
                silent += 1
                detail.append(f"{plan} {db:.1f}dBFS")
        frac = (silent / total) if total else 1.0
        cnt.rec(frac < THRESH["silence_frac_max"],
                "⑦ C2 音轨配音铺满（句窗非静音）",
                f"非保留句窗 {total} 个，静音 {silent} 个（占比 {frac:.2f} <"
                f"{THRESH['silence_frac_max']}）{('; 异常窗: ' + ', '.join(detail)) if detail else ''}")
    except Exception as exc:  # noqa: BLE001
        cnt.rec(False, "⑦ C2 音轨配音铺满", f"执行异常: {exc}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python tests/check_e2e.py",
        description="e2e 冒烟断言集（§7）：时长/字幕渲染/ar RTL/AI 标识/metrics/非口型帧/配音铺满")
    ap.add_argument("--ep", required=True, help="集 ID（如 e2e01）")
    ap.add_argument("--langs", default="en,es,ar", help="断言语种，逗号分隔")
    ap.add_argument("--jobs-dir", default=None, help="jobs 根目录（默认 configs）")
    ap.add_argument("--src", default=None, help="原片参考（默认 clips/<ep>_raw.mp4）")
    ap.add_argument("--ocr-interval", type=float, default=0.5,
                    help="字幕带 OCR 采样间隔秒（默认 0.5）")
    ns = ap.parse_args(argv)

    t0 = time.monotonic()
    langs = [x.strip() for x in ns.langs.split(",") if x.strip()]
    cfg = load_pipeline_config()
    jobs_root = Path(ns.jobs_dir) if ns.jobs_dir else Path(cfg["paths"]["jobs_dir"])
    ws = ep_dir(ns.ep, jobs_root)
    src = Path(ns.src) if ns.src else (
        Path(cfg["paths"]["clips_dir"]) / f"{ns.ep}_raw.mp4")
    if not src.is_file():
        print(f"FAIL 原片参考不存在: {src}")
        return 1

    band_cfg = cfg.get("erase_band") or {}
    band = (int(band_cfg.get("y0_px", 1440)), int(band_cfg.get("y1_px", 1780)))
    lz_cfg = cfg.get("label_zone") or {}
    label_zone = (int(lz_cfg.get("top_px", 60)),
                  int(lz_cfg.get("top_px", 60)) + int(lz_cfg.get("height_px", 120)))

    clean = ws / "01_media" / "video_1080x1920_25fps_clean.mp4"
    master = ws / "01_media" / "video_1080x1920_25fps.mp4"
    if not clean.is_file():
        print(f"FAIL 擦除基带不存在: {clean}（M11 未跑？）")
        return 1

    from pipeline.m2_ocr import SubtitleOcr  # 懒初始化（torch 先行由 ocr_wrap 保证）

    ocr = SubtitleOcr()

    print(f"== check_e2e: ep={ns.ep} langs={','.join(langs)} src={src.name} ==")
    all_fail = 0
    for lang in langs:
        print(f"-- 语种 {lang} " + "-" * 56)
        cnt = _Cnt()
        out12 = ws / "12_out" / f"{ns.ep}.{lang}.mp4"
        lip = ws / "09_lip" / "done" / f"{ns.ep}.{lang}.lip.mp4"
        # 最终成片 = 12_out 槽位（规划 §3 交付位；e2e_smoke 在口型后把带标识的
        # 成片封回该槽位——m10 回贴产物不落标识位，故不以它为交付）。
        final = out12
        cnt.rec(out12.is_file(), f"① 成片存在（12_out/{ns.ep}.{lang}.mp4）"
                + ("；含口型回贴（09_lip/done 已封入）" if lip.is_file() else ""),
                f"final={final}")

        # C2 句窗中点（渲染/铺满检查的抽样锚点）
        mids: list[float] = []
        fps = 25.0
        try:
            from pipeline import contracts as C

            utts = C.load_jsonl(ws / "04_dial" / "utterances.jsonl",
                                C.UtteranceTable).root
            mids = [round((u.start + u.end) / 2, 3) for u in utts]
        except Exception as exc:  # noqa: BLE001
            cnt.rec(False, "①b C2 可读", f"执行异常: {exc}")
        if master.is_file():
            import cv2

            cap = cv2.VideoCapture(str(master))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
            cap.release()

        check_duration(cnt, final, src)
        check_subs(cnt, ws, lang, final, clean, band, mids, fps, ocr)
        n_frames = frame_count(final)
        check_labels(cnt, ws, final, clean, label_zone, fps, n_frames, ocr)
        check_metrics(cnt, ws, lang)
        check_non_lip_frames(cnt, ws, ns.ep, lang, final, out12, clean,
                             master, band, label_zone)
        check_dub_coverage(cnt, ws, lang)
        all_fail += cnt.fail_n
        print(f"   （{lang}: {cnt.pass_n} PASS / {cnt.fail_n} FAIL）")

    wall = time.monotonic() - t0
    print(f"== check_e2e: {langs} 全语种 FAIL 合计 {all_fail}"
          f"（墙钟 {wall:.0f}s）==")
    return 1 if all_fail else 0


if __name__ == "__main__":
    sys.exit(main())
