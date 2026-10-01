"""M2 硬字幕 OCR + 校对 eval（规划 §4 M2；任务 T6 冻结口径）。

冻结 eval 命令::

    pytest tests/test_m2.py        # 入口 scripts/eval_m2.sh

§4 M2 原文通过线："自拍样片 OCR 文本与人工标注 20 条 CER ≤5%；字幕起止时间
误差 ≤0.3s（90% 命中）"。自拍样片（D1 素材）尚未拍摄 —— 按任务 T6 冻结的等价
口径执行：**ffmpeg drawtext 压中文字幕的合成视频**（压制时刻即人工标注：文本与
起止时间先验已知），断言抽取行语料级 CER ≤5%、起止时间误差 ≤0.3s（≥90% 行
命中）。自拍样片到位后按同口径换素材，通过线不变。

覆盖面：
  ① 冻结 eval（drawtext 合成视频 → 采样 OCR → 字幕行 vs 人工标注）；
  ② C2 出口（utterances.jsonl 契约校验 + utt_id 稳定公式 + ocr 事实回填）；
  ③ ASR 缺席退化为纯 OCR（agree=False 语义）；
  ④ OCR↔ASR 投票/合并纯函数（含重切句窗、字级时间戳夹取、贪心 1:1）；
  ⑤ CLI 真实子进程（python -m pipeline.m2_ocr）与错误路径。

合成素材刻意用 0x303030 深灰底 + 白字黑边（短剧硬字幕样式，字号 62 落在
erase_band 1440–1780 内），行间留 ≥0.4s 空档，验证"字幕变化处合并去重"。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline import contracts as C
from pipeline.config import REPO_ROOT
from pipeline.m1_ingest import FFMPEG, main as m1_main
from pipeline.m2_ocr import (
    OcrFrameRecord,
    OcrLineRecord,
    cer,
    edit_distance,
    main as m2_main,
    merge_frames_to_lines,
    merge_ocr_asr,
    normalize_text,
    overlap_ratio,
    vote_text,
)

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

#: 主素材：5 行台词（起, 止, 文本）——全部落在字幕带内，行间 ≥0.4s 空档
GT_LINES: list[tuple[float, float, str]] = [
    (0.8, 2.6, "你到底想怎么样？把话说清楚。"),
    (3.0, 4.8, "三年了，哪一样不是我做的？"),
    (5.2, 7.0, "那你就可以这样对我吗！"),
    (7.4, 9.2, "我以为你至少会信我。"),
    (9.6, 11.4, "海南孤岛，也有明月。"),
]
MAIN_DUR = 12.0
#: CLI 子进程素材：2 行短样（独立 jobs，避免叠加主素材 OCR 时长）
CLI_LINES: list[tuple[float, float, str]] = [
    (0.6, 2.0, "程氏的项目不能倒。"),
    (2.6, 4.4, "预算超了，档期不能动。"),
]
CLI_DUR = 5.0

EP = "ep01"
BAND = (1440, 1780)          # 与 configs/pipeline.yaml erase_band 同源
TEXT_Y = 1560
FONTSIZE = 62
TIME_TOL_S = 0.3             # §4 M2 冻结：起止时间误差 ≤0.3s
HIT_MIN = 0.9                # §4 M2 冻结：90% 命中
CORPUS_CER_MAX = 0.05        # §4 M2 冻结：语料级 CER ≤5%


pytestmark = pytest.mark.skipif(FONT is None, reason=f"无中文字体（{_FONT_CANDIDATES}）")


def _burn_subtitles(dst: Path, gt: list[tuple[float, float, str]], dur: float) -> Path:
    """drawtext 压中文字幕（textfile 写 UTF-8，无 BOM —— T6 实测渲染口径）。"""
    work = dst.parent
    work.mkdir(parents=True, exist_ok=True)
    font_esc = FONT.replace(":", "\\:")  # 过滤图内盘符冒号转义（规划 §8 同款写法）
    chain = []
    for i, (a, b, _text) in enumerate(gt):
        tf = work / f"sub{i}.txt"
        tf.write_text(_text, encoding="utf-8")
        chain.append(
            f"drawtext=fontfile='{font_esc}':textfile=sub{i}.txt:"
            f"fontcolor=white:borderw=3:bordercolor=black@0.85:fontsize={FONTSIZE}:"
            f"x=(w-text_w)/2:y={TEXT_Y}:enable='between(t,{a},{b})'"
        )
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"color=c=0x303030:size=1080x1920:rate=25:duration={dur}",
           "-vf", ",".join(chain), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)]
    # textfile 用相对文件名 → ffmpeg 必须 cwd 到字幕文本所在目录（避免盘符冒号转义）
    subprocess.run(cmd, check=True, timeout=300, capture_output=True, text=True, cwd=str(work))
    assert dst.is_file() and dst.stat().st_size > 0
    return dst


def _load_jsonl_models(path: Path, cls):
    return C.load_jsonl(path, cls)


def _match_line(gt: tuple[float, float, str], lines: list[OcrLineRecord]):
    """GT 行 → 重叠率最大的抽取行（无重叠返回 None）。"""
    best, best_r = None, 0.0
    for ln in lines:
        r = overlap_ratio((gt[0], gt[1]), (ln.start, ln.end))
        if r > best_r:
            best, best_r = ln, r
    return best


# ---------------------------------------------------------------------------
# fixtures（module 级：一次合成 + 一次 M1 + 一次全量 M2）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def zh_clip(tmp_path_factory) -> Path:
    return _burn_subtitles(tmp_path_factory.mktemp("m2_clip") / "ep01_raw.mp4",
                           GT_LINES, MAIN_DUR)


@pytest.fixture(scope="module")
def jobs(tmp_path_factory, zh_clip) -> Path:
    d = tmp_path_factory.mktemp("m2_jobs")
    assert m1_main(["--ep", EP, "--in", str(zh_clip), "--jobs-dir", str(d)]) == 0
    return d


@pytest.fixture(scope="module")
def summary(jobs) -> dict:
    """对主素材跑一次 M2（纯 OCR：04_dial 尚无 ASR 产物）。"""
    rc = m2_main(["--ep", EP, "--jobs-dir", str(jobs)])
    assert rc == 0, "m2_ocr 主流程返回非 0"
    lines = _load_jsonl_models(jobs / EP / "03_ocr" / "ocr_merged.jsonl", OcrLineRecord)
    return {"jobs": jobs, "lines": lines}


# ---------------------------------------------------------------------------
# ① 冻结 eval：抽取行 vs 人工标注（CER ≤5%、时间误差 ≤0.3s 且 ≥90% 命中）
# ---------------------------------------------------------------------------

def test_ocr_lines_vs_ground_truth(summary):
    lines = summary["lines"]
    assert lines, "ocr_merged.jsonl 无字幕行"
    assert len(lines) <= len(GT_LINES), f"抽取行多于标注（存在幻影行）: {len(lines)}"

    hits, per_line = 0, []
    total_ref, total_err = 0, 0
    for gt in GT_LINES:
        ln = _match_line(gt, lines)
        assert ln is not None, f"标注行无任何重叠抽取: {gt}"
        e = edit_distance(normalize_text(gt[2]), normalize_text(ln.text))
        total_ref += len(normalize_text(gt[2]))
        total_err += e
        per_line.append(f"{gt[2][:8]}… cer={e}/{len(normalize_text(gt[2]))}")
        ds, de = abs(ln.start - gt[0]), abs(ln.end - gt[1])
        if ds <= TIME_TOL_S and de <= TIME_TOL_S:
            hits += 1
    corpus_cer = total_err / max(total_ref, 1)
    assert corpus_cer <= CORPUS_CER_MAX, (
        f"语料级 CER {corpus_cer:.4f} > {CORPUS_CER_MAX}（{'; '.join(per_line)}）")
    assert hits / len(GT_LINES) >= HIT_MIN, (
        f"时间命中 {hits}/{len(GT_LINES)} < {HIT_MIN}（{'; '.join(per_line)}）")


def test_merged_lines_sane(summary):
    lines = summary["lines"]
    prev_end = -1.0
    for ln in lines:
        assert 0.0 <= ln.start < ln.end <= MAIN_DUR + 0.5, ln
        assert 0.0 < ln.conf <= 1.0 and ln.frames >= 1, ln
        assert (ln.x0, ln.y0) < (ln.x1, ln.y1) and ln.y0 >= BAND[0] - 5, ln  # 带内 bbox
        assert ln.start >= prev_end - 1e-6, f"字幕行未按时间排序: {ln} after {prev_end}"
        prev_end = ln.end


# ---------------------------------------------------------------------------
# ② C2 出口：契约校验 + utt_id 稳定公式 + ocr 事实
# ---------------------------------------------------------------------------

def test_utterances_contract_c2(summary):
    utt_path = summary["jobs"] / EP / "04_dial" / "utterances.jsonl"
    rows = C.load_jsonl(utt_path, C.UtteranceTable).root  # 容器强校验（唯一性/时间窗）
    assert len(rows) == len(summary["lines"]), "纯 OCR 模式下 C2 行数应等于字幕行数"
    for u in rows:
        assert u.utt_id == C.make_utt_id(EP, u.start), u
        assert u.shot_id == "s0000" and u.lang == "zh" and u.text, u
        assert u.ocr is not None and u.ocr.text, u
        assert u.ocr.agree is False, "ASR 缺席时 agree 不得为 True（未经确认）"
    # 每条标注行都有时间窗对齐的 C2 行，且文本 = OCR 文本（合成字幕置信 ≥0.9）
    for gt in GT_LINES:
        hit = [u for u in rows
               if abs(u.start - gt[0]) <= TIME_TOL_S and abs(u.end - gt[1]) <= TIME_TOL_S]
        assert hit, f"标注行无对齐 C2 行: {gt}"
        u = hit[0]
        assert normalize_text(u.text) == normalize_text(gt[2]), (u.text, gt[2])
        assert u.ocr.conf >= 0.9, u


# ---------------------------------------------------------------------------
# ③ OCR↔ASR 投票 / 合并（纯函数，不触引擎）
# ---------------------------------------------------------------------------

def test_vote_text():
    assert vote_text("你好", 0.95, "你好") == ("你好", "ocr", True)
    assert vote_text("你好", 0.95, "再见") == ("你好", "ocr", False)
    assert vote_text("你好", 0.70, "再见了你") == ("再见了你", "asr", False)
    assert vote_text("你好", 0.70, "你好")[2] is True
    # ASR 缺席 → 兜底 OCR，agree=False
    chosen, src, agree = vote_text("你好", 0.70, "")
    assert (chosen, src, agree) == ("你好", "ocr", False)
    # 标点/空白不参与一致性
    assert vote_text("你，好！", 0.95, "你好")[2] is True


def test_overlap_ratio():
    assert abs(overlap_ratio((1.0, 3.0), (2.0, 4.0)) - 0.5) < 1e-9
    assert abs(overlap_ratio((1.0, 3.0), (1.0, 3.0)) - 1.0) < 1e-9
    assert overlap_ratio((1.0, 3.0), (3.0, 5.0)) == 0.0
    assert overlap_ratio((1.0, 1.0), (1.0, 3.0)) == 0.0  # 零长行


def test_cer_helpers():
    assert edit_distance("abc", "abc") == 0
    assert edit_distance("abc", "abd") == 1
    assert edit_distance("", "xy") == 2
    assert cer("你到底想怎么样？把话说清楚。", "你到底想怎么样把话说清楚") == 0.0
    assert cer("abcd", "abxy") == 0.5
    assert cer("", "") == 0.0 and cer("", "x") == 1.0


def test_merge_frames_to_lines():
    fr = lambda t, text, conf=0.95: OcrFrameRecord(t=t, text=text, conf=conf,
                                                   boxes=[[100, 1500, 500, 1580]])
    # 同文连帧并一行 + 单帧抖动桥接（2.2 丢帧不拆行）
    frames = [fr(1.0, "甲"), fr(1.2, "甲"), fr(1.4, "甲"),
              fr(1.6, "乙"), fr(1.8, "乙"),
              fr(2.0, "丙"), fr(2.4, "丙")]
    lines = merge_frames_to_lines(frames, interval_s=0.2, lang="zh", video_dur=3.0)
    assert [(round(l.start, 2), round(l.end, 2), l.text) for l in lines] == [
        (0.9, 1.5, "甲"), (1.5, 1.9, "乙"), (1.9, 2.5, "丙")]
    assert lines[2].frames == 2  # 断裂帧不计入 frames
    assert merge_frames_to_lines([], interval_s=0.2) == []
    # 超 2 步断裂不桥接 → 拆两行
    lines2 = merge_frames_to_lines([fr(1.0, "甲"), fr(1.8, "甲")], interval_s=0.2)
    assert len(lines2) == 2


def test_merge_ocr_asr_paths():
    """§4 M2 投票口径全分支 + B1 规则 8① 重切句窗。"""
    line_hi_same = OcrLineRecord(start=1.0, end=3.0, text="你到底想怎么样", conf=0.95, frames=5)
    line_hi_diff = OcrLineRecord(start=1.0, end=3.0, text="你到底想怎么样吗", conf=0.95, frames=5)
    line_lo = OcrLineRecord(start=1.0, end=3.0, text="你到底想怎么样吗", conf=0.80, frames=5)
    asr_u = C.Utterance(
        utt_id="epX-u00001100", shot_id="s0000", start=1.1, end=3.2, lang="zh",
        text="你到底想怎么样",
        words=[C.Word(w="你", s=1.2, e=1.4), C.Word(w="好", s=2.0, e=2.2)],
        emo=C.EmoTag(label="angry", score=0.8))

    # conf≥0.9 且一致 → OCR 文本 + agree=True；句窗重切 + 字夹取 + 其余字段保留
    rows = merge_ocr_asr("epX", [line_hi_same], [asr_u])
    assert rows[0].text == "你到底想怎么样" and rows[0].ocr.agree is True
    assert (rows[0].start, rows[0].end) == (1.0, 3.0)
    assert [w.w for w in rows[0].words] == ["你", "好"]
    assert rows[0].emo is not None and rows[0].utt_id == "epX-u00001100"
    C.UtteranceTable.model_validate(rows)

    # conf≥0.9 不一致 → OCR 为准 + agree=False
    rows = merge_ocr_asr("epX", [line_hi_diff], [asr_u])
    assert rows[0].text == "你到底想怎么样吗" and rows[0].ocr.agree is False

    # conf<0.9 → 以 ASR 为准
    rows = merge_ocr_asr("epX", [line_lo], [asr_u])
    assert rows[0].text == "你到底想怎么样" and rows[0].ocr.agree is False

    # ASR 缺席 → 纯 OCR 行（utt_id 稳定公式、agree=False）
    rows = merge_ocr_asr("epX", [line_hi_same], [])
    assert len(rows) == 1 and rows[0].utt_id == C.make_utt_id("epX", 1.0)
    assert rows[0].ocr.agree is False and rows[0].words == []

    # 一行横跨两句、对任单句重叠率 <60% → 三方共存（已知边界，句级去重归后续批次）
    u1 = C.Utterance(utt_id="a", shot_id="s0000", start=1.0, end=1.5, lang="zh", text="甲")
    u2 = C.Utterance(utt_id="b", shot_id="s0000", start=2.0, end=3.0, lang="zh", text="乙")
    rows = merge_ocr_asr("epX", [OcrLineRecord(start=1.0, end=3.0, text="甲乙",
                                               conf=0.5, frames=5)], [u1, u2])
    assert len(rows) == 3
    assert any(r.utt_id == "a" and r.ocr is None and r.text == "甲" for r in rows)
    assert any(r.utt_id == "b" and r.ocr is None and r.text == "乙" for r in rows)
    assert any(r.text == "甲乙" and r.ocr is not None for r in rows)
    C.UtteranceTable.model_validate(rows)

    # 强重叠 → 贪心命中
    u3 = C.Utterance(utt_id="c", shot_id="s0000", start=1.2, end=2.9, lang="zh", text="丙",
                     words=[C.Word(w="丙", s=1.5, e=1.8)])
    rows = merge_ocr_asr("epX", [OcrLineRecord(start=1.0, end=3.0, text="丁",
                                               conf=0.95, frames=5)], [u3])
    assert len(rows) == 1 and rows[0].utt_id == "c" and rows[0].text == "丁"
    assert [w.w for w in rows[0].words] == ["丙"]  # 字窗 (1.5,1.8) 落在新窗内保留


def test_merge_asr_wins_when_low_conf_on_fixture(summary):
    """用真实抽取行验证投票：低置信副本 → ASR 文本胜出。"""
    lines = summary["lines"]
    assert lines, "无真实抽取行"
    gt = GT_LINES[0]
    ln = _match_line(gt, lines)
    asr_u = C.Utterance(
        utt_id=C.make_utt_id(EP, ln.start + 0.05), shot_id="s0000",
        start=ln.start + 0.05, end=ln.end, lang="zh", text="这是语音识别的转写文本")
    low = ln.model_copy(update={"conf": 0.5, "start": ln.start + 0.05})
    rows = merge_ocr_asr(EP, [low], [asr_u])
    assert rows[0].text == "这是语音识别的转写文本"  # conf<0.9 → ASR 为准
    assert rows[0].ocr.conf == 0.5 and rows[0].ocr.agree is False
    C.UtteranceTable.model_validate(rows)


# ---------------------------------------------------------------------------
# ④ CLI（真实子进程）与错误路径
# ---------------------------------------------------------------------------

def test_cli_subprocess(tmp_path):
    """§4 M2 CLI 冻结形态 python -m pipeline.m2_ocr --ep … 经真实子进程验证。"""
    clip = _burn_subtitles(tmp_path / "cli_raw.mp4", CLI_LINES, CLI_DUR)
    jd = tmp_path / "cli_jobs"
    assert m1_main(["--ep", "epcli", "--in", str(clip), "--jobs-dir", str(jd)]) == 0
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(REPO_ROOT)}
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.m2_ocr", "--ep", "epcli",
         "--jobs-dir", str(jd)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600, env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "OK m2_ocr ep=epcli" in r.stdout
    merged = jd / "epcli" / "03_ocr" / "ocr_merged.jsonl"
    assert merged.is_file() and (jd / "epcli" / "03_ocr" / "ocr_raw.jsonl").is_file()
    lines = _load_jsonl_models(merged, OcrLineRecord)
    assert len(lines) == len(CLI_LINES)
    hits = sum(1 for gt in CLI_LINES
               if (m := _match_line(gt, lines)) is not None
               and abs(m.start - gt[0]) <= TIME_TOL_S and abs(m.end - gt[1]) <= TIME_TOL_S
               and cer(gt[2], m.text) <= CORPUS_CER_MAX)
    assert hits == len(CLI_LINES), f"CLI 素材命中 {hits}/{len(CLI_LINES)}"
    # C2 出口同样落盘且可过契约校验
    rows = C.load_jsonl(jd / "epcli" / "04_dial" / "utterances.jsonl", C.UtteranceTable).root
    assert len(rows) == len(CLI_LINES)
    assert all(u.ocr is not None and u.ocr.agree is False for u in rows)


def test_cli_missing_video(tmp_path, capsys):
    """M1 产物缺失 → 可读的 FAIL 提示 + 退出码 1。"""
    (tmp_path / "epX" / "01_media").mkdir(parents=True)
    rc = m2_main(["--ep", "epX", "--jobs-dir", str(tmp_path)])
    assert rc == 1
    assert "FAIL m2_ocr" in capsys.readouterr().out


def test_raw_product_shape(summary):
    raw_path = summary["jobs"] / EP / "03_ocr" / "ocr_raw.jsonl"
    rows = _load_jsonl_models(raw_path, OcrFrameRecord)
    assert rows, "ocr_raw.jsonl 不应有非空帧之外的空文件语义问题"
    for r in rows:
        assert 0.0 <= r.t <= MAIN_DUR and r.text and 0.0 < r.conf <= 1.0
        assert all(len(b) == 4 and b[1] >= BAND[0] - 5 and b[3] <= BAND[1] + 5
                   for b in r.boxes)
    assert json.loads((summary["jobs"] / EP / "01_media" / "probe.json")
                      .read_text(encoding="utf-8"))["ep"] == EP
