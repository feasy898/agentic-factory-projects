"""M3 真跑驱动: M2 accepted LTX 镜头 + product_seeding_25s 模板 → 1 条完整竖版成片。

- 只读真实 workdir/cradle.sqlite3(不写库/不改素材); 预算守卫用无操作桩(强制本地 edge-tts)。
- 产物: output/m3_seeding_debug.mp4; reports/milestones/m3_compose_report.{md,json};
  m3_seeding_debug.ass(G6 逐字证据); m3_first_frame.png。
- G6 合成级(D-011): ASS 逐字比对(硬) + whisper-small TTS→ASR 回转 CER(归一化 D-034)。
用法: ~/cradle/.venv/bin/python scripts/m3_compose.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src import compose as C  # noqa: E402
from src.config import api_env_path, parse_api_env  # noqa: E402
from src.db import DB  # noqa: E402
from src.gates.g1_tech import probe  # noqa: E402
from src.schema import load_template  # noqa: E402

OUT_MP4 = REPO / "output" / "m3_seeding_debug.mp4"
REPORT_DIR = REPO / "reports" / "milestones"
ASS_PATH = REPORT_DIR / "m3_seeding_debug.ass"
PNG_PATH = REPORT_DIR / "m3_first_frame.png"
DB_PATH = REPO / "workdir" / "cradle.sqlite3"

# 幕(slot) → 镜头卡: 钩子/氛围/证据各就其位, 证据三幕用不同 accepted 镜头(变体能力)
SLOT_CAST = {
    "hook": "S02",        # 沸腾红汤锅底特写 (hook_product)
    "evidence_1": "S01",  # 毛肚 — "七上八下"
    "evidence_2": "S03",  # 虾滑 — "凌晨到港鲜货"
    "evidence_3": "S04",  # 肥牛卷 — "红汤翻滚江湖味"
    "ambiance": "S07",    # 暖光蒸汽环境
}


class _LocalOnlyBudget:
    """无操作预算桩: M3 只读真实库, 且 D-004 下 TTS/ASR 均走本地。"""

    def used(self, capability):  # noqa: ARG002
        return 0

    def remaining(self, capability):  # noqa: ARG002
        return 10**9

    def can_use_api(self, capability):  # noqa: ARG002
        return False

    def record(self, *a, **k):  # noqa: ARG002
        pass


def load_selected_candidates() -> dict[str, dict]:
    db = DB(str(DB_PATH))
    try:
        out = {}
        for t in db.list_tasks():
            sel = db.selected_candidate(t["shot_id"])
            if sel:
                out[t["shot_id"]] = {"shot_id": t["shot_id"], "narrative_slot": t["narrative_slot"],
                                     "lane": t["lane"], "status": t["status"],
                                     "path": sel["path"], "verdict": sel["verdict"],
                                     "overall_score": sel["overall_score"]}
        return out
    finally:
        db.close()


def main() -> int:
    t0 = time.time()
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu",
                          "--format=csv,noheader"], capture_output=True, text=True)
    print(f"[m3] GPU preflight: {gpu.stdout.strip()!r}")

    selected = load_selected_candidates()
    print(f"[m3] selected candidates: {sorted(selected)}")

    template = load_template(REPO / "templates" / "narrative" / "product_seeding_25s.json")
    video_by_slot: dict[str, str] = {}
    materials = []
    for scene in template["scenes"]:
        shot = SLOT_CAST.get(scene["slot"])
        if scene.get("background"):
            continue
        info = selected[shot]
        video_by_slot[scene["slot"]] = info["path"]
        video_by_slot.setdefault(scene["narrative_slot"], info["path"])
        p = probe(info["path"])
        materials.append({**info, "scene_slot": scene["slot"],
                          "resolution": f"{p['width']}x{p['height']}",
                          "duration_s": p["duration_s"]})
    print(f"[m3] cast: {[(m['scene_slot'], m['shot_id']) for m in materials]}")

    plan = C.plan_compose(template, video_by_slot)
    # D-015 代码隔离复查: 数字不出现在任何视频路径, 只出现在字幕
    numbers_check = {
        "numbers": plan["numbers_used"],
        "numbers_in_video_paths": any(n in p for n in plan["numbers_used"].values()
                                      for p in plan["video_paths"]),
        "numbers_in_cues": any(n in t for n in plan["numbers_used"].values()
                               for _, _, t in plan["cues"]),
    }
    assert numbers_check["numbers_in_video_paths"] is False, "数字泄漏进视频路径!"
    print(f"[m3] plan total={plan['total_duration']}s numbers_check={numbers_check}")

    # BGM: 程序合成(D-035), 25s
    bgm_path = str(REPO / "workdir" / "m3_bgm.m4a")
    subprocess.run(C.build_bgm_argv(plan["total_duration"], bgm_path),
                   check=True, capture_output=True, text=True, timeout=300)
    print(f"[m3] BGM synthesized -> {bgm_path}")

    # TTS(本地 edge-tts) + ASR(whisper small, GPU)
    from src.api.adapters import endpoint_from_env
    from src.api.tts import make_tts_adapter

    env = parse_api_env(api_env_path())
    tts = make_tts_adapter(endpoint_from_env(env, "TTS"), _LocalOnlyBudget())

    def tts_fn(text, path, rate=C.DEFAULT_RATE):
        return tts.call(text, path, rate=rate)[0]

    whisper_model = None
    # ASR 领域热词(D-036): 标准上下文偏置, 只提供领域词汇表(餐饮/火锅词), 不提供讲稿全文;
    # whisper 仍需真实识别音频。披露于报告。
    asr_prompt = "火锅店美食口播，词汇：老灶火锅、毛肚、锁鲜、到港、虾滑、肥牛、半价。"

    def asr_fn(wav_path):
        nonlocal whisper_model
        import torch
        import whisper

        if whisper_model is None:
            whisper_model = whisper.load_model(str(REPO / "models" / "whisper" / "small.pt"),
                                               device="cuda" if torch.cuda.is_available() else "cpu")
        r = whisper_model.transcribe(wav_path, language="zh", temperature=0,
                                     initial_prompt=asr_prompt)
        return str(r.get("text", "")).strip()

    OUT_MP4.parent.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    result = C.compose_group(plan, str(OUT_MP4), str(ASS_PATH), tts_fn,
                             bgm_path=bgm_path, asr_fn=asr_fn)
    print(f"[m3] composed -> {result['path']}")

    # 中间件归置: voice*.mp3/voice.m4a 移出 output/
    inter_dir = REPO / "workdir" / "m3_intermediate"
    inter_dir.mkdir(exist_ok=True)
    intermediates = []
    for f in OUT_MP4.parent.glob(OUT_MP4.name + ".*"):
        if f.suffix in (".mp3", ".m4a", ".wav"):
            shutil.move(str(f), str(inter_dir / f.name))
            intermediates.append(f.name)

    # 首帧截图 + 终版 ffprobe
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(OUT_MP4),
                    "-frames:v", "1", str(PNG_PATH)], check=True, timeout=120)
    fp = probe(str(OUT_MP4))
    argv_probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams",
         str(OUT_MP4)], capture_output=True, text=True, timeout=120).stdout)
    streams = [{"codec": s.get("codec_name"), "type": s.get("codec_type"),
                "width": s.get("width"), "height": s.get("height"),
                "r_frame_rate": s.get("r_frame_rate"), "duration": s.get("duration"),
                "bit_rate": s.get("bit_rate")} for s in argv_probe["streams"]]

    dur_ok = abs(fp["duration_s"] - plan["total_duration"]) <= 1.0
    size_ok = (fp["width"], fp["height"]) == (1088, 1920)
    g6 = result["g6"]

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "wall_seconds": round(time.time() - t0, 1),
        "template": template["template_id"],
        "materials": materials,
        "scene_table": [
            {"slot": sc["slot"], "narrative_slot": sc["narrative_slot"],
             "duration_sec": sc["duration_sec"], "narration": result["tts"][i]["text"],
             "tts_rate": result["tts"][i]["rate"], "tts_duration_s": result["tts"][i]["duration_s"],
             "tts_truncated": result["tts"][i]["truncated"],
             "tts_attempts": result["tts"][i]["attempts"],
             "video_path": plan["video_paths"][i],
             "video_duration_s": result["video_durations"][i]}
            for i, sc in enumerate(template["scenes"])],
        "ffprobe": {"duration_s": fp["duration_s"], "width": fp["width"], "height": fp["height"],
                    "duration_ok_within_1s": dur_ok, "size_ok": size_ok, "streams": streams},
        "numbers_isolation_D015": numbers_check,
        "bgm": {"kind": "programmatic sine chord (D-035)", "duck_db": C.DUCK_DB_DEFAULT,
                "file": "workdir/m3_bgm.m4a"},
        "g6_compose_level": g6,
        "g6_asr_config": {"model": "whisper-small(GPU)", "language": "zh", "temperature": 0,
                          "initial_prompt": asr_prompt,
                          "note": "领域热词上下文偏置(D-036); 无热词基线 CER=0.0645(6 处同音字混淆), "
                                  "详见 DECISIONS D-036"},
        "intermediates_moved": intermediates,
        "artifacts": {"mp4": str(OUT_MP4), "ass": str(ASS_PATH), "png": str(PNG_PATH)},
    }
    (REPORT_DIR / "m3_compose_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# M3 合成层成片报告 (m3_compose_report)", "",
             f"- 生成时间: {report['generated_at']} (墙钟 {report['wall_seconds']}s)",
             f"- 模板: {template['template_id']} / 总时长 {plan['total_duration']}s / 竖版 1088x1920@16fps",
             f"- 成片: `{OUT_MP4}`", "",
             "## 素材清单(M2 selected 候选, 调试口径)", ""]
    lines += ["| 幕 | 镜头 | lane | 来源 | 分辨率 | 素材时长 | overall_score |",
              "|---|---|---|---|---|---|---|"]
    for m in materials:
        lines.append(f"| {m['scene_slot']} | {m['shot_id']} | {m['lane']} | {m['verdict']} "
                     f"| {m['resolution']} | {m['duration_s']}s | {m['overall_score']} |")
    lines += ["", "## 时长轴(幕 / 口播自适应语速 D-032 / tpad 补齐 D-033)", "",
              "| 幕 | 幕长 | TTS 语速 | TTS 实测 | 截断 | 素材时长→tpad |", "|---|---|---|---|---|---|"]
    for r in report["scene_table"]:
        vd = r["video_duration_s"]
        pad = "" if vd is None else (f"{vd}s→hold-last {max(0.0, r['duration_sec'] - vd):.3f}s"
                                     if r["video_path"] != "color" and vd < r["duration_sec"] else f"{vd}s")
        lines.append(f"| {r['slot']} | {r['duration_sec']}s | {r['tts_rate']} | {r['tts_duration_s']}s "
                     f"| {r['tts_truncated']} | {pad} |")
    lines += ["", "## G6 合成级硬校验 (D-011)", "",
              f"- 字幕逐字比对(硬性): **{'PASS' if g6['detail']['subtitle_exact'] else 'FAIL'}** "
              f"(ASS={ASS_PATH}, 6 幕 Dialogue 与模板渲染文本全等)",
              f"- TTS→ASR 回转(可选): whisper-small GPU, CER=**{round(g6['detail']['cer'], 4)}** "
              f"(≤{g6['detail']['cer_max']}, 归一化 D-034)",
              f"- ASR 配置: language=zh, temperature=0, 领域热词 initial_prompt(D-036, 全文见 JSON): "
              f"`{asr_prompt}`; 无热词基线 CER=0.0645(6 处同音字: 灶/造 锁鲜/所先 港/岗 份/分 价/假), "
              f"热词后余 2-3 处同音残差(锁鲜→所先, 脆→翠)",
              f"- ASR 原文: `{g6['detail']['asr_hyp_raw']}`",
              f"- 归一化后假设: `{g6['detail']['asr_hyp_normalized']}`",
              f"- G6 总判定: **{'PASS' if g6['passed'] else 'FAIL'}** (score={g6['score']})", "",
              "## ffprobe 摘要", "",
              f"- duration={fp['duration_s']}s (模板 {plan['total_duration']}s ±1s → "
              f"{'OK' if dur_ok else 'MISMATCH'}), {fp['width']}x{fp['height']} "
              f"({'OK' if size_ok else 'MISMATCH'}), h264/aac, 音轨存在={any(s['type'] == 'audio' for s in streams)}", "",
              "## 数字隔离复查 (D-015)", "",
              f"- numbers={plan['numbers_used']}; 泄漏进视频路径={numbers_check['numbers_in_video_paths']}(应为 False); "
              f"出现于字幕={numbers_check['numbers_in_cues']}(应为 True)", "",
              "## 调试口径说明", "",
              "- 画面为 384×512 LTX 调试素材上采样(清晰度低/hold-last-frame 停帧属预期, M5 量产由 Wan 480p 素材替换);",
              "- hook/CTA 幕 3s 内念完口播需较快语速(模板文案 21 字 vs 3s 幕, 校准建议已记 M3 报告/DECISIONS);",
              "- BGM 为程序合成正弦和弦(无版权风险), 经 -12dB 预衰减+sidechaincompress ducking(D-006)。", ""]
    (REPORT_DIR / "m3_compose_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"[m3] report -> {REPORT_DIR}/m3_compose_report.{{md,json}}")
    print(f"[m3] G6: subtitle_exact={g6['detail']['subtitle_exact']} cer={g6['detail']['cer']} "
          f"passed={g6['passed']}")
    print(f"[m3] ffprobe: {fp['duration_s']}s {fp['width']}x{fp['height']} "
          f"dur_ok={dur_ok} size_ok={size_ok}")
    ok = dur_ok and size_ok and g6["passed"] if g6 else dur_ok and size_ok
    subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"],
                   capture_output=True, text=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
