#!/usr/bin/env python3
"""Phase 0（D1 骨架跑通日）验收门：把开工前验收固化为可重复执行的脚本。

定位：本文件是生产线的 spec+eval 资产之一——"通过线"不靠口头承诺，
而靠本脚本每次真实运行来裁定。任何一项 [FAIL] 即以退出码 1 阻塞后续里程碑。
每项门检查的注释说明它守护的是哪条底线；修复时先让门变绿，再继续开发。

用法（系统 python，工作目录任意）：

    python scripts/gate_phase0.py            # 六项门禁，全过 exit 0

约定：
- 仓库根按本文件位置自动定位（scripts/ 的上一级），不依赖当前工作目录；
- 所有 Python 子命令一律使用 python/.venv/Scripts/python.exe（虚拟环境）执行；
- 逐项打印 [PASS]/[FAIL]（环境缺失项可标 [SKIP-ENV]，不算失败也不算通过）；
  全部通过打印 "GATE PHASE0: PASS" 并退出 0，否则打印 "GATE PHASE0: FAIL"
  并退出 1；
- 子进程超时按进程树终止（Windows 用 Job Object 整树 Terminate，POSIX 用
  进程组 killpg），不留 Playwright/Chromium 残留占着调试端口与临时目录。

六个门项（对应 Phase 0 / D1 的跑通标志 + 审查收紧项）：
  1. pfcore 编排 CLI 骨架可用：
     `--help` 文本含全部子命令名（validate/build/run/pack/rules-check）；
     最小成功命令 = validate golden spec（exit 0）；
     最小失败命令 = validate bad 样本（exit 1）。
  2. packager 打包器 CLI 骨架可用：
     `--help` 文本含子命令名（build/channels）；
     最小成功命令 = channels 列规则库（exit 0）；
     最小失败命令 = 未知命令（exit != 0）。
  3. 上游对照 spike 工程（_vendor/spike，仅本机、不入库）六渠道产物
     按入库期望清单校验：specs-eval/spike-manifest.json 逐渠道断言
     文件名（pattern 通配、恰一命中）、体积 ≥ minBytes（0 字节即 FAIL）、
     zip 渠道逐条目校验（google: index.html；tiktok: index.html+config.json；
     mintegral: build.js+Template.html）。本机无 _vendor/spike 时标
     [SKIP-ENV]——不算 FAIL 也不算 PASS，期望清单入库保证可复现。
  4. llmgw 网关离线自测全过 + 零厂商硬编码：
     解析 `venv python -m llmgw.selftest` 的 stdout，断言恰好 6 条 [PASS]、
     0 条 [FAIL] 且含 "SELFTEST PASS"，退出码 0；
     厂商扫描两层：① python/llmgw 源码零端点/厂商词；② 全入库树
     （git ls-files）的依赖声明（requirements*/package.json/pyproject.toml）
     与 import/require 语句零厂商包名——`import openai` 或依赖清单钉了
     厂商包都算 FAIL。
  5. qacore 质检器雏形真实跑通（--autoplay）：
     mini.html 夹具（装配 PF/__PF_QC__ 桩）经双视口+自动试玩产出报告：
     exit 0、checks 非空、零 fail；**skip 不算过**——已实装检查
     （CHK01/03/04/05/07/08/09）出现任何 skip 即 FAIL；
     CHK03（零外网）/CHK08（控制台零错误）/CHK09（加载时长）必须为 pass。
  6. 质检变异样本（防"永远绿灯"假质检）：三个 mutant 各自必须且只能
     击中对应检查项，qacore 退出码必须为 1：
       MUT-01 外链 img      → 恰好 CHK03 fail
       MUT-02 未静音 audio  → 恰好 CHK04 fail
       MUT-04 超体积 HTML   → 恰好 CHK01 fail（--channel meta，>3MB 上限）

本脚本自身公开入库，注释与字符串一律使用中性名，不出现任何上游项目名；
上游对照工程的事实（渠道键名、产物清单、版本钉死）记录在
_vendor/NOTES.md 与 specs-eval/spike-manifest.json（后者入库）。
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# Windows 控制台默认非 UTF-8 代码页，先固定本进程输出编码，避免中文乱码。
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ------------------------------------------------------------------ 路径定位
# 仓库根 = 本文件（repo/scripts/gate_phase0.py）的上一级目录。
# 全部子命令用绝对路径 + 显式 cwd，工作目录任意都能跑。
REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"                # Python 模块与 venv 所在目录
VENV_PYTHON = PYTHON_DIR / ".venv" / "Scripts" / "python.exe"

VENDOR_DIR = REPO_ROOT / "_vendor"               # 上游参考 clone（不入库）
SPIKE_DIR = VENDOR_DIR / "spike"                 # 上游对照 spike 工程
SPIKE_MANIFEST = REPO_ROOT / "specs-eval" / "spike-manifest.json"
# ^ 六渠道产物期望清单（入库）：文件名 pattern + 最小体积 + zip 关键条目。

TMP_GATE_DIR = REPO_ROOT / "tmp" / "gate-phase0"
QACORE_REPORT = TMP_GATE_DIR / "qacore-report.json"
MUTATION_DIR = TMP_GATE_DIR / "mutations"
# ^ 质检报告与变异样本写到仓库 tmp/ 下（.gitignore 已覆盖 tmp/），每次门禁
#   先删旧文件，保证"报告存在"是本次运行的真事实而不是上次残留。

FIXTURE_MINI = PYTHON_DIR / "qacore" / "tests" / "fixtures" / "mini.html"
SPEC_GOLDEN = REPO_ROOT / "specs-eval" / "golden-match3.json"
SPEC_BAD_DIR = REPO_ROOT / "specs-eval" / "bad"

# ------------------------------------------------------------------ 门禁常量

# pfcore / packager 的子命令名：--help 文本必须完整包含（防"入口能跑但命令
# 树被砍"的假灯）。来源：python/pfcore/__main__.py build_parser / packager HELP。
# 全流水线命令名 2026-09-28 裁决为 make（占位 run 已删），见 pipeline-contract.md §1。
PFCORE_SUBCOMMANDS = ("validate", "build", "make", "pack", "rules-check")
PACKAGER_SUBCOMMANDS = ("build", "channels")

# llmgw.selftest 的顶层测试项数：stdout 必须恰好打印这么多条 [PASS]。
EXPECTED_SELFTEST_PASS = 6

# qacore 已实装的检查项：门禁的夹具运行里这些项出现 skip 即 FAIL
# （skip 不算过；未实装项 CHK02/06/10 允许 skip 但也不算通过）。
QACORE_IMPLEMENTED_IDS = ("CHK01", "CHK03", "CHK04", "CHK05", "CHK07",
                          "CHK08", "CHK09")
# 其中这三项是合规底线，必须 pass（审查 A 节：外链/控制台/加载三项）。
QACORE_MUST_PASS_IDS = ("CHK03", "CHK08", "CHK09")

# 变异样本：构造方式（对 mini.html 夹具的最小变异）与必须命中的检查项。
_MUT_AUDIO_DATA_URI = ("data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEA"
                       "RKwAAIhYAQACABAAZGF0YQAAAAA=")
MUTATION_OVERSIZE_CHANNEL = "meta"   # 规则库中该渠道上限 3MB，压线样本用它
_MUT_EXTERNAL_IMG = ('<img src="https://cdn.example.com/mut01-external.png"'
                     ' alt="" width="1" height="1">')
_MUT_UNMUTED_AUDIO = f'<audio autoplay src="{_MUT_AUDIO_DATA_URI}"></audio>'
MUTANTS = (
    {"name": "MUT-01-external-img", "inject": _MUT_EXTERNAL_IMG,
     "channel": "preview", "expect": "CHK03",
     "desc": "外链 <img>（qacore abort 拦截并记账，CHK08 不受扰）"},
    {"name": "MUT-02-unmuted-audio", "inject": _MUT_UNMUTED_AUDIO,
     "channel": "preview", "expect": "CHK04",
     "desc": "未静音 <audio autoplay>（媒体探针重采样捕获）"},
    {"name": "MUT-04-oversize", "inject": "PADDING",
     "channel": MUTATION_OVERSIZE_CHANNEL, "expect": "CHK01",
     "desc": f"包体压过 {MUTATION_OVERSIZE_CHANNEL} 渠道 maxBytes 的注释填充"},
)

# llmgw 厂商端点/厂商名扫描黑名单：代码中零命中才通过（一切由环境变量驱动）。
# 词表只收具体厂商标识与端点域名；扩展时注意误报（只加确定性强的词）。
VENDOR_ENDPOINT_RE = re.compile(
    r"bigmodel|openai\.com|dashscope|anthropic|deepseek|moonshot|stepfun"
    r"|generativelanguage|cohere|zhipu|mistral\.ai|minimax|baichuan",
    re.IGNORECASE,
)

# 厂商标识符（import / 依赖声明扫描用）：匹配 import 语句、require 目标与
# 依赖清单里的包名。命中任何一处即 FAIL——llmgw 与全仓只允许标准库/中立包。
_VENDOR_IDENTS = (r"openai|anthropic|dashscope|deepseek|moonshot|zhipu|stepfun"
                  r"|cohere|mistral|minimax|baichuan|bigmodel|generativelanguage")
PY_VENDOR_IMPORT_RE = re.compile(
    rf"^\s*(?:import|from)\s+({_VENDOR_IDENTS})\b", re.IGNORECASE | re.MULTILINE)
JS_VENDOR_IMPORT_RE = re.compile(
    rf"(?:require\(\s*|from\s+|import\s+)['\"]({_VENDOR_IDENTS})",
    re.IGNORECASE)
DEP_VENDOR_DECL_RE = re.compile(rf"\b({_VENDOR_IDENTS})\b", re.IGNORECASE)
_DEP_MANIFEST_NAMES = ("requirements.txt", "package.json", "package-lock.json",
                       "pyproject.toml")


def _is_dep_manifest(path: Path) -> bool:
    name = path.name.lower()
    return name in _DEP_MANIFEST_NAMES or name.startswith("requirements")


def _is_py_source(path: Path) -> bool:
    return path.suffix.lower() == ".py"


def _is_js_source(path: Path) -> bool:
    return path.suffix.lower() in (".mjs", ".js", ".ts")


# ------------------------------------------------------------------ 门禁框架
class Gate:
    """逐项登记 [PASS]/[FAIL]（环境缺失可 [SKIP-ENV]），最后汇总决定退出码。"""

    def __init__(self) -> None:
        self.failures = 0
        self.skip_env = 0

    def item(self, label: str, ok: bool, details: list[str] | tuple = ()) -> bool:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        for line in details:
            print(f"       {line}")
        if not ok:
            self.failures += 1
        return ok

    def item_skip_env(self, label: str, details: list[str] | tuple = ()) -> None:
        """环境缺失（如本机无 _vendor）：不算 FAIL 也不算 PASS。"""
        print(f"[SKIP-ENV] {label}")
        for line in details:
            print(f"       {line}")
        self.skip_env += 1


# ------------------------------------------------- 子进程：进程树超时终止
_IS_WINDOWS = os.name == "nt"


def _make_job_kill_on_close():
    """Windows：建一个 KILL_ON_JOB_CLOSE 的 Job Object。

    子进程及其全部后代（Playwright driver、Chromium）自动入作业；
    超时用 TerminateJobObject 整树终止，门禁自身退出（CloseHandle）时
    若仍有存活后代也会被一并清掉。失败（极少见，如嵌套作业受限）返回
    (None, None)，调用方退化为仅杀直接子进程。
    """
    import ctypes

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in
                    ("ReadOperationCount", "WriteOperationCount",
                     "OtherOperationCount", "ReadTransferCount",
                     "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32)]

    class _EXT_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMIT),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p  # 句柄按 void* 取，防符号截断
    kernel32.SetInformationJobObject.restype = ctypes.c_bool
    kernel32.AssignProcessToJobObject.restype = ctypes.c_bool
    kernel32.TerminateJobObject.restype = ctypes.c_bool
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p,
                                                  ctypes.c_void_p]
    kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None, None
    info = _EXT_LIMIT()
    info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                            ctypes.sizeof(info)):
        kernel32.CloseHandle(job)
        return None, None
    return job, kernel32


def _resume_first_thread(pid: int) -> bool:
    """恢复 pid 的第一个线程（配合 CREATE_SUSPENDED 启动）。

    先挂起启动再入作业，杜绝"子进程抢在我们 AssignProcessToJobObject 之前
    又生出孙进程、孙进程落在作业之外"的竞态。"""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.OpenThread.restype = ctypes.c_void_p
    _TH32CS_SNAPTHREAD = 0x4
    _THREAD_SUSPEND_RESUME = 0x0002

    class _THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ThreadID", ctypes.c_ulong),
                    ("th32OwnerProcessID", ctypes.c_ulong),
                    ("tpBasePri", ctypes.c_long),
                    ("tpDeltaPri", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong)]

    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if not snap:
        return False
    entry = _THREADENTRY32()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = kernel32.Thread32First(snap, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                th = kernel32.OpenThread(_THREAD_SUSPEND_RESUME, None,
                                         entry.th32ThreadID)
                if th:
                    kernel32.ResumeThread(th)
                    kernel32.CloseHandle(th)
                    return True
            ok = kernel32.Thread32Next(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return False


def _terminate_tree(proc: subprocess.Popen, job, kernel32) -> None:
    """整树终止：taskkill /T（按 pid 组，趁直接子进程还活着先走一遍树）→
    Job Object 整树 → 直接子进程确认；POSIX 用进程组 killpg。"""
    if _IS_WINDOWS:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        except Exception:
            pass
        if job is not None and kernel32 is not None:
            try:
                kernel32.TerminateJobObject(job, 1)
            except Exception:
                pass
        try:
            proc.kill()
        except OSError:
            pass
    else:
        import posix
        try:
            posix.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.kill()
        except OSError:
            pass


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, list[str]]:
    """跑一条子命令，返回 (退出码, 输出行)。

    统一注入 PYTHONUTF8=1，让 venv 内 Python 子进程的管道输出固定 UTF-8
    （Windows 下 Python 对管道默认用本地代码页，不注入则中文会乱码）。
    解码用 errors="replace"，保证任何字节都不至于让门禁本身崩溃。
    超时按进程树终止（绝不只 kill 直接子进程留孙进程残留）：
      - Windows：子进程以 CREATE_SUSPENDED 启动 → 挂进 KILL_ON_JOB_CLOSE 的
        Job Object → 再恢复运行（杜绝孙进程漏出作业的竞态）；超时先
        taskkill /T 按 pid 组整树清、再 TerminateJobObject；
      - 极端情形（残余进程仍握着输出管道）关管道脱身，门禁绝不陪葬；
      - POSIX：start_new_session + 进程组 killpg。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    kwargs = dict(cwd=str(cwd), stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, env=env)
    job = kernel32 = None
    if _IS_WINDOWS:
        _CREATE_SUSPENDED = 0x4
        proc = subprocess.Popen(cmd, creationflags=_CREATE_SUSPENDED, **kwargs)
        try:
            job, kernel32 = _make_job_kill_on_close()
            if job is not None:
                # 分配失败（嵌套作业受限等）立即弃用作业对象，走 taskkill 兜底
                if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):
                    kernel32.CloseHandle(job)
                    job, kernel32 = None, None
        except Exception:  # 作业对象不可用：兜底路径仍能整树清理
            job, kernel32 = None, None
        if not _resume_first_thread(proc.pid):
            try:
                proc.kill()
            except OSError:
                pass
            raise RuntimeError(f"子进程线程恢复失败（pid={proc.pid}），已终止")
    else:
        proc = subprocess.Popen(cmd, start_new_session=True, **kwargs)
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_tree(proc, job, kernel32)
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            # 残余进程握着管道：关门脱身，不让门禁替残留进程陪葬
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
            out, err = b"", b""
    finally:
        if job is not None:
            try:
                kernel32.CloseHandle(job)
            except OSError:
                pass
    returncode = proc.returncode
    if returncode is None:  # 终止后仍未收敛：按超时约定退出码上报
        returncode = 124 if timed_out else 1
    text = out.decode("utf-8", "replace") + err.decode("utf-8", "replace")
    return returncode, [ln for ln in text.splitlines() if ln.strip()]


def mark(ok: bool, text: str) -> str:
    """子断言行前缀：ok / FAIL，让项内失败一眼可见。"""
    return f"{'ok  ' if ok else 'FAIL'} {text}"


# ------------------------------------------------------------------ 门项 1/2

def check_1_pfcore(gate: Gate) -> None:
    """门项 1：pfcore --help 含全部子命令名 + 最小成功/失败命令真实退出码。"""
    label = "1/6 pfcore CLI 骨架：--help 含子命令名；validate golden=0、bad=1"
    lines: list[str] = []
    if not VENV_PYTHON.is_file():
        gate.item(label, False, [f"缺少虚拟环境解释器：{VENV_PYTHON}"])
        return
    ok = True

    try:
        rc, out = run_cmd([str(VENV_PYTHON), "-m", "pfcore", "--help"],
                          cwd=PYTHON_DIR, timeout=120)
    except Exception as exc:  # 子进程消失/超时等，一律按 FAIL 呈现而非崩溃
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return
    help_text = "\n".join(out)
    for sub in PFCORE_SUBCOMMANDS:
        hit = sub in help_text
        lines.append(mark(hit, f"--help 含子命令 {sub!r}"))
        ok = ok and hit
    ok = ok and rc == 0
    lines.append(mark(rc == 0, f"--help exit={rc}"))

    # 最小成功命令：validate golden spec（与 Phase 1 的 M1 eval 同一条链路）
    if SPEC_GOLDEN.is_file():
        rc, out = run_cmd([str(VENV_PYTHON), "-m", "pfcore", "validate",
                           SPEC_GOLDEN.relative_to(REPO_ROOT).as_posix()],
                          cwd=REPO_ROOT, timeout=120)
        lines.append(mark(rc == 0, f"validate golden: exit={rc}（应 0）"))
        ok = ok and rc == 0
    else:
        lines.append(mark(False, f"golden spec 不存在：{SPEC_GOLDEN}"))
        ok = False

    # 最小失败命令：validate bad 样本必须 exit 1（校验器真的会拒）
    bad_files = sorted(SPEC_BAD_DIR.glob("*.json")) if SPEC_BAD_DIR.is_dir() else []
    if bad_files:
        rc, out = run_cmd([str(VENV_PYTHON), "-m", "pfcore", "validate",
                           bad_files[0].relative_to(REPO_ROOT).as_posix()],
                          cwd=REPO_ROOT, timeout=120)
        lines.append(mark(rc == 1,
                          f"validate bad（{bad_files[0].name}）: exit={rc}（应 1）"))
        ok = ok and rc == 1
    else:
        lines.append(mark(False, f"bad 样本目录为空：{SPEC_BAD_DIR}"))
        ok = False

    gate.item(label, ok, lines)


def check_2_packager(gate: Gate) -> None:
    """门项 2：packager --help 含子命令名 + 最小成功/失败命令真实退出码。"""
    label = "2/6 packager CLI 骨架：--help 含子命令名；channels=0、未知命令≠0"
    bin_path = REPO_ROOT / "packages" / "packager" / "bin.mjs"
    if not bin_path.is_file():
        gate.item(label, False, [f"入口文件不存在：{bin_path}"])
        return
    lines: list[str] = []
    ok = True

    try:
        rc, out = run_cmd(["node", "packages/packager/bin.mjs", "--help"],
                          cwd=REPO_ROOT, timeout=120)
    except Exception as exc:
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return
    help_text = "\n".join(out)
    for sub in PACKAGER_SUBCOMMANDS:
        hit = sub in help_text
        lines.append(mark(hit, f"--help 含子命令 {sub!r}"))
        ok = ok and hit
    ok = ok and rc == 0
    lines.append(mark(rc == 0, f"--help exit={rc}"))

    # 最小成功命令：channels 列规则库（轻量、无产物副作用）
    rc, out = run_cmd(["node", "packages/packager/bin.mjs", "channels"],
                      cwd=REPO_ROOT, timeout=120)
    lines.append(mark(rc == 0, f"channels: exit={rc}（应 0）"))
    ok = ok and rc == 0

    # 最小失败命令：未知命令必须非 0 退出
    rc, out = run_cmd(["node", "packages/packager/bin.mjs",
                       "definitely-not-a-command"],
                      cwd=REPO_ROOT, timeout=120)
    lines.append(mark(rc != 0, f"未知命令: exit={rc}（应非 0）"))
    ok = ok and rc != 0

    gate.item(label, ok, lines)


# ------------------------------------------------------------------ 门项 3

def check_3_spike_artifacts(gate: Gate) -> None:
    """门项 3：spike 六渠道产物按入库期望清单校验（本机无 _vendor 则 SKIP-ENV）。"""
    label = ("3/6 上游对照 spike 六渠道产物：按 specs-eval/spike-manifest.json "
             "校验文件名/最小体积/zip 条目")
    if not SPIKE_MANIFEST.is_file():
        gate.item(label, False,
                  [f"期望清单不存在（入库文件，缺失即 FAIL）：{SPIKE_MANIFEST}"])
        return
    try:
        manifest = json.loads(SPIKE_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        gate.item(label, False, [f"期望清单不可解析：{exc}"])
        return
    entries = manifest.get("artifacts")
    expected_codes = manifest.get("channelsExpected") or []
    if not isinstance(entries, list) or not entries:
        gate.item(label, False, ["期望清单缺非空 artifacts 数组"])
        return

    # 本机无上游对照工程：期望清单已入库，但对照轨产物不在——SKIP-ENV。
    if not SPIKE_DIR.is_dir():
        gate.item_skip_env(label, [
            f"本机无上游对照工程：{SPIKE_DIR} 不存在",
            f"期望清单（入库，可复现）：{SPIKE_MANIFEST.relative_to(REPO_ROOT).as_posix()}",
            "六渠道对照需按 _vendor/NOTES.md 的版本与命令重建 spike 后复验",
        ])
        return

    lines: list[str] = []
    ok = True
    seen_codes: list[str] = []
    for entry in entries:
        channel = str(entry.get("channel", "?"))
        code = str(entry.get("code", "?"))
        pattern = str(entry.get("pattern", ""))
        min_bytes = int(entry.get("minBytes", 1))
        seen_codes.append(code)
        matches = sorted(SPIKE_DIR.glob(pattern)) if pattern else []
        if len(matches) != 1:
            lines.append(mark(False, f"{channel}: pattern 命中 {len(matches)} 件"
                                     f"（应恰 1）{pattern}"))
            ok = False
            continue
        path = matches[0]
        size = path.stat().st_size
        if size <= 0 or size < min_bytes:
            lines.append(mark(False, f"{channel}: {path.name} {size} B "
                                     f"（0 字节拒收 / 下限 {min_bytes} B）"))
            ok = False
        else:
            lines.append(mark(True, f"{channel}: {path.name} {size} B ≥ {min_bytes} B"))
        zentries = entry.get("zipEntries") or []
        if not zentries:
            continue
        if path.suffix.lower() != ".zip":
            lines.append(mark(False, f"{channel}: 期望 zip 但产物非 .zip"))
            ok = False
            continue
        try:
            with zipfile.ZipFile(path) as zf:
                infos = {i.filename: i.file_size for i in zf.infolist()}
            for ze in zentries:
                zname = str(ze.get("name"))
                zmin = int(ze.get("minBytes", 1))
                zsize = infos.get(zname)
                if zsize is None:
                    lines.append(mark(False, f"{channel}: zip 缺条目 {zname}"))
                    ok = False
                elif zsize <= 0 or zsize < zmin:
                    lines.append(mark(False, f"{channel}: zip 条目 {zname} "
                                             f"{zsize} B < {zmin} B"))
                    ok = False
                else:
                    lines.append(mark(True, f"{channel}: zip 条目 {zname} "
                                            f"{zsize} B ≥ {zmin} B"))
        except (zipfile.BadZipFile, OSError) as exc:
            lines.append(mark(False, f"{channel}: zip 读取失败：{exc}"))
            ok = False

    codes_ok = sorted(seen_codes) == sorted(expected_codes)
    lines.append(mark(codes_ok, f"渠道代号覆盖 {sorted(seen_codes)}"
                                f"（期望 {sorted(expected_codes)}）"))
    ok = ok and codes_ok
    gate.item(label, ok, lines)


# ------------------------------------------------------------------ 门项 4

def _tracked_repo_files() -> list[Path] | None:
    """入库树文件清单：git ls-files 为准；git 不可用时退化为目录枚举
    （跳过依赖/产物目录，仅作兜底）。"""
    try:
        proc = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
                              capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:200])
        names = proc.stdout.decode("utf-8", "replace").split("\0")
        return [REPO_ROOT.joinpath(*n.split("/")) for n in names if n]
    except Exception:
        skip_dirs = {".git", "node_modules", ".venv", "__pycache__", "_vendor",
                     "tmp", "artifacts", "coverage"}
        return [p for p in REPO_ROOT.rglob("*")
                if p.is_file() and not (set(p.parts) & skip_dirs)]


def scan_vendor_endpoints() -> tuple[list[str], int]:
    """扫描 python/llmgw 下全部 .py，返回 (命中描述列表, 已扫文件数)。"""
    hits: list[str] = []
    scanned = 0
    for f in sorted((PYTHON_DIR / "llmgw").rglob("*.py")):
        scanned += 1
        for lineno, line in enumerate(
                f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = VENDOR_ENDPOINT_RE.search(line)
            if m:
                hits.append(f"{f.relative_to(REPO_ROOT)}:{lineno}: 命中 {m.group(0)!r}")
    return hits, scanned


def scan_vendor_deps_imports(files: list[Path]) -> tuple[list[str], int, int]:
    """扫入库树的依赖声明与 import/require 语句，返回 (命中列表, 依赖文件数, 代码文件数)。"""
    hits: list[str] = []
    n_dep = n_code = 0
    for f in files:
        try:
            if not f.is_file():
                continue
            if _is_dep_manifest(f):
                n_dep += 1
                text = f.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(text.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith("//"):
                        continue  # 注释非依赖声明，不计命中
                    m = DEP_VENDOR_DECL_RE.search(line)
                    if m:
                        hits.append(f"{f.relative_to(REPO_ROOT)}:{lineno}: "
                                    f"依赖声明命中 {m.group(0)!r}: {line.strip()[:80]}")
            elif _is_py_source(f):
                n_code += 1
                text = f.read_text(encoding="utf-8", errors="replace")
                for m in PY_VENDOR_IMPORT_RE.finditer(text):
                    hits.append(f"{f.relative_to(REPO_ROOT)}: import 语句命中 "
                                f"{m.group(1)!r}")
            elif _is_js_source(f):
                n_code += 1
                text = f.read_text(encoding="utf-8", errors="replace")
                for m in JS_VENDOR_IMPORT_RE.finditer(text):
                    hits.append(f"{f.relative_to(REPO_ROOT)}: import/require 命中 "
                                f"{m.group(1)!r}")
        except OSError:
            continue
    return hits, n_dep, n_code


def check_4_llmgw(gate: Gate) -> None:
    """门项 4：llmgw 自测 stdout 恰好 N 条 [PASS] 且 SELFTEST PASS + 双层厂商扫描。"""
    label = (f"4/6 llmgw 网关：-m llmgw.selftest stdout 含 {EXPECTED_SELFTEST_PASS} 条 "
             "[PASS] 且 SELFTEST PASS；python/llmgw 与入库树依赖/import 零厂商硬编码")
    lines: list[str] = []
    ok = True

    if not VENV_PYTHON.is_file():
        lines.append(mark(False, f"缺少虚拟环境解释器：{VENV_PYTHON}"))
        gate.item(label, False, lines)
        return
    try:
        rc, out = run_cmd([str(VENV_PYTHON), "-m", "llmgw.selftest"],
                          cwd=PYTHON_DIR, timeout=180)
    except Exception as exc:
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return

    n_pass = sum(1 for ln in out if ln.startswith("[PASS]"))
    n_fail = sum(1 for ln in out if ln.startswith("[FAIL]"))
    has_banner = any("SELFTEST PASS" in ln for ln in out)
    selftest_ok = rc == 0 and n_pass == EXPECTED_SELFTEST_PASS \
        and n_fail == 0 and has_banner
    lines.append(mark(selftest_ok,
                      f"selftest exit={rc}，[PASS]×{n_pass}（应 "
                      f"{EXPECTED_SELFTEST_PASS}），[FAIL]×{n_fail}，"
                      f"SELFTEST PASS 横幅={'有' if has_banner else '无'}"))
    if not selftest_ok:
        lines.extend(out[-6:])
    ok = ok and selftest_ok

    hits, scanned = scan_vendor_endpoints()
    lines.append(mark(not hits, f"llmgw 端点/厂商词扫描：{scanned} 个 .py，"
                                f"命中 {len(hits)} 处")
                  + ("" if not hits else f"（如 {hits[0]}）"))
    ok = ok and not hits

    files = _tracked_repo_files() or []
    dep_hits, n_dep, n_code = scan_vendor_deps_imports(files)
    lines.append(mark(not dep_hits,
                      f"入库树依赖/import 厂商扫描：{n_dep} 个依赖清单 + "
                      f"{n_code} 个源码文件，命中 {len(dep_hits)} 处"))
    lines.extend(f"      {h}" for h in dep_hits[:10])
    ok = ok and not dep_hits

    gate.item(label, ok, lines)


# ------------------------------------------------------------------ 门项 5

def check_5_qacore(gate: Gate) -> None:
    """门项 5：qacore --autoplay 真实质检 mini.html；skip 不算过，底线三项必须 pass。"""
    label = ("5/6 qacore 质检器：--autoplay 全过；已实装项零 skip；"
             f"{'/'.join(QACORE_MUST_PASS_IDS)} 必须 pass")
    if not VENV_PYTHON.is_file():
        gate.item(label, False, [f"缺少虚拟环境解释器：{VENV_PYTHON}"])
        return
    if not FIXTURE_MINI.is_file():
        gate.item(label, False, [f"夹具不存在：{FIXTURE_MINI}"])
        return

    # 先删旧报告再跑，"报告存在"才是本次运行的真事实。
    QACORE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    if QACORE_REPORT.exists():
        QACORE_REPORT.unlink()

    try:
        rc, out = run_cmd(
            [str(VENV_PYTHON), "-m", "qacore", "run",
             FIXTURE_MINI.relative_to(PYTHON_DIR).as_posix(),
             "--channel", "preview", "--autoplay",
             "--out", str(QACORE_REPORT)],
            cwd=PYTHON_DIR, timeout=300,
        )
    except Exception as exc:
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return

    lines = [mark(rc == 0, f"qacore exit={rc}（应 0）")] + out[-2:]
    ok = rc == 0
    report: dict = {}
    if not QACORE_REPORT.is_file():
        ok = False
        lines.append(mark(False, f"报告未产出：{QACORE_REPORT}"))
    else:
        try:
            report = json.loads(QACORE_REPORT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            ok = False
            lines.append(mark(False, f"报告不可解析：{exc}"))

    if report:
        checks = report.get("checks")
        if not isinstance(checks, list) or not checks:
            ok = False
            lines.append(mark(False, f"报告缺非空 checks 键：{type(checks).__name__}"))
        else:
            by_id = {c.get("id"): c for c in checks if isinstance(c, dict)}
            fails = [cid for cid, c in by_id.items() if c.get("status") == "fail"]
            lines.append(mark(not fails,
                              f"{len(checks)} 项检查，FAIL {len(fails)} 项"
                              f"{('：' + ','.join(fails)) if fails else ''}"))
            ok = ok and not fails
            # skip 不算过：已实装项出现 skip 即 FAIL
            skipped_impl = [cid for cid in QACORE_IMPLEMENTED_IDS
                            if by_id.get(cid, {}).get("status") == "skip"]
            lines.append(mark(not skipped_impl,
                              f"已实装项（{'/'.join(QACORE_IMPLEMENTED_IDS)}）"
                              f"零 skip{'（实测无 skip）' if not skipped_impl else ''}"
                              f"{('，skip：' + ','.join(skipped_impl)) if skipped_impl else ''}"))
            ok = ok and not skipped_impl
            # 底线三项必须 pass
            for mid in QACORE_MUST_PASS_IDS:
                st = by_id.get(mid, {}).get("status")
                lines.append(mark(st == "pass", f"{mid} status={st!r}（应 pass）"))
                ok = ok and st == "pass"

    gate.item(label, ok, lines)


# ------------------------------------------------------------------ 门项 6

def _build_mutant_source(mutant: dict, base: str, limit_bytes: int) -> bytes:
    """按变异方式构造 mutant 源字节。"""
    if mutant["inject"] == "PADDING":
        base_bytes = base.encode("utf-8")
        target = limit_bytes + 4096
        pad = target - len(base_bytes) - len(b"<!---->")
        if pad <= 0:
            raise ValueError(f"填充量异常：{pad}")
        return base_bytes.replace(b"</body>",
                                  b"<!--" + b"x" * pad + b"--></body>")
    marker = "  <script>\n    // QC 桥接桩"
    if marker not in base:
        raise ValueError("夹具缺少 QC 桥接桩锚点，变异注入位置失效")
    return base.replace(marker, f"  {mutant['inject']}\n{marker}").encode("utf-8")


def check_6_mutations(gate: Gate) -> None:
    """门项 6：三个变异样本各自恰好击中对应 CHK 且 qacore exit 1（防假绿灯）。"""
    label = ("6/6 质检变异样本：外链 img→CHK03 / 未静音 audio→CHK04 / "
             "超体积→CHK01，各自恰好命中且 qacore exit 1")
    if not VENV_PYTHON.is_file():
        gate.item(label, False, [f"缺少虚拟环境解释器：{VENV_PYTHON}"])
        return
    if not FIXTURE_MINI.is_file():
        gate.item(label, False, [f"夹具不存在：{FIXTURE_MINI}"])
        return
    base = FIXTURE_MINI.read_text(encoding="utf-8")
    rules_path = REPO_ROOT / "channel-rules" / "channel-rules.json"
    limit_bytes = 3_145_728
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        limit_bytes = int(rules["channels"][MUTATION_OVERSIZE_CHANNEL]["maxBytes"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass  # 规则库不可读时用内部从严线 3MB

    MUTATION_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    ok = True
    for mutant in MUTANTS:
        name = mutant["name"]
        src_path = MUTATION_DIR / f"{name}.html"
        report_path = MUTATION_DIR / f"{name}.report.json"
        try:
            src_path.write_bytes(_build_mutant_source(mutant, base, limit_bytes))
        except (OSError, ValueError) as exc:
            lines.append(mark(False, f"{name}: 样本构造失败：{exc}"))
            ok = False
            continue
        if report_path.exists():
            report_path.unlink()
        try:
            rc, out = run_cmd(
                [str(VENV_PYTHON), "-m", "qacore", "run",
                 str(src_path),   # mutant 在 tmp/ 下（python/ 之外），用绝对路径
                 "--channel", mutant["channel"], "--autoplay",
                 "--out", str(report_path)],
                cwd=PYTHON_DIR, timeout=300)
        except Exception as exc:
            lines.append(mark(False, f"{name}: 子进程异常：{exc!r}"))
            ok = False
            continue

        failed_ids: list[str] = []
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                failed_ids = [c.get("id") for c in report.get("checks", [])
                              if isinstance(c, dict) and c.get("status") == "fail"]
            except (OSError, json.JSONDecodeError) as exc:
                lines.append(mark(False, f"{name}: 报告不可解析：{exc}"))
                ok = False
                continue
        else:
            lines.append(mark(False, f"{name}: 报告未产出（qacore exit={rc}）"))
            ok = False
            continue

        precise = rc == 1 and failed_ids == [mutant["expect"]]
        lines.append(mark(precise,
                          f"{name}（{mutant['desc']}）: exit={rc}（应 1），"
                          f"命中 {failed_ids or '无'}（应恰 [{mutant['expect']}]）"))
        ok = ok and precise

    gate.item(label, ok, lines)


# ------------------------------------------------------------------ 主流程

def main() -> int:
    print("=" * 72)
    print("Phase 0 验收门（gate_phase0）")
    print(f"仓库根     : {REPO_ROOT}")
    print(f"venv 解释器: {VENV_PYTHON}")
    print("=" * 72)

    if not REPO_ROOT.is_dir() or not PYTHON_DIR.is_dir():
        print("[FAIL] 仓库结构异常：未找到 python/ 目录（脚本被挪动了？）")
        return 1

    gate = Gate()
    t0 = time.monotonic()
    for check in (check_1_pfcore, check_2_packager, check_3_spike_artifacts,
                  check_4_llmgw, check_5_qacore, check_6_mutations):
        check(gate)
    elapsed = time.monotonic() - t0

    total = 6
    print("-" * 72)
    if gate.failures:
        note = f"，另 {gate.skip_env} 项 SKIP-ENV" if gate.skip_env else ""
        print(f"GATE PHASE0: FAIL（{total - gate.failures}/{total} 项通过{note}，"
              f"耗时 {elapsed:.1f}s）——先修复失败项，再继续推进里程碑。")
        return 1
    note = f"（另 {gate.skip_env} 项 SKIP-ENV：本机缺上游对照工程，不算失败）" \
        if gate.skip_env else ""
    print(f"GATE PHASE0: PASS（{total}/{total} 项通过{note}，耗时 {elapsed:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
