"""voxdia 组件推理网络（说话人嵌入提取，本机 CPU 可跑）—— M5 内部实现件。

中性名 ``voxdia`` 的架构实现（组件注册表与权重获取见 configs/models.yaml 与
内部台账 plan/oss-manifest.md 附录A；上游代码 Apache-2.0，公开版不写上游名）。

组成：
  1. :func:`kaldi_fbank` —— 与 torchaudio.compliance.kaldi.fbank 默认参数逐项
     对齐的纯 torch 实现（80 mel / 25ms 窗 / 10ms 移 / povey 窗 / 去直流 /
     0.97 预加重 / snip_edges / log-floor）。仓库 torch 钉 2.14 而 torchaudio
     官方轮子止于 2.11，故手写；数值一致性在 T7 实测对拍（GPU 机 torchaudio
     2.5.1 参照实现，见 tests/test_m5.py::test_voxdia_fbank_parity，离线时 skip）。
  2. :class:`VoxDiaNet` —— 嵌入网络。模块属性名（head/xvector/tdnn/block1..3/
     transit1..3/out_nonlinear/stats/dense）与权重 state_dict 键严格对应，
     类名可中性化；本仓权重 ``models/voxdia/campplus_cn_common.bin``
     （ModelScope 直下，Apache-2.0；192 维嵌入，16k 音频）。
  3. :class:`SpeakerEmbedder` —— 装载权重 + 特征(CMN) + L2 归一化的一站式封装。

时间口径：嵌入只吃 wav 切片，与全片时间轴零耦合（切片起止由调用方负责，
绝对时间语义见 contracts 冻结规则 7）。
"""

from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path

import torch
import torch.nn.functional as F

__all__ = [
    "VoxDiaNet",
    "SpeakerEmbedder",
    "kaldi_fbank",
    "default_weights_path",
    "VoxDiaError",
]

#: 默认权重路径（configs/models.yaml voxdia.weights 同源；models/ 不入公开仓）
_DEFAULT_WEIGHT_NAME = "campplus_cn_common.bin"


class VoxDiaError(RuntimeError):
    """voxdia 组件执行错误（权重缺失/音频过短等）。"""


def default_weights_path() -> Path:
    """models/voxdia/<默认权重>（仓库根的上一级 models/ 缓存目录）。"""
    root = Path(__file__).resolve().parents[1]
    return root.parent / "models" / "voxdia" / _DEFAULT_WEIGHT_NAME


# ---------------------------------------------------------------------------
# Kaldi 风格 FBank（torchaudio.compliance.kaldi.fbank 默认参数的纯 torch 复刻）
# ---------------------------------------------------------------------------

_POW2_FLOOR = 512  # 25ms@16k=400 → 补零到 512 点 FFT


def _mel(f: torch.Tensor) -> torch.Tensor:
    return 1127.0 * torch.log(torch.clamp(1.0 + f / 700.0, min=1e-10))


def _get_mel_banks(num_bins: int, window_length_padded: int, sample_freq: float,
                   low_freq: float, high_freq: float) -> torch.Tensor:
    """Kaldi mel 滤波器组 [num_bins, num_fft_bins]（线性插值三角组，无 VTLEN 换折）。

    与 torchaudio.compliance.kaldi._get_mel_banks 默认参数一致：
    vtln_warp=1.0（不换折，vtln_low/high 不参与）。
    """
    num_fft_bins = window_length_padded // 2 + 1  # rfft 单边谱 0..N/2（含 Nyquist）
    fft_bin_width = sample_freq / window_length_padded
    nyquist = 0.5 * sample_freq
    high_freq = nyquist if high_freq <= 0.0 else high_freq
    mel_low = float(_mel(torch.tensor(low_freq)))
    mel_high = float(_mel(torch.tensor(high_freq)))
    # 每个三角组 left/center/right 在 mel 轴上等距
    mel_freq_delta = (mel_high - mel_low) / (num_bins + 1)
    bin_freqs = fft_bin_width * torch.arange(num_fft_bins, dtype=torch.float64)
    bin_mels = _mel(bin_freqs)  # [num_fft_bins]
    banks = torch.zeros(num_bins, num_fft_bins, dtype=torch.float64)
    for b in range(num_bins):
        left = mel_low + b * mel_freq_delta
        center = mel_low + (b + 1) * mel_freq_delta
        right = mel_low + (b + 2) * mel_freq_delta
        up = (bin_mels > left) & (bin_mels <= center)
        down = (bin_mels > center) & (bin_mels < right)
        banks[b, up] = (bin_mels[up] - left) / (center - left)
        banks[b, down] = (right - bin_mels[down]) / (right - center)
    return banks


def kaldi_fbank(wav: torch.Tensor, *, sample_rate: int = 16000,
                num_mel_bins: int = 80, frame_length_ms: float = 25.0,
                frame_shift_ms: float = 10.0, preemphasis: float = 0.97) -> torch.Tensor:
    """16k 单声道波形 [N] → log-mel fbank [T, 80]（torchaudio kaldi 默认口径）。

    对齐项（torchaudio.compliance.kaldi.fbank 默认值）：dither=0、
    remove_dc_offset=True、raw_power（不除窗长）、use_log_fbank=True、
    energy_floor 不启用（use_energy=False）、povey 窗、snip_edges=True、
    low_freq=20、high_freq=0(→nyquist)。
    """
    if wav.dim() != 1:
        raise VoxDiaError(f"kaldi_fbank 期望 1 维波形，得到 shape={tuple(wav.shape)}")
    wav = wav.to(torch.float64)
    window_size = int(sample_rate * frame_length_ms / 1000.0)
    window_shift = int(sample_rate * frame_shift_ms / 1000.0)
    if wav.numel() < window_size:
        # torchaudio 口径：不足一窗时补零出单帧（保持最短音频可嵌入）
        pad = window_size - wav.numel()
        wav = F.pad(wav, (0, pad))
    num_frames = 1 + (wav.numel() - window_size) // window_shift
    frames = wav.unfold(0, window_size, window_shift)[:num_frames].clone()  # [T, 400]

    # 去直流 → 预加重（首样点保持）→ povey 窗
    frames -= frames.mean(dim=1, keepdim=True)
    frames[:, 1:] -= preemphasis * frames[:, :-1]
    n = torch.arange(window_size, dtype=torch.float64)
    povey = torch.pow(0.5 - 0.5 * torch.cos(2.0 * math.pi * n / (window_size - 1)), 0.85)
    frames *= povey

    padded = _POW2_FLOOR
    spec = torch.fft.rfft(frames, n=padded)  # [T, 257]
    power = spec.real**2 + spec.imag**2  # kaldi raw power（不归一）

    banks = _get_mel_banks(num_mel_bins, padded, float(sample_rate), 20.0, 0.0)
    mel_energy = power @ banks.T  # [T, 80]
    eps = torch.finfo(torch.float32).eps  # torchaudio 同款 floor
    return torch.log(torch.clamp(mel_energy, min=eps)).to(torch.float32)


# ---------------------------------------------------------------------------
# 嵌入网络（类名中性化；模块属性名与权重键严格对应）
# ---------------------------------------------------------------------------

def _get_nonlinear(config_str: str, channels: int) -> torch.nn.Sequential:
    nonlinear: torch.nn.Sequential = torch.nn.Sequential()
    for name in config_str.split("-"):
        if name == "relu":
            nonlinear.add_module("relu", torch.nn.ReLU(inplace=True))
        elif name == "prelu":
            nonlinear.add_module("prelu", torch.nn.PReLU(channels))
        elif name == "batchnorm":
            nonlinear.add_module("batchnorm", torch.nn.BatchNorm1d(channels))
        elif name == "batchnorm_":
            nonlinear.add_module("batchnorm", torch.nn.BatchNorm1d(channels, affine=False))
        else:
            raise ValueError(f"未登记的非线性配置: {name!r}")
    return nonlinear


class _FbankCompressor(torch.nn.Module):
    """频域卷积前端（属性名 conv1/bn1/layer1/layer2/conv2/bn2 与权重键对应）。"""

    def __init__(self, m_channels: int = 32, feat_dim: int = 80):
        super().__init__()
        self.in_planes = m_channels
        self.conv1 = torch.nn.Conv2d(1, m_channels, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn1 = torch.nn.BatchNorm2d(m_channels)
        self.layer1 = self._make_layer(m_channels, 2, stride=2)
        self.layer2 = self._make_layer(m_channels, 2, stride=2)
        self.conv2 = torch.nn.Conv2d(m_channels, m_channels, kernel_size=3,
                                     stride=(2, 1), padding=1, bias=False)
        self.bn2 = torch.nn.BatchNorm2d(m_channels)
        self.out_channels = m_channels * (feat_dim // 8)

    def _make_layer(self, planes: int, num_blocks: int, stride: int) -> torch.nn.Sequential:
        layers: list[torch.nn.Module] = []
        for s in (stride, *(1,) * (num_blocks - 1)):
            layers.append(_BasicResBlock(self.in_planes, planes, s))
            self.in_planes = planes
        return torch.nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # [B, F, T] → [B, C*F', T']
        x = x.unsqueeze(1)
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.layer1(out)
        out = self.layer2(out)
        out = F.relu(self.bn2(self.conv2(out)))
        shape = out.shape
        return out.reshape(shape[0], shape[1] * shape[2], shape[3])


class _BasicResBlock(torch.nn.Module):
    expansion = 1

    def __init__(self, in_planes: int, planes: int, stride: int = 1):
        super().__init__()
        self.conv1 = torch.nn.Conv2d(in_planes, planes, kernel_size=3,
                                     stride=(stride, 1), padding=1, bias=False)
        self.bn1 = torch.nn.BatchNorm2d(planes)
        self.conv2 = torch.nn.Conv2d(planes, planes, kernel_size=3, stride=1,
                                     padding=1, bias=False)
        self.bn2 = torch.nn.BatchNorm2d(planes)
        self.shortcut: torch.nn.Sequential = torch.nn.Sequential()
        if stride != 1 or in_planes != self.expansion * planes:
            self.shortcut = torch.nn.Sequential(
                torch.nn.Conv2d(in_planes, self.expansion * planes, kernel_size=1,
                                stride=(stride, 1), bias=False),
                torch.nn.BatchNorm2d(self.expansion * planes),
            )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        out = out + self.shortcut(x)
        return F.relu(out)


class _TdnnLayer(torch.nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, stride: int = 1,
                 padding: int = 0, dilation: int = 1, bias: bool = False,
                 config_str: str = "batchnorm-relu"):
        super().__init__()
        if padding < 0:
            assert kernel_size % 2 == 1
            padding = (kernel_size - 1) // 2 * dilation
        self.linear = torch.nn.Conv1d(in_channels, out_channels, kernel_size,
                                      stride=stride, padding=padding,
                                      dilation=dilation, bias=bias)
        self.nonlinear = _get_nonlinear(config_str, out_channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.nonlinear(self.linear(x))


class _CamLayer(torch.nn.Module):
    def __init__(self, bn_channels: int, out_channels: int, kernel_size: int,
                 stride: int, padding: int, dilation: int, bias: bool, reduction: int = 2):
        super().__init__()
        self.linear_local = torch.nn.Conv1d(bn_channels, out_channels, kernel_size,
                                            stride=stride, padding=padding,
                                            dilation=dilation, bias=bias)
        self.linear1 = torch.nn.Conv1d(bn_channels, bn_channels // reduction, 1)
        self.relu = torch.nn.ReLU(inplace=True)
        self.linear2 = torch.nn.Conv1d(bn_channels // reduction, out_channels, 1)
        self.sigmoid = torch.nn.Sigmoid()

    def _seg_pooling(self, x: torch.Tensor, seg_len: int = 100) -> torch.Tensor:
        seg = F.avg_pool1d(x, kernel_size=seg_len, stride=seg_len, ceil_mode=True)
        shape = seg.shape
        seg = seg.unsqueeze(-1).expand(*shape, seg_len).reshape(*shape[:-1], -1)
        return seg[..., : x.shape[-1]]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.linear_local(x)
        context = x.mean(-1, keepdim=True) + self._seg_pooling(x)
        m = self.sigmoid(self.linear2(self.relu(self.linear1(context))))
        return y * m


class _CamDenseTdnnLayer(torch.nn.Module):
    def __init__(self, in_channels: int, out_channels: int, bn_channels: int,
                 kernel_size: int, stride: int = 1, dilation: int = 1, bias: bool = False,
                 config_str: str = "batchnorm-relu", memory_efficient: bool = False):
        super().__init__()
        assert kernel_size % 2 == 1
        padding = (kernel_size - 1) // 2 * dilation
        self.memory_efficient = memory_efficient
        self.nonlinear1 = _get_nonlinear(config_str, in_channels)
        self.linear1 = torch.nn.Conv1d(in_channels, bn_channels, 1, bias=False)
        self.nonlinear2 = _get_nonlinear(config_str, bn_channels)
        self.cam_layer = _CamLayer(bn_channels, out_channels, kernel_size,
                                   stride=stride, padding=padding, dilation=dilation, bias=bias)

    def _bn_function(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear1(self.nonlinear1(x))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self._bn_function(x)  # 推理期不做 checkpoint（memory_efficient 仅训练态生效）
        return self.cam_layer(self.nonlinear2(x))


class _CamDenseTdnnBlock(torch.nn.ModuleList):
    def __init__(self, num_layers: int, in_channels: int, out_channels: int,
                 bn_channels: int, kernel_size: int, stride: int = 1, dilation: int = 1,
                 bias: bool = False, config_str: str = "batchnorm-relu",
                 memory_efficient: bool = False):
        super().__init__()
        for i in range(num_layers):
            self.add_module(f"tdnnd{i + 1}", _CamDenseTdnnLayer(
                in_channels=in_channels + i * out_channels, out_channels=out_channels,
                bn_channels=bn_channels, kernel_size=kernel_size, stride=stride,
                dilation=dilation, bias=bias, config_str=config_str,
                memory_efficient=memory_efficient))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for layer in self:
            x = torch.cat([x, layer(x)], dim=1)
        return x


class _TransitLayer(torch.nn.Module):
    def __init__(self, in_channels: int, out_channels: int, bias: bool = True,
                 config_str: str = "batchnorm-relu"):
        super().__init__()
        self.nonlinear = _get_nonlinear(config_str, in_channels)
        self.linear = torch.nn.Conv1d(in_channels, out_channels, 1, bias=bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear(self.nonlinear(x))


class _DenseLayer(torch.nn.Module):
    def __init__(self, in_channels: int, out_channels: int, bias: bool = False,
                 config_str: str = "batchnorm-relu"):
        super().__init__()
        self.linear = torch.nn.Conv1d(in_channels, out_channels, 1, bias=bias)
        self.nonlinear = _get_nonlinear(config_str, out_channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if len(x.shape) == 2:
            x = self.linear(x.unsqueeze(dim=-1)).squeeze(dim=-1)
        else:
            x = self.linear(x)
        return self.nonlinear(x)


def _statistics_pooling(x: torch.Tensor) -> torch.Tensor:
    mean = x.mean(dim=-1)
    std = x.std(dim=-1, unbiased=True)
    return torch.cat([mean, std], dim=-1)


class VoxDiaNet(torch.nn.Module):
    """说话人嵌入网络（段级输出；属性名与权重 state_dict 键严格对应）。"""

    def __init__(self, feat_dim: int = 80, embedding_size: int = 192,
                 growth_rate: int = 32, bn_size: int = 4, init_channels: int = 128,
                 config_str: str = "batchnorm-relu", memory_efficient: bool = True,
                 output_level: str = "segment"):
        super().__init__()
        self.head = _FbankCompressor(m_channels=32, feat_dim=feat_dim)
        self.output_level = output_level
        channels = self.head.out_channels
        self.xvector = torch.nn.Sequential(OrderedDict([
            ("tdnn", _TdnnLayer(channels, init_channels, 5, stride=2, dilation=1,
                                padding=-1, config_str=config_str)),
        ]))
        channels = init_channels
        for i, (num_layers, kernel_size, dilation) in enumerate(
                zip((12, 24, 16), (3, 3, 3), (1, 2, 2))):
            self.xvector.add_module(f"block{i + 1}", _CamDenseTdnnBlock(
                num_layers=num_layers, in_channels=channels, out_channels=growth_rate,
                bn_channels=bn_size * growth_rate, kernel_size=kernel_size,
                dilation=dilation, config_str=config_str,
                memory_efficient=memory_efficient))
            channels = channels + num_layers * growth_rate
            self.xvector.add_module(f"transit{i + 1}", _TransitLayer(
                channels, channels // 2, bias=False, config_str=config_str))
            channels //= 2
        self.xvector.add_module("out_nonlinear", _get_nonlinear(config_str, channels))
        if self.output_level == "segment":
            self.xvector.add_module("stats", _StatsPool())
            self.xvector.add_module("dense", _DenseLayer(
                channels * 2, embedding_size, config_str="batchnorm_"))
        else:
            raise ValueError("本仓只用 segment 级输出")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """fbank [B, T, F] → 嵌入 [B, embedding_size]。"""
        x = x.permute(0, 2, 1)  # (B,T,F) => (B,F,T)
        x = self.head(x)
        x = self.xvector(x)
        return x


class _StatsPool(torch.nn.Module):
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return _statistics_pooling(x)


# ---------------------------------------------------------------------------
# 一站式封装
# ---------------------------------------------------------------------------

class SpeakerEmbedder:
    """权重装载 + fbank/CMN 特征 + L2 归一化嵌入（CPU 单线程友好）。"""

    #: torch intra-op 线程帽（本机 64 核默认全开会线程互踩：7.4s 音频嵌入
    #: 49.6s → 8 线程 0.25s，T7 实测；与 m3 audiosplit threads=16 同一教训）
    TORCH_THREADS = 8

    def __init__(self, weights: str | Path | None = None, device: str = "cpu",
                 embedding_size: int = 192):
        if device == "cpu" and torch.get_num_threads() > self.TORCH_THREADS:
            torch.set_num_threads(self.TORCH_THREADS)
        path = Path(weights) if weights else default_weights_path()
        if not path.is_file():
            raise VoxDiaError(
                f"voxdia 权重缺失: {path}（下载来源与放置目录见 configs/models.yaml "
                "voxdia 条目；ModelScope iic/speech_campplus_sv_zh-cn_16k-common 直下）")
        self.net: VoxDiaNet = VoxDiaNet(embedding_size=embedding_size)
        state = torch.load(path, map_location="cpu", weights_only=False)
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        self.net.load_state_dict(state, strict=True)
        self.net.eval().to(device)
        self.device = device
        self.dim = embedding_size

    @torch.no_grad()
    def embed_waveform(self, wav: torch.Tensor, *, sample_rate: int = 16000) -> torch.Tensor:
        """16k 单声道波形 [N]（float，任意幅度刻度）→ L2 归一化嵌入 [dim]。"""
        if wav.numel() < sample_rate // 10:  # <0.1s 拒绝（嵌入无意义）
            raise VoxDiaError(f"音频过短无法嵌入: {wav.numel()} 采样（<0.1s）")
        feat = kaldi_fbank(wav.to(torch.float32), sample_rate=sample_rate)
        feat = feat - feat.mean(dim=0, keepdim=True)  # 逐 utterance CMN（官方口径）
        emb = self.net(feat.unsqueeze(0)).squeeze(0)
        return F.normalize(emb, dim=-1)

    @torch.no_grad()
    def embed_file(self, wav_path: str | Path, *, sample_rate: int = 16000) -> torch.Tensor:
        """wav 文件 → L2 归一化嵌入（经 soundfile 解码，16k 单声道重采样）。"""
        import soundfile as sf

        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        if sr != sample_rate:
            import librosa

            mono = librosa.resample(mono, orig_sr=sr, target_sr=sample_rate)
        return self.embed_waveform(torch.from_numpy(mono.copy()), sample_rate=sample_rate)
