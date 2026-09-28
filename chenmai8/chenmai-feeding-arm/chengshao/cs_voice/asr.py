"""ASR 引擎：CPU 离线语音识别，输出纯文本供意图解析。

主后端 ``FunasrBackend``：funasr 运行时 + 小体积多语种识别模型
（模型仓库 id 默认 ``iic/SenseVoiceSmall``，可用环境变量
``CS_VOICE_ASR_MODEL`` 覆盖；权重经 modelscope 拉取后落本地缓存，
之后全程离线）。非流式，适合短句指令（≤30s）。

回退后端 ``OnnxBackend``（开发指令 §9 回退表）：funasr 运行时不可用时，
切换 sherpa-onnx 的同源 ONNX 模型目录（``CS_VOICE_ONNX_DIR`` 指向
解包后的模型目录，CPU 可跑），接口不变。

识别结果中的富标签（语种/情感/事件等 ``<|...|>`` 标记）统一剥除，
只返回纯文本。
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path

import numpy as np

DEFAULT_MODEL_ID = "iic/SenseVoiceSmall"

_RICH_TAG = re.compile(r"<\|[^|]*\|>")


def strip_rich_tags(text: str) -> str:
    """剥除识别结果中的 ``<|zh|>`` 类富标签，只留可读文本。"""
    return _RICH_TAG.sub("", text or "").strip()


class AsrEngine:
    """语音识别引擎门面：``auto`` 模式下主后端失败自动落到回退后端。

    模型懒加载：构造不加载，首次 :meth:`ensure_loaded` /
    :meth:`transcribe` 时才拉起（下载只发生一次，之后读本地缓存）。
    """

    def __init__(self, backend: str = "auto", model_id: str | None = None,
                 device: str = "cpu") -> None:
        if backend not in {"auto", "funasr", "onnx"}:
            raise ValueError(f"未知 backend: {backend!r}")
        self._backend_choice = backend
        self._model_id = model_id or os.environ.get(
            "CS_VOICE_ASR_MODEL", DEFAULT_MODEL_ID
        )
        self._device = device
        self._impl = None          # 已加载的后端实例
        self.backend_name = "none"  # 实际生效后端名（进报告）

    # -- 后端实现 ----------------------------------------------------------

    def _make_funasr(self):
        import torch
        from funasr import AutoModel  # 延迟导入：未装 funasr 时才走回退

        # 64 核 Windows 上 torch 默认多线程会互相争抢（实测 rtf 抖到 1.5+），
        # 单线程最稳最快（rtf≈0.25）；可用 CS_VOICE_TORCH_THREADS 覆盖。
        torch.set_num_threads(int(os.environ.get("CS_VOICE_TORCH_THREADS", "1")))
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass  # 每进程只允许设置一次，重复调用忽略

        model_path = self._resolve_local_model_dir() or self._model_id
        model = AutoModel(
            model=model_path,
            device=self._device,
            disable_update=True,
            disable_log=True,
        )
        return ("funasr", lambda path: model.generate(
            input=path, cache={}, language="auto", itn=True,
        ))

    def _resolve_local_model_dir(self) -> Path | None:
        """模型已在本地缓存（modelscope 布局）则返回其目录，避免联网校验。

        命中新布局 ``<cache>/models/<org>--<name>/snapshots/<ref>/config.yaml``
        或旧布局 ``<cache>/hub/<org>/<name>/config.yaml``；都未命中返回 None
        （首次运行仍走 hub 下载，之后固定本地）。
        """
        cache_root = Path(os.environ.get("MODELSCOPE_CACHE")
                          or (Path.home() / ".cache" / "modelscope"))
        mid = self._model_id
        org, _, name = mid.partition("/")
        if cache_root.name == "models":  # env 已指到 .../models 层
            mid_dir = cache_root
        else:
            mid_dir = cache_root / "models" / f"{org}--{name}"
        candidates = [
            mid_dir / "snapshots" / "master",
            mid_dir,
            cache_root / "hub" / org / name,
        ]
        for cand in candidates:
            if (cand / "config.yaml").is_file():
                return cand
        return None

    def _make_onnx(self):
        import sherpa_onnx  # 延迟导入：§9 回退路径

        model_dir = Path(
            os.environ.get("CS_VOICE_ONNX_DIR", "")
            or (_REPO_CACHE / "sherpa-onnx-sensevoice")
        )
        if not model_dir.is_dir():
            raise RuntimeError(
                "ONNX 回退后端未配置：请设置 CS_VOICE_ONNX_DIR 指向模型目录"
            )
        rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_dir / "model.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=2,
        )
        import soundfile as sf

        def infer(path: str):
            wave, sr = sf.read(path, dtype="float32", always_2d=True)
            stream = rec.create_stream()
            stream.accept_waveform(sr, wave.mean(axis=1))
            rec.decode_stream(stream)
            return [{"text": stream.result.text}]

        return ("onnx", infer)

    # -- 公开接口 ----------------------------------------------------------

    def ensure_loaded(self) -> str:
        """加载模型，返回实际生效的后端名；失败按 §9 顺序回退。"""
        if self._impl is not None:
            return self.backend_name
        order = {
            "auto": ["_make_funasr", "_make_onnx"],
            "funasr": ["_make_funasr"],
            "onnx": ["_make_onnx"],
        }[self._backend_choice]
        errs: list[str] = []
        for factory in order:
            try:
                self.backend_name, infer = getattr(self, factory)()
                self._impl = infer
                return self.backend_name
            except Exception as err:  # noqa: BLE001 —— 回退链要接住一切加载错误
                errs.append(f"{factory}: {err!r}")
        raise RuntimeError("ASR 后端全部加载失败（含 §9 回退）: " + " | ".join(errs))

    def transcribe(self, wave: np.ndarray, sr: int) -> str:
        """识别一段单声道波形（float，任意采样率），返回纯文本。"""
        if wave.ndim != 1:
            wave = wave.reshape(-1)
        if sr != 16000:  # 模型前端按 16k 工作，这里统一重采样
            wave = _resample(wave, sr, 16000)
            sr = 16000
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            import soundfile as sf

            sf.write(tmp.name, wave, sr, subtype="PCM_16")
            return self.transcribe_file(tmp.name)
        finally:
            os.unlink(tmp.name)

    def transcribe_file(self, path: str | Path) -> str:
        """识别一个 wav/flac 等音频文件，返回纯文本。"""
        self.ensure_loaded()
        t0 = time.perf_counter()
        res = self._impl(str(path))
        elapsed = time.perf_counter() - t0
        self.last_infer_s = elapsed  # 最近一次推理耗时（供 eval 采集）
        text = res[0].get("text", "") if res else ""
        return strip_rich_tags(text)


_REPO_CACHE = Path.home() / ".cache" / "cs_voice"


def _resample(wave: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    try:
        import soxr

        return soxr.resample(wave, sr_in, sr_out)
    except ImportError:  # pragma: no cover —— soxr 在锁定依赖中，正常不会走到
        from scipy.signal import resample_poly

        from math import gcd

        g = gcd(sr_in, sr_out)
        return resample_poly(wave, sr_out // g, sr_in // g)
