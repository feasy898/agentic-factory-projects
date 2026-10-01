"""M13 应用壳 eval（W13）：FastAPI 端点 + 演示页 + 全链路装配。

运行（仓库根）::

    pytest tests/test_app.py -q

覆盖（任务 W13 + 开发指令 §4 M13）：
1. 组件装配：缺省（不注入、不探测）→ 分割/分类显式降级（原因非空、
   Null 实现产物过 M1 契约往返）；SegResult side 规范化适配；
2. 演示页：/demo 200、四区块（上传/结果列表/证据卡/护照预览）在位、
   **零外链**（无任何 http(s) 的 src/href/@import/url 引用）；
3. 标准端点：三套标准可列出（display/grades/verified）；
4. **httpx ASGI 端到端（注入测试替身）**：上传内置合成整盘夹具 → 200 →
   轮询作业 → 结果信封字段齐全（BatchResult 全契约字段 + 往返校验）→
   逐豆证据图可取 → 护照 HTML 可下载且二维码（zxing-cpp）解码回读
   payload/report_id/sha256 与 BatchResult 一致；
5. **降级端到端（缺省装配）**：0 检出走完全链路，degraded_stages 注明
   segment/classify，结果与护照仍完整可下载；
6. 合成请求（JSON {"synth":...}）→ 内置确定性模拟源兜底并注明降级；
7. 上传校验（缺图/坏图/未知标准/未知语言）与 404/失败路径
   （无定位码图 → 作业 failed 且 stage=calibration）。

全部素材为程序化合成（MockSource 夹具），不依赖任何真实数据集与网络。
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
import zxingcpp

from beaneye.acquisition import MockSource
from beaneye.app import PipelineRequest, build_components, create_app
from beaneye.app.components import normalize_seg_result
from beaneye.app.pipeline import STAGE_ORDER, run_pipeline
from beaneye.report import canonical_sha256, parse_qr_payload
from beaneye.schemas import BatchResult, BeanMask, SegResult, TrayScan
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
RANK = {k: TAX.severity_rank(k) for k in TAX.keys()}
STANDARD = "cqi_fine_robusta"
POLL_TIMEOUT_S = 240.0


# ---------------------------------------------------------------------------
# 测试替身：正射盘面网格上的阈值分割 + 灰度规则分类（验证接口抽象接线；
# 非生产实现——生产 classic/NN 由 M4/M5 模块提供）
# ---------------------------------------------------------------------------


class _ThresholdSegDouble:
    """Otsu 阈值 + 连通域：在 warp 后的 mm 网格上产 BeanMask（source=classic）。"""

    stage = "segment"
    version = "classic_threshold:test_double"

    def __init__(self, *, tray_mm: float = 300.0, grid_px: int = 2048,
                 min_area_mm2: float = 8.0, max_area_mm2: float = 90.0) -> None:
        self.mm_per_px = tray_mm / grid_px
        self.min_area_mm2 = min_area_mm2
        self.max_area_mm2 = max_area_mm2

    def predict(self, img_rgb: np.ndarray, scan: TrayScan) -> SegResult:
        gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        s = self.mm_per_px
        masks: list[BeanMask] = []
        for c in contours:
            area_mm2 = float(cv2.contourArea(c)) * s * s
            if area_mm2 < self.min_area_mm2 or area_mm2 > self.max_area_mm2:
                continue  # 噪点与四角定位码（60x60mm）都落在 [8, 90]mm² 之外
            poly = self._poly_mm(c)
            if poly is None:
                continue
            x, y, w, h = cv2.boundingRect(c)
            m = cv2.moments(c)
            if m["m00"] > 0:
                cx, cy = m["m10"] / m["m00"] * s, m["m01"] / m["m00"] * s
            else:
                cx, cy = (x + w / 2.0) * s, (y + h / 2.0) * s
            masks.append(
                BeanMask(
                    mask_id=f"top_{len(masks):04d}",  # side 由装配器规范化
                    side="top",
                    polygon=poly,
                    bbox_mm=(x * s, y * s, (x + w) * s, (y + h) * s),
                    area_mm2=area_mm2,
                    centroid_mm=(cx, cy),
                    source="classic",
                    conf=0.9,
                )
            )
        return SegResult(scan_id=scan.scan_id, side="top", masks=masks, runtime_s=0.0)

    def _poly_mm(self, contour: np.ndarray) -> list[list[float]] | None:
        s = self.mm_per_px
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        pts = approx if len(approx) >= 3 else contour
        if len(pts) < 3:
            return None
        return [[float(p[0][0]) * s, float(p[0][1]) * s] for p in pts[:64]]


class _GrayClsDouble:
    """灰度规则分类：暗粒记 black，其余 normal（对接收到的 crop RGBA 判定）。"""

    stage = "classify"
    version = "gray_rules:test_double"

    def __init__(self, dark_gray_max: float = 90.0) -> None:
        self.dark_gray_max = dark_gray_max

    def classify(self, crop_rgba: np.ndarray, mask: BeanMask) -> tuple[str, float, int]:
        sel = crop_rgba[..., 3] > 0
        if not sel.any():
            return "normal", 0.5, 0
        rgb = crop_rgba[..., :3].astype(np.float32)
        gray = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2])[sel]
        mean = float(gray.mean())
        if mean < self.dark_gray_max:
            return "black", 0.9, RANK["black"]
        return "normal", 0.99, 0


# ---------------------------------------------------------------------------
# 夹具：合成整盘对 + 应用客户端
# ---------------------------------------------------------------------------


def _mock_pair(tmp_path: Path, *, n_beans: int, defect_rate: float, seed: int):
    src = MockSource(
        tmp_path / "ingest", n_beans=n_beans, width=1024, height=1024,
        seed=seed, defect_rate=defect_rate,
    )
    scan = src.capture_pair(f"sample-{seed}", "tray_01")
    root = tmp_path / "ingest"
    return scan, root / scan.top_image, root / scan.bottom_image


class _SyncASGIClient:
    """同步测试外观：内部是 ``httpx.AsyncClient + httpx.ASGITransport``（进程内
    ASGI 端到端）。作业在线程池执行，轮询循环在事件循环间隙 sleep，不阻塞。"""

    def __init__(self, app) -> None:
        import asyncio

        self._loop = asyncio.new_event_loop()
        self._app = app
        self._client: httpx.AsyncClient | None = None

    def __enter__(self) -> "_SyncASGIClient":
        transport = httpx.ASGITransport(app=self._app)
        client = httpx.AsyncClient(
            transport=transport, base_url="http://testserver", timeout=60.0
        )
        self._loop.run_until_complete(client.__aenter__())
        self._client = client
        return self

    def __exit__(self, *exc) -> None:
        assert self._client is not None
        self._loop.run_until_complete(self._client.__aexit__(*exc))
        self._loop.close()
        self._client = None

    def get(self, url: str, **kw) -> httpx.Response:
        return self._loop.run_until_complete(self._client.get(url, **kw))

    def post(self, url: str, **kw) -> httpx.Response:
        return self._loop.run_until_complete(self._client.post(url, **kw))


def _make_client(app) -> _SyncASGIClient:
    return _SyncASGIClient(app)


@pytest.fixture()
def full_app(tmp_path: Path):
    return create_app(
        data_root=tmp_path / "data",
        segment=_ThresholdSegDouble(),
        classify=_GrayClsDouble(),
        allow_probe=False,
        langs=("zh", "en", "vi"),
    )


@pytest.fixture()
def plain_app(tmp_path: Path):
    # 缺省装配：不注入、不探测 → segment/classify 显式降级
    return create_app(data_root=tmp_path / "data", allow_probe=False)


def _upload_pair(client: httpx.Client, scan, top: Path, bottom: Path, **fields):
    files = {
        "top": ("top.png", top.read_bytes(), "image/png"),
        "bottom": ("bottom.png", bottom.read_bytes(), "image/png"),
    }
    fields.setdefault("standard", STANDARD)
    fields.setdefault("langs", "zh")
    return client.post("/api/v1/scans", files=files, data=fields)


def _wait_done(client: httpx.Client, job_id: str) -> dict:
    deadline = time.time() + POLL_TIMEOUT_S
    last: dict | None = None
    while time.time() < deadline:
        r = client.get(f"/api/v1/jobs/{job_id}")
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in ("done", "failed"):
            return last
        time.sleep(0.25)
    raise AssertionError(f"作业 {job_id} 超时未完成：{last}")


def _run_to_result(client: httpx.Client, scan, top: Path, bottom: Path, **fields) -> dict:
    r = _upload_pair(client, scan, top, bottom, **fields)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "job_id" in body
    job = _wait_done(client, body["job_id"])
    assert job["status"] == "done", f"作业失败: {job}"
    rr = client.get(f"/api/v1/results/{job['result_id']}")
    assert rr.status_code == 200, rr.text
    return rr.json()


def _qr_from_html(html: str) -> np.ndarray:
    m = re.search(r'class="qr" src="data:image/png;base64,([A-Za-z0-9+/=]+)"', html)
    assert m is not None, "护照 HTML 中未找到二维码图"
    png = base64.b64decode(m.group(1))
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    return img


# ---------------------------------------------------------------------------
# 1. 组件装配与降级
# ---------------------------------------------------------------------------


def test_default_components_degrade_explicitly():
    comps = build_components(allow_probe=False)
    assert comps.degraded_stages() == ["segment", "classify"]
    reasons = comps.degraded_reasons()
    assert reasons.get("segment") and reasons.get("classify")

    seg = comps.segment.impl
    scan = TrayScan(
        scan_id="scan_x", sample_id="s", tray_id="t",
        top_image="a.png", bottom_image="b.png", calibration=None,
        captured_at="2026-09-28T10:00:00+08:00", source="mock",
    )
    raw = seg.predict(np.zeros((8, 8, 3), dtype=np.uint8), scan)
    assert isinstance(raw, SegResult) and raw.masks == []
    SegResult.from_json(raw.to_json())  # M1 契约往返无损

    cls = comps.classify.impl
    assert cls.classify(np.zeros((4, 4, 4), dtype=np.uint8), raw.masks) == ("normal", 0.0, 0)


def test_normalize_seg_result_rewrites_side_and_ids():
    scan = TrayScan(
        scan_id="scan_x", sample_id="s", tray_id="t",
        top_image="a.png", bottom_image="b.png", calibration=None,
        captured_at="2026-09-28T10:00:00+08:00", source="mock",
    )
    seg = _ThresholdSegDouble()
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    raw = seg.predict(img, scan)
    assert raw.side == "top"
    out = normalize_seg_result(raw, side="bottom", scan_id="scan_x")
    assert out.side == "bottom" and out.scan_id == "scan_x"
    assert all(m.side == "bottom" for m in out.masks)
    assert all(m.mask_id.startswith("bottom_") for m in out.masks)
    # 已一致的输入原样返回（尊重自带 side 的实现）
    assert normalize_seg_result(out, side="bottom", scan_id="scan_x") is out


def test_injected_components_not_degraded():
    comps = build_components(
        _ThresholdSegDouble(), _GrayClsDouble(), allow_probe=False
    )
    assert comps.degraded_stages() == []
    assert "test_double" in comps.segment.resolved_version("x")
    assert "test_double" in comps.classify.resolved_version("x")


def test_reject_component_missing_protocol_method():
    from beaneye.app.components import ComponentError

    with pytest.raises(ComponentError):
        build_components(object(), None, allow_probe=False)


# ---------------------------------------------------------------------------
# 2. 演示页与基础端点
# ---------------------------------------------------------------------------


def test_demo_page_self_contained(plain_app):
    with _make_client(plain_app) as client:
        r = client.get("/demo")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    for kw in ("上传", "检测结果列表", "证据卡", "质量护照"):
        assert kw in html, f"演示页缺少区块关键词: {kw}"
    # 零外链：不允许任何 http(s) 的 src/href/@import/url() 引用
    assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', html, re.IGNORECASE)
    assert not re.search(r"url\(\s*['\"]?https?://", html, re.IGNORECASE)
    assert "@import" not in html
    # 根路径重定向到演示页
    with _make_client(plain_app) as client:
        r2 = client.get("/", follow_redirects=False)
    assert r2.status_code in (301, 302, 307)
    assert r2.headers["location"] == "/demo"


def test_health_and_standards_endpoints(plain_app):
    with _make_client(plain_app) as client:
        h = client.get("/api/v1/health")
        assert h.status_code == 200
        assert h.json()["status"] == "ok"
        assert set(h.json()["degraded_stages"]) == {"segment", "classify"}

        r = client.get("/api/v1/standards")
        assert r.status_code == 200
        body = r.json()
        ids = [s["id"] for s in body["standards"]]
        assert set(ids) == {"cqi_fine_robusta", "nyt_604", "db46_t642"}
        assert body["default"] == "cqi_fine_robusta"
        for s in body["standards"]:
            assert set(s["display"]) == {"zh", "en", "vi"}
            assert isinstance(s["grades"], list) and s["grades"]
            assert isinstance(s["verified"], bool)


# ---------------------------------------------------------------------------
# 3. 端到端：上传合成整盘 → 完整链路（注入替身）
# ---------------------------------------------------------------------------


def test_e2e_upload_full_pipeline(full_app, tmp_path: Path):
    scan, top, bottom = _mock_pair(tmp_path, n_beans=36, defect_rate=0.3, seed=20260928)
    with _make_client(full_app) as client:
        env = _run_to_result(client, scan, top, bottom, sample_id="e2e-full", langs="zh,en,vi")

        # -- 降级与版本元数据 ------------------------------------------------
        assert env["degraded"] is False, env["degraded_reasons"]
        assert env["degraded_stages"] == []
        pv = env["pipeline_versions"]
        assert "test_double" in pv["segment"] and "test_double" in pv["classify"]
        assert pv["agent"] == "template" and pv["standard"] == STANDARD

        # -- BatchResult 字段齐全 + M1 往返 -----------------------------------
        res = env["result"]
        assert set(res.keys()) >= set(BatchResult.model_fields), "BatchResult 字段缺失"
        br = BatchResult.from_json(json.dumps(res))  # 契约校验器全部重跑
        assert br.result_id == env["result_id"]
        assert env["scan"]["calibrated"] is True and env["scan"]["source"] == "usb"
        assert env["scan"]["sample_id"] == "e2e-full"

        # -- 逐粒结果与计数一致性 ---------------------------------------------
        assert len(br.beans) >= 24, f"配对粒数过少: {len(br.beans)}/36"
        defect_beans = [b for b in br.beans if b.final_defect != "normal"]
        assert len(defect_beans) >= 3, f"缺陷粒过少: {len(defect_beans)}"
        hist: dict[str, int] = {}
        for b in br.beans:
            hist[b.final_defect] = hist.get(b.final_defect, 0) + 1
        for key, n in br.grading.defect_counts.items():
            assert TAX.is_valid_key(key)
            assert hist.get(key, 0) == n
        assert br.grading.standard_id == STANDARD
        assert re.fullmatch(r"[0-9a-f]{64}", br.grading.standard_yaml_sha), "标准 YAML sha 格式非法"
        assert set(STAGE_ORDER[:8]) <= set(br.timings_s), f"阶段耗时缺失: {br.timings_s}"

        # -- 证据图端点 --------------------------------------------------------
        b0 = defect_beans[0]
        er = client.get(f"/api/v1/results/{env['result_id']}/evidence/{b0.bean_id}/top")
        assert er.status_code == 200
        assert er.headers["content-type"].startswith("image/png")
        crop = cv2.imdecode(np.frombuffer(er.content, np.uint8), cv2.IMREAD_UNCHANGED)
        assert crop is not None and crop.ndim == 3 and crop.shape[2] == 4  # RGBA 证据
        assert min(crop.shape[:2]) >= 8
        # 不存在的豆 / 不存在的面
        assert client.get(
            f"/api/v1/results/{env['result_id']}/evidence/nope/top"
        ).status_code == 404
        assert client.get(
            f"/api/v1/results/{env['result_id']}/evidence/{b0.bean_id}/left"
        ).status_code == 400

        # -- 护照：三语可下载 + QR 解码回读 ------------------------------------
        for lg in ("zh", "en", "vi"):
            pr = client.get(
                f"/api/v1/results/{env['result_id']}/passport",
                params={"lang": lg, "download": 1},
            )
            assert pr.status_code == 200, pr.text
            assert "attachment" in pr.headers["content-disposition"]
            assert len(pr.content) > 20 * 1024, f"{lg} 护照过小: {len(pr.content)}B"
        # 预览态（inline）+ 未知语言 404
        pv_r = client.get(f"/api/v1/results/{env['result_id']}/passport", params={"lang": "zh"})
        assert pv_r.status_code == 200
        assert "inline" in pv_r.headers["content-disposition"]
        bad = client.get(f"/api/v1/results/{env['result_id']}/passport", params={"lang": "xx"})
        assert bad.status_code == 404

    img = _qr_from_html(pv_r.text)
    found = zxingcpp.read_barcodes(img)
    assert found, "二维码解码失败"
    payload = found[0].text
    assert payload == env["passport"]["qr_payload"]
    rid, sha = parse_qr_payload(payload)
    assert rid == env["result_id"]
    assert sha == env["passport"]["sha256"] == canonical_sha256(br)


# ---------------------------------------------------------------------------
# 4. 端到端：缺省装配 → 显式降级（0 检出走完全链路）
# ---------------------------------------------------------------------------


def test_e2e_degraded_default_pipeline(plain_app, tmp_path: Path):
    scan, top, bottom = _mock_pair(tmp_path, n_beans=12, defect_rate=0.2, seed=7)
    with _make_client(plain_app) as client:
        env = _run_to_result(client, scan, top, bottom, langs="zh")

    assert env["degraded"] is True
    assert set(env["degraded_stages"]) == {"segment", "classify"}
    reasons = env["degraded_reasons"]
    assert "分割" in reasons.get("segment", "") and "分类" in reasons.get("classify", "")

    br = BatchResult.from_json(json.dumps(env["result"]))
    assert br.beans == [] and br.measurements.bean_count == 0  # 0 检出，诚实空盘
    assert br.grading.standard_id == STANDARD
    assert br.agent_report is not None and br.agent_report.backend == "template"
    assert "unavailable" in br.pipeline_versions["segment"]

    # 降级模式下证据图必然缺失（无任何检出）
    with _make_client(plain_app) as client:
        er = client.get(f"/api/v1/results/{env['result_id']}/evidence/b0001/top")
        assert er.status_code == 404
        # 护照仍然可下载且 QR 自洽
        pr = client.get(
            f"/api/v1/results/{env['result_id']}/passport",
            params={"lang": "zh", "download": 1},
        )
    assert pr.status_code == 200 and len(pr.content) > 20 * 1024
    img = _qr_from_html(pr.text)
    found = zxingcpp.read_barcodes(img)
    assert found and found[0].text == env["passport"]["qr_payload"]
    rid, sha = parse_qr_payload(found[0].text)
    assert rid == env["result_id"] and sha == canonical_sha256(br)


# ---------------------------------------------------------------------------
# 5. 端到端：JSON 合成请求 → 内置模拟源兜底
# ---------------------------------------------------------------------------


def test_e2e_synth_json_falls_back_to_mock(plain_app, tmp_path: Path):
    body = {
        "synth": {"n_beans": 24, "defect_rate": 0.2, "seed": 5, "width": 1024, "height": 1024},
        "sample_id": "e2e-synth",
        "langs": "zh",
    }
    with _make_client(plain_app) as client:
        r = client.post("/api/v1/scans", json=body)
        assert r.status_code == 200, r.text
        submit = r.json()
        assert "synth" in submit["degraded_reasons"]
        assert "模拟源" in submit["degraded_reasons"]["synth"]
        job = _wait_done(client, submit["job_id"])
        assert job["status"] == "done", job
        rr = client.get(f"/api/v1/results/{job['result_id']}")
        assert rr.status_code == 200
        env = rr.json()

    assert env["scan"]["source"] == "mock"
    assert env["scan"]["sample_id"] == "e2e-synth"
    assert "synth" in env["degraded_stages"]
    br = BatchResult.from_json(json.dumps(env["result"]))
    assert br.beans == [] and br.measurements.bean_count == 0
    assert br.result_id == env["result_id"]


# ---------------------------------------------------------------------------
# 6. 请求校验 / 404 / 失败路径
# ---------------------------------------------------------------------------


def test_upload_validation_errors(plain_app, tmp_path: Path):
    scan, top, bottom = _mock_pair(tmp_path, n_beans=4, defect_rate=0.0, seed=3)
    with _make_client(plain_app) as client:
        # 缺一面
        r = client.post(
            "/api/v1/scans",
            files={"top": ("top.png", top.read_bytes(), "image/png")},
            data={"standard": STANDARD},
        )
        assert r.status_code == 400
        # 坏图（非图像字节）
        r = client.post(
            "/api/v1/scans",
            files={
                "top": ("top.png", b"not-an-image", "image/png"),
                "bottom": ("bottom.png", bottom.read_bytes(), "image/png"),
            },
        )
        assert r.status_code == 400
        # 未知标准
        r = _upload_pair(client, scan, top, bottom, standard="nope")
        assert r.status_code == 400 and "nope" in r.json()["error"]
        # 未知语言
        r = _upload_pair(client, scan, top, bottom, langs="xx")
        assert r.status_code == 400
        # 非法 Content-Type
        r = client.post("/api/v1/scans", content=b"x", headers={"Content-Type": "text/plain"})
        assert r.status_code == 400
        # 非法 JSON
        r = client.post(
            "/api/v1/scans", json={"nosynth": {}}, headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 400
        # synth 参数越界
        r = client.post("/api/v1/scans", json={"synth": {"n_beans": 10**6}})
        assert r.status_code == 400


def test_unknown_ids_404(plain_app):
    with _make_client(plain_app) as client:
        assert client.get("/api/v1/jobs/does-not-exist").status_code == 404
        assert client.get("/api/v1/results/does-not-exist").status_code == 404
        assert client.get(
            "/api/v1/results/does-not-exist/passport", params={"lang": "zh"}
        ).status_code == 404
        assert client.get(
            "/api/v1/results/does-not-exist/evidence/b0001/top"
        ).status_code == 404


def test_job_fails_without_markers(plain_app, tmp_path: Path):
    rng = np.random.default_rng(11)
    noise = rng.integers(0, 255, size=(512, 512, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", noise)
    assert ok
    png = buf.tobytes()
    with _make_client(plain_app) as client:
        r = client.post(
            "/api/v1/scans",
            files={
                "top": ("top.png", png, "image/png"),
                "bottom": ("bottom.png", png, "image/png"),
            },
            data={"standard": STANDARD, "langs": "zh"},
        )
        assert r.status_code == 200
        job = _wait_done(client, r.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error_stage"] == "calibration"
    assert "定位码" in (job["error"] or "")


def test_results_list_summary(plain_app, tmp_path: Path):
    scan, top, bottom = _mock_pair(tmp_path, n_beans=8, defect_rate=0.1, seed=21)
    with _make_client(plain_app) as client:
        env = _run_to_result(client, scan, top, bottom, langs="zh")
        rl = client.get("/api/v1/results")
    assert rl.status_code == 200
    rows = rl.json()["results"]
    assert len(rows) >= 1
    row = next(x for x in rows if x["result_id"] == env["result_id"])
    for key in (
        "result_id", "sample_id", "standard_id", "grade", "passed", "bean_count",
        "primary_count", "secondary_count", "defect_counts", "degraded",
        "degraded_stages", "has_passport", "created_at",
    ):
        assert key in row
    assert row["degraded"] is True and row["has_passport"] is True


# ---------------------------------------------------------------------------
# 7. 管线直调（不经 HTTP）：outcome 元数据
# ---------------------------------------------------------------------------


def test_run_pipeline_outcome_metadata(tmp_path: Path):
    scan, top, bottom = _mock_pair(tmp_path, n_beans=10, defect_rate=0.2, seed=99)
    comps = build_components(_ThresholdSegDouble(), _GrayClsDouble(), allow_probe=False)
    req = PipelineRequest(
        scan=scan, top_path=top, bottom_path=bottom,
        standard_id=STANDARD, langs=["zh"], data_root=tmp_path / "data",
    )
    outcome = run_pipeline(req, comps)
    assert outcome.degraded_stages == []
    assert outcome.pairing_summary["paired"] >= 6
    assert outcome.passport is not None
    assert outcome.passport_runtime_s > 0
    assert set(STAGE_ORDER[:8]) <= set(outcome.result.timings_s)
    defect = [b for b in outcome.result.beans if b.final_defect != "normal"]
    if defect:
        crop = tmp_path / "data" / defect[0].top.crop_path
        assert crop.is_file()
