"""M7 验收（本机经 ssh 隧道调 GPU tts 服务 :9002）。

自验收口径（T12）：本机以 Windows SAPI 中文语音合成两段参考——
①音色参考=角色干净人声（中性陈述句）；②情绪参考=带情绪的原片该句人声
（质问句，SAPI rate/volume 拉出情绪轮廓）——经隧道调 :9002 合成**英文句**，断言：
  ① /health 主力引擎 loaded 且路由表与 models.yaml routing.tts 一致；
  ② 双参考合成：wav 落盘、实测时长>0、engine=dub-tts、emo_ref_used=true；
  ③ C 出口对账：客户端复测时长与服务端 duration_s 一致（±0.05s）；
  ④ 路由链：dry_run 解析 en/es/ar 链与 models.yaml 冻结镜像一致；
  ⑤ 离线：C 出口纯函数（响应→wav+时长）、客户端参数校验、payload 契约（桩服务）。
服务不可达（隧道未启动/GPU 机下线）时服务组整组 skip，保证门禁在无 GPU 环境仍绿。

命名纪律：本文件不出现任何上游项目/模型名（scripts/gate_b0 口径）。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pipeline.tts_client import (
    TtsClient,
    TtsError,
    synth_response_to_wav,
)

SERVICE_URL = os.environ.get("M7_TTS_URL", "http://127.0.0.1:9002")
#: 合成目标句（契约 C4/C5 示例句，英文）
EN_SENTENCE = "What do you actually want? Say it clearly."
#: models.yaml routing.tts 冻结镜像（服务 /health.routing 须与此一致）
ROUTING_EXPECT = {
    "en": ["dub-tts", "dub-tts-base", "alt-tts-a", "alt-tts-b"],
    "es": ["dub-tts", "alt-tts-a", "alt-tts-b"],
    "ar": ["dub-tts", "alt-tts-b"],
}

_client = TtsClient(SERVICE_URL, timeout=600.0, retries=5, retry_wait_s=3.0)


# ---------------------------------------------------------------------------
# 离线：C 出口纯函数 / 参数校验 / payload 契约（桩服务）
# ---------------------------------------------------------------------------

def _tiny_wav_bytes(sr: int = 22050, dur_s: float = 0.5) -> bytes:
    t = np.linspace(0.0, dur_s, int(sr * dur_s), endpoint=False)
    wav = (0.3 * np.sin(2 * np.pi * 220.0 * t)).astype("float32")
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV")
    return buf.getvalue()


def test_c_exit_response_to_wav(tmp_path: Path) -> None:
    """C 出口：服务响应（wav_b64+duration_s）→ 落盘 + 客户端复测时长一致。"""
    raw = _tiny_wav_bytes(sr=22050, dur_s=0.5)
    out = tmp_path / "u.wav"
    r = synth_response_to_wav(
        {"engine": "dub-tts", "wav_b64": __import__("base64").b64encode(raw).decode()},
        out,
    )
    assert r["duration_s"] == pytest.approx(0.5, abs=0.01)
    assert r["sr"] == 22050
    assert Path(r["out"]).is_file() and Path(r["out"]).stat().st_size == len(raw)


def test_c_exit_rejects_silence(tmp_path: Path) -> None:
    """全零波形（静音）→ C 出口拒收，不产出假交付。"""
    buf = io.BytesIO()
    sf.write(buf, np.zeros(8000, dtype="float32"), 16000, format="WAV")
    with pytest.raises(TtsError, match="空/静音"):
        synth_response_to_wav(
            {"engine": "x", "wav_b64": __import__("base64").b64encode(buf.getvalue()).decode()},
            tmp_path / "s.wav",
        )


def test_client_input_validation(tmp_path: Path) -> None:
    """客户端先挡一层：空文本/缺参考/越界参数（C5 口径），不发网络请求。"""
    cli = TtsClient("http://127.0.0.1:1")  # 不可达端口——校验应在请求前抛错
    ref = tmp_path / "ref.wav"
    ref.write_bytes(_tiny_wav_bytes())
    with pytest.raises(TtsError, match="text 为空"):
        cli.synth("  ", ref, out=tmp_path / "a.wav")
    with pytest.raises(TtsError, match="音色参考不存在"):
        cli.synth("hello", tmp_path / "nope.wav", out=tmp_path / "a.wav")
    with pytest.raises(TtsError, match="emo_alpha.*越界"):
        cli.synth("hello", ref, emo_alpha=1.5, out=tmp_path / "a.wav")
    with pytest.raises(TtsError, match="duration_factor.*越界"):
        cli.synth("hello", ref, duration_factor=3.0, out=tmp_path / "a.wav")
    with pytest.raises(TtsError, match="情绪参考不存在"):
        cli.synth("hello", ref, emo_ref=tmp_path / "nope.wav", out=tmp_path / "a.wav")


class _StubHandler(BaseHTTPRequestHandler):
    """桩 :9002 服务：断言 multipart 双参考字段齐全后回最小合法响应（离线钉契约）。"""

    seen: dict = {}

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"service": "tts", "loaded": {"dub-tts": True}}).encode())

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.seen["path"] = self.path
        self.seen["has_voice_ref"] = b'name="voice_ref"' in body
        self.seen["has_emo_ref"] = b'name="emo_ref"' in body
        self.seen["has_text"] = b"name=\"text\"" in body
        raw = _tiny_wav_bytes()
        payload = {
            "engine": "dub-tts",
            "chain": ["dub-tts"],
            "attempts": [{"engine": "dub-tts", "ok": True, "emo_ref_used": True}],
            "duration_s": 0.5,
            "sr": 22050,
            "wav_b64": __import__("base64").b64encode(raw).decode(),
            "timing": {"total_s": 0.1},
            "versions": {"dub-tts": "test"},
            "request": {"emo_ref_used": True, "voice_ref_s": 0.5, "emo_ref_s": 0.5},
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *a: object) -> None:  # 静默
        pass


def test_payload_contract_stub(tmp_path: Path) -> None:
    """payload 契约（桩服务）：POST /v1/tts multipart 携带 text+voice_ref+emo_ref 三件套。"""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        ref = tmp_path / "ref.wav"
        ref.write_bytes(_tiny_wav_bytes())
        cli = TtsClient(f"http://127.0.0.1:{srv.server_address[1]}")
        r = cli.synth("hello", ref, emo_ref=ref, lang="en", out=tmp_path / "o.wav", utt_id="ep01-u00000000")
        assert _StubHandler.seen["path"] == "/v1/tts"
        assert _StubHandler.seen["has_voice_ref"] and _StubHandler.seen["has_emo_ref"]
        assert _StubHandler.seen["has_text"]
        assert r["engine"] == "dub-tts"
        assert r["duration_s"] == pytest.approx(0.5, abs=0.01)
        assert r["request_echo"]["emo_ref_used"] is True
    finally:
        srv.shutdown()


# ---------------------------------------------------------------------------
# 在线（服务不可达整组 skip，同 tests/test_m4.py 口径）
# ---------------------------------------------------------------------------

def _service_up() -> bool:
    try:
        return bool(_client.health().get("loaded", {}).get("dub-tts"))
    except TtsError:
        return False


def _sapi_voice(culture_prefix: str) -> str | None:
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
        if culture.lower().startswith(culture_prefix) and name:
            return name
    return None


def _synthesize_zh(out_wav: Path, text: str, *, rate: int = 0, volume: int = 100) -> Path:
    """SAPI 中文合成 → ffmpeg 16k 单声道。失败抛 SkipTest（本机无 zh 声库时）。"""
    voice = _sapi_voice("zh")
    if not voice:
        pytest.skip("本机无中文 SAPI 声库（zh-CN），无法合成参考语音")
    raw = out_wav.with_name(out_wav.stem + "_raw.wav")
    ps = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        f"$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');"
        f"$s.Rate={rate};$s.Volume={volume};"
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
def service() -> TtsClient:
    if not _service_up():
        pytest.skip(
            f"GPU tts 服务不可达（{SERVICE_URL}，先 GPU 机 bash gpu-services/tts/run_gpu.sh start，"
            "本机 TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash ops/tunnel_gpu.sh start）"
        )
    return _client


@pytest.fixture(scope="module")
def refs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """双参考：①音色=中性陈述句；②情绪=质问句（rate/volume 拉出情绪轮廓）。"""
    d = tmp_path_factory.mktemp("m7")
    return {
        "voice": _synthesize_zh(d / "voice_ref.wav", "三年了，程氏的项目，哪一样不是我亲手做起来的。"),
        "emo": _synthesize_zh(d / "emo_ref.wav", "那你就可以这样对我吗！把话说清楚！", rate=2, volume=100),
    }


def test_health_routing(service: TtsClient) -> None:
    """① 主力引擎 loaded；路由表与 models.yaml routing.tts 冻结镜像一致。"""
    h = _client.health()
    assert h["loaded"]["dub-tts"] is True
    assert h["cuda_available"] is True
    assert h["routing"] == ROUTING_EXPECT
    assert h["weights_present"]["dub-tts"] is True
    assert h["engines"]["dub-tts"]["precision"] == "fp32"


def test_dual_ref_synthesis(service: TtsClient, refs: dict[str, Path], tmp_path: Path) -> None:
    """② 核心口径：音色/情绪双参考合成英文句——wav 落盘、时长>0、双参考被确认。"""
    out = tmp_path / "u0007.wav"
    r = _client.synth(
        EN_SENTENCE, refs["voice"], emo_ref=refs["emo"], lang="en",
        emo_alpha=0.7, duration_factor=1.0, out=out, utt_id="ep01-u00000000",
    )
    assert r["engine"] == "dub-tts", f"引擎路由异常: {r['attempts']}"
    assert out.is_file() and out.stat().st_size > 1000
    # C 出口：实际时长>0，且客户端复测=服务端回传（③ 对账）
    wav, sr = sf.read(str(out), dtype="float32")
    dur_measured = len(np.asarray(wav).squeeze()) / sr
    assert dur_measured > 0.3
    assert r["duration_s"] == pytest.approx(dur_measured, abs=0.05)
    # 双参考在服务端被消费：主力引擎原生双参考通道，emo_ref_used 须为 true
    assert r["request_echo"]["emo_ref_used"] is True
    assert r["request_echo"]["voice_ref_s"] > 0 and r["request_echo"]["emo_ref_s"] > 0


def test_voice_only_no_emo_ref(service: TtsClient, refs: dict[str, Path], tmp_path: Path) -> None:
    """缺省情绪参考：只用音色参考也可合成（C5.emo_ref 可空），emo_ref_used=false。"""
    r = _client.synth(EN_SENTENCE, refs["voice"], lang="en", out=tmp_path / "v_only.wav")
    assert r["duration_s"] > 0.3
    assert r["request_echo"]["emo_ref_used"] is False


SAMPLE_TEXT = {"en": EN_SENTENCE, "es": "¿Qué es lo que quieres? Dilo claramente.", "ar": "ماذا تريد؟ قلها بوضوح."}


@pytest.mark.parametrize("lang", ["en", "es", "ar"])
def test_routing_dry_run(service: TtsClient, refs: dict[str, Path], lang: str) -> None:
    """④ 路由链：dry_run 解析链=models.yaml 冻结镜像，不占 GPU。"""
    r = _client.synth(SAMPLE_TEXT[lang], refs["voice"],
                      lang=lang, out="unused.wav", dry_run=True)
    assert r["chain"] == ROUTING_EXPECT[lang]
    assert r["engine"] == ROUTING_EXPECT[lang][0]


def test_explicit_unknown_engine(service: TtsClient, refs: dict[str, Path]) -> None:
    """显式未知引擎 → 服务端 400（客户端归一为 TtsError）。"""
    with pytest.raises(TtsError, match="HTTP 400"):
        _client.synth(EN_SENTENCE, refs["voice"], lang="en", engine="no-such-engine",
                      out="unused.wav")
