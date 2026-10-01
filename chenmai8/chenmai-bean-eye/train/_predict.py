"""train/ NN 推理器封装（私有模块：checkpoint / ONNX 两条真实模式推理路线）。

**仅真实模式导入**（GPU 机依赖：NN 训练栈见 requirements-oss.txt；本机
windev 未装、未能离线核对 API——上 GPU 机先跑 ``det_finetune.py --cpu-smoke``
做连通冒烟，见 train/README.md「API 核对」节）。

- :class:`CheckpointPredictor` —— NN 包 seg 模型加载 checkpoint 推理
  （主路线；返回 supervision 风格 detections，此处转 :class:`_metrics.Instance`）；
- :class:`OnnxPredictor` —— onnxruntime 推理（部署形态；输出签名自检，
  无掩码输出时明确报错并指引 checkpoint 路线）。onnxruntime **不在**
  requirements-oss.txt 的钉版清单内（该文件只列 NN 栈闭包，实测 2026-09-28
  安装未含它）——GPU 机按需 ``pip install onnxruntime``；缺失时抛
  :class:`RuntimeError`（带安装指引），由各脚本 main() 转成可读 [FAIL]。

类别 id 口径：模型/ONNX 的 class_id + ``class_id_offset`` = COCO category_id
（训练框架可能把 1..13 的类别 id 压成 0..12；offset 由 eval 脚本参数控制，
默认 0，冒烟时按 README 核对）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

import _common
from _metrics import Instance, detections_to_instances

# ImageNet 归一化（NN 包默认预处理口径；与导出/量化保持一致）
_MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)


class CheckpointPredictor:
    """NN 包 seg 模型 + checkpoint 推理（主评测路线）。"""

    def __init__(
        self,
        checkpoint: str | Path,
        *,
        device: str = "cuda:0",
        resolution: int | None = None,
        variant: str = "small",
        score_thr: float = 0.5,
    ) -> None:
        nn_pkg, _torch = _common.import_nn_stack()
        cls = _common.nn_model_class(nn_pkg, variant)
        kwargs: dict = {"device": device}
        if resolution is not None:
            kwargs["resolution"] = int(resolution)
        if checkpoint:
            kwargs["pretrain_weights"] = str(checkpoint)
        try:
            self.model = cls(**kwargs)
        except TypeError:
            # 钉版构造器签名差异回退：只传 device（分辨率走该版本默认值），
            # 回退发生时打印告警（README「API 核对」节说明的防御路径）。
            print(f"[警告] NN 包构造器不接受 resolution/pretrain_weights 参数，回退最小构造")
            self.model = cls(device=device)
        self.score_thr = float(score_thr)

    def predict(self, bgr: np.ndarray) -> list[Instance]:
        """BGR 整盘图 → Instance 列表（空检测返回 []）。"""
        det = self.model.predict(bgr[:, :, ::-1], threshold=self.score_thr)
        if det is None or len(det) == 0:
            return []
        masks = getattr(det, "mask", None)
        if masks is None:
            raise RuntimeError(
                "模型未返回掩码（确认使用 seg 系型号/权重；见 train/README.md API 核对节）"
            )
        return detections_to_instances(
            det.class_id, det.confidence, np.asarray(masks, dtype=bool)
        )


class OnnxPredictor:
    """onnxruntime 推理（部署形态；输出签名自检 + 掩码解码）。"""

    def __init__(
        self,
        onnx_path: str | Path,
        *,
        score_thr: float = 0.5,
        providers: list[str] | None = None,
        class_id_offset: int = 0,
    ) -> None:
        try:
            import onnxruntime  # GPU 机按需安装；不在 requirements-oss.txt 钉版内
        except ImportError as exc:  # 转可读错误（main() 只捕 RuntimeError 等）
            raise RuntimeError(
                "onnxruntime 未安装（ONNX 评测路线需要；GPU 机执行 "
                "pip install onnxruntime，或改用 --checkpoint 路线）"
            ) from exc

        self.session = onnxruntime.InferenceSession(
            str(onnx_path),
            providers=providers or ["CPUExecutionProvider"],
        )
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = [d if isinstance(d, int) else None for d in inp.shape]
        self.static_hw = (shape[-2], shape[-1]) if shape[-2] and shape[-1] else None
        self.score_thr = float(score_thr)
        self.class_id_offset = int(class_id_offset)
        self._output_roles()

    def _output_roles(self) -> None:
        """按名字/形状识别输出张量角色（boxes/scores/labels/masks）。"""
        self.out_names = [o.name for o in self.session.get_outputs()]
        infos = [(o.name, o.shape) for o in self.session.get_outputs()]
        roles: dict[str, str] = {}
        for name, shape in infos:
            n = name.lower()
            if "mask" in n:
                roles[name] = "masks"
            elif "score" in n or "conf" in n:
                roles[name] = "scores"
            elif "label" in n or "class" in n:
                roles[name] = "labels"
            elif "box" in n or "det" in n:
                roles[name] = "boxes"
        if len(roles) < 3:  # 形状兜底：1D=分数/标签，2D=框，3D=掩码
            for name, shape in infos:
                if name in roles:
                    continue
                dims = [d for d in shape if isinstance(d, int) and d > 0]
                if len(dims) >= 3:
                    roles[name] = "masks"
                elif len(dims) == 1:
                    roles[name] = "scores" if "scores" not in roles.values() else "labels"
                elif len(dims) == 2:
                    roles[name] = "boxes"
        self.roles = roles
        if "masks" not in roles.values():
            raise RuntimeError(
                f"ONNX 输出不含掩码头（outputs={infos}）；请用 checkpoint 路线评测，"
                "或用 export_onnx_quant.py 从 seg 模型重导出（含掩码）"
            )
        if "scores" not in roles.values() or "labels" not in roles.values():
            raise RuntimeError(
                f"ONNX 输出无法识别 scores/labels（outputs={infos}）；"
                "请核对导出版本与 train/README.md API 核对节"
            )

    def _preprocess(self, bgr: np.ndarray) -> np.ndarray:
        img = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        if self.static_hw is not None:
            img = cv2.resize(img, (self.static_hw[1], self.static_hw[0]),
                             interpolation=cv2.INTER_LINEAR)
        img = (img - _MEAN) / _STD
        return img.transpose(2, 0, 1)[None].astype(np.float32)

    def predict(self, bgr: np.ndarray) -> list[Instance]:
        feed = {self.input_name: self._preprocess(bgr)}
        raw = self.session.run(None, feed)
        by_role = {
            role: raw[self.out_names.index(name)]
            for name, role in self.roles.items()
        }
        scores = np.asarray(by_role["scores"]).reshape(-1)
        labels = np.asarray(by_role["labels"]).reshape(-1)
        masks = np.asarray(by_role["masks"])
        if masks.ndim == 4:  # N×1×H×W → N×H×W
            masks = masks[:, 0]
        keep = scores >= self.score_thr
        scores, labels, masks = scores[keep], labels[keep], masks[keep]
        # 掩码阈值化（sigmoid 概率图 → 二值）+ 贴回原图分辨率
        n, mh, mw = masks.shape
        h, w = bgr.shape[:2]
        inst: list[list[np.ndarray]] = [[], [], []]
        out_scores: list[float] = []
        out_labels: list[int] = []
        for i in range(n):
            m = masks[i].astype(np.float32)
            if (mh, mw) != (h, w):
                m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
            inst[0].append(m > 0.5)
            inst[1].append(float(scores[i]))
            inst[2].append(int(labels[i]) + self.class_id_offset)
        if not inst[0]:
            return []
        return detections_to_instances(
            np.asarray(inst[2]), np.asarray(inst[1]), np.asarray(inst[0])
        )
