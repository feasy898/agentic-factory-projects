"""G7 物体恒存门禁 (SPECS_V2 §3): 五个子项 a-e, 任一子项触发即 fail。

背景: v1 六门禁工作在"帧语义+相邻平滑"空间, 看不见"物体同一性"空间的失败
(食物流体化/分裂融合/数量渐变/静态物体流动)。G7 用跨步采样+开放词表检测+
静态区光流+首尾漂移+VLM 成对审讯直接补这个盲区。

子项:
- a 跨步主体一致性: 帧 [0, N/4, N/2, 3N/4, N-1](跨步非相邻), 主体 bbox 区域
  (与 G7b 共用检测结果; 无检测框退全帧)提 DINOv2 embedding, 与 t0 余弦序列,
  min < 阈值 → fail。
- b 开放词表检测+跟踪计数: Grounding DINO(定版口径 fp32 权重+autocast fp16, D-054),
  文本提示由镜头卡 prompt_en 派生; 跟踪用 vendored 纯 Python ByteTrack 式 IoU 跟踪
  (稀疏采样下省略 Kalman, 见模块尾 D-056 注)。指标: ①计数时序(帧间变化>tol 或
  方差超阈) ②track churn(中生/中灭事件数, 即分裂/合并/ID跳变)。
- c 静态区光流: 首帧 SAM 按 subject 分割动态物体 → 反选静态区(或镜头卡
  expected_static_mask 显式指定); RAFT-small 相邻采样帧光流幅值 P95 超阈 → fail
  (RAFT 不可用退化光度差+SSIM)。锁定机位镜头专用; 无 subject/无检测框 → skipped。
- d 首尾漂移: 帧 N vs 帧 0 全帧 DINO 余弦(与 a 合并计算, 防跨步采样漏末段)。
- e VLM 成对审讯: 提示词全文见 g7_vlm_prompt.txt(含豁免条款), 首尾帧左右拼图,
  走 v1 vlm 适配器 API; API 不可用 → skipped+记录, 不做 CLIP 假实现(D-004)。

依赖注入: embed_fn/detect_fn/seg_fn/flow_fn/vlm_fn/frame_paths 均可 stub
(与 G3/G4 惯例一致), 全部纯逻辑可单测; torch 仅在 default_* 工厂内 lazy import。
"""

from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image

from . import make_gate

G7_GATE_ID = "G7"
G7_SUBS = ("a", "b", "c", "d", "e")
# 加权总分权重(活跃子项归一化); e 为 API 可用时的增补权重
SUB_WEIGHTS = {"a": 0.30, "b": 0.25, "c": 0.25, "d": 0.20, "e": 0.25}
N_SAMPLES_DEFAULT = 16  # 均匀采样帧数(5s@16fps → 帧距 ~0.33s, D-056)

# 冷启动阈值(SPECS_V2 §4; 全部以 M2 校准结果覆盖, 落 config/thresholds_v2.yaml)
COLD_START_THRESHOLDS = {
    "g7a_mode": "bbox",           # a 口径: bbox(规格 §3 原义) | full(校准定版, 见 thresholds_v2.yaml)
    "g7a_min_cos": 0.75,          # a: 跨步主体余弦最小值下限
    "g7b_count_delta_tol": 2.0,   # b: 帧间计数变化容差(> 触发)
    "g7b_count_var_max": 4.0,     # b: 计数时序方差上限(> 触发)
    "g7b_churn_max": 3.0,         # b: track churn(中生+中灭事件数)上限(> 触发)
    "g7c_flow_p95_max_px": 0.5,   # c: 静态区光流幅值 P95 上限(px, > 触发)
    "g7c_photo_diff_max": 0.08,   # c: RAFT 不可用退化判据-光度差上限(> 触发)
    "g7c_ssim_min": 0.60,         # c: RAFT 不可用退化判据-SSIM 下限(< 触发)
    "g7d_min_cos": 0.75,          # d: 首尾全帧余弦下限
    "g7e_min_ok": 0.6,            # e: 四项中任一 <0.6 → fail(规格定死)
    "det_box_threshold": 0.30,    # Grounding DINO box 置信度(运行期过滤口径)
    "det_text_threshold": 0.25,   # Grounding DINO text 置信度
    "det_high_thresh": 0.35,      # 跟踪器高/低分检测分界(GDINO 零样本分通常 <0.6)
}


def load_thresholds(path: str | None = None) -> dict:
    """冷启动值 + config/thresholds_v2.yaml 覆盖(yaml 顶层 g7: 键)。文件缺失→纯冷启动。"""
    th = dict(COLD_START_THRESHOLDS)
    p = Path(path) if path else _project_root() / "config" / "thresholds_v2.yaml"
    if p.exists():
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        g7 = data.get("g7", {}) if isinstance(data, dict) else {}
        for k in th:
            if isinstance(g7, dict) and g7.get(k) is not None:
                th[k] = g7[k]
    return th


def resolve_thresholds(thresholds: dict | None = None, thresholds_yaml: str | None = None) -> dict:
    """run_fixtures 阈值解析: 显式 yaml > 显式 dict(合并冷启动) > config/thresholds_v2.yaml。"""
    if thresholds_yaml:
        return load_thresholds(thresholds_yaml)
    if thresholds:
        return {**COLD_START_THRESHOLDS, **thresholds}
    return load_thresholds()


def _project_root() -> Path:
    try:
        from ..config import project_root

        return project_root()
    except Exception:  # pragma: no cover - 独立脚本场景
        return Path(__file__).resolve().parents[2]


# ---------------- 纯逻辑工具 ----------------

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def cosine(a, b) -> float:
    a = np.asarray(a, dtype="float64").flatten()
    b = np.asarray(b, dtype="float64").flatten()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def stride_indices(n: int, k: int = 5) -> list[int]:
    """跨步采样下标 [0, n/4, n/2, 3n/4, n-1](升序去重; n<5 时收缩并保首尾)。"""
    if n <= 0:
        return []
    if n == 1:
        return [0]
    idx = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1})
    return idx[:k] if len(idx) <= k else idx


def clamp_box(box, w: int, h: int) -> list[int]:
    x1, y1, x2, y2 = [int(round(float(v))) for v in box]
    x1, x2 = max(0, min(x1, w - 1)), max(0, min(x2, w - 1))
    y1, y2 = max(0, min(y1, h - 1)), max(0, min(y2, h - 1))
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def crop_box(img: Image.Image, box: list[int] | None) -> Image.Image:
    """主体 bbox 裁剪; box 为 None → 全帧。"""
    if not box:
        return img
    w, h = img.size
    return img.crop(clamp_box(box, w, h))


def union_box(boxes) -> list[int] | None:
    if not boxes:
        return None
    return [
        min(float(b[0]) for b in boxes),
        min(float(b[1]) for b in boxes),
        max(float(b[2]) for b in boxes),
        max(float(b[3]) for b in boxes),
    ]


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter
    return float(inter / denom) if denom > 0 else 0.0


def match_box(subject_box, dets, min_iou: float = 0.1):
    """在 dets 中找与 subject_box IoU 最高的框(≥min_iou), 用于跨帧主体区域跟随。"""
    best, best_iou = None, min_iou
    for d in dets or []:
        v = iou(subject_box, d["box"])
        if v > best_iou:
            best, best_iou = d["box"], v
    return best


def p95(vals) -> float:
    vals = list(vals)
    if not vals:
        return 0.0
    return float(np.percentile(np.asarray(vals, dtype="float64"), 95))


def count_series_metrics(counts: list[int]) -> dict:
    """计数时序指标: 帧间最大绝对变化 + 方差。"""
    if len(counts) < 2:
        return {"max_abs_delta": 0.0, "variance": 0.0}
    deltas = [abs(int(counts[i + 1]) - int(counts[i])) for i in range(len(counts) - 1)]
    arr = np.asarray(counts, dtype="float64")
    return {"max_abs_delta": float(max(deltas)), "variance": float(arr.var())}


def global_ssim(a_gray: np.ndarray, b_gray: np.ndarray) -> float:
    """全局 SSIM(纯 numpy, 无 skimage 依赖), 用作 RAFT 不可用时的退化判据之一。"""
    a = np.asarray(a_gray, dtype="float64")
    b = np.asarray(b_gray, dtype="float64")
    if a.shape != b.shape:
        b = np.asarray(Image.fromarray(b.astype(np.uint8)).resize(
            (a.shape[1], a.shape[0])), dtype="float64")
    mu_a, mu_b = a.mean(), b.mean()
    var_a, var_b = a.var(), b.var()
    cov = ((a - mu_a) * (b - mu_b)).mean()
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    denom = (var_a + var_b + c2)
    if denom <= 0:
        return 1.0 if var_a == var_b else 0.0
    return float(((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * denom))


def to_gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype="float64")


# ---------------- G7b: 开放词表派生 + vendored 跟踪 ----------------

# 检测词表(按出现顺序做跨度消费, 避免重复; 均为可数固态/器皿名词, 刻意排除
# steam/smoke/light/bokeh 等豁免类元素, 与 G7e 豁免条款一致)
_DETECT_LEXICON = (
    ("beef tripe", "tripe"),
    ("shrimp paste", "shrimp"),
    ("fatty beef", "beef"),
    ("rice cake", "rice cake"),
    ("hot pot", "hot pot"),
    ("hotpot", "hot pot"),
    ("broth", "broth"),
    ("soup", "soup"),
    ("tripe", "tripe"),
    ("shrimp", "shrimp"),
    ("beef", "beef"),
    ("chilies", "chili"),
    ("chili", "chili"),
    ("peppercorn", "peppercorn"),
    ("strainer", "strainer"),
    ("ladle", "ladle"),
    ("bowl", "bowl"),
    ("plate", "plate"),
    ("pot", "pot"),
    ("glass", "glass"),
    ("cup", "cup"),
    ("bottle", "bottle"),
    ("drink", "drink"),
    ("juice", "juice"),
    ("cake", "cake"),
    ("table", "table"),
    ("tableware", "tableware"),
    ("chopsticks", "chopsticks"),
    ("spoon", "spoon"),
    ("lantern", "lantern"),
    ("storefront", "storefront"),
    ("street", "street"),
    ("window", "window"),
    ("corridor", "corridor"),
)


def derive_detect_terms(card: dict, max_terms: int = 5) -> list[str]:
    """从镜头卡 prompt_en(+subject) 派生 Grounding DINO 检测词表。

    无命中 → [](调用方据此跳过 G7b/c, 如 ken_burns 程序产物无生成主体)。
    """
    texts = [str(card.get("prompt_en") or "")]
    subj = card.get("subject") or {}
    if isinstance(subj, dict):
        texts.append(str(subj.get("desc_en") or ""))
    text = " ".join(texts).lower()
    consumed: list[tuple[int, int]] = []
    terms: list[str] = []
    for phrase, canonical in _DETECT_LEXICON:
        if len(terms) >= max_terms:
            break
        for m in re.finditer(rf"\b{re.escape(phrase)}s?\b", text):
            span = m.span()
            if any(s < span[1] and span[0] < e for s, e in consumed):
                continue
            consumed.append(span)
            if canonical not in terms:
                terms.append(canonical)
            break
    return terms


def build_gdino_prompt(terms: list[str]) -> str:
    """Grounding DINO 文本提示: "shrimp. bowl. hot pot."。"""
    return ". ".join(t for t in terms if t) + "." if terms else ""


class LiteByteTracker:
    """精简 ByteTrack 式 IoU 跟踪(vendored 纯 Python, SPECS_V2 §3 允许)。

    稀疏采样(帧距 ~0.33s)下 Kalman 预测无意义, 采用: 高/低分两级检测
    (score 高于 high_thresh 优先关联, 低分兜底), 贪心 IoU 关联(lap 不做强依赖),
    confirmed 需累计命中 ≥min_hits(滤单帧误检), max_age 帧内丢失可复活(滤抖动)。
    """

    def __init__(self, high_thresh: float = 0.5, iou_thr: float = 0.4,
                 max_age: int = 2, min_hits: int = 2):
        self.high_thresh = float(high_thresh)
        self.iou_thr = float(iou_thr)
        self.max_age = int(max_age)
        self.min_hits = int(min_hits)
        self.tracks: list[dict] = []
        self._next_id = 1
        self._frame_idx = -1

    def _new_track(self, det, frame_idx: int) -> dict:
        return {"id": self._next_id, "box": list(det["box"]), "score": float(det["score"]),
                "hits": 1, "age": 0, "born": frame_idx, "last_seen": frame_idx, "dead": None,
                "confirmed": self.min_hits <= 1}

    def update(self, dets, frame_idx: int) -> list[int]:
        """喂入一帧检测, 返回本帧 confirmed track id 列表。

        关联次序(精简 BYTE): ①高分检测 vs 全部可跟 track(丢失者可复活);
        ②低分检测 vs 仅连续在跟的 track(不用低分复活); ③高分剩余孵化新 track。
        """
        self._frame_idx = frame_idx
        dets = sorted(dets or [], key=lambda d: -float(d.get("score", 0.0)))
        high = [d for d in dets if float(d.get("score", 0.0)) > self.high_thresh]
        low = [d for d in dets if float(d.get("score", 0.0)) <= self.high_thresh]
        used_tracks: set[int] = set()
        used_high: set[int] = set()
        used_low: set[int] = set()

        def associate(group, track_filter, used_det):
            for tr in self.tracks:
                if id(tr) in used_tracks or not track_filter(tr):
                    continue
                best_j, best_v = -1, self.iou_thr
                for j, d in enumerate(group):
                    if j in used_det:
                        continue
                    v = iou(tr["box"], d["box"])
                    if v > best_v:
                        best_j, best_v = j, v
                if best_j >= 0:
                    used_tracks.add(id(tr))
                    used_det.add(best_j)
                    d = group[best_j]
                    tr["box"] = list(d["box"])
                    tr["score"] = float(d["score"])
                    tr["hits"] += 1
                    tr["age"] = 0
                    tr["last_seen"] = frame_idx
                    if tr["hits"] >= self.min_hits:
                        tr["confirmed"] = True

        associate(high, lambda tr: tr["age"] <= self.max_age, used_high)   # ①
        associate(low, lambda tr: tr["age"] == 0, used_low)                # ②
        spawned: set[int] = set()
        for j, d in enumerate(high):                                       # ③
            if j not in used_high:
                tr_new = self._new_track(d, frame_idx)
                self.tracks.append(tr_new)
                spawned.add(id(tr_new))
        for tr in self.tracks:                                             # ④老化(新生存不加龄)
            if id(tr) not in used_tracks and id(tr) not in spawned:
                tr["age"] += 1
        return [tr["id"] for tr in self.tracks if tr["confirmed"] and tr["age"] == 0]

    def finish(self, last_frame_idx: int | None = None) -> None:
        """终结全部 track(补齐死亡帧信息; 末帧仍存活者死于末帧)。"""
        last = last_frame_idx if last_frame_idx is not None else self._frame_idx
        for tr in self.tracks:
            if tr["dead"] is None:
                tr["dead"] = last if tr["last_seen"] >= last else tr["last_seen"]


def tracker_stats(tracker: LiteByteTracker, n_frames: int) -> dict:
    """跟踪统计: 每帧 confirmed 计数 + churn(中生/中灭事件数)。

    计数 = confirmed track 的存活区间 [born, last_seen] 覆盖(确认对全程回溯,
    避免 min_hits 预热期把首帧计成 0); churn 只统计 confirmed track 的
    中生(首帧后出生)+中灭(末帧前死亡), 未确认的单帧噪声不计(滤误检)。
    """
    tracker.finish(last_frame_idx=n_frames - 1)
    counts = []
    for i in range(n_frames):
        c = sum(1 for tr in tracker.tracks
                if tr["confirmed"] and tr["born"] <= i <= tr["last_seen"])
        counts.append(c)
    births = sum(1 for tr in tracker.tracks if tr["confirmed"] and tr["born"] > 0)
    deaths = sum(1 for tr in tracker.tracks if tr["confirmed"] and tr["dead"] < n_frames - 1)
    return {"counts": counts, "births": births, "deaths": deaths,
            "churn": births + deaths, "n_tracks": len(tracker.tracks)}


# ---------------- G7e: 提示词与解析 ----------------

def prompt_file_path() -> Path:
    return Path(__file__).resolve().parent / "g7_vlm_prompt.txt"


def load_prompt_text() -> str:
    return prompt_file_path().read_text(encoding="utf-8")


G7E_KEYS = ("object_shape_kept", "object_count_kept", "no_liquid_flow", "no_split_merge")


def parse_g7e_json(text) -> dict:
    """解析 G7e VLM 返回(容代码围栏/前后缀); 四项缺失或非数值抛 ValueError。"""
    if isinstance(text, dict):
        raw = text
    else:
        s = str(text).strip()
        if "```" in s:
            s = max(s.split("```"), key=len)
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            raise ValueError(f"G7e 返回中未找到 JSON 对象: {str(text)[:120]!r}")
        raw = json.loads(s[i:j + 1])
    out = {}
    for k in G7E_KEYS:
        if k not in raw:
            raise ValueError(f"G7e JSON 缺少 {k}")
        out[k] = clamp01(float(raw[k]))
    out["verdict"] = str(raw.get("verdict", ""))
    out["main_issue"] = str(raw.get("main_issue", ""))
    return out


def g7e_triggered(parsed: dict, min_ok: float = 0.6) -> bool:
    """四项中任一 < min_ok 或 verdict=fail → 触发。"""
    if any(v < min_ok for v in (parsed[k] for k in G7E_KEYS)):
        return True
    return str(parsed.get("verdict", "")).strip().lower() == "fail"


def make_pair_image(img_first: Image.Image, img_last: Image.Image, out_path: str) -> str:
    """首尾帧左右拼图(左=开头, 右=结尾)。以左帧(开头)高度为基准, 右帧等比对齐。"""
    a, b = img_first.convert("RGB"), img_last.convert("RGB")
    h = a.height
    if b.height != h:
        b = b.resize((max(1, int(b.width * h / b.height)), h))
    canvas = Image.new("RGB", (a.width + b.width + 8, h), (255, 255, 255))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + 8, 0))
    canvas.save(out_path)
    return out_path


# ---------------- 帧抽取 ----------------

def extract_frames_uniform(video_path: str, out_dir: str, n: int = N_SAMPLES_DEFAULT) -> list[str]:
    """ffmpeg 均匀抽 n 帧到 out_dir(时长探测复用 g1_tech)。"""
    import subprocess

    from .g1_tech import probe_duration

    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "frame_*.png")):
        os.remove(old)
    duration = probe_duration(video_path)
    fps_expr = f"fps={n}/{max(duration, 1e-6):.6f}"
    argv = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_path,
            "-vf", fps_expr, "-frame_pts", "0", os.path.join(out_dir, "frame_%03d.png")]
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    if cp.returncode != 0:
        raise RuntimeError(f"G7 抽帧失败: {cp.stderr[-300:]}")
    return sorted(glob.glob(os.path.join(out_dir, "frame_*.png")))


# ---------------- 主入口(全链可注入) ----------------

def _sub(sub_id: str, *, skipped: bool = False, reason: str | None = None, **kw) -> dict:
    """子项结果骨架: skipped 时 score=1.0(中性, 不触发, 不入加权)。"""
    base = {"sub": sub_id, "skipped": bool(skipped), "reason": reason,
            "score": 1.0, "triggered": False}
    base.update(kw)
    return base


def g7_object_persistence(
    video_path: str,
    detect_terms: list[str] | None,
    thresholds: dict | None = None,
    *,
    embed_fn=None,
    detect_fn=None,
    seg_fn=None,
    flow_fn=None,
    vlm_fn=None,
    frame_paths: list[str] | None = None,
    frames_dir: str | None = None,
    n_samples: int = N_SAMPLES_DEFAULT,
    expected_static_mask: str | None = None,
    prompt_text: str | None = None,
) -> dict:
    """G7 主入口。detect_terms 为空 → b/c 按无主体跳过(a/d 全帧口径)。

    任一活跃子项 triggered → G7 passed=False; score=活跃子项加权均值(0-1)。
    detail 内含全部原始指标(校准脚本据此做阈值扫描, 无需重跑模型)。
    """
    th = {**COLD_START_THRESHOLDS, **(thresholds or {})}
    terms = list(detect_terms or [])

    if frame_paths is None:
        frames_dir = frames_dir or f"{video_path}.g7frames"
        frame_paths = extract_frames_uniform(video_path, frames_dir, n_samples)
    if len(frame_paths) < 2:
        return make_gate(G7_GATE_ID, True, 1.0,
                         a=_sub("a", skipped=True, reason="insufficient_frames"),
                         b=_sub("b", skipped=True, reason="insufficient_frames"),
                         c=_sub("c", skipped=True, reason="insufficient_frames"),
                         d=_sub("d", skipped=True, reason="insufficient_frames"),
                         e=_sub("e", skipped=True, reason="insufficient_frames"),
                         thresholds=th, meta={"n_frames": len(frame_paths), "terms": terms})

    imgs = [Image.open(p).convert("RGB") for p in frame_paths]
    n = len(imgs)
    stride = stride_indices(n)

    # --- 共用检测(G7b) ---
    dets_per_frame = None
    prompt = build_gdino_prompt(terms) if (detect_fn and terms) else ""
    if prompt:
        dets_per_frame = [detect_fn(img, prompt) for img in imgs]
    # 运行期检测阈值过滤(检测器本身跑低门槛, 便于校准离线重放); 主体框用运行期口径
    rt_thr = float(th.get("det_box_threshold", 0.30))
    dets_rt = ([[d for d in dets if float(d["score"]) >= rt_thr] for dets in dets_per_frame]
               if dets_per_frame else None)
    subject_box = union_box([d["box"] for d in dets_rt[0]]) if dets_rt else None

    # --- G7a 跨步主体一致性 ---
    # g7a_mode: "bbox"(规格 §3 原义, 主体区域) | "full"(校准定版 D-059: 检测框抖动使
    # bbox 口径可分性劣于全帧, 校准后默认 full; 两种口径的序列都落盘可复查)
    a_mode = str(th.get("g7a_mode", "bbox"))
    sub_a = _sub("a", n_frames=len(stride), bbox=subject_box, sims=[], threshold=float(th["g7a_min_cos"]),
                 mode=a_mode)
    if embed_fn is None:
        sub_a.update(skipped=True, reason="no_embed_fn")
    else:
        crop0 = crop_box(imgs[stride[0]], subject_box)
        e0 = embed_fn(crop0)
        sims, full_sims = [], []
        ef0 = embed_fn(imgs[stride[0]])  # 全帧口径(M0 D-052 扫描可比), 校准期对照 a_bbox
        for i in stride[1:]:
            bi = match_box(subject_box, dets_per_frame[i]) if dets_per_frame else None
            bi = bi or subject_box
            sims.append(cosine(e0, embed_fn(crop_box(imgs[i], bi))))
            full_sims.append(cosine(ef0, embed_fn(imgs[i])))
        sub_a["sims"] = [round(s, 4) for s in sims]
        sub_a["sims_fullframe"] = [round(s, 4) for s in full_sims]
        vals = full_sims if a_mode == "full" else sims
        sub_a["score"] = round(min(vals), 4) if vals else 1.0
        sub_a["triggered"] = bool(vals) and sub_a["score"] < th["g7a_min_cos"]

    # --- G7d 首尾漂移(全帧, 与 a 合并计算) ---
    sub_d = _sub("d", threshold=float(th["g7d_min_cos"]))
    if embed_fn is None:
        sub_d.update(skipped=True, reason="no_embed_fn")
    else:
        sub_d["score"] = round(cosine(embed_fn(imgs[0]), embed_fn(imgs[-1])), 4)
        sub_d["triggered"] = sub_d["score"] < th["g7d_min_cos"]

    # --- G7b 检测+跟踪计数 ---
    sub_b = _sub("b", threshold={"count_delta_tol": float(th["g7b_count_delta_tol"]),
                                 "count_var_max": float(th["g7b_count_var_max"]),
                                 "churn_max": float(th["g7b_churn_max"])})
    if dets_per_frame is None:
        sub_b.update(skipped=True, reason="no_terms_or_detect_fn")
    else:
        # 原始检测全量落盘(低门槛), 校准期可离线重放任意检测阈值 (GPU 不重跑)
        sub_b["dets_raw"] = [
            [{"box": [round(v, 1) for v in d["box"]], "score": round(float(d["score"]), 4),
              "label": d.get("label", "")} for d in dets if float(d["score"]) >= 0.20]
            for dets in dets_per_frame
        ]
        sub_b["dets_runtime_threshold"] = rt_thr
        tracker = LiteByteTracker(high_thresh=float(th.get("det_high_thresh", 0.35)))
        for i, dets in enumerate(dets_rt):
            tracker.update(dets, i)
        stats = tracker_stats(tracker, n)
        m = count_series_metrics(stats["counts"])
        sub_b.update(
            counts=stats["counts"], max_abs_delta=round(m["max_abs_delta"], 3),
            variance=round(m["variance"], 4), churn=stats["churn"],
            births=stats["births"], deaths=stats["deaths"], n_tracks=stats["n_tracks"],
        )
        if sum(stats["counts"]) == 0:
            sub_b.update(skipped=True, reason="no_detections")
        else:
            trig_delta = m["max_abs_delta"] > th["g7b_count_delta_tol"]
            trig_var = m["variance"] > th["g7b_count_var_max"]
            trig_churn = stats["churn"] > th["g7b_churn_max"]
            sub_b["triggered"] = bool(trig_delta or trig_var or trig_churn)
            excess = (
                max(0.0, m["max_abs_delta"] - th["g7b_count_delta_tol"]) / max(1.0, th["g7b_count_delta_tol"])
                + max(0.0, m["variance"] - th["g7b_count_var_max"]) / max(1.0, th["g7b_count_var_max"])
                + max(0.0, stats["churn"] - th["g7b_churn_max"]) / max(1.0, th["g7b_churn_max"])
            )
            sub_b["score"] = round(clamp01(1.0 - excess), 4)
            sub_b["trigger_detail"] = {"delta": trig_delta, "var": trig_var, "churn": trig_churn}

    # --- G7c 静态区光流 ---
    sub_c = _sub("c", threshold=float(th["g7c_flow_p95_max_px"]))
    t0_dets = dets_per_frame[0] if dets_per_frame else []
    static_mask = None
    if expected_static_mask and os.path.exists(expected_static_mask):
        m_img = Image.open(expected_static_mask).convert("L").resize(imgs[0].size, Image.NEAREST)
        static_mask = np.asarray(m_img) > 127
        sub_c["mask_source"] = "expected_static_mask"
    elif t0_dets and seg_fn is not None:
        dynamic = seg_fn(imgs[0], [d["box"] for d in t0_dets])
        static_mask = ~np.asarray(dynamic, dtype=bool)
        sub_c["mask_source"] = "sam_inverse"
        sub_c["dynamic_area_ratio"] = round(float(np.asarray(dynamic, dtype=bool).mean()), 4)
    if flow_fn is None:
        sub_c.update(skipped=True, reason="no_flow_fn")
    elif static_mask is None:
        sub_c.update(skipped=True, reason="no_subject_or_mask")
    else:
        pairs = []
        for i in range(n - 1):
            r = flow_fn(imgs[i], imgs[i + 1], static_mask)
            r = r if isinstance(r, dict) else {"p95_px": r}
            pairs.append(r)
        p95s = [float(r.get("p95_px")) for r in pairs if r.get("p95_px") is not None]
        p95s_full = [float(r["p95_px_full"]) for r in pairs if r.get("p95_px_full") is not None]
        sub_c["p95_px_per_pair"] = [round(v, 3) for v in p95s]
        sub_c["p95_px_full_per_pair"] = [round(v, 3) for v in p95s_full]
        sub_c["raft"] = bool(pairs and pairs[0].get("raft", True))
        if p95s:
            worst = max(p95s)
            sub_c["p95_px"] = round(worst, 3)
            sub_c["triggered"] = worst > th["g7c_flow_p95_max_px"]
            sub_c["score"] = round(clamp01(th["g7c_flow_p95_max_px"] / max(worst, 1e-6)), 4)
        else:  # RAFT 不可用退化: 光度差 + SSIM(静态区内)
            photos = [float(r.get("photo_diff", 0.0)) for r in pairs]
            ssims = [float(r.get("ssim", 1.0)) for r in pairs]
            sub_c["photo_diff_max"] = round(max(photos), 4)
            sub_c["ssim_min"] = round(min(ssims), 4)
            sub_c["raft"] = False
            sub_c["triggered"] = bool(
                max(photos) > th["g7c_photo_diff_max"] or min(ssims) < th["g7c_ssim_min"])
            sub_c["score"] = round(clamp01(1.0 - max(photos) / max(th["g7c_photo_diff_max"], 1e-6)), 4)
        sub_c["n_pairs"] = len(pairs)

    # --- G7e VLM 成对审讯 ---
    sub_e = _sub("e", threshold=float(th["g7e_min_ok"]))
    if vlm_fn is None:
        sub_e.update(skipped=True, reason="vlm_unavailable")
    else:
        try:
            base_dir = frames_dir or (os.path.dirname(frame_paths[0]) or ".")
            pair_png = os.path.join(base_dir, "g7e_pair.png")
            os.makedirs(base_dir, exist_ok=True)
            make_pair_image(imgs[0], imgs[-1], pair_png)
            pt = prompt_text if prompt_text is not None else load_prompt_text()
            parsed = parse_g7e_json(vlm_fn(pair_png, pt))
            sub_e.update(parsed=parsed, score=round(min(parsed[k] for k in G7E_KEYS), 4))
            sub_e["triggered"] = g7e_triggered(parsed, th["g7e_min_ok"])
        except Exception as exc:  # noqa: BLE001 — VLM 异常/解析失败如实记录, 不误杀
            sub_e.update(skipped=True, reason=f"vlm_failed: {exc}"[:300])

    # --- 聚合 ---
    active = {s: d for s, d in (("a", sub_a), ("b", sub_b), ("c", sub_c), ("d", sub_d), ("e", sub_e))
              if not d["skipped"]}
    triggered_any = any(d["triggered"] for d in active.values())
    w_sum = sum(SUB_WEIGHTS[s] for s in active)
    score = (sum(SUB_WEIGHTS[s] * float(d["score"]) for s, d in active.items()) / w_sum) if w_sum else 1.0

    gate = make_gate(
        G7_GATE_ID, not triggered_any, round(float(score), 4),
        a=sub_a, b=sub_b, c=sub_c, d=sub_d, e=sub_e,
        thresholds=th,
        meta={"n_frames": n, "stride": stride, "terms": terms,
              "gdino_prompt": prompt or None, "sample_fps_basis": n_samples},
    )
    return gate


# ---------------- 缺省模型工厂(进程级缓存, GPU 串行纪律: 用毕 del+empty_cache 由调用方) ----------------

_DEFAULT_CACHE: dict = {}


def default_embed_fn(device: str = "cuda"):
    """DINOv2 ViT-L/14 fp16, CLS token(M0 扫描同口径, D-052 可比)。"""
    key = ("embed", device)
    if key in _DEFAULT_CACHE:
        return _DEFAULT_CACHE[key]
    import torch
    from transformers import AutoImageProcessor, AutoModel

    mp = _project_root() / "models" / "dinov2-large"
    if not mp.exists():
        raise RuntimeError(f"DINOv2 模型缺失: {mp}")
    proc = AutoImageProcessor.from_pretrained(str(mp))
    model = AutoModel.from_pretrained(str(mp), torch_dtype=torch.float16).to(device).eval()

    def embed(img: Image.Image) -> np.ndarray:
        x = proc(images=img, return_tensors="pt")
        with torch.no_grad():
            o = model(pixel_values=x.pixel_values.half().to(device))
        return o.last_hidden_state[:, 0][0].float().cpu().numpy()

    _DEFAULT_CACHE[key] = embed
    return embed


def default_detect_fn(device: str = "cuda", box_threshold: float = 0.30, text_threshold: float = 0.25):
    """Grounding DINO tiny; 定版口径 fp32 权重 + autocast(fp16)(D-054, 纯 .half() 有 dtype bug)。"""
    key = ("detect", device, box_threshold, text_threshold)
    if key in _DEFAULT_CACHE:
        return _DEFAULT_CACHE[key]
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    mp = _project_root() / "models" / "grounding-dino-tiny"
    if not mp.exists():
        raise RuntimeError(f"Grounding DINO 模型缺失: {mp}")
    proc = AutoProcessor.from_pretrained(str(mp))
    model = AutoModelForZeroShotObjectDetection.from_pretrained(
        str(mp), torch_dtype=torch.float32).to(device).eval()

    def detect(img: Image.Image, prompt: str) -> list[dict]:
        inputs = proc(images=img, text=prompt, return_tensors="pt").to(device)
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
            out = model(**inputs)
        # target_sizes 必须传原始 (H, W), 否则返回 [0,1] 归一化坐标(transformers 4.49 实测);
        # threshold 为 4.49 形参名(box_threshold 是旧名, 会被 **kwargs 静默吞掉)
        res = proc.post_process_grounded_object_detection(
            out, inputs.input_ids, threshold=box_threshold, text_threshold=text_threshold,
            target_sizes=[(img.height, img.width)])[0]
        boxes = res["boxes"].detach().cpu().float().tolist()
        scores = res["scores"].detach().cpu().float().tolist()
        labels = res.get("text_labels")
        if labels is None:
            labels = res.get("labels", [])
        w, h = img.size
        return [{"box": clamp_box(b, w, h), "score": round(float(s), 4), "label": str(l)}
                for b, s, l in zip(boxes, scores, labels)]

    _DEFAULT_CACHE[key] = detect
    return detect


def default_seg_fn(device: str = "cuda"):
    """SAM ViT-B fp16, box 提示分割, 返回多框并集 bool mask(H,W)。"""
    key = ("seg", device)
    if key in _DEFAULT_CACHE:
        return _DEFAULT_CACHE[key]
    import torch
    from transformers import SamModel, SamProcessor

    mp = _project_root() / "models" / "sam-vit-base"
    if not mp.exists():
        raise RuntimeError(f"SAM 模型缺失: {mp}")
    proc = SamProcessor.from_pretrained(str(mp))
    model = SamModel.from_pretrained(str(mp), torch_dtype=torch.float16).to(device).eval()

    def segment(img: Image.Image, boxes: list[list]) -> np.ndarray:
        inputs = proc(images=img, input_boxes=[boxes], return_tensors="pt").to(device)
        inputs["pixel_values"] = inputs["pixel_values"].half()
        with torch.no_grad():
            out = model(**inputs)
        masks = proc.image_processor.post_process_masks(
            out.pred_masks.cpu(), inputs["original_sizes"].cpu(),
            inputs["reshaped_input_sizes"].cpu())[0]  # [n_boxes, 1, H, W]
        union = None
        arr = masks[:, 0].numpy() if hasattr(masks, "numpy") else np.asarray(masks[:, 0])
        for i in range(arr.shape[0]):
            m = arr[i] > 0
            union = m if union is None else (union | m)
        return union if union is not None else np.zeros((img.height, img.width), dtype=bool)

    _DEFAULT_CACHE[key] = segment
    return segment


def default_flow_fn(device: str = "cuda"):
    """RAFT-small fp32 相邻采样帧光流; 加载失败自动退化光度差+SSIM(SPECS_V2 §3-G7c)。

    返回 fn(imgA, imgB, static_mask)->{"p95_px"|None, "photo_diff", "ssim", "raft"}。
    """
    try:
        import torch
        import torchvision.transforms.functional as TF
        from torchvision.models.optical_flow import Raft_Small_Weights, raft_small

        src = _project_root() / "models" / "raft" / "raft_small_C_T_V2-01064c6d.pth"
        ckpt_dir = os.path.expanduser("~/.cache/torch/hub/checkpoints")
        ckpt = os.path.join(ckpt_dir, "raft_small_C_T_V2-01064c6d.pth")
        if src.exists() and not os.path.exists(ckpt):
            os.makedirs(ckpt_dir, exist_ok=True)
            try:
                os.symlink(str(src), ckpt)
            except OSError:
                import shutil

                shutil.copy(str(src), ckpt)
        weights = Raft_Small_Weights.DEFAULT
        model = raft_small(weights=weights).to(device).eval()
        tf = weights.transforms()
        raft_ok = True
    except Exception as exc:  # noqa: BLE001
        raft_ok = False
        _raft_err = str(exc)

    def flow(img_a: Image.Image, img_b: Image.Image, static_mask: np.ndarray | None) -> dict:
        a_np = np.asarray(img_a.convert("RGB"), dtype="float32") / 255.0
        b_np = np.asarray(img_b.convert("RGB"), dtype="float32") / 255.0
        mask = static_mask
        if mask is not None and mask.shape != a_np.shape[:2]:
            m_img = Image.fromarray((mask.astype(np.uint8) * 255)).resize(
                (a_np.shape[1], a_np.shape[0]), Image.NEAREST)
            mask = np.asarray(m_img) > 127
        if raft_ok:
            ta = TF.to_tensor(img_a.convert("RGB")).unsqueeze(0).to(device)
            tb = TF.to_tensor(img_b.convert("RGB")).unsqueeze(0).to(device)
            ta_t, tb_t = tf(ta, tb)
            with torch.no_grad():
                fl = model(ta_t, tb_t)[-1]  # [1,2,H,W]
            mag = torch.sqrt(fl[0, 0] ** 2 + fl[0, 1] **2).detach().cpu().numpy()
            p95_full = float(np.percentile(mag.flatten(), 95))  # 全帧口径, 校准对照用
            if mask is not None:
                if mask.shape != mag.shape:
                    m_img = Image.fromarray((mask.astype(np.uint8) * 255)).resize(
                        (mag.shape[1], mag.shape[0]), Image.NEAREST)
                    mask_m = np.asarray(m_img) > 127
                else:
                    mask_m = mask
                vals = mag[mask_m]
            else:
                vals = mag.flatten()
            p95_px = float(np.percentile(vals, 95)) if vals.size >= 50 else 0.0
        else:
            p95_px = None
            p95_full = None
        if mask is not None:
            diff = np.abs(a_np - b_np).mean(axis=2)[mask]
            photo = float(diff.mean()) if diff.size else 0.0
            ssim_v = global_ssim(
                (a_np.mean(axis=2) * 255).astype(np.uint8), (b_np.mean(axis=2) * 255).astype(np.uint8))
        else:
            photo = float(np.abs(a_np - b_np).mean())
            ssim_v = global_ssim(
                (a_np.mean(axis=2) * 255).astype(np.uint8), (b_np.mean(axis=2) * 255).astype(np.uint8))
        return {"p95_px": p95_px, "p95_px_full": p95_full,
                "photo_diff": photo, "ssim": ssim_v, "raft": raft_ok}

    return flow


def default_vlm_fn(db=None):
    """VLM API 适配器(仅 API; D-004 无 API → None → 调用方按 skipped 处理, 不做 CLIP 假实现)。"""
    from ..config import api_env_path, parse_api_env

    env = parse_api_env(api_env_path())
    if not env["VLM"]["configured"]:
        return None
    from ..api.adapters import BudgetGuard, endpoint_from_env
    from ..api.vlm import api_review

    endpoint = endpoint_from_env(env, "VLM")
    budget = BudgetGuard(db) if db is not None else None

    def call(pair_png: str, prompt_text: str, **kw):
        out = api_review(endpoint, pair_png, prompt_text, **kw)
        if budget is not None:
            budget.record("vlm", "api", True)
        return out

    return call


# ---------------- 夹具库复跑入口 ----------------

def _default_terms_json() -> Path:
    return _project_root() / "workdir" / "fixtures" / "g7_terms.json"


def run_fixtures(
    db,
    thresholds: dict | None = None,
    thresholds_yaml: str | None = None,
    terms_json: str | None = None,
    out_json: str | None = None,
    frames_root: str | None = None,
    labels: list[str] | None = None,
    limit: int | None = None,
    n_samples: int = N_SAMPLES_DEFAULT,
    fns: dict | None = None,
) -> dict:
    """全部夹具过 G7, 每子项分数落 g7_runs 表 + JSON 快照(SPECS_V2 §3-6)。

    fns: 注入 {embed_fn, detect_fn, seg_fn, flow_fn, vlm_fn}(单测/离线复算用),
    缺省加载本地模型; vlm_fn 缺省走 default_vlm_fn(无 API → None → e 项 skipped)。
    """
    fns = fns or {}
    th = resolve_thresholds(thresholds, thresholds_yaml)
    tp = Path(terms_json) if terms_json else _default_terms_json()
    terms_map = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
    frames_root = frames_root or str(_project_root() / "workdir" / "v2m1_frames")

    fns = fns or {}
    embed_fn = fns.get("embed_fn") or default_embed_fn()
    # 检测器跑低门槛(0.25, M0 冒烟口径), 运行期过滤与校准重放由 det_box_threshold 控制
    det_thr = min(0.25, float(th["det_box_threshold"]))
    detect_fn = fns.get("detect_fn") or default_detect_fn(
        box_threshold=det_thr, text_threshold=float(th["det_text_threshold"]))
    seg_fn = fns.get("seg_fn") or default_seg_fn()
    flow_fn = fns.get("flow_fn") or default_flow_fn()
    vlm_fn = fns["vlm_fn"] if "vlm_fn" in fns else default_vlm_fn(db)

    rows = db.list_fixtures()
    if labels:
        rows = [r for r in rows if r["label"] in labels]
    if limit:
        rows = rows[:limit]

    records = []
    for fx in rows:
        fid, path, label = fx["fixture_id"], fx["path"], fx["label"]
        meta = terms_map.get(fid, {})
        terms = meta.get("terms") or []
        gate = g7_object_persistence(
            path, terms, th,
            embed_fn=embed_fn, detect_fn=detect_fn, seg_fn=seg_fn, flow_fn=flow_fn, vlm_fn=vlm_fn,
            frames_dir=os.path.join(frames_root, fid), n_samples=n_samples,
        )
        ts = db.add_g7_run(fid, "overall", gate["score"], gate["passed"] is False, False, {
            "label": label, "category": fx.get("category"), "terms": terms,
            "meta": gate["detail"]["meta"],
        })
        for sub_id in G7_SUBS:
            d = gate["detail"][sub_id]
            db.add_g7_run(fid, sub_id, d["score"], d["triggered"], d["skipped"], d)
        rec = {"fixture_id": fid, "label": label, "category": fx.get("category"),
               "source_key": meta.get("key"), "shot": meta.get("shot"), "terms": terms,
               "passed": gate["passed"], "score": gate["score"],
               "subs": {s: gate["detail"][s] for s in G7_SUBS}}
        records.append(rec)
        trig = [s for s in G7_SUBS if gate["detail"][s]["triggered"]]
        print(f"[G7] {fid} {label} passed={gate['passed']} score={gate['score']} "
              f"triggered={trig or '-'} skipped={[s for s in G7_SUBS if gate['detail'][s]['skipped']] or '-'}",
              flush=True)

    summary = {
        "thresholds": th,
        "n_fixtures": len(records),
        "n_g7_fail": sum(1 for r in records if not r["passed"]),
        "by_label": {},
        "records": records,
    }
    for lab in ("fail", "pass_structural", "pass_candidate"):
        grp = [r for r in records if r["label"] == lab]
        summary["by_label"][lab] = {
            "n": len(grp),
            "g7_fail": sum(1 for r in grp if not r["passed"]),
        }
    if out_json:
        op = Path(out_json)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


"""
D-056 备忘(落地于 DECISIONS.md): 采样密度 = 均匀 16 帧/条(帧距 ~0.33s, 规格 §3 允许 8-16);
跟踪 = vendored LiteByteTracker(稀疏帧距下省 Kalman, 高分孵化/min_hits=2 确认/max_age=2 复活,
贪心 IoU 关联不强依赖 lap); 光流对 = 相邻采样帧(非原始帧距), P95 阈值按此口径校准;
G7b/c 仅在"词表非空 + 检测器可用(+c 项首帧有框)"时激活, ken_burns 程序产物按无主体跳过。
"""
