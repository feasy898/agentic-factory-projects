"""webui.app —— 最小操作界面（M10，FastAPI + 单页，零外链）。

流程：浏览器单页（webui/static/index.html，无任何外部资源引用）→
选模板 / 传 PNG 素材 / 填文案（或直接传 spec JSON）→ POST /api/build 组装
PlayableSpec（specgen）→ 后台线程调 ``python -m pfcore make``（真实流水线：
校验→模板构建→打包→qacore 自动试玩质检）→ 状态轮询 → 二维码 + 质检报告链接。

设计纪律（与 pfcore.make 同一套）：
- 零外链：页面自包含；产物链接全部指向本伺服的 /artifacts/... 相对路径。
- 防 SSRF：本服务不发起任何 HTTP 请求（landingUrl 只做 http/https 格式校验，
  从不访问；二维码为 qrcode 库本地生成；LAN 地址探测复用 pfcore.make._lan_ip）。
- 质检是裁判：qacore 有 fail 时 pfcore make 不产出 demo-prebuilt，任务如实记失败。
- 无登录、仅 LAN（uvicorn 绑 0.0.0.0）；任务串行（信号量）避免质检资源互踩。

用法：python -m webui.app [--port 8788] [--host 0.0.0.0]
自验收：python -m webui.selftest
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pfcore.make import _lan_ip
from pfcore.validation import validate_spec_dict

from . import specgen

REPO_ROOT = Path(__file__).resolve().parents[1]
JOBS_ROOT = REPO_ROOT / "artifacts" / "webui"
STATIC_DIR = Path(__file__).resolve().parent / "static"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_SPEC_BYTES = 256 * 1024
MAX_PNG_BYTES = 5 * 1024 * 1024
MAX_PNG_FILES = 12
JOB_TIMEOUT_SEC = 900
LOG_TAIL_LINES = 40

STATE = {"host": "127.0.0.1", "port": 8788}
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAKE_SEM = threading.Semaphore(1)  # make 含无头浏览器质检，串行防资源互踩

app = FastAPI(title="pf-webui", docs_url=None, redoc_url=None, openapi_url=None)
JOBS_ROOT.mkdir(parents=True, exist_ok=True)
# 挂载点 = JOBS_ROOT 本身（任务链接 /artifacts/webui/<id>/... 的剩余路径正对上
# <JOBS_ROOT>/<id>/...；挂到 /artifacts 会多出一层 webui 造成 404）。
app.mount("/artifacts/webui", StaticFiles(directory=str(JOBS_ROOT)), name="artifacts")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _persist(job: dict) -> None:
    try:
        (job_root(job["id"]) / "job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def job_root(job_id: str) -> Path:
    return JOBS_ROOT / job_id


def _tail(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-LOG_TAIL_LINES:])


# ---------------------------------------------------------------- 素材落盘

def _save_uploads(files: list[UploadFile], dst_dir: Path,
                  slot_order: list[str], notes: list[str],
                  known_keys: set[str] | None = None) -> dict[str, str]:
    """校验并把上传 PNG 写入 dst_dir/<槽位>.png；返回 {槽位键: 相对 spec 的路径}。

    槽位匹配：文件名主干命中 slot_order（或 known_keys）用主干；否则按
    slot_order 顺延取下一个空槽。known_keys 非空时（spec 上传模式）主干不
    在 known_keys 的文件忽略并记 note。非法类型/超限抛 HTTPException(400)。
    """
    if len(files) > MAX_PNG_FILES:
        raise HTTPException(400, detail=f"素材文件最多 {MAX_PNG_FILES} 个")
    written: dict[str, str] = {}
    used = set(known_keys or ())
    for f in files:
        raw_name = Path(f.filename or "").name
        stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in Path(raw_name).stem.lower())
        ext = Path(raw_name).suffix.lower()
        data = f.file.read(MAX_PNG_BYTES + 1)
        if len(data) > MAX_PNG_BYTES:
            raise HTTPException(400, detail=f"素材超 5MB 上限：{raw_name}")
        if ext != ".png":
            raise HTTPException(400, detail=f"仅接受 PNG 素材，得到 {ext or '(无扩展名)'}：{raw_name}")
        if not data.startswith(PNG_MAGIC):
            raise HTTPException(400, detail=f"不是合法 PNG（魔数不符）：{raw_name}")
        slot = stem if stem in slot_order and stem not in used else next(
            (s for s in slot_order if s not in used), None)
        if slot is None:
            if known_keys is not None and stem not in known_keys:
                notes.append(f"素材 {raw_name} 的键 {stem!r} 不在 spec.sprites 中，已忽略")
                continue
            notes.append(f"素材 {raw_name} 无可用槽位，已忽略（模板槽位：{', '.join(slot_order)}）")
            continue
        used.add(slot)
        dst = dst_dir / f"{slot}.png"
        dst.write_bytes(data)
        written[slot] = f"assets/{slot}.png"
        if stem != slot:
            notes.append(f"素材 {raw_name} → 槽位 {slot}")
    return written


# ---------------------------------------------------------------- 任务执行

def _start_make(job: dict) -> None:
    spec_path = job_root(job["id"]) / "spec.json"
    cmd = [sys.executable, "-m", "pfcore", "make",
           "--spec", str(spec_path),
           "--locales", job["locale"],
           "--channels", ",".join(job["channels"]),
           "--out", str(job_root(job["id"]) / "out"),
           "--no-serve"]  # 不另起静态伺服：产物统一由本服务 /artifacts 挂载伺服
    job["status"] = "running"
    job["startedAt"] = _now()
    _persist(job)
    try:
        with MAKE_SEM:
            proc = subprocess.run(
                cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=JOB_TIMEOUT_SEC)
        job["logTail"] = _tail(proc.stdout + "\n" + proc.stderr)
        if proc.returncode != 0:
            job["status"] = "failed"
            job["error"] = f"pfcore make exit {proc.returncode}（质检是裁判：任何 fail 都不产出产物）"
            return
        job.update(_collect_result(job))
        job["status"] = "done"
    except subprocess.TimeoutExpired:
        job["status"] = "failed"
        job["error"] = f"pfcore make 超时（>{JOB_TIMEOUT_SEC}s）"
    except Exception as exc:  # 收集/二维码任何意外：如实失败，不假绿
        job["status"] = "failed"
        job["error"] = f"任务收尾异常：{exc!r}"
    finally:
        job["finishedAt"] = _now()
        _persist(job)


def _collect_result(job: dict) -> dict:
    """make 成功后解析 pipeline-report，重出二维码（指向本服务的 LAN URL），组链接。"""
    demo = job_root(job["id"]) / "out" / "demo-prebuilt"
    pipeline = json.loads((demo / "pipeline-report.json").read_text(encoding="utf-8"))
    preview_rel = f"preview/{Path(pipeline['preview']['html']).name}"
    qa = pipeline.get("qa") or {}

    base_path = f"/artifacts/webui/{job['id']}/out/demo-prebuilt"
    port = int(STATE["port"])
    host = _lan_ip()
    scan_url = f"http://{host}:{port}{base_path}/{preview_rel}" if port != 80 \
        else f"http://{host}{base_path}/{preview_rel}"
    import qrcode  # 延迟导入（同 make 纪律）

    qr = qrcode.QRCode(border=2, box_size=6,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(scan_url)
    qr.make(fit=True)
    # make 以 --no-serve 运行，其 qr.png 指向占位端口；这里以本服务的 LAN 可达
    # URL 覆写（汇总页相对引用同名文件，保持一致）。
    qr.make_image(fill_color="black", back_color="white").save(str(demo / "qr.png"))

    counts = {"pass": 0, "fail": 0, "skip": 0}
    for c in qa.get("checks") or []:
        counts[c.get("status", "")] = counts.get(c.get("status", ""), 0) + 1
    pf = qa.get("pf") or {}
    return {
        "projectId": job["projectId"],
        "wallSec": round(float((pipeline.get("timings") or {}).get("makeWallSec") or 0), 1),
        "links": {
            "summary": f"{base_path}/index.html",
            "preview": f"{base_path}/{preview_rel}",
            "qr": f"/api/jobs/{job['id']}/qr.png",
            "report": f"{base_path}/{qa.get('report_rel', 'pipeline-report.json')}",
            "pipeline": f"{base_path}/pipeline-report.json",
        },
        "scanUrl": scan_url,
        "packages": [
            {"channel": p["channel"], "locale": p["locale"], "format": p["format"],
             "bytes": p["bytes"], "maxBytes": p["maxBytes"], "href": f"{base_path}/{p['rel']}"}
            for p in pipeline.get("packages") or []
        ],
        "qa": {
            "channel": qa.get("channel"), "loadMs": qa.get("loadMs"),
            "pass": counts["pass"], "fail": counts["fail"], "skip": counts["skip"],
            "endMs": pf.get("endMs"), "endWin": pf.get("endWin"), "readyMs": pf.get("readyMs"),
        },
    }


# ---------------------------------------------------------------- 路由

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "time": _now()}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "templates": [{"id": t, "label": specgen.TEMPLATE_LABELS[t],
                       "spriteSlots": specgen.SPRITE_SLOTS[t]} for t in specgen.TEMPLATES],
        "locales": list(specgen.LOCALES),
        "defaults": specgen.defaults_table(),
        "channels": specgen.DEFAULT_CHANNELS,
        "landingUrlDefault": specgen.DEFAULT_LANDING_URL,
    }


@app.get("/api/jobs")
def jobs_list() -> list[dict]:
    with JOBS_LOCK:
        items = sorted(JOBS.values(), key=lambda j: j.get("createdAt", ""), reverse=True)
        return [{"id": j["id"], "status": j["status"], "mode": j["mode"],
                 "projectId": j.get("projectId"), "locale": j.get("locale"),
                 "createdAt": j.get("createdAt"), "finishedAt": j.get("finishedAt")}
                for j in items]


@app.get("/api/jobs/{job_id}")
def jobs_get(job_id: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, detail=f"任务不存在：{job_id}")
        return dict(job)


@app.get("/api/jobs/{job_id}/qr.png")
def jobs_qr(job_id: str) -> FileResponse:
    qr = job_root(job_id) / "out" / "demo-prebuilt" / "qr.png"
    if not qr.is_file():
        raise HTTPException(404, detail="二维码尚未产出（任务未完成或质检未过）")
    return FileResponse(qr, media_type="image/png")


@app.post("/api/build")
async def api_build(
    spec: UploadFile | None = File(None),
    assets: list[UploadFile] | None = File(None),
    template: str = Form("match3"),
    project_id: str = Form(""),
    title: str = Form(""),
    locale: str = Form("zh"),
    seed: str = Form(""),
    landing_url: str = Form(""),
    near_win: bool = Form(True),
    cta: str = Form(""),
    tutorial: str = Form(""),
    win: str = Form(""),
    lose: str = Form(""),
    score: str = Form(""),
) -> JSONResponse:
    """两条入路：上传 spec JSON（assets 同键覆盖）或纯表单组装 spec。"""
    uploads = list(assets or [])
    notes: list[str] = []
    job_id = secrets.token_hex(6)
    root = job_root(job_id)
    (root / "assets").mkdir(parents=True, exist_ok=True)

    if spec is not None and (spec.filename or "").strip():
        # ---- 模式 A：上传 spec JSON ------------------------------------
        raw = await spec.read(MAX_SPEC_BYTES + 1)
        if len(raw) > MAX_SPEC_BYTES:
            raise HTTPException(400, detail=f"spec 文件超 {MAX_SPEC_BYTES // 1024}KB 上限")
        try:
            spec_dict = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(400, detail=f"spec JSON 解析失败：{exc}") from exc
        issues = validate_spec_dict(spec_dict)
        if issues:
            raise HTTPException(400, detail={"errors": [i.render() for i in issues]})
        written = _save_uploads(
            uploads, root / "assets",
            slot_order=sorted((spec_dict.get("assets") or {}).get("sprites") or {}),
            notes=notes, known_keys=set((spec_dict.get("assets") or {}).get("sprites") or {}))
        for slot, rel in written.items():
            spec_dict["assets"]["sprites"][slot] = rel
        mode = "spec"
        channels = [c for c in (spec_dict.get("channels") or {}).get("targets") or []
                    if c != "preview"] or list(specgen.DEFAULT_CHANNELS)
        template_id = str((spec_dict.get("game") or {}).get("template") or "")
        job_core = {
            "projectId": str((spec_dict.get("meta") or {}).get("projectId") or "playable"),
            "locale": str((spec_dict.get("i18n") or {}).get("defaultLocale") or "en"),
            "seed": (spec_dict.get("meta") or {}).get("seed"),
        }
    else:
        # ---- 模式 B：表单组装 spec -------------------------------------
        try:
            seed_val = int(seed.strip()) if seed.strip() else None
        except ValueError:
            raise HTTPException(400, detail=f"seed 须为非负整数：{seed!r}") from None
        slots = _save_uploads(uploads, root / "assets",
                              slot_order=specgen.SPRITE_SLOTS.get(template,
                                                                  specgen.SPRITE_SLOTS["match3"]),
                              notes=notes)
        try:
            spec_dict = specgen.assemble_spec(
                template, project_id=project_id, title=title, locale=locale,
                texts={"cta": cta, "tutorial": tutorial, "win": win, "lose": lose, "score": score},
                seed=seed_val, landing_url=landing_url, near_win=near_win, sprite_slots=slots)
        except specgen.SpecBuildError as exc:
            raise HTTPException(400, detail={"errors": exc.messages}) from exc
        issues = validate_spec_dict(spec_dict)  # 组装后仍过一遍权威校验（双保险）
        if issues:
            raise HTTPException(400, detail={"errors": [i.render() for i in issues]})
        mode = "form"
        channels = list(specgen.DEFAULT_CHANNELS)
        template_id = template
        job_core = {"projectId": spec_dict["meta"]["projectId"],
                    "locale": locale, "seed": spec_dict["meta"]["seed"]}

    (root / "spec.json").write_text(
        json.dumps(spec_dict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    job: dict = {
        "id": job_id, "status": "queued", "mode": mode,
        "template": template_id, "channels": channels,
        "createdAt": _now(), "notes": notes, "error": None,
        "logTail": "", "links": None, "packages": [], "qa": None,
        **job_core,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
    _persist(job)
    threading.Thread(target=_start_make, args=(job,), daemon=True,
                     name=f"make-{job_id}").start()
    return JSONResponse({"id": job_id, "status": "queued"}, status_code=200)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="webui.app", description="试玩广告工厂最小操作界面（M10）：上传 → make → 二维码+质检报告")
    parser.add_argument("--port", type=int, default=8788, help="伺服端口（默认 8788）")
    parser.add_argument("--host", default="0.0.0.0",
                         help="绑定地址（默认 0.0.0.0，局域网手机可扫二维码）")
    args = parser.parse_args(argv)
    STATE["host"], STATE["port"] = args.host, args.port
    print(f"[webui] http://{args.host}:{args.port}/ （任务产物 /artifacts/webui/<id>/…）", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
