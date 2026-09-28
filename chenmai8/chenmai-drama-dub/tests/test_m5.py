"""M5 镜头切分 + 说话人区分 + 正脸近景判定 eval（规划 §4 M5；任务 T7 自验收口径）。

冻结 eval 命令::

    pytest tests/test_m5.py

素材与真值（任务 T7 自验收）：ffmpeg 合成的**双人轮替对话**样本 ——
  - 音频：Windows SAPI 双声库（zh-CN 女声 / en-US 女声，本机实测仅此两库）
    各 4 句交替摆放（真值区间=摆放已知）；16k 单声道 = 04_dial/vocals.wav 口径；
  - 视频：540x960@25fps，A 句 = 青底 + 公版人像（tests/fixtures/portrait_pd.jpg，
    马克·吐温坐像，摄影 A.F. Bradley，公有领域/Wikimedia Commons，不入上游任何
    名录）＝人脸 + 正脸近景镜头；B 句 = 紫底 + 游动方块（无人脸）＝负例镜头；
    镜头切分真值 = 轮替边界。
断言（T7 自验收原文「说话人分段与真值一致率达标、镜头表含正脸判定」，全部真实执行）：
  ① diar.jsonl（C2-pre 段级 schema 强校验）：聚类说话人数 == 2、按时间最优映射后
    分段一致率 ≥ 0.85（≈ DER ≤ 15%，规划 §4 M5 冻结线口径）；
  ② C1 shots.json 强校验：切分召回 ≥ 0.8（±0.4s 容差）；
  ③ 02_shots/frontal_closeups.json（正脸近景镜头表）：每镜头含正脸判定字段；
    人像镜头 frontal=true/faces≥1，无人脸镜头 frontal=false —— 与合成真值一致率
    100%（§4 M5「face 标记与人工逐镜标注一致率 ≥80%」的合成版）；
  ④ C2 回填（utt_id 原子替换）：speaker 非空率 100%、人像句 face.frontal/closeup
    命中 lip 分流规则（C6 lip_eligible）、镜头 shot_id 回填非占位；
  ⑤ 纯函数：正脸/近景判定与头部姿态分解（合成数值双向验证）；
  ⑥ fbank 数值一致性：对拍 fixtures/fbank_ref.npy（GPU 机 torchaudio 参照实现，
    见模型卡 runtime_notes；参照文件缺失时 skip —— 本条不属冻结验收线）；
  ⑦ voicebank 子命令：登记/列表/绑定 → voices.yaml + C3 characters.json
    （CastBook 强校验）+ speaker_map.json + CLI 子进程。

环境依赖：ffmpeg/ffprobe（PATH）、双 SAPI 声库、三组件权重
（models/voxdia|shot-cut|facemesh，不入公开仓；缺失时对应用例 skip 并给下载提示）。
依赖注意：torch 须先于 paddle（仓库硬约束）——本文件只经 pipeline 延迟导入 torch，
套件内无 paddle 用例，次序天然满足。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from pipeline.config import REPO_ROOT, load_pipeline_config
from pipeline.contracts import (
    CastBook,
    DiarTable,
    ShotSheet,
    UtteranceTable,
    load_jsonl,
    load_model,
    lip_eligible,
    make_utt_id,
    upsert_jsonl,
)
from pipeline.m1_ingest import FFMPEG, ffprobe_json
from pipeline.m5_diar import (
    DiarError,
    build_face_fact,
    cluster_speakers,
    decide_closeup,
    decide_frontal,
    energy_vad_windows,
    estimate_head_pose,
    main as m5_main,
    voice_bind,
    voice_list,
    voice_register,
)

pytestmark = pytest.mark.skipif(
    shutil.which(FFMPEG) is None,
    reason="ffmpeg 不在 PATH（M5 合成素材硬依赖）",
)

EPS = 0.4            # ② 切分时间容差
CUT_RECALL_MIN = 0.8   # ② 冻结线
AGREE_MIN = 0.85     # ① 冻结线（≈ DER ≤ 15%）
MAX_SPEAKERS = 3     # ① 说话人数上限 = 合成角色数 2 + 1（plan §4 M5 ②）

ZH_SENTENCES = [
    "你到底想怎么样？把话说清楚。",
    "三年了，这个项目哪一样不是我亲手做起来的？",
    "那你就可以这样对我吗！",
    "我以为你至少会信我说的话。",
]
EN_SENTENCES = [
    "The budget is over and the schedule cannot move at all.",
    "The client arrives tomorrow morning for the final review.",
    "We have to ship this feature before the deadline.",
    "Please trust me on this decision, it will work out.",
]
GAP_S = 0.6          # 轮替间隙（保证能量 VAD 可分）
LEAD_S = 1.0         # 首句前置静音

FACE_W = 520         # 人像贴图宽（face 高 ≈ 0.27 画幅 → closeup 命中 1/4 线）
FRAME_W, FRAME_H, FPS = 540, 960, 25
COLOR_A = (168, 128, 64)    # 青底（BGR）
COLOR_B = (112, 76, 112)    # 紫底（BGR）


# ---------------------------------------------------------------------------
# 合成素材
# ---------------------------------------------------------------------------

def _sapi_voices() -> dict[str, str]:
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices()|ForEach-Object{"
        "$_.VoiceInfo.Name+'|'+$_.VoiceInfo.Culture.Name}"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                         capture_output=True, text=True, timeout=60).stdout
    voices: dict[str, str] = {}
    for line in out.splitlines():
        name, _, culture = line.strip().partition("|")
        if not name:
            continue
        lang = culture.split("-")[0].lower()
        voices.setdefault(lang, name)
    return voices


def _sapi_sentence(dst: Path, voice: str, text: str) -> Path:
    raw = dst.with_name(dst.stem + "_raw.wav")
    ps = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');"
        "$s.SetOutputToWaveFile('" + str(raw).replace("\\", "/") + "');"
        f"$s.Speak('{text}');"
        "$s.Dispose()"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-500:]
    rr = subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(raw),
                         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
                        capture_output=True, text=True, timeout=120)
    assert rr.returncode == 0, rr.stderr[-500:]
    raw.unlink()
    assert dst.is_file() and dst.stat().st_size > 1000
    return dst


def _dur(path: Path) -> float:
    return float(ffprobe_json(path)["format"]["duration"])


def _build_turns(work: Path) -> tuple[list[dict], Path]:
    """8 句轮替 → (turns 真值, 16k 单声道 vocals wav)。"""
    voices = _sapi_voices()
    if "zh" not in voices or "en" not in voices:
        pytest.skip(f"本机 SAPI 声库不足两名（需 zh+en），实得: {voices}")
    spk_files: dict[str, list[Path]] = {"spkA": [], "spkB": []}
    for i, t in enumerate(ZH_SENTENCES):
        spk_files["spkA"].append(_sapi_sentence(work / f"a{i}.wav", voices["zh"], t))
    for i, t in enumerate(EN_SENTENCES):
        spk_files["spkB"].append(_sapi_sentence(work / f"b{i}.wav", voices["en"], t))

    turns, inputs, starts_ms = [], [], []
    t = LEAD_S
    for k in range(8):
        spk = "spkA" if k % 2 == 0 else "spkB"
        src = spk_files[spk][k // 2]
        d = _dur(src)
        turns.append({"start": round(t, 3), "end": round(t + d, 3),
                      "spk": spk, "src": str(src)})
        inputs.append(src)
        starts_ms.append(int(t * 1000))
        t += d + GAP_S

    n = len(inputs)
    argv: list[str] = [FFMPEG, "-y", "-loglevel", "error"]
    for p in inputs:
        argv += ["-i", str(p)]
    fc = "".join(f"[{i}:a]adelay={ms}:all=1[a{i}];" for i, ms in enumerate(starts_ms))
    fc += "".join(f"[a{i}]" for i in range(n))
    fc += f"amix=inputs={n}:duration=longest:normalize=0"
    voc = work / "vocals.wav"
    argv += ["-filter_complex", fc, "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", str(voc)]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-600:]
    return turns, voc


def _imread_unicode(path: Path) -> "np.ndarray | None":
    """cv2.imread 在 Windows 不支持非 ASCII 路径（仓库路径含中文，T7 实测），
    改 np.fromfile + imdecode。"""
    import cv2

    if not path.is_file():
        return None
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def _render_video(work: Path, turns: list[dict], portrait: Path) -> tuple[Path, float]:
    """cv2 逐帧合成 → ffmpeg rawvideo 管道压制 540x960@25fps 无声视频。"""
    import cv2

    face = _imread_unicode(portrait)
    assert face is not None, "人像 fixture 缺失"
    fh = int(FACE_W * face.shape[0] / face.shape[1])
    face = cv2.resize(face, (FACE_W, fh), interpolation=cv2.INTER_AREA)

    total = turns[-1]["end"] + 0.8
    n_frames = int(round(total * FPS))
    vid = work / "sample_video.mp4"

    def speaker_at(t: float) -> str | None:
        """帧所属说话人段：句内=该句；句间=延续前句背景（使视觉切换点恰好
        落在轮替起点，镜头真值=轮次起点）；首句前导静音=无人（B 底）。"""
        hit = next((x for x in turns if x["start"] <= t < x["end"]), None)
        if hit:
            return hit["spk"]
        prev = [x for x in turns if x["end"] <= t]
        return (prev[-1]["spk"] if prev else None)

    proc = subprocess.Popen(
        [FFMPEG, "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{FRAME_W}x{FRAME_H}",
         "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", str(vid)],
        stdin=subprocess.PIPE)
    rng = np.random.default_rng(0)
    try:
        for f in range(n_frames):
            t = f / FPS
            spk = speaker_at(t)
            is_a = spk == "spkA"
            frame = np.full((FRAME_H, FRAME_W, 3), COLOR_A if is_a else COLOR_B,
                            dtype=np.uint8)
            # 游动指示物（帧间差异，避免静帧退化）
            cx = int(40 + (FRAME_W - 80) * (0.5 + 0.5 * np.sin(2 * np.pi * t / 3.0)))
            cy = 60 + int(30 * rng.random())
            frame[cy:cy + 22, cx:cx + 22] = 255
            if is_a:
                bob = int(4 * np.sin(2 * np.pi * t / 2.0))
                y0 = (FRAME_H - fh) // 2 + bob
                frame[y0:y0 + fh, (FRAME_W - FACE_W) // 2:(FRAME_W + FACE_W) // 2] = face
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait(timeout=120)
    assert proc.returncode == 0, "视频压制失败"
    return vid, total


def _jobs_with_sample(tmp: Path, turns: list[dict], voc: Path, vid: Path) -> Path:
    """把成品样本摆进 jobs/epM5/（M1/M4 产出口径），并造 M4 式 utterances 空表。"""
    from pipeline import contracts as C

    media = tmp / "epM5" / "01_media"
    dial = tmp / "epM5" / "04_dial"
    media.mkdir(parents=True)
    dial.mkdir(parents=True)
    shutil.copy2(voc, dial / "vocals.wav")
    shutil.copy2(vid, media / "video_540x960_25fps.mp4")
    # M4 等价预分段：utterances（句窗=真值轮次，speaker/face 留空待 M5 回填）
    utts = [C.Utterance(utt_id=make_utt_id("epM5", t["start"]), shot_id="s0000",
                        start=t["start"], end=t["end"], lang="zh", speaker=None,
                        char_id=None, text="", words=[])
            for t in turns]
    upsert_jsonl(dial / "utterances.jsonl", utts, container=C.UtteranceTable)
    (tmp / "epM5" / "truth.json").write_text(
        json.dumps({"turns": [{k: v for k, v in t.items() if k != "src"}
                              for t in turns]}, ensure_ascii=False), encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _weights_ready(component: str) -> Path:
    models = REPO_ROOT.parent / "models" / component
    marks = {"voxdia": "campplus_cn_common.bin",
             "shot-cut": "scdet-pytorch-weights.pth",
             "facemesh": "face_landmarker.task"}
    p = models / marks[component]
    if not p.is_file():
        pytest.skip(f"{component} 权重未就位: {p}（见 configs/models.yaml {component} 条目）")
    return p


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    """双人轮替对话样本 + 真值（模块级一次合成，全部用例复用）。"""
    _weights_ready("voxdia")
    _weights_ready("shot-cut")
    _weights_ready("facemesh")
    work = tmp_path_factory.mktemp("m5_sample")
    turns, voc = _build_turns(work)
    portrait = REPO_ROOT / "tests" / "fixtures" / "portrait_pd.jpg"
    vid, total = _render_video(work, turns, portrait)
    jobs = _jobs_with_sample(tmp_path_factory.mktemp("m5_jobs"), turns, voc, vid)
    return {"turns": turns, "jobs": jobs, "vid": vid, "voc": voc, "total": total}


@pytest.fixture(scope="module")
def report(sample):
    """M5 全流程跑一遍（CLI 形态 in-process），全部断言复用其产物。"""
    rc = m5_main(["--ep", "epM5", "--jobs-dir", str(sample["jobs"]),
                  "--video", str(sample["vid"]),
                  "--max-speakers", str(MAX_SPEAKERS)])
    assert rc == 0, "m5_diar 主流程返回非 0"
    return json.loads((sample["jobs"] / "epM5" / "04_dial" / "diar_report.json")
                      .read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 冻结 eval（任务 T7 自验收 ①②③④）
# ---------------------------------------------------------------------------

def _label_agreement(segments: list[dict], turns: list[dict]) -> tuple[float, int, int]:
    """diar 段（中点落轮次）× 真值说话人 → 最优映射后的一致率（时长加权）。"""
    truth_speakers = sorted({t["spk"] for t in turns})
    rows = []
    for s in segments:
        mid = (float(s["start"]) + float(s["end"])) / 2.0
        hit = next((t for t in turns if t["start"] <= mid < t["end"]), None)
        if hit:
            rows.append((s["speaker"], hit["spk"], float(s["end"]) - float(s["start"])))
    import itertools

    best_acc, best_map = -1.0, {}
    pred_labels = sorted({r[0] for r in rows})
    for perm in itertools.permutations(truth_speakers, len(pred_labels)):
        mapping = dict(zip(pred_labels, perm))
        correct = sum(d for p, g, d in rows if mapping.get(p) == g)
        acc = correct / sum(d for _, _, d in rows)
        if acc > best_acc:
            best_acc, best_map = acc, mapping
    return best_acc, len(pred_labels), sum(r[2] for r in rows)


def test_diar_segmentation_agreement(sample, report):
    """① diar.jsonl：C2-pre 强校验 + 说话人数==2 + 一致率 ≥0.85（DER≤15% 冻结线）。"""
    diar = load_jsonl(sample["jobs"] / "epM5" / "04_dial" / "diar.jsonl", DiarTable)
    segments = [r.model_dump() for r in diar.root]
    assert len(segments) >= 8, f"分段过少: {len(segments)}"
    assert all(s["speaker"] for s in segments), "存在空 speaker（契约要求 unknown 或标签）"
    acc, n_pred, total_s = _label_agreement(segments, sample["turns"])
    print(f"\n[diar 实测] 一致率={acc:.3f}（冻结线 ≥{AGREE_MIN}）pred_speakers={n_pred} "
          f"speech={total_s:.1f}s segments={len(segments)}")
    assert n_pred == 2, f"聚类说话人数应为 2（上限 {MAX_SPEAKERS}），实得 {n_pred}"
    assert report["n_speakers"] == 2, report
    assert acc >= AGREE_MIN, f"说话人分段一致率 {acc:.3f} < {AGREE_MIN}"


def test_shots_cuts_recall(sample, report):
    """② C1 shots.json 强校验 + 轮替边界切分召回 ≥0.8（±0.4s）。"""
    sheet = load_model(sample["jobs"] / "epM5" / "02_shots" / "shots.json", ShotSheet)
    assert sheet.ep == "epM5" and sheet.shots, sheet
    truth_bounds = [t["start"] for t in sample["turns"]]  # 轮替起点=视觉切换点
    hits = 0
    for b in truth_bounds:
        if any(s.start - EPS <= b <= s.end + EPS and s.start > 0
               for s in sheet.shots if abs(s.start - b) <= EPS):
            hits += 1
    recall = hits / len(truth_bounds)
    print(f"\n[shots 实测] 轮替边界 {len(truth_bounds)} 个，命中 {hits}，"
          f"recall={recall:.2f}（冻结线 ≥{CUT_RECALL_MIN}），镜头数={len(sheet.shots)}")
    assert recall >= CUT_RECALL_MIN, f"切分召回 {recall:.2f} < {CUT_RECALL_MIN}"
    for a, b in zip(sheet.shots, sheet.shots[1:]):
        assert b.start >= a.end - 1e-6, "镜头区间倒挂"


def test_frontal_closeup_table(sample, report):
    """③ 正脸近景镜头表：每镜含正脸判定；人像镜 frontal=true、无人脸镜 false，
    与合成真值逐镜一致率 100%。"""
    doc = json.loads((sample["jobs"] / "epM5" / "02_shots" / "frontal_closeups.json")
                     .read_text(encoding="utf-8"))
    rows = doc["shots"]
    assert rows, "正脸近景镜头表为空"
    for r in rows:
        assert isinstance(r["frontal"], bool) and isinstance(r["closeup"], bool) \
            and isinstance(r["faces"], int), f"镜头缺正脸判定字段: {r['shot_id']}"
    # 逐镜真值：镜头主体（时间中点）的画面说话人（句间延续前句口径）= spkA → frontal
    def truth_spk_at(t: float) -> str | None:
        hit = next((x for x in sample["turns"] if x["start"] <= t < x["end"]), None)
        if hit:
            return hit["spk"]
        prev = [x for x in sample["turns"] if x["end"] <= t]
        return (prev[-1]["spk"] if prev else None)

    def truth_frontal(r: dict) -> bool:
        mid = (r["start"] + r["end"]) / 2.0
        return truth_spk_at(mid) == "spkA"

    agree = sum(1 for r in rows if r["frontal"] == truth_frontal(r))
    n_pos = sum(1 for r in rows if truth_frontal(r))
    print(f"\n[faces 实测] 逐镜正脸判定一致率 {agree}/{len(rows)}，"
          f"人像镜 {n_pos} 个（真值），faces≥1 命中 "
          f"{sum(1 for r in rows if truth_frontal(r) and r['faces'] >= 1)}/{n_pos}")
    assert agree == len(rows), "正脸判定与合成真值不一致"
    assert all(r["frontal"] and r["faces"] >= 1 for r in rows if truth_frontal(r)), \
        "人像镜须检出人脸且正脸"
    assert all(not r["frontal"] and r["faces"] == 0
               for r in rows if not truth_frontal(r)), "无人脸镜不得虚报正脸"


def test_utterance_backfill_and_lip_rule(sample, report):
    """④ C2 回填：speaker 非空 100%、人像句 face 命中 C6 分流、shot_id 非占位。"""
    utts = load_jsonl(sample["jobs"] / "epM5" / "04_dial" / "utterances.jsonl",
                      UtteranceTable).root
    assert len(utts) == 8
    assert all(u.speaker for u in utts), "speaker 回填不全（存在空标签）"
    # 标签语义：M5 产 spkN 通用标签；与真值轮次的对应关系逐句校验（轮替 → 两种标签交替）
    truth_spk = [next(t for t in sample["turns"] if t["start"] <= u.start < t["end"])["spk"]
                 for u in utts]
    lab_of = {}
    consistent = 0
    for u, t_spk in zip(utts, truth_spk):
        if lab_of.setdefault(t_spk, u.speaker) == u.speaker:
            consistent += 1
    assert len(lab_of) == 2 and consistent == 8, \
        f"句级说话人回填与真值不符: {list(zip(truth_spk, [u.speaker for u in utts]))}"
    by_truth = {}
    for u in utts:
        hit = next(t for t in sample["turns"] if t["start"] <= u.start < t["end"])
        by_truth.setdefault(hit["spk"], []).append(u)
    a_utts = by_truth.get("spkA", [])
    assert a_utts and all(u.face and u.face.frontal and u.face.closeup
                          for u in a_utts), "人像句须回填正脸近景 face"
    assert all(lip_eligible(u) for u in a_utts), "人像句应命中 C6 口型分流规则"
    b_utts = by_truth.get("spkB", [])
    assert b_utts and all(u.face is None for u in b_utts), "无人脸句 face 应保持空"
    assert all(u.shot_id != "s0000" for u in utts), "shot_id 应回填为真实镜头"


# ---------------------------------------------------------------------------
# 纯函数与组件单测
# ---------------------------------------------------------------------------

def test_frontal_closeup_unit():
    """⑤ 正脸/近景/姿态分解纯函数（合成数值双向验证）。"""
    assert decide_frontal(5.0, 10.0, threshold_deg=25.0)
    assert decide_frontal(-25.0, 25.0, threshold_deg=25.0)
    assert not decide_frontal(5.0, 30.0, threshold_deg=25.0)
    assert not decide_frontal(30.0, 5.0, threshold_deg=25.0)
    assert decide_closeup((0, 0, 100, 300), 1000, min_ratio=0.25)
    assert not decide_closeup((0, 0, 100, 200), 1000, min_ratio=0.25)
    assert not decide_closeup((0, 0, 0, 0), 1000, min_ratio=0.25)
    # 头部姿态矩阵分解：绕 Y 轴 40° → |yaw|>25；绕 X 轴 30° → |pitch|>25
    import math

    def rot_y(deg):
        a = math.radians(deg)
        return np.array([[math.cos(a), 0, math.sin(a)],
                         [0, 1, 0],
                         [-math.sin(a), 0, math.cos(a)]], dtype=np.float64)

    def rot_x(deg):
        a = math.radians(deg)
        return np.array([[1, 0, 0],
                         [0, math.cos(a), -math.sin(a)],
                         [0, math.sin(a), math.cos(a)]], dtype=np.float64)

    m = np.eye(4)
    m[:3, :3] = rot_y(40.0)
    _p, yaw, _r = estimate_head_pose(m)
    assert abs(yaw) > 25, f"40° 转 Y 矩阵应给 |yaw|>25，实得 {yaw}"
    m2 = np.eye(4)
    m2[:3, :3] = rot_x(30.0)
    pitch, _y, _r2 = estimate_head_pose(m2)
    assert abs(pitch) > 25, f"30° 转 X 矩阵应给 |pitch|>25，实得 {pitch}"


def test_cluster_helper_synthetic():
    """谱聚类助手：三簇合成嵌入应还原 3 簇。

    嵌入用正锥构造（公共基向量 + 簇向偏移；真实声纹嵌入跨说话人余弦为正，
    T7 实测跨人 ~0.23/同人 ~0.95）——簇内余弦 ≈0.999、簇间 ≈0.8。
    """
    rng = np.random.default_rng(3)
    base = rng.standard_normal(192)
    centers = [base + 0.6 * rng.standard_normal(192) for _ in range(3)]
    emb = np.stack([c + 0.02 * rng.standard_normal(192) for c in centers
                    for _ in range(4)]).astype(np.float32)
    labels, info = cluster_speakers(emb, max_speakers=5)
    assert info["n_speakers"] == 3, info
    # 同簇标签一致
    for c in range(3):
        got = {labels[i] for i in range(c * 4, c * 4 + 4)}
        assert len(got) == 1, (c, got)


def test_energy_vad_windows():
    """能量 VAD 兜底：双段语音 + 间隙 → 两窗（时间正确）。"""
    sr = 16000
    x = np.zeros(int(4.0 * sr), dtype=np.float32)
    x[int(0.5 * sr):int(1.5 * sr)] = 0.6 * np.sin(
        2 * np.pi * 220 * np.arange(int(1.0 * sr)) / sr)
    x[int(2.5 * sr):int(3.5 * sr)] = 0.6 * np.sin(
        2 * np.pi * 180 * np.arange(int(1.0 * sr)) / sr)
    wins = energy_vad_windows(x, sr)
    assert len(wins) == 2, wins
    assert abs(wins[0][0] - 0.5) < 0.15 and abs(wins[1][1] - 3.5) < 0.15, wins


def test_voxdia_fbank_parity():
    """⑥ fbank 数值一致性（对拍 fixtures/fbank_ref.npy；参照缺失时 skip）。"""
    import torch

    from pipeline._voxdia_net import kaldi_fbank

    ref_path = REPO_ROOT / "tests" / "fixtures" / "fbank_ref.npy"
    if not ref_path.is_file():
        pytest.skip("缺 fixtures/fbank_ref.npy（参照实现离线不可得；非冻结线用例）")
    rng = np.random.default_rng(7)
    x = rng.standard_normal(4 * 16000).astype(np.float32)
    mine = kaldi_fbank(torch.from_numpy(x)).numpy()
    ref = np.load(ref_path)
    assert mine.shape == ref.shape, (mine.shape, ref.shape)
    diff = float(np.abs(mine - ref).max())
    print(f"\n[fbank parity] max_abs={diff:.2e}")
    assert diff < 0.02, f"fbank 与参照实现偏差过大: {diff}"


def test_face_scanner_on_portrait_fixture():
    """facemesh 组件真实推理（公版人像）：检出人脸 + 正脸 + 近景判定命中。"""
    import cv2

    from pipeline._facemesh_face import FaceScanner

    _weights_ready("facemesh")
    img = _imread_unicode(REPO_ROOT / "tests" / "fixtures" / "portrait_pd.jpg")
    assert img is not None
    with FaceScanner() as fs:
        obs = fs.observe_frame(img, 0.0)
    assert obs, "人像 fixture 未检出人脸"
    o = obs[0]
    assert o.frontal, f"正脸人像判定为非正脸: yaw={o.yaw:.1f} pitch={o.pitch:.1f}"
    h = img.shape[0]
    assert o.closeup == decide_closeup(o.bbox, h, min_ratio=0.25)


# ---------------------------------------------------------------------------
# voicebank 子命令（每剧音色库）
# ---------------------------------------------------------------------------

def _voice_ref_wav(work: Path) -> Path:
    """SAPI 长段合成 10-15s 参考音频（超出范围仅 WARN 不拒绝）。"""
    voices = _sapi_voices()
    if "zh" not in voices:
        pytest.skip("本机无 zh SAPI 声库")
    text = ("我们一起来看今天的进度。接下来还要讨论几个重要的问题。"
            "希望你能够认真听取每一个细节，有任何意见都可以随时提出。"
            "我们争取在最后期限之前完成全部的交付内容。")
    return _sapi_sentence(work / "ref.wav", voices["zh"], text)


def test_voicebank_register_list_bind(sample, tmp_path):
    """⑦ voice add/list/bind：voices.yaml 登记 + wav 落 voicebank + C3 强校验
    + speaker_map.json + 双向绑定。"""
    work = tmp_path
    ref = _voice_ref_wav(work)
    voices_copy = work / "voices.yaml"
    shutil.copy2(REPO_ROOT / "configs" / "voices.yaml", voices_copy)

    out = voice_register("epM5", "char_nan", ref, name="程总", gender="m",
                         desc="男主", ep="epM5", jobs_dir=sample["jobs"],
                         voices_path=voices_copy, consent_subject="团队成员A")
    assert out["char_id"] == "char_nan" and out["copied_to"], out
    assert Path(out["copied_to"]).is_file()

    rows = voice_list("epM5", voices_path=voices_copy)
    assert any(r["char_id"] == "char_nan" and r["name"] == "程总" for r in rows)

    # C3 characters.json 经 CastBook 强校验
    book = load_model(sample["jobs"] / "epM5" / "05_cast" / "characters.json", CastBook)
    assert "char_nan" in book.root and book.root["char_nan"].voice_ref.endswith("_ref.wav")

    # 绑定 spk0 → char_nan（回填 C2 char_id 的依据）
    bound = voice_bind("epM5", "spk0", "char_nan", ep="epM5",
                       jobs_dir=sample["jobs"], voices_path=voices_copy)
    assert Path(bound["written"]).is_file()
    mapping = json.loads(Path(bound["written"]).read_text(encoding="utf-8"))
    assert mapping == {"spk0": "char_nan"}
    # 未登记角色拒绝绑定
    with pytest.raises(DiarError):
        voice_bind("epM5", "spk1", "char_ghost", ep="epM5",
                   jobs_dir=sample["jobs"], voices_path=voices_copy)


def test_voice_cli_subprocess(tmp_path):
    """voice 子命令真实子进程形态（list 空库 rc=0 + add 缺文件 rc=1）。"""
    env = {**os.environ, "PYTHONUTF8": "1"}
    voices_copy = tmp_path / "voices.yaml"
    shutil.copy2(REPO_ROOT / "configs" / "voices.yaml", voices_copy)
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.m5_diar", "voice", "list",
         "--cast", "epX", "--voices", str(voices_copy)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300, env=env)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    r2 = subprocess.run(
        [sys.executable, "-m", "pipeline.m5_diar", "voice", "add",
         "--cast", "epX", "--char", "c1", "--wav", str(tmp_path / "ghost.wav"),
         "--voices", str(voices_copy)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300, env=env)
    assert r2.returncode == 1 and "FAIL" in r2.stdout


def test_missing_input_fails(tmp_path, capsys):
    """无音频输入：rc=1 + FAIL（不静默吞错）。"""
    (tmp_path / "epZ").mkdir()
    rc = m5_main(["--ep", "epZ", "--jobs-dir", str(tmp_path), "--no-video"])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_media_absent_products_absent(sample):
    """产物口径齐备性：shots/diar/报告四件套就位（02_shots 与 04_dial）。"""
    ep = sample["jobs"] / "epM5"
    for rel in ("02_shots/shots.json", "02_shots/frontal_closeups.json",
                "04_dial/diar.jsonl", "04_dial/diar_report.json"):
        p = ep / rel
        assert p.is_file() and p.stat().st_size > 0, f"缺产物 {rel}"
