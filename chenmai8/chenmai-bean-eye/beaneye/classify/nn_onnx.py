"""M5 分类 NN 头（批10 接入）· ONNX 单粒裁片分类器（``NnOnnxClassifier``）。

满足冻结 ``ClsModel`` Protocol（``beaneye.schemas``）::

    classify(crop_rgba, mask) -> (defect, conf, severity_rank)

与 :class:`beaneye.classify.rules.RulesV0` 同协议同输出 schema，装配侧
（``beaneye.app.components.build_components`` / ``create_app(classify=…)``）
可零改动换入。**缺省产品行为不变**：``beaneye.classify.build_default()``
仍返回 RulesV0；NN 头按需显式构造（实时侧开关见 ``beaneye.realtime``）。

部署状态（批13，2026-10-04）
    缺省 ``DEFAULT_TAU`` = **0.1**（批13 缺陷过采样×8 重训 ONNX 的 τ 扫描
    推荐工作点）；缺省 ONNX = ``train/runs/crop_cls/b13_winner.onnx``
    （demo 实时侧 ``--nn-onnx`` 缺省已指向）。胜者判定、探针三数与档案见
    ``train/runs/crop_cls/DEPLOYED.md``。以下批9/批10 记录为历史沿革，保留。

权重来源（批9 产物，不入库；``*.onnx`` 随 .gitignore 忽略）
    ``train/runs/crop_cls/b9.onnx``（44 MB，opset 17，静态输入
    ``1×3×224×224``，输出 13 维 logits，类别序 = taxonomy
    ``severity_order``，第 0 位 = normal）。批9 判定与阈值扫描结论
    （train/sweep_defect_threshold.py，扫描对象 = 批9 ONNX + 实拍探针
    398 粒）：

    - argmax 口径基线：坏堆 {broken,black,sour} 检出 38.2%（21/55）、
      normal 堆 normal 判对率 76.97%（264/343）；
    - 检出门 55% 与 normal 门 70% **在全体实测 τ 上不可同时满足**；
    - 推荐 τ=0.13（= 精确最优点 τ≈0.1377 同豆级计数）：检出 56.36%
      （31/55，过 55% 门），normal 判对率 66.47%（228/343，距 70% 门差
      3.53pt，低于探针验收线 80%）——以 −10.5pt normal 判对率换
      +18.2pt 检出，漏检代价高的应用前提下该交换成立；
    - 若限定 0.1 网格，最近点 τ=0.1（检出 58.18%、normal 62.68%）。

决策规则（τ 校准，与扫描口径逐位同源）
    对 13 维 logits 取 softmax 后：预测 = defect 当 **12 个缺陷类**
    （非 normal 类）的最大 softmax 概率 ≥ τ；否则 normal。判 defect 时
    类别 = 缺陷类上的 argmax（top-defect）。conf = 判定类别的 softmax
    概率（defect 时即该 max 缺陷概率；normal 时为 normal 类概率）。
    判定边界为 ``>=``（与扫描脚本 ``p_max_defect >= tau`` 一致）。

预处理（训练/扫描同口径）
    crop RGBA（RGB 通道序 + alpha=掩码，``beaneye.app.pipeline.
    extract_mask_crop_rgba`` 产物）→ alpha 白底合成（训练侧「掩码外置
    白底」先验；fillPoly 产生的二值 alpha 下与硬掩码逐位等价）→ INTER_AREA
    缩放 224² → /255 → ImageNet mean/std 归一化 → CHW float32。
    3 通道输入按「全幅=豆」处理（无 alpha 可合成时退化为整幅）。

依赖纪律
    onnxruntime **惰性导入**：模块本身零 NN 依赖，仅在实际构建会话时
    import（未安装 onnxruntime 时 RulesV0 主链路与本模块的导入/构造均
    不受影响）。会话可经 ``session=`` 注入（测试替身 / 复用已建会话）。

异常语义（对齐 RulesV0 纪律）
    - 空 crop / 非法维度 → ``(normal, 0.0, 0)``（逐粒退化，绝不阻塞管线）；
    - 模型结构性错误（文件缺失/非法、logits 宽度 ≠ 类别表宽度）→
      :class:`NnOnnxError`（配置错误要响，不能整盘静默判 normal）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from beaneye.schemas import BeanMask
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = ["NnOnnxClassifier", "NnOnnxError", "DEFAULT_TAU"]

# τ 缺省工作点（批13 部署工作点 = 批13 τ 扫描推荐值，判定与探针三数见
# train/runs/crop_cls/DEPLOYED.md；批10 时代缺省 0.13，批13 起替换）
DEFAULT_TAU = 0.1

# ImageNet 归一化常数（训练口径；train/crop_classifier.py 同值）
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_INPUT_SIZE = 224


class NnOnnxError(RuntimeError):
    """NN ONNX 分类头的结构性错误（文件缺失/非法、会话失败、宽度不符）。"""


def _softmax(z: np.ndarray) -> np.ndarray:
    """数值稳定 softmax（与批10 扫描脚本同式）。"""
    e = np.exp(z - z.max())
    return e / e.sum()


class NnOnnxClassifier:
    """ONNX 单粒分类头：RGBA crop + BeanMask → (defect, conf, rank)，τ 校准判决。"""

    stage = "classify"
    version = "nn_onnx:v1"

    def __init__(
        self,
        onnx_path: str | Path | None = None,
        *,
        tau: float = DEFAULT_TAU,
        classes: list[str] | None = None,
        taxonomy: Taxonomy | None = None,
        size: int = _INPUT_SIZE,
        providers: list[str] | None = None,
        session: object | None = None,
    ) -> None:
        """参数
        ----
        onnx_path:
            ONNX 模型路径（惰性加载：首次 ``classify`` 才读文件/建会话）。
        tau:
            缺陷判决阈值（缺省 0.1 = 批13 部署工作点，档案 DEPLOYED.md）。
        classes:
            输出类别表（须与训练类别序一致）；缺省取 taxonomy
            ``severity_order``（批9 训练类别表即此序，第 0 位 = normal）。
        taxonomy:
            严重度表；缺省 ``load_taxonomy()``。
        size:
            输入边长（缺省 224 = 交付件静态形状）。
        providers:
            onnxruntime execution providers（缺省 CPU）。
        session:
            预建推理会话（duck-type：``run(keys, feed)`` +
            ``get_inputs()``）；注入后 ``onnx_path`` 不再被使用，且不会
            触发 onnxruntime 导入（测试替身路径）。
        """
        if tau < 0.0 or tau > 1.0:
            raise ValueError(f"tau 必须在 [0,1]，得到 {tau}")
        if size <= 0:
            raise ValueError(f"size 必须为正，得到 {size}")
        self.onnx_path = Path(onnx_path) if onnx_path is not None else None
        self.tau = float(tau)
        self.tax = taxonomy if taxonomy is not None else load_taxonomy()
        self._classes = list(classes) if classes is not None else list(self.tax.severity_order)
        if self._classes.count("normal") != 1:
            raise NnOnnxError(
                f"类别表必须恰好含一个 'normal'（判决语义需要），得到 {self._classes}"
            )
        self._normal_idx = self._classes.index("normal")
        self._defect_idx = [i for i, c in enumerate(self._classes) if c != "normal"]
        self._size = int(size)
        self._providers = list(providers) if providers is not None else ["CPUExecutionProvider"]
        self._session = session

    # ------------------------------------------------------------------
    # ClsModel Protocol
    # ------------------------------------------------------------------

    def classify(self, crop_rgba: np.ndarray, mask: BeanMask) -> tuple[str, float, int]:
        """冻结协议入口：crop RGBA + BeanMask → (defect, conf, severity_rank)。"""
        out = self.classify_proba(crop_rgba, mask)
        return out["label"], out["conf"], out["rank"]

    # ------------------------------------------------------------------
    # 扩展入口（HUD/评测/调试用；协议调用方不依赖）
    # ------------------------------------------------------------------

    def classify_proba(self, crop_rgba: np.ndarray, mask: BeanMask) -> dict:
        """同 :meth:`classify`，另返回 softmax 概率与 τ 判决明细。

        返回 dict 字段：``label / conf / rank / tau / p_normal /
        p_max_defect / top_defect / probs（label → 概率）``。
        """
        tensor = self._preprocess(crop_rgba)
        if tensor is None:
            # 逐粒退化（对齐 RulesV0：空 crop → normal、conf 0，不阻塞管线）
            return {"label": "normal", "conf": 0.0, "rank": 0, "tau": self.tau,
                    "p_normal": None, "p_max_defect": None, "top_defect": None,
                    "probs": None}
        logits = self._forward(tensor)
        probs = _softmax(np.asarray(logits, dtype=np.float64))
        if probs.shape[-1] != len(self._classes):
            raise NnOnnxError(
                f"logits 宽度 {probs.shape[-1]} 与类别表宽度 {len(self._classes)} 不符"
                f"（classes={self._classes[:3]}…，模型/类别表不匹配？）"
            )
        sub = probs[self._defect_idx]
        k = int(np.argmax(sub))
        p_max_defect = float(sub[k])
        top_defect = self._classes[self._defect_idx[k]]
        if p_max_defect >= self.tau:
            return {"label": top_defect, "conf": p_max_defect,
                    "rank": int(self.tax.severity_rank(top_defect)),
                    "tau": self.tau, "p_normal": float(probs[self._normal_idx]),
                    "p_max_defect": p_max_defect, "top_defect": top_defect,
                    "probs": {c: float(p) for c, p in zip(self._classes, probs)}}
        return {"label": "normal", "conf": float(probs[self._normal_idx]), "rank": 0,
                "tau": self.tau, "p_normal": float(probs[self._normal_idx]),
                "p_max_defect": p_max_defect, "top_defect": top_defect,
                "probs": {c: float(p) for c, p in zip(self._classes, probs)}}

    # ------------------------------------------------------------------
    # 内部：预处理 / 会话 / 前向
    # ------------------------------------------------------------------

    def _preprocess(self, crop_rgba: np.ndarray) -> np.ndarray | None:
        """RGBA crop → (1,3,size,size) float32；空/非法输入返回 None（退化位）。"""
        import cv2

        arr = np.asarray(crop_rgba)
        if arr.ndim != 3 or arr.shape[2] not in (3, 4) or arr.shape[0] < 1 or arr.shape[1] < 1:
            return None
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        if arr.shape[2] == 4:
            rgb = arr[:, :, :3].astype(np.float32)
            alpha = arr[:, :, 3].astype(np.float32) / 255.0
            # alpha 白底合成（训练侧「掩码外置白底」先验；二值 alpha 下与
            # np.where(mask, crop, 255) 逐位等价）
            comp = rgb * alpha[..., None] + 255.0 * (1.0 - alpha[..., None])
            comp = np.clip(np.rint(comp), 0, 255).astype(np.uint8)
        else:
            comp = arr
        # crop_rgba 契约即 RGB 通道序（extract_mask_crop_rgba 已 BGR→RGB），
        # 无需再转；直接缩放后归一化。
        resized = cv2.resize(comp, (self._size, self._size), interpolation=cv2.INTER_AREA)
        x = resized.astype(np.float32) / 255.0
        x = (x - _IMAGENET_MEAN) / _IMAGENET_STD
        return x.transpose(2, 0, 1)[None].astype(np.float32)

    def _ensure_session(self):
        """惰性会话构建：注入优先；否则此处才 import onnxruntime。"""
        if self._session is not None:
            return self._session
        if self.onnx_path is None:
            raise NnOnnxError("未提供 onnx_path 或注入 session，无法构建推理会话")
        if not self.onnx_path.is_file():
            raise NnOnnxError(f"ONNX 文件不存在: {self.onnx_path}")
        try:
            import onnxruntime
        except ImportError as exc:
            raise NnOnnxError(
                "onnxruntime 未安装（NN 分类头需要；RulesV0 链路不受影响）——"
                "pip install onnxruntime"
            ) from exc
        try:
            self._session = onnxruntime.InferenceSession(
                str(self.onnx_path), providers=self._providers
            )
        except Exception as exc:
            raise NnOnnxError(f"ONNX 会话构建失败（{self.onnx_path}）: {exc}") from exc
        return self._session

    def _forward(self, tensor: np.ndarray) -> np.ndarray:
        sess = self._ensure_session()
        inp_name = sess.get_inputs()[0].name
        try:
            out = sess.run(None, {inp_name: tensor})[0][0]
        except NnOnnxError:
            raise
        except Exception as exc:
            raise NnOnnxError(f"ONNX 前向失败: {exc}") from exc
        return out
