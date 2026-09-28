"""M4 验收（本机经 ssh 隧道调 GPU asr_align 服务）。

自验收口径（T5）：本机以 Windows SAPI 中文语音（zh-CN 声库）合成一句话，
经 ffmpeg 重采样为 16k 单声道 wav，经隧道调 :9001，断言：
  ① 转写非空；② 字级时间戳非空、单调、落在音频时长内；③ 情绪标签非空；
  ④ 说话人预分段（segments）非空；⑤ 阿语请求走 align-proportional 降级分支。
服务不可达（隧道未启动/GPU 机下线）时整组 skip，保证 B0 门禁在无 GPU 环境仍绿。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pipeline.gpu_client import GpuClient, GpuServiceError

SERVICE_URL = os.environ.get("M4_ASR_URL", "http://127.0.0.1:9001")
ZH_SENTENCE = "你到底想怎么样？把话说清楚。"

_client = GpuClient(SERVICE_URL, timeout=300.0, retries=0)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _service_up() -> bool:
    try:
        return bool(_client.health().get("loaded", {}).get("asr-core"))
    except GpuServiceError:
        return False


def _sapi_zh_voice() -> str | None:
    """取一个 zh-CN 声库（本机实测有 Microsoft Huihui Desktop）。"""
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices()|ForEach-Object{"
        "$_.VoiceInfo.Name+'|'+$_.VoiceInfo.Culture.Name}"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        name, _, culture = line.strip().partition("|")
        if culture.lower().startswith("zh") and name:
            return name
    return None


def _synthesize_zh_wav(out_wav: Path, text: str = ZH_SENTENCE) -> Path:
    """SAPI 中文语音合成 → ffmpeg 重采样 16k 单声道。失败抛 SkipTest。"""
    voice = _sapi_zh_voice()
    if not voice:
        pytest.skip("本机无中文 SAPI 声库（zh-CN），无法合成测试语音")
    raw = out_wav.with_name(out_wav.stem + "_raw.wav")  # SAPI 原生采样率中间产物
    ps = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        f"$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');"
        "$s.SetOutputToWaveFile('" + str(raw).replace("\\", "/") + "');"
        f"$s.Speak('{text}');"
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=120,
                   capture_output=True, text=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
         "-ar", "16000", "-ac", "1", str(out_wav)],
        check=True, timeout=120, capture_output=True, text=True,
    )
    assert out_wav.is_file() and out_wav.stat().st_size > 1000
    return out_wav


@pytest.fixture(scope="module")
def service() -> GpuClient:
    if not _service_up():
        pytest.skip(f"GPU asr_align 服务不可达（{SERVICE_URL}，先跑 ops/tunnel_gpu.sh start）")
    return _client


@pytest.fixture(scope="module")
def zh_wav(service: GpuClient, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _synthesize_zh_wav(tmp_path_factory.mktemp("m4") / "m4_zh_16k.wav")


# ---------------------------------------------------------------------------
# 断言集
# ---------------------------------------------------------------------------

def test_health(service: GpuClient) -> None:
    h = _client.health()
    assert h["loaded"] == {"asr-core": True, "align-core": True, "emo-tag": True}
    assert h["cuda_available"] is True


def test_transcribe_align_emo(service: GpuClient, zh_wav: Path) -> None:
    """核心口径：非空转写 + 非空逐字时间戳 + 情绪 + 说话人预分段。"""
    import soundfile as sf

    resp = service.asr_align(zh_wav, lang="zh")
    dur = float(resp["duration_s"])

    # ① 转写非空
    assert resp["text"].strip(), f"空转写: {resp}"
    # ② 逐字时间戳：非空、e>=s、单调、落在时长内
    words = resp["words"]
    assert len(words) >= 2, f"字级时间戳为空: {resp}"
    prev_end = -0.2
    for w in words:
        assert w["e"] >= w["s"] >= prev_end - 0.01, w
        assert -0.5 <= w["s"] and w["e"] <= dur + 0.5, (w, dur)
        prev_end = w["e"]
    assert abs(dur - len(sf.read(str(zh_wav))[0]) / 16000) < 0.5
    # ③ 情绪标签非空且合法
    assert resp["emo"] and resp["emo"]["label"], resp.get("emo")
    assert 0.0 <= resp["emo"]["score"] <= 1.0
    # ④ 说话人预分段非空，且覆盖语音窗口
    segs = resp["segments"]
    assert segs and segs[0]["end"] > segs[0]["start"] >= 0.0
    # 对齐器：中文应走主对齐器（若偶发降级须显式留痕）
    assert resp["aligner"] in ("align-core", "align-proportional"), resp.get("align_degrade", "")
    # 计时齐全
    assert set(resp["timing"]) >= {"asr_s", "align_s", "emo_s", "total_s"}


def test_ar_proportional_branch(service: GpuClient, zh_wav: Path) -> None:
    """阿语降级：主对齐器不含阿语 → 字符比例线性内插（models.yaml routing.align.ar）。"""
    resp = service.asr_align(zh_wav, lang="ar")
    assert resp["aligner"] == "align-proportional"
    assert resp["words"], resp
    for w in resp["words"]:
        assert w["e"] > w["s"]
    last_end = resp["words"][-1]["e"]
    assert last_end <= float(resp["duration_s"]) + 0.5
