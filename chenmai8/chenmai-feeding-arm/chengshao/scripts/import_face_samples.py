"""face_samples 导入脚本：抽帧入 assets + 半自动标签初稿（开发指令 §5.3 样本获取）。

用法（包根 chengshao/ 下执行）::

    # 视频（手机录制的张闭嘴/转头片段）
    python scripts/import_face_samples.py --video C:/faces/front_open_close.mp4 --fps 2 --max-frames 60
    # 一组静帧
    python scripts/import_face_samples.py --images C:/faces/stills/

行为：
1) 抽帧（或拷贝静帧）到 assets/face_samples/clips/<名>/fNNNNN.jpg；
2) 用 MouthEstimator 对每帧算 jaw_open / |head_yaw|；
3) 张闭嘴滞回分段（jaw_open 升过 --open-enter 记 open，降到 --open-exit 记 closed），
   |yaw|>25° 记 turn=true —— 全部标 draft=true 供人工修订；
4) 合并写回 assets/face_samples/labels.json（保留已有条目），
   并生成 clips/<名>/_contact_sheet.jpg 供快速人工复核。

Windows 中文路径安全（经 cs_mouth.imgio）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

PKG_PARENT = Path(__file__).resolve().parents[1]  # chengshao/
if str(PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(PKG_PARENT))

from cs_mouth.estimator import MouthEstimator  # noqa: E402
from cs_mouth.imgio import imread_u, imwrite_u, open_video_u, release_video_u  # noqa: E402

LABELS_PATH = PKG_PARENT / "assets" / "face_samples" / "labels.json"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="face_samples 导入 + 半自动标签初稿")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--video", nargs="+", help="视频文件路径（可多个）")
    g.add_argument("--images", help="静帧目录（jpg/png）")
    p.add_argument("--fps", type=float, default=2.0, help="视频抽帧率（默认 2）")
    p.add_argument("--max-frames", type=int, default=60, help="每片段最多入样帧数（默认 60）")
    p.add_argument("--open-enter", type=float, default=0.5, help="判张嘴进入阈值")
    p.add_argument("--open-exit", type=float, default=0.3, help="判张嘴退出阈值（滞回）")
    p.add_argument("--turn-deg", type=float, default=25.0, help="转头角阈值（度）")
    return p.parse_args(argv)


def extract_frames(src: Path, args, out_dir: Path) -> list[Path]:
    """从视频抽帧或从目录收静帧，统一写入 out_dir，返回帧路径列表。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    if src.is_file():
        cap = open_video_u(src)
        if cap is None:
            print(f"[跳过] 视频无法打开：{src}", file=sys.stderr)
            return frames
        fps = cap.get(__import__("cv2").CAP_PROP_FPS) or 30.0
        step = max(1, int(round(fps / max(args.fps, 0.1))))
        idx = 0
        while len(frames) < args.max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                fp = out_dir / f"f{len(frames):05d}.jpg"
                if imwrite_u(fp, frame, [int(__import__("cv2").IMWRITE_JPEG_QUALITY), 88]):
                    frames.append(fp)
            idx += 1
        release_video_u(cap)
    elif src.is_dir():
        exts = {".jpg", ".jpeg", ".png", ".bmp"}
        for f in sorted(x for x in src.iterdir() if x.suffix.lower() in exts):
            if len(frames) >= args.max_frames:
                break
            img = imread_u(f)
            if img is None:
                continue
            fp = out_dir / f"f{len(frames):05d}.jpg"
            if imwrite_u(fp, img, [int(__import__("cv2").IMWRITE_JPEG_QUALITY), 88]):
                frames.append(fp)
    else:
        print(f"[跳过] 路径不存在：{src}", file=sys.stderr)
    return frames


def auto_label(frames: list[Path], args, est: MouthEstimator) -> tuple[list[dict], list[float]]:
    """逐帧推理 → 滞回分段标签初稿。返回 (labels, jaw 曲线)。"""
    entries: list[dict] = []
    curve: list[float] = []
    state_open = False
    for fp in frames:
        img = imread_u(fp)
        pose = est.from_bgr(img) if img is not None else None
        if pose is None or not pose.valid:
            entries.append({"file": fp.name, "face": False, "jaw": None, "turn": None, "draft": True})
            curve.append(float("nan"))
            continue
        jaw = float(pose.jaw_open)
        curve.append(jaw)
        if not state_open and jaw > args.open_enter:
            state_open = True
        elif state_open and jaw < args.open_exit:
            state_open = False
        turn = abs(float(pose.head_yaw)) > __import__("math").radians(args.turn_deg)
        entries.append(
            {
                "file": fp.name,
                "face": True,
                "jaw": "open" if state_open else "closed",
                "turn": bool(turn),
                "draft": True,
                "jaw_open_raw": round(jaw, 3),
                "yaw_deg": round(float(pose.head_yaw) * 180.0 / 3.141592653589793, 1),
            }
        )
    return entries, curve


def contact_sheet(frames: list[Path], entries: list[dict], out_path: Path, cols: int = 4) -> None:
    import cv2
    import numpy as np

    cells = []
    for fp, e in zip(frames, entries):
        img = imread_u(fp)
        if img is None:
            continue
        h, w = img.shape[:2]
        s = 320.0 / max(w, 1)
        img = cv2.resize(img, (320, max(1, int(h * s))))
        tag = f"{e.get('jaw')} turn={e.get('turn')}"
        cv2.rectangle(img, (0, 0), (320, 22), (0, 0, 0), -1)
        cv2.putText(img, tag, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cells.append(img)
    if not cells:
        return
    ch = max(c.shape[0] for c in cells)
    rows = []
    for k in range(0, len(cells), cols):
        row = list(cells[k : k + cols])
        row = [
            np.pad(c, ((0, ch - c.shape[0]), (0, 0), (0, 0))) if c.shape[0] < ch else c
            for c in row
        ]
        while len(row) < cols:
            row.append(np.zeros((ch, 320, 3), np.uint8))
        rows.append(np.hstack(row))
    imwrite_u(out_path, np.vstack(rows), [int(cv2.IMWRITE_JPEG_QUALITY), 82])


def merge_labels(input_dir: Path, clip_key: str, entries: list[dict]) -> None:
    """把片段条目合并进 labels.json（同片段整组替换，其余保留）。"""
    data = {"version": 1, "note": "", "frames": []}
    try:
        data.update(json.loads(LABELS_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    prefix = f"clips/{clip_key}/"
    others = [f for f in data.get("frames", []) if not str(f.get("file", "")).startswith(prefix)]
    new = [{"file": f"clips/{clip_key}/{e['file']}", **{k: v for k, v in e.items() if k != "file"}} for e in entries]
    data["frames"] = others + new
    data.setdefault("meta", {})[clip_key] = {"imported": date.today().isoformat(), "frames": len(new)}
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABELS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    args = parse_args(argv)
    sources = [Path(v) for v in args.video] if args.video else [Path(args.images)]
    est = MouthEstimator(backend="mono")
    base = LABELS_PATH.parent
    n_total = 0
    for src in sources:
        clip_key = src.stem if src.is_file() else src.name
        out_dir = base / "clips" / clip_key
        frames = extract_frames(src, args, out_dir)
        if not frames:
            print(f"[无帧] {src}")
            continue
        entries, _ = auto_label(frames, args, est)
        contact_sheet(frames, entries, out_dir / "_contact_sheet.jpg")
        merge_labels(base, clip_key, entries)
        n_total += len(frames)
        n_open = sum(1 for e in entries if e.get("jaw") == "open")
        n_turn = sum(1 for e in entries if e.get("turn"))
        print(f"[完成] {src} -> {len(frames)} 帧（draft 张嘴 {n_open}，转头 {n_turn}）；"
              f"复核图 clips/{clip_key}/_contact_sheet.jpg")
    print(f"共导入 {n_total} 帧（draft=true，请对照 contact sheet 人工修订 labels.json）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
