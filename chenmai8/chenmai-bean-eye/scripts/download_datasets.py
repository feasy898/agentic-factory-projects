#!/usr/bin/env python3
"""BeanEye 数据集下载器（W0c）。

主源 DCV（Roboflow Universe 上的咖啡生豆缺陷分割数据集，coco-segmentation 格式，
4038 图 / 12 类多边形掩码，CC BY 4.0）：下载需要免费账号的 Roboflow API key，
通过 --key 参数（或环境变量 ROBOFLOW_API_KEY / BEANEYE_ROBOFLOW_API_KEY）注入，
key 永不写入日志与错误信息（统一脱敏）。

实现说明：不使用 roboflow pip 包（其依赖 opencv-python-headless 会覆盖本仓钉版的
opencv-python==4.10.0.84）；本脚本按 roboflow==1.5.1（Apache-2.0）的私有 REST 协议
用已钉版的 httpx 直连：
    GET {api}/{workspace}/{project}                          -> 项目信息 + versions
    GET {api}/{workspace}/{project}/{ver}?nocache=true       -> 版本生成状态
    GET {api}/{workspace}/{project}/{ver}/{format}?nocache=true
        -> 202 {"progress": x}（导出生成中，轮询）
        -> 200 {"export": {"link": <签名 zip 直链>, ...}}
    GET <link>                                               -> 流式下载 zip（无需 key）

目录规范（开发指令 §6）：
    data/datasets/dcv/                 主源（content/ 为导出内容，_downloads/ 为原始 zip）
    data/datasets/dcv_sample/          小样本（--sample N，先验证用）
    data/datasets/usk_coffee/          辅源（人工表单获取后用 --usk-archive 登记入库）
每个数据集目录含 SHA256SUMS（`sha256sum -c` 可校验）与 manifest.json（来源/版本/
许可证/统计）。人工解锁步骤见 data/datasets/README.md。

用法（仓库根目录执行）：
    .venv/Scripts/python.exe scripts/download_datasets.py --only dcv --key <RF_KEY>
    .venv/Scripts/python.exe scripts/download_datasets.py --only dcv              # 无 key -> 打印解锁步骤
    .venv/Scripts/python.exe scripts/download_datasets.py --only dcv --key K --sample 50   # 小样本
    .venv/Scripts/python.exe scripts/download_datasets.py --only dcv --key K --dry-run     # 只解析不落盘
    .venv/Scripts/python.exe scripts/download_datasets.py --only usk --usk-archive <zip路径或URL>
    .venv/Scripts/python.exe scripts/download_datasets.py --only usk              # 打印人工表单步骤
    .venv/Scripts/python.exe scripts/download_datasets.py --selftest              # 本机自检（含真实网络探针）

退出码：0 成功；1 运行失败；2 用法错误；3 需要人工步骤（缺 key / 缺 USK 包）。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import httpx

# 输出统一 UTF-8（Windows 被重定向时默认跟随 GBK 代码页会乱码，与 doctor.py 同法）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = ROOT / "data" / "datasets"

API_URL = "https://api.roboflow.com"
# 上游坐标（仅内部使用；公开仓库按 D-3 走中性名，见 plan/开发指令.md §10）
DCV_WORKSPACE = "redtraining"
DCV_PROJECT = "defectoscafeverde"
DCV_UNIVERSE_URL = f"https://universe.roboflow.com/{DCV_WORKSPACE}/{DCV_PROJECT}"
DCV_LICENSE = "CC BY 4.0（以导出包/项目页实际声明为准；使用须署名）"
DCV_FORMAT = "coco-segmentation"

USK_FORM_URL = "https://forms.gle/4QSchCETdWrWrtfA8"

READ_CHUNK = 1 << 20  # 1 MiB
POLL_INTERVAL_S = 3
TOOL_ID = "scripts/download_datasets.py v1"

# key 传递方式在 header 与 query 间自动回退后记忆（首次 401 时各试一次）
_AUTH_USE_QUERY = False


class BlockedError(Exception):
    """需要人工步骤（缺 API key / 缺 USK 包）——对应退出码 3。"""


class RoboflowAPIError(Exception):
    """Roboflow REST 调用失败，status 为 HTTP 状态码。"""

    def __init__(self, status: int, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.hint = hint


class ExtractError(Exception):
    """zip 解包安全检查未通过（路径穿越/符号链接/超限）。"""


def redact(text: str, key: str | None) -> str:
    """任何输出前过一遍：日志与异常文本中不得出现 key。"""
    if key and key in text:
        return text.replace(key, "***REDACTED***")
    return text


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- HTTP 基础

def _handle_status(status: int, body: str) -> None:
    """非 200/202 的统一错误分类（friendly hint 指向 README）。"""
    snippet = body[:300] if body else "(无响应体)"
    if status == 401:
        raise RoboflowAPIError(
            status,
            f"Roboflow 拒绝了 API key（401）：{snippet}",
            "key 无效或未生效。注册/取 key 步骤见 data/datasets/README.md（Settings → Roboflow API Keys，"
            "取 Private API Key），或检查 --key 是否多复制了空格。",
        )
    if status == 403:
        raise RoboflowAPIError(
            status,
            f"Roboflow 拒绝访问（403）：{snippet}",
            "无权访问该 workspace/project。核对 --workspace/--project 拼写，并确认账号可打开该数据集页面。",
        )
    if status == 404:
        raise RoboflowAPIError(
            status,
            f"项目或版本不存在（404）：{snippet}",
            "核对 --workspace/--project/--version；可用 --list-versions 列出可用版本。",
        )
    if status == 429:
        raise RoboflowAPIError(
            status,
            f"Roboflow 限流（429）：{snippet}",
            "稍后重试；免费账号有请求频率与导出并发限制。",
        )
    raise RoboflowAPIError(status, f"Roboflow API 返回 {status}：{snippet}")


def api_get_json(client: httpx.Client, url: str, key: str) -> tuple[int, dict]:
    """GET 并解析 JSON；认证优先 Bearer header（key 不进 URL），401 时回退 query 一次。

    返回 (status_code, payload)；非 200/202 抛 RoboflowAPIError。
    """
    global _AUTH_USE_QUERY
    header = {"Authorization": f"Bearer {key}"}
    if _AUTH_USE_QUERY:
        r = client.get(url, params={"api_key": key}, headers=header)
        if r.status_code == 401:
            r = client.get(url, headers=header)
            if r.status_code != 401:
                _AUTH_USE_QUERY = False
    else:
        r = client.get(url, headers=header)
        if r.status_code == 401:
            r = client.get(url, params={"api_key": key})
            if r.status_code == 200 or r.status_code == 202:
                _AUTH_USE_QUERY = True
    if r.status_code not in (200, 202):
        _handle_status(r.status_code, r.text)
    try:
        payload = r.json()
    except Exception as exc:  # 200/202 但非 JSON
        raise RoboflowAPIError(r.status_code, f"响应不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise RoboflowAPIError(r.status_code, f"响应 JSON 不是对象：{str(payload)[:200]}")
    return r.status_code, payload


def api_get_json_probe(client: httpx.Client, url: str, key: str) -> tuple[int, dict]:
    """与 api_get_json 相同，但显式使用调用点的全局认证模式（供 selftest 复用）。"""
    return api_get_json(client, url, key)


# ---------------------------------------------------------------- Roboflow 流程

def get_project(client: httpx.Client, ws: str, proj: str, key: str) -> dict:
    _, payload = api_get_json(client, f"{API_URL}/{ws}/{proj}", key)
    return payload


def resolve_version(project_payload: dict, version_arg: str) -> int:
    """'latest' 取 versions 里数值最大的 id；数字字符串直接用。"""
    versions = project_payload.get("versions") or []
    if version_arg.lower() in ("latest", "newest"):
        ids = []
        for v in versions:
            try:
                ids.append(int(v.get("id")))
            except (TypeError, ValueError):
                continue
        if not ids:
            raise RoboflowAPIError(200, "项目响应中没有可解析的版本列表（versions 为空）")
        return max(ids)
    try:
        return int(version_arg)
    except ValueError as exc:
        raise SystemExit(f"[用法] --version 需要整数或 'latest'，收到 {version_arg!r}") from exc


def wait_version_ready(
    client: httpx.Client, ws: str, proj: str, version: int, key: str, wait_s: float
) -> dict:
    """等待数据集版本本身处于可用状态（导出大版本时版本可能仍在生成）。"""
    url = f"{API_URL}/{ws}/{proj}/{version}?nocache=true"
    deadline = time.monotonic() + wait_s
    while True:
        _, payload = api_get_json(client, url, key)
        vobj = payload.get("version") or {}
        generating = bool(vobj.get("generating")) or int(vobj.get("images") or 0) == 0
        if not generating:
            return vobj
        progress = float(vobj.get("progress") or 0.0) * 100
        print(f"\r[DCV] 版本 v{version} 生成中 {progress:5.1f}%", end="", flush=True)
        if time.monotonic() > deadline:
            raise RoboflowAPIError(
                200,
                f"等待版本 v{version} 生成超时（>{wait_s:.0f}s）",
                "稍后重跑同一命令即可；导出未完成时 Roboflow 不会给出下载链。",
            )
        time.sleep(POLL_INTERVAL_S)


def poll_export_link(
    client: httpx.Client,
    ws: str,
    proj: str,
    version: int,
    fmt: str,
    key: str,
    wait_s: float,
) -> tuple[str, dict]:
    """触发/轮询 coco-segmentation 导出，直到拿到签名下载直链。"""
    url = f"{API_URL}/{ws}/{proj}/{version}/{fmt}?nocache=true"
    deadline = time.monotonic() + wait_s
    while True:
        status, payload = api_get_json(client, url, key)
        if status == 200:
            export = payload.get("export")
            if isinstance(export, dict) and export.get("link"):
                return str(export["link"]), export
            if payload.get("ready") is False or isinstance(export, dict):
                progress = float(payload.get("progress") or 0.0) * 100
                print(f"\r[DCV] {fmt} 导出生成中 {progress:5.1f}%", end="", flush=True)
            else:
                raise RoboflowAPIError(
                    200,
                    f"导出响应缺少 export.link 字段，键={sorted(payload.keys())[:8]}",
                    "协议可能已变更；请把该输出发给规划 agent 更新下载器。",
                )
        else:  # 202：导出生成中
            progress = float(payload.get("progress") or 0.0) * 100
            print(f"\r[DCV] {fmt} 导出生成中 {progress:5.1f}%", end="", flush=True)
        if time.monotonic() > deadline:
            raise RoboflowAPIError(
                200,
                f"等待 {fmt} 导出完成超时（>{wait_s:.0f}s）",
                "首次生成 4038 图导出可能需几分钟到十几分钟；稍后重跑同一命令会复用已生成的导出。",
            )
        time.sleep(POLL_INTERVAL_S)


# ---------------------------------------------------------------- 下载 / 解包 / 校验

def stream_to_file(client: httpx.Client, url: str, dest: Path, max_bytes: int, label: str) -> str:
    """流式下载到 dest（.part 暂存、成功后改名），边下边算 sha256。返回 sha256 hex。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    sha = hashlib.sha256()
    done = 0
    last_print = 0.0
    if url.startswith("file://"):
        raw_path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
        # Windows: file:///C:/... 的 path 是 /C:/...，需去掉前导斜杠
        if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        src = Path(raw_path)
        with src.open("rb") as fsrc, part.open("wb") as fdst:
            while True:
                chunk = fsrc.read(READ_CHUNK)
                if not chunk:
                    break
                done += len(chunk)
                if done > max_bytes:
                    part.unlink(missing_ok=True)
                    raise ExtractError(f"{label} 超过大小上限 {max_bytes} 字节")
                sha.update(chunk)
                fdst.write(chunk)
    else:
        with client.stream("GET", url) as r:
            if r.status_code != 200:
                _handle_status(r.status_code, r.read().decode("utf-8", "replace")[:300])
            total = int(r.headers.get("content-length") or 0)
            with part.open("wb") as f:
                for chunk in r.iter_bytes(READ_CHUNK):
                    done += len(chunk)
                    if done > max_bytes:
                        f.close()
                        part.unlink(missing_ok=True)
                        raise ExtractError(f"{label} 超过大小上限 {max_bytes} 字节")
                    sha.update(chunk)
                    f.write(chunk)
                    now = time.monotonic()
                    if now - last_print > 1.0:
                        last_print = now
                        if total:
                            print(
                                f"\r[{label}] 下载中 {done / (1 << 20):8.1f}/{total / (1 << 20):8.1f} MiB"
                                f" ({done * 100 // max(total, 1):3d}%)",
                                end="",
                                flush=True,
                            )
                        else:
                            print(f"\r[{label}] 已下载 {done / (1 << 20):8.1f} MiB", end="", flush=True)
    print(f"\r[{label}] 下载完成 {done / (1 << 20):8.1f} MiB          ")
    part.replace(dest)
    return sha.hexdigest()


def safe_extract_zip(zip_path: Path, dest: Path, max_total_bytes: int) -> list[Path]:
    """安全解包：拒绝路径穿越/绝对路径/盘符/符号链接，累计解压体积限幅。返回解出的文件列表。"""
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            p = PurePosixPath(name.replace("\\", "/"))
            if p.is_absolute() or (len(name) > 1 and name[1] == ":") or ".." in p.parts:
                raise ExtractError(f"zip 内含不安全路径，拒绝解包: {name!r}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:  # 符号链接
                raise ExtractError(f"zip 内含符号链接，拒绝解包: {name!r}")
            if info.is_dir():
                (dest / p).mkdir(parents=True, exist_ok=True)
                continue
            total += info.file_size
            if total > max_total_bytes:
                raise ExtractError(f"zip 累计解压体积超限 {max_total_bytes} 字节（疑似 zip 炸弹）")
            target = dest / p
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as fsrc, target.open("wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
            extracted.append(target)
    return extracted


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_coco_segmentation(content_dir: Path) -> dict:
    """校验 coco-segmentation 导出结构：各 split 的 _annotations.coco.json 可解析、
    图片文件在磁盘存在、多边形标注统计。返回摘要 dict（含 missing 样例）。"""
    summary: dict = {"annotation_files": 0, "splits": {}, "categories": [], "problems": []}
    ann_files = sorted(content_dir.rglob("_annotations.coco.json"))
    if not ann_files:
        raise ExtractError(f"未找到任何 _annotations.coco.json（{content_dir}）")
    for ann_path in ann_files:
        split = ann_path.parent.name or "."
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        for required in ("images", "annotations", "categories"):
            if required not in data:
                raise ExtractError(f"{ann_path} 缺少 COCO 必需字段 {required}")
        images = data["images"]
        anns = data["annotations"]
        cats = [c.get("name", str(c.get("id"))) for c in data["categories"]]
        if not summary["categories"]:
            summary["categories"] = sorted(cats)
        # 图片文件存在性（全量核对；缺失只记样例）
        missing = []
        for img in images:
            fn = img.get("file_name", "")
            hit = any((ann_path.parent / cand).is_file() for cand in (fn, Path(fn).name))
            if not hit:
                missing.append(fn)
        poly = 0
        for ann in anns:
            seg = ann.get("segmentation")
            if (
                isinstance(seg, list)
                and seg
                and isinstance(seg[0], list)
                and len(seg[0]) >= 6
                and len(seg[0]) % 2 == 0
            ):
                poly += 1
        summary["annotation_files"] += 1
        summary["splits"][split] = {
            "images": len(images),
            "missing_images": len(missing),
            "annotations": len(anns),
            "polygon_annotations": poly,
        }
        if missing:
            summary["problems"].append(
                f"{ann_path}: {len(missing)} 张图片文件缺失，样例: {missing[:3]}"
            )
    return summary


def write_sha256sums(base: Path, rel_paths: list[str]) -> Path:
    """写 sha256sum -c 兼容清单（LF、正斜杠、相对 base 排序）。返回清单路径。

    注意：SHA256SUMS 不包含自身条目（文件无法包含自身哈希）；
    manifest.json 先于清单写出，因此可被纳入校验。
    """
    lines = []
    for rel in sorted(rel_paths):
        lines.append(f"{sha256_file(base / rel)}  {rel}")
    out = base / "SHA256SUMS"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return out


def write_manifest(base: Path, meta: dict, rel_paths: list[str]) -> Path:
    meta = {"tool": TOOL_ID, "written_at_utc": now_iso_utc(), **meta}
    out = base / "manifest.json"
    out.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_sha256sums(base, rel_paths + ["manifest.json"])
    return out


def archive_and_extract(
    client: httpx.Client,
    link: str,
    out_dir: Path,
    archive_name: str,
    max_bytes: int,
    label: str,
    reuse_sha: str | None,
) -> tuple[Path, str]:
    """下载（或复用已验过的）zip 并安全解包到 out_dir/content/。返回 (archive_path, sha256)。"""
    archive_path = out_dir / "_downloads" / archive_name
    sha = reuse_sha
    if archive_path.is_file() and reuse_sha:
        actual = sha256_file(archive_path)
        if actual == reuse_sha:
            print(f"[{label}] 复用已下载且校验通过的归档: {archive_path}")
        else:
            print(f"[{label}] 归档 sha256 与 manifest 不符，重新下载")
            sha = None
    if sha is None:
        sha = stream_to_file(client, link, archive_path, max_bytes, label)
    safe_extract_zip(archive_path, out_dir / "content", max_bytes)
    return archive_path, sha


def collect_rel_paths(base: Path) -> list[str]:
    rels = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.name not in ("SHA256SUMS", "manifest.json"):
            rels.append(p.relative_to(base).as_posix())
    return rels


# ---------------------------------------------------------------- 各数据集入口

def require_key(args) -> str:
    key = args.key or os.environ.get("ROBOFLOW_API_KEY") or os.environ.get("BEANEYE_ROBOFLOW_API_KEY")
    if not key:
        raise BlockedError(
            "DCV 下载需要 Roboflow API key（本机未配置）。\n"
            "  解锁三步（详见 data/datasets/README.md）：\n"
            "    1) 注册免费账号（Roboflow 官网）\n"
            "    2) Settings → Roboflow API Keys → 复制 Private API Key\n"
            "    3) python scripts/download_datasets.py --only dcv --key <你的KEY>\n"
            "       （或设环境变量 ROBOFLOW_API_KEY 后省略 --key）"
        )
    return key


def download_dcv(args) -> int:
    out_dir = Path(args.out) if args.out else DATASETS_DIR / "dcv"
    key = require_key(args)
    max_bytes = int(args.max_gb * (1 << 30))
    limits = httpx.Timeout(15.0, read=60.0)
    with httpx.Client(timeout=limits, follow_redirects=True) as client:
        project = get_project(client, args.workspace, args.project, key)
        version = resolve_version(project, args.version)
        print(
            f"[DCV] 项目 {args.workspace}/{args.project}，选定版本 v{version}"
            f"（license={project.get('license', '未知')}，project.images={project.get('images', '?')}）"
        )
        if args.list_versions:
            for v in sorted(project.get("versions") or [], key=lambda x: int(x.get("id", 0) or 0)):
                print(f"[DCV]   v{v.get('id')}  images={v.get('images')}  created={v.get('created')}")
            return 0
        wait_version_ready(client, args.workspace, args.project, version, key, args.wait_min * 60)
        link, export = poll_export_link(
            client, args.workspace, args.project, version, args.format, key, args.wait_min * 60
        )
        if args.dry_run:
            head = client.head(link)
            size = int(head.headers.get("content-length") or 0) / (1 << 20)
            print(f"[DCV] DRY-RUN：导出直链可用，大小 ≈{size:.1f} MiB，未落盘（--dry-run）")
            return 0

        manifest_path = out_dir / "manifest.json"
        reuse_sha = None
        if manifest_path.is_file():
            try:
                old = json.loads(manifest_path.read_text(encoding="utf-8"))
                reuse_sha = (old.get("archive") or {}).get("sha256")
            except Exception:
                reuse_sha = None
        archive_path, sha = archive_and_extract(
            client, link, out_dir,
            archive_name=f"dcv_v{version}_{args.format}.zip",
            max_bytes=max_bytes, label="DCV", reuse_sha=reuse_sha,
        )
        coco = validate_coco_segmentation(out_dir / "content")

    total_imgs = sum(s["images"] for s in coco["splits"].values())
    total_anns = sum(s["annotations"] for s in coco["splits"].values())
    total_poly = sum(s["polygon_annotations"] for s in coco["splits"].values())
    if total_imgs == 0 or total_poly == 0:
        raise ExtractError("coco-segmentation 校验失败：图片或多边形标注数为 0")

    sample_info = {}
    if args.sample:
        sample_info = build_sample(out_dir, DATASETS_DIR / "dcv_sample", archive_path, sha, coco, args.sample, args.format, version)

    rels = collect_rel_paths(out_dir)
    meta = {
        "internal_name": "dcv",
        "source_url": DCV_UNIVERSE_URL,
        "api_workspace": args.workspace,
        "api_project": args.project,
        "version": version,
        "format": args.format,
        "license": project.get("license") or DCV_LICENSE,
        "export_id": (export or {}).get("id"),
        "archive": {"path": archive_path.relative_to(out_dir).as_posix(), "sha256": sha, "bytes": archive_path.stat().st_size},
        "coco_validation": coco,
        "totals": {"images": total_imgs, "annotations": total_anns, "polygon_annotations": total_poly},
        "categories": coco["categories"],
        "sample": sample_info,
    }
    write_manifest(out_dir, meta, rels)
    print(f"[DCV] [OK] 图片 {total_imgs} / 标注 {total_anns}（多边形 {total_poly}），"
          f"类别 {len(coco['categories'])} 类: {', '.join(coco['categories'])}")
    for problem in coco["problems"][:5]:
        print(f"[DCV] [WARN] {problem}")
    print(f"[DCV] [OK] 产物目录 {out_dir}（SHA256SUMS 可用 sha256sum -c 校验）")
    if sample_info:
        print(f"[DCV] [OK] 小样本 {sample_info['dir']}（每 split ≤{args.sample} 张，供 W12a 先行验证）")
    return 0


def build_sample(content_root: Path, sample_dir: Path, archive_path: Path, archive_sha: str, coco: dict, n: int, fmt: str, version: int) -> dict:
    """小样本：从已解包内容抽每 split 前 n 张图 + 裁剪后的标注，独立成目录。"""
    if sample_dir.exists():
        shutil.rmtree(sample_dir)
    (sample_dir / "content").mkdir(parents=True)
    splits_out = {}
    for ann_path in sorted((content_root / "content").rglob("_annotations.coco.json")):
        split = ann_path.parent.name or "."
        data = json.loads(ann_path.read_text(encoding="utf-8"))
        images = sorted(data["images"], key=lambda x: x.get("file_name", ""))[:n]
        keep_ids = {img["id"] for img in images}
        anns = [a for a in data["annotations"] if a.get("image_id") in keep_ids]
        out = {"info": data.get("info", {}), "licenses": data.get("licenses", []),
               "categories": data["categories"], "images": images, "annotations": anns}
        sdir = sample_dir / "content" / split
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "_annotations.coco.json").write_text(
            json.dumps(out, ensure_ascii=False), encoding="utf-8", newline="\n")
        for img in images:
            fn = img.get("file_name", "")
            for cand in (ann_path.parent / fn, ann_path.parent / Path(fn).name):
                if cand.is_file():
                    (sdir / Path(fn).name).write_bytes(cand.read_bytes())
                    break
        splits_out[split] = {"images": len(images), "annotations": len(anns)}
    total = sum(s["images"] for s in splits_out.values())
    rels = collect_rel_paths(sample_dir)
    meta = {
        "internal_name": "dcv_sample",
        "mode": "sample",
        "of_internal_name": "dcv",
        "source_url": DCV_UNIVERSE_URL,
        "version": version,
        "format": fmt,
        "license": DCV_LICENSE,
        "sample_per_split": n,
        "sample_totals": {"images": total},
        "splits": splits_out,
        "parent_archive": {"path": archive_path.relative_to(content_root).as_posix(), "sha256": archive_sha},
        "coco_validation_summary": coco["splits"],
        "categories": coco["categories"],
    }
    write_manifest(sample_dir, meta, rels)
    return {"dir": str(sample_dir), "images": total, "splits": splits_out}


def download_usk(args) -> int:
    """USK 辅源：官方只走人工表单；拿到包后用 --usk-archive 登记入库。"""
    out_dir = Path(args.out) if args.out else DATASETS_DIR / "usk_coffee"
    if not args.usk_archive:
        raise BlockedError(
            "USK 辅源没有公开直链，需人工申请（详见 data/datasets/README.md）：\n"
            f"    1) 填写官方 Google Form：{USK_FORM_URL}\n"
            "    2) 等待官方回复下载链接（邮箱）\n"
            "    3) 把收到的包登记入库：\n"
            "       python scripts/download_datasets.py --only usk --usk-archive <下载的zip路径或URL>"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = int(args.max_gb * (1 << 30))
    src = args.usk_archive
    archive_path = out_dir / "_downloads" / "usk_coffee.zip"
    limits = httpx.Timeout(15.0, read=60.0)
    with httpx.Client(timeout=limits, follow_redirects=True) as client:
        if urllib.parse.urlparse(src).scheme in ("http", "https"):
            sha = stream_to_file(client, src, archive_path, max_bytes, "USK")
        elif src.startswith("file://"):
            sha = stream_to_file(client, src, archive_path, max_bytes, "USK")
        else:
            p = Path(src)
            if not p.is_file():
                raise FileNotFoundError(f"--usk-archive 指向的文件不存在: {p}")
            sha = stream_to_file(client, p.resolve().as_uri(), archive_path, max_bytes, "USK")
    extracted = safe_extract_zip(archive_path, out_dir / "content", max_bytes)

    # USK 无 COCO 标注：按扩展名统计即可
    ext_counts: dict[str, int] = {}
    for p in extracted:
        if p.is_file():
            ext_counts[p.suffix.lower() or "(无后缀)"] = ext_counts.get(p.suffix.lower(), 0) + 1
    rels = collect_rel_paths(out_dir)
    meta = {
        "internal_name": "usk_coffee",
        "source_url": USK_FORM_URL,
        "acquisition": "manual（官方表单申请，--usk-archive 登记）",
        "archive": {"path": archive_path.relative_to(out_dir).as_posix(), "sha256": sha,
                    "bytes": archive_path.stat().st_size, "origin": src},
        "file_type_counts": dict(sorted(ext_counts.items(), key=lambda kv: -kv[1])),
        "file_count": len([p for p in extracted if p.is_file()]),
        "note": "USK 4 类（peaberry/longberry/premium/defect）仅作素材粒型参考，defect 粗标不进训练映射（开发指令 §3）",
    }
    write_manifest(out_dir, meta, rels)
    print(f"[USK] [OK] 入库 {meta['file_count']} 个文件: {ext_counts}")
    print(f"[USK] [OK] 产物目录 {out_dir}（SHA256SUMS 可用 sha256sum -c 校验）")
    return 0


# ---------------------------------------------------------------- 自检

def make_synthetic_coco_zip(dest: Path) -> Path:
    """构造微型 coco-segmentation zip（自检用，非真实数据）：train/valid/test + 多边形标注。"""
    import struct
    import zlib

    def png_bytes(color: tuple[int, int, int]) -> bytes:
        # 最小合法 PNG：8x8 RGB
        w = h = 8
        raw = b"".join(b"\x00" + bytes(color) * w for _ in range(h))

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def coco_json(split: str, n: int) -> bytes:
        images, anns = [], []
        for i in range(n):
            images.append({"id": i + 1, "file_name": f"{split}_{i:03d}.jpg", "width": 8, "height": 8})
            anns.append({"id": i + 1, "image_id": i + 1, "category_id": 1,
                         "segmentation": [[1.0, 1.0, 6.0, 1.0, 6.0, 6.0, 1.0, 6.0]],
                         "bbox": [1, 1, 5, 5], "area": 25.0, "iscrowd": 0})
        return json.dumps({"images": images, "annotations": anns,
                           "categories": [{"id": 1, "name": "normal", "supercategory": "none"}]},
                          ensure_ascii=False).encode("utf-8")

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for split, n in (("train", 3), ("valid", 2), ("test", 1)):
            zf.writestr(f"{split}/_annotations.coco.json", coco_json(split, n))
            for i in range(n):
                zf.writestr(f"{split}/{split}_{i:03d}.jpg", png_bytes((90, 60, 40)))
    return dest


def make_zipslip_zip(dest: Path) -> Path:
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("../evil.txt", "nope")
    return dest


def selftest() -> int:
    """5 项自检：合成链路回环 / 穿越拒绝 / 清单闭环 / 小样本抽取 / 真实网络鉴权探针。"""
    results: list[tuple[str, bool, str]] = []
    tmp = Path(tempfile.mkdtemp(prefix="beaneye-dl-selftest-"))
    out_dir = ROOT / "out" / "selftest-datasets"
    if out_dir.exists():
        shutil.rmtree(out_dir)

    # 1) 合成 zip -> 下载回环(file://) -> sha256 -> 安全解包 -> COCO 校验
    try:
        zpath = make_synthetic_coco_zip(tmp / "synth.zip")
        expect_sha = sha256_file(zpath)
        dest = out_dir / "dcv"
        limits = httpx.Timeout(15.0, read=60.0)
        with httpx.Client(timeout=limits, follow_redirects=True) as client:
            got_sha = stream_to_file(client, zpath.resolve().as_uri(), dest / "_downloads" / "synth.zip",
                                     1 << 30, "SELFTEST")
            safe_extract_zip(dest / "_downloads" / "synth.zip", dest / "content", 1 << 30)
        coco = validate_coco_segmentation(dest / "content")
        imgs = sum(s["images"] for s in coco["splits"].values())
        polys = sum(s["polygon_annotations"] for s in coco["splits"].values())
        ok = got_sha == expect_sha and imgs == 6 and polys == 6 and len(coco["splits"]) == 3
        detail = (f"sha一致={got_sha == expect_sha} images={imgs} poly={polys} "
                  f"splits={sorted(coco['splits'])} categories={coco['categories']}")
        results.append(("合成 coco-segmentation 链路回环", ok, detail))
    except Exception as exc:
        results.append(("合成 coco-segmentation 链路回环", False, f"{exc.__class__.__name__}: {exc}"))

    # 2) 路径穿越 zip 必须被拒绝
    try:
        try:
            safe_extract_zip(make_zipslip_zip(tmp / "evil.zip"), out_dir / "evil-content", 1 << 30)
            results.append(("zip 路径穿越拒绝", False, "未抛出 ExtractError"))
        except ExtractError as exc:
            results.append(("zip 路径穿越拒绝", True, str(exc)))
    except Exception as exc:
        results.append(("zip 路径穿越拒绝", False, f"{exc.__class__.__name__}: {exc}"))

    # 3) SHA256SUMS / manifest 闭环
    try:
        dest = out_dir / "dcv"
        rels = collect_rel_paths(dest)
        write_manifest(dest, {"internal_name": "dcv", "mode": "selftest"}, rels)
        sums = (dest / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        all_ok = bool(sums)
        for line in sums:
            h, rel = line.split("  ", 1)
            all_ok = all_ok and sha256_file(dest / rel) == h
        manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        need_keys = {"internal_name", "tool", "written_at_utc"}
        results.append(("SHA256SUMS+manifest 闭环", all_ok and need_keys <= set(manifest),
                        f"{len(sums)} 条全对={all_ok} manifest键={sorted(manifest)[:4]}..."))
    except Exception as exc:
        results.append(("SHA256SUMS+manifest 闭环", False, f"{exc.__class__.__name__}: {exc}"))

    # 4) 小样本抽取（合成 zip 上模拟 --sample 2）
    try:
        dest = out_dir / "dcv"
        coco = validate_coco_segmentation(dest / "content")
        info = build_sample(dest, out_dir / "dcv_sample", dest / "_downloads" / "synth.zip",
                            sha256_file(dest / "_downloads" / "synth.zip"), coco, 2, DCV_FORMAT, 1)
        s_coco = validate_coco_segmentation(out_dir / "dcv_sample" / "content")
        s_imgs = sum(s["images"] for s in s_coco["splits"].values())
        # 每 split ≤2 张：train 3→2, valid 2→2, test 1→1，共 5
        ok = info["images"] == 5 and s_imgs == 5 and set(info["splits"]) == {"train", "valid", "test"}
        results.append(("小样本抽取（--sample 路径）", ok,
                        f"sample images={info['images']} splits={info['splits']}"))
    except Exception as exc:
        results.append(("小样本抽取（--sample 路径）", False, f"{exc.__class__.__name__}: {exc}"))

    # 5) 真实网络鉴权探针：伪造 key 打真实端点，预期 401 分类为鉴权错误（证明可达 + 协议形状 + 错误路径）
    try:
        limits = httpx.Timeout(15.0, read=30.0)
        with httpx.Client(timeout=limits, follow_redirects=True) as client:
            try:
                api_get_json_probe(client, f"{API_URL}/{DCV_WORKSPACE}/{DCV_PROJECT}", "selftest-invalid-key-0123456789abcdef")
                results.append(("真实 API 鉴权探针（伪造 key 预期 401）", False, "未返回 401（响应异常）"))
            except RoboflowAPIError as exc:
                ok = exc.status == 401
                results.append(("真实 API 鉴权探针（伪造 key 预期 401）", ok,
                                f"status={exc.status}（证明 api.roboflow.com 可达、错误分类正确）"))
    except Exception as exc:
        results.append(("真实 API 鉴权探针（伪造 key 预期 401）", False,
                        f"网络不可达或其他异常 {exc.__class__.__name__}: {redact(str(exc), 'selftest-invalid-key-0123456789abcdef')}"))

    shutil.rmtree(tmp, ignore_errors=True)

    print("== BeanEye 数据集下载器自检 ==")
    passed = 0
    for name, ok, detail in results:
        passed += ok
        print(f"[SELFTEST] {'PASS' if ok else 'FAIL'} {name}: {detail}")
    print(f"[SELFTEST] {passed}/{len(results)} PASS")
    print(f"DOWNLOAD-DATASETS SELFTEST: {'PASS' if passed == len(results) else 'FAIL'}")
    return 0 if passed == len(results) else 1


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="BeanEye 数据集下载器（DCV 主源 + USK 辅源登记）")
    p.add_argument("--only", choices=["dcv", "usk", "all"], default="all", help="下载哪个数据集（默认 all）")
    p.add_argument("--key", default=None, help="Roboflow API key（也可用环境变量 ROBOFLOW_API_KEY）；绝不打印")
    p.add_argument("--workspace", default=DCV_WORKSPACE, help=argparse.SUPPRESS)
    p.add_argument("--project", default=DCV_PROJECT, help=argparse.SUPPRESS)
    p.add_argument("--version", default="latest", help="数据集版本号或 latest（默认 latest）")
    p.add_argument("--format", default=DCV_FORMAT, help=f"导出格式（默认 {DCV_FORMAT}）")
    p.add_argument("--out", default=None, help="覆盖默认输出目录")
    p.add_argument("--sample", type=int, default=0, metavar="N", help="每 split 抽前 N 张另存小样本到 data/datasets/dcv_sample/")
    p.add_argument("--usk-archive", default=None, metavar="PATH_OR_URL", help="USK 人工获取的 zip（本地路径或 URL），登记入库")
    p.add_argument("--max-gb", type=float, default=8.0, help="归档/解压累计大小上限（默认 8 GiB）")
    p.add_argument("--wait-min", type=float, default=30.0, help="导出生成轮询上限（分钟，默认 30）")
    p.add_argument("--dry-run", action="store_true", help="只解析项目/版本/导出直链，不落盘")
    p.add_argument("--list-versions", action="store_true", help="列出可用版本后退出（需 key）")
    p.add_argument("--selftest", action="store_true", help="本机自检（合成链路 + 真实网络鉴权探针）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    statuses: list[tuple[str, int]] = []
    todo = ["dcv", "usk"] if args.only == "all" else [args.only]
    for name in todo:
        try:
            rc = download_dcv(args) if name == "dcv" else download_usk(args)
            statuses.append((name, rc))
        except BlockedError as exc:
            print(f"[{name.upper()}] [BLOCKED] {exc}")
            statuses.append((name, 3))
        except RoboflowAPIError as exc:
            print(f"[{name.upper()}] [NG] {redact(str(exc), args.key)}")
            if exc.hint:
                print(f"[{name.upper()}] 提示: {exc.hint}")
            print(f"[{name.upper()}] 人工解锁步骤见 data/datasets/README.md")
            statuses.append((name, 1))
        except (ExtractError, FileNotFoundError) as exc:
            print(f"[{name.upper()}] [NG] {redact(str(exc), args.key)}")
            statuses.append((name, 1))
        except httpx.HTTPError as exc:
            print(f"[{name.upper()}] [NG] 网络错误: {exc.__class__.__name__}: {redact(str(exc), args.key)}")
            print(f"[{name.upper()}] 提示: 本机到 api.roboflow.com 需直连可达（2026-09-28 实测可达）；代理环境请设置 HTTPS_PROXY")
            statuses.append((name, 1))
    print("----------------------------")
    for name, rc in statuses:
        print(f"[{name.upper()}] exit={rc}")
    codes = [rc for _, rc in statuses]
    if 1 in codes:
        print("DOWNLOAD-DATASETS: FAIL")
        return 1
    if 3 in codes:
        print("DOWNLOAD-DATASETS: BLOCKED (需人工步骤，见 data/datasets/README.md)")
        return 3
    print("DOWNLOAD-DATASETS: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
