"""evidence_transfer 车道 (SPECS_V2 §5.4) — 证据转移: 源视频低强度重绘。

管线 (侦察结论 D-060, 路径①=diffsynth 1.1.9 原生, 零新模型):
  源视频 (用户实拍或合成测试源, assets/evidence/)
  → 均匀采样 num_frames(4k+1, ≤81) 帧, 预缩放到产线分辨率
  → WanVideoPipeline(input_video=帧序列, input_image=首帧,
     denoising_strength=0.2-0.35) 低强度视频重绘
  → 输出 mp4。
重绘只加"氛围/风格", 场景结构/物体形态由源视频锁定 (denoise 越低越贴源)。

结构保持度验证 (M3 核心佐证, SPECS_V2 §5.4 必做):
  make_synthetic_source(): 静态图 + 程序 zoompan + 确定性粒子 → 已知运动合成源
  → 经重绘 → structural_persistence(): 源/输出 RAFT 光流场相关性 + 深度图相关性
  量化结构保持度。相关性低 → 换备选路径 (坑③预案, 数据裁决)。

证据激活接口: assets/evidence/README (用户放入实拍视频即激活);
镜头卡 evidence_asset 字段 (schema v4) 指向源视频。
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image

from ..config import project_root
from .common import even, reset_vram_counter, timed, vram_peak_mb, write_frames_mp4
from .wan import DENOISE_RANGE, LTX_FPS, WAN_MAX_FRAMES, load_wan_pipeline

EVIDENCE_MODEL_TAG = "evidence_transfer"
EVIDENCE_DIR = "assets/evidence"
DEFAULT_DENOISE = 0.30
SYNTH_FRAMES = 49  # 3s@16fps (4k+1)
SYNTH_ZOOM_TOTAL = 0.06  # 合成源已知运动: 3s 内 1.00→1.06 慢推
SYNTH_N_PARTICLES = 12
SYNTH_PARTICLE_SPEED = 0.9  # px/frame (对角向), 已知匀速直线


# ---------------- 源视频读取 ----------------

def read_source_frames(video_path: str, num_frames: int, size: tuple[int, int]) -> list[Image.Image]:
    """源视频均匀采样 num_frames 帧并预缩放到 size (pipeline 不再缩放, D-060)。

    源帧数不足 → 循环补齐; 超出 → 均匀抽样。返回 PIL RGB 列表。
    """
    import subprocess

    w, h = even(size[0]), even(size[1])
    argv = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw: list[np.ndarray] = []
    frame_bytes = w * h * 3
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        raw.append(np.frombuffer(buf, dtype="uint8").reshape(h, w, 3).copy())
    proc.stdout.close()
    proc.wait()
    if not raw:
        raise RuntimeError(f"证据源视频读取失败(空): {video_path}")
    idx = np.linspace(0, len(raw) - 1, int(num_frames)).round().astype(int)
    return [Image.fromarray(raw[i]).resize(size, Image.LANCZOS) for i in idx]


# ---------------- 车道入口 ----------------

def generate(
    card: dict,
    seed: int,
    out_path: str,
    steps: int = 20,
    fps: int = LTX_FPS,
    num_frames: int | None = None,
    pipeline=None,
    source_video: str | None = None,
    denoise: float = DEFAULT_DENOISE,
    guidance_delta: float = 0.0,
    device: str = "cuda",
) -> dict:
    """evidence_transfer 车道生成: 源视频低强度重绘 (denoise 等效 0.2-0.35)。

    pipeline 可注入 (签名同 wan.load_wan_pipeline 的 call, 须支持
    input_video/denoising_strength); source_video 显式传入优先于卡面 evidence_asset。
    """
    if not (DENOISE_RANGE[0] <= float(denoise) <= DENOISE_RANGE[1]):
        raise ValueError(
            f"证据重绘 denoise 必须 {DENOISE_RANGE[0]}-{DENOISE_RANGE[1]} (SPECS_V2 §5.4), 收到 {denoise}"
        )
    src = source_video or card.get("evidence_asset")
    if not src or not os.path.exists(src):
        raise FileNotFoundError(
            f"证据源视频不可用: {src!r} (镜头卡 evidence_asset / assets/evidence/)"
        )
    res = (int(card["resolution"][0]), int(card["resolution"][1]))
    nf = num_frames or min(frames_4k1(card["duration_sec"], fps), WAN_MAX_FRAMES)

    if pipeline is None:
        pipeline = load_wan_pipeline(device=device)

    frames_src = read_source_frames(src, nf, res)
    negative = list(card.get("negative", []))

    reset_vram_counter()
    with timed() as t:
        frames = pipeline(
            prompt=card["prompt_en"],
            negative=negative,
            first_frame=None,
            width=res[0],
            height=res[1],
            num_frames=nf,
            steps=int(steps),
            seed=int(seed),
            guidance_delta=float(guidance_delta),
            fps=int(fps),
            input_video=frames_src,
            denoising_strength=float(denoise),
        )
    write_frames_mp4(frames, fps, out_path)
    return {
        "path": out_path,
        "model": EVIDENCE_MODEL_TAG,
        "lane": "evidence_transfer",
        "source": str(src),
        "source_label": "synthetic_demo" if _is_synthetic(src) else "user_evidence",
        "denoise": float(denoise),
        "seed": int(seed),
        "steps": int(steps),
        "num_frames": nf,
        "duration_s": round(nf / fps, 4),
        "fps": int(fps),
        "vram_peak_mb": vram_peak_mb(),
        "gen_seconds": round(t.seconds, 3),
    }


def frames_4k1(duration_sec: float, fps: int = LTX_FPS) -> int:
    """时长 → 4k+1 帧数 (2..WAN_MAX_FRAMES)。纯函数。"""
    n = max(2, int(round(float(duration_sec) * fps)))
    return min(((n - 1) + 3) // 4 * 4 + 1, WAN_MAX_FRAMES)


def _is_synthetic(path: str) -> bool:
    return "synthetic" in os.path.basename(str(path)).lower()


# ---------------- 合成测试源 (已知运动 ground truth) ----------------

def _particle_positions(t_frame: int, w: int, h: int, n: int = SYNTH_N_PARTICLES) -> np.ndarray:
    """确定性粒子轨迹: 匀速直线 + 画布回绕 (closed-form, 无 RNG)。纯函数。"""
    i = np.arange(n, dtype="float32")
    x0 = (0.13 + 0.071 * i) * w
    y0 = (0.17 + 0.059 * i) * h
    dx = SYNTH_PARTICLE_SPEED * 0.7071 * t_frame
    dy = SYNTH_PARTICLE_SPEED * 0.7071 * t_frame
    x = (x0 + dx) % w
    y = (y0 + dy) % h
    return np.stack([x, y], axis=1)


def _draw_particles(canvas: np.ndarray, pts: np.ndarray, radius: int = 2) -> np.ndarray:
    """在画布上画亮粒子 (3x3~5x5 实心块, 确定性)。"""
    h, w = canvas.shape[:2]
    for x, y in pts:
        xi, yi = int(round(x)) % w, int(round(y)) % h
        x0, x1 = max(0, xi - radius), min(w, xi + radius + 1)
        y0, y1 = max(0, yi - radius), min(h, yi + radius + 1)
        if x1 > x0 and y1 > y0:
            canvas[y0:y1, x0:x1] = np.minimum(
                255, canvas[y0:y1, x0:x1].astype("int32") + 140
            ).astype("uint8")
    return canvas


def make_synthetic_source(
    base_image_path: str,
    out_mp4: str,
    n_frames: int = SYNTH_FRAMES,
    fps: int = LTX_FPS,
    size: tuple[int, int] = (480, 832),
) -> dict:
    """合成已知运动源: 静态图程序 zoompan (1.00→1.06 线性慢推) + 确定性匀速粒子。

    运动 ground truth 已知: 径向缩放流场 (解析) + 匀速平移粒子。
    """
    w, h = even(size[0]), even(size[1])
    img = Image.open(base_image_path).convert("RGB").resize((w, h), Image.LANCZOS)
    frames: list[np.ndarray] = []
    for i in range(int(n_frames)):
        t = i / max(1, n_frames - 1)
        s = 1.0 + SYNTH_ZOOM_TOTAL * t
        cw, ch = w / s, h / s
        box = ((w - cw) / 2, (h - ch) / 2, (w + cw) / 2, (h + ch) / 2)
        frame = np.asarray(img.resize((w, h), Image.BILINEAR, box=box), dtype="uint8").copy()
        frame = _draw_particles(frame, _particle_positions(i, w, h))
        frames.append(frame)
    write_frames_mp4(frames, fps, out_mp4)
    return {
        "path": out_mp4,
        "n_frames": int(n_frames),
        "fps": int(fps),
        "zoom_total": SYNTH_ZOOM_TOTAL,
        "n_particles": SYNTH_N_PARTICLES,
        "particle_speed_px_frame": SYNTH_PARTICLE_SPEED,
        "motion_gt": "radial_zoom(1.00->1.06 linear) + constant_velocity_particles",
    }


# ---------------- 结构保持度量化 ----------------

def load_raft_flow_fn(device: str = "cuda"):
    """RAFT-small fp32 → fn(imgA, imgB) -> np.ndarray (H,W,2) 光流场 (D-054 口径)。"""
    import torch
    import torchvision.transforms.functional as TF
    from torchvision.models.optical_flow import Raft_Small_Weights, raft_small

    src = project_root() / "models" / "raft" / "raft_small_C_T_V2-01064c6d.pth"
    ckpt_dir = os.path.expanduser("~/.cache/torch/hub/checkpoints")
    ckpt = os.path.join(ckpt_dir, "raft_small_C_T_V2-01064c6d.pth")
    if src.exists() and not os.path.exists(ckpt):
        os.makedirs(ckpt_dir, exist_ok=True)
        try:
            os.symlink(str(src), ckpt)
        except OSError:
            import shutil

            shutil.copy(str(src), ckpt)
    model = raft_small(weights=Raft_Small_Weights.DEFAULT).to(device).eval()
    tf = Raft_Small_Weights.DEFAULT.transforms()

    def flow(img_a: Image.Image, img_b: Image.Image) -> np.ndarray:
        ta = TF.to_tensor(img_a.convert("RGB")).unsqueeze(0).to(device)
        tb = TF.to_tensor(img_b.convert("RGB")).unsqueeze(0).to(device)
        ta_t, tb_t = tf(ta, tb)
        with torch.no_grad():
            fl = model(ta_t, tb_t)[-1]  # [1,2,H,W]
        return fl[0].detach().float().cpu().numpy().transpose(1, 2, 0)

    return flow


def depth_from_image(img: Image.Image) -> np.ndarray:
    """PIL 图 → HxW 深度图 (复用 compositing25 的 Depth-Anything 缓存管线)。"""
    from .compositing25 import get_depth_pipeline

    out = get_depth_pipeline()(img.convert("RGB"))
    return np.asarray(out["depth"], dtype="float32")


def structural_persistence(
    src_video: str,
    out_video: str,
    flow_fn=None,
    n_pairs: int = 6,
    size: tuple[int, int] = (480, 832),
    with_depth: bool = True,
) -> dict:
    """结构保持度量化: 源/输出的光流场相关性 + 深度图相关性。

    指标:
    - flow_cos: 相邻帧对光流向量场 (展平) 余弦相似度, 跨帧对平均 — 方向+幅度一致性;
    - flow_pearson: vx/vy 分量 Pearson 相关的平均值 — 线性结构一致性;
    - epe_px: 端点误差均值 (px, 同尺寸口径);
    - depth_corr_first/last: 首帧/末帧深度图 Pearson 相关 (结构骨架保持)。
    flow_fn 可注入 (CPU 单测); RAFT 输出分辨率与输入帧一致 (transforms 保尺寸)。
    """
    n_frames = min(frames_4k1(3.0), 49)
    src_frames = read_source_frames(src_video, n_frames, size)
    out_frames = read_source_frames(out_video, n_frames, size)

    if flow_fn is None:
        flow_fn = load_raft_flow_fn(device="cuda")

    idx = np.linspace(0, n_frames - 2, int(n_pairs)).round().astype(int)
    cos_l, pear_l, epe_l = [], [], []
    for i in idx:
        f_src = flow_fn(src_frames[i], src_frames[i + 1])
        f_out = flow_fn(out_frames[i], out_frames[i + 1])
        if f_out.shape != f_src.shape:  # 防御: 逐通道对齐到源光流分辨率
            f_out = np.stack([
                np.asarray(
                    Image.fromarray(_norm_u8(f_out[:, :, c])).resize(
                        (f_src.shape[1], f_src.shape[0]), Image.BILINEAR),
                    dtype="float32",
                )
                for c in range(2)
            ], axis=2)
        a = f_src.reshape(-1, 2).astype("float64")
        b = f_out.reshape(-1, 2).astype("float64")
        cos_l.append(_cos_flat(a, b))
        pear_l.append(_pearson(a[:, 0], b[:, 0]))
        pear_l.append(_pearson(a[:, 1], b[:, 1]))
        epe_l.append(float(np.sqrt(((a - b) ** 2).sum(axis=1)).mean()))

    result = {
        "flow_cos": round(float(np.mean(cos_l)), 4),
        "flow_cos_min": round(float(np.min(cos_l)), 4),
        "flow_pearson": round(float(np.mean(pear_l)), 4),
        "epe_px": round(float(np.mean(epe_l)), 3),
        "n_pairs": int(n_pairs),
        "flow_backend": getattr(flow_fn, "__name__", "injected"),
    }
    if with_depth:
        d_s0, d_o0 = depth_from_image(src_frames[0]), depth_from_image(out_frames[0])
        d_sn, d_on = depth_from_image(src_frames[-1]), depth_from_image(out_frames[-1])
        result["depth_corr_first"] = round(_pearson(d_s0.flatten(), d_o0.flatten()), 4)
        result["depth_corr_last"] = round(_pearson(d_sn.flatten(), d_on.flatten()), 4)
    return result


def _cos_flat(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float((a * b).sum() / (na * nb))


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype="float64").flatten()
    y = np.asarray(y, dtype="float64").flatten()
    if x.size < 2 or x.std() < 1e-9 or y.std() < 1e-9:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


def _norm_u8(a: np.ndarray) -> Image.Image:
    lo, hi = float(a.min()), float(a.max())
    if hi - lo < 1e-6:
        return Image.fromarray(np.zeros(a.shape, dtype="uint8"), mode="L")
    return Image.fromarray(((a - lo) / (hi - lo) * 255).astype("uint8"), mode="L")
