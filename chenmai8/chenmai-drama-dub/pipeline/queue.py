"""M14 任务队列与编排（规划 §4 M14；任务 T20）—— SQLite 队列 + 断点续跑 + 记账。

职责与口径
==========
1. **ep×lang 粒度作业**：一个 job = ``(ep, lang)`` 上以 ``to_step`` 收尾的步骤
   子图。任务（task）粒度按规划冻结表 ``tasks(ep, module, state, deps,
   artifact)`` 落库，增补 ``lang`` 列：``lang=''`` 为 ep 级共享步骤（m1–m5
   一类），多语种作业共享同一行 —— 第二个语种入队时已完成共享步骤直接跳过。
2. **四态机**：``pending(待跑) → running(进行) → done(完成) | failed(失败)``。
   作业四态同枚举。失败步在 resume 时重试（断点续跑语义：修好即续）。
3. **断点续跑**：状态为 done 且产物在位（存在且非空）的任务跳过不重跑；
   产物被清理则降级回 pending 重跑。进程被杀时停在 running 的任务，下次
   resume 按 ``run_id`` 判定为陈旧 → 收回 pending 从断点重跑（单写者 MVP：
   同一批 jobs.db 同时只应有一个队列进程在跑，见下方"并发口径"）。
4. **依赖未满足拒绝执行**：任务的依赖步任一非 done（失败/被拒绝连带）→
   本步拒绝执行（note 记原因，不产生子进程），作业判 failed。
5. **步骤图与服务依赖声明（单一来源）**：``STEP_SPECS`` 声明每步的依赖
   （deps）、产物（artifact 模板）与**外部服务依赖**（``SERVICE_DEPS``，
   如 ``asr-align@9001``）。M13 审校台的单句重生成（m6→m8→m7→m9）与导出
   回路（m11→m9）按规划与本图同源 —— 通过 :func:`subgraph` /
   :func:`service_deps` 导入复用，不另行声明第二份（本批落地时 M13 模块
   尚未入库，故声明唯一来源落在本模块、供其反向复用，契约只增不改名）。
   步骤执行器为数据驱动（``StepSpec.cmd`` argv 模板），可用 ``--graph
   <json>`` 换整张图（eval 用微型桩图验收，零 GPU/零真模型）。
6. **metrics.db 记账 → M15 CallLedger**：每步每次尝试落一行
   ``step_metrics``（墙钟/退出码/声明服务），:func:`ledger_from_metrics_db`
   把账目水合成真实的 :class:`pipeline.m15_metrics._common.CallLedger`
   （子类只增不改名），可直接喂给 M15 成本指标 ``cost.compute`` ——
   全链路逐步耗时的"透传"路径由此闭环（M15 cost 模块 docstring 预留口径）。

CLI（pipeline/cli.py）：``enqueue`` / ``status`` / ``resume``，另按 M14 规格把
T1 骨架的 ``run`` 占位落成 enqueue+resume。

并发口径：MVP 单写者——jobs.db/metrics.db 的写入方只有队列进程自身（步骤
子进程只写各自工作区产物）；多作业可各自 enqueue 后分别 resume。步骤在子
进程内串行执行（依赖序；GPU 服务侧 lip/tts 存在显存互斥，串行即正确性），
"本地进程池"的并行面 = 多作业各自独立进程。

SQL 纪律：全部外部输入经 ``?`` 参数绑定；DDL 为静态常量，无拼接。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

__all__ = [
    "STATE_PENDING", "STATE_RUNNING", "STATE_DONE", "STATE_FAILED",
    "TASK_STATES", "JOB_STATES", "StepSpec", "SERVICE_DEPS",
    "default_graph", "graph_from_file", "validate_graph", "subgraph",
    "service_deps", "QueueError", "QueueUsageError", "Queue",
    "ledger_from_metrics_db", "repo_root",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def repo_root() -> Path:
    """仓库根（步骤子进程的 cwd/PYTHONPATH 基准，保证 `python -m pipeline.*` 可解析）。"""
    return Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 状态机（四态，任务与作业同枚举）
# ---------------------------------------------------------------------------

STATE_PENDING = "pending"    # 待跑
STATE_RUNNING = "running"    # 进行
STATE_DONE = "done"          # 完成
STATE_FAILED = "failed"      # 失败

TASK_STATES = (STATE_PENDING, STATE_RUNNING, STATE_DONE, STATE_FAILED)
JOB_STATES = TASK_STATES


class QueueError(RuntimeError):
    """队列运行期错误（执行失败/依赖拒绝等，CLI → exit 1）。"""


class QueueUsageError(ValueError):
    """用法/入参错误（未知步骤、缺 params 等，CLI → exit 2，不落库）。"""


# ---------------------------------------------------------------------------
# 步骤图与服务依赖声明（单一来源，供 M13 等消费方导入复用）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepSpec:
    """单步声明：命令模板 + 依赖 + 产物模板 + 外部服务依赖。

    ``cmd`` 占位符（仅整 token 精确替换，非 str.format，避免代码串内花括号
    冲突）：``{python}`` `{ep}` ``{lang}`` ``{jobs_dir}`` + ``params`` 键
    （如 ``{input}``）。``artifact`` 为相对 ep 工作区的产物模板（``{lang}``
    渲染；目录型产物=目录内非空即算在位）。``scope``：``ep`` 共享步（任务
    行 lang=''）| ``lang`` 逐语种步。
    """
    id: str
    cmd: tuple[str, ...]
    deps: tuple[str, ...] = ()
    artifact: str = ""
    services: tuple[str, ...] = ()
    scope: str = "lang"                    # "ep" | "lang"
    params_required: tuple[str, ...] = ()  # enqueue 时必须给到的 params 键


#: 外部服务依赖声明（步骤 id → 服务名@端口；单一来源，M13 导入复用）。
#: m6 的 ``mt@9004`` 仅 ``--backend local`` 时强依赖（mock 后端不依赖），
#: 故此表是"该步可能依赖的在线服务"，服务健康检查归消费方按 backend 决定。
SERVICE_DEPS: dict[str, tuple[str, ...]] = {
    "m4": ("asr-align@9001",),
    "m6": ("mt@9004",),
    "m7": ("tts@9002",),
    "m10": ("lip@9003",),
}

#: 生产默认步骤图（与 scripts/e2e_smoke.sh 的链路同序；m12/M12 模块与
#: m13/M13 审校台落地后按"只增"补入本表）：
#:   共享(ep): m1 → m3 → m4 → m2 → m5；逐语种: m6 → m8 → m7 / m11 → m9 → m10 → m15
#: m4 的 CLI 暂无 ``--jobs-dir``（T5 骨架形态），自定 jobs_dir 时用 --graph 覆盖该步。
DEFAULT_GRAPH: dict[str, StepSpec] = {
    "m1": StepSpec(
        "m1",
        ("{python}", "-m", "pipeline.m1_ingest", "--ep", "{ep}",
         "--in", "{input}", "--jobs-dir", "{jobs_dir}"),
        deps=(), artifact="01_media/video_1080x1920_25fps.mp4",
        scope="ep", params_required=("input",),
    ),
    "m3": StepSpec(
        "m3",
        ("{python}", "-m", "pipeline.m3_separate", "--ep", "{ep}",
         "--jobs-dir", "{jobs_dir}"),
        deps=("m1",), artifact="04_dial/vocals.wav", scope="ep",
    ),
    "m4": StepSpec(
        "m4",
        ("{python}", "-m", "pipeline.m4_asr", "--ep", "{ep}"),
        deps=("m3",), artifact="04_dial/asr.jsonl",
        services=SERVICE_DEPS["m4"], scope="ep",
    ),
    "m2": StepSpec(
        "m2",
        ("{python}", "-m", "pipeline.m2_ocr", "--ep", "{ep}",
         "--jobs-dir", "{jobs_dir}"),
        deps=("m1", "m4"), artifact="03_ocr/ocr_merged.jsonl", scope="ep",
    ),
    "m5": StepSpec(
        "m5",
        ("{python}", "-m", "pipeline.m5_diar", "--ep", "{ep}",
         "--jobs-dir", "{jobs_dir}"),
        deps=("m2", "m4"), artifact="04_dial/utterances.jsonl", scope="ep",
    ),
    "m6": StepSpec(
        "m6",
        ("{python}", "-m", "pipeline.m6_translate", "--ep", "{ep}",
         "--lang", "{lang}", "--jobs-dir", "{jobs_dir}"),
        deps=("m5",), artifact="06_mt/translations.jsonl",
        services=SERVICE_DEPS["m6"], scope="lang",
    ),
    "m8": StepSpec(
        "m8",
        ("{python}", "-m", "pipeline.m8_align", "--ep", "{ep}",
         "--lang", "{lang}", "--jobs-dir", "{jobs_dir}"),
        deps=("m6",), artifact="07_synth/synth_plan.{lang}.jsonl", scope="lang",
    ),
    "m7": StepSpec(
        "m7",
        ("{python}", "-m", "pipeline.m7_tts", "--ep", "{ep}",
         "--lang", "{lang}", "--jobs-dir", "{jobs_dir}"),
        deps=("m8",), artifact="07_synth/wavs",
        services=SERVICE_DEPS["m7"], scope="lang",
    ),
    "m11": StepSpec(
        "m11",
        ("{python}", "-m", "pipeline.m11_subs", "--ep", "{ep}",
         "--lang", "{lang}", "--jobs-dir", "{jobs_dir}"),
        deps=("m6",), artifact="10_subs/tgt.{lang}.ass", scope="lang",
    ),
    "m9": StepSpec(
        "m9",
        ("{python}", "-m", "pipeline.m9_mix", "--ep", "{ep}",
         "--lang", "{lang}", "--jobs-dir", "{jobs_dir}"),
        deps=("m7", "m11"), artifact="12_out/{ep}.{lang}.mp4", scope="lang",
    ),
    "m10": StepSpec(
        "m10",
        ("{python}", "-m", "pipeline.m10_lipsync", "--ep", "{ep}",
         "--lang", "{lang}", "--jobs-dir", "{jobs_dir}"),
        deps=("m9",), artifact="09_lip/lip_plan.{lang}.jsonl",
        services=SERVICE_DEPS["m10"], scope="lang",
    ),
    "m15": StepSpec(
        "m15",
        ("{python}", "-m", "pipeline.m15_metrics", "--ep", "{ep}",
         "--lang", "{lang}", "--jobs-dir", "{jobs_dir}"),
        deps=("m10",), artifact="12_out/metrics.json", scope="lang",
    ),
}


def default_graph() -> dict[str, StepSpec]:
    """生产默认步骤图（深拷贝语义：frozen dataclass 共享安全，直接返回）。"""
    return dict(DEFAULT_GRAPH)


def graph_from_file(path: str | Path) -> dict[str, StepSpec]:
    """JSON 步骤图 → {id: StepSpec}（eval/自定义编排入口，字段同 StepSpec）。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise QueueUsageError(f"步骤图文件缺少非空 steps 数组: {path}")
    graph: dict[str, StepSpec] = {}
    for s in steps_raw:
        try:
            spec = StepSpec(
                id=str(s["id"]),
                cmd=tuple(str(x) for x in s["cmd"]),
                deps=tuple(str(x) for x in s.get("deps", ())),
                artifact=str(s.get("artifact", "")),
                services=tuple(str(x) for x in s.get("services", ())),
                scope=str(s.get("scope", "lang")),
                params_required=tuple(str(x) for x in s.get("params_required", ())),
            )
        except KeyError as exc:
            raise QueueUsageError(f"步骤定义缺字段 {exc}: {s}") from exc
        if spec.scope not in ("ep", "lang"):
            raise QueueUsageError(f"步骤 {spec.id} scope 非法: {spec.scope!r}")
        if not spec.cmd:
            raise QueueUsageError(f"步骤 {spec.id} cmd 为空")
        graph[spec.id] = spec
    validate_graph(graph)
    return graph


def validate_graph(graph: dict[str, StepSpec]) -> None:
    """静态校验：依赖已知、无环（全图 Kahn）、共享步不得依赖逐语种步。"""
    for spec in graph.values():
        for dep in spec.deps:
            if dep not in graph:
                raise QueueUsageError(f"步骤 {spec.id} 依赖未知的 {dep!r}")
        if spec.scope == "ep":
            for dep in spec.deps:
                if graph[dep].scope != "ep":
                    raise QueueUsageError(
                        f"共享步 {spec.id} 不得依赖逐语种步 {dep}（scope 单调）")
    indeg = {sid: len(spec.deps) for sid, spec in graph.items()}
    ready = sorted(sid for sid, k in indeg.items() if k == 0)
    seen = 0
    while ready:
        sid = ready.pop(0)
        seen += 1
        for other, spec in graph.items():
            if sid in spec.deps:
                indeg[other] -= 1
                if indeg[other] == 0:
                    ready.append(other)
        ready.sort()
    if seen != len(graph):
        raise QueueUsageError("步骤图存在环（deps 循环依赖）")


def subgraph(graph: dict[str, StepSpec], to_step: str) -> list[StepSpec]:
    """``to_step`` 的祖先闭包（含自身）的依赖序拓扑排列（Kahn）。

    M13 等消费方复用本函数取"某出口前的执行链"，如单句重生成的
    ``subgraph(g, 'm9')`` 与导出的 ``subgraph(g, 'm11')``。
    """
    if to_step not in graph:
        raise QueueUsageError(
            f"未知步骤 {to_step!r}（可用：{', '.join(sorted(graph))}）")
    need: set[str] = set()
    stack = [to_step]
    while stack:
        sid = stack.pop()
        if sid in need:
            continue
        need.add(sid)
        dep = graph[sid].deps
        for d in dep:
            if d not in graph:
                raise QueueUsageError(f"步骤 {sid} 依赖未知的 {d!r}")
            stack.append(d)
    indeg = {sid: sum(1 for d in graph[sid].deps if d in need) for sid in need}
    ready = sorted(sid for sid, k in indeg.items() if k == 0)
    order: list[StepSpec] = []
    while ready:
        sid = ready.pop(0)
        order.append(graph[sid])
        for other in need:
            if sid in graph[other].deps:
                indeg[other] -= 1
                if indeg[other] == 0:
                    ready.append(other)
        ready.sort()
    if len(order) != len(need):
        raise QueueUsageError("步骤图存在环（deps 循环依赖）")
    return order


def service_deps(steps: Iterable[StepSpec]) -> dict[str, tuple[str, ...]]:
    """一组步骤的外部服务依赖视图（M13 导入复用：判断哪些服务须在位）。"""
    return {s.id: s.services for s in steps if s.services}


# ---------------------------------------------------------------------------
# 队列引擎
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ep TEXT NOT NULL,
  lang TEXT NOT NULL,
  to_step TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  params TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(ep, lang, to_step)
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ep TEXT NOT NULL,
  lang TEXT NOT NULL,
  module TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  deps TEXT NOT NULL DEFAULT '[]',
  artifact TEXT NOT NULL DEFAULT '',
  run_id TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  UNIQUE(ep, lang, module)
);
"""

_METRICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS step_metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ep TEXT NOT NULL,
  lang TEXT NOT NULL,
  module TEXT NOT NULL,
  run_id TEXT NOT NULL,
  attempt INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  wall_s REAL NOT NULL,
  exit_code INTEGER NOT NULL,
  services TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_step_metrics_key
  ON step_metrics(ep, lang, module);
"""

_NOTE_MAX = 500


class Queue:
    """SQLite 任务队列（jobs.db 任务表 + metrics.db 记账），单写者 MVP。"""

    def __init__(
        self,
        jobs_dir: str | Path,
        *,
        db_path: str | Path | None = None,
        metrics_db_path: str | Path | None = None,
        graph: Optional[dict[str, StepSpec]] = None,
    ) -> None:
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else self.jobs_dir / "jobs.db"
        self.metrics_db_path = (Path(metrics_db_path) if metrics_db_path
                                else self.jobs_dir / "metrics.db")
        self.graph = graph if graph is not None else default_graph()
        validate_graph(self.graph)
        self.run_id = uuid.uuid4().hex
        self._init_schema()

    # -- 基础 ---------------------------------------------------------------

    def _connect(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        for path, schema in ((self.db_path, _SCHEMA),
                             (self.metrics_db_path, _METRICS_SCHEMA)):
            with self._connect(path) as conn:
                conn.executescript(schema)

    def _ep_dir(self, ep: str) -> Path:
        from pipeline.scaffold import ep_dir

        return ep_dir(ep, self.jobs_dir)  # ep 白名单校验（防路径穿越）

    @staticmethod
    def render(token: str, *, ep: str, lang: str, jobs_dir: Path,
               params: dict[str, str]) -> str:
        """占位符精确替换（整 token；不用 str.format，避免代码串花括号冲突）。"""
        subs = {"{python}": sys.executable, "{ep}": ep, "{lang}": lang,
                "{jobs_dir}": str(Path(jobs_dir).resolve())}
        for key, value in params.items():
            subs["{%s}" % key] = str(value)
        out = token
        for key, value in subs.items():
            if key in out:
                out = out.replace(key, value)
        return out

    # -- 入队 ---------------------------------------------------------------

    def enqueue(self, ep: str, langs: Iterable[str], to_step: str,
                params: Optional[dict[str, str]] = None) -> list[int]:
        """入队 ep×lang 作业（幂等：同 (ep,lang,to_step) 复用既有作业行）。"""
        params = dict(params or {})
        if to_step not in self.graph:
            raise QueueUsageError(
                f"未知步骤 {to_step!r}（可用：{', '.join(sorted(self.graph))}）")
        langs = [str(x).strip() for x in langs if str(x).strip()]
        if not langs:
            raise QueueUsageError("langs 为空（至少一个目标语种）")
        plan = subgraph(self.graph, to_step)
        for spec in plan:
            for key in spec.params_required:
                if not str(params.get(key, "")).strip():
                    raise QueueUsageError(
                        f"步骤 {spec.id} 缺必需参数 --param {key}=...")
        self._ep_dir(ep)  # ep 合法性先行校验（不落任何行）
        ids: list[int] = []
        now = _now()
        with self._connect(self.db_path) as conn:
            for lang in langs:
                row = conn.execute(
                    "SELECT id FROM jobs WHERE ep=? AND lang=? AND to_step=?",
                    (ep, lang, to_step)).fetchone()
                if row is not None:
                    ids.append(int(row["id"]))  # 幂等入队：复用既有作业（断点保留）
                    continue
                try:
                    cur = conn.execute(
                        "INSERT INTO jobs(ep, lang, to_step, state, params,"
                        " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (ep, lang, to_step, STATE_PENDING,
                         json.dumps(params, ensure_ascii=False, sort_keys=True),
                         now, now))
                    ids.append(int(cur.lastrowid))
                except sqlite3.IntegrityError:  # 并发窗口兜底：回头复用
                    row = conn.execute(
                        "SELECT id FROM jobs WHERE ep=? AND lang=? AND to_step=?",
                        (ep, lang, to_step)).fetchone()
                    if row is None:
                        raise
                    ids.append(int(row["id"]))
        for job_id in ids:
            self._ensure_tasks(job_id)
        return ids

    def _job_row(self, job_id: int) -> sqlite3.Row:
        with self._connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise QueueUsageError(f"作业不存在: #{job_id}")
        return row

    def _ensure_tasks(self, job_id: int) -> None:
        """作业闭包内缺失的任务行补齐（既有行不动 —— 断点状态保留）。"""
        job = self._job_row(job_id)
        ep, lang = job["ep"], job["lang"]
        params = json.loads(job["params"])
        plan = subgraph(self.graph, job["to_step"])
        rows = []
        ep_root = self._ep_dir(ep)
        for spec in plan:
            tlang = "" if spec.scope == "ep" else lang
            if spec.artifact:
                art = Path(self.render(spec.artifact, ep=ep, lang=lang,
                                       jobs_dir=self.jobs_dir, params=params))
                if not art.is_absolute():  # 相对模板 → 相对 ep 工作区
                    art = ep_root / art
                artifact = str(art)
            else:
                artifact = ""
            rows.append((ep, tlang, spec.id, STATE_PENDING,
                         json.dumps(list(spec.deps)), artifact, _now()))
        with self._connect(self.db_path) as conn:
            for r in rows:
                # 列序: ep, lang, module, state, deps, artifact, note, updated_at
                conn.execute(
                    "INSERT OR IGNORE INTO tasks(ep, lang, module, state, deps,"
                    " artifact, note, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (*r[:6], "", r[6]))

    # -- 状态 ---------------------------------------------------------------

    def status(self, *, ep: str = "", lang: str = "",
               job_id: int | None = None) -> dict[str, Any]:
        """作业与任务快照（CLI status / --json 数据源）。"""
        q, args = "SELECT * FROM jobs WHERE 1=1", []
        if job_id is not None:
            q += " AND id=?"
            args.append(job_id)
        if ep:
            q += " AND ep=?"
            args.append(ep)
        if lang:
            q += " AND lang=?"
            args.append(lang)
        q += " ORDER BY id"
        with self._connect(self.db_path) as conn:
            jobs = [dict(r) for r in conn.execute(q, args).fetchall()]
            for job in jobs:
                trows = conn.execute(
                    "SELECT * FROM tasks WHERE ep=? AND (lang=? OR lang='') "
                    "ORDER BY id", (job["ep"], job["lang"])).fetchall()
                job["tasks"] = [dict(t) for t in trows]
        return {"jobs": jobs}

    # -- 断点续跑 / 执行 -----------------------------------------------------

    def _reclaim_stale(self, jobs: list[dict[str, Any]]) -> int:
        """被杀进程遗留的 running 任务收回 pending（run_id 非本运行即陈旧）。"""
        n = 0
        now = _now()
        with self._connect(self.db_path) as conn:
            for job in jobs:
                cur = conn.execute(
                    "UPDATE tasks SET state=?, note=?, run_id='', updated_at=?"
                    " WHERE state=? AND run_id<>? AND ep=? AND (lang=? OR lang='')",
                    (STATE_PENDING, "reclaimed: 陈旧 running（上次进程中断）",
                     now, STATE_RUNNING, self.run_id, job["ep"], job["lang"]))
                n += int(cur.rowcount or 0)
        return n

    def resume(self, job_ids: Optional[Iterable[int]] = None, *,
               ep: str = "", lang: str = "",
               all_jobs: bool = False) -> dict[str, Any]:
        """收回陈旧任务并按依赖序续跑（done 且产物在位 → 跳过）。

        退出判定：全部目标作业 done → ``{"ok": True}``；任一 failed → ok=False
        （CLI → exit 1）。
        """
        with self._connect(self.db_path) as conn:
            if all_jobs:
                rows = conn.execute("SELECT * FROM jobs ORDER BY id").fetchall()
            else:
                q, args = "SELECT * FROM jobs WHERE 1=1", []
                if job_ids:
                    ids = [int(x) for x in job_ids]
                    q += " AND id IN (%s)" % ",".join("?" * len(ids))
                    args.extend(ids)
                if ep:
                    q += " AND ep=?"
                    args.append(ep)
                if lang:
                    q += " AND lang=?"
                    args.append(lang)
                if not args:
                    raise QueueUsageError("resume 需 --job/--ep/--all 之一")
                rows = conn.execute(q, args).fetchall()
        jobs = [dict(r) for r in rows]
        if not jobs:
            raise QueueUsageError("没有匹配的作业（先 enqueue，或换过滤条件）")
        reclaimed = self._reclaim_stale(jobs)
        results = []
        ok_all = True
        for job in jobs:
            outcome = self._execute_job(job)
            results.append(outcome)
            ok_all = ok_all and outcome["state"] == STATE_DONE
        return {"ok": ok_all, "reclaimed": reclaimed, "jobs": results,
                "run_id": self.run_id}

    def run(self, ep: str, langs: Iterable[str], to_step: str,
            params: Optional[dict[str, str]] = None) -> dict[str, Any]:
        """M14 规格入口：``run ep01 --langs en --to m12`` = enqueue + resume。"""
        ids = self.enqueue(ep, langs, to_step, params)
        out = self.resume(job_ids=ids)
        out["job_ids"] = ids
        return out

    # -- 单作业执行 ----------------------------------------------------------

    def _task(self, ep: str, tlang: str, module: str) -> Optional[sqlite3.Row]:
        with self._connect(self.db_path) as conn:
            return conn.execute(
                "SELECT * FROM tasks WHERE ep=? AND lang=? AND module=?",
                (ep, tlang, module)).fetchone()

    def _artifact_ok(self, task: dict[str, Any]) -> bool:
        """断点跳过判据：done 任务产物在位（存在且非空；目录=内含非空项）。"""
        art = task.get("artifact") or ""
        if not art:
            return True
        p = Path(art)
        if not p.exists():
            return False
        if p.is_dir():
            return any(f.stat().st_size > 0 for f in p.rglob("*") if f.is_file())
        return p.stat().st_size > 0

    def _execute_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id, ep, lang = job["id"], job["ep"], job["lang"]
        params = json.loads(job["params"])
        plan = subgraph(self.graph, job["to_step"])
        refused: set[str] = set()          # 本轮被拒绝（连带）的共享/语种步
        touched: list[dict[str, Any]] = []
        self._set_job_state(job_id, STATE_RUNNING)
        for spec in plan:
            tlang = "" if spec.scope == "ep" else lang
            task = self._task(ep, tlang, spec.id)
            if task is None:  # 防御：任务行缺失（被外部清理）→ 补建后重取
                self._ensure_tasks(job_id)
                task = self._task(ep, tlang, spec.id)
                if task is None:
                    raise QueueError(f"任务行缺失且补建失败: {ep}/{tlang}/{spec.id}")
            task_d = dict(task)
            key = f"{tlang}:{spec.id}"
            # ① done 且产物在位 → 跳过（断点续跑核心）
            if task_d["state"] == STATE_DONE and self._artifact_ok(task_d):
                touched.append({"module": spec.id, "lang": tlang,
                                "state": STATE_DONE, "skipped": True})
                continue
            # ② done 但产物被清 → 降级重跑
            if task_d["state"] == STATE_DONE:
                self._set_task(ep, tlang, spec.id, state=STATE_PENDING,
                               note="artifact missing → rerun", run_id="",
                               artifact=task_d["artifact"])
                task_d["state"] = STATE_PENDING
            # ③ 依赖未满足 → 拒绝执行（含上游失败/被拒绝的连带）
            dep_unmet: list[str] = []
            for dep in spec.deps:
                dspec = self.graph[dep]
                dlang = "" if dspec.scope == "ep" else lang
                if f"{dlang}:{dep}" in refused:
                    dep_unmet.append(f"{dep}(refused)")
                    continue
                drow = self._task(ep, dlang, dep)
                dstate = drow["state"] if drow else STATE_PENDING
                if dstate != STATE_DONE:
                    dep_unmet.append(f"{dep}({dstate})")
            if dep_unmet:
                refused.add(key)
                self._set_task(ep, tlang, spec.id, state=STATE_FAILED,
                               note="refused: 依赖未满足 " + ",".join(dep_unmet),
                               run_id="", artifact=task_d["artifact"])
                touched.append({"module": spec.id, "lang": tlang,
                                "state": STATE_FAILED, "refused": True,
                                "reason": ",".join(dep_unmet)})
                continue
            # ④ 真执行（子进程；记账；成败落状态）
            res = self._run_step(job, spec, tlang, params)
            touched.append(res)
        # 作业收口
        states = [t["state"] for t in touched]
        final = STATE_DONE if states and all(s == STATE_DONE for s in states) \
            else STATE_FAILED
        self._set_job_state(job_id, final)
        return {"job": job_id, "ep": ep, "lang": lang, "to": job["to_step"],
                "state": final, "tasks": touched}

    def _set_job_state(self, job_id: int, state: str) -> None:
        with self._connect(self.db_path) as conn:
            conn.execute("UPDATE jobs SET state=?, updated_at=? WHERE id=?",
                         (state, _now(), job_id))

    def _set_task(self, ep: str, tlang: str, module: str, *, state: str,
                  note: str = "", run_id: str = "", artifact: str) -> None:
        """任务行更新（静态 SQL + 全参数绑定；artifact 由调用方显式给值）。"""
        with self._connect(self.db_path) as conn:
            conn.execute(
                "UPDATE tasks SET state=?, note=?, run_id=?, artifact=?,"
                " updated_at=? WHERE ep=? AND lang=? AND module=?",
                (state, note[:_NOTE_MAX], run_id, artifact, _now(),
                 ep, tlang, module))

    # -- 步骤子进程与记账 ----------------------------------------------------

    def _bump_attempts(self, ep: str, tlang: str, module: str) -> int:
        """attempts 自增并回读（每次真实尝试记一次，供记账与状态页）。"""
        with self._connect(self.db_path) as conn:
            conn.execute(
                "UPDATE tasks SET attempts=attempts+1 WHERE ep=? AND lang=? AND module=?",
                (ep, tlang, module))
            row = conn.execute(
                "SELECT attempts FROM tasks WHERE ep=? AND lang=? AND module=?",
                (ep, tlang, module)).fetchone()
        return int(row["attempts"] or 0) if row else 0

    def _run_step(self, job: dict[str, Any], spec: StepSpec, tlang: str,
                  params: dict[str, str]) -> dict[str, Any]:
        ep, lang = job["ep"], job["lang"]
        argv = [self.render(tok, ep=ep, lang=lang, jobs_dir=self.jobs_dir,
                            params=params) for tok in spec.cmd]
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        root = str(repo_root())
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        started = _now()
        t0 = time.perf_counter()
        task = self._task(ep, tlang, spec.id)
        artifact = task["artifact"] if task else ""
        self._set_task(ep, tlang, spec.id, state=STATE_RUNNING,
                       note=f"running (run {self.run_id[:8]})",
                       run_id=self.run_id, artifact=artifact)
        self._set_job_state(job["id"], STATE_RUNNING)
        attempt = self._bump_attempts(ep, tlang, spec.id)
        mrow = self._metrics_open(ep, lang if tlang else "", spec.id, attempt,
                                  started, spec.services)
        try:
            proc = subprocess.Popen(
                argv, cwd=root, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace")
            out, err = proc.communicate()
            code = int(proc.returncode or 0)
            tail = (err or out or "").strip()[-_NOTE_MAX:]
        except OSError as exc:
            code, tail = 127, f"spawn failed: {exc}"
        wall = round(time.perf_counter() - t0, 3)
        finished = _now()
        ok = code == 0
        self._metrics_close(mrow, finished, wall, code)
        if ok:
            self._set_task(ep, tlang, spec.id, state=STATE_DONE,
                           note=f"ok (attempt {attempt}, {wall}s)",
                           run_id=self.run_id, artifact=artifact)
        else:
            self._set_task(ep, tlang, spec.id, state=STATE_FAILED,
                           note=f"exit {code}: {tail}",
                           run_id=self.run_id, artifact=artifact)
        return {"module": spec.id, "lang": tlang,
                "state": STATE_DONE if ok else STATE_FAILED,
                "exit_code": code, "wall_s": wall, "attempt": attempt,
                "note": tail}

    def _metrics_open(self, ep: str, lang: str, module: str, attempt: int,
                      started: str, services: tuple[str, ...]) -> int:
        """子进程 spawn 前先插记账行（exit_code=-1 在册），返回行 id。

        落账时机即口径：队列进程被杀时该尝试仍留痕（如实记账：未完成尝试
        ≠ 不存在），而非随进程丢失；完成后由 :meth:`_metrics_close` 回填。
        """
        with self._connect(self.metrics_db_path) as conn:
            cur = conn.execute(
                "INSERT INTO step_metrics(ep, lang, module, run_id, attempt,"
                " started_at, finished_at, wall_s, exit_code, services)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ep, lang, module, self.run_id, attempt, started, "",
                 0.0, -1, json.dumps(list(services), ensure_ascii=False)))
        return int(cur.lastrowid)

    def _metrics_close(self, row_id: int, finished: str, wall: float,
                       code: int) -> None:
        """回填真实退出码/墙钟（被杀尝试无回填 → 恒为 -1 在册）。"""
        with self._connect(self.metrics_db_path) as conn:
            conn.execute(
                "UPDATE step_metrics SET finished_at=?, wall_s=?, exit_code=?"
                " WHERE id=?", (finished, wall, code, row_id))


# ---------------------------------------------------------------------------
# metrics.db → M15 CallLedger 水合（记账对接；契约只增不改名）
# ---------------------------------------------------------------------------

def ledger_from_metrics_db(metrics_db: str | Path, *,
                           ep: str = "", lang: str = "") -> Any:
    """metrics.db 步账目 → M15 :class:`CallLedger`（真实实例，可直接入参）。

    - ``stages``：键 ``module`` 或逐语种 ``module[lang]``（与 e2e 命名同式），
      值 = 该键全部尝试的墙钟累计（含失败重试 —— 真实成本口径）；
    - ``calls``：每行尝试一条（service=声明服务首项或 ``cpu``、
      op=``module#attempt``、seconds=墙钟、ok=退出码 0）；
    - ``wall_total``：各阶段累计和（覆盖会话账本的"本次运行"语义，
      子类只增不改名 —— 父类定义原样保留）；
    - **lang 过滤含共享行**：``lang`` 过滤同时纳入该 ep 的共享步（lang=''）
      —— 产出一个语种成片所摊到的真实成本含 ep 级步骤；跨语种合计时共享步
      会按语种重复计入，属消费方可见的摊提口径选择（此处如实注明）。

    消费示例（M15 成本指标）::

        led = ledger_from_metrics_db(jobs_dir / "metrics.db", ep="ep01", lang="en")
        cost.compute(ws, lang, ep, led, output_duration_s=dur)
    """
    from pipeline.m15_metrics._common import CallLedger

    class MetricsDbLedger(CallLedger):
        """水合账本：wall_total = 全阶段累计（历史口径），其余语义同父类。"""

        def __init__(self, stages: dict[str, float], calls: list[dict[str, Any]]):
            super().__init__()
            self.stages = stages
            self.calls = calls

        @property
        def wall_total(self) -> float:  # type: ignore[override]
            return round(sum(self.stages.values()), 3)

    if not Path(metrics_db).is_file():
        raise QueueError(f"metrics.db 不存在: {metrics_db}")
    stages: dict[str, float] = {}
    calls: list[dict[str, Any]] = []
    q = ("SELECT ep, lang, module, attempt, wall_s, exit_code, services"
         " FROM step_metrics WHERE 1=1")
    args: list[Any] = []
    if ep:
        q += " AND ep=?"
        args.append(ep)
    if lang:
        q += " AND (lang=? OR lang='')"  # 共享步摊入该语种成本
        args.append(lang)
    q += " ORDER BY id"
    conn = sqlite3.connect(str(metrics_db))
    conn.row_factory = sqlite3.Row
    try:
        for r in conn.execute(q, args).fetchall():
            key = r["module"] if not r["lang"] else f"{r['module']}[{r['lang']}]"
            stages[key] = round(stages.get(key, 0.0) + float(r["wall_s"]), 3)
            services = json.loads(r["services"] or "[]")
            calls.append({
                "service": services[0] if services else "cpu",
                "op": f"{r['module']}#{r['attempt']}",
                "seconds": round(float(r["wall_s"]), 3),
                "ok": int(r["exit_code"]) == 0,
                "note": f"{r['ep']}/{r['lang'] or '-'}",
            })
    finally:
        conn.close()
    return MetricsDbLedger(stages, calls)
