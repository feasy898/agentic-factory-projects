"""M10 按镜头分流口型（规划 §4 M10）—— lip_plan 分流 + GPU 服务客户端 + 回贴合成。

职责（只读写 09_lip/ 一层 + 跨层只读 M5/C2/M9 产物；交换只经冻结契约）：
  ① lip_plan 分流（契约 C6）：消费 M5 正脸近景镜头表（``02_shots/
     frontal_closeups.json``，M5 模块级产物）与 C2 ``face`` 事实——
     ``shot ∈ 正脸近景表 && face.frontal && face.closeup && !overlap``
     才入口型（:func:`pipeline.contracts.lip_eligible` + 镜头表硬门槛）；
     台词最长前 10%（``pipeline.yaml lip.pro_top_ratio``）与 ``--pro-shots``
     显式清单升级精口型（lip-pro，models.yaml routing.lip.top10pct）；
     其余合格镜头快口型（lip-fast），不合格镜头不出现在计划里 = 原画。
  ② GPU 服务客户端（:9003，本机经 ops/tunnel_gpu.sh 隧道）：视频段（帧数=
     时间真相）+ 该窗配音（16k wav）→ 同帧数口型再生成视频段（mp4 b64）。
     执行按 models.yaml ``components.<engine>.fallback`` 冻结降级链：重点
     镜头 lip-pro 权重未部署（TBD-D1）→ 服务 503 → 依注册表降级
     lip-pro-1.5 → lip-fast（降质不弃做），链逐节点失败记入 attempts
     如实上报，链尾 lip-fast 失败 = 硬错误，不静默伪装。
  ③ 回贴合成：源视频逐帧 raw yuv420p 解码 → 窗内帧替换为服务产出帧、
     窗外帧原字节透传 → 无损 x264（qp=0）重封装 → ``09_lip/done/
     <ep>.<lang>.lip.mp4``。**帧哈希自验**（:func:`verify_paste_back`）：
     非口型帧 raw yuv sha256 逐帧全等（字节级零改动）、口型窗帧全不同
     且嘴区像素变化量 ≥ 阈值（口型确实动了）——不过即 FAIL，不出假交付。

时间口径：C6 ``window`` 为全片绝对秒（C2 同轴）；帧域映射
``f0=round(window[0]×fps)``、``f1=round(window[1]×fps)``，抽段/回贴全部
以帧号为基准（秒域 seek 只用帧栅格点 f/fps，规避 -ss 舍入漂移）。

CLI（规划 §4 M10 冻结形态）::

    python -m pipeline.m10_lipsync --ep ep01 --lang en [--pro-shots s0007,s0012]
        [--source <mp4>] [--audio <wav>] [--url ...] [--jobs-dir <dir>]
        [--no-verify] [--work-dir <dir>]

退出码：0 成功（含自验通过）；1 输入/服务/自验错误；2 用法错误。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx

from pipeline import contracts as C
from pipeline.config import CONFIG_DIR, load_pipeline_config, load_yaml
from pipeline.scaffold import create_workspace, ep_dir

__all__ = [
    "run", "main", "LipError", "LipClient", "lip_response_to_video",
    "build_lip_plan", "window_to_frames", "frame_hashes",
    "splice_segments", "verify_paste_back", "extract_video_segment",
    "extract_audio_segment", "engine_fallback_chain",
]

#: 服务地址环境变量 → 默认值（本机经 ops/tunnel_gpu.sh 隧道访问 GPU :9003）
SERVICE_ENV = ("M10_LIP_URL", "http://127.0.0.1:9003")
#: 引擎名（models.yaml routing.lip 冻结镜像的兜底字面量；注册表为准）
ENGINE_FAST = "lip-fast"
ENGINE_PRO = "lip-pro"
#: 首载/排队余量（引擎常驻；预处理+批量生成随窗长线性）
DEFAULT_TIMEOUT_S = 600.0
#: 队列长度上限（防上传体量失控）
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
#: 嘴区变化量冻结线（窗口内 face bbox 下半区像素平均绝对差；crf18 重编码
#: 噪声实测 <1.5 灰阶，口型开合变化为数十灰阶——3.0 取数量级分隔）
MIN_MOUTH_MAD = 3.0


class LipError(RuntimeError):
    """M10 执行错误（输入缺失/服务失败/自验不过均归一为该异常）。"""


def engine_fallback_chain(engine: str, models_cfg: Optional[dict] = None) -> list[str]:
    """引擎 → 执行降级链（models.yaml ``components.<engine>.fallback`` 冻结镜像）。

    例：lip-pro → ``["lip-pro", "lip-pro-1.5", "lip-fast"]``（注册表 fallback
    依序展开）；lip-fast → ``["lip-fast"]``。链尾必为 lip-fast——精口型不可用
    时按注册表降级到快口型执行（重点镜头降质不弃做）；未登记引擎原样返回。
    """
    cfg = models_cfg if models_cfg is not None else load_yaml(CONFIG_DIR / "models.yaml")
    comps = cfg.get("components", {})
    chain: list[str] = [engine]
    seen = {engine}
    node = engine
    while node in comps:
        fb = (comps[node] or {}).get("fallback") or []
        if not fb:
            break
        nxt = str(fb[0])
        if nxt in seen:
            break
        chain.append(nxt)
        seen.add(nxt)
        node = nxt
    return chain


# ---------------------------------------------------------------------------
# ① lip_plan 分流（契约 C6）
# ---------------------------------------------------------------------------

def _frontal_closeup_table(ws: Path) -> dict[str, dict[str, Any]]:
    """M5 正脸近景镜头表 → {shot_id: 行}。缺席即硬错误（C6 硬门槛的数据源）。"""
    path = ws / "02_shots" / "frontal_closeups.json"
    if not path.is_file():
        raise LipError(
            f"M5 正脸近景镜头表不存在: {path}（先跑 python -m pipeline.m5_diar "
            "--ep <ep>——C6 分流以该表为硬门槛，无表不分流）")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {row["shot_id"]: row for row in doc.get("shots", [])}


def build_lip_plan(
    ep: str,
    lang: str,
    *,
    jobs_dir: str | Path | None = None,
    cfg: dict | None = None,
    models_cfg: dict | None = None,
    pro_shots: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """生成 C6 ``09_lip/lip_plan.<lang>.jsonl``（整表重建，幂等）。

    C6 schema 无语种字段，窗=原始句窗；按语种分文件与 C5 同口径
    （m8_align._synth_plan_name 惯例），同时刷新无后缀当前语种副本。
    返回摘要 dict。
    """
    cfg = cfg if cfg is not None else load_pipeline_config()
    root = Path(jobs_dir) if jobs_dir else Path(cfg["paths"]["jobs_dir"])
    ws = ep_dir(ep, root)
    utt_path = ws / "04_dial" / "utterances.jsonl"
    if not utt_path.is_file():
        raise LipError(f"C2 不存在: {utt_path}（M2/M4/M5 链路先行）")
    fc = _frontal_closeup_table(ws)
    utterances = C.load_jsonl(utt_path, C.UtteranceTable).root

    eligible_shots = {sid for sid, row in fc.items()
                      if row.get("frontal") and row.get("closeup")}
    lip_cfg = cfg.get("lip") or {}
    top_ratio = float(lip_cfg.get("pro_top_ratio", 0.10))
    routing = ((models_cfg or load_yaml(CONFIG_DIR / "models.yaml"))
               .get("routing", {}).get("lip", {}))
    eng_fast = str(routing.get("frontal_closeup", ENGINE_FAST))
    eng_pro = str(routing.get("top10pct", ENGINE_PRO))

    rows: list[C.LipPlanItem] = []
    skipped: list[dict[str, Any]] = []
    for u in utterances:
        if u.shot_id not in eligible_shots or not C.lip_eligible(u):
            skipped.append({"utt_id": u.utt_id, "shot_id": u.shot_id,
                            "reason": "not_frontal_closeup_or_overlap"})
            continue
        rows.append(u)  # 占位：先收集，排序升级在下一步
    # 重点镜头：台词最长前 top_ratio（同镜多句按句长独立参与排序）
    pro_set = set(pro_shots)
    pro_cut: Optional[float] = None
    if rows:
        durs = sorted((u.end - u.start for u in rows), reverse=True)
        k = max(1, int(round(len(durs) * top_ratio)))
        pro_cut = durs[k - 1]  # 达到该句长即升级（并列全升）

    plan_rows: list[C.LipPlanItem] = []
    for u in rows:
        is_pro = u.shot_id in pro_set or (pro_cut is not None
                                          and (u.end - u.start) >= pro_cut - 1e-9)
        plan_rows.append(C.LipPlanItem(
            utt_id=u.utt_id, shot_id=u.shot_id,
            engine=eng_pro if is_pro else eng_fast,
            priority="pro" if is_pro else "normal",
            window=[u.start, u.end], face_track=0))
    plan_rows.sort(key=lambda r: (r.window[0], r.utt_id))

    main_name = f"lip_plan.{lang}.jsonl"
    plan_path = ws / "09_lip" / main_name
    C.dump_jsonl(plan_path, C.LipPlanTable.model_validate(
        [r.model_dump() for r in plan_rows]))
    copy_path = ws / "09_lip" / "lip_plan.jsonl"
    C.dump_jsonl(copy_path, C.LipPlanTable.model_validate(
        [r.model_dump() for r in plan_rows]))
    return {
        "ep": ep, "lang": lang,
        "plan_path": str(plan_path), "copy_path": str(copy_path),
        "n_utterances": len(utterances),
        "n_eligible": len(plan_rows),
        "n_fast": sum(1 for r in plan_rows if r.engine == eng_fast),
        "n_pro": sum(1 for r in plan_rows if r.engine == eng_pro),
        "n_skipped": len(skipped),
        "eligible_shots": sorted(eligible_shots),
        "pro_shot_ids": sorted(pro_set),
        "pro_dur_cut": round(pro_cut, 3) if pro_cut is not None else None,
        "engines": {"frontal_closeup": eng_fast, "top10pct": eng_pro},
    }


# ---------------------------------------------------------------------------
# 帧域换算与 ffmpeg 抽段
# ---------------------------------------------------------------------------

def window_to_frames(window: list[float], fps: float, n_total: int,
                     *, utt_id: str = "") -> tuple[int, int]:
    """C6 秒窗 → 帧号区间 [f0, f1)（帧栅格取整；越界夹取；空窗报错）。"""
    f0 = max(0, int(round(float(window[0]) * fps)))
    f1 = min(n_total, int(round(float(window[1]) * fps)))
    if f1 <= f0:
        raise LipError(
            f"口型窗映射为空: utt_id={utt_id or '-'} window={window} "
            f"fps={fps} → [{f0},{f1})（视频共 {n_total} 帧）")
    return f0, f1


def _run(cmd: list[str], *, timeout_s: float = 1800.0) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if r.returncode != 0:
        raise LipError(f"命令失败 ({' '.join(cmd[:4])}…): {r.stderr[-500:]}")
    return r


def probe_video(path: str | Path) -> dict[str, Any]:
    """ffprobe → {fps, n_frames, width, height, duration_s, has_audio}。

    帧数用 -count_frames 实数（元数据 nb_frames 在拼接/裁切产物上常缺/不准）。
    """
    r = _run([
        "ffprobe", "-v", "error", "-count_frames",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=r_frame_rate,nb_read_frames,width,height,duration",
        "-of", "json", str(path),
    ])
    import json

    s = (json.loads(r.stdout).get("streams") or [{}])[0]
    num, _, den = str(s.get("r_frame_rate", "25/1")).partition("/")
    fps = float(num) / float(den or 1)
    n = int(s.get("nb_read_frames") or 0)
    if fps <= 1.0 or n <= 0:
        raise LipError(f"视频探测异常: fps={fps} n_frames={n} ({path})")
    return {
        "fps": fps, "n_frames": n,
        "width": int(s.get("width") or 0), "height": int(s.get("height") or 0),
        "duration_s": round(float(s.get("duration") or 0.0), 3),
        "has_audio": _has_audio(path),
    }


def _has_audio(path: str | Path) -> bool:
    r = _run(["ffprobe", "-v", "error", "-select_streams", "a",
              "-show_entries", "stream=index", "-of", "csv=p=0", str(path)])
    return bool(r.stdout.strip())


def extract_video_segment(src: str | Path, out: str | Path, f0: int, f1: int,
                          fps: float) -> int:
    """源视频按帧号抽 [f0, f1) → 独立段（发给服务的"镜头窗"）。

    seek 点用帧栅格秒 f/fps（accurate_seek 首帧 pts ≥ f0/fps，恰好第 f0 帧）；
    抽段重编码 crf12（服务的输入口径，服务在解码帧上再生成，段自身质量
    不进交付——窗内帧最终被服务产出整体替换）。返回实测帧数。
    """
    t0, t1 = f0 / fps, f1 / fps
    _run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{t0:.6f}", "-to", f"{t1:.6f}", "-i", str(src),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
        "-pix_fmt", "yuv420p", "-vsync", "0", str(out),
    ])
    return probe_video(out)["n_frames"]


def extract_audio_segment(audio: str | Path, out: str | Path,
                          f0: int, f1: int, fps: float) -> None:
    """配音轨按帧号抽 [f0, f1) → 16k 单声道 wav（服务端还会硬对齐一次）。"""
    t0, t1 = f0 / fps, f1 / fps
    _run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{t0:.6f}", "-to", f"{t1:.6f}", "-i", str(audio),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out),
    ])


# ---------------------------------------------------------------------------
# ② GPU 服务客户端（:9003）
# ---------------------------------------------------------------------------

def lip_response_to_video(resp: dict[str, Any], out: str | Path) -> dict[str, Any]:
    """服务响应 → 落盘 mp4（C 出口纯函数，eval 可离线测）。

    校验 video_b64 非空、sha256 对账（防半截传输）、帧数>0。
    返回 ``{"out", "video_bytes", "n_frames", "fps", "sha256"}``。
    """
    b64 = resp.get("video_b64")
    if not b64:
        raise LipError(f"响应无 video_b64（engine={resp.get('engine')}）")
    raw = base64.b64decode(b64)
    sha = hashlib.sha256(raw).hexdigest()
    want = resp.get("sha256")
    if want and want != sha:
        raise LipError(f"段 sha256 对账失败: 服务端 {want} vs 客户端 {sha}")
    n_frames = int(resp.get("n_frames") or 0)
    if n_frames <= 0:
        raise LipError("响应帧数非正")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    return {"out": str(out_path), "video_bytes": len(raw),
            "n_frames": n_frames, "fps": float(resp.get("fps") or 0.0),
            "sha256": sha}


class LipClient:
    """:9003 lip 客户端：multipart 视频段+配音上传 → JSON（mp4 b64 + 帧数/耗时）。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        retries: int = 2,
        retry_wait_s: float = 2.0,
    ) -> None:
        if base_url is None:
            env_name, default = SERVICE_ENV
            base_url = os.environ.get(env_name, default)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.retry_wait_s = retry_wait_s

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.request(method, f"{self.base_url}{path}", **kw)
                if resp.status_code >= 400:
                    raise LipError(f"HTTP {resp.status_code} {path}: {resp.text[:400]}")
                return resp
            except (httpx.HTTPError, LipError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(self.retry_wait_s)
        raise LipError(f"{method} {self.base_url}{path} 失败（重试 {self.retries} 次后）: {last_exc}")

    def health(self) -> dict[str, Any]:
        """GET /health —— 引擎装载状态/物理卡/显存余量。"""
        return self._request("GET", "/health").json()

    def lip(
        self,
        video: str | Path,
        audio: str | Path,
        out: str | Path,
        *,
        utt_id: str = "",
        shot_id: str = "",
        mode: str = "fast",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """POST /v1/lip —— 单窗口型再生成。返回 C 出口：``out``（mp4 路径）
        + ``n_frames``/``fps``/``timing``/``rtf``。

        ``mode="fast"``=lip-fast 主力；``mode="pro"``=精口型（权重未部署时
        服务 503，本客户端归一为 :class:`LipError`，调用方决定跳过或中止）。
        ``dry_run=True`` 只做请求校验，不占 GPU。
        """
        vpath, apath = Path(video), Path(audio)
        if not vpath.is_file():
            raise LipError(f"视频段不存在: {vpath}")
        if not apath.is_file():
            raise LipError(f"配音段不存在: {apath}")
        for p in (vpath, apath):
            if p.stat().st_size > MAX_UPLOAD_BYTES:
                raise LipError(f"{p.name} 超过 {MAX_UPLOAD_BYTES // (1024*1024)}MB 上限")
        files = {
            "video": (vpath.name, vpath.read_bytes(), "video/mp4"),
            "audio": (apath.name, apath.read_bytes(), "audio/wav"),
        }
        data = {"mode": mode, "utt_id": utt_id, "shot_id": shot_id,
                "dry_run": str(bool(dry_run)).lower()}
        resp = self._request("POST", "/v1/lip", files=files, data=data).json()
        if dry_run:
            return resp
        result = lip_response_to_video(resp, out)
        result.update(
            mode=resp.get("mode"), timing=resp.get("timing"),
            rtf=resp.get("rtf"), versions=resp.get("versions"),
            request_echo=resp.get("request"),
            n_placeholder_fixed=resp.get("n_placeholder_fixed"),
        )
        return result


# ---------------------------------------------------------------------------
# ③ 回贴合成 + 帧哈希自验
# ---------------------------------------------------------------------------

def _raw_frame_stream(video: str | Path, pix_fmt: str = "yuv420p") -> Iterator[bytes]:
    """解码视频 → 原始 yuv420p 帧字节流（不经 RGB 转换，保位精确）。"""
    probe = probe_video(video)
    w, h = probe["width"], probe["height"]
    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-i", str(video),
         "-f", "rawvideo", "-pix_fmt", pix_fmt, "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    frame_size = w * h * 3 // 2
    try:
        while True:
            buf = proc.stdout.read(frame_size)
            if not buf:
                break
            if len(buf) != frame_size:
                raise LipError(f"原始帧流截断: {len(buf)}/{frame_size} ({video})")
            yield buf
    finally:
        proc.stdout.close()
        proc.wait(timeout=60)


def frame_hashes(video: str | Path) -> list[str]:
    """逐帧 raw yuv sha256（字节级对比的基准；与解码路径无关的位精确哈希）。"""
    return [hashlib.sha256(b).hexdigest() for b in _raw_frame_stream(video)]


def splice_segments(src: str | Path, segments: list[tuple[int, int, str]],
                    out: str | Path, *, n_frames: int,
                    keep_src_audio: bool = True) -> dict[str, Any]:
    """回贴合成：窗外帧=源视频原帧字节透传，窗内帧=服务产出段帧替换。

    ``segments`` = [(f0, f1, 段 mp4 路径)]（帧号左闭右开；源帧流与段帧流
    按帧号同步推进——进入窗后每步读一个源帧丢弃、写一个段帧，两路解码
    均匀受料，窗区互不重叠，重叠即报错）。先出**无损**视频轨（raw
    yuv420p → x264 qp=0，解码位精确），再从源片复制音轨（-c:a copy，口型
    不改音频——混音归 M9，字幕归 M11）。返回统计 dict。
    """
    segs = sorted(segments, key=lambda x: x[0])
    covered: list[tuple[int, int]] = []
    for f0, f1, seg in segs:
        if not (0 <= f0 < f1 <= n_frames):
            raise LipError(f"回贴窗越界: [{f0},{f1})（源共 {n_frames} 帧）")
        for a, b in covered:
            if f0 < b and a < f1:
                raise LipError(f"回贴窗重叠: [{a},{b}) ∩ [{f0},{f1})")
        covered.append((f0, f1))
    pending = [(f0, f1, _raw_frame_stream(seg)) for f0, f1, seg in segs]

    probe = probe_video(src)
    w, h = probe["width"], probe["height"]
    video_only = Path(out).with_name(Path(out).name + ".vonly.mp4")
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{w}x{h}",
         "-r", f"{probe['fps']:.6f}", "-i", "-",
         "-c:v", "libx264", "-qp", "0", "-preset", "medium",
         "-pix_fmt", "yuv420p", str(video_only)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdin is not None

    n_replaced = 0
    n_passthrough = 0
    cur: Optional[tuple[int, int, Iterator[bytes]]] = None
    try:
        for i, src_frame in enumerate(_raw_frame_stream(src)):
            if i >= n_frames:
                break
            if cur is None and pending and pending[0][0] == i:
                cur = pending.pop(0)
            if cur is not None and cur[0] <= i < cur[1]:
                seg_frame = next(cur[2], None)
                if seg_frame is None:
                    raise LipError(
                        f"段帧早于窗尾耗尽: 窗 [{cur[0]},{cur[1]}) 帧号 {i}")
                proc.stdin.write(seg_frame)
                n_replaced += 1
            else:
                if cur is not None and i >= cur[1]:
                    cur = None  # 本窗结束（多余段帧不再消费，随流关闭释放）
                proc.stdin.write(src_frame)
                n_passthrough += 1
        proc.stdin.close()
        if proc.wait() != 0:
            raise LipError("回贴合成编码失败（ffmpeg 非零退出）")
    finally:
        for _f0, _f1, it in pending:
            it.close() if hasattr(it, "close") else None  # noqa: E501

    if keep_src_audio and probe["has_audio"]:
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_only),
              "-i", str(src), "-map", "0:v:0", "-map", "1:a:0",
              "-c:v", "copy", "-c:a", "copy", str(out)])
        video_only.unlink(missing_ok=True)
    else:
        video_only.replace(out)
    return {"n_frames": n_frames, "n_replaced": n_replaced,
            "n_passthrough": n_passthrough, "n_segments": len(segs),
            "covered_ranges": covered}


# ---------------------------------------------------------------------------
# 帧哈希自验（冻结验收口径）
# ---------------------------------------------------------------------------

def _mouth_box(bbox: list[int]) -> tuple[int, int, int, int]:
    """C2 人脸框 → 嘴区框（脸框下半 45%；嘴是口型再生成的唯一动区）。"""
    x0, y0, x1, y1 = bbox
    h = max(1, y1 - y0)
    return (int(x0), int(y0 + h * 0.55), int(x1), int(y1))


def _window_mouth_mad(src: str | Path, out: str | Path, f0: int, f1: int,
                      box: tuple[int, int, int, int]) -> float:
    """口型窗内嘴区平均绝对差（BGR 口径，0-255 灰阶量级）。"""
    import cv2
    import numpy as np

    cap_s = cv2.VideoCapture(str(src))
    cap_o = cv2.VideoCapture(str(out))
    total, n = 0.0, 0
    idx = 0
    x0, y0, x1, y1 = box
    while idx < f1:
        got_s, fs = cap_s.read()
        got_o, fo = cap_o.read()
        if not (got_s and got_o):
            break
        if idx >= f0:
            total += float(np.abs(
                fs[y0:y1, x0:x1].astype(np.int16)
                - fo[y0:y1, x0:x1].astype(np.int16)).mean())
            n += 1
        idx += 1
    cap_s.release()
    cap_o.release()
    if n == 0:
        raise LipError(f"嘴区对比无帧: 窗 [{f0},{f1})")
    return total / n


def verify_paste_back(
    src: str | Path,
    out: str | Path,
    windows: list[tuple[int, int, list[int] | None]],
    *,
    min_mouth_mad: float = MIN_MOUTH_MAD,
) -> dict[str, Any]:
    """帧哈希自验（冻结验收口径，本模块生产路径内置）：

    ① 帧数一致；② **非口型帧字节级零改动**——窗外每帧 raw yuv sha256
    逐帧全等；③ **口型窗帧全不同**——窗内每帧哈希必异（被服务产出替换）；
    ④ **口型区变化**——有 face bbox 的窗，嘴区像素平均绝对差 ≥
    ``min_mouth_mad``（crf18 重编码噪声 <1.5 灰阶，口型开合为数十灰阶）。
    任一不过 → ``ok=False`` 并附逐项计数（不出假交付）。
    """
    hs = frame_hashes(src)
    ho = frame_hashes(out)
    n = len(hs)
    rep: dict[str, Any] = {
        "n_frames_src": len(hs), "n_frames_out": len(ho),
        "n_windows": len(windows), "min_mouth_mad": min_mouth_mad,
        "ok": False,
    }
    if len(hs) != len(ho):
        rep["reason"] = f"帧数不一致: src={len(hs)} out={len(ho)}"
        return rep
    cover = [False] * n
    for f0, f1, _bbox in windows:
        for i in range(max(0, f0), min(n, f1)):
            cover[i] = True
    n_outside = sum(1 for c in cover if not c)
    n_inside = n - n_outside
    identical_outside = sum(1 for i in range(n) if not cover[i] and hs[i] == ho[i])
    changed_inside = sum(1 for i in range(n) if cover[i] and hs[i] != ho[i])
    rep.update({
        "n_frames_outside": n_outside, "n_frames_inside": n_inside,
        "identical_outside": identical_outside,
        "changed_inside": changed_inside,
    })
    if n_outside and identical_outside != n_outside:
        bad = [i for i in range(n) if not cover[i] and hs[i] != ho[i]][:5]
        rep["reason"] = f"非口型帧被改动 {n_outside - identical_outside} 帧（例: {bad}）"
        return rep
    if n_inside and changed_inside != n_inside:
        same = [i for i in range(n) if cover[i] and hs[i] == ho[i]][:5]
        rep["reason"] = f"口型窗内有帧未变化 {n_inside - changed_inside} 帧（例: {same}）"
        return rep
    mads = []
    for f0, f1, bbox in windows:
        if not bbox:
            continue
        mad = _window_mouth_mad(src, out, f0, f1, _mouth_box(bbox))
        mads.append({"window": [f0, f1], "mouth_mad": round(mad, 2),
                     "bbox": list(bbox), "pass": bool(mad >= min_mouth_mad)})
    rep["mouth"] = mads
    if mads and not all(m["pass"] for m in mads):
        rep["reason"] = (f"口型区变化不足（min mad="
                         f"{min(m['mouth_mad'] for m in mads)} < {min_mouth_mad}）")
        return rep
    rep["ok"] = True
    return rep


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _resolve_source(ws: Path, source: Optional[str]) -> Path:
    if source:
        p = Path(source)
        if not p.is_file():
            raise LipError(f"源视频不存在: {p}")
        return p
    p = ws / "01_media" / "video_1080x1920_25fps.mp4"
    if not p.is_file():
        raise LipError(
            f"默认源视频不存在: {p}（M1 产物；或 --source 显式指定）")
    return p


def _resolve_dub(ws: Path, audio: Optional[str], lang: str) -> Path:
    if audio:
        p = Path(audio)
        if not p.is_file():
            raise LipError(f"配音轨不存在: {p}")
        return p
    p = ws / "08_mix" / f"dubbed.{lang}.wav"
    if not p.is_file():
        raise LipError(
            f"配音轨不存在: {p}（M7/M9 产物；或 --audio 显式指定）")
    return p


def run(
    ep: str,
    lang: str,
    *,
    jobs_dir: str | Path | None = None,
    cfg: dict | None = None,
    source: Optional[str] = None,
    audio: Optional[str] = None,
    url: Optional[str] = None,
    pro_shots: tuple[str, ...] = (),
    rebuild_plan: bool = True,
    verify: bool = True,
    work_dir: Optional[str | Path] = None,
) -> dict[str, Any]:
    """M10 主流程：建 C6 计划 → 逐窗调 :9003 → 回贴合成 → 帧哈希自验。

    执行按 models.yaml ``components.<engine>.fallback`` 冻结降级链：重点
    镜头 lip-pro 不可用（权重未部署→服务 503）依注册表降级 lip-fast，链
    逐节点失败记入 ``attempts`` 如实上报（降级不静默），链尾 lip-fast 失败
    = 硬错误。返回报告 dict（调用方打印）。
    """
    cfg = cfg if cfg is not None else load_pipeline_config()
    root = Path(jobs_dir) if jobs_dir else Path(cfg["paths"]["jobs_dir"])
    create_workspace(ep, root)
    ws = ep_dir(ep, root)
    lip_dir = ws / "09_lip"

    if rebuild_plan or not (lip_dir / f"lip_plan.{lang}.jsonl").is_file():
        plan_info = build_lip_plan(ep, lang, jobs_dir=root, cfg=cfg,
                                   pro_shots=pro_shots)
    else:
        plan_info = {"plan_path": str(lip_dir / f"lip_plan.{lang}.jsonl"),
                     "reused": True}
    plan = C.load_jsonl(lip_dir / f"lip_plan.{lang}.jsonl",
                        C.LipPlanTable).root

    src = _resolve_source(ws, source)
    dub = _resolve_dub(ws, audio, lang)
    probe = probe_video(src)
    fps, n_total = probe["fps"], probe["n_frames"]

    work = Path(work_dir) if work_dir else (lip_dir / "work")
    work.mkdir(parents=True, exist_ok=True)
    cli = LipClient(url)
    t_all = time.perf_counter()

    items: list[dict[str, Any]] = []
    segments: list[tuple[int, int, str]] = []
    verify_windows: list[tuple[int, int, Optional[list[int]]]] = []
    c2 = {u.utt_id: u for u in C.load_jsonl(
        ws / "04_dial" / "utterances.jsonl", C.UtteranceTable).root}
    for row in plan:
        item: dict[str, Any] = {
            "utt_id": row.utt_id, "shot_id": row.shot_id,
            "engine": row.engine, "priority": row.priority,
            "window": list(row.window), "status": "pending",
        }
        f0, f1 = window_to_frames(row.window, fps, n_total, utt_id=row.utt_id)
        seg_v = work / f"{row.utt_id}.src.mp4"
        seg_a = work / f"{row.utt_id}.dub.wav"
        seg_o = work / f"{row.utt_id}.lip.mp4"
        n_seg = extract_video_segment(src, seg_v, f0, f1, fps)
        if n_seg != f1 - f0:
            raise LipError(
                f"抽段帧数失配: utt_id={row.utt_id} 期望 {f1 - f0} 实得 {n_seg} "
                f"（f0={f0} fps={fps}）")
        extract_audio_segment(dub, seg_a, f0, f1, fps)
        # 执行降级链（models.yaml components.<engine>.fallback 冻结镜像）：
        # 重点镜头 lip-pro 不可用（权重未部署→服务 503）→ 依注册表降级
        # lip-pro-1.5 → lip-fast，降质不弃做；链首失败逐级记 attempts，
        # 链尾 lip-fast（主力）失败 = 硬错误，不静默弃窗。
        t0 = time.perf_counter()
        attempts: list[dict[str, Any]] = []
        executed: Optional[str] = None
        r: Optional[dict[str, Any]] = None
        for eng in engine_fallback_chain(row.engine):
            mode = "fast" if eng == ENGINE_FAST else "pro"
            try:
                r = cli.lip(seg_v, seg_a, seg_o, utt_id=row.utt_id,
                            shot_id=row.shot_id, mode=mode)
                executed = eng
                break
            except LipError as exc:
                attempts.append({"engine": eng, "ok": False,
                                 "error": str(exc)[:300]})
                if eng == ENGINE_FAST:
                    raise LipError(
                        f"主力引擎 lip-fast 调用失败: utt_id={row.utt_id} "
                        f"{attempts[-1]['error']}") from exc
                print(f"  WARN {row.utt_id}: {eng} 不可用，降级下一链节点"
                      f"（{attempts[-1]['error'][:120]}…）")
        assert executed is not None and r is not None
        wall_s = round(time.perf_counter() - t0, 2)
        if r["n_frames"] != f1 - f0:
            raise LipError(
                f"服务产出帧数失配: utt_id={row.utt_id} 期望 {f1 - f0} 实得 "
                f"{r['n_frames']}（回贴拒绝错位拼接）")
        item.update(status="done", engine_used=executed,
                    degraded=bool(executed != row.engine),
                    attempts=attempts or None, frames=[f0, f1], wall_s=wall_s,
                    rtf=r.get("rtf"), timing=r.get("timing"),
                    n_placeholder_fixed=r.get("n_placeholder_fixed"))
        segments.append((f0, f1, str(seg_o)))
        u = c2.get(row.utt_id)
        bbox = list(u.face.bbox) if (u and u.face) else None
        verify_windows.append((f0, f1, bbox))
        items.append(item)

    out_path = lip_dir / "done" / f"{ep}.{lang}.lip.mp4"
    if segments:
        splice = splice_segments(src, segments, out_path, n_frames=n_total,
                                 keep_src_audio=probe["has_audio"])
    else:
        splice = {"n_frames": n_total, "n_replaced": 0, "n_passthrough": 0,
                  "n_segments": 0, "covered_ranges": [],
                  "note": "无口型窗（全部原画），未合成——成片不出，见 plan"}

    report: dict[str, Any] = {
        "ep": ep, "lang": lang, "module": "m10_lipsync",
        "source": str(src), "dub": str(dub),
        "fps": round(fps, 6), "n_frames": n_total,
        "plan": plan_info, "items": items,
        "splice": splice,
        "out": str(out_path),
        "service_url": cli.base_url,
        "access": ("GPU 机: ssh dev-env-with-gpu → bash gpu-services/lip/"
                   "run_gpu.sh start（127.0.0.1:9003，物理 cuda:1）；"
                   "本机隧道: TUNNEL_LOCAL_PORT=9003 TUNNEL_REMOTE_PORT=9003 "
                   "bash ops/tunnel_gpu.sh start"),
        "wall_s": round(time.perf_counter() - t_all, 2),
    }
    if verify and segments:
        vr = verify_paste_back(src, out_path, verify_windows)
        report["verify"] = vr
        if not vr.get("ok"):
            (lip_dir / f"lip_report.{lang}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
            raise LipError(f"回贴自验不过: {vr.get('reason')}")
    elif not segments:
        report["verify"] = {"ok": True, "note": "无口型窗（全部原画），未触发合成与自验"}

    (lip_dir / f"lip_report.{lang}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.m10_lipsync",
        description="M10 按镜头分流口型（C6 计划 + GPU :9003 + 回贴合成）")
    ap.add_argument("--ep", required=True, help="集 ID，如 ep01")
    ap.add_argument("--lang", required=True, help="语种（配音轨 dubbed.<lang>.wav）")
    ap.add_argument("--pro-shots", default="",
                    help="强制升级精口型的镜头清单（逗号分隔 shot_id）")
    ap.add_argument("--source", default=None, help="源视频覆盖（默认 01_media 主视频）")
    ap.add_argument("--audio", default=None, help="配音轨覆盖（默认 08_mix/dubbed.<lang>.wav）")
    ap.add_argument("--url", default=None, help="服务地址（默认 M10_LIP_URL 或 http://127.0.0.1:9003）")
    ap.add_argument("--jobs-dir", default=None, help="jobs 根目录（默认 configs/pipeline.yaml）")
    ap.add_argument("--work-dir", default=None, help="段交换目录（默认 09_lip/work，tmp 性质）")
    ap.add_argument("--no-verify", action="store_true", help="跳过帧哈希自验（仅调试用）")
    args = ap.parse_args(argv)

    pro_shots = tuple(s.strip() for s in args.pro_shots.split(",") if s.strip())
    try:
        report = run(
            args.ep, args.lang, jobs_dir=args.jobs_dir, source=args.source,
            audio=args.audio, url=args.url, pro_shots=pro_shots,
            verify=not args.no_verify, work_dir=args.work_dir)
    except (LipError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"FAIL m10_lipsync: {exc}")
        return 1
    done = [i for i in report["items"] if i["status"] == "done"]
    degraded = [i for i in done if i.get("degraded")]
    skip = [i for i in report["items"] if i["status"] == "skipped"]
    print(
        f"OK m10_lipsync ep={report['ep']} lang={report['lang']} "
        f"windows={len(done)}/degraded={len(degraded)}/skipped={len(skip)} "
        f"replaced={report['splice']['n_replaced']}fr "
        f"passthrough={report['splice']['n_passthrough']}fr "
        f"verify={(report.get('verify') or {}).get('ok')} wall={report['wall_s']}s"
    )
    for i in done:
        t = i.get("timing") or {}
        eng = f" engine={i['engine']}→{i['engine_used']}" if i.get("degraded") \
            else f" engine={i['engine_used'] or i['engine']}"
        print(f"  {i['utt_id']} [{i['frames'][0]},{i['frames'][1]}){eng} "
              f"rtf={i.get('rtf')} infer={t.get('infer_s')}s "
              f"pre={t.get('preprocess_s')}s paste={t.get('paste_s')}s")
        for a in (i.get("attempts") or []):
            print(f"    attempt {a['engine']}: FAIL {a['error'][:140]}")
    for i in skip:
        print(f"  {i['utt_id']}（{i['shot_id']}）SKIPPED: {i.get('skip_reason')}")
    print(f"  → {report['out']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
