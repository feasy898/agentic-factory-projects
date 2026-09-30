"""M13 应用壳 · FastAPI 装配（beaneye.app.main）。

端点（plan/开发指令.md §4 M13）：

- ``POST /api/v1/scans`` —— multipart 双图上传，或 JSON ``{"synth": {...}}``
  （合成引擎缺位 → 内置确定性模拟源兜底，响应注明降级）→ ``{job_id}``；
- ``GET  /api/v1/jobs/{id}`` —— 作业状态（queued/running/done/failed + stage）；
- ``GET  /api/v1/results`` / ``GET /api/v1/results/{id}`` —— 结果列表 / 完整
  BatchResult 信封（含 ``degraded`` / ``degraded_stages`` / ``degraded_reasons``）；
- ``GET  /api/v1/results/{id}/passport?lang=zh[&download=1]`` —— 护照 HTML
  预览/下载；
- ``GET  /api/v1/results/{id}/evidence/{bean_id}/{side}`` —— 逐豆证据裁剪图；
- ``GET  /api/v1/standards`` —— 可用定级标准；
- ``GET  /demo`` —— 单页演示（上传/结果列表/护照预览/证据卡，静态资源全部
  本地内嵌，零外链）。

降级总原则：识别模型缺位 → 空检出继续走完全链路并显式标注；护照失败 →
结果照常返回、护照阶段入降级清单；标定失败 → 作业 failed（图上无定位码
无法给出 mm 坐标，静默继续只会产出假结果）。
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

from beaneye.acquisition.base import imwrite_bgr
from beaneye.app.components import Components, build_components
from beaneye.app.pipeline import PipelineRequest, make_offline_agent
from beaneye.app.store import JOB_DONE, AppStore
from beaneye.report import LANGS as REPORT_LANGS
from beaneye.schemas import TrayScan
from beaneye.standards import list_standards, load_standard

__all__ = ["create_app", "run", "DEFAULT_DATA_ROOT", "DEMO_HTML_PATH"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = Path(os.environ.get("BEANEYE_DATA_ROOT") or (_REPO_ROOT / "out" / "app"))
DEMO_HTML_PATH = Path(__file__).resolve().parent / "static" / "demo.html"

_SCAN_ROOT_NAME = "scans"
_UPLOAD_MAX_BYTES = 64 * 1024 * 1024
_SIDES = ("top", "bottom")


# ---------------------------------------------------------------------------
# 请求解析产物
# ---------------------------------------------------------------------------


@dataclass
class _Ingest:
    scan: TrayScan
    top_path: Path
    bottom_path: Path
    standard_id: str
    langs: list[str]
    degraded_reasons: dict[str, str]


class _BadRequest(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------


def create_app(
    *,
    data_root: str | Path | None = None,
    segment: Any | None = None,
    classify: Any | None = None,
    agent: Any | None = None,
    allow_probe: bool = True,
    langs: Sequence[str] = ("zh", "en", "vi"),
    max_workers: int = 2,
) -> FastAPI:
    """构造 FastAPI 应用。

    参数
    ----
    data_root:
        扫描图/证据/护照的数据根目录（缺省 ``$BEANEYE_DATA_ROOT`` 或
        ``<仓库>/out/app``）。
    segment / classify:
        显式注入的分割/分类实现（满足冻结 Protocol；缺省探测
        ``beaneye.segment`` / ``beaneye.classify`` 工厂，探测不到即显式降级）。
    allow_probe:
        False 时跳过工厂探测（纯注入或纯降级；测试用）。
    agent:
        注入溯因智能体；缺省离线模板实现（评测不依赖网络）。
    langs:
        护照默认语言（可用请求参数覆盖）。
    max_workers:
        进程内作业线程池大小。
    """
    root = Path(data_root) if data_root is not None else DEFAULT_DATA_ROOT
    components: Components = build_components(segment, classify, allow_probe=allow_probe)
    offline_agent = agent if agent is not None else make_offline_agent()
    default_langs = _norm_langs(list(langs))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.store.shutdown()

    app = FastAPI(
        title="BeanEye 啡眼 · 质量检测 API",
        version="0.1.0",
        lifespan=lifespan,
    )
    store = AppStore(
        components,
        data_root=str(root),
        max_workers=max_workers,
        agent=offline_agent,
    )
    app.state.store = store
    app.state.data_root = root
    app.state.default_langs = default_langs

    # -- 页面 --------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        return RedirectResponse(url="/demo")

    @app.get("/demo", include_in_schema=False)
    async def demo() -> HTMLResponse:
        return HTMLResponse(DEMO_HTML_PATH.read_text(encoding="utf-8"))

    # -- 健康 / 标准 --------------------------------------------------------
    @app.get("/api/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "degraded_stages": components.degraded_stages(),
            "data_root": str(root),
        }

    @app.get("/api/v1/standards")
    async def standards() -> dict[str, Any]:
        items = []
        for sid in sorted(list_standards()):
            std = load_standard(sid)
            items.append(
                {
                    "id": std.standard_id,
                    "display": dict(std.display),
                    "grades": std.grade_names(),
                    "verified": len(std.warnings) == 0,
                    "warning_count": len(std.warnings),
                }
            )
        return {"standards": items, "default": items[0]["id"] if items else None}

    # -- 提交作业 ------------------------------------------------------------
    @app.post("/api/v1/scans")
    async def create_scan(request: Request) -> JSONResponse:
        ct = (request.headers.get("content-type") or "").lower()
        try:
            if "multipart/form-data" in ct:
                ingest = await _ingest_multipart(request, default_langs)
            elif "application/json" in ct:
                ingest = await _ingest_synth_json(request, default_langs)
            else:
                raise _BadRequest(
                    "Content-Type 须为 multipart/form-data（双图上传）或 application/json"
                    "（{\"synth\": {...}} 内置合成源）"
                )
        except _BadRequest as exc:
            return JSONResponse({"error": exc.message}, status_code=400)
        job = store.submit(
            PipelineRequest(
                scan=ingest.scan,
                top_path=ingest.top_path,
                bottom_path=ingest.bottom_path,
                standard_id=ingest.standard_id,
                langs=ingest.langs,
                data_root=root,
                ingest_degraded=ingest.degraded_reasons,
            )
        )
        return JSONResponse(
            {
                "job_id": job.job_id,
                "status": job.status,
                "sample_id": job.sample_id,
                "standard_id": job.standard_id,
                "degraded_reasons": ingest.degraded_reasons,
                "poll": f"/api/v1/jobs/{job.job_id}",
            },
            status_code=200,
        )

    # -- 作业状态 ------------------------------------------------------------
    @app.get("/api/v1/jobs/{job_id}")
    async def job_status(job_id: str) -> JSONResponse:
        job = store.get_job(job_id)
        if job is None:
            return JSONResponse({"error": f"未知作业 {job_id}"}, status_code=404)
        return JSONResponse(job.public_view())

    # -- 结果 ----------------------------------------------------------------
    @app.get("/api/v1/results")
    async def results_list() -> dict[str, Any]:
        return {"results": [r.summary_view() for r in store.list_results()]}

    @app.get("/api/v1/results/{result_id}")
    async def result_detail(result_id: str) -> JSONResponse:
        rec = store.get_result(result_id)
        if rec is None:
            return JSONResponse({"error": f"未知结果 {result_id}"}, status_code=404)
        return JSONResponse(_result_envelope(rec))

    @app.get("/api/v1/results/{result_id}/passport")
    async def result_passport(result_id: str, lang: str = "zh", download: int = 0) -> Response:
        rec = store.get_result(result_id)
        if rec is None:
            return JSONResponse({"error": f"未知结果 {result_id}"}, status_code=404)
        if rec.passport is None:
            reason = rec.degraded_reasons.get("passport", "护照未生成")
            return JSONResponse({"error": reason}, status_code=409)
        if lang not in rec.passport.html_paths:
            return JSONResponse(
                {
                    "error": f"护照无 {lang!r} 语言版本；可用: {sorted(rec.passport.html_paths)}",
                },
                status_code=404,
            )
        path = Path(rec.passport.html_paths[lang])
        if not path.is_file():
            return JSONResponse({"error": f"护照文件缺失: {path}"}, status_code=404)
        fname = f"passport_{lang}_{result_id[:8]}.html"
        return FileResponse(
            path,
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{fname}"' if download else f'inline; filename="{fname}"'
                )
            },
        )

    @app.get("/api/v1/results/{result_id}/evidence/{bean_id}/{side}")
    async def result_evidence(result_id: str, bean_id: str, side: str) -> Response:
        rec = store.get_result(result_id)
        if rec is None:
            return JSONResponse({"error": f"未知结果 {result_id}"}, status_code=404)
        if side not in _SIDES:
            return JSONResponse({"error": f"side 须为 {'/'.join(_SIDES)}"}, status_code=400)
        bean = next((b for b in rec.result.beans if b.bean_id == bean_id), None)
        if bean is None:
            return JSONResponse({"error": f"结果 {result_id} 无豆 {bean_id}"}, status_code=404)
        obs = getattr(bean, side)
        if obs is None:
            return JSONResponse({"error": f"豆 {bean_id} 无 {side} 面观测"}, status_code=404)
        crop = Path(rec.data_root) / obs.crop_path
        if not crop.is_file():
            return JSONResponse({"error": f"证据图缺失: {obs.crop_path}"}, status_code=404)
        return Response(content=crop.read_bytes(), media_type="image/png")

    return app


# ---------------------------------------------------------------------------
# 上传解析（multipart / synth JSON）
# ---------------------------------------------------------------------------


async def _ingest_multipart(request: Request, default_langs: list[str]) -> _Ingest:
    form = await request.form()
    raw: dict[str, bytes] = {}
    for side in _SIDES:
        up = form.get(side)
        if up is None or isinstance(up, str):
            raise _BadRequest(f"缺少 {side} 面整盘图（multipart 字段名 {side!r}）")
        data = await up.read()
        if not data:
            raise _BadRequest(f"{side} 面整盘图为空")
        if len(data) > _UPLOAD_MAX_BYTES:
            raise _BadRequest(f"{side} 面整盘图超过 {_UPLOAD_MAX_BYTES // (1024 * 1024)}MB 上限")
        raw[side] = data

    imgs = {side: _decode_image(raw[side], side) for side in _SIDES}
    standard_id = _pick_str(form, "standard") or _default_standard()
    langs = _norm_langs(_pick_str(form, "langs"), fallback=default_langs)
    sample_id = _pick_str(form, "sample_id") or f"sample-{_short_uid()}"
    tray_id = _pick_str(form, "tray_id") or "tray_01"
    _require_standard(standard_id)

    scan_id = f"scan_up_{_short_uid()}"
    scan_dir = Path(request.app.state.data_root) / _SCAN_ROOT_NAME / scan_id
    top_rel, bottom_rel = f"{scan_id}/top.png", f"{scan_id}/bottom.png"
    imwrite_bgr(Path(scan_dir) / "top.png", imgs["top"])
    imwrite_bgr(Path(scan_dir) / "bottom.png", imgs["bottom"])
    scan = TrayScan(
        scan_id=scan_id,
        sample_id=sample_id,
        tray_id=tray_id,
        top_image=top_rel,
        bottom_image=bottom_rel,
        calibration=None,
        captured_at=_now_iso(),
        source="usb",  # 上传图=真实相机拍摄语义（契约三值取 usb）
    )
    return _Ingest(
        scan=scan,
        top_path=scan_dir / "top.png",
        bottom_path=scan_dir / "bottom.png",
        standard_id=standard_id,
        langs=langs,
        degraded_reasons={},
    )


async def _ingest_synth_json(request: Request, default_langs: list[str]) -> _Ingest:
    try:
        body = await request.json()
    except Exception as exc:
        raise _BadRequest(f"JSON 请求体解析失败（{exc.__class__.__name__}）") from exc
    if not isinstance(body, dict) or "synth" not in body:
        raise _BadRequest('JSON 请求体须为 {"synth": {...}, ...}')
    synth = body.get("synth") or {}
    if not isinstance(synth, dict):
        raise _BadRequest('"synth" 须为对象')

    # 合成引擎（beaneye.synth）已落库、采集源接线未完成 → 内置确定性模拟源兜底
    # （显式降级；接线待办登记于 docs/assets/feedback.md）
    from beaneye.acquisition import MockSource

    req_id = _short_uid()
    scan_dir = Path(request.app.state.data_root) / _SCAN_ROOT_NAME / f"req_{req_id}"
    try:
        src = MockSource(
            scan_dir,
            n_beans=_want_int(synth, "n_beans", 36, 0, 400),
            width=_want_int(synth, "width", 1024, 256, 4096),
            height=_want_int(synth, "height", 1024, 256, 4096),
            seed=_want_int(synth, "seed", 20260928, 0, 2**31 - 1),
            defect_rate=_want_float(synth, "defect_rate", 0.2, 0.0, 1.0),
            scan_prefix=f"synth_{req_id}",
        )
        scan = src.capture_pair(
            _want_str2(synth, body, "sample_id", f"sample-synth-{req_id}"),
            _want_str2(synth, body, "tray_id", "tray_01"),
        )
    except _BadRequest:
        raise
    except Exception as exc:
        raise _BadRequest(f"内置合成源失败（{exc.__class__.__name__}: {exc}）") from exc

    standard_id = _want_str2({}, body, "standard", "") or _default_standard()
    _require_standard(standard_id)
    langs_raw = body.get("langs")
    langs = _norm_langs(langs_raw if isinstance(langs_raw, str) else None, fallback=default_langs)
    from beaneye.acquisition import scan_paths

    paths = scan_paths(scan, scan_dir)
    return _Ingest(
        scan=scan,
        top_path=paths["top"],
        bottom_path=paths["bottom"],
        standard_id=standard_id,
        langs=langs,
        degraded_reasons={
            "synth": "合成引擎已落库但本入口未接线（synth_source 接线待办）——已回退内置"
            "确定性模拟源（source=mock），盘面豆粒与缺陷为程序化合成，不代表真实样品"
        },
    )


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _result_envelope(rec: Any) -> dict[str, Any]:
    rid = rec.result.result_id
    passport_urls = {
        lang: f"/api/v1/results/{rid}/passport?lang={lang}"
        for lang in (rec.passport.langs if rec.passport is not None else [])
    }
    return {
        "result_id": rid,
        "status": JOB_DONE,
        "degraded": bool(rec.degraded_stages),
        "degraded_stages": list(rec.degraded_stages),
        "degraded_reasons": dict(rec.degraded_reasons),
        "pairing_summary": dict(rec.pairing_summary),
        "scan": {
            "scan_id": rec.scan.scan_id,
            "sample_id": rec.scan.sample_id,
            "tray_id": rec.scan.tray_id,
            "source": rec.scan.source,
            "calibrated": rec.scan.calibration is not None,
        },
        "pipeline_versions": dict(rec.result.pipeline_versions),
        "timings_s": dict(rec.result.timings_s),
        "result": _result_dict(rec.result),
        "passport": (_passport_dict(rec.passport) if rec.passport is not None else None),
        "passport_urls": passport_urls,
        "created_at": rec.created_at,
    }


def _result_dict(result: Any) -> dict[str, Any]:
    return json.loads(result.to_json())


def _passport_dict(passport: Any) -> dict[str, Any]:
    return json.loads(passport.to_json())


def _decode_image(data: bytes, side: str) -> np.ndarray:
    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise _BadRequest(f"{side} 面整盘图无法解码（损坏或非图像）")
    h, w = img.shape[:2]
    if h < 200 or w < 200:
        raise _BadRequest(f"{side} 面整盘图过小（{w}x{h}），至少 200x200")
    return img


def _pick_str(form: Any, key: str) -> str | None:
    v = form.get(key)
    if v is None or isinstance(v, type(None)):
        return None
    s = str(v).strip()
    return s or None


def _want_str2(primary: dict, secondary: dict, key: str, default: str) -> str:
    """依次查两个字典的字符串字段（如 synth 内层与请求体外层）。"""
    for src in (primary, secondary):
        v = src.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return default


def _want_int(d: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= int(v) <= hi:
        raise _BadRequest(f"{key} 须为整数且在 [{lo}, {hi}]")
    return int(v)


def _want_float(d: dict, key: str, default: float, lo: float, hi: float) -> float:
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= float(v) <= hi:
        raise _BadRequest(f"{key} 须为数值且在 [{lo}, {hi}]")
    return float(v)


def _norm_langs(raw: str | Sequence[str] | None, *, fallback: list[str] | None = None) -> list[str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return list(fallback) if fallback else list(REPORT_LANGS)
    items = raw if isinstance(raw, (list, tuple)) else [p.strip() for p in str(raw).split(",")]
    out: list[str] = []
    for it in items:
        s = str(it).strip()
        if not s:
            continue
        if s not in REPORT_LANGS:
            raise _BadRequest(f"语言 {s!r} 不支持；可用: {list(REPORT_LANGS)}")
        if s not in out:
            out.append(s)
    if not out:
        return list(fallback) if fallback else list(REPORT_LANGS)
    return out


def _require_standard(standard_id: str) -> None:
    if standard_id not in list_standards():
        raise _BadRequest(f"未知定级标准 {standard_id!r}；可用: {sorted(list_standards())}")


def _default_standard() -> str:
    stds = sorted(list_standards())
    if "cqi_fine_robusta" in stds:
        return "cqi_fine_robusta"
    return stds[0]


def _short_uid() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run(
    *,
    host: str = "127.0.0.1",
    port: int = 8600,
    data_root: str | Path | None = None,
    **factory_kwargs: Any,
) -> None:
    """本机起服务（演示入口）：``python -m beaneye.app``。"""
    import uvicorn

    app = create_app(data_root=data_root, **factory_kwargs)
    uvicorn.run(app, host=host, port=port)
