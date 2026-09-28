#!/usr/bin/env python3
"""Phase 1（D2 契约与首条链）验收门：T1.1-T1.4 的验收命令固化为可重复执行的脚本。

定位与 gate_phase0.py 相同：生产线的 spec+eval 资产之一，"通过线"不靠口头承诺，
而靠本脚本每次真实运行来裁定。任何一项 [FAIL] 即以退出码 1 阻塞后续里程碑。

用法（系统 python，工作目录任意）：

    python scripts/gate_phase1.py

约定：
- 仓库根按本文件位置自动定位（scripts/ 的上一级），不依赖当前工作目录；
- Python 子命令一律使用 python/.venv/Scripts/python.exe（虚拟环境），
  Node 子命令使用 PATH 中的 node；两者都在仓库根目录下执行；
- 逐项打印 [PASS]/[FAIL]（项内每个子断言另起一行标注 ok/FAIL）；
  全部通过打印 "GATE PHASE1: PASS" 并退出 0，否则 "GATE PHASE1: FAIL" 退出 1。

四个门项（对应 Phase 1 的四个任务验收）：
  1. M1 spec 校验（T1.1）三连：
     a) venv python -m pfcore validate specs-eval/golden-match3.json -> exit 0；
     b) specs-eval/bad/*.json 逐个 validate -> 全部 exit 1 且错误信息含 $ 开头的
        字段路径（"错误定位到字段"是 M1 的输出契约）；
     c) node packages/spec/test/ajv-check.mjs -> exit 0（golden 通过、bad 全拒）。
  2. M2 engine-bridge（T1.2）：node packages/engine-bridge/test/run.mjs
     （即 node --test 该测试目录）-> exit 0，全部用例通过。
  3. M4 packager（T1.3）：对 match3 占位工程（packager 自带夹具 dist）跑
     applovin / meta / mintegral 三渠道打包，逐渠道断言：
     - 大小 ≤ channel-rules 渠道上限；
     - 结构（单 HTML 渠道：目录内仅 index.html 一个包内文件；
       mintegral zip：条目恰为 build.js + Template.html，且入口引用 build.js）；
     - 零外链：包内文本除 CTA landingUrl 白名单外不得出现任何 http(s) URL；
       另按渠道规则断言 applovin 注入 mraid.js、meta 禁 MRAID。
  4. M3 match3 模板（T1.4）selftest：
     a) node packages/templates/tmpl-match3/build.mjs 构建 preview 单 HTML；
     b) venv python -m qacore run artifacts/preview/match3.html
        --channel preview --autoplay -> exit 0（报告内无 fail 项）；
     c) 报告中 pf:end 在 45s 内触发（qc.autoplayTimeoutSec 预算）。

产物（全部落在 gitignore 覆盖的目录，门禁每次先清理旧产物，保证"存在"是
本次运行的真事实）：打包产物在 tmp/gate-phase1/packager/，质检报告在
tmp/gate-phase1/match3-report.json，模板 preview 产物在 artifacts/preview/。

本脚本自身公开入库，注释与字符串一律使用中性名，不出现任何上游项目名。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# Windows 控制台默认非 UTF-8 代码页，先固定本进程输出编码，避免中文乱码。
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ------------------------------------------------------------------ 路径定位
# 仓库根 = 本文件（repo/scripts/gate_phase1.py）的上一级目录。
# 全部子命令用绝对路径 + 显式 cwd，工作目录任意都能跑。
REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / "python" / ".venv" / "Scripts" / "python.exe"

SPEC_GOLDEN = REPO_ROOT / "specs-eval" / "golden-match3.json"
SPEC_BAD_DIR = REPO_ROOT / "specs-eval" / "bad"
RULES_PATH = REPO_ROOT / "channel-rules" / "channel-rules.json"
PACKAGER_BIN = REPO_ROOT / "packages" / "packager" / "bin.mjs"
PACKAGER_FIXTURE_DIST = (
    REPO_ROOT / "packages" / "packager" / "test" / "fixture" / "match3-dist"
)
MATCH3_BUILD = REPO_ROOT / "packages" / "templates" / "tmpl-match3" / "build.mjs"
MATCH3_HTML = REPO_ROOT / "artifacts" / "preview" / "match3.html"

PACK_OUT = REPO_ROOT / "tmp" / "gate-phase1" / "packager"
QACORE_REPORT = REPO_ROOT / "tmp" / "gate-phase1" / "match3-report.json"
# ^ 打包产物与质检报告写到 tmp/（.gitignore 覆盖）；每次门禁先删旧目录/旧报告。

# 包内文件清单需排除打包器写的 pack-manifest.json（元数据侧车，不随包投放）。
MANIFEST_NAME = "pack-manifest.json"

# 门项 1b：错误信息必须含 "$." 开头的字段路径（M1 输出契约"错误定位到字段"）。
FIELD_PATH_RE = re.compile(r"\$\.[A-Za-z_][A-Za-z0-9_.\[\]]*")
# 门项 3：外链扫描（与开发指令 §6-M4 的 grep -rEo "https?://" 等价的白名单扫描）。
EXTERNAL_URL_RE = re.compile(r"\bhttps?://[^\s\"'<>\\)\]}]+")
# 门项 4：自动试玩到结束页的预算（spec qc.autoplayTimeoutSec，运行时契约冻结值）。
AUTOPLAY_BUDGET_MS = 45_000.0


# ------------------------------------------------------------------ 门禁框架
class Gate:
    """逐项登记 [PASS]/[FAIL]，最后汇总决定退出码。"""

    def __init__(self) -> None:
        self.failures = 0

    def item(self, label: str, ok: bool, details: list[str] | tuple = ()) -> bool:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        for line in details:
            print(f"       {line}")
        if not ok:
            self.failures += 1
        return ok


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, list[str]]:
    """跑一条子命令，返回 (退出码, 输出行)。

    统一注入 PYTHONUTF8=1，让 venv 内 Python 子进程的管道输出固定 UTF-8。
    解码用 errors="replace"，保证任何字节都不至于让门禁本身崩溃。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, timeout=timeout, env=env,
    )
    text = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return proc.returncode, [ln for ln in text.splitlines() if ln.strip()]


def mark(ok: bool, text: str) -> str:
    """子断言行前缀：ok / FAIL，让项内失败一眼可见。"""
    return f"{'ok  ' if ok else 'FAIL'} {text}"


def external_urls(text: str, whitelist: set[str]) -> list[str]:
    """文本中出现的、不以白名单 URL 为前缀的 http(s) 外链列表。"""
    found = [m.group(0) for m in EXTERNAL_URL_RE.finditer(text)]
    return [u for u in found if not any(u.startswith(w) for w in whitelist)]


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class SubChecks:
    """门项内的子断言收集器：逐条记 ok/FAIL 行，任一 FAIL 拖垮整项。"""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.ok = True

    def check(self, ok: bool, text: str) -> None:
        self.lines.append(mark(ok, text))
        if not ok:
            self.ok = False


# ------------------------------------------------------------------ 门项 1：M1 spec 校验
def check_1_spec(gate: Gate) -> None:
    """门项 1（T1.1）：golden 通过 / bad 全拒含字段路径 / ajv 双侧校验全过。"""
    label = ("1/4 M1 spec 校验：pfcore validate golden=过、bad 样本全拒含字段路径、"
             "ajv-check 全过")
    sub = SubChecks()

    if not VENV_PYTHON.is_file():
        gate.item(label, False, [f"缺少虚拟环境解释器：{VENV_PYTHON}"])
        return
    if not SPEC_GOLDEN.is_file():
        gate.item(label, False, [f"golden spec 不存在：{SPEC_GOLDEN}"])
        return

    # a) golden 必须通过（venv python，在仓库根，与 M1 EVAL 命令一致）。
    rc, out = run_cmd([str(VENV_PYTHON), "-m", "pfcore", "validate",
                       SPEC_GOLDEN.relative_to(REPO_ROOT).as_posix()],
                      cwd=REPO_ROOT, timeout=120)
    sub.check(rc == 0, f"golden: pfcore validate exit={rc}")
    if rc != 0:
        sub.lines.extend(out[-4:])

    # b) bad 样本逐个跑：exit 1 且错误信息含 $ 字段路径（逐文件裁定，不合并跑）。
    bad_files = sorted(SPEC_BAD_DIR.glob("*.json"))
    sub.check(bool(bad_files), f"bad 样本目录非空：{len(bad_files)} 个 .json")
    for f in bad_files:
        rc, out = run_cmd([str(VENV_PYTHON), "-m", "pfcore", "validate",
                           f.relative_to(REPO_ROOT).as_posix()],
                          cwd=REPO_ROOT, timeout=120)
        has_path = bool(FIELD_PATH_RE.search("\n".join(out)))
        first_err = next((ln.strip() for ln in out if ln.strip().startswith("$.")), "")
        sub.check(rc == 1 and has_path,
                  f"bad {f.name}: exit={rc}（应 1），字段路径="
                  f"{'有' if has_path else '无'} {first_err}")

    # c) ajv 侧校验（node，在仓库根）：golden 通过、bad 全拒。
    ajv = REPO_ROOT / "packages" / "spec" / "test" / "ajv-check.mjs"
    if not ajv.is_file():
        sub.check(False, f"ajv-check 不存在：{ajv}")
    else:
        rc, out = run_cmd(["node", ajv.relative_to(REPO_ROOT).as_posix()],
                          cwd=REPO_ROOT, timeout=120)
        summary = next((ln for ln in out if ln.startswith("AJV-CHECK:")), "")
        sub.check(rc == 0, f"ajv-check: exit={rc} {summary}")
        if rc != 0:
            sub.lines.extend(out[-4:])

    gate.item(label, sub.ok, sub.lines)


# ------------------------------------------------------------------ 门项 2：M2 engine-bridge
def check_2_bridge(gate: Gate) -> None:
    """门项 2（T1.2）：engine-bridge node --test 全部用例通过。"""
    label = "2/4 M2 engine-bridge：node --test 全部用例通过"
    runner = REPO_ROOT / "packages" / "engine-bridge" / "test" / "run.mjs"
    if not runner.is_file():
        gate.item(label, False, [f"测试入口不存在：{runner}"])
        return

    try:
        rc, out = run_cmd(["node", runner.relative_to(REPO_ROOT).as_posix()],
                          cwd=REPO_ROOT, timeout=300)
    except Exception as exc:
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return

    # TAP 汇总行（# tests / # pass / # fail …）仅作展示；裁定以退出码为准
    # （node --test 任一用例失败即非 0 退出）。
    summary = [ln for ln in out if re.match(r"^# (tests|pass|fail|cancelled) ", ln)]
    details = [f"exit={rc}"] + (summary if summary else out[-3:])
    gate.item(label, rc == 0, details)


# ------------------------------------------------------------------ 门项 3：M4 packager 三渠道
def check_3_packager(gate: Gate) -> None:
    """门项 3（T1.3）：applovin/meta/mintegral 三渠道产物 大小/结构/零外链。"""
    label = ("3/4 M4 packager 三渠道：大小 ≤ 规则上限、包结构正确、"
             "landingUrl 白名单外零外链")
    details: list[str] = []

    try:
        spec = read_json(SPEC_GOLDEN)
        channels = read_json(RULES_PATH)["channels"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        gate.item(label, False, [f"spec/规则库读取失败：{exc}"])
        return
    if not PACKAGER_BIN.is_file() or not PACKAGER_FIXTURE_DIST.is_dir():
        gate.item(label, False,
                  [f"打包器入口/夹具缺失：{PACKAGER_BIN}、{PACKAGER_FIXTURE_DIST}"])
        return

    # CTA 落地页是包内唯一允许出现的 http(s) URL（白名单前缀匹配）。
    whitelist = {spec["flow"]["endScreen"]["landingUrl"]}
    project = str(spec["meta"]["projectId"])
    details.append(f"外链白名单（CTA landingUrl）：{sorted(whitelist)}")

    # 每次先清空产物目录：目录里"有什么"是本次构建的真事实。
    if PACK_OUT.exists():
        shutil.rmtree(PACK_OUT)
    PACK_OUT.mkdir(parents=True)

    sub = SubChecks()

    def build(channel: str) -> tuple[Path, int, list[str]]:
        """跑一条 build 命令，返回 (产物目录, 退出码, 输出行)。"""
        rc, out = run_cmd(
            ["node", PACKAGER_BIN.relative_to(REPO_ROOT).as_posix(), "build",
             "--spec", SPEC_GOLDEN.relative_to(REPO_ROOT).as_posix(),
             "--dist", PACKAGER_FIXTURE_DIST.relative_to(REPO_ROOT).as_posix(),
             "--channel", channel, "--locale", "en",
             "--out", PACK_OUT.relative_to(REPO_ROOT).as_posix()],
            cwd=REPO_ROOT, timeout=180,
        )
        pkg_dir = PACK_OUT / project / channel / "en"
        return pkg_dir, rc, out

    def package_files(pkg_dir: Path) -> list[str]:
        """包内文件清单（排除 pack-manifest.json 元数据侧车）。"""
        if not pkg_dir.is_dir():
            return []
        return sorted(p.name for p in pkg_dir.iterdir() if p.name != MANIFEST_NAME)

    def scan_external(where: str, text: str) -> None:
        """零外链子断言：白名单外出现任何 http(s) URL 即 FAIL。"""
        bad = external_urls(text, whitelist)
        sub.check(not bad, f"{where}: 白名单外零外链"
                           + (f"（命中 {len(bad)} 条：{bad[:3]}）" if bad else ""))

    def channel_limit(channel: str) -> int | None:
        entry = channels.get(channel)
        v = entry.get("maxBytes") if isinstance(entry, dict) else None
        return int(v) if isinstance(v, int) else None

    # ---- applovin：单 HTML 全内联，MRAID 注入，≤5MB ----
    pkg_dir, rc, out = build("applovin")
    sub.check(rc == 0, f"applovin: build exit={rc}")
    files = package_files(pkg_dir)
    single = files == ["index.html"]
    sub.check(single, f"applovin: 结构=单文件 index.html（实际 {files or '目录缺失'}）")
    if single:
        html = (pkg_dir / "index.html").read_text(encoding="utf-8")
        size = (pkg_dir / "index.html").stat().st_size
        limit = channel_limit("applovin")
        sub.check(limit is not None and size <= limit,
                  f"applovin: {size} B ≤ 上限 {limit} B")
        scan_external("applovin", html)
        sub.check('src="mraid.js"' in html, "applovin: 按渠道规则注入 mraid.js（相对引用）")
        sub.check("data:image/" in html, "applovin: 资源已内联（base64 data URI）")
    details.extend(sub.lines)
    applovin_ok = sub.ok
    sub = SubChecks()

    # ---- meta：单 HTML，禁 MRAID，≤3MB（内部从严线） ----
    pkg_dir, rc, out = build("meta")
    sub.check(rc == 0, f"meta: build exit={rc}")
    files = package_files(pkg_dir)
    single = files == ["index.html"]
    sub.check(single, f"meta: 结构=单文件 index.html（实际 {files or '目录缺失'}）")
    if single:
        html = (pkg_dir / "index.html").read_text(encoding="utf-8")
        size = (pkg_dir / "index.html").stat().st_size
        limit = channel_limit("meta")
        sub.check(limit is not None and size <= limit, f"meta: {size} B ≤ 上限 {limit} B")
        scan_external("meta", html)
        sub.check(not re.search(r"\bmraid\b", html, re.IGNORECASE),
                  "meta: 无 MRAID 引用（渠道禁用）")
    details.extend(sub.lines)
    meta_ok = sub.ok
    sub = SubChecks()

    # ---- mintegral：zip，条目恰为 build.js + Template.html（Phase 0 实测结构） ----
    pkg_dir, rc, out = build("mintegral")
    sub.check(rc == 0, f"mintegral: build exit={rc}")
    files = package_files(pkg_dir)
    zips = [f for f in files if f.endswith(".zip")]
    sub.check(len(zips) == 1,
              f"mintegral: 结构=单个 zip 产物（实际 {files or '目录缺失'}）")
    if len(zips) == 1:
        zpath = pkg_dir / zips[0]
        size = zpath.stat().st_size
        limit = channel_limit("mintegral")
        sub.check(limit is not None and size <= limit,
                  f"mintegral: zip {size} B ≤ 上限 {limit} B")
        try:
            with zipfile.ZipFile(zpath) as zf:
                names = sorted(zf.namelist())
                tpl = zf.read("Template.html").decode("utf-8", "replace") \
                    if "Template.html" in names else ""
                js = zf.read("build.js").decode("utf-8", "replace") \
                    if "build.js" in names else ""
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            names, tpl, js = [], "", ""
            sub.check(False, f"mintegral: zip 读取失败：{exc}")
        sub.check(names == ["Template.html", "build.js"],
                  f"mintegral: 条目恰为 [Template.html, build.js]（实际 {names}）")
        if names:
            sub.check('<script src="build.js"></script>' in tpl,
                      "mintegral: Template.html 相对引用 build.js")
            scan_external("mintegral Template.html", tpl)
            scan_external("mintegral build.js", js)
            sub.check("data:image/" in tpl,
                      "mintegral: Template.html 资源已内联（base64 data URI）")
    details.extend(sub.lines)
    mintegral_ok = sub.ok

    gate.item(label, applovin_ok and meta_ok and mintegral_ok, details)


# ------------------------------------------------------------------ 门项 4：M3 match3 selftest
def check_4_match3(gate: Gate) -> None:
    """门项 4（T1.4）：构建 match3 preview 产物 -> qacore --autoplay 全过且 pf:end ≤45s。"""
    label = "4/4 M3 match3 模板 selftest：qacore --autoplay 全过且 pf:end 45s 内触发"
    sub = SubChecks()

    if not VENV_PYTHON.is_file():
        gate.item(label, False, [f"缺少虚拟环境解释器：{VENV_PYTHON}"])
        return

    # a) 模板构建（preview 单 HTML，零外链自包含）。
    rc, out = run_cmd(
        ["node", MATCH3_BUILD.relative_to(REPO_ROOT).as_posix(),
         "--spec", SPEC_GOLDEN.relative_to(REPO_ROOT).as_posix(),
         "--out", MATCH3_HTML.relative_to(REPO_ROOT).as_posix()],
        cwd=REPO_ROOT, timeout=180,
    )
    built = rc == 0 and MATCH3_HTML.is_file()
    size = MATCH3_HTML.stat().st_size if MATCH3_HTML.is_file() else -1
    sub.check(built, f"构建 {MATCH3_HTML.relative_to(REPO_ROOT).as_posix()}: "
                     f"exit={rc}, {size} B")
    if not built:
        sub.lines.extend(out[-4:])
        gate.item(label, False, sub.lines)
        return

    # b) qacore 自动试玩（先删旧报告，"报告存在"才是本次运行的真事实）。
    QACORE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    if QACORE_REPORT.exists():
        QACORE_REPORT.unlink()
    rc, out = run_cmd(
        [str(VENV_PYTHON), "-m", "qacore", "run",
         MATCH3_HTML.relative_to(REPO_ROOT).as_posix(),
         "--channel", "preview", "--autoplay",
         "--out", QACORE_REPORT.relative_to(REPO_ROOT).as_posix()],
        cwd=REPO_ROOT, timeout=300,
    )
    sub.check(rc == 0, f"qacore run --autoplay: exit={rc}")
    if rc != 0:
        sub.lines.extend(out[-4:])

    # c) 报告断言：无 fail 检查项；pf:end 在 45s 预算内触发。
    report: dict = {}
    if not QACORE_REPORT.is_file():
        sub.check(False, f"质检报告未产出：{QACORE_REPORT}")
    else:
        try:
            report = read_json(QACORE_REPORT)
        except (OSError, json.JSONDecodeError) as exc:
            sub.check(False, f"质检报告不可解析：{exc}")

    if report:
        checks = report.get("checks") or []
        failed = [c.get("id") for c in checks if c.get("status") == "fail"]
        skipped = [c.get("id") for c in checks if c.get("status") == "skip"]
        sub.check(bool(checks) and not failed,
                  f"质检 {len(checks)} 项：{len(failed)} FAIL"
                  f"（skip {len(skipped)}：{','.join(skipped) or '-'}，"
                  "未实装检查属后续里程碑）")
        pf = report.get("pf") or {}
        end_ms = pf.get("endMs")
        end_ok = isinstance(end_ms, (int, float)) and 0 <= end_ms <= AUTOPLAY_BUDGET_MS
        sub.check(end_ok,
                  f"pf:end 于 {None if end_ms is None else round(end_ms)}ms 触发"
                  f"（预算 {AUTOPLAY_BUDGET_MS:.0f}ms，win={pf.get('endWin')}）")
        sub.check(report.get("autoplay") is True, "报告 autoplay 标志为 true")

    gate.item(label, sub.ok, sub.lines)


# ------------------------------------------------------------------ 主流程
def main() -> int:
    print("=" * 72)
    print("Phase 1 验收门（gate_phase1）")
    print(f"仓库根     : {REPO_ROOT}")
    print(f"venv 解释器: {VENV_PYTHON}")
    print("=" * 72)

    if not REPO_ROOT.is_dir() or not (REPO_ROOT / "packages").is_dir():
        print("[FAIL] 仓库结构异常：未找到 packages/ 目录（脚本被挪动了？）")
        return 1

    gate = Gate()
    t0 = time.monotonic()
    for check in (check_1_spec, check_2_bridge, check_3_packager, check_4_match3):
        check(gate)
    elapsed = time.monotonic() - t0

    total = 4
    print("-" * 72)
    if gate.failures:
        print(f"GATE PHASE1: FAIL（{total - gate.failures}/{total} 项通过，"
              f"耗时 {elapsed:.1f}s）——先修复失败项，再继续推进里程碑。")
        return 1
    print(f"GATE PHASE1: PASS（{total}/{total} 项通过，耗时 {elapsed:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
