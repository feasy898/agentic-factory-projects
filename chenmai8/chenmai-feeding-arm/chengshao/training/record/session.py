"""录制会话共享件（chengshao.training.record.session）。

职责（record/ 各采集脚本共用）：
- **机器人学习运行栈数据集格式**（中性名，命名纪律：训练框架原名不入仓库
  文本，check_naming.py 把关）的写入与结构校验：meta/（info.json、
  episodes.jsonl、tasks.jsonl）+ data/chunk-XXX/episode_YYYYYY.parquet
  （状态/动作表）+ videos/chunk-XXX/<cam_key>/episode_YYYYYY.mp4（双路相机）；
- 合成相机帧生成（mock dry-run 用，确定性、无随机数）；
- mock 执行环境搭建（MockArm + SafetyEnvelope + VirtualClock，全链与
  cs_arm 一致：一切指令经包络）；
- 硬件会话门（CS_HW_SESSION=1 + 设备就绪，缺失一律显式失败 exit 2，
  占位即契约：不假装成功）。

格式校验口径（如实声明）：``validate_dataset`` 是**本仓库自带的结构自检**
（对齐训练框架装载所需的最小结构不变式：feature 形状/维度、episode 行数
对账、任务表、视频文件在位）；终验以 GPU 机训练框架实际装载数据集通过
为准（runbook_gpu.md / runbook_3060.md 记录该步骤）。

退出码约定（与 training.common 一致）：0=成功；1=数据集校验未过；2=参数/
硬件纪律拒绝。
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np

from chengshao.cs_schema import N_ARM_JOINTS  # noqa: E402
from chengshao.training.common import (  # noqa: E402
    ConfigError,
    dump_json,
    safe_rel_output,
    utc_now_iso,
)

_MODULE = "training.record.session"

# ---- 格式常量（训练框架数据集布局；中性名引用，结构如实对齐） ----------------
CODEBASE_VERSION = "v2.1"  # 训练框架数据集布局版本（装载端要求写入 info.json）
CHUNK_SIZE = 1000  # 每 chunk 的回合数（chunk-XXX 目录名 = episode//1000）
RESOLUTION = (640, 480)  # 录制协议 §1.2：640×480（W×H）
VALID_CAMS = ("scene", "wrist")  # 双路相机键（场景/腕部）
ROBOT_TYPE = "chengshao_follower"  # 中性机器人类型名（单从臂，无主臂）

STATE_FEATURE = "observation.state"
ACTION_FEATURE = "action"
CAM_FEATURE_PREFIX = "observation.images."
# parquet 表列（布局 v2.1：状态/动作 + 回合记账列；相机帧走视频通道不进表）
PARQUET_COLUMNS = (
    STATE_FEATURE, ACTION_FEATURE, "timestamp", "frame_index",
    "episode_index", "index", "task_index",
)


def cam_feature(cam: str) -> str:
    return f"{CAM_FEATURE_PREFIX}{cam}"


def chunk_dir(episode_index: int) -> str:
    return f"chunk-{episode_index // CHUNK_SIZE:03d}"


def episode_file(episode_index: int, suffix: str) -> str:
    return f"episode_{episode_index:06d}{suffix}"


# ---------------------------------------------------------------------------
# 合成相机帧（mock dry-run；确定性：只依赖 cam/t_s/frame_index）
# ---------------------------------------------------------------------------

def synthesize_frame(cam: str, t_s: float, frame_index: int,
                     size: tuple[int, int] = RESOLUTION) -> np.ndarray:
    """确定性合成 BGR 帧：背景网格 + 碗（固定椭圆）+ 勺尖（随 t 的弧线）。

    cam="scene"：广角看碗/勺；cam="wrist"：近距特写（勺尖居中放大）。
    仿真数据仅用于格式链路 dry-run，不代表真实视觉内容。
    """
    w, h = size
    img = np.full((h, w, 3), 235, dtype=np.uint8)
    # 背景网格（32px 格），颜色随帧号微移以便肉眼区分连续帧
    off = int(frame_index % 32)
    for x in range(-off, w, 32):
        img[:, max(0, x):max(0, x) + 1] = (205, 205, 205)
    for y in range(-off, h, 32):
        img[max(0, y):max(0, y) + 1, :] = (205, 205, 205)

    import cv2

    phase = float(np.clip(math.sin(max(0.0, t_s) * 0.8), -1.0, 1.0) * 0.5 + 0.5)
    if cam == "scene":
        cx, cy = int(w * 0.62), int(h * 0.70)
        cv2.ellipse(img, (cx, cy), (70, 28), 0, 0, 360, (60, 70, 160), -1)
        sx = int(w * (0.25 + 0.45 * phase))
        sy = int(h * (0.30 + 0.38 * phase))
        cv2.circle(img, (sx, sy), 9, (40, 40, 40), -1)
    elif cam == "wrist":
        sx, sy = int(w * 0.5), int(h * 0.5)
        cv2.circle(img, (sx, sy), 14, (40, 40, 40), -1)
        cv2.circle(img, (sx + 6, sy - 4), int(4 + 6 * phase), (90, 140, 230), -1)
        cv2.rectangle(img, (0, h - 26), (w, h), (30, 30, 30), -1)
    else:  # pragma: no cover - 参数校验层已拦截
        raise ConfigError(f"未知相机键：{cam!r}")
    cv2.putText(img, f"{cam} f={frame_index} t={t_s:.2f}s", (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)
    return img


# ---------------------------------------------------------------------------
# 数据集写入（回合缓冲 → parquet + mp4 + meta）
# ---------------------------------------------------------------------------

@dataclass
class EpisodeBuffer:
    """单回合录制缓冲：状态/动作/时间戳 + 双路相机帧 + 事件下标。"""

    episode_index: int
    states: list[list[float]] = field(default_factory=list)
    actions: list[list[float]] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)
    images: dict[str, list[np.ndarray]] = field(default_factory=dict)
    events: dict[str, list[int]] = field(default_factory=dict)

    def add_step(self, state: list[float], action: list[float], t_s: float,
                 images: dict[str, np.ndarray]) -> int:
        if len(state) != N_ARM_JOINTS or len(action) != N_ARM_JOINTS:
            raise ConfigError(
                f"state/action 必须 {N_ARM_JOINTS} 维：{len(state)}/{len(action)}")
        self.states.append([float(v) for v in state])
        self.actions.append([float(v) for v in action])
        self.timestamps.append(float(t_s))
        for cam, img in images.items():
            self.images.setdefault(cam, []).append(img)
        return len(self.states) - 1

    def mark(self, event: str, frame_index: int) -> None:
        self.events.setdefault(event, []).append(int(frame_index))

    @property
    def length(self) -> int:
        return len(self.states)


class DatasetWriter:
    """训练框架数据集布局写入器（先回合缓冲、finish 后统一落 meta）。

    用法::

        w = DatasetWriter(root, task="...", cams=("scene", "wrist"))
        w.start_episode(0); w.add_step(...); w.mark("scoop_done", i)
        w.finish_episode()          # 写 parquet + mp4
        w.finalize()                # 写 meta/（info/episodes/tasks）
    """

    def __init__(self, root: Path | str, *, task: str, cams: list[str],
                 fps: float, joint_names: list[str],
                 resolution: tuple[int, int] = RESOLUTION) -> None:
        if not cams or not set(cams) <= set(VALID_CAMS):
            raise ConfigError(f"cams 必须为 {VALID_CAMS} 的非空子集：{cams}")
        if fps <= 0:
            raise ConfigError(f"fps 必须为正：{fps}")
        if len(joint_names) != N_ARM_JOINTS:
            raise ConfigError(f"joint_names 必须 {N_ARM_JOINTS} 维")
        self.root = Path(root)
        self.task = task
        self.cams = list(cams)
        self.fps = float(fps)
        self.joint_names = list(joint_names)
        self.resolution = tuple(resolution)
        self._episodes: list[dict[str, Any]] = []
        self._buffer: EpisodeBuffer | None = None
        self._events: dict[str, dict[str, list[int]]] = {}
        self._global_index = 0
        self._data_bytes = 0
        self._video_bytes = 0

    # ---- 回合生命周期 ---------------------------------------------------------

    def start_episode(self, episode_index: int) -> EpisodeBuffer:
        if self._buffer is not None:
            raise ConfigError("上一回合未 finish_episode()")
        self._buffer = EpisodeBuffer(episode_index=episode_index)
        return self._buffer

    def finish_episode(self) -> dict[str, Any]:
        buf = self._buffer
        if buf is None:
            raise ConfigError("未 start_episode()")
        if buf.length == 0:
            raise ConfigError(f"episode {buf.episode_index} 为空（0 步），拒绝落盘")
        self._write_parquet(buf)
        for cam in self.cams:
            frames = buf.images.get(cam, [])
            if len(frames) != buf.length:
                raise ConfigError(
                    f"episode {buf.episode_index} 相机 {cam} 帧数({len(frames)})"
                    f"≠ 步数({buf.length})")
            self._write_video(buf, cam, frames)
        entry = {
            "episode_index": buf.episode_index,
            "tasks": [self.task],
            "length": buf.length,
        }
        self._episodes.append(entry)
        if buf.events:
            self._events[str(buf.episode_index)] = buf.events
        self._buffer = None
        return entry

    def discard_episode(self) -> None:
        """丢弃当前未完成回合缓冲（操作者中止时用；已落盘回合不受影响）。"""
        if self._buffer is None:
            raise ConfigError("没有进行中的回合缓冲可丢弃")
        self._buffer = None

    def finalize(self) -> Path:
        if self._buffer is not None:
            raise ConfigError("仍有未 finish 的回合缓冲")
        self.root.mkdir(parents=True, exist_ok=True)
        video_feats = sum(1 for _ in self.cams)
        info = {
            "codebase_version": CODEBASE_VERSION,
            "robot_type": ROBOT_TYPE,
            "total_episodes": len(self._episodes),
            "total_frames": sum(e["length"] for e in self._episodes),
            "total_tasks": 1,
            "total_videos": len(self._episodes) * video_feats,
            "total_chunks": max(1, math.ceil(max(1, len(self._episodes)) / CHUNK_SIZE)),
            "chunks_size": CHUNK_SIZE,
            "fps": self.fps,
            "data_files_size_in_mb": round(self._data_bytes / 1e6, 3),
            "video_files_size_in_mb": round(self._video_bytes / 1e6, 3),
            "splits": ["train"],
            "features": self._features(),
        }
        info_path = self.root / "meta" / "info.json"
        dump_json(info_path, info)
        self._write_jsonl(self.root / "meta" / "episodes.jsonl", self._episodes)
        self._write_jsonl(self.root / "meta" / "tasks.jsonl",
                          [{"task_index": 0, "task": self.task}])
        if self._events:
            # 本仓库扩展 sidecar（训练装载不读）：帧下标事件，供
            # spoon_cls/prepare_data 自动标注与人工质检对账。
            dump_json(self.root / "meta" / "record_events.json", {
                "$comment": "本仓库扩展：episode→事件→帧下标（训练装载不读）",
                "events": self._events,
            })
        return info_path.parent.parent

    # ---- 内部写入 -------------------------------------------------------------

    def _features(self) -> dict[str, Any]:
        names = {"dtype": "float32", "shape": [N_ARM_JOINTS],
                 "names": list(self.joint_names)}
        feats: dict[str, Any] = {
            STATE_FEATURE: dict(names),
            ACTION_FEATURE: dict(names),
        }
        for cam in self.cams:
            feats["observation.images." + cam] = {
                "dtype": "video",
                "shape": [self.resolution[1], self.resolution[0], 3],
                "names": None,
            }
        for key, dtype in (("timestamp", "float64"), ("frame_index", "int64"),
                           ("episode_index", "int64"), ("index", "int64"),
                           ("task_index", "int64")):
            feats[key] = {"dtype": dtype, "shape": [1], "names": None}
        return feats

    def _write_parquet(self, buf: EpisodeBuffer) -> Path:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:  # 占位即契约：缺依赖显式失败
            raise ConfigError(
                "写数据集需要 pyarrow（训练侧依赖，requirements-gpu.txt 栈自带）；"
                f"当前环境缺失：{exc}") from exc
        n = buf.length
        table = pa.table({
            STATE_FEATURE: pa.array(buf.states, type=pa.list_(pa.float32(), N_ARM_JOINTS)),
            ACTION_FEATURE: pa.array(buf.actions, type=pa.list_(pa.float32(), N_ARM_JOINTS)),
            "timestamp": pa.array(buf.timestamps, type=pa.float64()),
            "frame_index": pa.array(list(range(n)), type=pa.int64()),
            "episode_index": pa.array([buf.episode_index] * n, type=pa.int64()),
            "index": pa.array([self._global_index + i for i in range(n)], type=pa.int64()),
            "task_index": pa.array([0] * n, type=pa.int64()),
        })
        out_dir = self.root / "data" / chunk_dir(buf.episode_index)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / episode_file(buf.episode_index, ".parquet")
        pq.write_table(table, out)
        self._global_index += n
        self._data_bytes += out.stat().st_size
        return out

    def _write_video(self, buf: EpisodeBuffer, cam: str,
                     frames: list[np.ndarray]) -> Path:
        import cv2

        out_dir = self.root / "videos" / chunk_dir(buf.episode_index) / cam_feature(cam)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / episode_file(buf.episode_index, ".mp4")
        w, h = self.resolution
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"),
                                 self.fps, (w, h))
        if not writer.isOpened():
            raise ConfigError(
                f"视频编码器不可用（mp4v {w}x{h}@{self.fps}）：{out}——"
                "检查 OpenCV 构建是否带 ffmpeg 后端")
        try:
            for img in frames:
                if img.shape[:2] != (h, w):
                    img = cv2.resize(img, (w, h))
                if img.ndim == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                writer.write(np.ascontiguousarray(img))
        finally:
            writer.release()
        self._video_bytes += out.stat().st_size
        return out

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 结构校验（本仓库自检口径；终验以 GPU 机训练框架装载为准）
# ---------------------------------------------------------------------------

def validate_dataset(root: Path | str, *,
                     state_dim: int = N_ARM_JOINTS) -> dict[str, Any]:
    """校验数据集目录结构，返回报告 dict（含 ``ok`` 与逐项 checks）。"""
    from chengshao.training.common import load_json

    root = Path(root)
    checks: dict[str, bool] = {}
    errors: list[str] = []

    def require(name: str, cond: bool, msg: str) -> None:
        checks[name] = bool(cond)
        if not cond:
            errors.append(msg)

    info_path = root / "meta" / "info.json"
    require("info_json_exists", info_path.is_file(), f"缺 {info_path}")
    if not info_path.is_file():
        return {"ok": False, "root": str(root), "checks": checks, "errors": errors}
    info = load_json(info_path)
    require("codebase_version", info.get("codebase_version") == CODEBASE_VERSION,
            f"codebase_version 应为 {CODEBASE_VERSION}：{info.get('codebase_version')!r}")
    fps = info.get("fps")
    require("fps_positive", isinstance(fps, (int, float)) and fps > 0, f"fps 非法：{fps!r}")
    feats = info.get("features") or {}
    for key in (STATE_FEATURE, ACTION_FEATURE):
        f = feats.get(key) or {}
        require(f"{key}_dim", list(f.get("shape") or []) == [state_dim],
                f"{key}.shape 应为 [{state_dim}]，实际 {f.get('shape')!r}")
    cams = [k[len(CAM_FEATURE_PREFIX):] for k in feats
            if k.startswith(CAM_FEATURE_PREFIX)]
    require("cams_present", bool(cams), "info.features 缺相机视频 feature")

    episodes = _read_jsonl(root / "meta" / "episodes.jsonl")
    tasks = _read_jsonl(root / "meta" / "tasks.jsonl")
    require("episodes_nonempty", bool(episodes), "meta/episodes.jsonl 为空")
    require("tasks_nonempty", bool(tasks), "meta/tasks.jsonl 为空")
    require("total_episodes_match",
            info.get("total_episodes") == len(episodes),
            f"total_episodes({info.get('total_episodes')})≠episodes.jsonl({len(episodes)})")
    total_frames = sum(int(e.get("length", 0)) for e in episodes)
    require("total_frames_match", info.get("total_frames") == total_frames,
            f"total_frames({info.get('total_frames')})≠Σlength({total_frames})")
    n_video_feats = max(1, len(cams))
    require("total_videos_match",
            info.get("total_videos") == len(episodes) * n_video_feats,
            f"total_videos({info.get('total_videos')})≠episodes×cams"
            f"({len(episodes)}×{n_video_feats})")

    frames_ok, vids_ok, cols_ok, dims_ok = True, True, True, True
    for e in episodes:
        ei = int(e["episode_index"])
        p = root / "data" / chunk_dir(ei) / episode_file(ei, ".parquet")
        if not p.is_file():
            frames_ok = False
            errors.append(f"缺回合数据文件：{p}")
            continue
        rows = _read_parquet_rows(p)
        if rows is None or rows.get("n_rows") != int(e["length"]):
            frames_ok = False
            errors.append(f"episode {ei} 行数对账失败：{rows}")
            continue
        if not set(PARQUET_COLUMNS) <= set(rows["columns"]):
            cols_ok = False
            errors.append(f"episode {ei} 缺列："
                          f"{sorted(set(PARQUET_COLUMNS) - set(rows['columns']))}")
        for key in (STATE_FEATURE, ACTION_FEATURE):
            if rows.get(f"{key}_dim") != state_dim:
                dims_ok = False
                errors.append(f"episode {ei} {key} 维度={rows.get(f'{key}_dim')}")
        for cam in cams:
            v = root / "videos" / chunk_dir(ei) / cam_feature(cam) / episode_file(ei, ".mp4")
            if not v.is_file() or v.stat().st_size == 0:
                vids_ok = False
                errors.append(f"缺回合视频：{v}")
    require("episode_parquet_ok", frames_ok and cols_ok and dims_ok,
            "回合数据文件对账见 errors")
    require("episode_videos_ok", vids_ok, "回合视频文件见 errors")

    return {
        "ok": not errors,
        "root": str(root),
        "format": f"robot-learning-runtime-dataset {CODEBASE_VERSION}（中性名）",
        "episodes": len(episodes),
        "frames": total_frames,
        "cams": cams,
        "fps": fps,
        "checks": checks,
        "errors": errors[:20],
        "validated_at": utc_now_iso(),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _read_parquet_rows(path: Path) -> dict[str, Any] | None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return None
    try:
        pf = pq.ParquetFile(path)
    except Exception:  # noqa: BLE001 - 损坏文件按对账失败处理
        return None
    schema = pf.schema_arrow
    out: dict[str, Any] = {"n_rows": pf.metadata.num_rows,
                           "columns": [f.name for f in schema]}
    by_name = {f.name: f for f in schema}
    for key in (STATE_FEATURE, ACTION_FEATURE):
        f = by_name.get(key)
        if f is None:
            out[f"{key}_dim"] = None
        elif isinstance(f.type, pa.FixedSizeListType):
            out[f"{key}_dim"] = int(f.type.list_size)
        else:
            out[f"{key}_dim"] = -1  # 变长 list：维度不受约束（对齐口径按固定长写）
    return out


# ---------------------------------------------------------------------------
# mock 执行环境与硬件门
# ---------------------------------------------------------------------------

def build_mock_env(seed: int = 1000):
    """MockArm + SafetyEnvelope + VirtualClock（零硬件、确定性、全链经包络）。

    返回 (envelope, clock, model)；使能由调用方负责（enable/disable 成对）。
    ``seed`` 仅作签名占位（MockArm 本身确定性）；保留便于真机路径对齐。
    """
    from chengshao.cs_arm import MockArm, SafetyEnvelope, VirtualClock

    clock = VirtualClock()
    arm = MockArm(clock=clock)
    env = SafetyEnvelope(arm, model=arm.model, clock=clock,
                         watchdog_timeout_s=0.5)
    return env, clock, arm.model


def require_hw_session(script: str) -> None:
    """硬件会话门：未放行 CS_HW_SESSION=1 一律拒绝（exit 2，fail-closed）。"""
    import os

    if os.environ.get("CS_HW_SESSION") != "1":
        print(f"[training] 拒绝：{script} 真实采集需硬件会话放行"
              "（CS_HW_SESSION=1）+ cs_arm 接口与相机就绪；构建期本机不采数。",
              file=sys.stderr)
        raise SystemExit(2)


def open_camera(dev: int, size: tuple[int, int] = RESOLUTION):
    """打开 V4L2/ DirectShow 相机；失败返回 None（调用方 fail-closed）。"""
    import cv2

    cap = cv2.VideoCapture(int(dev), cv2.CAP_ANY)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
    cap.set(cv2.CAP_PROP_FPS, 30.0)
    return cap


def capture_frame(cap: Any, cam: str) -> np.ndarray:
    """从真实相机抓一帧 BGR；抓帧失败抛 ConfigError（不补合成帧冒充）。"""
    ok, img = cap.read()
    if not ok or img is None:
        raise ConfigError(f"相机 {cam} 抓帧失败（不合成数据冒充真实帧）")
    return img


def emit_report(path: Path | str, *, module: str, cmd: str,
                metrics: dict[str, Any], thresholds: dict[str, Any],
                passed: bool) -> Path:
    """§10.2 证据报告（training.common.write_report 的录制侧转接）。"""
    from chengshao.training.common import write_report

    return write_report(path, module=module, cmd=cmd, metrics=metrics,
                        thresholds=thresholds, passed=passed)


def resolve_out_dir(value: str | None, default: str, *, field_name: str) -> Path:
    """仓库相对输出目录解析（safe_rel_output 包装；data/ 不进 git）。"""
    return safe_rel_output(str(value) if value else default, field=field_name)


# ---- CLI：数据集结构自检入口 ------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.record.session",
        description="训练框架数据集布局结构自检（本仓库口径；终验以 GPU 机装载为准）")
    parser.add_argument("--validate", type=Path, required=True,
                        help="待校验的数据集根目录")
    parser.add_argument("--report", type=Path, default=None,
                        help="§10.2 证据报告输出路径（缺省只打印）")
    args = parser.parse_args(argv)
    if not Path(args.validate).is_dir():
        print(f"[training] 错误：数据集目录不存在：{args.validate}", file=sys.stderr)
        return 2
    report = validate_dataset(args.validate)
    print("VALIDATE:", report)
    if args.report is not None:
        emit_report(args.report, module=_MODULE,
                    cmd=f"python -m chengshao.training.record.session --validate {args.validate}",
                    metrics={k: v for k, v in report.items() if k != "checks"},
                    thresholds={"structure_ok": True},
                    passed=report["ok"])
        print(f"REPORT: {args.report}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
