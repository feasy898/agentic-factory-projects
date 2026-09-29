"""M10 验收（本机经 ssh 隧道调 GPU lip 服务 :9003）。

自验收口径（T16）：①C6 分流纯逻辑——正脸近景镜头表（M5 产出）硬门槛 +
face.frontal/closeup/!overlap + 台词最长前 10% 与 --pro-shots 升级精口型；
②回贴合成位精确性——无损拼装路径自洽（零替换输出逐帧字节等同源）、
抽段帧数=帧域换算、错位/越界/重叠拒绝；③帧哈希自验器——窗外改动可检出、
窗内漏替换可检出；④服务真跑（在线）：4s 正脸近景样本（人像恒定+缓慢变焦，
[0,2) 口型窗、[2,4) 原画）→ 服务真跑 → 输出**非口型帧 raw yuv sha256 逐帧
字节级不变** + **口型窗帧全异** + **嘴区像素变化量达标** → exit 0。
服务不可达（隧道未启动/GPU 机下线）时服务组整组 skip，保证门禁在无 GPU 环境仍绿。

命名纪律：本文件不出现任何上游项目/模型名（scripts/gate_b0 口径）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pipeline import contracts as C
from pipeline.m10_lipsync import (
    LipClient,
    LipError,
    build_lip_plan,
    engine_fallback_chain,
    extract_video_segment,
    frame_hashes,
    lip_response_to_video,
    run,
    splice_segments,
    verify_paste_back,
    window_to_frames,
)

SERVICE_URL = os.environ.get("M10_LIP_URL", "http://127.0.0.1:9003")
REPO = Path(__file__).resolve().parents[1]
PORTRAIT = REPO / "tests" / "fixtures" / "portrait_pd.jpg"

_client = LipClient(SERVICE_URL, timeout=600.0, retries=3, retry_wait_s=3.0)


# ---------------------------------------------------------------------------
# 样本与工作区构造（C2 / M5 镜头表 = 冻结 schema 的合成产物）
# ---------------------------------------------------------------------------

def _run_ffmpeg(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"ffmpeg 失败: {r.stderr[-400:]}"


def build_closeup_video(out: Path, *, dur_s: float = 4.0, fps: int = 25,
                        size: str = "540x960") -> None:
    """正脸近景样本视频：公版人像 cover 裁切 + 缓慢变焦（帧间有差异，
    逐帧错位拼接会被字节级自验当场抓出）。"""
    assert PORTRAIT.is_file(), f"公版人像 fixture 缺失: {PORTRAIT}"
    w, hv = (size.split("x") + [""])[:2]
    frames = int(dur_s * fps)
    _run_ffmpeg([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-t", f"{dur_s}", "-i", str(PORTRAIT),
        "-vf", (
            f"scale={w}:{hv}:force_original_aspect_ratio=increase,"
            f"crop={w}:{hv},"
            f"zoompan=z='min(1.0+0.0004*on,1.2)':d={frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{hv}:fps={fps}"
        ),
        "-frames:v", f"{frames}", "-c:v", "libx264", "-crf", "18",
        "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out),
    ])


def build_dub_track(out: Path, *, dur_s: float = 4.0, speech_s: float = 2.0,
                    sr: int = 16000) -> None:
    """配音轨：前 speech_s 为带调制的人声带通信号（驱动逐帧口型开合），
    其余静音（原画区）。避免依赖系统 TTS 声库，样本可重建。"""
    n = int(dur_s * sr)
    t = np.arange(n) / sr
    f0 = 165.0
    wob = 1.0 + 0.35 * np.sign(np.sin(2 * np.pi * 3.2 * t)) * np.sin(
        2 * np.pi * 14.0 * t)  # 词组节奏的开合包络
    sig = 0.5 * wob * np.sin(2 * np.pi * f0 * t)
    sig += 0.12 * np.sin(2 * np.pi * 2 * f0 * t) * wob
    sig[int(speech_s * sr):] = 0.0  # 口型窗外静音
    sig *= np.minimum(1.0, t * 20) * np.minimum(1.0, (dur_s - t) * 20)
    sf.write(str(out), sig.astype(np.float32), sr, subtype="PCM_16")


def synth_workspace(ep: str, jobs: Path, *, video: Path, audio: Path,
                    utt_windows: list[tuple[float, float, bool, bool]],
                    fps: int = 25) -> Path:
    """最小工作区：01_media 源 + 08_mix 配音 + 02_shots M5 表 + C2 事实。

    ``utt_windows`` = [(start, end, frontal, closeup)]；face bbox 取画面
    中央竖带（人像 cover 裁切后人脸居中，下半含嘴区——自验器只拿它算
    嘴区相对变化量，框略宽不影响判定方向）。
    """
    import cv2

    ws = jobs / ep
    (ws / "01_media").mkdir(parents=True, exist_ok=True)
    (ws / "02_shots").mkdir(parents=True, exist_ok=True)
    (ws / "04_dial").mkdir(parents=True, exist_ok=True)
    (ws / "08_mix").mkdir(parents=True, exist_ok=True)
    (ws / "09_lip").mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    ok, frame = cap.read()
    cap.release()
    assert ok
    hv, w = frame.shape[:2]
    # 人像近景：脸占中上 2/3（cover 裁切口径）；bbox 给脸区，嘴区取下半
    bbox = [int(w * 0.18), int(hv * 0.12), int(w * 0.82), int(hv * 0.78)]

    utts = []
    diar = []
    for i, (s, e, frontal, closeup) in enumerate(utt_windows):
        utt_id = f"{ep}-u{int(round(s * 1000)):08d}"
        utts.append(C.Utterance(
            utt_id=utt_id, shot_id=f"s{i:04d}", start=s, end=e, lang="zh",
            text="样本句", overlap=False,
            face=C.FaceFact(frontal=frontal, closeup=closeup, bbox=bbox)))
        diar.append(C.DiarSegment(start=s, end=e, speaker="spk0"))
    C.dump_jsonl(ws / "04_dial" / "utterances.jsonl",
                 C.UtteranceTable.model_validate(utts))
    C.dump_jsonl(ws / "04_dial" / "diar.jsonl",
                 C.DiarTable.model_validate(diar))

    n = len(utt_windows)
    shots_doc = {
        "schema_version": 1, "ep": ep,
        "shots": [{
            "shot_id": f"s{i:04d}", "start": s, "end": e, "faces": 1,
            "frontal": bool(frontal and closeup),
            "closeup": bool(frontal and closeup),
            "tracks": [{"track_id": i, "frontal": frontal, "closeup": closeup,
                        "bbox": bbox}],
        } for i, (s, e, frontal, closeup) in enumerate(utt_windows)],
    }
    # M5 表口径：非正脸近景镜头也在表内但置 false（表缺失才是硬错误）
    shots_doc["shots"].append({
        "shot_id": f"s{n:04d}", "start": 90.0, "end": 92.0, "faces": 0,
        "frontal": False, "closeup": False, "tracks": [],
    })
    (ws / "02_shots" / "frontal_closeups.json").write_text(
        json.dumps(shots_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    (ws / "02_shots" / "shots.json").write_text(
        C.ShotSheet(ep=ep, fps=fps, dur=max(e for s, e, *_ in utt_windows),
                    shots=[C.Shot(shot_id=f"s{i:04d}", start=s, end=e,
                                  faces=1)
                           for i, (s, e, *_r) in enumerate(utt_windows)]
                    ).model_dump_json(), encoding="utf-8")
    import shutil

    shutil.copy2(video, ws / "01_media" / "video_1080x1920_25fps.mp4")
    shutil.copy2(audio, ws / "08_mix" / "dubbed.en.wav")
    return ws


# ---------------------------------------------------------------------------
# 离线：C6 分流纯逻辑
# ---------------------------------------------------------------------------

def test_plan_gate_requires_m5_table(tmp_path: Path) -> None:
    """M5 正脸近景镜头表缺席 → 硬错误（无表不分流，C6 硬门槛）。"""
    ws = tmp_path / "epX"
    (ws / "04_dial").mkdir(parents=True)
    C.dump_jsonl(ws / "04_dial" / "utterances.jsonl", C.UtteranceTable.model_validate(
        [C.Utterance(utt_id="epX-u00000000", shot_id="s0000",
                     start=0.0, end=1.0, lang="zh")]))
    with pytest.raises(LipError, match="正脸近景镜头表不存在"):
        build_lip_plan("epX", "en", jobs_dir=tmp_path)


def test_plan_routing_and_pro(tmp_path: Path) -> None:
    """分流全表：合格→lip-fast；不合格（表外/无脸/重叠）不进计划；
    台词最长前 10% 与 --pro-shots 升级精口型；C6 容器强校验过。"""
    video = tmp_path / "v.mp4"
    audio = tmp_path / "dub.wav"
    build_closeup_video(video, dur_s=8.0)
    build_dub_track(audio, dur_s=8.0)
    ep = "epP"
    # s0000 合格近景（3 句：0-1 短 / 2-4 长 / 5-6 中）；s0001 有脸但重叠；
    # s0002 非正脸近景（表置 false）；s0003 表外镜头（C2 有 face 也不做）
    ws = synth_workspace(ep, tmp_path, video=video, audio=audio, utt_windows=[
        (0.0, 1.0, True, True),
        (2.0, 4.0, True, True),    # 最长 → top10% 升 pro
        (5.0, 6.0, True, True),
    ])
    # 注入重叠句（同镜第二说话人，C2 overlap=true）与非近景句
    rows = C.load_jsonl(ws / "04_dial" / "utterances.jsonl",
                        C.UtteranceTable).root
    bbox = rows[0].face.bbox
    extra = [
        C.Utterance(utt_id=f"{ep}-u00002100", shot_id="s0000", start=2.1,
                    end=3.0, lang="zh", overlap=True,
                    face=C.FaceFact(frontal=True, closeup=True, bbox=bbox)),
        C.Utterance(utt_id=f"{ep}-u00007100", shot_id="s0002", start=7.1,
                    end=7.9, lang="zh", overlap=False,
                    face=C.FaceFact(frontal=False, closeup=False, bbox=bbox)),
        C.Utterance(utt_id=f"{ep}-u00009000", shot_id="s0003", start=9.0,
                    end=9.8, lang="zh", overlap=False,
                    face=C.FaceFact(frontal=True, closeup=True, bbox=bbox)),
    ]
    C.dump_jsonl(ws / "04_dial" / "utterances.jsonl",
                 C.UtteranceTable.model_validate(list(rows) + extra))

    info = build_lip_plan(ep, "en", jobs_dir=tmp_path, pro_shots=("s0000",))
    # 合格：u0(表内+frontal+closeup+非重叠)、u2、u(5-6)；pro：最长 u(2-4) +
    # --pro-shots 命中 s0000 的两句；重叠句/非近景句/表外句全部不进计划
    plan = C.load_jsonl(info["plan_path"], C.LipPlanTable).root
    by_id = {p.utt_id: p for p in plan}
    assert f"{ep}-u00002100" not in by_id, "重叠句须被分流排除"
    assert f"{ep}-u00007100" not in by_id, "非正脸近景句须被分流排除"
    assert f"{ep}-u00009000" not in by_id, "M5 表外镜头须被分流排除"
    assert info["n_eligible"] == 3
    assert by_id[f"{ep}-u00002000"].engine == "lip-pro"      # 台词最长前 10%
    assert by_id[f"{ep}-u00000000"].engine == "lip-pro"      # --pro-shots
    assert by_id[f"{ep}-u00005000"].engine == "lip-fast"
    assert by_id[f"{ep}-u00005000"].priority == "normal"
    assert by_id[f"{ep}-u00002000"].priority == "pro"
    assert by_id[f"{ep}-u00005000"].window == [5.0, 6.0]
    assert Path(info["copy_path"]).is_file()                 # 无后缀语种副本


def test_window_to_frames_math() -> None:
    assert window_to_frames([0.0, 2.0], 25.0, 100) == (0, 50)
    assert window_to_frames([12.402, 14.0], 25.0, 1000) == (310, 350)
    assert window_to_frames([-0.2, 900.0], 25.0, 100) == (0, 100)
    with pytest.raises(LipError, match="映射为空"):
        window_to_frames([3.0, 3.0], 25.0, 100)


# ---------------------------------------------------------------------------
# 离线：C 出口纯函数 / 客户端校验 / payload 契约（桩服务）
# ---------------------------------------------------------------------------

def test_response_to_video(tmp_path: Path) -> None:
    raw = b"fake-mp4-bytes"
    b64 = base64.b64encode(raw).decode()
    sha = hashlib.sha256(raw).hexdigest()
    r = lip_response_to_video({"video_b64": b64, "sha256": sha,
                               "n_frames": 50, "fps": 25.0},
                              tmp_path / "seg.mp4")
    assert Path(r["out"]).read_bytes() == raw
    assert r["n_frames"] == 50 and r["sha256"] == sha
    with pytest.raises(LipError, match="sha256 对账失败"):
        lip_response_to_video({"video_b64": b64, "sha256": "bad", "n_frames": 1},
                              tmp_path / "x.mp4")
    with pytest.raises(LipError, match="video_b64"):
        lip_response_to_video({}, tmp_path / "y.mp4")
    with pytest.raises(LipError, match="帧数非正"):
        lip_response_to_video({"video_b64": b64, "n_frames": 0},
                              tmp_path / "z.mp4")


def test_client_input_validation(tmp_path: Path) -> None:
    cli = LipClient("http://127.0.0.1:1")  # 不可达端口——校验应在请求前抛错
    v = tmp_path / "v.mp4"
    a = tmp_path / "a.wav"
    v.write_bytes(b"x")
    a.write_bytes(b"y")
    with pytest.raises(LipError, match="视频段不存在"):
        cli.lip(tmp_path / "nope.mp4", a, out=tmp_path / "o.mp4")
    with pytest.raises(LipError, match="配音段不存在"):
        cli.lip(v, tmp_path / "nope.wav", out=tmp_path / "o.mp4")


class _StubHandler(BaseHTTPRequestHandler):
    """桩 :9003 服务：断言 multipart video+audio+mode 字段齐全后回最小合法响应。"""

    seen: dict = {}

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({
            "service": "lip", "loaded": {"lip-fast": True},
            "physical_device": "cuda:1", "logical_device": "cuda:0",
            "engine": {"name": "lip-fast", "precision": "fp16"},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.seen["path"] = self.path
        body = self.rfile.read(length)
        self.seen["has_video"] = b'name="video"' in body
        self.seen["has_audio"] = b'name="audio"' in body
        self.seen["mode"] = (
            body.split(b'name="mode"', 1)[1].split(b"\r\n\r\n", 1)[1]
            .split(b"\r\n", 1)[0]
            if b'name="mode"' in body else b"")
        raw = b"stub-segment"
        payload = {
            "engine": "lip-fast", "mode": "fast",
            "n_frames": 50, "fps": 25.0, "duration_s": 2.0,
            "video_b64": base64.b64encode(raw).decode(),
            "video_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "timing": {"preprocess_s": 0.1, "infer_s": 0.2, "paste_s": 0.01},
            "rtf": 0.2, "n_placeholder_fixed": 0,
            "versions": {"lip-fast": "test"},
            "request": {"utt_id": "u", "shot_id": "s"},
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *a: object) -> None:  # 静默
        pass


def test_payload_contract_stub(tmp_path: Path) -> None:
    """payload 契约（桩服务）：POST /v1/lip multipart 携带 video+audio+mode。"""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        v = tmp_path / "v.mp4"
        a = tmp_path / "a.wav"
        v.write_bytes(b"vv")
        a.write_bytes(b"aa")
        cli = LipClient(f"http://127.0.0.1:{srv.server_address[1]}")
        h = cli.health()
        assert h["loaded"]["lip-fast"] is True
        r = cli.lip(v, a, tmp_path / "o.mp4", utt_id="ep01-u00000000",
                    shot_id="s0000", mode="fast")
        assert _StubHandler.seen["path"] == "/v1/lip"
        assert _StubHandler.seen["has_video"] and _StubHandler.seen["has_audio"]
        assert _StubHandler.seen["mode"] == b"fast"
        assert r["n_frames"] == 50
        assert (tmp_path / "o.mp4").read_bytes() == b"stub-segment"
        assert r["rtf"] == 0.2
    finally:
        srv.shutdown()


# ---------------------------------------------------------------------------
# 离线：回贴合成位精确性 + 自验器（真实 ffmpeg 编解码）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tiny_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """120 帧 320x480@25fps 测试视频（渐变+跳变帧，帧间可区分）。"""
    d = tmp_path_factory.mktemp("m10v")
    out = d / "tiny.mp4"
    _run_ffmpeg([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i",
        "testsrc2=size=320x480:rate=25:duration=4.8",
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", str(out),
    ])
    return out


def test_splice_lossless_passthrough(tiny_video: Path, tmp_path: Path) -> None:
    """零替换拼装：输出逐帧 raw yuv sha256 与源全等（无损回路成立，
    这是"非口型帧字节级零改动"的实现基础）。"""
    out = tmp_path / "pass.mp4"
    stats = splice_segments(tiny_video, [], out, n_frames=120)
    assert stats["n_replaced"] == 0 and stats["n_passthrough"] == 120
    assert frame_hashes(out) == frame_hashes(tiny_video)


def test_extract_segment_frame_math(tiny_video: Path, tmp_path: Path) -> None:
    """抽段帧数=帧域换算（帧栅格 seek 不漂移）。"""
    assert extract_video_segment(tiny_video, tmp_path / "a.mp4", 0, 50, 25.0) == 50
    assert extract_video_segment(tiny_video, tmp_path / "b.mp4", 50, 120, 25.0) == 70
    assert extract_video_segment(tiny_video, tmp_path / "c.mp4", 30, 90, 25.0) == 60


def test_splice_replace_and_detect(tiny_video: Path, tmp_path: Path) -> None:
    """窗内替换生效（帧异）、窗外透传（帧同）；自验器对"窗外被改动"与
    "窗内漏替换"两类缺陷都能抓。"""
    # 段=源片 [0,50) 的重编码变体（模拟服务产出：内容近似但位不同）
    seg = tmp_path / "seg.mp4"
    extract_video_segment(tiny_video, seg, 0, 50, 25.0)
    out = tmp_path / "out.mp4"
    stats = splice_segments(tiny_video, [(0, 50, str(seg))], out, n_frames=120)
    assert stats["n_replaced"] == 50 and stats["n_passthrough"] == 70
    hs, ho = frame_hashes(tiny_video), frame_hashes(out)
    assert len(hs) == len(ho) == 120
    assert all(hs[i] != ho[i] for i in range(50)), "窗内帧应全被替换"
    assert all(hs[i] == ho[i] for i in range(50, 120)), "窗外帧应字节透传"
    vr = verify_paste_back(tiny_video, out, [(0, 50, None)])
    assert vr["ok"] is True and vr["identical_outside"] == 70

    # 缺陷注入①：窗外帧被改动（重编码整片当"产出"）→ 自验必须 FAIL
    bad = tmp_path / "bad.mp4"
    _run_ffmpeg(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tiny_video),
                 "-c:v", "libx264", "-crf", "25", "-preset", "veryfast",
                 "-pix_fmt", "yuv420p", str(bad)])
    vr = verify_paste_back(tiny_video, bad, [(0, 50, None)])
    assert vr["ok"] is False and "非口型帧被改动" in vr["reason"]

    # 缺陷注入②：窗内漏替换（零段拼装却谎称 [0,50) 是窗）→ 自验必须 FAIL
    plain = tmp_path / "plain.mp4"
    splice_segments(tiny_video, [], plain, n_frames=120)
    vr = verify_paste_back(tiny_video, plain, [(0, 50, None)])
    assert vr["ok"] is False and "未变化" in vr["reason"]


def test_splice_rejects_overlap_and_oob(tiny_video: Path, tmp_path: Path) -> None:
    seg = tmp_path / "seg.mp4"
    extract_video_segment(tiny_video, seg, 0, 50, 25.0)
    with pytest.raises(LipError, match="重叠"):
        splice_segments(tiny_video, [(0, 50, str(seg)), (40, 90, str(seg))],
                        tmp_path / "o1.mp4", n_frames=120)
    with pytest.raises(LipError, match="越界"):
        splice_segments(tiny_video, [(100, 130, str(seg))],
                        tmp_path / "o2.mp4", n_frames=120)


def test_engine_fallback_chain() -> None:
    """执行降级链 = models.yaml components.<engine>.fallback 冻结镜像：
    lip-pro → [lip-pro, lip-pro-1.5, lip-fast]；lip-fast 单节点。"""
    assert engine_fallback_chain("lip-pro") == ["lip-pro", "lip-pro-1.5", "lip-fast"]
    assert engine_fallback_chain("lip-fast") == ["lip-fast"]


def test_run_pro_unreachable_hard_fail(tmp_path: Path) -> None:
    """降级链尾 lip-fast（主力）不可达 = 硬错误——链首 lip-pro 的 503 口径
    可降级，主力失败不静默弃窗。"""
    video = tmp_path / "v.mp4"
    audio = tmp_path / "dub.wav"
    build_closeup_video(video, dur_s=2.0)
    build_dub_track(audio, dur_s=2.0, speech_s=1.5)
    synth_workspace("epF", tmp_path, video=video, audio=audio,
                    utt_windows=[(0.0, 1.5, True, True)])
    with pytest.raises(LipError, match="主力引擎 lip-fast 调用失败"):
        run("epF", "en", jobs_dir=tmp_path, url="http://127.0.0.1:1",
            verify=False)


# ---------------------------------------------------------------------------
# 在线（服务不可达整组 skip，同 tests/test_m7_tts.py 口径）
# ---------------------------------------------------------------------------

def _service_up() -> bool:
    try:
        return bool(_client.health().get("loaded", {}).get("lip-fast"))
    except LipError:
        return False


@pytest.fixture(scope="module")
def service() -> LipClient:
    if not _service_up():
        pytest.skip(
            f"GPU lip 服务不可达（{SERVICE_URL}，先 GPU 机 bash gpu-services/lip/"
            "run_gpu.sh start，本机 TUNNEL_LOCAL_PORT=9003 TUNNEL_REMOTE_PORT=9003 "
            "bash ops/tunnel_gpu.sh start）"
        )
    return _client


def test_health(service: LipClient) -> None:
    """① 主力引擎 loaded；物理卡=部署矩阵 cuda:1；精度=fp16。"""
    h = _client.health()
    assert h["loaded"]["lip-fast"] is True
    assert h["cuda_available"] is True
    assert h["physical_device"] == "cuda:1"
    assert h["engine"]["precision"] == "fp16"
    assert h["engine"]["version"]


def test_real_run_2s_window(service: LipClient, tmp_path: Path) -> None:
    """② 核心口径：4s 正脸近景样本（[0,2) 口型窗 / [2,4) 原画）→ 服务真跑
    → 非口型帧字节级不变 + 口型窗帧全异 + 嘴区变化达标 → exit 0。

    单句窗按台词最长前 10% 升 lip-pro（plan 口径）→ 服务 503（权重 TBD-D1）
    → 注册表降级链落到 lip-fast 真跑——降级路径与主路径一次覆盖。"""
    video = tmp_path / "sample.mp4"
    audio = tmp_path / "dub.wav"
    build_closeup_video(video, dur_s=4.0)
    build_dub_track(audio, dur_s=4.0, speech_s=2.0)
    ep = "epL"
    synth_workspace(ep, tmp_path, video=video, audio=audio,
                    utt_windows=[(0.0, 2.0, True, True)])

    report = run(ep, "en", jobs_dir=tmp_path, url=SERVICE_URL, verify=True)
    item = report["items"][0]
    assert item["status"] == "done", f"服务调用失败: {item}"
    assert item["degraded"] is True, "单句 top10% 应按计划升 lip-pro 后降级执行"
    assert item["engine"] == "lip-pro" and item["engine_used"] == "lip-fast"
    assert item["attempts"], "降级前链节点失败须记入 attempts"
    assert "lip-pro" in item["attempts"][0]["engine"]
    assert item["rtf"] is not None  # RTF 如实记录（冻结线归 M10 GPU eval）
    vr = report["verify"]
    assert vr["ok"] is True, f"自验不过: {vr}"
    assert vr["n_frames_outside"] == 50 and vr["identical_outside"] == 50
    assert vr["n_frames_inside"] == 50 and vr["changed_inside"] == 50
    assert vr["mouth"] and all(m["pass"] for m in vr["mouth"])
    assert Path(report["out"]).is_file()
    # 报告落盘 + 耗时/RTF 可追溯
    rep_path = tmp_path / ep / "09_lip" / "lip_report.en.json"
    assert rep_path.is_file()
    on_disk = json.loads(rep_path.read_text(encoding="utf-8"))
    assert on_disk["items"][0]["rtf"] == item["rtf"]
    print(f"\n[lip real] rtf={item['rtf']} wall={item['wall_s']}s "
          f"timing={item['timing']}")


def test_real_run_cli(service: LipClient, tmp_path: Path) -> None:
    """③ CLI 冻结形态（python -m pipeline.m10_lipsync）真实子进程 exit 0。"""
    video = tmp_path / "sample.mp4"
    audio = tmp_path / "dub.wav"
    build_closeup_video(video, dur_s=4.0)
    build_dub_track(audio, dur_s=4.0, speech_s=2.0)
    synth_workspace("epC", tmp_path, video=video, audio=audio,
                    utt_windows=[(0.0, 2.0, True, True)])
    r = subprocess.run(
        [os.environ.get("PY", "python"), "-m", "pipeline.m10_lipsync",
         "--ep", "epC", "--lang", "en", "--jobs-dir", str(tmp_path),
         "--url", SERVICE_URL],
        capture_output=True, text=True, timeout=900,
        env={**os.environ, "PYTHONUTF8": "1"}, cwd=str(REPO))
    assert r.returncode == 0, f"CLI 失败: {r.stdout}\n{r.stderr}"
    assert "verify=True" in r.stdout
    assert Path(tmp_path / "epC" / "09_lip" / "done" / "epC.en.lip.mp4").is_file()
