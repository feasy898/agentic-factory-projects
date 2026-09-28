"""shot-cut 组件推理网络（镜头切分，本机 CPU 可跑）—— M5 内部实现件。

中性名 ``shot-cut`` 的架构实现（组件注册表与权重获取见 configs/models.yaml 与
内部台账 plan/oss-manifest.md 附录A；上游代码 MIT，公开版不写上游名）。

组成：
  1. :class:`ShotCutNet` —— 网络本体。模块属性名（SDDCNN/frame_sim_layer/
     color_hist_layer/fc1/cls_layer1/cls_layer2）与权重 state_dict 键严格对应，
     类名可中性化；输入 = uint8 帧 [B, T, 27, 48, 3]（RGB），输出单帧转场概率。
  2. :func:`predict_scene_frames` —— 官方推理口径：不足 100 帧倍数时末帧重复补齐，
     单前向出全片转场概率；超长视频按 1500 帧分块（块内同样 100 帧倍数口径）。

权重：``models/shot-cut/scdet-pytorch-weights.pth``（HF 镜像直下，不入公开仓）。
"""

from __future__ import annotations

import random
from pathlib import Path

import torch
import torch.nn.functional as functional

__all__ = ["ShotCutNet", "predict_scene_frames", "default_weights_path", "ScDetError"]


class ScDetError(RuntimeError):
    """shot-cut 组件执行错误（权重缺失/输入形状非法等）。"""


def default_weights_path() -> Path:
    """models/shot-cut/<默认权重>（仓库根的上一级 models/ 缓存目录）。"""
    root = Path(__file__).resolve().parents[1]
    return root.parent / "models" / "shot-cut" / "scdet-pytorch-weights.pth"


def load_scdet_net(weights: str | Path | None = None, device: str = "cpu") -> "ShotCutNet":
    """装载权重（strict=True，键/形状不匹配立即暴露）。"""
    path = Path(weights) if weights else default_weights_path()
    if not path.is_file():
        raise ScDetError(
            f"shot-cut 权重缺失: {path}（下载与放置目录见 configs/models.yaml shot-cut 条目）")
    net = ShotCutNet()
    state = torch.load(path, map_location="cpu", weights_only=False)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    net.load_state_dict(state, strict=True)
    return net.eval().to(device)


class ShotCutNet(torch.nn.Module):
    """镜头转场检测网络（单帧转场概率；类名中性化、属性名对齐权重键）。"""

    def __init__(self, F: int = 16, L: int = 3, S: int = 2, D: int = 1024,
                 use_many_hot_targets: bool = True, use_frame_similarity: bool = True,
                 use_color_histograms: bool = True, use_mean_pooling: bool = False,
                 dropout_rate: float = 0.5):
        super().__init__()
        self.SDDCNN = torch.nn.ModuleList(
            [_StackedDDCNN(in_filters=3, n_blocks=S, filters=F, stochastic_depth_drop_prob=0.0)]
            + [_StackedDDCNN(in_filters=(F * 2 ** (i - 1)) * 4, n_blocks=S, filters=F * 2 ** i)
               for i in range(1, L)])
        self.frame_sim_layer = _FrameSimilarity(
            sum([(F * 2 ** i) * 4 for i in range(L)]), lookup_window=101,
            output_dim=128, similarity_dim=128, use_bias=True) if use_frame_similarity else None
        self.color_hist_layer = _ColorHistograms(
            lookup_window=101, output_dim=128) if use_color_histograms else None
        self.dropout = torch.nn.Dropout(dropout_rate) if dropout_rate is not None else None

        output_dim = ((F * 2 ** (L - 1)) * 4) * 3 * 6  # 3x6 空间维度
        if use_frame_similarity:
            output_dim += 128
        if use_color_histograms:
            output_dim += 128
        self.fc1 = torch.nn.Linear(output_dim, D)
        self.cls_layer1 = torch.nn.Linear(D, 1)
        self.cls_layer2 = torch.nn.Linear(D, 1) if use_many_hot_targets else None
        self.use_mean_pooling = use_mean_pooling
        self.eval()

    def forward(self, inputs: torch.Tensor):
        assert (isinstance(inputs, torch.Tensor)
                and list(inputs.shape[2:]) == [27, 48, 3]
                and inputs.dtype == torch.uint8), "输入须为 uint8 [B, T, 27, 48, 3]"
        x = inputs.permute([0, 4, 1, 2, 3]).float().div_(255.0)

        block_features: list[torch.Tensor] = []
        for block in self.SDDCNN:
            x = block(x)
            block_features.append(x)

        if self.use_mean_pooling:
            x = torch.mean(x, dim=[3, 4])
            x = x.permute(0, 2, 1)
        else:
            x = x.permute(0, 2, 3, 4, 1)
            x = x.reshape(x.shape[0], x.shape[1], -1)

        if self.frame_sim_layer is not None:
            x = torch.cat([self.frame_sim_layer(block_features), x], 2)
        if self.color_hist_layer is not None:
            x = torch.cat([self.color_hist_layer(inputs), x], 2)

        x = self.fc1(x)
        x = functional.relu(x)
        if self.dropout is not None:
            x = self.dropout(x)

        one_hot = self.cls_layer1(x)
        if self.cls_layer2 is not None:
            return one_hot, {"many_hot": self.cls_layer2(x)}
        return one_hot


class _StackedDDCNN(torch.nn.Module):
    def __init__(self, in_filters: int, n_blocks: int, filters: int, shortcut: bool = True,
                 pool_type: str = "avg", stochastic_depth_drop_prob: float = 0.0):
        super().__init__()
        assert pool_type in ("max", "avg")
        self.shortcut = shortcut
        self.DDCNN = torch.nn.ModuleList([
            _DilatedDCNN(in_filters if i == 1 else filters * 4, filters,
                         activation=functional.relu if i != n_blocks else None)
            for i in range(1, n_blocks + 1)])
        self.pool = (torch.nn.MaxPool3d(kernel_size=(1, 2, 2)) if pool_type == "max"
                     else torch.nn.AvgPool3d(kernel_size=(1, 2, 2)))
        self.stochastic_depth_drop_prob = stochastic_depth_drop_prob

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        x = inputs
        shortcut = None
        for block in self.DDCNN:
            x = block(x)
            if shortcut is None:
                shortcut = x
        x = functional.relu(x)
        if self.shortcut is not None:
            if self.stochastic_depth_drop_prob != 0.0 and self.training:
                x = shortcut if random.random() < self.stochastic_depth_drop_prob \
                    else x + shortcut
            else:
                x = x + shortcut
        return self.pool(x)


class _DilatedDCNN(torch.nn.Module):
    def __init__(self, in_filters: int, filters: int, batch_norm: bool = True,
                 activation=None):
        super().__init__()
        self.Conv3D_1 = _Conv3D(in_filters, filters, 1, use_bias=not batch_norm)
        self.Conv3D_2 = _Conv3D(in_filters, filters, 2, use_bias=not batch_norm)
        self.Conv3D_4 = _Conv3D(in_filters, filters, 4, use_bias=not batch_norm)
        self.Conv3D_8 = _Conv3D(in_filters, filters, 8, use_bias=not batch_norm)
        self.bn = torch.nn.BatchNorm3d(filters * 4, eps=1e-3) if batch_norm else None
        self.activation = activation

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        x = torch.cat([self.Conv3D_1(inputs), self.Conv3D_2(inputs),
                       self.Conv3D_4(inputs), self.Conv3D_8(inputs)], dim=1)
        if self.bn is not None:
            x = self.bn(x)
        if self.activation is not None:
            x = self.activation(x)
        return x


class _Conv3D(torch.nn.Module):
    """(2+1)D 分解卷积：空间 3x3 + 时间 1x1x1（按空洞率）。"""

    def __init__(self, in_filters: int, filters: int, dilation_rate: int,
                 separable: bool = True, use_bias: bool = True):
        super().__init__()
        if separable:
            conv1 = torch.nn.Conv3d(in_filters, 2 * filters, kernel_size=(1, 3, 3),
                                    dilation=(1, 1, 1), padding=(0, 1, 1), bias=False)
            conv2 = torch.nn.Conv3d(2 * filters, filters, kernel_size=(3, 1, 1),
                                    dilation=(dilation_rate, 1, 1),
                                    padding=(dilation_rate, 0, 0), bias=use_bias)
            self.layers = torch.nn.ModuleList([conv1, conv2])
        else:
            conv = torch.nn.Conv3d(in_filters, filters, kernel_size=3,
                                   dilation=(dilation_rate, 1, 1),
                                   padding=(dilation_rate, 1, 1), bias=use_bias)
            self.layers = torch.nn.ModuleList([conv])

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        x = inputs
        for layer in self.layers:
            x = layer(x)
        return x


class _FrameSimilarity(torch.nn.Module):
    def __init__(self, in_filters: int, similarity_dim: int = 128, lookup_window: int = 101,
                 output_dim: int = 128, use_bias: bool = False):
        super().__init__()
        self.projection = torch.nn.Linear(in_filters, similarity_dim, bias=use_bias)
        self.fc = torch.nn.Linear(lookup_window, output_dim)
        self.lookup_window = lookup_window
        assert lookup_window % 2 == 1

    def forward(self, inputs: list[torch.Tensor]) -> torch.Tensor:
        x = torch.cat([torch.mean(x, dim=[3, 4]) for x in inputs], dim=1)
        x = torch.transpose(x, 1, 2)
        x = self.projection(x)
        x = functional.normalize(x, p=2, dim=2)

        batch_size, time_window = x.shape[0], x.shape[1]
        similarities = torch.bmm(x, x.transpose(1, 2))
        similarities_padded = functional.pad(
            similarities, [(self.lookup_window - 1) // 2, (self.lookup_window - 1) // 2])
        batch_indices = torch.arange(0, batch_size, device=x.device).view(
            [batch_size, 1, 1]).repeat([1, time_window, self.lookup_window])
        time_indices = torch.arange(0, time_window, device=x.device).view(
            [1, time_window, 1]).repeat([batch_size, 1, self.lookup_window])
        lookup_indices = (torch.arange(0, self.lookup_window, device=x.device).view(
            [1, 1, self.lookup_window]).repeat([batch_size, time_window, 1]) + time_indices)
        similarities = similarities_padded[batch_indices, time_indices, lookup_indices]
        return functional.relu(self.fc(similarities))


class _ColorHistograms(torch.nn.Module):
    def __init__(self, lookup_window: int = 101, output_dim: int | None = 128):
        super().__init__()
        self.fc = (torch.nn.Linear(lookup_window, output_dim)
                   if output_dim is not None else None)
        self.lookup_window = lookup_window
        assert lookup_window % 2 == 1

    @staticmethod
    def compute_color_histograms(frames: torch.Tensor) -> torch.Tensor:
        frames = frames.int()

        def get_bin(f: torch.Tensor) -> torch.Tensor:  # 0..511
            R, G, B = f[:, :, 0], f[:, :, 1], f[:, :, 2]
            return ((R >> 5) << 6) + ((G >> 5) << 3) + (B >> 5)

        batch_size, time_window, height, width, no_channels = frames.shape
        assert no_channels == 3
        frames_flatten = frames.view(batch_size * time_window, height * width, 3)
        binned_values = get_bin(frames_flatten)
        frame_bin_prefix = (torch.arange(
            0, batch_size * time_window, device=frames.device) << 9).view(-1, 1)
        binned_values = (binned_values + frame_bin_prefix).view(-1)
        histograms = torch.zeros(
            batch_size * time_window * 512, dtype=torch.int32, device=frames.device)
        histograms.scatter_add_(
            0, binned_values,
            torch.ones(len(binned_values), dtype=torch.int32, device=frames.device))
        histograms = histograms.view(batch_size, time_window, 512).float()
        return functional.normalize(histograms, p=2, dim=2)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        x = self.compute_color_histograms(inputs)
        batch_size, time_window = x.shape[0], x.shape[1]
        similarities = torch.bmm(x, x.transpose(1, 2))
        similarities_padded = functional.pad(
            similarities, [(self.lookup_window - 1) // 2, (self.lookup_window - 1) // 2])
        batch_indices = torch.arange(0, batch_size, device=x.device).view(
            [batch_size, 1, 1]).repeat([1, time_window, self.lookup_window])
        time_indices = torch.arange(0, time_window, device=x.device).view(
            [1, time_window, 1]).repeat([batch_size, 1, self.lookup_window])
        lookup_indices = (torch.arange(0, self.lookup_window, device=x.device).view(
            [1, 1, self.lookup_window]).repeat([batch_size, time_window, 1]) + time_indices)
        similarities = similarities_padded[batch_indices, time_indices, lookup_indices]
        if self.fc is not None:
            return functional.relu(self.fc(similarities))
        return similarities


# ---------------------------------------------------------------------------
# 官方推理口径：补齐 100 帧倍数 → 单前向全片转场概率
# ---------------------------------------------------------------------------

#: 单次前向的最大帧数（显存/内存护栏；超长视频分块，块间由调用方拼接概率）
MAX_FORWARD_FRAMES = 1500


@torch.no_grad()
def predict_scene_frames(net: ShotCutNet, frames: torch.Tensor, *,
                         device: str = "cpu") -> torch.Tensor:
    """uint8 帧 [T, 27, 48, 3] → 单帧转场概率 [T]（float32, sigmoid 后）。

    官方口径：T 不足 100 的倍数时以末帧重复补齐，前向后丢弃补齐帧的概率；
    超 :data:`MAX_FORWARD_FRAMES` 时按块处理（块内同口径），概率顺序拼接。
    """
    if frames.dim() != 4 or tuple(frames.shape[1:]) != (27, 48, 3):
        raise ScDetError(f"期望帧 [T, 27, 48, 3]，得到 {tuple(frames.shape)}")
    total = frames.shape[0]
    out = torch.zeros(total, dtype=torch.float32)
    for start in range(0, total, MAX_FORWARD_FRAMES):
        chunk = frames[start:start + MAX_FORWARD_FRAMES]
        remainder = chunk.shape[0] % 100
        if remainder:
            pad = chunk[-1:].expand(100 - remainder, -1, -1, -1)
            chunk = torch.cat([chunk, pad], dim=0)
        pred = net(chunk.unsqueeze(0).to(device))[0]  # [1, T, 1]（单帧转场 logit）
        probs = torch.sigmoid(pred[0, :, 0])
        n_orig = min(chunk.shape[0], start + MAX_FORWARD_FRAMES
                     if start + MAX_FORWARD_FRAMES <= total else total) - start
        out[start:start + n_orig] = probs[:n_orig].float().cpu()
    return out
