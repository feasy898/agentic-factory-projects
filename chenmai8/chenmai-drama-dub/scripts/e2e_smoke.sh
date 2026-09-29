#!/usr/bin/env bash
# e2e_smoke.sh — 端到端冒烟（规划 §7 / 任务 T22 / D9 出口判据：本脚本退出码 0）。
#
# 流程：合成素材（中文对白 + 硬字幕短视频，SAPI zh 人声 + 公有领域人像帧）
#   → 全管线 M1→M3→M4(:9001)→M2→M5→音色库→逐语种[M6(mock)→M8→M7(:9002)→M11→M9
#   →显式标识→M10(:9003)→封元数据→M15] → tests/check_e2e.py 断言集。
#
# 用法（任意 cwd 可跑；Git Bash/MSYS 环境，ffmpeg/ffprobe 须在 PATH）::
#   bash scripts/e2e_smoke.sh                    # 三语 en,es,ar，默认全新重跑
#   bash scripts/e2e_smoke.sh --langs en         # 单语（--skip-gpu 同义于 --langs en）
#   bash scripts/e2e_smoke.sh --reuse            # 不清场不重造素材（断点续跑）
#
# GPU 依赖与降级口径（T22 定案）：
#   - :9001 asr / :9002 tts 必须可达（配音与识别是 e2e 的被测对象，不可达时
#     不伪造结果 → 两轮重试各含 60s 等待后 FAIL exit 1，输出 SKIP-GPU 指引；
#     GPU 受限时可用 --langs en / --skip-gpu 收敛为单语冒烟）；
#   - :9003 lip 可选：不可达 → SKIP-LIP 注明并继续（m10 仅出空计划不合成，
#     最终成片=12_out 成片；check_e2e 的"非口型帧不变"自动切换容差口径）；
#   - 显式 AI 标识（片头 3s 文字提示，PIL 预渲染 PNG + ffmpeg overlay 实现，
#     本机 ffmpeg 6.1.1 drawtext=textfile 滤镜图解析异常故用等效替身）为本脚本
#     的 M12 最小替身（T11 未收口的部分），元数据隐式标识由 M9 依 C7
#     labels.json 写入——两者都被 check_e2e 断言；
#   - 每语种 M15 后快照 12_out/metrics.<lang>.json（metrics.json 本体只留
#     最后一语种，断言集读快照）。
#   - 素材台词首句起于 3.2s：片头 0–3s 为显式标识专属静默区，保证无任何
#     口型窗覆盖标识时段（④ 断言的确定性前提）。
# 日志: tmp/e2e_smoke.log；素材布局: tmp/e2e_material.json。
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
JOBS_ABS="$ROOT/../jobs"
CLIPS_ABS="$ROOT/../clips"

EP="e2e01"
LANGS=""
FRESH=1
SKIP_GPU=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ep) EP="$2"; shift 2 ;;
    --langs) LANGS="$2"; shift 2 ;;
    --skip-gpu) SKIP_GPU=1; shift ;;
    --reuse) FRESH=0; shift ;;
    *) echo "未知参数: $1（支持 --ep/--langs/--skip-gpu/--reuse）"; exit 2 ;;
  esac
done
[ -n "$LANGS" ] || { [ "$SKIP_GPU" = 1 ] && LANGS="en" || LANGS="en,es,ar"; }

export PYTHONUTF8=1
PY="$ROOT/.venv/Scripts/python.exe"
[ -f "$PY" ] || PY="$ROOT/.venv/bin/python"
[ -f "$PY" ] || { echo "FAIL 未找到 .venv 解释器"; exit 1; }

mkdir -p tmp
LOG="$ROOT/tmp/e2e_smoke.log"
: > "$LOG"

say() { echo "$@" | tee -a "$LOG"; }
run_step() {  # run_step <名称> <cmd...> —— 失败即打印日志尾并 exit 1
  local name="$1"; shift
  say "---- [$name] $*"
  if ! "$@" >> "$LOG" 2>&1; then
    say "FAIL 步骤失败: $name（日志尾 25 行见下）"
    tail -25 "$LOG" | tee -a "$LOG"
    exit 1
  fi
  say "---- [$name] OK"
}
check_rc() {  # check_rc <名称> <rc> —— 内联 python heredoc 后的退出码检查
  if [ "$2" -ne 0 ]; then
    say "FAIL 步骤失败: $1（rc=$2，日志尾 25 行见下）"
    tail -25 "$LOG" | tee -a "$LOG"
    exit 1
  fi
  say "---- [$1] OK"
}

probe_port() { curl -sf -m 3 "http://127.0.0.1:$1/health" >/dev/null 2>&1; }

ensure_tunnel() {  # ensure_tunnel <port> <必需 yes|no> <名称>
  local port="$1" required="$2" name="$3" i
  if probe_port "$port"; then say "tunnel :$port ($name) already UP"; return 0; fi
  TUNNEL_LOCAL_PORT="$port" TUNNEL_REMOTE_PORT="$port" bash ops/tunnel_gpu.sh start >> "$LOG" 2>&1
  for i in 1 2 3; do
    probe_port "$port" && { say "tunnel :$port ($name) UP"; return 0; }
    sleep 5
  done
  # 公网链路周期性 reset：等 60s 重拉一轮再判（通用上下文：遇限流等 60s）
  say "tunnel :$port ($name) 未就绪，60s 后重试一轮"
  sleep 60
  TUNNEL_LOCAL_PORT="$port" TUNNEL_REMOTE_PORT="$port" bash ops/tunnel_gpu.sh restart >> "$LOG" 2>&1
  for i in 1 2 3; do
    probe_port "$port" && { say "tunnel :$port ($name) UP（重试后）"; return 0; }
    sleep 5
  done
  if [ "$required" = "yes" ]; then
    say "SKIP-GPU: GPU 服务 :$port ($name) 不可达（隧道两轮重试无效）。"
    say "  ASR/TTS 是本 e2e 的被测对象，不可达时不伪造结果——请先 bash ops/tunnel_gpu.sh start"
    say "  并确认 GPU 机服务常驻（gpu-services/*/run_gpu.sh），再重跑；或 --langs en 缩小面。"
    exit 1
  fi
  say "SKIP-LIP: GPU 服务 :$port ($name) 不可达——口型阶段跳过（m10 仅出空计划），链路继续。"
  return 1
}

# ---------------------------------------------------------------------------
# 0) 隧道（:9001/:9002 必需，:9003 可选）
# ---------------------------------------------------------------------------
LIP_UP=1
ensure_tunnel 9001 yes "asr_align" || exit 1
ensure_tunnel 9002 yes "tts" || exit 1
ensure_tunnel 9003 no "lip" || LIP_UP=0

# ---------------------------------------------------------------------------
# 1) 合成素材：中文对白 + 硬字幕（1080x1920/25fps，人脸入画供口型分流）
# ---------------------------------------------------------------------------
RAW_CLIP="$CLIPS_ABS/${EP}_raw.mp4"
if [ "$FRESH" = 1 ]; then
  say "---- 清场 jobs/$EP 与素材（--reuse 可跳过）"
  rm -rf "$JOBS_ABS/$EP"
  rm -f "$RAW_CLIP"
fi
if [ ! -f "$RAW_CLIP" ]; then
  say "---- [material] 合成素材 → $RAW_CLIP"
  "$PY" - "$EP" "$RAW_CLIP" >> "$LOG" 2>&1 <<'PYMAT'
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

ep, clip_s = sys.argv[1], sys.argv[2]
root = Path.cwd()
clip = Path(clip_s)
clip.parent.mkdir(parents=True, exist_ok=True)
tmp = root / "tmp"
tmp.mkdir(exist_ok=True)

# 台词取自 mt_backends._MOCK_LEXICON 全覆盖句（ASR 实测可整句命中，见 jobs/ep01），
# 保证 mock 翻译无未覆盖 Han 残段 → 目标语字幕零中文（check ③a 的前提）。
SENTS = [  # (text, speaker, sapi_rate)
    ("你到底想怎么样", "A", 0),
    ("把话说清楚", "B", -2),
    ("三年了", "A", -1),
]
FONT = Path(r"C:\Windows\Fonts\msyh.ttc")
assert FONT.is_file(), f"缺中文字体: {FONT}"

def trim_tail(data: np.ndarray, sr: int, thr: float = 0.004, margin_s: float = 0.06):
    """掐头去尾静音（SAPI 慢速尾音会拖过 VAD，令 OCR/ASR 句窗失配——实测教训）。"""
    x = np.asarray(data).squeeze()
    nz = np.nonzero(np.abs(x) > thr)[0]
    assert nz.size, "整段静音"
    a = max(0, int(nz[0] - margin_s * sr))
    b = min(len(x), int(nz[-1] + margin_s * sr))
    return x[a:b]

# ---- 1a) SAPI 合成 3 句 → 48k mono wav ----
voices = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Add-Type -AssemblyName System.Speech;"
     "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
     "$s.GetInstalledVoices()|ForEach-Object{$_.VoiceInfo.Name+'|'+$_.VoiceInfo.Culture.Name}"],
    capture_output=True, text=True, timeout=60).stdout
zh_voice = next((ln.split("|")[0] for ln in voices.splitlines()
                 if "|zh" in ln.lower()), None)
assert zh_voice, f"本机无 zh SAPI 声库:\n{voices}"
wavs = []
for i, (text, spk, rate) in enumerate(SENTS):
    raw = tmp / f"e2e_sapi_{i}.wav"
    ok48 = tmp / f"e2e_sapi_{i}_48k.wav"
    ps = ("$ErrorActionPreference='Stop';"
          "Add-Type -AssemblyName System.Speech;"
          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          f"$s.SelectVoice('{zh_voice}');$s.Rate={rate};"
          "$s.SetOutputToWaveFile('" + str(raw).replace('\\', '/') + "');"
          f"$s.Speak('{text}');$s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=120,
                   capture_output=True, text=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
                    "-ar", "48000", "-ac", "1", str(ok48)], check=True, timeout=120)
    wavs.append((ok48, spk))

# ---- 1b) 时间轴布局：首句 3.2s 起（片头 0-3s 留给显式标识），句间 1.0s，尾留 1.0s；
#            字幕显示窗=修剪后语音窗（与 M2 OCR 行/M4 VAD 窗对齐，保证 OCR↔ASR 融合命中）----
cursor, layout = 3.2, []
for i, ((w, spk), (text, _, _)) in enumerate(zip(wavs, SENTS)):
    data, _sr = sf.read(str(w), dtype="float32")
    data = trim_tail(data, _sr)
    trim_w = w.with_name(w.stem + "_trim.wav")
    sf.write(str(trim_w), data, _sr, subtype="PCM_16")
    wavs[i] = (trim_w, spk)
    dur = len(data) / _sr
    layout.append({"text": text, "speaker": spk, "start": round(cursor, 3),
                   "end": round(cursor + dur, 3)})
    cursor += dur + 1.0
total = round(cursor + 1.0 - 1.0, 3)  # 末句后留 1.0s 静默（④c/⑥ 抽样锚点）
n_frames = int(round(total * 25))

# ---- 1c) 音轨：48k 立声摆放 ----
sr = 48000
track = np.zeros((int(round(total * sr)), 2), dtype=np.float32)
for (w, _), item in zip(wavs, layout):
    data, _sr = sf.read(str(w), dtype="float32")
    data = np.asarray(data).squeeze()
    i0 = int(item["start"] * sr)
    seg = data[: max(0, len(track) - i0)] * 0.85
    track[i0:i0 + len(seg), 0] += seg
    track[i0:i0 + len(seg), 1] += seg
peak = float(np.abs(track).max())
if peak > 0.99:
    track *= 0.99 / peak
audio_wav = tmp / "e2e_audio_48k.wav"
sf.write(str(audio_wav), track, sr, subtype="PCM_16")

# ---- 1d) 视频：公有领域人像（fixtures，M5 同款真脸）铺满画幅 + 硬字幕 ----
from pipeline.m1_ingest import FFMPEG  # noqa: E402

portrait = Image.open(root / "tests" / "fixtures" / "portrait_pd.jpg").convert("RGB")
scale = 1920 / portrait.height
pw = int(portrait.width * scale)
portrait = portrait.resize((pw, 1920), Image.LANCZOS)
x0 = max(0, (pw - 1080) // 2)
base_img = portrait.crop((x0, 0, x0 + 1080, 1920))

font = ImageFont.truetype(str(FONT), 64)
sub_imgs = {}
for i, item in enumerate(layout):
    img = base_img.copy()
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), item["text"], font=font, stroke_width=6)
    tw = bbox[2] - bbox[0]
    d.text(((1080 - tw) / 2 - bbox[0], 1560 - bbox[1]), item["text"],
           font=font, fill=(255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0))
    sub_imgs[i] = np.asarray(img)[:, :, ::-1].copy()  # RGB→BGR
none_img = np.asarray(base_img)[:, :, ::-1].copy()

video_only = tmp / "e2e_video.mp4"
vw = cv2.VideoWriter(str(video_only), cv2.VideoWriter_fourcc(*"mp4v"), 25, (1080, 1920))
assert vw.isOpened(), "cv2.VideoWriter 打开失败（mp4v 后端缺失？）"
for f in range(n_frames):
    t = f / 25.0
    state = none_img
    for i, item in enumerate(layout):
        if item["start"] - 0.02 <= t <= item["end"] + 0.02:
            state = sub_imgs[i]
    vw.write(state)
vw.release()

subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(video_only),
                "-i", str(audio_wav), "-c:v", "libx264", "-preset", "fast",
                "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-shortest", str(clip)], check=True, timeout=600)
video_only.unlink(missing_ok=True)
(tmp / "e2e_material.json").write_text(json.dumps(
    {"ep": ep, "clip": str(clip), "duration_s": total, "fps": 25,
     "n_frames": n_frames, "sentences": layout}, ensure_ascii=False, indent=2),
    encoding="utf-8")
print(f"OK material {clip} dur={total}s frames={n_frames}")
PYMAT
  check_rc "material" $?
  say "素材布局: $(head -c 400 tmp/e2e_material.json | tr -d '\n')"
fi

# ---------------------------------------------------------------------------
# 2) 音频/识别/对齐链（每集一次）
# ---------------------------------------------------------------------------
run_step "m1_ingest"   "$PY" -m pipeline.m1_ingest --ep "$EP" --in "$RAW_CLIP"
run_step "m3_separate" "$PY" -m pipeline.m3_separate --ep "$EP"
run_step "m4_asr"      "$PY" -m pipeline.m4_asr --ep "$EP"
run_step "m2_ocr"      "$PY" -m pipeline.m2_ocr --ep "$EP"
run_step "m5_diar"     "$PY" -m pipeline.m5_diar --ep "$EP"

# ---------------------------------------------------------------------------
# 3) 音色库：按 C2 聚类说话人登记角色参考并绑定 + 重跑 M5 回填 char_id
#    （voices.yaml 副本写 tmp/，不动 configs/voices.yaml）
# ---------------------------------------------------------------------------
say "---- [voicebank] 按 diar 聚类登记角色参考并绑定"
cp configs/voices.yaml "tmp/e2e_voices_$EP.yaml"
"$PY" - "$EP" "$ROOT/tmp/e2e_voices_$EP.yaml" >> "$LOG" 2>&1 <<'PYVB'
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ep, voices_path = sys.argv[1], sys.argv[2]
root = Path.cwd()
sys.path.insert(0, str(root))
from pipeline import contracts as C  # noqa: E402
from pipeline.config import load_pipeline_config  # noqa: E402

wsp = Path(load_pipeline_config()["paths"]["jobs_dir"]) / ep
utts = C.load_jsonl(wsp / "04_dial" / "utterances.jsonl", C.UtteranceTable).root
spk_windows: dict[str, list[tuple[float, float]]] = {}
for u in utts:
    spk_windows.setdefault(u.speaker or "spk0", []).append((float(u.start), float(u.end)))

voc, vsr = sf.read(str(wsp / "04_dial" / "vocals.wav"), dtype="float32")
voc = np.asarray(voc).squeeze()

def bind(spk: str, char: str, name: str) -> None:
    segs = []
    for a, b in spk_windows.get(spk, []):
        i0, i1 = int(a * vsr), min(int(b * vsr), len(voc))
        if i1 > i0:
            segs.append(voc[i0:i1])
            segs.append(np.zeros(int(0.2 * vsr), dtype=np.float32))
    ref = np.concatenate(segs)[: int(15.5 * vsr)] if segs else None
    assert ref is not None and ref.size > vsr, f"{spk} 人声切片为空"
    ref_path = root / "tmp" / f"e2e_ref_{char}.wav"  # 暂存 tmp；voice add 负责复制入 voicebank
    sf.write(str(ref_path), ref, vsr, subtype="PCM_16")
    for cmd in (
        ["-m", "pipeline.m5_diar", "voice", "add", "--cast", ep, "--char", char,
         "--wav", str(ref_path), "--name", name, "--gender", "u", "--ep", ep,
         "--voices", voices_path],
        ["-m", "pipeline.m5_diar", "voice", "bind", "--cast", ep,
         "--spk", spk, "--char", char, "--ep", ep, "--voices", voices_path],
    ):
        r = subprocess.run([sys.executable, *cmd], capture_output=True, cwd=str(root),
                           text=True, encoding="utf-8", errors="replace", timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)} 失败: {(r.stderr or r.stdout)[:300]}")
    print(f"bound {spk} -> {char} (ref {ref.size / vsr:.1f}s)")

spks = sorted(spk_windows)
print(f"clusters: {spks}")
for i, spk in enumerate(spks[:2]):  # 上限 2 角色（对白双方）
    bind(spk, f"char_{'ab'[i]}", f"e2e角色{'甲乙'[i]}")
PYVB
check_rc "voicebank" $?
if [ -f "$JOBS_ABS/$EP/05_cast/speaker_map.json" ]; then
  run_step "m5_diar_rerun" "$PY" -m pipeline.m5_diar --ep "$EP"   # speaker_map 就位后回填 char_id
fi

# ---------------------------------------------------------------------------
# 4) C7 labels.json（M9 隐式标识读它；显式替身与其同源）
# ---------------------------------------------------------------------------
"$PY" - "$EP" >> "$LOG" 2>&1 <<'PYC7'
import json
import sys
from pathlib import Path

ep = sys.argv[1]
root = Path.cwd()
sys.path.insert(0, str(root))
from pipeline import contracts as C  # noqa: E402
from pipeline.config import load_pipeline_config  # noqa: E402

jobs_root = Path(load_pipeline_config()["paths"]["jobs_dir"])
p = jobs_root / ep / "11_labels" / "labels.json"
if p.is_file():
    print(f"labels exists: {p}")
    sys.exit(0)
provider = "澄迈短剧出海（e2e 冒烟）"
content_id = f"{ep}-e2e"
labels = {
    "service_provider": provider,
    "content_id": content_id,
    "standard": "GB45438-2025",
    "explicit": {"text": "本内容由AI生成",
                 "video": "12_out（片头 3s drawtext，e2e 的 M12 最小替身）",
                 "audio_announce": False},
    "implicit": {"metadata_field": "XMP:aiGeneratedContent",
                 "value": f"{content_id}|{provider}"},
    "c2pa": "pending（T11/M12 未收口，e2e 不断言 C2PA）",
    "audio_wm": {"engine": "audmark", "payload": content_id, "bits": 16},
}
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
C.load_model(p, C.Labels)  # 落盘前契约强校验
print(f"OK labels {p}")
PYC7
check_rc "labels_c7" $?

# ---------------------------------------------------------------------------
# 5) 逐语种：M6→M8→M7→M11→M9→显式标识→[prelip 快照→M10→封元数据]→M15
# ---------------------------------------------------------------------------
for LANG in ${LANGS//,/ }; do
  say "======== 语种 $LANG ========"
  run_step "m6_translate[$LANG]" "$PY" -m pipeline.m6_translate --ep "$EP" --lang "$LANG" --backend mock
  run_step "m8_align[$LANG]"     "$PY" -m pipeline.m8_align --ep "$EP" --lang "$LANG"

  say "---- [m7_synth[$LANG]] C5 → :9002 逐句合成（+C5.atempo 微调）"
  "$PY" - "$EP" "$LANG" >> "$LOG" 2>&1 <<'PYTTS'
import subprocess
import sys
from pathlib import Path

ep, lang = sys.argv[1], sys.argv[2]
root = Path.cwd()
sys.path.insert(0, str(root))
from pipeline import contracts as C  # noqa: E402
from pipeline.config import load_pipeline_config  # noqa: E402
from pipeline.m1_ingest import FFMPEG  # noqa: E402
from pipeline.tts_client import TtsClient  # noqa: E402

ws = Path(load_pipeline_config()["paths"]["jobs_dir"]) / ep
rows = C.load_jsonl(ws / "07_synth" / f"synth_plan.{lang}.jsonl", C.SynthPlanTable).root
cli = TtsClient()
n = 0
for r in rows:
    if r.keep_original:
        print(f"skip {r.utt_id} (keep_original)")
        continue
    out = ws / r.out
    res = cli.synth(
        r.text, str(ws / r.voice_ref),
        emo_ref=str(ws / r.emo_ref) if r.emo_ref else None,
        lang=lang, emo_alpha=float(r.emo_alpha),
        duration_factor=float(r.duration_factor),
        engine=r.engine or "auto", out=str(out), utt_id=r.utt_id)
    if r.atempo and abs(float(r.atempo) - 1.0) > 1e-3:
        tmp = out.with_name(out.stem + ".atempo.wav")
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(out),
                        "-af", f"atempo={float(r.atempo):.4f}", str(tmp)],
                       check=True, timeout=300)
        tmp.replace(out)
    n += 1
    print(f"synth {r.utt_id} engine={res['engine']} dur={res['duration_s']}s "
          f"df={r.duration_factor} atempo={r.atempo} expect={r.expect_dur}s")
assert n > 0, "C5 无可合成句（全 keep_original？）"
print(f"OK m7_synth {n} 句")
PYTTS
  check_rc "m7_synth[$LANG]" $?

  run_step "m11_subs[$LANG]" "$PY" -m pipeline.m11_subs --ep "$EP" --lang "$LANG"
  run_step "m9_mix[$LANG]"   "$PY" -m pipeline.m9_mix --ep "$EP" --lang "$LANG"

  say "---- [explicit_label[$LANG]] 片头 3s 显式标识（M12 最小替身，PIL 渲染 PNG + overlay）+ 元数据重封"
  "$PY" - "$EP" "$LANG" >> "$LOG" 2>&1 <<'PYLBL'
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ep, lang = sys.argv[1], sys.argv[2]
root = Path.cwd()
sys.path.insert(0, str(root))
from pipeline.config import load_pipeline_config  # noqa: E402
from pipeline.m1_ingest import FFMPEG  # noqa: E402

out12 = (Path(load_pipeline_config()["paths"]["jobs_dir"]) / ep / "12_out"
         / f"{ep}.{lang}.mp4")
assert out12.is_file(), f"成片不存在: {out12}（M9 未跑？）"
labels = json.loads((out12.parents[1] / "11_labels" / "labels.json")
                    .read_text(encoding="utf-8"))
field, value = labels["implicit"]["metadata_field"], labels["implicit"]["value"]

# 用 PIL 预渲染标识 PNG（等价 drawtext 顶部居中/片头 3s；本机 ffmpeg 6.1.1 的
# drawtext=textfile 走滤镜图解析异常，overlay+enable 为等效替身，实测通过）。
tmp = Path(tempfile.mkdtemp(prefix="e2e_lbl_"))
font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 84)
probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
bb = probe.textbbox((0, 0), "本内容由AI生成", font=font, stroke_width=6)
img = Image.new("RGBA", (bb[2] - bb[0], bb[3] - bb[1]), (0, 0, 0, 0))
ImageDraw.Draw(img).text((-bb[0], -bb[1]), "本内容由AI生成", font=font,
                         fill=(255, 255, 255, 255), stroke_width=6,
                         stroke_fill=(0, 0, 0, 255))
png = tmp / "ai_label.png"
img.save(png)

fc = "[0:v][1:v]overlay=(W-w)/2:64:enable='lte(t,3)'[v]"  # label_zone: top_px=60
tmp_out = out12.with_name(out12.name + ".lbl.tmp.mp4")
subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(out12), "-i", str(png),
                "-filter_complex", fc, "-map", "[v]", "-map", "0:a:0",
                "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                "-pix_fmt", "yuv420p", "-c:a", "copy",
                "-movflags", "+faststart+use_metadata_tags",
                "-metadata", f"{field}={value}", str(tmp_out)],
               check=True, timeout=1200)
tmp_out.replace(out12)
print(f"OK explicit_label {out12.name} field={field}")
PYLBL
  check_rc "explicit_label[$LANG]" $?

  if [ "$LIP_UP" = 1 ]; then
    cp "$JOBS_ABS/$EP/12_out/$EP.$LANG.mp4" "$JOBS_ABS/$EP/12_out/.prelip.$EP.$LANG.mp4"
    run_step "m10_lip[$LANG]" "$PY" -m pipeline.m10_lipsync --ep "$EP" --lang "$LANG" \
      --source "$JOBS_ABS/$EP/12_out/$EP.$LANG.mp4"
    say "---- [seal[$LANG]] 口型成片元数据封口（-c copy 重写 C7 隐式标识位）→ 12_out 槽位"
    "$PY" - "$EP" "$LANG" >> "$LOG" 2>&1 <<'PYSEAL'
import json
import subprocess
import sys
from pathlib import Path

ep, lang = sys.argv[1], sys.argv[2]
root = Path.cwd()
sys.path.insert(0, str(root))
from pipeline.config import load_pipeline_config  # noqa: E402
from pipeline.m1_ingest import FFMPEG  # noqa: E402

ws = Path(load_pipeline_config()["paths"]["jobs_dir"]) / ep
lip = ws / "09_lip" / "done" / f"{ep}.{lang}.lip.mp4"
if not lip.is_file():
    print("no lip product（空计划原画）——跳过封口，最终成片=12_out 成片")
    sys.exit(0)
labels = json.loads((ws / "11_labels" / "labels.json").read_text(encoding="utf-8"))
field, value = labels["implicit"]["metadata_field"], labels["implicit"]["value"]
out12 = ws / "12_out" / f"{ep}.{lang}.mp4"
tmp = out12.with_name(out12.name + ".seal.tmp.mp4")
subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(lip),
                "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                "-movflags", "+faststart+use_metadata_tags",
                "-metadata", f"{field}={value}", str(tmp)], check=True, timeout=600)
tmp.replace(out12)  # 12_out 槽位 = 最终交付成片（含口型）
print(f"OK seal 12_out/{ep}.{lang}.mp4 ← {lip.name}")
PYSEAL
    check_rc "seal[$LANG]" $?
  else
    say "SKIP-LIP: 口型服务不可达，$LANG 跳过 M10（最终成片=12_out 成片）"
  fi

  run_step "m15_metrics[$LANG]" "$PY" -m pipeline.m15_metrics --ep "$EP" --lang "$LANG"
  cp "$JOBS_ABS/$EP/12_out/metrics.json" "$JOBS_ABS/$EP/12_out/metrics.$LANG.json"
  say "---- metrics 快照 → 12_out/metrics.$LANG.json"
done

# ---------------------------------------------------------------------------
# 6) 断言集
# ---------------------------------------------------------------------------
say "======== check_e2e ========"
"$PY" tests/check_e2e.py --ep "$EP" --langs "$LANGS" --src "$RAW_CLIP" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
say "======== e2e_smoke 结束: exit=$rc（langs=$LANGS lip=$([ "$LIP_UP" = 1 ] && echo on || echo SKIP-LIP)）========"
exit "$rc"
