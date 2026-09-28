#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B0 批次门禁（gate_b0）—— T0/T0b/T1/T3 收口检查。

用法（系统 Python，任意 cwd 均可运行；内部自动定位仓库根并使用 .venv 的解释器）：
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b0.py

检查项（逐项打印 [PASS]/[FAIL]，任何 FAIL 退出码 1）：
  ① pytest tests/ 全绿且零跳过（用 .venv 的 python 在仓库根执行）：
    输出含 skipped 即 FAIL（B0 修订 2026-09-28：跳过不再算过）；
    并确保 pytest 子进程 PATH 上可解析 ffmpeg/ffprobe —— 继承 PATH 找不到时
    依次回退注入 FFMPEG_FALLBACK_DIRS，仍找不到则 FAIL（否则 M1/M4 会整组静默跳过）；
  ② configs/models.yaml：每个引擎条目含 fallback 字段，且四个已冒烟引擎
    （dub-tts / alt-tts-b / lip-fast / asr-core）的 volta_status 严格等于 "ok"
    （空 / pending / fail / degraded 一律不过）；
  ③ data/gpu_smoke_report.json：四个指定引擎各有一条 ok:true 的条目，且
    dtype 与定案一致（dub-tts=fp32 / alt-tts-b=fp32 / lip-fast=fp16 / asr-core=fp16），
    且产物可核 —— artifact_path 本地存在时实测（音频时长 ≥0.3s / 视频帧数 >0 /
    转写文本 size>0）；远端路径（本机不可达）时该条目必须内联 artifact_verify
    {sha256, size, duration_s|frames}（ssh 实测后回填的摘要），二者缺一即 FAIL；
  ④ 仓库中性名检查：被禁 token 对应内部台账 plan/oss-manifest.md 附录A 的上游名；
    台账不可读或附录A 解析出 0 条 → **FAIL**（独立克隆必须失败，禁止静默降级）；
    可读时做覆盖校验（每条上游名至少被一个 token 命中），再对公开文件 grep 零命中。

公开目录口径（与 tests/test_skeleton.py::test_neutral_naming_discipline 既有口径一致
并作扩展）：git 追踪的全部文本文件；其中 docs/ 与 requirements.txt 为依赖安装记录，
必须使用真实 PyPI 发行名，不在本检查范围。扫描后缀：.py/.yaml/.yml/.md/.json/
.sh/.ps1/.toml/.txt。被禁 token 在本文件中以拼接构造，避免自命中。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]

# 被禁 token（小写、子串匹配），与内部台账附录A 的上游名一一对应；映射关系只在台账维护。
# 一律拼接构造：本文件自身也在公开扫描集内，任何位置（含注释）不得出现连续上游名。
# 说明：
#   - 裸 "c2pa" 不禁：那是 C2PA 标准名（台账第 3 节），已固化进 C1-C8 契约
#     字段（contracts.py 的 label_status.c2pa 与 c2pa_manifest.json 工件名）；
#     禁的是上游**软件**名及其组合短语（见下行 token）。
#   - 裸 "lora" 不禁：中性名 isomt-lora 本身含该子串。
def _sep_variants(*parts: str) -> list[str]:
    """同一上游词根的三种写法：无分隔 / 下划线 / 连字符（B1 修订 2026-09-28）。

    上游 API 的蛇形命名（词根拼接见 _BANNED_ROOTS）与连字符写法同样禁止；
    词根只在拼接处闭合，源码中不出现连续上游名（防自命中）。
    """
    return ["".join(parts), "_".join(parts), "-".join(parts)]


# (附录A 组, 词根 parts)；三写法展开
_BANNED_ROOTS = [
    ("audiosplit 组", ("paddle", "ocr")),
    ("audiosplit 组", ("audio-", "separator")),
    ("audiosplit 组", ("dem", "ucs")),
    # asr-core / alt-tts-a / align-core 共同上游前缀
    ("asr 组", ("qw", "en")),
    ("align-core 组", ("forced", "aligner")),
    ("emo-tag 组（框架名 + 模型名）", ("sense", "voice")),
    ("emo-tag 组", ("fun", "asr")),
    ("voxdia 组", ("3d-", "speaker")),
    ("voxdia 组", ("cam", "++")),
    ("voxdia 组", ("pyan", "note")),
    ("actspk 组", ("light-", "asd")),
    ("facemesh 组", ("media", "pipe")),
    ("shot-cut 组", ("trans", "net")),
    ("cap-clean 组", ("video-subtitle-", "remover")),
    ("mt-core 组", ("hy-", "mt")),
    ("dub-tts 组（含连字符仓名变体）", ("index", "tts")),
    ("alt-tts-b 组", ("vox", "cpm")),
    ("lip-fast 组", ("muse", "talk")),
    ("lip-pro 组", ("latent", "sync")),
    ("audmark 组", ("audio", "seal")),
    ("provenance 组（工具名）", ("c2pa", "tool")),
    ("provenance 组", ("c2pa-", "python")),
    ("provenance 组", ("content", "auth")),
    ("isomt-lora 组", ("dub", "mt")),
    # 台账正文同禁（与 tests/test_skeleton.py::_banned_tokens 保持一致的超集）
    ("正文", ("paddle", "paddle")),
    ("正文", ("wav2", "lip")),
    ("正文", ("whis", "per")),
    ("正文", ("flash", "attention")),
    ("正文", ("vll", "m")),
]
BANNED_TOKENS = [v for _, _parts in _BANNED_ROOTS for v in _sep_variants(*_parts)]
# 短语 token（含空格，不做分隔变体）
BANNED_TOKENS.append("c2pa" + " toolchain")

SCAN_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".sh", ".ps1", ".toml", ".txt"}
# 依赖安装记录：必须写真实 PyPI 发行名，无法用中性名替代 → 不在公开扫描范围
SCOPE_EXCLUDES = ("docs/", "requirements.txt")

# ②/③ 中要求 volta_status==ok 且有 ok:true 条目的引擎（T3 已冒烟收口的四组件）
VOLTA_REQUIRED = ("dub-tts", "alt-tts-b", "lip-fast", "asr-core")

# ③ dtype 定案（与 configs/models.yaml 的 precision 字段及冒烟实测一致）：
#    dub-tts 引擎无 fp16 开关（use_bf16 only，Volta 禁 bf16）→ fp32 是唯一实测档
EXPECTED_DTYPE = {"dub-tts": "fp32", "alt-tts-b": "fp32", "lip-fast": "fp16", "asr-core": "fp16"}
# ③ 产物核验口径：音频 ≥0.3s；视频帧数 >0；转写文本 size>0
AUDIO_MIN_SECONDS = 0.3
# ① ffmpeg/ffprobe 继承 PATH 找不到时的回退目录（本机实测安装位置）
FFMPEG_FALLBACK_DIRS = (r"D:\tools\bin",)

# 内部台账（附录A 上游名权威来源）；仓库外内部文件，独立克隆时不可得 → 优雅降级
MANIFEST_CANDIDATES = (ROOT.parent / "plan" / "oss-manifest.md",
                       ROOT / "plan" / "oss-manifest.md")

# B1 修订：套件含 M1/M3/M4 实测用例（M3 为 CPU 真模型推理，全量实测 ~1932s，
# 2026-09-28）——900s 是 M3 入列前的旧值，会误杀全绿套件；给足余量取 3600s。
PYTEST_TIMEOUT_S = 3600


def venv_python() -> Path | None:
    """定位仓库 .venv 的解释器（Windows/Linux 两种布局）。"""
    for rel in ((".venv", "Scripts", "python.exe"),
                (".venv", "bin", "python"),
                (".venv", "bin", "python3")):
        p = ROOT.joinpath(*rel)
        if p.is_file():
            return p
    return None


def run_venv_json(code: str, args: list[str]) -> object:
    """经 .venv python 执行一段返回 JSON 的代码（系统 python 缺三方库时的桥）。"""
    vpy = venv_python()
    if vpy is None:
        raise RuntimeError("未找到 .venv 解释器")
    r = subprocess.run([str(vpy), "-c", code, *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"venv 桥执行失败: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def load_yaml(path: Path) -> object:
    try:
        import yaml  # 系统解释器自带则直接用
    except ImportError:
        return run_venv_json(
            "import sys, yaml, json;"
            "print(json.dumps(yaml.safe_load(open(sys.argv[1], encoding='utf-8'))))",
            [str(path)])
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------

def _pytest_env() -> tuple[dict[str, str] | None, str]:
    """构造 pytest 子进程环境，并修复 PATH 继承：ffmpeg/ffprobe 不在继承 PATH 时
    依次回退注入 :data:`FFMPEG_FALLBACK_DIRS`。返回 (env|None, 说明)。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    def have(exe: str) -> bool:
        return shutil.which(exe, path=env.get("PATH", "")) is not None

    if have("ffmpeg") and have("ffprobe"):
        return env, "PATH 自带 ffmpeg/ffprobe"
    for d in FFMPEG_FALLBACK_DIRS:
        if any((Path(d) / f"{exe}.exe").is_file() or (Path(d) / exe).is_file()
               for exe in ("ffmpeg", "ffprobe")):
            env["PATH"] = d + os.pathsep + env.get("PATH", "")
            if have("ffmpeg") and have("ffprobe"):
                return env, f"继承 PATH 无 ffmpeg/ffprobe，已回退注入 {d}"
    return None, ("ffmpeg/ffprobe 不在 PATH（含回退目录 " + "; ".join(FFMPEG_FALLBACK_DIRS) +
                  "）—— M1/M4 测试将整组静默跳过；请安装 ffmpeg 并把其 bin 目录加入 PATH")


def check_pytest() -> tuple[bool, str]:
    vpy = venv_python()
    if vpy is None:
        return False, "未找到 .venv 解释器（.venv/Scripts/python.exe 或 .venv/bin/python）"
    env, env_note = _pytest_env()
    if env is None:
        return False, env_note
    try:
        r = subprocess.run([str(vpy), "-m", "pytest", "tests/", "-q"],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=PYTEST_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return False, f"pytest 超时（>{PYTEST_TIMEOUT_S}s）"
    out = r.stdout or ""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    tail = " | ".join(lines[-3:])[:300] if lines else (r.stderr or "").strip()[:300]
    if r.returncode != 0:
        return False, f"pytest 退出码 {r.returncode}: {tail}"
    # B0 修订：出现 skipped 即 FAIL（有跳过说明门禁环境残缺，不得当全绿基线）
    m = re.search(r"(\d+)\s+skipped", out)
    if m or "skipped" in out.lower():
        return False, (f"pytest 输出含 skipped（{m.group(1) if m else '?'} 个）—— "
                       f"跳过不算过: {tail}")
    return True, f"[{env_note}] {tail}"


def check_models_yaml() -> tuple[bool, str]:
    path = ROOT / "configs" / "models.yaml"
    if not path.is_file():
        return False, "configs/models.yaml 不存在"
    try:
        data = load_yaml(path)
    except Exception as exc:  # 解析失败即 FAIL
        return False, f"models.yaml 解析失败: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("components"), dict):
        return False, "models.yaml 缺 components 引擎表"
    comps = data["components"]
    if not comps:
        return False, "components 为空"
    missing_fb = sorted(n for n, c in comps.items()
                        if not isinstance(c, dict) or "fallback" not in c)
    if missing_fb:
        return False, f"缺 fallback 字段的引擎条目: {missing_fb}"
    absent = [n for n in VOLTA_REQUIRED if n not in comps]
    if absent:
        return False, f"缺引擎条目: {absent}"
    # B0 修订：空 / pending / fail / degraded 一律不过，四组件必须严格 "ok"
    bad_volta = {n: str(comps[n].get("volta_status") or "").strip() or "<空>"
                 for n in VOLTA_REQUIRED
                 if str(comps[n].get("volta_status") or "").strip().lower() != "ok"}
    if bad_volta:
        return False, f"四组件 volta_status 须严格等于 'ok'（空/fail/pending 均不过）: {bad_volta}"
    volta_brief = ", ".join(f"{n}={comps[n]['volta_status']}" for n in VOLTA_REQUIRED)
    return True, (f"{len(comps)} 个引擎条目均含 fallback 字段；"
                  f"四组件 volta_status: {volta_brief}")


def _ffprobe_path() -> str | None:
    """ffprobe 可执行文件（含回退目录口径，与 _pytest_env 一致）。"""
    for base in (None, *FFMPEG_FALLBACK_DIRS):
        p = shutil.which("ffprobe", path=(base if base else os.environ.get("PATH", "")))
        if p:
            return p
    return None


def _ffprobe_json(args: list[str]) -> dict:
    exe = _ffprobe_path()
    if exe is None:
        raise RuntimeError("ffprobe 不在 PATH（含回退目录）")
    r = subprocess.run([exe, "-loglevel", "error", *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


def _probe_artifact(kind: str, path: Path) -> tuple[bool, str]:
    """本地产物实测：音频时长 ≥0.3s / 视频帧数 >0 / 转写文本 size>0。"""
    if not path.is_file():
        return False, f"产物文件不存在: {path}"
    if kind == "audio":
        data = _ffprobe_json(["-show_entries", "format=duration",
                              "-of", "json", str(path)])
        dur = float(data["format"]["duration"])
        ok, detail = dur >= AUDIO_MIN_SECONDS, f"实测时长 {dur:.3f}s"
    elif kind == "video":
        data = _ffprobe_json(["-select_streams", "v:0", "-count_packets",
                              "-show_entries", "stream=nb_read_packets",
                              "-of", "json", str(path)])
        frames = int(data["streams"][0]["nb_read_packets"])
        ok, detail = frames > 0, f"实测帧数 {frames}"
    else:  # transcript
        size = path.stat().st_size
        ok, detail = size > 0, f"转写文本 {size} bytes"
    return ok, detail


def _verify_inline_digest(item: dict) -> tuple[bool, str]:
    """远端产物核验（二选一之一）：条目内联 artifact_verify 摘要（ssh 实测后回填）。"""
    v = item.get("artifact_verify")
    if not isinstance(v, dict):
        return False, "远端 artifact_path 本机不可达，且条目无内联 artifact_verify 摘要"
    sha = str(v.get("sha256") or "")
    size = v.get("size")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        return False, "artifact_verify.sha256 缺失或非 64 位十六进制"
    if not isinstance(size, int) or size <= 0:
        return False, "artifact_verify.size 缺失或非正整数"
    model = item.get("model")
    kind = {"dub-tts": "audio", "alt-tts-b": "audio", "lip-fast": "video"}.get(model, "transcript")
    if kind == "audio":
        dur = v.get("duration_s")
        if not isinstance(dur, (int, float)) or dur < AUDIO_MIN_SECONDS:
            return False, f"artifact_verify.duration_s 须 ≥{AUDIO_MIN_SECONDS}s"
        return True, f"内联摘要核验: sha256={sha[:12]}… size={size} duration={dur}s"
    if kind == "video":
        frames = v.get("frames")
        if not isinstance(frames, int) or frames <= 0:
            return False, "artifact_verify.frames 须为正整数"
        return True, f"内联摘要核验: sha256={sha[:12]}… size={size} frames={frames}"
    return True, f"内联摘要核验: sha256={sha[:12]}… size={size}"


def check_smoke_report() -> tuple[bool, str]:
    path = ROOT / "data" / "gpu_smoke_report.json"
    if not path.is_file():
        return False, "data/gpu_smoke_report.json 不存在"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"gpu_smoke_report.json 解析失败: {exc}"
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return False, "gpu_smoke_report.json 无 items 列表"
    notes: list[str] = []
    fails: list[str] = []
    for model, expect_dtype in EXPECTED_DTYPE.items():
        rows = [it for it in items
                if isinstance(it, dict) and it.get("model") == model]
        if not rows:
            fails.append(f"{model}: 无条目")
            continue
        ok_rows = [it for it in rows if it.get("ok") is True]
        if not ok_rows:
            fails.append(f"{model}: 无 ok:true 条目（失败项须修复后重跑冒烟，不能只记录 error）")
            continue
        it = ok_rows[0]
        dtype = str(it.get("dtype") or "").strip().lower()
        if dtype.split("-")[0] != expect_dtype:
            fails.append(f"{model}: dtype={dtype or '<空>'} 与定案 {expect_dtype} 不一致")
            continue
        # 产物核验：本地存在 → 实测；远端路径 → 内联 artifact_verify 摘要（二选一）
        ap = it.get("artifact_path")
        if not ap:
            fails.append(f"{model}: ok 条目缺 artifact_path")
            continue
        ap_local = Path(str(ap))
        if ap_local.is_file():
            kind = {"dub-tts": "audio", "alt-tts-b": "audio",
                    "lip-fast": "video"}.get(model, "transcript")
            try:
                ok, detail = _probe_artifact(kind, ap_local)
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, f"产物实测失败: {exc}"
            if not ok:
                fails.append(f"{model}: 本地产物核验不过 —— {detail}")
            else:
                notes.append(f"{model}: dtype={dtype} 本地产物 {detail}")
        else:
            ok, detail = _verify_inline_digest(it)
            if not ok:
                fails.append(f"{model}: {detail}")
            else:
                notes.append(f"{model}: dtype={dtype} 远端路径 {detail}")
    if fails:
        return False, "；".join(fails)
    n_fail_rows = sum(1 for it in items if isinstance(it, dict) and it.get("ok") is not True)
    notes.append(f"共 {len(items)} 条（含 {n_fail_rows} 条如实记录的失败项）")
    return True, "；".join(notes)


def public_files() -> list[Path]:
    """公开目录文件集 = git 追踪文件 − 依赖安装记录 − 非文本后缀。"""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                             capture_output=True, check=True, timeout=60).stdout
        names = [n for n in out.decode("utf-8", "replace").split("\0") if n]
    except Exception:
        # git 不可用时退化为目录枚举（仍覆盖全部公开代码/配置目录）
        names = []
        for sub in ("pipeline", "configs", "tests", "scripts", "gpu", "data"):
            d = ROOT / sub
            if d.is_dir():
                names.extend(str(p.relative_to(ROOT)) for p in sorted(d.rglob("*"))
                             if p.is_file() and "__pycache__" not in p.parts)
        for extra in ("README.md", "conftest.py", "requirements.txt"):
            if (ROOT / extra).is_file():
                names.append(extra)
    picked = []
    for n in names:
        n = n.replace("\\", "/")
        if n.startswith(SCOPE_EXCLUDES) or n in SCOPE_EXCLUDES:
            continue
        if Path(n).suffix.lower() in SCAN_SUFFIXES:
            picked.append(ROOT / n)
    return picked


APPENDIX_HEADING_RE = re.compile(r"^#{1,6}\s*附录\s*A")


def parse_manifest_appendix() -> tuple[Path | None, list[tuple[str, str]]]:
    """解析内部台账附录A → [(中性名, 上游名单元格), ...]；找不到/解析不出返回 (None, [])。

    锚定规则：以「## 附录A」标题行定位（正文其他位置也会提到“附录A”三字，
    不能用子串包含判断），且只认其后含「中性名」表头的那张表，防止误吞前文章节表。
    """
    manifest = next((p for p in MANIFEST_CANDIDATES if p.is_file()), None)
    if manifest is None:
        return None, []
    try:
        lines = manifest.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return manifest, []
    rows: list[tuple[str, str]] = []
    started = header_seen = False
    for raw in lines:
        s = raw.strip()
        if not started:
            if APPENDIX_HEADING_RE.match(s):
                started = True
            continue
        if not header_seen:
            if s.startswith("|") and "中性名" in s:
                header_seen = True
            continue
        if not s.startswith("|"):
            if rows:
                break  # 表格结束
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue  # 分隔行
        neutral, upstream = cells[0], cells[1]
        if neutral and upstream and neutral != "中性名":
            rows.append((neutral, upstream))
    return manifest, rows


def check_neutral_names() -> tuple[bool, str]:
    # 第一步：台账附录A 覆盖校验。B0 修订：台账不可读或解析出 0 条 → FAIL
    # （独立克隆必须失败，禁止静默降级——否则 token 表与台账脱节发现不了）。
    manifest, rows = parse_manifest_appendix()
    notes: list[str] = []
    if manifest is None:
        return False, ("内部台账不可读（" + " 或 ".join(str(p) for p in MANIFEST_CANDIDATES) +
                       "）—— token 表失去对照来源，判 FAIL")
    if not rows:
        return False, (f"内部台账已找到（{manifest}）但附录A 解析出 0 条 —— "
                       "覆盖校验失去依据，判 FAIL（请核对附录A 表头/表格结构）")
    uncovered = [neutral for neutral, upstream in rows
                 if not any(tok in upstream.lower() for tok in BANNED_TOKENS)]
    if uncovered:
        return False, ("附录A 上游名未被 token 表覆盖（请更新 BANNED_TOKENS），"
                       "中性名: " + ", ".join(uncovered))
    notes.append(f"附录A 覆盖校验通过（{len(rows)} 条上游名均被 token 表覆盖）")
    # 第二步：公开文件 grep
    files = public_files()
    if not files:
        return False, "公开文件集为空（扫描范围异常）"
    hits: list[str] = []
    scanned = 0
    for path in files:
        try:
            text = path.read_bytes().decode("utf-8", "replace").lower()
        except OSError as exc:
            return False, f"无法读取 {path.relative_to(ROOT)}: {exc}"
        scanned += 1
        for token in BANNED_TOKENS:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}: {token!r}")
    if hits:
        return False, (f"{len(hits)} 处上游名命中:\n    " + "\n    ".join(hits))
    notes.append(f"扫描 {scanned} 个公开文件 × {len(BANNED_TOKENS)} 个被禁 token，零命中")
    return True, "；".join(notes)


# ---------------------------------------------------------------------------

def main() -> int:
    checks = [
        ("① pytest tests/ 全绿且零跳过（并保证子进程 PATH 可解析 ffmpeg）", check_pytest),
        ("② models.yaml 每条目含 fallback 且四组件 volta_status==ok", check_models_yaml),
        ("③ smoke 报告四引擎各一条 ok:true + dtype 定案一致 + 产物可核验", check_smoke_report),
        ("④ 中性名检查（台账附录A 强校验 + 公开文件零命中）", check_neutral_names),
    ]
    n_fail = 0
    for title, fn in checks:
        try:
            ok, detail = fn()
        except Exception as exc:  # 检查本身抛错 = 该项 FAIL
            ok, detail = False, f"检查执行异常: {exc}"
        if not ok:
            n_fail += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {title}")
        for ln in detail.splitlines():
            print(f"       {ln}")
    total = len(checks)
    print(f"== gate_b0: {total - n_fail}/{total} PASS ==")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
