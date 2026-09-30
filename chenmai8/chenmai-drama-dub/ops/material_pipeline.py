#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""素材母盘链（material pipeline）—— 短剧真实母盘素材的验版/入库/盘点。

背景（2026-10-01 夜班 worker-A）：
  - 活跃线考古结论：短剧真实母盘素材（owner 指令「自找公开素材，多找几个」）在
    windev 会话中断时处于「下载中」状态；materials/didaozhan_p1.mp4 为唯一落盘件，
    经本工具 verify 实测为**截断件**（容器头声明 1541.8s，实际可解码视频止于 ~31.6s，
    大量 Invalid NAL unit size）——「验版」正是为拦住这种半截文件进入母盘而设。
  - 公版依据：地道战(1965)/英雄儿女(1964)/闪闪的红星(1974) 均为中国大陆电影作品，
    著作权保护期（发表后 50 年）分别于 2015/2014/2024 年底届满，已进入公有领域；
    采集源与许可登记见 docs/assets/materials-sourcing.md。
  - 分工边界：本工具只做 验版 → 母盘登记 → 盘点；**不做竖屏化/烧字幕**——
    竖屏规范化由 M1 ingest 承担（docs/assets/specs/m1-ingest.md §2.3：
    scale decrease + 黑边 pad 到 media.width/height），母盘保持原始画面避免
    双重转码损失；字幕硬烧属 M11 域（m11-subs.md）。

用法（系统 python3.12，零第三方依赖；ffmpeg/ffprobe 需在 PATH）：
  python ops/material_pipeline.py verify  <file> [--fast] [--report OUT.json]
  python ops/material_pipeline.py master  <file> --title <NAME> [--materials-dir DIR]
  python ops/material_pipeline.py plan    [--materials-dir DIR]

退出码：0 = 验版通过/母盘入库成功；1 = 验版不合格或母盘拒绝；2 = 用法/输入错误。
目录约定（与 M1 的 jobs 树同源原则：素材区在项目根、不在仓内）：
  <项目根>/materials/raw/     采集收件（原始下载件，只进不出）
  <项目根>/materials/master/  母盘（验版通过件的规范化登记拷贝）
  <项目根>/materials/master/manifest.json  母盘台账（追加式，原子写）
其中 <项目根> = 仓库根的上级（repo/../materials）。
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_ROOT.parent
DEFAULT_MATERIALS = PROJECT_ROOT / "materials"

# 容器声明时长与实测可解码时长的容差（秒）——超出即判 TRUNCATED
DURATION_TOLERANCE_S = 1.0
# 解码错误上限——零容忍（母盘件不允许任何 decode error）
MAX_DECODE_ERRORS = 0


class MaterialError(Exception):
    """素材链硬错误（用法/输入/工具缺失）。"""


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path, block: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(block)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _require_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise MaterialError(f"{tool} 不在 PATH（M1 同款硬依赖，见 m1-ingest.md 上游依赖节）")


def probe_streams(path: Path) -> dict:
    """ffprobe 流清单 + format 信息（JSON）。attached_pic 封面图剔除，
    与 M1 的流型判定同口径（m1-ingest.md §2.3 流型判定）。"""
    cmd = [
        "ffprobe", "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(path),
    ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise MaterialError(f"ffprobe 失败（rc={proc.returncode}）: {proc.stderr.strip()[:300]}")
    data = json.loads(proc.stdout or "{}")
    real_streams = [
        s for s in data.get("streams", [])
        if not (s.get("codec_type") == "video" and (s.get("disposition", {}) or {}).get("attached_pic", 0))
    ]
    data["streams"] = real_streams
    return data


def decode_scan(path: Path, fast: bool = False) -> dict:
    """全流解码扫描：stderr 逐行数 error，-progress 抓真实可解码时长。

    fast=True 时跳过全解码（只探视频包尾界 pts）——用于大文件快速预检，
    母盘入库（master）一律全解码。
    """
    if fast:
        # 视频包尾界：截断件在损坏处停止，packets 输出即实际数据边界
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)]
        proc = _run(cmd, timeout=300)
        tail = 0.0
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                tail = max(tail, float(line))
            except ValueError:
                continue
        return {"mode": "fast", "decode_errors": 0, "video_tail_s": round(tail, 3),
                "decoded_duration_s": None}

    # 全解码扫描：视频流；-progress pipe:1 输出 out_time_us 行
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
           "-map", "0:v:0", "-f", "null", "-progress", "pipe:1", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    errors = [ln for ln in (proc.stderr or "").splitlines() if ln.strip()]
    decoded_s = None
    for ln in (proc.stdout or "").splitlines():
        m = re.match(r"out_time_us=(\d+)", ln.strip())
        if m:
            decoded_s = int(m.group(1)) / 1_000_000.0
    return {
        "mode": "full",
        "decode_errors": len(errors),
        "error_samples": errors[:5],
        "decoded_duration_s": round(decoded_s, 3) if decoded_s is not None else None,
    }


def verify(path: Path, fast: bool = False) -> dict:
    """验版：流探针 + 解码扫描 + sha256 → OK / TRUNCATED / CORRUPT 判定。"""
    if not path.is_file():
        raise MaterialError(f"输入不存在: {path}")
    _require_tools()
    prob = probe_streams(path)
    fmt = prob.get("format", {}) or {}
    container_dur = float(fmt.get("duration") or 0.0)
    has_video = any(s.get("codec_type") == "video" for s in prob["streams"])
    has_audio = any(s.get("codec_type") == "audio" for s in prob["streams"])

    scan = decode_scan(path, fast=fast)
    if scan["mode"] == "fast":
        effective_s = scan["video_tail_s"]
    else:
        effective_s = scan["decoded_duration_s"] or 0.0

    reasons: list[str] = []
    verdict = "OK"
    if scan["decode_errors"] > MAX_DECODE_ERRORS:
        verdict = "CORRUPT"
        reasons.append(f"解码错误 {scan['decode_errors']} 处（上限 {MAX_DECODE_ERRORS}）")
    if container_dur > 0 and effective_s > 0 and (container_dur - effective_s) > DURATION_TOLERANCE_S:
        verdict = "TRUNCATED"
        reasons.append(
            f"可解码止于 {effective_s:.1f}s，容器声明 {container_dur:.1f}s "
            f"（缺口 {container_dur - effective_s:.1f}s > 容差 {DURATION_TOLERANCE_S}s）")
    if not has_video and not has_audio:
        verdict = "CORRUPT"
        reasons.append("无有效视频/音频流（M1 对既无视频也无音轨的输入会 IngestError）")

    report = {
        "schema_version": 1,
        "tool": "ops/material_pipeline.py verify",
        "checked_at": _now_iso(),
        "file": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "container_duration_s": round(container_dur, 3),
        "decoded_duration_s": scan.get("decoded_duration_s"),
        "video_tail_s": scan.get("video_tail_s"),
        "decode_errors": scan["decode_errors"],
        "scan_mode": scan["mode"],
        "has_video": has_video,
        "has_audio": has_audio,
        "streams": [
            {"codec_type": s.get("codec_type"), "codec_name": s.get("codec_name"),
             "width": s.get("width"), "height": s.get("height"),
             "r_frame_rate": s.get("r_frame_rate"), "duration": s.get("duration")}
            for s in prob["streams"]
        ],
        "verdict": verdict,
        "reasons": reasons,
    }
    return report


def _master_dirs(materials_dir: Path) -> tuple[Path, Path]:
    raw = materials_dir / "raw"
    master = materials_dir / "master"
    return raw, master


def master(path: Path, title: str, materials_dir: Path) -> dict:
    """母盘入库：verify 必须 OK；拷贝（不转码不裁切）+ manifest 追加（原子写）。"""
    report = verify(path, fast=False)
    _, master_dir = _master_dirs(materials_dir)
    if report["verdict"] != "OK":
        master_dir.mkdir(parents=True, exist_ok=True)
        reject_path = master_dir / "verify_failed.json"
        reject_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        raise MaterialError(
            f"验版不合格（{report['verdict']}）：{'; '.join(report['reasons'])}；"
            f"完整报告落 {reject_path}，不入库不出母盘")

    master_dir.mkdir(parents=True, exist_ok=True)
    dest = master_dir / f"{title}.mp4"
    shutil.copy2(path, dest)

    manifest_path = master_dir / "manifest.json"
    entries: list[dict] = []
    if manifest_path.exists():
        entries = json.loads(manifest_path.read_text(encoding="utf-8")).get("items", [])
    entry = {
        "title": title,
        "file": f"master/{dest.name}",
        "registered_at": _now_iso(),
        "source_file": str(path),
        "sha256": report["sha256"],
        "size_bytes": report["size_bytes"],
        "container_duration_s": report["container_duration_s"],
        "streams": report["streams"],
        "verify": {"verdict": report["verdict"], "scan_mode": report["scan_mode"],
                   "decode_errors": report["decode_errors"]},
        "pipeline_note": "母盘保持原始画面（不预裁竖屏/不预烧字幕）：竖屏化由 M1 ingest 承担"
                         "（docs/assets/specs/m1-ingest.md §2.3），字幕硬烧属 M11 域。",
    }
    entries = [e for e in entries if e.get("title") != title]  # 同名重登=覆盖旧条目
    entries.append(entry)
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema_version": 1, "items": entries},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, manifest_path)  # 原子替换

    out = {"registered": True, "title": title, "dest": str(dest),
           "sha256": report["sha256"], "manifest": str(manifest_path)}
    return out


def plan(materials_dir: Path) -> dict:
    """盘点：raw 待验件 / master 已登记 / 差异（raw 中未入库、manifest 幽灵条目）。"""
    raw, master_dir = _master_dirs(materials_dir)
    raw_files = sorted(p.name for p in raw.iterdir() if p.is_file()) if raw.is_dir() else []
    manifest = master_dir / "manifest.json"
    items = json.loads(manifest.read_text(encoding="utf-8")).get("items", []) if manifest.exists() else []
    registered_srcs = {Path(e["source_file"]).name for e in items if e.get("source_file")}
    return {
        "materials_dir": str(materials_dir),
        "raw_pending_verify": [n for n in raw_files],
        "raw_not_registered": [n for n in raw_files if n not in registered_srcs],
        "registered_titles": [e.get("title") for e in items],
        "manifest_entries": len(items),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="素材母盘链：验版/入库/盘点")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_v = sub.add_parser("verify", help="验版（解码扫描+截断检测+sha256）")
    p_v.add_argument("file", type=Path)
    p_v.add_argument("--fast", action="store_true", help="跳过全解码，只探视频包尾界")
    p_v.add_argument("--report", type=Path, default=None, help="报告落盘路径")

    p_m = sub.add_parser("master", help="母盘入库（验版必须 OK）")
    p_m.add_argument("file", type=Path)
    p_m.add_argument("--title", required=True)
    p_m.add_argument("--materials-dir", type=Path, default=DEFAULT_MATERIALS)

    p_p = sub.add_parser("plan", help="raw/master 盘点差异")
    p_p.add_argument("--materials-dir", type=Path, default=DEFAULT_MATERIALS)

    args = ap.parse_args(argv)
    try:
        if args.cmd == "verify":
            report = verify(args.file, fast=args.fast)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            if args.report:
                args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
            print(f"VERDICT={report['verdict']}", file=sys.stderr)
            return 0 if report["verdict"] == "OK" else 1
        if args.cmd == "master":
            out = master(args.file, args.title, args.materials_dir)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        if args.cmd == "plan":
            print(json.dumps(plan(args.materials_dir), ensure_ascii=False, indent=2))
            return 0
        return 2
    except MaterialError as exc:
        print(f"MATERIAL_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
