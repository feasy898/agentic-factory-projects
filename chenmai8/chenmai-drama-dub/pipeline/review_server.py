"""M13 审校台 Web（规划 §4 M13；任务 T19）—— FastAPI + SQLite + 原生 JS 单页。

定位：内网人工审校工作台（无鉴权，规划口径），消费已产出的上游契约
（C2 逐句事实表 / C4 译文候选 / C5 合成计划 / 08_mix 音轨 / 12_out 成片），
四组功能（对应任务 T19 验收面）：

  ① 逐句表格 —— ``GET /api/tasks/{tid}/lines``：C4 译文与候选
     (text/syl/est_dur/q) + 时长预算 (C4.budget lo/hi) + **实测时长**
     （07_synth/wavs 逐文件 soundfile 实测，落窗判定）+ 审校状态机列；
  ② 单句重生成回路 —— ``PUT .../translation``（改译文，回写 C4）→
     ``POST .../regenerate``：M8 单句重对齐（复算 C5 计划行）→ M7 重合成
     （``:9002`` 经 M7_TTS_URL 探测，**隧道不可达时 mock 占位音频生成并在
     状态机/响应中如实注明**，mock 波形以译文哈希为种子、文本变则波形变）
     → M9 重混（整集 ducking+响度+成片）→ 片段预览（句窗切片 wav / 成片
     mp4 切段）；另有 ``POST .../retranslate`` 走 M6 单句重翻（术语注入）；
  ③ 术语表管理 —— ``06_mt/terms_seed.json`` CRUD（M6 术语种子同源格式
     ``{"源术语": {"语种": "译法"}}``），有效术语 = C3 terms[lang] ∪ 种子
     （复用 m6.build_glossary，M6 上下文注入同一实现）；
  ④ 导出 —— MP4（12_out 成片，缺则触发 M9 compose）+ 字幕 SRT
     （C2 句窗 × C4 chosen）+ 合规报告 C8 ``compliance.<lang>.json``
     （findings 由 M12 规则引擎产出，未接入前留空并如实注明）。

状态机（SQLite ``lines.state``，逐句）::

    idle → edited（改译/重翻）→ aligned（M8）→ synthesized（M7）
         → mixed→ready（M9）；任一步失败 → error（detail 留痕）。
    每步转移写 ``regens`` 流水（stage/from_state/to_state/ok/detail）。

并发与安全：
  - SQLite 单连接 + 线程锁串行化 DB 访问，WAL + busy_timeout（并发请求
    不锁死）；重生成按 (ep,lang) 任务级锁串行（同集重混互斥，异集并行），
    计算在锁外；
  - SQL 一律参数绑定（? 占位），ep 经 :func:`pipeline.scaffold.ep_dir`
    白名单校验，文件下载仅限 12_out 白名单文件名。

CLI（规划 §4 M13 冻结形态）::

    python -m pipeline.review_server --jobs jobs --port 8080
    python -m pipeline.review_server --jobs jobs --db <path> --host 0.0.0.0

自验收：``pytest tests/test_review_console.py``（httpx ASGI 端到端：
创建任务→改一句→重生成状态机→导出 200；离线路径全绿，GPU 真合成用例
在 ``:9002`` 不可达时整组 skip 并注明 skip-gpu 归因）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from pipeline import contracts as C
from pipeline import m9_mix as M9
from pipeline.config import load_pipeline_config
from pipeline.m1_ingest import FFMPEG, FFPROBE
from pipeline.m6_translate import (
    CTX_WINDOW,
    _upsert_translations,
    budget_for,
    build_cast_summary_text,
    build_glossary,
    char_id_for,
    count_syllables,
    estimate_dur_s,
    load_syl_table,
)
from pipeline.m8_align import AlignParams, align_utterance, params_from_cfg
from pipeline.mt_backends import MTBackend, MTContext, make_backend
from pipeline.scaffold import create_workspace, ep_dir
from pipeline.tts_client import SERVICE_ENV, TtsClient, TtsError

__all__ = [
    "ReviewStore",
    "create_app",
    "main",
]

#: 支持的目标语（与 M9 同口径）
SUPPORTED_LANGS = M9.SUPPORTED_LANGS
#: 状态机全序（error 为旁路终态，可经重生成恢复）
LINE_STATES = ("idle", "edited", "aligned", "synthesized", "mixed", "ready", "error")
#: 重生成阶段 → 落定状态（顺序固定 m8→m7→m9）
REGEN_STAGES = ("m8", "m7", "m9")
_STAGE_STATE = {"m8": "aligned", "m7": "synthesized", "m9": "ready"}
_STAGE_NAME = {"m8": "m8-align", "m7": "m7-synth", "m9": "m9-mix"}
#: 单句重生成耗时目标（规划 §4 M13：≤60s 返回；实测随语料/负载浮动，只记录不硬门）
REGEN_TARGET_S = 60.0
#: mock 占位音频口径（注明用）：采样率与生成幅度
MOCK_SR = 22050
MOCK_AMP = 0.3
#: 片段预览句窗外扩（秒）
PREVIEW_PAD_S = 0.25
#: 真合成探测/调用超时（探测要短，调用给足首载余量）
TTS_PROBE_TIMEOUT_S = 3.0
TTS_SYNTH_TIMEOUT_S = 240.0
#: 审校台编辑产物的候选来源标记（审计口径：人改过的候选与机器候选可区分）
EDIT_SRC = "review-console"
#: 导出文件名白名单（12_out 内允许下载的名字模式）
_EXPORT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _now() -> str:
    """UTC ISO 时间戳（审计列）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 工作区文件读写的并发安全（Windows 实测竞态：契约原子写 os.replace 与
# 并发 open() 读之间有毫秒级窗口，读侧偶发 PermissionError/Errno 13；
# 审校台是并发服务，所有契约文件 I/O 统一经 fs_retry 小退避重试）
# ---------------------------------------------------------------------------

_FS_RETRY = 6
_FS_RETRY_WAIT_S = 0.05

#: 只重试瞬时竞态（PermissionError）；FileNotFoundError 是「产物不存在」的
#: 合法语义，由调用方按缺省兜底，绝不重试伪装。


def fs_retry(fn, *args, **kw):
    """毫秒级竞态窗口的小退避重试（重试耗尽后如实抛出最后一次异常）。"""
    last: Optional[BaseException] = None
    for i in range(_FS_RETRY):
        try:
            return fn(*args, **kw)
        except PermissionError as exc:
            last = exc
            time.sleep(_FS_RETRY_WAIT_S * (i + 1))
    assert last is not None
    raise last


# ---------------------------------------------------------------------------
# SQLite 存取（单连接 + 线程锁；SQL 全参数绑定）
# ---------------------------------------------------------------------------

class ReviewStore:
    """审校台 SQLite 存储（任务/逐句状态机/重生成流水）。

    单连接（``check_same_thread=False``）+ 可重入锁串行化全部 DB 操作；
    WAL + busy_timeout 保证读并发不阻塞。schema 只增不改名。
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None

    # -- 连接与 schema ----------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(
                    str(self.db_path), check_same_thread=False, timeout=30.0
                )
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA synchronous=NORMAL")
                self._conn = conn
                self._init_schema(conn)
            return self._conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              ep         TEXT NOT NULL,
              lang       TEXT NOT NULL,
              state      TEXT NOT NULL DEFAULT 'open',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(ep, lang)
            );
            CREATE TABLE IF NOT EXISTS lines (
              task_id      INTEGER NOT NULL REFERENCES tasks(id),
              utt_id       TEXT NOT NULL,
              state        TEXT NOT NULL DEFAULT 'idle',
              synth_mode   TEXT,
              measured_dur REAL,
              detail       TEXT,
              updated_at   TEXT NOT NULL,
              PRIMARY KEY (task_id, utt_id)
            );
            CREATE TABLE IF NOT EXISTS regens (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id    INTEGER NOT NULL REFERENCES tasks(id),
              utt_id     TEXT NOT NULL,
              stage      TEXT NOT NULL,
              from_state TEXT NOT NULL,
              to_state   TEXT NOT NULL,
              ok         INTEGER NOT NULL,
              detail     TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        conn.commit()

    # -- 任务 --------------------------------------------------------------

    def create_task(self, ep: str, lang: str) -> tuple[int, bool]:
        """建任务（同 (ep,lang) 幂等复用）。返回 (task_id, 是否新建)。"""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT id FROM tasks WHERE ep = ? AND lang = ?", (ep, lang)
            ).fetchone()
            if row is not None:
                return int(row["id"]), False
            ts = _now()
            cur = conn.execute(
                "INSERT INTO tasks (ep, lang, state, created_at, updated_at)"
                " VALUES (?, ?, 'open', ?, ?)",
                (ep, lang, ts, ts),
            )
            conn.commit()
            return int(cur.lastrowid), True

    def get_task(self, task_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def touch_task(self, task_id: int, state: Optional[str] = None) -> None:
        with self._lock:
            conn = self._connect()
            if state:
                conn.execute(
                    "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
                    (state, _now(), task_id),
                )
            else:
                conn.execute(
                    "UPDATE tasks SET updated_at = ? WHERE id = ?",
                    (_now(), task_id),
                )
            conn.commit()

    # -- 逐句状态机 ----------------------------------------------------------

    def ensure_lines(self, task_id: int, utt_ids: list[str]) -> None:
        """C2 快照同步：缺的 utt 行补 idle（不删旧行，只增不改）。"""
        with self._lock:
            conn = self._connect()
            have = {
                r["utt_id"]
                for r in conn.execute(
                    "SELECT utt_id FROM lines WHERE task_id = ?", (task_id,)
                ).fetchall()
            }
            ts = _now()
            for uid in utt_ids:
                if uid not in have:
                    conn.execute(
                        "INSERT INTO lines (task_id, utt_id, state, updated_at)"
                        " VALUES (?, ?, 'idle', ?)",
                        (task_id, uid, ts),
                    )
            conn.commit()

    def get_line(self, task_id: int, utt_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connect().execute(
                "SELECT * FROM lines WHERE task_id = ? AND utt_id = ?",
                (task_id, utt_id),
            ).fetchone()
            return dict(row) if row is not None else None

    def set_line(
        self,
        task_id: int,
        utt_id: str,
        *,
        state: Optional[str] = None,
        synth_mode: Optional[str] = None,
        measured_dur: Optional[float] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        """更新逐句状态机列（None=不改该列；synth_mode/measured_dur 可显式清空）。"""
        sets: list[str] = ["updated_at = ?"]
        args: list[Any] = [_now()]
        if state is not None:
            sets.append("state = ?")
            args.append(state)
        if synth_mode is not None:
            sets.append("synth_mode = ?")
            args.append(synth_mode)
        if measured_dur is not None:
            sets.append("measured_dur = ?")
            args.append(float(measured_dur))
        if detail is not None:
            sets.append("detail = ?")
            args.append(json.dumps(detail, ensure_ascii=False))
        args += [task_id, utt_id]
        with self._lock:
            conn = self._connect()
            conn.execute(
                f"UPDATE lines SET {', '.join(sets)} WHERE task_id = ? AND utt_id = ?",
                args,
            )
            conn.commit()

    # -- 重生成流水 ----------------------------------------------------------

    def add_regen(
        self,
        task_id: int,
        utt_id: str,
        stage: str,
        from_state: str,
        to_state: str,
        ok: bool,
        detail: dict[str, Any],
    ) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO regens (task_id, utt_id, stage, from_state, to_state,"
                " ok, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, utt_id, stage, from_state, to_state,
                 1 if ok else 0, json.dumps(detail, ensure_ascii=False), _now()),
            )
            conn.commit()

    def list_regens(
        self, task_id: int, utt_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            if utt_id is None:
                rows = conn.execute(
                    "SELECT * FROM regens WHERE task_id = ? ORDER BY id", (task_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM regens WHERE task_id = ? AND utt_id = ? ORDER BY id",
                    (task_id, utt_id),
                ).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["detail"] = json.loads(d["detail"])
                except ValueError:
                    pass
                out.append(d)
            return out


# ---------------------------------------------------------------------------
# 工作区读取助手（C2/C4/C5/C3 —— 只通过冻结契约交换）
# ---------------------------------------------------------------------------

def _load_utterances(root: Path) -> list[C.Utterance]:
    utt_path = root / "04_dial" / "utterances.jsonl"
    if not utt_path.is_file():
        return []
    utts = list(fs_retry(C.load_jsonl, utt_path, C.UtteranceTable).root)
    utts.sort(key=lambda u: (u.start, u.end))
    return utts


def _load_c4(root: Path, lang: str) -> dict[str, C.Translation]:
    path = root / "06_mt" / "translations.jsonl"
    if not path.is_file():
        return {}
    rows = [
        r for r in fs_retry(C.load_jsonl, path, C.TranslationTable).root
        if r.tgt == lang
    ]
    return {r.utt_id: r for r in rows}


def _load_c5(root: Path, lang: str) -> dict[str, C.SynthPlanItem]:
    path = root / "07_synth" / f"synth_plan.{lang}.jsonl"
    if not path.is_file():
        return {}
    return {i.utt_id: i
            for i in fs_retry(C.load_jsonl, path, C.SynthPlanTable).root}


def _load_cast(root: Path) -> dict[str, C.Character]:
    path = root / "05_cast" / "characters.json"
    if not path.is_file():
        return {}
    return dict(fs_retry(C.load_model, path, C.CastBook).root)


def _meas_dur(root: Path, utt_id: str) -> Optional[float]:
    """实测时长：07_synth/wavs/<utt>.wav 存在时 soundfile 实测（秒，3 位）。"""
    wav = root / "07_synth" / "wavs" / f"{utt_id}.wav"
    if not wav.is_file():
        return None
    try:
        info = fs_retry(sf.info, str(wav))
        return round(info.frames / info.samplerate, 3)
    except (RuntimeError, OSError, PermissionError):
        return None


def _seed_path(root: Path) -> Path:
    return root / "06_mt" / "terms_seed.json"


def _load_seed(root: Path) -> dict[str, dict[str, str]]:
    path = _seed_path(root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(fs_retry(path.read_text, encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_seed(root: Path, seed: dict[str, dict[str, str]]) -> None:
    """术语种子原子写（tmp + os.replace，与契约写盘同口径；并发安全见 fs_retry）。"""
    path = _seed_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(seed, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    fs_retry(os.replace, tmp, path)


# ---------------------------------------------------------------------------
# 合成：真 :9002 探测/调用 + mock 占位（文本哈希种子，注明口径）
# ---------------------------------------------------------------------------

def tts_reachable(base_url: Optional[str] = None) -> tuple[bool, str]:
    """探测 :9002（短超时零重试）。返回 (可达?, 摘要)。

    可达指 HTTP /health 通（引擎是否就绪由调用结果判定；调用失败也回落
    mock 并在 reason 注明 —— 审校台回路不因 GPU 侧故障中断人工流程）。
    """
    env_name, default = SERVICE_ENV
    url = (base_url or os.environ.get(env_name, default)).rstrip("/")
    try:
        h = TtsClient(url, timeout=TTS_PROBE_TIMEOUT_S, retries=0).health()
        return True, json.dumps(
            {"url": url, "loaded": h.get("loaded") or {}}, ensure_ascii=False)
    except TtsError as exc:
        return False, f"{url} 不可达: {exc}"[:300]


def mock_synth(text: str, dur_s: float, out: Path) -> float:
    """mock 占位音频（**隧道不可达时的显式降级，逐处注明**）。

    以 sha256(译文) 为种子生成确定性波形（基频 + 文本相关噪声 × 词节奏包络），
    时长 = 预测时长（C5 expect_dur）：同文本恒同波形、文本变则波形变 ——
    支撑「导出片段该句音频变化、其余句不变」的可检验口径。返回实测时长。
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    n = max(1, int(round(max(dur_s, 0.05) * MOCK_SR)))
    t = np.arange(n, dtype=np.float64) / MOCK_SR
    f0 = 140.0 + 120.0 * float(rng.random())
    syll = 0.55 + 0.45 * np.sin(2 * np.pi * 7.0 * t + 2 * np.pi * float(rng.random()))
    wav = MOCK_AMP * np.sin(2 * np.pi * f0 * t + 2 * np.pi * float(rng.random())) * syll
    wav = wav + 0.06 * rng.standard_normal(n)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), wav.astype(np.float32), MOCK_SR, subtype="PCM_16")
    return round(n / MOCK_SR, 3)


def _tts_synth(
    item: C.SynthPlanItem, root: Path, lang: str
) -> tuple[Path, float, dict[str, Any]]:
    """真 :9002 合成（C5 双参考口径）。失败抛 :class:`TtsError`。"""
    voice_ref = root / item.voice_ref
    if not voice_ref.is_file():
        raise TtsError(f"音色参考不存在: {item.voice_ref}")
    emo_ref = root / item.emo_ref if item.emo_ref else None
    if emo_ref is not None and not emo_ref.is_file():
        emo_ref = None  # 情绪参考缺失：只用音色参考（服务口径），报告注明
    out = root / item.out
    cli = TtsClient(timeout=TTS_SYNTH_TIMEOUT_S, retries=0)
    r = cli.synth(
        item.text, str(voice_ref),
        emo_ref=str(emo_ref) if emo_ref else None,
        lang=lang, emo_alpha=item.emo_alpha,
        duration_factor=item.duration_factor, engine=item.engine,
        out=str(out), utt_id=item.utt_id,
    )
    info = {"engine": r.get("engine"), "chain": r.get("chain"),
            "duration_s": r.get("duration_s"), "emo_ref_used": bool(emo_ref)}
    return out, float(r.get("duration_s") or 0.0), info


# ---------------------------------------------------------------------------
# 单句重生成回路（M8 重对齐 → M7 重合成 → M9 重混）
# ---------------------------------------------------------------------------

def _bootstrap_c5(
    root: Path, ep: str, lang: str, cfg: dict[str, Any]
) -> None:
    """C5 缺失时整集跑一次 M8（一次性引导；此后重生成只动单句行）。"""
    from pipeline import m8_align as M8  # 局部导入：避免 import 期循环

    M8.align_episode(ep, lang, jobs_dir=root.parent, cfg=cfg)


def _stage_m8(
    task_id: int, store: ReviewStore, root: Path, ep: str, lang: str,
    u: C.Utterance, row: Optional[C.Translation], cfg: dict[str, Any],
    from_state: str,
) -> dict[str, Any]:
    """M8 单句重对齐：复算 C5 计划行并 upsert（无后缀副本同 M8 口径刷新）。"""
    t0 = time.time()
    main_path = root / "07_synth" / f"synth_plan.{lang}.jsonl"
    if not main_path.is_file():
        _bootstrap_c5(root, ep, lang, cfg)
    p: AlignParams = params_from_cfg(cfg)
    budget_cfg = cfg.get("budget") or {}
    cast = _load_cast(root)
    rates = load_syl_table(Path(cfg["paths"]["models_dir"]) / "syl2dur.json")
    decision = align_utterance(
        u, row, cast=cast, root=root, lang=lang, params=p,
        lo_ratio=float(budget_cfg.get("lo_ratio", 0.9)),
        hi_ratio=float(budget_cfg.get("hi_ratio", 1.1)), rates=rates,
    )
    fs_retry(C.upsert_jsonl, main_path, [decision.item],
             container=C.SynthPlanTable, key_field="utt_id")
    copy_path = root / "07_synth" / "synth_plan.jsonl"
    fs_retry(shutil.copyfile, main_path, copy_path)
    detail = {
        "status": decision.status, "cand_idx": decision.cand_idx,
        "text": decision.text, "duration_factor": decision.duration_factor,
        "atempo": decision.atempo, "pred_dur": decision.pred_dur,
        "window": list(decision.window), "keep_original": decision.item.keep_original,
        "elapsed_s": round(time.time() - t0, 3),
    }
    store.add_regen(task_id, u.utt_id, _STAGE_NAME["m8"], from_state,
                    _STAGE_STATE["m8"], True, detail)
    return detail


def _stage_m7(
    task_id: int, store: ReviewStore, root: Path, lang: str,
    u: C.Utterance, from_state: str, tts_mode: str,
) -> dict[str, Any]:
    """M7 单句重合成：真 :9002 / mock 占位（不可达时注明）/ keep-original 跳过。"""
    t0 = time.time()
    item = _load_c5(root, lang).get(u.utt_id)
    if item is None:
        raise RuntimeError(
            f"C5 无 {u.utt_id} 行（先跑 M8 重对齐，或 m8 阶段）")
    out = root / item.out
    if item.keep_original:
        detail = {"mode": "keep-original",
                  "reason": "C5 keep_original=true（nonverbal/无译文）——复用原人声，不合成",
                  "elapsed_s": round(time.time() - t0, 3)}
        store.add_regen(task_id, u.utt_id, _STAGE_NAME["m7"], from_state,
                        _STAGE_STATE["m7"], True, detail)
        return detail

    mode = "mock"
    reason = ""
    info: dict[str, Any] = {}
    if tts_mode == "force-mock":
        reason = "请求显式 force-mock（离线口径）"
    else:
        ok, probe = tts_reachable()
        if not ok:
            reason = f"GPU tts 服务不可达（tts/:9002）→ mock 占位音频生成（已注明）: {probe}"
        else:
            try:
                _, dur, info = _tts_synth(item, root, lang)
                mode = "tts-gpu"
                reason = "真 :9002 合成（tts-gpu）"
            except TtsError as exc:
                reason = f":9002 调用失败 → mock 占位音频生成（已注明）: {exc}"[:300]

    if mode == "mock":
        mock_synth(item.text, float(item.expect_dur or 0.0), out)
    info_wav = fs_retry(sf.info, str(out))
    meas = round(info_wav.frames / info_wav.samplerate, 3)
    detail = {
        "mode": mode, "tts_requested": tts_mode, "reason": reason,
        "mock": mode == "mock",
        "text": item.text, "expect_dur": item.expect_dur, "meas_dur": meas,
        "wav": str(out), "elapsed_s": round(time.time() - t0, 3),
        **({"tts": info} if info else {}),
    }
    store.add_regen(task_id, u.utt_id, _STAGE_NAME["m7"], from_state,
                    _STAGE_STATE["m7"], True, detail)
    return detail


def _stage_m9(
    task_id: int, store: ReviewStore, utt_id: str, ep: str, lang: str,
    jobs_dir: Path, cfg: dict[str, Any], from_state: str, compose: bool,
) -> dict[str, Any]:
    """M9 整集重混（ducking + 响度 + 成片 compose 可选）。"""
    t0 = time.time()
    rep = M9.mix_episode(ep, lang, jobs_dir=jobs_dir, cfg=cfg, compose=compose)
    detail = {
        "mix_duration_s": rep["mix"]["duration_s"],
        "loudness_i": rep["loudness"]["final"]["input_i"],
        "loudness_in_tolerance": rep["loudness"]["in_tolerance"],
        "compose_status": rep["compose"].get("status"),
        "compose_out": rep["compose"].get("out"),
        "elapsed_s": round(time.time() - t0, 3),
    }
    store.add_regen(task_id, utt_id, _STAGE_NAME["m9"], from_state,
                    _STAGE_STATE["m9"], True, detail)
    return detail


# ---------------------------------------------------------------------------
# SRT / 合规报告导出
# ---------------------------------------------------------------------------

def _srt_ts(t: float) -> str:
    """SRT 时间戳 ``HH:MM:SS,mmm``（负值夹 0）。"""
    t = max(0.0, float(t))
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(
    utts: list[C.Utterance], c4: dict[str, C.Translation]
) -> tuple[str, list[str]]:
    """C2 句窗 × C4 chosen → SRT 文本。返回 (srt 内容, 跳过句清单)。

    跳过口径：无 C4 行 / 无 chosen / 译文为空的句子（如实列出，不伪造字幕）。
    """
    blocks: list[str] = []
    skipped: list[str] = []
    for u in utts:
        row = c4.get(u.utt_id)
        text = ""
        if row is not None and row.chosen is not None and row.candidates:
            text = row.candidates[row.chosen].text.strip()
        if not text:
            skipped.append(u.utt_id)
            continue
        blocks.append(
            f"{len(blocks) + 1}\n"
            f"{_srt_ts(u.start)} --> {_srt_ts(u.end)}\n{text}\n"
        )
    return ("\n".join(blocks) + ("\n" if blocks else "")), skipped


def _ffprobe_tags(path: Path) -> dict[str, str]:
    """ffprobe format_tags（合规隐式标识核验用；失败返回空表）。"""
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format_tags",
             "-print_format", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300,
        )
        if r.returncode != 0:
            return {}
        return dict(json.loads(r.stdout).get("format", {}).get("tags", {}) or {})
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


def build_compliance(
    root: Path, ep: str, lang: str, cfg: dict[str, Any],
    reviewed: list[str],
) -> dict[str, Any]:
    """C8 合规报告（审校台出口）。

    如实口径：findings 归 M12 规则引擎（未接入前留空并在 generator 注明）；
    隐式标识状态对 12_out 成片 ffprobe 实测（C7 缺省回落 m9 配置兜底）；
    显式/C2PA/水印三项 pending（M12 未部署），不伪造 ok。
    """
    channels = cfg.get("channels") or {}
    market = str((channels.get(lang) or {}).get("market", f"unknown-{lang}"))
    label_field, label_value = M9.DEFAULT_LABEL_FIELD, ""
    labels_path = root / "11_labels" / "labels.json"
    if labels_path.is_file():
        labels = fs_retry(C.load_model, labels_path, C.Labels)
        label_field = labels.implicit.metadata_field
        label_value = labels.implicit.value
        content_id = labels.content_id
        standard = labels.standard
    else:
        label_value = f"{ep}-{lang}|{M9.DEFAULT_SERVICE_PROVIDER}"
        content_id = f"{ep}-{lang}"
        standard = "GB45438-2025"
    mp4 = root / "12_out" / f"{ep}.{lang}.mp4"
    implicit_state = "pending"
    if mp4.is_file():
        tags = _ffprobe_tags(mp4)
        implicit_state = "ok" if tags.get(label_field) == label_value else "failed"
    report = {
        "market": market,
        "ep": ep,
        "findings": [],
        "label_status": {
            "explicit": "pending", "implicit": implicit_state,
            "c2pa": "pending", "audio_wm": "pending",
        },
        "human_review": reviewed,
        "generator": (
            "review-console（M13 审校台导出；findings 由 M12 规则引擎产出，"
            "未接入前留空；explicit/c2pa/audio_wm 待 M12 落地）"
        ),
    }
    C.ComplianceReport.model_validate(report)  # C8 契约强校验后才落盘
    return report


# ---------------------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------------------

class TaskCreate(BaseModel):
    ep: str = Field(min_length=1)
    lang: str = "en"


class TranslationEdit(BaseModel):
    text: Optional[str] = None
    chosen_idx: Optional[int] = Field(default=None, ge=0)


class RetranslateReq(BaseModel):
    backend: str = "mock"
    n_candidates: int = Field(default=4, ge=1, le=5)


class RegenerateReq(BaseModel):
    stages: list[str] = Field(default_factory=lambda: list(REGEN_STAGES))
    tts: str = "auto"           # auto（探测，不可达 mock）| force-mock
    compose: bool = True


class GlossaryUpsert(BaseModel):
    tgt: str = Field(min_length=1)


class ExportReq(BaseModel):
    mp4: bool = True
    srt: bool = True
    compliance: bool = True


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

def create_app(
    jobs_dir: str | Path,
    *,
    db_path: str | Path | None = None,
    configs_dir: str | Path | None = None,
) -> FastAPI:
    """构建审校台应用（tests 以 httpx ASGITransport 直挂；uvicorn 生产同款）。"""
    jobs_root = Path(jobs_dir).resolve()
    cfg = load_pipeline_config(configs_dir)
    store = ReviewStore(db_path or (jobs_root / "review_console.db"))
    regen_locks: dict[str, threading.Lock] = {}
    regen_locks_guard = threading.Lock()

    app = FastAPI(title="审校台（M13）", version="0.1.0")

    # -- 助手 ---------------------------------------------------------------

    def _task_or_404(task_id: int) -> dict[str, Any]:
        task = store.get_task(task_id)
        if task is None:
            raise HTTPException(404, f"任务不存在: {task_id}")
        return task

    def _root_or_404(task: dict[str, Any]) -> Path:
        try:
            return ep_dir(str(task["ep"]), jobs_root)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    def _utt_or_404(root: Path, utt_id: str) -> C.Utterance:
        for u in _load_utterances(root):
            if u.utt_id == utt_id:
                return u
        raise HTTPException(404, f"C2 无此句: {utt_id}")

    def _regen_lock(ep: str, lang: str) -> threading.Lock:
        with regen_locks_guard:
            return regen_locks.setdefault(f"{ep}|{lang}", threading.Lock())

    def _line_payload(root: Path, lang: str, u: C.Utterance,
                      line: dict[str, Any],
                      c4: Optional[dict[str, C.Translation]] = None,
                      c5: Optional[dict[str, C.SynthPlanItem]] = None,
                      ) -> dict[str, Any]:
        c4 = _load_c4(root, lang) if c4 is None else c4
        c5 = _load_c5(root, lang) if c5 is None else c5
        row = c4.get(u.utt_id)
        item = c5.get(u.utt_id)
        budget = row.budget if row is not None else budget_for(
            u, float(cfg["budget"]["lo_ratio"]), float(cfg["budget"]["hi_ratio"]))
        meas = _meas_dur(root, u.utt_id)
        chosen_text = ""
        if row is not None and row.chosen is not None and row.candidates:
            chosen_text = row.candidates[row.chosen].text
        return {
            "utt_id": u.utt_id,
            "start": u.start, "end": u.end,
            "shot_id": u.shot_id,
            "speaker": u.speaker, "char_id": u.char_id or char_id_for(u),
            "src_text": u.text, "nonverbal": u.nonverbal,
            "budget": budget.model_dump(),
            "chosen_idx": row.chosen if row else None,
            "chosen_text": chosen_text,
            "policy": row.policy if row else None,
            "candidates": [c.model_dump() for c in row.candidates] if row else [],
            "c5": (item.model_dump(exclude={"emo_alpha"}) if item else None),
            "meas_dur": meas,
            "in_window": bool(
                meas is not None and budget.lo <= meas <= budget.hi),
            "state": line["state"], "synth_mode": line["synth_mode"],
            "measured_dur_db": line["measured_dur"],
            "updated_at": line["updated_at"],
        }

    def _sync_c4_row(root: Path, row: C.Translation) -> int:
        """C4 复合键 (utt_id,tgt) 替换写盘（复用 m6 原语；并发安全见 fs_retry）。"""
        return fs_retry(_upsert_translations,
                        root / "06_mt" / "translations.jsonl", [row])

    # -- 首页（原生 JS 单页，无构建链）--------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    # -- 任务 ----------------------------------------------------------------

    @app.post("/api/tasks")
    def create_task(body: TaskCreate) -> dict[str, Any]:
        if body.lang not in SUPPORTED_LANGS:
            raise HTTPException(400, f"语种 {body.lang!r} 未登记（支持：{', '.join(SUPPORTED_LANGS)}）")
        try:
            root = ep_dir(body.ep, jobs_root)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not (root / "04_dial" / "utterances.jsonl").is_file():
            raise HTTPException(400, f"C2 不存在: {root}/04_dial/utterances.jsonl（先跑上游链路 M2/M4）")
        create_workspace(body.ep, jobs_root)
        tid, created = store.create_task(body.ep, body.lang)
        store.ensure_lines(tid, [u.utt_id for u in _load_utterances(root)])
        store.touch_task(tid)
        task = store.get_task(tid)
        assert task is not None
        return {"task": task, "created": created}

    @app.get("/api/tasks")
    def list_tasks() -> list[dict[str, Any]]:
        return store.list_tasks()

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: int) -> dict[str, Any]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        store.ensure_lines(task_id, [u.utt_id for u in _load_utterances(root)])
        lines = store.list_regens(task_id)
        return {**task, "n_regens": len(lines)}

    # -- 逐句表格 ------------------------------------------------------------

    @app.get("/api/tasks/{task_id}/lines")
    def list_lines(task_id: int) -> dict[str, Any]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        utts = _load_utterances(root)
        if not utts:
            raise HTTPException(400, "C2 为空")
        store.ensure_lines(task_id, [u.utt_id for u in utts])
        lang = str(task["lang"])
        c4, c5 = _load_c4(root, lang), _load_c5(root, lang)
        rows = [_line_payload(root, lang, u, line, c4, c5) for u in utts
                if (line := store.get_line(task_id, u.utt_id)) is not None]
        return {"task_id": task_id, "ep": task["ep"], "lang": lang,
                "lines": rows,
                "states": {s: sum(1 for r in rows if r["state"] == s)
                           for s in LINE_STATES}}

    @app.get("/api/tasks/{task_id}/lines/{utt_id}")
    def get_line(task_id: int, utt_id: str) -> dict[str, Any]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        u = _utt_or_404(root, utt_id)
        line = store.get_line(task_id, utt_id)
        if line is None:
            raise HTTPException(404, "无此审校行")
        return _line_payload(root, str(task["lang"]), u, line)

    # -- 改译文 / 换候选（回写 C4）---------------------------------------------

    @app.put("/api/tasks/{task_id}/lines/{utt_id}/translation")
    def edit_translation(task_id: int, utt_id: str, body: TranslationEdit) -> dict[str, Any]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        u = _utt_or_404(root, utt_id)
        lang = str(task["lang"])
        c4 = _load_c4(root, lang)
        row = c4.get(utt_id)
        rates = load_syl_table(Path(cfg["paths"]["models_dir"]) / "syl2dur.json")
        if row is None:
            # 无 C4 行：人工首译 → 单候选行（预算按 C2 窗自算，同 m8 兜底口径）
            budget = budget_for(u, float(cfg["budget"]["lo_ratio"]),
                                float(cfg["budget"]["hi_ratio"]))
            row = C.Translation(utt_id=utt_id, tgt=lang, context=[],
                                budget=budget, candidates=[], policy="manual-edit")
        if body.text is not None:
            text = body.text.strip()
            if not text:
                raise HTTPException(400, "译文不得为空")
            idx = row.chosen if row.chosen is not None else 0
            if not row.candidates:
                row.candidates.append(C.Candidate(
                    text=text, syl=0, est_dur=0.0, src=EDIT_SRC, q=1.0))
            else:
                old = row.candidates[idx]
                row.candidates[idx] = C.Candidate(
                    text=text,
                    syl=count_syllables(text, lang),
                    est_dur=estimate_dur_s(count_syllables(text, lang), lang, rates),
                    src=EDIT_SRC, q=old.q,
                )
            row.chosen = idx
        elif body.chosen_idx is not None:
            if body.chosen_idx >= len(row.candidates):
                raise HTTPException(400,
                                    f"chosen_idx={body.chosen_idx} 越界（共 {len(row.candidates)} 候选）")
            row.chosen = body.chosen_idx
        else:
            raise HTTPException(400, "text 与 chosen_idx 至少给一个")
        _sync_c4_row(root, row)
        store.set_line(task_id, utt_id, state="edited",
                       detail={"action": "edit-translation",
                               "text": body.text, "chosen_idx": body.chosen_idx})
        store.touch_task(task_id)
        line = store.get_line(task_id, utt_id)
        assert line is not None
        return _line_payload(root, lang, u, line)

    # -- M6 单句重翻（术语注入上下文）-----------------------------------------

    @app.post("/api/tasks/{task_id}/lines/{utt_id}/retranslate")
    def retranslate(task_id: int, utt_id: str, body: RetranslateReq) -> dict[str, Any]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        u = _utt_or_404(root, utt_id)
        lang = str(task["lang"])
        try:
            backend: MTBackend = make_backend(body.backend)
        except Exception as exc:  # noqa: BLE001 —— make_backend 的配置错误归 400
            raise HTTPException(400, f"后端不可用: {exc}")
        utts = _load_utterances(root)
        idx = next(i for i, x in enumerate(utts) if x.utt_id == utt_id)
        cast = _load_cast(root)
        seed = _load_seed(root)
        glossary = build_glossary(cast, seed, lang)
        cast_text = build_cast_summary_text(cast, {}, lang)
        budget = budget_for(u, float(cfg["budget"]["lo_ratio"]),
                            float(cfg["budget"]["hi_ratio"]))
        prev = [x.text for x in utts[max(0, idx - CTX_WINDOW):idx] if x.text.strip()]
        nxt = [x.text for x in utts[idx + 1: idx + 1 + CTX_WINDOW] if x.text.strip()]
        ctx = MTContext(tgt_lang=lang, cast_summary=cast_text, terms=glossary,
                        prev_texts=prev, next_texts=nxt,
                        budget=(budget.orig_dur, budget.lo, budget.hi))
        drafts = backend.translate(u.text or utt_id, ctx,
                                   n_candidates=body.n_candidates)
        rates = load_syl_table(Path(cfg["paths"]["models_dir"]) / "syl2dur.json")
        cands = [
            C.Candidate(text=d.text, syl=count_syllables(d.text, lang),
                        est_dur=estimate_dur_s(count_syllables(d.text, lang), lang, rates),
                        src=d.src, q=round(d.q, 3))
            for d in drafts
        ]
        order = sorted(range(len(cands)), key=lambda i: (
            0 if budget.lo <= cands[i].est_dur <= budget.hi else 1,
            -cands[i].q, abs(cands[i].est_dur - budget.orig_dur)))
        row = C.Translation(
            utt_id=utt_id, tgt=lang, context=prev, budget=budget,
            candidates=[cands[i] for i in order], chosen=0, policy="in-budget-first")
        _sync_c4_row(root, row)
        store.set_line(task_id, utt_id, state="edited",
                       detail={"action": "retranslate", "backend": backend.name,
                               "terms_injected": glossary})
        store.touch_task(task_id)
        line = store.get_line(task_id, utt_id)
        assert line is not None
        return {"line": _line_payload(root, lang, u, line),
                "backend": backend.name,
                "terms_injected": glossary,
                "context": {"prev": prev, "next": nxt}}

    # -- 单句重生成（M8→M7→M9 状态机）-----------------------------------------

    @app.post("/api/tasks/{task_id}/lines/{utt_id}/regenerate")
    def regenerate(task_id: int, utt_id: str, body: RegenerateReq) -> dict[str, Any]:
        task = _task_or_404(task_id)
        ep, lang = str(task["ep"]), str(task["lang"])
        root = _root_or_404(task)
        u = _utt_or_404(root, utt_id)
        stages = [s for s in REGEN_STAGES if s in set(body.stages)]
        if not stages:
            raise HTTPException(400, f"stages 为空（可选：{', '.join(REGEN_STAGES)}）")
        if body.tts not in ("auto", "force-mock"):
            raise HTTPException(400, "tts 仅支持 auto | force-mock")
        store.ensure_lines(task_id, [x.utt_id for x in _load_utterances(root)])
        line = store.get_line(task_id, utt_id)
        assert line is not None
        from_state = str(line["state"])
        t0 = time.time()
        trace: list[dict[str, Any]] = []
        synth_mode: Optional[str] = None
        meas: Optional[float] = None
        with _regen_lock(ep, lang):
            c4 = _load_c4(root, lang)
            row = c4.get(utt_id)
            if (row is not None and row.chosen is not None and row.candidates
                    and row.candidates[row.chosen].src == EDIT_SRC):
                # 人工改稿优先：M8 候选阶梯只对审校定稿候选重对齐
                #（否则阶梯可能换回机器候选，人工译文被静默丢弃）
                row = row.model_copy(update={
                    "candidates": [row.candidates[row.chosen]], "chosen": 0})
            try:
                if "m8" in stages:
                    d = _stage_m8(task_id, store, root, ep, lang, u,
                                  row, cfg, from_state)
                    trace.append({"stage": "m8-align", "ok": True, "detail": d})
                    store.set_line(task_id, utt_id, state="aligned")
                    from_state = "aligned"
                if "m7" in stages:
                    d = _stage_m7(task_id, store, root, lang, u,
                                  from_state, body.tts)
                    trace.append({"stage": "m7-synth", "ok": True, "detail": d})
                    synth_mode = str(d["mode"])
                    meas = d.get("meas_dur")
                    store.set_line(task_id, utt_id, state="synthesized",
                                   synth_mode=synth_mode, measured_dur=meas)
                    from_state = "synthesized"
                if "m9" in stages:
                    d = _stage_m9(task_id, store, utt_id, ep, lang, jobs_root,
                                  cfg, from_state, body.compose)
                    trace.append({"stage": "m9-mix", "ok": True, "detail": d})
                    store.set_line(task_id, utt_id, state="ready")
            except Exception as exc:  # noqa: BLE001 —— 状态机如实记 error
                err = {"error": f"{type(exc).__name__}: {exc}"[:500],
                       "failed_after": from_state}
                store.add_regen(task_id, utt_id, "error", from_state, "error",
                                False, err)
                store.set_line(task_id, utt_id, state="error", detail=err)
                raise HTTPException(500, {
                    "task_id": task_id, "utt_id": utt_id, "ok": False,
                    "error": err["error"], "trace": trace,
                })
        store.touch_task(task_id, state="regenerated")
        line = store.get_line(task_id, utt_id)
        assert line is not None
        elapsed = round(time.time() - t0, 2)
        return {
            "task_id": task_id, "utt_id": utt_id, "ok": True,
            "state": line["state"], "synth_mode": synth_mode,
            "mock": synth_mode == "mock",
            "meas_dur": meas, "elapsed_s": elapsed,
            "target_s": REGEN_TARGET_S,
            "trace": trace,
        }

    @app.get("/api/tasks/{task_id}/regens")
    def list_regens(task_id: int, utt_id: Optional[str] = None) -> list[dict[str, Any]]:
        _task_or_404(task_id)
        return store.list_regens(task_id, utt_id)

    # -- 术语表（C3 terms ∪ terms_seed；CRUD 落 06_mt/terms_seed.json）---------

    @app.get("/api/tasks/{task_id}/glossary")
    def get_glossary(task_id: int) -> dict[str, Any]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        lang = str(task["lang"])
        seed = _load_seed(root)
        effective = build_glossary(_load_cast(root), seed, lang)
        return {"task_id": task_id, "lang": lang, "seed": seed,
                "effective": effective,
                "seed_path": str(_seed_path(root).relative_to(root))}

    @app.put("/api/tasks/{task_id}/glossary/{src}")
    def upsert_glossary(task_id: int, src: str, body: GlossaryUpsert) -> dict[str, Any]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        lang = str(task["lang"])
        src = src.strip()
        if not src:
            raise HTTPException(400, "源术语不得为空")
        seed = _load_seed(root)
        entry = dict(seed.get(src) or {})
        entry[lang] = body.tgt.strip()
        seed[src] = entry
        _write_seed(root, seed)
        return get_glossary(task_id)  # type: ignore[return-value]

    @app.delete("/api/tasks/{task_id}/glossary/{src}")
    def delete_glossary(task_id: int, src: str) -> dict[str, Any]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        lang = str(task["lang"])
        seed = _load_seed(root)
        entry = dict(seed.get(src) or {})
        if lang not in entry:
            raise HTTPException(404, f"种子无 {lang} 译法: {src}")
        del entry[lang]
        if entry:
            seed[src] = entry
        else:
            seed.pop(src, None)
        _write_seed(root, seed)
        return get_glossary(task_id)  # type: ignore[return-value]

    # -- 片段预览 ------------------------------------------------------------

    def _audio_track(root: Path, lang: str) -> Path:
        for name in (f"dubbed.{lang}.wav", "dubbed.wav"):
            p = root / "08_mix" / name
            if p.is_file():
                return p
        raise HTTPException(404, "08_mix 人声轨不存在（先跑 M9 重混）")

    @app.get("/api/tasks/{task_id}/lines/{utt_id}/preview")
    def preview_line(task_id: int, utt_id: str) -> Response:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        u = _utt_or_404(root, utt_id)
        path = _audio_track(root, str(task["lang"]))
        info = fs_retry(sf.info, str(path))
        i0 = max(0, int((u.start - PREVIEW_PAD_S) * info.samplerate))
        i1 = min(info.frames, int((u.end + PREVIEW_PAD_S) * info.samplerate))
        data, sr = fs_retry(sf.read, str(path), start=i0, stop=i1,
                            dtype="float32", always_2d=True)
        buf = io.BytesIO()
        sf.write(buf, data, sr, format="WAV", subtype="PCM_16")
        return Response(content=buf.getvalue(), media_type="audio/wav",
                        headers={"Content-Disposition":
                                 f'inline; filename="{utt_id}.wav"'})

    @app.get("/api/tasks/{task_id}/lines/{utt_id}/clip")
    def clip_line(task_id: int, utt_id: str) -> FileResponse:
        """成片句窗切段（mp4，重编码精确切）；无成片回 404 并注明。"""
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        u = _utt_or_404(root, utt_id)
        src = root / "12_out" / f"{task['ep']}.{task['lang']}.mp4"
        if not src.is_file():
            raise HTTPException(404, "12_out 成片不存在（先跑 M9 重混 compose 或导出）")
        out_dir = root / "08_mix" / "previews"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{utt_id}.mp4"
        cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
               "-i", str(src), "-ss", f"{max(0.0, u.start - PREVIEW_PAD_S):.3f}",
               "-to", f"{u.end + PREVIEW_PAD_S:.3f}",
               "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
               "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)]

        def _cut() -> subprocess.CompletedProcess:
            return subprocess.run(cmd, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=600)

        r = fs_retry(_cut)
        if r.returncode != 0 or not out.is_file():
            raise HTTPException(500, f"切段失败: {(r.stderr or '')[-300:]}")
        return FileResponse(out, media_type="video/mp4", filename=out.name)

    @app.get("/api/tasks/{task_id}/video")
    def task_video(task_id: int) -> FileResponse:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        src = root / "12_out" / f"{task['ep']}.{task['lang']}.mp4"
        if not src.is_file():
            raise HTTPException(404, "12_out 成片不存在（先跑 M9 重混 compose 或导出）")
        return FileResponse(src, media_type="video/mp4", filename=src.name)

    # -- 导出（MP4 / SRT / C8 合规报告）---------------------------------------

    @app.post("/api/tasks/{task_id}/export")
    def export_task(task_id: int, body: ExportReq) -> dict[str, Any]:
        task = _task_or_404(task_id)
        ep, lang = str(task["ep"]), str(task["lang"])
        root = _root_or_404(task)
        utts = _load_utterances(root)
        if not utts:
            raise HTTPException(400, "C2 为空")
        out_dir = root / "12_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        report: dict[str, Any] = {"task_id": task_id, "ep": ep, "lang": lang,
                                  "artifacts": {}}

        mp4 = out_dir / f"{ep}.{lang}.mp4"
        if body.mp4:
            note = ""
            if not mp4.is_file():
                # 与单句重生成的 M9 互斥（同写 08_mix/12_out，同集串行）
                with _regen_lock(ep, lang):
                    if not mp4.is_file():
                        try:
                            M9.mix_episode(ep, lang, jobs_dir=jobs_root,
                                           cfg=cfg, compose=True)
                        except M9.MixError as exc:
                            note = f"M9 compose 未产出（如实记因）: {exc}"[:300]
            report["artifacts"]["mp4"] = {
                "path": str(mp4), "exists": mp4.is_file(), "note": note,
            }

        if body.srt:
            srt, skipped = build_srt(utts, _load_c4(root, lang))
            srt_path = out_dir / f"{ep}.{lang}.srt"
            srt_path.write_text(srt, encoding="utf-8", newline="\n")
            report["artifacts"]["srt"] = {
                "path": str(srt_path), "exists": srt_path.is_file(),
                "n_blocks": srt.count("\n\n") + (1 if srt.strip() else 0),
                "skipped_lines": skipped,
            }

        if body.compliance:
            reviewed = [
                r["utt_id"] for r in
                (store.get_line(task_id, u.utt_id) for u in utts)
                if r is not None and r["state"] not in ("idle", "error")
            ]
            comp = build_compliance(root, ep, lang, cfg, reviewed)
            comp_path = out_dir / f"compliance.{lang}.json"
            tmp = comp_path.with_name(comp_path.name + ".tmp")
            tmp.write_text(json.dumps(comp, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8", newline="\n")
            fs_retry(os.replace, tmp, comp_path)
            report["artifacts"]["compliance"] = {
                "path": str(comp_path), "exists": comp_path.is_file(),
                "label_status": comp["label_status"],
                "human_review": reviewed,
            }

        store.touch_task(task_id, state="exported")
        report["ok"] = any(a.get("exists") for a in report["artifacts"].values())
        return report

    @app.get("/api/tasks/{task_id}/export/files")
    def export_files(task_id: int) -> list[dict[str, Any]]:
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        ep, lang = str(task["ep"]), str(task["lang"])
        out: list[dict[str, Any]] = []
        for name in (f"{ep}.{lang}.mp4", f"{ep}.{lang}.srt",
                     f"compliance.{lang}.json"):
            p = root / "12_out" / name
            if p.is_file():
                out.append({"name": name, "size": p.stat().st_size,
                            "path": str(p)})
        return out

    @app.get("/api/tasks/{task_id}/files/{name}")
    def download(task_id: int, name: str) -> FileResponse:
        """导出产物下载（仅 12_out 白名单文件名，防路径穿越）。"""
        task = _task_or_404(task_id)
        root = _root_or_404(task)
        if not _EXPORT_NAME_RE.match(name) or ".." in name:
            raise HTTPException(400, f"非法文件名: {name!r}")
        p = (root / "12_out" / name).resolve()
        if p.parent != (root / "12_out").resolve() or not p.is_file():
            raise HTTPException(404, f"产物不存在: {name}")
        media = "video/mp4" if name.endswith(".mp4") else (
            "application/x-subrip" if name.endswith(".srt") else
            "application/json")
        return FileResponse(p, media_type=media, filename=name)

    return app


# ---------------------------------------------------------------------------
# 首页（原生 JS 单页；无构建链，内网使用无鉴权）
# ---------------------------------------------------------------------------

_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>审校台（M13）</title>
<style>
 body{font-family:system-ui,sans-serif;margin:12px;background:#141821;color:#e6e9ef}
 h2{font-size:16px;margin:14px 0 6px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 td,th{border:1px solid #2c3442;padding:4px 6px;text-align:left;vertical-align:top}
 th{background:#1d2430}
 button{background:#2f6fed;color:#fff;border:0;border-radius:4px;padding:4px 10px;cursor:pointer;margin:1px}
 button.sec{background:#3a4457}
 input,select{background:#0f131a;color:#e6e9ef;border:1px solid #2c3442;border-radius:4px;padding:3px 6px}
 .tag{display:inline-block;border-radius:8px;padding:0 8px;font-size:11px;background:#2c3442}
 .st-ready{background:#1d7a46}.st-edited{background:#8a6d1d}.st-error{background:#8a2323}
 .st-synthesized{background:#28567f}.st-aligned{background:#4b3f7f}.st-mixed{background:#1f6f6f}
 textarea{width:95%;background:#0f131a;color:#e6e9ef;border:1px solid #2c3442}
 #msg{color:#ffb84d;font-size:13px;min-height:18px;white-space:pre-wrap}
 audio{width:180px;height:28px}
</style></head><body>
<h2>审校台 · 逐句表格（C4 译文/候选 · 预算/实测）</h2>
<div>
 <select id="taskSel"></select>
 <input id="ep" placeholder="集 ID，如 ep01" size="10">
 <select id="lang"><option>en</option><option>es</option><option>ar</option></select>
 <button onclick="createTask()">创建/打开任务</button>
 <button class="sec" onclick="refreshTasks()">刷新任务</button>
 <button class="sec" onclick="exportAll()">导出（MP4/SRT/合规）</button>
 <a id="videoLink" href="#" target="_blank">成片</a>
</div>
<div id="glossary"></div>
<div id="msg"></div>
<table id="lines"><thead><tr>
 <th>句</th><th>时间</th><th>角色</th><th>原文</th><th>译文(chosen)</th>
 <th>候选(est)</th><th>预算/实测</th><th>状态</th><th>操作</th>
</tr></thead><tbody></tbody></table>
<script>
const $=s=>document.querySelector(s);
let TID=null,UTTS=[];
function msg(t){$("#msg").textContent=t}
async function jf(u,opt){const r=await fetch(u,opt);const b=await r.json();
 if(!r.ok){msg("HTTP "+r.status+": "+(b.detail&&(b.detail.error||JSON.stringify(b.detail))||""));throw new Error(b.detail)}
 return b}
async function refreshTasks(){const ts=await jf("/api/tasks");const s=$("#taskSel");s.innerHTML="";
 for(const t of ts){const o=document.createElement("option");o.value=t.id;
  o.textContent=`#${t.id} ${t.ep}/${t.lang} ${t.state}`;s.append(o)}
 if(ts.length){TID=ts[0].id;s.value=TID;loadLines();loadGlossary()}}
$("#taskSel").onchange=e=>{TID=+e.target.value;loadLines();loadGlossary()};
async function createTask(){const b=await jf("/api/tasks",{method:"POST",
 headers:{"Content-Type":"application/json"},body:JSON.stringify({ep:$("#ep").value,lang:$("#lang").value})});
 TID=b.task.id;msg(`任务 #${TID} ${b.created?"已创建":"已存在"}`);refreshTasks()}
function rowHtml(l){
 const cands=(l.candidates||[]).map((c,i)=>`${i===l.chosen_idx?"★":""}${c.text} <span class="tag">${c.est_dur}s/${c.src}</span>`).join("<br>");
 const b=l.budget, st=l.state;
 return `<tr><td>${l.utt_id}<br><span class="tag">${st}</span></td>
 <td>${l.start}–${l.end}</td><td>${l.char_id||""}</td><td>${l.src_text}</td>
 <td><textarea rows="2" id="t_${l.utt_id}">${l.chosen_text||""}</textarea><br>
 <button onclick="save('${l.utt_id}')">存译文</button>
 <button class="sec" onclick="retrans('${l.utt_id}')">M6重翻</button></td>
 <td>${cands}</td>
 <td>${b.lo.toFixed(2)}–${b.hi.toFixed(2)}s<br>实测 ${l.meas_dur==null?"-":l.meas_dur+"s"+(l.in_window?" ✓":" ✗")}
 <br>${l.synth_mode?"合成:"+l.synth_mode:""}</td>
 <td><span class="tag st-${st}">${st}</span></td>
 <td><button onclick="regen('${l.utt_id}')">重生成</button><br>
 <audio controls src="/api/tasks/${TID}/lines/${l.utt_id}/preview"></audio><br>
 <button class="sec" onclick="clip('${l.utt_id}')">片段</button></td></tr>`}
async function loadLines(){if(!TID)return;const b=await jf(`/api/tasks/${TID}/lines`);
 UTTS=b.lines;document.querySelector("#lines tbody").innerHTML=b.lines.map(rowHtml).join("");
 $("#videoLink").href=`/api/tasks/${TID}/video`;msg(`状态统计 ${JSON.stringify(b.states)}`)}
async function save(u){const text=document.getElementById("t_"+u).value;
 await jf(`/api/tasks/${TID}/lines/${u}/translation`,{method:"PUT",
 headers:{"Content-Type":"application/json"},body:JSON.stringify({text})});msg(u+" 译文已存(C4)");loadLines()}
async function retrans(u){await jf(`/api/tasks/${TID}/lines/${u}/retranslate`,{method:"POST",
 headers:{"Content-Type":"application/json"},body:"{}"});msg(u+" M6 重翻完成");loadLines()}
async function regen(u){msg(u+" 重生成中…");const b=await jf(`/api/tasks/${TID}/lines/${u}/regenerate`,
 {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})});
 msg(`${u} 重生成完成 ${b.elapsed_s}s 状态=${b.state} 合成=${b.synth_mode}${b.mock?"(mock 占位，隧道不可达已注明)":""}`);
 loadLines();loadGlossary()}
async function clip(u){window.open(`/api/tasks/${TID}/lines/${u}/clip`)}
async function loadGlossary(){if(!TID)return;const g=await jf(`/api/tasks/${TID}/glossary`);
 const rows=Object.entries(g.seed).map(([s,m])=>`<tr><td>${s}</td><td>${m[g.lang]||""}</td>
 <td><button class="sec" onclick="delTerm('${s}')">删</button></td></tr>`).join("");
 $("#glossary").innerHTML=`<h2>术语表（注入 M6 上下文；有效 ${Object.keys(g.effective).length} 条）</h2>
 <table><tr><th>源</th><th>译(${g.lang})</th><th></th></tr>${rows}
 <tr><td><input id="g_src" size="8" placeholder="源术语"></td>
 <td><input id="g_tgt" size="12" placeholder="译法"><button onclick="addTerm()">加/改</button></td><td></td></tr></table>`}
async function addTerm(){const s=$("#g_src").value.trim(),t=$("#g_tgt").value.trim();
 await jf(`/api/tasks/${TID}/glossary/${encodeURIComponent(s)}`,{method:"PUT",
 headers:{"Content-Type":"application/json"},body:JSON.stringify({tgt:t})});msg(`术语 ${s}→${t} 已存`);loadGlossary()}
async function delTerm(s){await jf(`/api/tasks/${TID}/glossary/${encodeURIComponent(s)}`,{method:"DELETE"});loadGlossary()}
async function exportAll(){const b=await jf(`/api/tasks/${TID}/export`,{method:"POST",
 headers:{"Content-Type":"application/json"},body:JSON.stringify({})});
 msg("导出: "+JSON.stringify(b.artifacts));loadLines()}
refreshTasks();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# CLI（规划 §4 M13 冻结形态：python -m pipeline.review_server --jobs jobs --port 8080）
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.review_server",
        description="M13 审校台 Web（FastAPI + SQLite，内网使用无鉴权）",
    )
    ap.add_argument("--jobs", default=None,
                    help="jobs 根目录（默认取 configs/pipeline.yaml paths.jobs_dir）")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--db", default=None,
                    help="SQLite 路径（默认 <jobs>/review_console.db）")
    args = ap.parse_args(argv)

    cfg = load_pipeline_config()
    jobs_root = Path(args.jobs) if args.jobs else Path(cfg["paths"]["jobs_dir"])
    import uvicorn

    uvicorn.run(create_app(jobs_root, db_path=args.db),
                host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
