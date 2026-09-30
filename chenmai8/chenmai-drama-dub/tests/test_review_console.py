"""M13 审校台 eval（规划 §4 M13；任务 T19 自验收口径）。

冻结 eval 命令（本批验收入口）::

    pytest tests/test_review_console.py        # 离线路径全绿为准

端到端（任务 T19 验收序，全离线零 GPU）::
    创建任务 → 逐句表格 → 改一句译文（回写 C4）→ 单句重生成状态机
    （M8 重对齐 → M7 重合成（force-mock 占位，注明）→ M9 重混）
    → 导出（MP4/SRT/C8 合规报告）→ 产物下载 200。

覆盖面：
  ① e2e 主链：任务创建幂等；改一句 → C4 chosen/候选更新（src=review-console
     审计口径）→ regenerate 三阶段 trace（m8-align/m7-synth/m9-mix）全 ok、
     状态机 idle→edited→aligned→synthesized→ready、C5 行同步、**该句 wav
     波形哈希变化且其余句 wav 逐字节不变**（重生成两次对比预览切片）、
     mock 占位在响应/状态机中如实注明（synth_mode="mock"）；
  ② 导出：MP4 成片存在（M9 compose）+ SRT 含改后译文（跳过句如实列出）
     + C8 合规报告契约强校验（implicit=ok 对成片 ffprobe 实测，
     explicit/c2pa/audio_wm=pending 不伪造，human_review=审校句）+
     文件下载 200（mp4/srt/json）；句窗 wav 预览与 mp4 片段预览 200；
  ③ 术语表：terms_seed CRUD（PUT/GET/DELETE）+ M6 单句重翻注入
     （新术语在**全部候选** 100% 命中；删除后回落词典口径）；
  ④ 状态机旁路：keep-original 句合成跳过（wav 不动）；M9 前置缺失
     → 500 + 行状态 error + 流水留痕；
  ⑤ 校验/404：空译文/越界 chosen/未知任务句/非法集 ID/未登记语种/
     C2 缺失建任务均拒绝；
  ⑥ 并发 5 请求（GET/PUT 混合）无锁死（SQLite WAL+锁串行化）；
  ⑦ UI 单页可达（原生 JS，无构建链）。

GPU 用例（skip-gpu 注明）：真 :9002 合成用例在 GPU tts 服务不可达时
整组 skip，skip reason 含「服务不可达（tts/:9002）」——归因口径同
tests/test_m7_tts.py（门禁 --skip-gpu 豁免按此归因）；离线用例一律
``tts="force-mock"``，不探测不依赖 :9002。

素材口径：合成样片（7s 1080x1920@25fps 纯色视频 + 48k 稳态 bgm +
三句 C2 语料走真 M6 mock 后端/M8 全集引导产出 C4/C5 + 占位合成 wav +
M11 装配器 en ASS + C7 labels），与 test_m9 同款构造，全离线确定性。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import numpy as np
import pytest
import soundfile as sf

from pipeline import contracts as C
from pipeline import m11_subs as M11
from pipeline import review_server as RS
from pipeline.config import load_pipeline_config
from pipeline.contracts import make_utt_id
from pipeline.m6_translate import translate_episode
from pipeline.m8_align import align_episode
from pipeline.mt_backends import MockMtBackend
from pipeline.scaffold import create_workspace
from pipeline.tts_client import SERVICE_ENV, TtsClient, TtsError

EP = "epm13"
LANG = "en"
MASTER_DUR = 7.0
SR = 48000

#: 语料（utt_id 用冻结公式；文本全部落在 mock 词典覆盖面内，离线确定）
LINES: list[tuple[float, float, str, str]] = [
    (0.8, 2.2, "char_a", "你到底想怎么样？把话说清楚。"),
    (3.0, 5.0, "char_b", "三年了，程氏的项目、老城的基地，哪一样不是我亲手做起来的？"),
    (5.4, 6.2, "char_a", "那你就可以这样对我吗！"),
]
U0, U1, U2 = (make_utt_id(EP, s) for s, _e, _c, _t in LINES)
BGM_FREQ = 150.0

#: C7 labels（同 test_m9 口径，自填具体值供隐式标识精确回读）
LABELS = {
    "service_provider": "澄迈短剧出海测试",
    "content_id": f"{EP}-{LANG}",
    "standard": "GB45438-2025",
    "explicit": {"text": "本内容由AI生成", "video": "片头提示字幕≥3s",
                 "audio_announce": False},
    "implicit": {"metadata_field": "XMP:aiGeneratedContent",
                 "value": f"{EP}-{LANG}|澄迈短剧出海测试"},
    "c2pa": "11_labels/c2pa_manifest.json",
    "audio_wm": {"engine": "audmark", "payload": f"{EP}-{LANG}", "bits": 16},
}
LABEL_FIELD = LABELS["implicit"]["metadata_field"]
LABEL_VALUE = LABELS["implicit"]["value"]

EDIT_A = "Three years. Which of these did I not build?"
EDIT_B = "Three years now. Which one was not built by me?"

SERVICE_URL = os.environ.get(SERVICE_ENV[0], SERVICE_ENV[1])


# ---------------------------------------------------------------------------
# 素材构造（确定性；同输入恒同输出）
# ---------------------------------------------------------------------------

def _tone(freq: float, dur: float, sr: int, amp: float = 0.2) -> np.ndarray:
    n = int(round(dur * sr))
    return amp * np.sin(2 * np.pi * freq * np.arange(n) / sr)


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _video_name() -> str:
    media = {**{"width": 1080, "height": 1920, "fps": 25},
             **(load_pipeline_config().get("media") or {})}
    return f"video_{int(media['width'])}x{int(media['height'])}_{int(media['fps'])}fps.mp4"


def _make_base_video(dst: Path) -> Path:
    """会话级基带视频（只编码一次；lens 纯色源，M9 自己烧 ASS）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i",
         f"color=c=0x101820:size=1080x1920:rate=25:duration={MASTER_DUR}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
         "-crf", "28", str(dst)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600,
    )
    assert r.returncode == 0, r.stderr[-500:]
    return dst


def build_workspace(jobs: Path, base_video: Path) -> Path:
    """建 ep 工作区：C2 → 真 M6(mock) 产 C4/C3 → 真 M8 产 C5 → 占位 wav
    + bgm + 基带视频 + en ASS + C7 labels（全离线确定性）。"""
    create_workspace(EP, jobs)
    root = jobs / EP

    utts = [
        C.Utterance(utt_id=make_utt_id(EP, s), shot_id="s0000", start=s,
                    end=e, lang="zh", speaker="spk0", char_id=cid, text=t)
        for s, e, cid, t in LINES
    ]
    C.dump_jsonl(root / "04_dial" / "utterances.jsonl",
                 C.UtteranceTable.model_validate(utts))

    # 真 M6（mock 后端）→ context.json + C3 暂定卡 + C4
    translate_episode(EP, LANG, MockMtBackend(), jobs_dir=jobs,
                      lo_ratio=0.9, hi_ratio=1.1)

    # 真 M8 全集引导 → C5（synth_plan.en.jsonl + 无后缀副本 + 对齐报告）
    align_episode(EP, LANG, jobs_dir=jobs)

    # 角色音色参考（真 :9002 在线用例的前置；离线用例不依赖）
    vb = root / "05_cast" / "voicebank"
    vb.mkdir(parents=True, exist_ok=True)
    for i, cid in enumerate(("char_a", "char_b")):
        sf.write(str(vb / f"{cid}_ref.wav"),
                 _tone(260.0 + 60.0 * i, 0.8, 16000).astype(np.float32),
                 16000, subtype="PCM_16")

    # 占位合成 wav（每句窗长单音；重生成会替换目标句）
    wavs = root / "07_synth" / "wavs"
    wavs.mkdir(parents=True, exist_ok=True)
    for i, (s, e, _cid, _t) in enumerate(LINES):
        uid = make_utt_id(EP, s)
        sf.write(str(wavs / f"{uid}.wav"),
                 _tone(400.0 + 80.0 * i, e - s, SR).astype(np.float32),
                 SR, subtype="PCM_16")

    # bgm（48k 立体声稳态）+ 基带视频
    bgm = _tone(BGM_FREQ, MASTER_DUR, SR, amp=0.1)
    sf.write(str(root / "01_media" / "bgm.wav"),
             np.stack([bgm, bgm], axis=1).astype(np.float32), SR,
             subtype="PCM_16")
    shutil.copyfile(base_video, root / "01_media" / _video_name())

    # 目标语 ASS（复用 M11 装配器，样式逻辑单一来源）
    events = [M11.AssEvent(start=s, end=e, text=f"line {i + 1}")
              for i, (s, e, _cid, _t) in enumerate(LINES)]
    style, _font = M11.style_for_lang(load_pipeline_config(), LANG)
    (root / "10_subs" / f"tgt.{LANG}.ass").write_text(
        M11.build_ass(events, style=style), encoding="utf-8")

    # C7 labels.json
    (root / "11_labels" / "labels.json").write_text(
        json.dumps(LABELS, ensure_ascii=False, indent=1), encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def base_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _make_base_video(
        tmp_path_factory.mktemp("m13_base") / _video_name())


@pytest.fixture()
def env(tmp_path: Path, base_video: Path):
    """每测试独立 workspace + 独立 SQLite + ASGI 应用（httpx AsyncClient）。"""
    jobs = tmp_path / "jobs"
    root = build_workspace(jobs, base_video)
    app = RS.create_app(jobs, db_path=jobs / "review.db")
    return {"jobs": jobs, "root": root, "app": app}


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://testserver")


def _call(app, method: str, url: str, **kw) -> httpx.Response:
    """单请求同步包装（每调用独立事件循环；app 状态在 SQLite/文件，跨调用保持）。"""
    async def _go():
        async with _client(app) as ac:
            return await ac.request(method, url, **kw)
    return asyncio.run(_go())


def _create_task(env) -> int:
    r = _call(env["app"], "POST", "/api/tasks",
              json={"ep": EP, "lang": LANG})
    assert r.status_code == 200, r.text
    return int(r.json()["task"]["id"])


# ---------------------------------------------------------------------------
# ① 端到端主链（任务 T19 验收序）
# ---------------------------------------------------------------------------

def test_e2e_create_edit_regenerate_export(env) -> None:
    app, root = env["app"], env["root"]
    wavs = root / "07_synth" / "wavs"

    # ---- 创建任务（幂等） ----
    r = _call(app, "POST", "/api/tasks", json={"ep": EP, "lang": LANG})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    tid = int(body["task"]["id"])
    r2 = _call(app, "POST", "/api/tasks", json={"ep": EP, "lang": LANG})
    assert r2.status_code == 200 and r2.json()["created"] is False
    assert int(r2.json()["task"]["id"]) == tid

    # ---- 逐句表格：C4 候选 + 预算 + 实测 ----
    r = _call(app, "GET", f"/api/tasks/{tid}/lines")
    assert r.status_code == 200
    lines = {ln["utt_id"]: ln for ln in r.json()["lines"]}
    assert set(lines) == {U0, U1, U2}
    ln1 = lines[U1]
    assert ln1["budget"]["orig_dur"] == 2.0
    assert ln1["budget"]["lo"] == 1.8 and ln1["budget"]["hi"] == 2.2
    assert ln1["candidates"], "M6 mock 应产出候选"
    for c in ln1["candidates"]:
        assert set(c) >= {"text", "syl", "est_dur", "src", "q"}
    assert ln1["meas_dur"] == 2.0 and ln1["in_window"] is True
    assert ln1["state"] == "idle"

    # ---- 改一句（回写 C4；逐句 wav 基线） ----
    before = {u: _sha(wavs / f"{u}.wav") for u in (U0, U1, U2)}
    r = _call(app, "PUT", f"/api/tasks/{tid}/lines/{U1}/translation",
              json={"text": EDIT_A})
    assert r.status_code == 200, r.text
    ln = r.json()
    assert ln["state"] == "edited" and ln["chosen_text"] == EDIT_A
    assert ln["candidates"][ln["chosen_idx"]]["src"] == RS.EDIT_SRC
    assert ln["candidates"][ln["chosen_idx"]]["est_dur"] == pytest.approx(2.5, abs=0.01)
    # C4 落盘核验（chosen 与审计来源）
    c4 = {row.utt_id: row for row in C.load_jsonl(
        root / "06_mt" / "translations.jsonl", C.TranslationTable).root}
    assert c4[U1].candidates[c4[U1].chosen].text == EDIT_A

    # ---- 重生成 #1（M8→M7(mock 注明)→M9；force-mock=离线确定性口径） ----
    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U1}/regenerate",
              json={"tts": "force-mock"})
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["ok"] is True and reg["state"] == "ready"
    assert reg["synth_mode"] == "mock" and reg["mock"] is True
    assert [t["stage"] for t in reg["trace"]] == ["m8-align", "m7-synth", "m9-mix"]
    assert reg["trace"][1]["detail"]["reason"].startswith("请求显式 force-mock")
    # M8：单候选二分落窗（est 2.5s → df≈0.8 → pred 2.0 ∈ [1.8,2.2]）
    d8 = reg["trace"][0]["detail"]
    assert d8["window"] == [1.8, 2.2] and 1.8 <= d8["pred_dur"] <= 2.2
    # C5 行同步
    c5 = {i.utt_id: i for i in C.load_jsonl(
        root / "07_synth" / f"synth_plan.{LANG}.jsonl", C.SynthPlanTable).root}
    assert c5[U1].text == EDIT_A and c5[U1].expect_dur == d8["pred_dur"]
    # 该句 wav 变、其余句逐字节不变
    after1 = {u: _sha(wavs / f"{u}.wav") for u in (U0, U1, U2)}
    assert after1[U1] != before[U1]
    assert after1[U0] == before[U0] and after1[U2] == before[U2]
    # M9 产物就位
    assert (root / "08_mix" / "dubbed.en.wav").is_file()
    assert (root / "08_mix" / "mix.en.wav").is_file()
    assert (root / "12_out" / f"{EP}.{LANG}.mp4").is_file()
    # 状态机流水
    r = _call(app, "GET", f"/api/tasks/{tid}/regens?utt_id={U1}")
    stages = [(x["stage"], x["from_state"], x["to_state"]) for x in r.json()]
    assert stages[:3] == [("m8-align", "edited", "aligned"),
                          ("m7-synth", "aligned", "synthesized"),
                          ("m9-mix", "synthesized", "ready")]
    # 预览基线（句窗切片 wav）
    r = _call(app, "GET", f"/api/tasks/{tid}/lines/{U1}/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    preview_a = r.content
    assert len(preview_a) > 44

    # ---- 改另一版译文 → 重生成 #2：该句音频变化、其余句仍不变 ----
    r = _call(app, "PUT", f"/api/tasks/{tid}/lines/{U1}/translation",
              json={"text": EDIT_B})
    assert r.status_code == 200
    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U1}/regenerate",
              json={"tts": "force-mock"})
    assert r.status_code == 200 and r.json()["ok"] is True
    after2 = {u: _sha(wavs / f"{u}.wav") for u in (U0, U1, U2)}
    assert after2[U1] not in (before[U1], after1[U1]), "重生成后该句波形须变"
    assert after2[U0] == before[U0] and after2[U2] == before[U2]
    r = _call(app, "GET", f"/api/tasks/{tid}/lines/{U1}/preview")
    assert r.status_code == 200 and r.content != preview_a

    # ---- 导出（MP4/SRT/C8）+ 下载 200 ----
    r = _call(app, "POST", f"/api/tasks/{tid}/export", json={})
    assert r.status_code == 200, r.text
    art = r.json()["artifacts"]
    assert art["mp4"]["exists"] is True
    assert art["srt"]["exists"] is True
    assert EDIT_B in (root / "12_out" / f"{EP}.{LANG}.srt").read_text(encoding="utf-8")
    comp = json.loads((root / "12_out" / f"compliance.{LANG}.json").read_text("utf-8"))
    C.ComplianceReport.model_validate(comp)  # C8 契约强校验
    assert comp["label_status"]["implicit"] == "ok"   # 成片 ffprobe 实测
    assert comp["label_status"]["explicit"] == "pending"  # M12 未部署不伪造
    assert U1 in comp["human_review"]
    r = _call(app, "GET", f"/api/tasks/{tid}/export/files")
    names = {f["name"] for f in r.json()}
    assert names == {f"{EP}.{LANG}.mp4", f"{EP}.{LANG}.srt",
                     f"compliance.{LANG}.json"}
    for name, mime in ((f"{EP}.{LANG}.mp4", "video/mp4"),
                       (f"{EP}.{LANG}.srt", "application/x-subrip"),
                       (f"compliance.{LANG}.json", "application/json")):
        r = _call(app, "GET", f"/api/tasks/{tid}/files/{name}")
        assert r.status_code == 200, (name, r.text)
        assert r.headers["content-type"].startswith(mime)

    # 片段预览（成片句窗切段）与整片
    r = _call(app, "GET", f"/api/tasks/{tid}/lines/{U1}/clip")
    assert r.status_code == 200 and \
        r.headers["content-type"].startswith("video/mp4")
    r = _call(app, "GET", f"/api/tasks/{tid}/video")
    assert r.status_code == 200

    # 任务态收敛
    task = _call(app, "GET", f"/api/tasks/{tid}").json()
    assert task["state"] == "exported" and task["n_regens"] >= 6


def test_line_table_metrics(env) -> None:
    app = env["app"]
    tid = _create_task(env)
    r = _call(app, "GET", f"/api/tasks/{tid}/lines")
    assert r.status_code == 200
    body = r.json()
    assert body["states"]["idle"] == 3
    for ln in body["lines"]:
        orig = ln["budget"]["orig_dur"]
        assert ln["budget"]["lo"] == pytest.approx(orig * 0.9, abs=1e-3)
        assert ln["budget"]["hi"] == pytest.approx(orig * 1.1, abs=1e-3)
        assert ln["c5"] is not None and "expect_dur" in ln["c5"]
        assert ln["meas_dur"] is not None
        assert ln["in_window"] == (ln["budget"]["lo"] <= ln["meas_dur"]
                                   <= ln["budget"]["hi"])


# ---------------------------------------------------------------------------
# ③ 术语表 CRUD + M6 单句重翻注入
# ---------------------------------------------------------------------------

def test_glossary_crud_and_m6_injection(env) -> None:
    app, root = env["app"], env["root"]
    tid = _create_task(env)

    # 基线：词典口径（程氏→the Cheng family）
    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U1}/retranslate",
              json={"backend": "mock"})
    assert r.status_code == 200, r.text
    assert "the Cheng family" in r.json()["line"]["chosen_text"]

    # PUT 术语 → 生效表含种子；重翻后**全部候选** 100% 用新术语
    r = _call(app, "PUT", f"/api/tasks/{tid}/glossary/{'程氏'}",
              json={"tgt": "the Cheng clan"})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["seed"]["程氏"][LANG] == "the Cheng clan"
    assert g["effective"]["程氏"] == "the Cheng clan"
    # 种子落盘（M6 术语种子同源格式与路径）
    seed = json.loads((root / "06_mt" / "terms_seed.json").read_text("utf-8"))
    assert seed["程氏"] == {LANG: "the Cheng clan"}

    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U1}/retranslate",
              json={"backend": "mock"})
    body = r.json()
    assert body["terms_injected"]["程氏"] == "the Cheng clan"
    cands = body["line"]["candidates"]
    assert cands and all("the Cheng clan" in c["text"] for c in cands)
    assert "the Cheng clan" in body["line"]["chosen_text"]
    # C4 落盘同步 + 行状态
    c4 = {row.utt_id: row for row in C.load_jsonl(
        root / "06_mt" / "translations.jsonl", C.TranslationTable).root}
    assert all("the Cheng clan" in c.text for c in c4[U1].candidates)
    assert _call(app, "GET", f"/api/tasks/{tid}/lines/{U1}").json()["state"] == "edited"

    # DELETE 术语 → 回落词典口径
    r = _call(app, "DELETE", f"/api/tasks/{tid}/glossary/{'程氏'}")
    assert r.status_code == 200
    assert "程氏" not in r.json()["seed"]
    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U1}/retranslate",
              json={"backend": "mock"})
    assert "the Cheng clan" not in r.json()["line"]["chosen_text"]
    # 删不存在的语种译法 → 404；空源术语 → 400
    assert _call(app, "DELETE",
                 f"/api/tasks/{tid}/glossary/{'程氏'}").status_code == 404
    assert _call(app, "PUT", f"/api/tasks/{tid}/glossary/{'  '}",
                 json={"tgt": "x"}).status_code == 400


# ---------------------------------------------------------------------------
# ④ 状态机旁路：keep-original 跳过合成 / 失败留痕
# ---------------------------------------------------------------------------

def test_keep_original_skips_synth(env) -> None:
    app, root = env["app"], env["root"]
    tid = _create_task(env)
    # u2 改写 C5 为 keep_original（nonverbal 口径）后单跑 m7
    plan_path = root / "07_synth" / f"synth_plan.{LANG}.jsonl"
    rows = {i.utt_id: i for i in C.load_jsonl(plan_path, C.SynthPlanTable).root}
    old = rows[U2].model_dump()
    old["keep_original"] = True
    C.upsert_jsonl(plan_path, [C.SynthPlanItem(**old)],
                   container=C.SynthPlanTable, key_field="utt_id")
    wav = root / "07_synth" / "wavs" / f"{U2}.wav"
    h0 = _sha(wav)
    _call(app, "PUT", f"/api/tasks/{tid}/lines/{U2}/translation",
          json={"text": "then you can treat me like this"})
    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U2}/regenerate",
              json={"stages": ["m7"], "tts": "force-mock"})
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["synth_mode"] == "keep-original" and reg["state"] == "synthesized"
    assert "keep_original" in reg["trace"][0]["detail"]["reason"]
    assert _sha(wav) == h0, "keep-original 句不得触碰合成 wav"


def test_regen_error_recorded(env) -> None:
    app, root = env["app"], env["root"]
    tid = _create_task(env)
    (root / "01_media" / "bgm.wav").unlink()  # M9 前置缺失 → m9 阶段必败
    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U0}/regenerate",
              json={"stages": ["m9"]})
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert detail["ok"] is False and "M3 背景轨不存在" in detail["error"]
    line = _call(app, "GET", f"/api/tasks/{tid}/lines/{U0}").json()
    assert line["state"] == "error"
    regens = _call(app, "GET",
                   f"/api/tasks/{tid}/regens?utt_id={U0}").json()
    assert any(x["stage"] == "error" and x["ok"] == 0 for x in regens)
    # 失败后恢复前置 → 同句可重生成回来（error 不是终态）
    bgm = _tone(BGM_FREQ, MASTER_DUR, SR, amp=0.1)
    sf.write(str(root / "01_media" / "bgm.wav"),
             np.stack([bgm, bgm], axis=1).astype(np.float32), SR,
             subtype="PCM_16")
    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U0}/regenerate",
              json={"tts": "force-mock"})
    assert r.status_code == 200 and r.json()["state"] == "ready"


# ---------------------------------------------------------------------------
# ⑤ 校验与 404
# ---------------------------------------------------------------------------

def test_validation_and_404(env) -> None:
    app = env["app"]
    tid = _create_task(env)
    assert _call(app, "PUT", f"/api/tasks/{tid}/lines/{U1}/translation",
                 json={"text": "   "}).status_code == 400
    assert _call(app, "PUT", f"/api/tasks/{tid}/lines/{U1}/translation",
                 json={}).status_code == 400
    assert _call(app, "PUT", f"/api/tasks/{tid}/lines/{U1}/translation",
                 json={"chosen_idx": 99}).status_code == 400
    assert _call(app, "GET", "/api/tasks/999").status_code == 404
    assert _call(app, "GET",
                 f"/api/tasks/{tid}/lines/nope").status_code == 404
    assert _call(app, "POST", f"/api/tasks/{tid}/lines/{U1}/regenerate",
                 json={"stages": ["bogus"]}).status_code == 400
    assert _call(app, "POST", f"/api/tasks/{tid}/lines/{U1}/regenerate",
                 json={"tts": "warp"}).status_code == 400
    # 非法集 ID / 未登记语种 / C2 缺失
    assert _call(app, "POST", "/api/tasks",
                 json={"ep": "../x", "lang": "en"}).status_code == 400
    assert _call(app, "POST", "/api/tasks",
                 json={"ep": EP, "lang": "fr"}).status_code == 400
    assert _call(app, "POST", "/api/tasks",
                 json={"ep": "ep_ghost", "lang": "en"}).status_code == 400
    # 下载白名单
    assert _call(app, "GET",
                 f"/api/tasks/{tid}/files/..%2Freview.db").status_code in (400, 404)
    # 导出文件清单在导出前为空
    assert _call(app, "GET",
                 f"/api/tasks/{tid}/export/files").status_code == 200


# ---------------------------------------------------------------------------
# ⑥ 并发 5 请求无锁死（SQLite WAL + 线程锁串行化）
# ---------------------------------------------------------------------------

def test_concurrent_requests_no_deadlock(env) -> None:
    app = env["app"]

    async def run() -> None:
        async with _client(app) as ac:
            tid_resp = await ac.post("/api/tasks",
                                     json={"ep": EP, "lang": LANG})
            tid = int(tid_resp.json()["task"]["id"])

            async def one(i: int) -> httpx.Response:
                if i == 0:
                    return await ac.put(
                        f"/api/tasks/{tid}/lines/{U1}/translation",
                        json={"text": f"concurrent variant {i}"})
                if i % 2 == 1:
                    return await ac.get(f"/api/tasks/{tid}/lines")
                return await ac.get(f"/api/tasks/{tid}/glossary")

            rs = await asyncio.wait_for(
                asyncio.gather(*[one(i) for i in range(5)]), timeout=60)
        assert all(r.status_code == 200 for r in rs), \
            [r.status_code for r in rs]

    asyncio.run(run())


# ---------------------------------------------------------------------------
# ⑦ UI 单页（原生 JS，无构建链）
# ---------------------------------------------------------------------------

def test_ui_page(env) -> None:
    r = _call(env["app"], "GET", "/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    for needle in ("审校台", "/api/tasks", "重生成", "术语表", "导出"):
        assert needle in r.text


# ---------------------------------------------------------------------------
# GPU 在线用例（服务不可达整组 skip，skip-gpu 归因同 test_m7 口径）
# ---------------------------------------------------------------------------

def _service_up() -> bool:
    try:
        h = TtsClient(SERVICE_URL, timeout=5.0, retries=0).health()
        return bool(h.get("loaded", {}).get("dub-tts"))
    except TtsError:
        return False


@pytest.fixture()
def gpu_service():
    if not _service_up():
        pytest.skip(
            "skip-gpu: GPU tts 服务不可达（tts/:9002，隧道未启动或远端下线）——"
            "离线路径不受影响；归因口径同 tests/test_m7_tts.py（gate --skip-gpu 豁免）"
        )
    return True


def test_regenerate_real_tts_online(env, gpu_service) -> None:
    """真 :9002 合成回路：synth_mode=tts-gpu、mock=false、wav 实测>0。"""
    app, root = env["app"], env["root"]
    tid = _create_task(env)
    wav = root / "07_synth" / "wavs" / f"{U0}.wav"
    h0 = _sha(wav)
    _call(app, "PUT", f"/api/tasks/{tid}/lines/{U0}/translation",
          json={"text": "what is it that you really want say it out loud"})
    r = _call(app, "POST", f"/api/tasks/{tid}/lines/{U0}/regenerate",
              json={"tts": "auto", "stages": ["m8", "m7"]})
    assert r.status_code == 200, r.text
    reg = r.json()
    assert reg["ok"] is True and reg["state"] == "synthesized"
    assert reg["synth_mode"] == "tts-gpu" and reg["mock"] is False
    d7 = reg["trace"][1]["detail"]
    assert d7["reason"].startswith("真 :9002 合成")
    assert reg["meas_dur"] > 0 and _sha(wav) != h0
    info = sf.info(str(wav))
    assert abs(info.frames / info.samplerate - reg["meas_dur"]) < 0.05
