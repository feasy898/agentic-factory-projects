"""GPU 服务统一 HTTP 客户端（httpx，M4 起步）。

地址解析顺序：显式参数 → 环境变量 ``M4_ASR_URL`` → 默认 ``http://127.0.0.1:9001``。
GPU 侧服务只监听 GPU 机 127.0.0.1（该机有公网出口，不对公网暴露端口），
本机一律经 :mod:`ops` 的 ``ops/tunnel_gpu.sh``（ssh -L）隧道访问，故默认值即本机端口。

用法：
    from pipeline.gpu_client import GpuClient
    cli = GpuClient()                      # 或 GpuClient("http://127.0.0.1:9001")
    cli.health()                           # 装载状态
    resp = cli.asr_align("audio_16k.wav", lang="zh")
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Optional

import httpx

#: 各 GPU 服务的环境变量名 → 默认地址（服务清单见 configs/models.yaml 与规划 §2）
SERVICE_ENV = {
    "asr": ("M4_ASR_URL", "http://127.0.0.1:9001"),
}


class GpuServiceError(RuntimeError):
    """GPU 服务调用失败（网络/HTTP 错误/业务错误均归一为该异常）。"""


class GpuClient:
    """asr_align(:9001) 客户端：multipart 上传 wav → JSON（超时默认 5 分钟，首载预热兜底）。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 300.0,
        retries: int = 2,
        retry_wait_s: float = 2.0,
    ) -> None:
        if base_url is None:
            env_name, default = SERVICE_ENV["asr"]
            base_url = os.environ.get(env_name, default)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.retry_wait_s = retry_wait_s

    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.request(method, f"{self.base_url}{path}", **kw)
                if resp.status_code >= 400:
                    raise GpuServiceError(f"HTTP {resp.status_code} {path}: {resp.text[:400]}")
                return resp
            except (httpx.HTTPError, GpuServiceError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(self.retry_wait_s)
        raise GpuServiceError(f"{method} {self.base_url}{path} 失败（重试 {self.retries} 次后）: {last_exc}")

    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        """GET /health —— 模型装载状态。服务不可达抛 :class:`GpuServiceError`。"""
        return self._request("GET", "/health").json()

    def asr_align(
        self,
        wav: str | Path,
        *,
        lang: str = "zh",
        text: str = "",
        do_align: bool = True,
        do_emo: bool = True,
    ) -> dict[str, Any]:
        """POST /v1/asr_align —— 一次调用拿全：转写 + 逐字时间戳 + 情绪/事件 + 说话人预分段。

        :param wav: 16k 单声道 wav（建议 M4 输入口径 ``04_dial/vocals.wav`` 人声，
                    B1 冻结：M4 不读 01_media/audio_16k.wav 混音；
                    其他采样率/声道由服务端重采样兜底）。
        :param lang: ``zh``/``en``/...；``ar`` 服务端自动走字符比例内插降级。
        :param text: 校对文本（非空则按它重对齐，OCR↔ASR 校对口径预留）。

        时间零点（B1 契约冻结，见 pipeline/contracts.py 规则 7 与
        docs/b1_contract_notes.md §2）：响应中 ``words[*].s/e`` 与
        ``segments[*].start/end`` 均为**本次上传音频内相对时间**（0 = 上传起点）；
        全片绝对时间 = 片段内时间 + offset（offset = 上传片段在全集音频中的
        起点秒，由调用方记录并经 ``contracts.to_absolute_seconds`` 平移）。
        整段 ``text`` 不是句级产物：切句规则 = OCR 时间段或 VAD segments
        （冻结规则 8），禁止把整段 text 当单句落 C2。
        """
        wav_path = Path(wav)
        if not wav_path.is_file():
            raise GpuServiceError(f"音频不存在: {wav_path}")
        data = wav_path.read_bytes()
        resp = self._request(
            "POST",
            "/v1/asr_align",
            files={"file": (wav_path.name, data, "audio/wav")},
            data={
                "lang": lang,
                "text": text or "",
                "do_align": str(bool(do_align)).lower(),
                "do_emo": str(bool(do_emo)).lower(),
            },
        )
        return resp.json()
