"""M3 人声/背景分离 eval（规划 §4 M3，冻结通过线）。

冻结 eval 命令::

    pytest tests/test_m3.py

断言（§4 M3 原文，全部真实执行）：
  ① 输出存在且时长=输入；
  ② 人声段 RMS 在有声区间 ≥ 总轨 RMS−6dB、在纯背景区间 ≤−15dBFS
    （正片真值=M2 字幕区间；本 eval 用 ffmpeg 合成的**带伴奏人声样本**，
    人声=Windows SAPI 中文语音（真实语音才能触发卡拉OK系分离模型的
    人声支路），伴奏=ffmpeg lavfi 合成的和声垫+低频脉冲+粉噪声底，
    真值区间=合成时的已知摆放）；
  ③ 60s 素材 CPU 处理 ≤10 分钟（实测值打印留痕）。

自验收追加（任务 T4）：分离出人声轨可被后续 ASR 用 —— 04_dial/vocals.wav
（16k 单声道，M4 唯一识别输入口径，B1 冻结）经隧道送 :9001 asr_align，
断言非空转写+非空字级时间戳；服务不可达时整组 skip（与 tests/test_m4.py 同口径）。

环境依赖：ffmpeg/ffprobe（PATH）、zh-CN SAPI 声库、分离权重
（models/audiosplit/<DEFAULT_MODEL>，不入公开仓；缺失时 skip 并给下载提示）。
依赖注意：同进程 torch 须先于 paddle 导入（仓库硬约束）——本文件运行期才经
pipeline.m3_separate 延迟导入 torch，且套件内无 paddle 测试，次序天然满足。
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pipeline.config import REPO_ROOT, load_pipeline_config
from pipeline.m1_ingest import FFMPEG, FFPROBE, ffprobe_json
from pipeline.m3_separate import (
    DEFAULT_MODEL,
    interval_rms_dbfs,
    load_separation_config,
    load_truth_intervals,
    main as m3_main,
)

pytestmark = pytest.mark.skipif(
    shutil.which(FFMPEG) is None or shutil.which(FFPROBE) is None,
    reason="ffmpeg/ffprobe 不在 PATH（M3 硬依赖）",
)

DUR_TOL_S = 0.2            # §4 M3 ①：输出时长=输入（与 M1 同一口径）
CPU_BUDGET_S = 600.0       # §4 M3 ③：60s 素材 CPU ≤10 分钟
VOICED_MARGIN_DB = -6.0    # §4 M3 ②：有声区间 人声RMS ≥ 总轨RMS−6dB
BGMONLY_CEILING_DBFS = -15.0  # §4 M3 ②：纯背景区间 人声RMS ≤ −15dBFS
BED_TARGET_DELTA_DB = -4.0  # 伴奏 RMS 相对语音 RMS 的目标差（真实卡拉OK量级，
                            # 让判据 ② 对分离质量有区分度而非电平摆设）

SENTENCES = [
    "你到底想怎么样？把话说清楚。",
    "三年了，程氏的项目、老城的基地，哪一样不是我亲手做起来的？",
    "那你就可以这样对我吗！",
    "我以为你至少会信我。",
    "预算超了，档期不能动，客户明天就要。",
]
MIN_TOTAL_S = 60.0  # ③ 的素材规模下限


def _run(cmd: list[str], timeout_s: float = 300.0) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout_s)
    assert r.returncode == 0, f"命令失败 rc={r.returncode}: {' '.join(cmd[:6])}\n{r.stderr[-800:]}"


def _dur(path: Path) -> float:
    return float(ffprobe_json(path)["format"]["duration"])


def _dbfs(x: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    return 20.0 * math.log10(r) if r > 1e-9 else -120.0


# ---------------------------------------------------------------------------
# 素材合成：伴奏（ffmpeg lavfi）+ 人声（SAPI zh）→ 48k 立体声带伴奏人声样本
# ---------------------------------------------------------------------------

def _sapi_zh_voice() -> str | None:
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices()|ForEach-Object{"
        "$_.VoiceInfo.Name+'|'+$_.VoiceInfo.Culture.Name}"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        name, _, culture = line.strip().partition("|")
        if culture.lower().startswith("zh") and name:
            return name
    return None


def _sapi_sentence(dst: Path, voice: str, text: str) -> Path:
    """SAPI 中文语音 → 单句 wav（原生采样率中间产物 + ffmpeg 重采样 48k 单声道）。"""
    raw = dst.with_name(dst.stem + "_raw.wav")
    ps = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        f"$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');"
        "$s.SetOutputToWaveFile('" + str(raw).replace("\\", "/") + "');"
        f"$s.Speak('{text}');"
        "$s.Dispose()"
    )
    _run(["powershell", "-NoProfile", "-Command", ps], timeout_s=120)
    _run([FFMPEG, "-y", "-loglevel", "error", "-i", str(raw),
          "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
    raw.unlink()
    assert dst.is_file() and dst.stat().st_size > 1000
    return dst


def _synth_bed(dst: Path, total_s: float) -> Path:
    """ffmpeg lavfi 合成 48k 立体声伴奏：低频脉冲（鼓点）+ 低音 + 和声垫 + 粉噪空气声。

    刻意**无人声形态学特征**（稳态和声、无共振峰、无语音停顿）——让卡拉OK系
    分离模型的"伴奏"支路有明确归属，判据 ② 才能度量分离质量而非电平。
    """
    d = f"{total_s:.3f}"
    _run([
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"aevalsrc=0.50*sin(2*PI*55*t)*exp(-8*mod(t\\,0.5)):s=48000:d={d}",
        "-f", "lavfi", "-i", f"sine=frequency=110:duration={d}",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={d}",
        "-f", "lavfi", "-i", f"sine=frequency=277.18:duration={d}",
        "-f", "lavfi", "-i", f"sine=frequency=329.63:duration={d}",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.05:duration={d}:seed=42",
        "-filter_complex",
        "[0:a]volume=0.50[k];"
        "[1:a]volume=0.16[b];"
        "[2:a]volume=0.07[c1];[3:a]volume=0.06[c2];[4:a]volume=0.05[c3];"
        "[5:a]volume=0.30,lowpass=f=6500[n];"
        "[k][b][c1][c2][c3][n]amix=inputs=6:duration=first:normalize=0,"
        "aformat=sample_fmts=s16:channel_layouts=stereo",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(dst),
    ])
    return dst


def _place_speech(dst: Path, sentences: list[Path], starts_ms: list[int]) -> tuple[list[tuple[float, float]], float]:
    """ffmpeg adelay+amix 把句子摆上 60s 时间轴；返回 (voiced 区间, 总时长)。"""
    n = len(sentences)
    inputs: list[str] = []
    for p in sentences:
        inputs += ["-i", str(p)]
    fc = "".join(f"[{i}:a]adelay={ms}:all=1[a{i}];" for i, ms in enumerate(starts_ms))
    fc += "".join(f"[a{i}]" for i in range(n))
    fc += f"amix=inputs={n}:duration=longest:normalize=0"
    _run([FFMPEG, "-y", "-loglevel", "error", *inputs,
          "-filter_complex", fc, "-ar", "48000", "-ac", "1",
          "-c:a", "pcm_s16le", str(dst)], timeout_s=300)
    voiced, total = [], 0.0
    for p, ms in zip(sentences, starts_ms):
        d = _dur(p)
        voiced.append([ms / 1000.0, ms / 1000.0 + d])
        total = max(total, ms / 1000.0 + d)
    return voiced, total


def _measure(wav: Path, intervals: list[list[float]]) -> tuple[float, float]:
    """(区间内 RMS dBFS, 峰值 dBFS)。"""
    x, sr = sf.read(str(wav), dtype="float64", always_2d=True)
    mono = x.mean(axis=1)
    chunks = []
    for s, e in intervals:
        i0, i1 = int(s * sr), max(int(s * sr) + 1, int(e * sr))
        chunks.append(mono[i0:min(i1, mono.shape[0])])
    rms = _dbfs(np.concatenate(chunks)) if chunks else -120.0
    peak = _dbfs(np.array([mono.max() if mono.size else 0.0]))
    return rms, peak


def _mix_to_stereo(dst: Path, bed: Path, speech: Path, bed_gain_db: float, trim_db: float) -> Path:
    """bed（按电平差定增益）+ speech → 48k 立体声 pcm_s16le 成品样本。"""
    _run([FFMPEG, "-y", "-loglevel", "error", "-i", str(bed), "-i", str(speech),
          "-filter_complex",
          f"[0:a]volume={bed_gain_db + trim_db:.2f}dB[b];"
          f"[1:a]volume={trim_db:.2f}dB,pan=stereo|c0=c0|c1=c0[s];"
          f"[b][s]amix=inputs=2:duration=first:normalize=0",
          "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(dst)])
    return dst


def _synthesize_sample(work: Path, n_sentences: int | None = None):
    """合成带伴奏人声样本 → (mix48 路径, truth dict, 语音轨路径, 增益 dB)。

    真值区间由实际摆放决定：voiced=每句实际起止；bgm_only=句间隙+头尾。
    ``n_sentences=None``（全套 5 句）→ 素材补足到 60s（判据 ③ 规模）；
    指定句数（CLI 冒烟用）→ 按实际时长收尾，不强行拉到 60s。
    """
    voice = _sapi_zh_voice()
    if not voice:
        pytest.skip("本机无中文 SAPI 声库（zh-CN），无法合成测试语音")
    n = n_sentences or len(SENTENCES)
    sents = [_sapi_sentence(work / f"sp{i}.wav", voice, t) for i, t in enumerate(SENTENCES[:n])]

    min_total = MIN_TOTAL_S if n_sentences is None else 0.0
    starts_ms, t = [], 3.0
    for p in sents:
        starts_ms.append(int(t * 1000))
        t += _dur(p) + 4.0
    total = max(min_total, t)

    bed = _synth_bed(work / "bed48.wav", total)
    speech_track = work / "speech48.wav"
    voiced, _ = _place_speech(speech_track, sents, starts_ms)

    speech_rms, speech_peak = _measure(speech_track, voiced)
    bed_x, bed_sr = sf.read(str(bed), dtype="float64", always_2d=True)
    bed_rms, bed_peak = _dbfs(bed_x.mean(axis=1)), _dbfs(np.array([bed_x.max()]))

    bed_gain_db = speech_rms - bed_rms + BED_TARGET_DELTA_DB
    mix_peak = 10 ** (speech_peak / 20) + 10 ** ((bed_peak + bed_gain_db) / 20)
    trim_db = min(0.0, -1.0 - 20 * math.log10(max(mix_peak, 1e-9)))

    mix = _mix_to_stereo(work / "mix48.wav", bed, speech_track, bed_gain_db, trim_db)

    bgm_only: list[list[float]] = []
    prev_end = 0.0
    for s, e in voiced:
        if s - prev_end > 0.05:
            bgm_only.append([prev_end, s])
        prev_end = e
    if total - prev_end > 0.05:
        bgm_only.append([prev_end, total])
    truth = {"voiced": voiced, "bgm_only": bgm_only}
    return mix, truth, speech_track, bed_gain_db


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _weights_ready() -> Path:
    comp = load_separation_config("cpu")
    ckpt = comp["weights_dir"] / comp["model"]
    if not ckpt.is_file():
        pytest.skip(f"分离权重未就位: {ckpt}（见 configs/models.yaml audiosplit 条目下载说明）")
    return ckpt


@pytest.fixture(scope="module")
def sample60(tmp_path_factory) -> dict:
    """60s 带伴奏人声样本（判据 ②③ 的素材）+ 真值区间 JSON。"""
    _weights_ready()
    d = tmp_path_factory.mktemp("m3_sample")
    mix, truth, speech_track, gain = _synthesize_sample(d)
    truth_path = d / "truth.json"
    truth_path.write_text(json.dumps(truth), encoding="utf-8")
    return {"dir": d, "mix": mix, "truth": truth, "truth_path": truth_path,
            "speech_track": speech_track, "bed_gain_db": gain}


@pytest.fixture(scope="module")
def jobs60(tmp_path_factory, sample60) -> Path:
    """把成品样本摆进 jobs/<ep>/01_media/（M1 产出口径），供 eval 复用。"""
    d = tmp_path_factory.mktemp("m3_jobs")
    media = d / "epT" / "01_media"
    media.mkdir(parents=True)
    shutil.copy2(sample60["mix"], media / "audio_48k.wav")
    return d


@pytest.fixture(scope="module")
def separation(jobs60, sample60) -> dict:
    """对 60s 样本执行一次 CPU 分离（in-process CLI），计时并复用产物。"""
    t0 = time.perf_counter()
    rc = m3_main(["--ep", "epT", "--jobs-dir", str(jobs60),
                  "--device", "cpu", "--truth", str(sample60["truth_path"])])
    wall = time.perf_counter() - t0
    assert rc == 0, "m3_separate 主流程返回非 0"
    return {"wall_s": wall}


# ---------------------------------------------------------------------------
# 冻结 eval（规划 §4 M3 ①②③）
# ---------------------------------------------------------------------------

def test_m3_eval_outputs_and_duration(separation, jobs60, sample60, capsys):
    """① 输出存在且时长=输入；产物口径：vocals 16k 单声道 / bgm 同输入。"""
    src = jobs60 / "epT" / "01_media" / "audio_48k.wav"
    voc = jobs60 / "epT" / "04_dial" / "vocals.wav"
    bgm = jobs60 / "epT" / "01_media" / "bgm.wav"
    rep = jobs60 / "epT" / "04_dial" / "separate.json"
    for p in (voc, bgm, rep):
        assert p.is_file() and p.stat().st_size > 0, f"缺产物 {p}"

    src_dur = _dur(src)
    for p in (voc, bgm):
        assert abs(_dur(p) - src_dur) <= DUR_TOL_S, f"{p.name}: |{_dur(p)}-{src_dur}| > {DUR_TOL_S}"

    va = ffprobe_json(voc)["streams"][0]
    assert va["codec_name"] == "pcm_s16le" and int(va["sample_rate"]) == 16000 \
        and int(va["channels"]) == 1, "vocals.wav 须为 16k 单声道（M4 识别输入口径）"
    ba = ffprobe_json(bgm)["streams"][0]
    assert ba["codec_name"] == "pcm_s16le" and int(ba["sample_rate"]) == 48000 \
        and int(ba["channels"]) == 2, "bgm.wav 须与分离输入同口径（48k 立体声，M9 配套）"


def test_m3_eval_rms_criteria(separation, jobs60, sample60):
    """② RMS 判据：有声区间 人声 ≥ 总轨−6dB；纯背景区间 人声 ≤ −15dBFS。

    独立重算（不信任 separate.json），真值=合成摆放。
    """
    src = jobs60 / "epT" / "01_media" / "audio_48k.wav"
    voc = jobs60 / "epT" / "04_dial" / "vocals.wav"
    truth = sample60["truth"]

    mix_voiced = interval_rms_dbfs(src, truth["voiced"])
    voc_voiced = interval_rms_dbfs(voc, truth["voiced"])
    voc_bgmonly = interval_rms_dbfs(voc, truth["bgm_only"])

    margins = [v - m for v, m in zip(voc_voiced, mix_voiced)]
    print(f"\n[RMS 实测] 每句裕量(vocals-mix)={ [round(m, 2) for m in margins] } dB; "
          f"纯背景区间人声 RMS={[round(v, 2) for v in voc_bgmonly]} dBFS")
    assert min(margins) >= VOICED_MARGIN_DB, \
        f"有声区间人声不足: 最小裕量 {min(margins):.2f}dB < {VOICED_MARGIN_DB}dB"
    assert max(voc_bgmonly) <= BGMONLY_CEILING_DBFS, \
        f"纯背景区间人声残留过高: {max(voc_bgmonly):.2f}dBFS > {BGMONLY_CEILING_DBFS}dBFS"

    doc = json.loads((jobs60 / "epT" / "04_dial" / "separate.json").read_text(encoding="utf-8"))
    assert doc["rms"]["criteria"]["voiced_ge_mix_minus_6db"] is True
    assert doc["rms"]["criteria"]["bgmonly_le_-15dbfs"] is True


def test_m3_eval_cpu_budget(separation, sample60):
    """③ 60s 素材 CPU 处理 ≤10 分钟（模型加载+分离+重采样落盘全计，实测打印留痕）。"""
    wall = separation["wall_s"]
    print(f"\n[CPU 实测] 60s 素材 CPU 全流程 {wall:.1f}s（预算 {CPU_BUDGET_S:.0f}s）")
    assert wall <= CPU_BUDGET_S, f"CPU 处理超时: {wall:.1f}s > {CPU_BUDGET_S:.0f}s"


# ---------------------------------------------------------------------------
# 自验收追加（任务 T4）：人声轨可被后续 ASR 用
# ---------------------------------------------------------------------------

SERVICE_URL = os.environ.get("M4_ASR_URL", "http://127.0.0.1:9001")


def test_vocals_asr_usable(separation, jobs60):
    """M3 出口（04_dial/vocals.wav，B1 冻结 M4 唯一识别输入）→ :9001 转写非空。"""
    from pipeline.gpu_client import GpuClient, GpuServiceError

    client = GpuClient(SERVICE_URL, timeout=300.0, retries=0)
    try:
        h = client.health()
    except GpuServiceError:
        pytest.skip(f"GPU asr_align 服务不可达（{SERVICE_URL}，先跑 ops/tunnel_gpu.sh start）")
    assert h.get("loaded", {}).get("asr-core"), h

    voc = jobs60 / "epT" / "04_dial" / "vocals.wav"
    resp = client.asr_align(voc, lang="zh")
    assert (resp.get("text") or "").strip(), f"人声轨转写为空: {resp}"
    assert resp.get("words"), "人声轨字级时间戳为空"
    dur = float(resp.get("duration_s") or 0.0)
    assert abs(dur - _dur(voc)) < 0.5, (dur, _dur(voc))
    print(f"\n[ASR 实测] vocals.wav → {resp['text']!r}（words={len(resp['words'])}）")


# ---------------------------------------------------------------------------
# 双路径配置 / CLI 形态 / 防御路径
# ---------------------------------------------------------------------------

def test_separation_routing_dual_path():
    """CPU/GPU 双路径配置路由（configs/models.yaml routing.separation）。"""
    cpu = load_separation_config("cpu")
    cuda = load_separation_config("cuda")
    assert cpu["component"] == "audiosplit" and cpu["device"] == "cpu"
    assert cpu["chunk_s"] == 120.0, "CPU 路径默认分块"
    assert cuda["component"] == "audiosplit-cuda"
    assert cuda["device_claim"] == "cuda:0" and cuda["chunk_s"] is None, "cuda 路径整轨"
    assert cpu["model"] == cuda["model"] == DEFAULT_MODEL
    assert cpu["weights_dir"].is_dir()


def test_cli_subprocess_cpu(tmp_path):
    """§4 M3 CLI 冻结形态经真实子进程验证（8s 短样本，不重复 60s 大样本）。"""
    d = tmp_path
    mix, truth, _, _ = _synthesize_sample(d, n_sentences=1)
    media = d / "epS" / "01_media"
    media.mkdir(parents=True)
    shutil.copy2(mix, media / "audio_48k.wav")
    env = {**os.environ, "PYTHONUTF8": "1"}
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.m3_separate", "--ep", "epS",
         "--jobs-dir", str(d), "--device", "cpu"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "OK m3_separate epS" in r.stdout
    assert (d / "epS" / "04_dial" / "vocals.wav").is_file()
    assert (d / "epS" / "01_media" / "bgm.wav").is_file()


def test_cli_cuda_on_cpu_machine_fails_cleanly(tmp_path, capsys):
    """device=cuda 而本机无 CUDA：拒绝执行（rc=1 + FAIL），不静默回退 CPU。"""
    import torch  # 环境预检：若该环境确有 CUDA 则本测试无意义，直接过
    if torch.cuda.is_available():
        pytest.skip("本环境 torch 有 CUDA，无法验证无卡拒绝路径")
    media = tmp_path / "epC" / "01_media"
    media.mkdir(parents=True)
    dummy = media / "audio_48k.wav"  # 1s 正弦占位（cuda 守卫先于分离触发）
    subprocess.run([FFMPEG, "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(dummy)],
                   check=True, capture_output=True, timeout=60)
    rc = m3_main(["--ep", "epC", "--jobs-dir", str(tmp_path), "--device", "cuda"])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_missing_input_fails(tmp_path, capsys):
    (tmp_path / "epX").mkdir()
    rc = m3_main(["--ep", "epX", "--jobs-dir", str(tmp_path)])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


def test_truth_loader():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.json"
        p.write_text(json.dumps({"voiced": [[1, 2]], "bgm_only": [[0, 1]]}), encoding="utf-8")
        t = load_truth_intervals(p)
        assert t == {"voiced": [[1.0, 2.0]], "bgm_only": [[0.0, 1.0]]}
        bad = Path(d) / "bad.json"
        bad.write_text(json.dumps({"voiced": [[1, 2]]}), encoding="utf-8")
        from pipeline.m3_separate import SeparationError

        with pytest.raises(SeparationError):
            load_truth_intervals(bad)
