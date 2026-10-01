"""M7 客户端 —— 情绪迁移合成（GPU :9002 tts 服务的本机封装）。

C 出口（冻结口径）：合成 wav + **实际时长**（``duration_s``，float 3 位）——
服务端实测产出音频后回传，客户端落盘后用 soundfile 复测，两边一致才交付。
M8 时长对齐以本出口的实测时长为 ``meas_dur``。

调用口径（契约 C5，:class:`pipeline.contracts.SynthPlanItem` 同源字段）：
  - ``text``            目标语台词（必填）；
  - ``voice_ref``       **音色参考**：角色干净人声样本（05_cast/voicebank，C3）；
  - ``emo_ref``         **情绪参考**：原片该句人声（04_dial/emo_refs）——音色与情绪
    **可来自不同说话人**，这是情绪迁移的核心用法；缺省=只用音色参考；
  - ``emo_alpha``       情绪强度 [0,1]（按情绪识别 score 映射 0.5–0.85，M7 生产规则）；
  - ``duration_factor`` 语速系数 [0.5,2.0]（初值 1.0，M8 二分搜索的调节旋钮）；
  - ``engine``          ``auto``=按 models.yaml routing.tts[lang] 链（默认）或显式引擎名；
  - ``lang``            en/es/ar/zh/ja。

服务路由：``auto`` 按语种链依序尝试（链节点失败/权重未部署记入 ``attempts`` 后继续）；
备选引擎无情绪参考通道时如实回 ``emo_ref_used=false``（音色参考继续生效）。

用法：
    from pipeline.tts_client import TtsClient
    cli = TtsClient()                       # 或 TtsClient("http://127.0.0.1:9002")
    r = cli.synth("What do you actually want?",
                  voice_ref="voicebank/char_nan_ref.wav",
                  emo_ref="emo_refs/u0007.wav", lang="en", out="u0007.wav")
    r["duration_s"]                          # C 出口：实际时长

CLI：
    python -m pipeline.tts_client --text "..." --voice-ref a.wav --emo-ref b.wav \\
        --lang en --out out.wav
退出码：0 成功（wav 落盘且实测时长>0）；1 输入/服务错误；2 用法错误。
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import httpx

#: 服务地址环境变量 → 默认值（本机经 ops/tunnel_gpu.sh 隧道访问 GPU :9002）
SERVICE_ENV = ("M7_TTS_URL", "http://127.0.0.1:9002")

#: C5 契约字段范围（与服务端一致，客户端先挡一层给可读报错）
EMO_ALPHA_RANGE = (0.0, 1.0)
DURATION_FACTOR_RANGE = (0.5, 2.0)
#: 首载/懒加载余量（主力引擎 fp32 首次装载 + 备选链懒加载）——超时上限 10 分钟
DEFAULT_TIMEOUT_S = 600.0


class TtsError(RuntimeError):
    """tts 服务调用失败（网络/HTTP/业务错误均归一为该异常）。"""


def synth_response_to_wav(resp: dict[str, Any], out: str | Path) -> dict[str, Any]:
    """服务响应 → 落盘 wav + 实测时长（C 出口纯函数，eval 可离线测）。

    返回 ``{"out", "duration_s", "sr", "wav_bytes"}``；产出空/静音抛 :class:`TtsError`。
    """
    import io as _io

    import numpy as np
    import soundfile as sf

    b64 = resp.get("wav_b64")
    if not b64:
        raise TtsError(f"响应无 wav_b64（engine={resp.get('engine')} attempts={resp.get('attempts')}）")
    raw = base64.b64decode(b64)
    wav, sr = sf.read(_io.BytesIO(raw), dtype="float32")
    wav = np.asarray(wav).squeeze()
    duration_s = round(len(wav) / sr, 3)
    if duration_s <= 0 or float(np.abs(wav).max()) < 1e-4:
        raise TtsError(f"产出空/静音 (dur={duration_s}s)")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    return {"out": str(out_path), "duration_s": duration_s, "sr": int(sr), "wav_bytes": len(raw)}


class TtsClient:
    """:9002 tts 客户端：multipart 双参考上传 → JSON（wav_b64 + duration_s）。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        retries: int = 2,
        retry_wait_s: float = 2.0,
    ) -> None:
        if base_url is None:
            env_name, default = SERVICE_ENV
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
                    raise TtsError(f"HTTP {resp.status_code} {path}: {resp.text[:400]}")
                return resp
            except (httpx.HTTPError, TtsError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(self.retry_wait_s)
        raise TtsError(f"{method} {self.base_url}{path} 失败（重试 {self.retries} 次后）: {last_exc}")

    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        """GET /health —— 引擎装载状态 / 路由表 / 权重就位情况。"""
        return self._request("GET", "/health").json()

    def synth(
        self,
        text: str,
        voice_ref: str | Path,
        *,
        emo_ref: Optional[str | Path] = None,
        lang: str = "en",
        emo_alpha: float = 0.7,
        duration_factor: float = 1.0,
        engine: str = "auto",
        out: str | Path,
        utt_id: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """POST /v1/tts —— 双参考合成。返回 C 出口：``out``（wav 路径）+ ``duration_s``。

        客户端复测落盘音频时长并与服务端 ``duration_s`` 对账（差 >0.05s 报错，
        防半截传输）。``dry_run=True`` 只做路由解析（不占 GPU，返回 chain/attempts）。
        """
        if not (text or "").strip():
            raise TtsError("text 为空")
        voice_path = Path(voice_ref)
        if not voice_path.is_file():
            raise TtsError(f"音色参考不存在: {voice_path}")
        for name, v in (("emo_alpha", emo_alpha), ("duration_factor", duration_factor)):
            lo, hi = EMO_ALPHA_RANGE if name == "emo_alpha" else DURATION_FACTOR_RANGE
            if not lo <= v <= hi:
                raise TtsError(f"{name}={v} 越界 [{lo},{hi}]（C5 口径）")
        emo_path: Optional[Path] = Path(emo_ref) if emo_ref else None
        if emo_path is not None and not emo_path.is_file():
            raise TtsError(f"情绪参考不存在: {emo_path}")

        files: dict[str, Any] = {"voice_ref": (voice_path.name, voice_path.read_bytes(), "audio/wav")}
        if emo_path is not None:
            files["emo_ref"] = (emo_path.name, emo_path.read_bytes(), "audio/wav")
        data = {
            "text": text,
            "lang": lang,
            "emo_alpha": str(emo_alpha),
            "duration_factor": str(duration_factor),
            "engine": engine,
            "utt_id": utt_id or "",
            "dry_run": str(bool(dry_run)).lower(),
        }
        resp = self._request("POST", "/v1/tts", files=files, data=data).json()

        if dry_run:
            return resp
        result = synth_response_to_wav(resp, out)
        server_dur = resp.get("duration_s")
        if server_dur is not None and abs(float(server_dur) - result["duration_s"]) > 0.05:
            raise TtsError(
                f"时长对账失败: 服务端 {server_dur}s vs 客户端复测 "
                f"{result['duration_s']}s（疑似传输截断）"
            )
        result.update(
            engine=resp.get("engine"),
            chain=resp.get("chain"),
            attempts=resp.get("attempts"),
            timing=resp.get("timing"),
            versions=resp.get("versions"),
            request_echo=resp.get("request"),
        )
        return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.tts_client", description="M7 TTS 客户端")
    ap.add_argument("--text", required=True, help="目标语台词")
    ap.add_argument("--voice-ref", required=True, help="音色参考 wav（角色干净人声）")
    ap.add_argument("--emo-ref", default=None, help="情绪参考 wav（原片该句人声；情绪迁移）")
    ap.add_argument("--lang", default="en", help="语种（en/es/ar/zh/ja）")
    ap.add_argument("--emo-alpha", type=float, default=0.7, help="情绪强度 [0,1]")
    ap.add_argument("--duration-factor", type=float, default=1.0, help="语速系数 [0.5,2.0]")
    ap.add_argument("--engine", default="auto", help="auto=语种链（models.yaml routing.tts）或显式引擎名")
    ap.add_argument("--out", required=True, help="产出 wav 路径")
    ap.add_argument("--utt-id", default="", help="C5 utt_id（服务端日志追踪用）")
    ap.add_argument("--url", default=None, help="服务地址（默认 M7_TTS_URL 或 http://127.0.0.1:9002）")
    ap.add_argument("--dry-run", action="store_true", help="只做路由解析，不占 GPU")
    args = ap.parse_args(argv)

    try:
        cli = TtsClient(args.url)
        if args.dry_run:
            r = cli.synth(args.text, args.voice_ref, emo_ref=args.emo_ref, lang=args.lang,
                          engine=args.engine, out=args.out, utt_id=args.utt_id, dry_run=True)
            print(f"OK tts dry-run engine={r['engine']} chain={r['chain']}")
            return 0
        r = cli.synth(
            args.text, args.voice_ref,
            emo_ref=args.emo_ref, lang=args.lang, emo_alpha=args.emo_alpha,
            duration_factor=args.duration_factor, engine=args.engine,
            out=args.out, utt_id=args.utt_id,
        )
    except (TtsError, OSError) as exc:
        print(f"FAIL tts_client: {exc}")
        return 1
    emo_used = (r.get("request_echo") or {}).get("emo_ref_used")
    print(
        f"OK tts engine={r['engine']} out={r['out']} duration_s={r['duration_s']} "
        f"sr={r['sr']} emo_ref_used={emo_used} timing={r.get('timing')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
