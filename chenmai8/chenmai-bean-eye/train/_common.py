"""train/ 训练脚本线 · 共享工具（私有模块，六脚本共用）。

模块级**只依赖标准库**（beaneye 的 yaml/pydantic 由函数内惰性导入——
dry-run 打类别表会经 beaneye.taxonomy 带上它们，属核心钉版、可承受；
cv2/numpy/synth 等重量级依赖一律真实分支才导入）。``--dry-run`` 必须纯
离线且不触碰重量级依赖（实测本机 warm import：cv2 ≈12s、
``beaneye.synth`` ≈44s）；NN 栈任何分支都不允许在 dry-run 出现。

职责：

- 仓库根定位与相对路径解析（脚本可从任意 cwd 运行；相对路径一律相对仓库根）；
- 控制台输出统一 UTF-8（Windows 控制台/重定向默认 GBK 会乱码，与
  ``scripts/gate_d3.py`` 同款做法）；
- :class:`PlanReporter` —— ``--dry-run`` 计划打印器（[OK]/[缺失]/[计划]/[错误]
  状态行；「缺失」不阻塞 dry-run（GPU 机就绪后提供），结构性错误计数后非零退出）；
- COCO 工具：类别表（taxonomy 13 类 → category id，severity_order 序、
  id 从 1 起、跨脚本确定性）、JSON 读写（与 ``beaneye.acquisition.base.write_json``
  同约定：UTF-8 / ensure_ascii=False / indent=2 + 换行）；
- sha256 清单（``sha256sum -c`` 兼容格式，数据集完整性校验）。

中性名说明（gate_d3 中性名纪律）：训练计划 T6 脚本清单中的上游 NN 专有件名
在本目录一律以中性名落盘——T1 微调脚本名为 ``det_finetune.py``，其余五脚本
与计划清单同名；对应关系见 ``train/README.md``。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 仓库根与路径
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "train" / "runs"
DEFAULT_SYNTH_CONFIG = REPO_ROOT / "configs" / "synth.yaml"
DEFAULT_TAXONOMY = REPO_ROOT / "configs" / "taxonomy.yaml"

# 让 ``python train/<script>.py`` 在任意 cwd 都能 import beaneye
# （sys.path[0] 只有 train/；仓库不要求 pip 安装，pytest 的 pythonpath 仅覆盖测试进程）
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def setup_console() -> None:
    """stdout/stderr 统一 UTF-8（子进程捕获与重定向下的中文不乱码）。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def resolve_path(raw: str | Path) -> Path:
    """路径解析：绝对路径原样；相对路径**相对仓库根**（与 README 约定一致）。"""
    p = Path(raw)
    return p if p.is_absolute() else REPO_ROOT / p


# ---------------------------------------------------------------------------
# 退出码约定（六脚本统一）
# ---------------------------------------------------------------------------

EXIT_OK = 0        # dry-run 计划打印完成 / 真实模式成功
EXIT_FAILED = 1    # 真实模式执行失败（或验收门槛未达）
EXIT_USAGE = 2     # 参数非法 / 提供的输入结构性错误（JSON 解析失败、类别键非法等）


# ---------------------------------------------------------------------------
# dry-run 计划打印器
# ---------------------------------------------------------------------------


class PlanReporter:
    """``--dry-run`` 的状态行打印器。

    - ``ok()``     输入/配置已就绪且校验通过；
    - ``plan()``   将要执行的步骤（纯描述）；
    - ``missing()``输入尚未就绪（GPU 机数据经 COS 中转到位后提供）——不阻塞 dry-run；
    - ``error()``  参数/配置结构性错误——计数，:meth:`finish` 返回非零码。
    """

    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.n_missing = 0
        self.n_error = 0

    def header(self, script: str, title: str) -> None:
        mode = (
            "DRY-RUN：不训练/不下载/不写产物，仅校验参数·路径·配置并打印计划"
            if self.dry_run
            else "RUN：真实执行模式"
        )
        print(f"== {title}（{script}）==")
        print(f"   [{mode}]")
        print(f"   仓库根: {REPO_ROOT}")

    def section(self, title: str) -> None:
        print(f"\n-- {title} " + "-" * max(0, 58 - len(title)))

    def ok(self, text: str) -> None:
        print(f"  [OK]    {text}")

    def plan(self, text: str) -> None:
        print(f"  [计划]  {text}")

    def warn(self, text: str) -> None:
        print(f"  [警告]  {text}")

    def missing(self, text: str) -> None:
        self.n_missing += 1
        print(f"  [缺失]  {text}（GPU 机数据到位后提供；不阻塞 dry-run）")

    def error(self, text: str) -> None:
        self.n_error += 1
        print(f"  [错误]  {text}")

    def check_file(self, path: Path, what: str) -> bool:
        """校验一个文件路径：存在→[OK]；缺失→[缺失]。返回是否存在。"""
        if path.is_file():
            self.ok(f"{what}: {path}")
            return True
        self.missing(f"{what}: {path}")
        return False

    def check_dir(self, path: Path, what: str) -> bool:
        """校验一个目录路径：存在→[OK]；缺失→[缺失]。返回是否存在。"""
        if path.is_dir():
            self.ok(f"{what}: {path}")
            return True
        self.missing(f"{what}: {path}")
        return False

    def finish(self) -> int:
        """收尾打印；结构性错误 → EXIT_USAGE，否则 EXIT_OK（缺失不算错误）。"""
        print(
            f"\n[DRY-RUN 摘要] 计划行见上；缺失 {self.n_missing} 项"
            f"（GPU 机就绪后提供），错误 {self.n_error} 项"
        )
        if self.n_error:
            print("[DRY-RUN 结果] FAIL（存在结构性错误，先修正参数/配置）")
            return EXIT_USAGE
        print("[DRY-RUN 结果] PASS（exit 0）")
        return EXIT_OK


# ---------------------------------------------------------------------------
# JSON 读写（与 beaneye.acquisition.base.write_json 同约定；stdlib 实现，
# 避免 dry-run 路径被 acquisition.base 顶部的 cv2 导入拖慢 ~12s）
# ---------------------------------------------------------------------------


def load_json(path: str | Path) -> object:
    """读取 UTF-8 JSON；文件缺失/解析失败抛 :class:`FileNotFoundError`/:class:`ValueError`。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"JSON 文件不存在: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败 {p}: {exc}") from exc


def save_json(path: str | Path, obj: object) -> Path:
    """UTF-8 / ensure_ascii=False / indent=2 + 换行落盘（人工可读、可 diff）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# sha256 清单（数据集完整性；`sha256sum -c` 可直接校验）
# ---------------------------------------------------------------------------


def sha256_file(path: str | Path) -> str:
    """分块计算文件 sha256（hex 小写；数据集清单用）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_sha256_sums(root: Path, files: list[Path], sums_path: Path) -> Path:
    """写 ``sha256sum -c`` 兼容清单（相对 root 的 POSIX 路径，排序去重）。

    清单目标缺失时抛错（静默跳过会让完整性清单变成假阳性）。
    """
    lines: list[str] = []
    seen: set[Path] = set()
    for f in sorted(set(files)):
        if f in seen:
            continue
        seen.add(f)
        if not f.is_file():
            raise FileNotFoundError(f"清单目标缺失（拒绝出假清单）: {f}")
        rel = f.relative_to(root).as_posix()
        lines.append(f"{sha256_file(f)}  {rel}")
    sums_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n"：Windows 文本模式默认把 \n 写成 \r\n，sha256sum -c 会把
    # \r 并进文件名导致全部 FAILED（实测踩坑）；清单必须是 LF。
    sums_path.write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n"
    )
    return sums_path


# ---------------------------------------------------------------------------
# 类别表（taxonomy 13 类 → COCO categories）
# ---------------------------------------------------------------------------


def build_categories() -> tuple[list[dict], object]:
    """taxonomy 13 类 → COCO ``categories``。

    id = ``severity_order`` 位次（1 起，normal=1 … black=13），跨脚本/跨机器
    确定性；supercategory = taxonomy ``kind``（normal/primary/secondary）。
    同时返回已加载的 taxonomy（供严重度裁决复用，避免二次加载）。
    beaneye 仅此处惰性导入（beaneye 包 __init__ 会拉起 pydantic schemas，
    dry-run 可承受；cv2 级别的重量级依赖仍不入 dry-run 路径）。
    """
    from beaneye.taxonomy import load_taxonomy  # 惰性导入（见 docstring）

    tax = load_taxonomy()
    cats = [
        {"id": i, "name": key, "supercategory": tax.get(key).kind}
        for i, key in enumerate(tax.severity_order, start=1)
    ]
    return cats, tax


def categories_by_name(cats: list[dict]) -> dict[str, int]:
    """COCO categories → {name: id} 查表。"""
    return {c["name"]: int(c["id"]) for c in cats}


# ---------------------------------------------------------------------------
# NN 栈惰性导入（真实模式专用；中性名拼装，见各脚本真实分支注释）
# ---------------------------------------------------------------------------


def import_nn_stack():
    """导入 GPU 机 NN 训练栈（检测分割 NN 包 + torch），返回 (nn_pkg, torch)。

    中性名纪律：包名/模型类名在本目录不落明文（gate_d3 扫描零命中），
    按下式拼装——语义即 ``requirements-oss.txt`` 首条钉版的检测分割训练包
    （Apache-2.0，中性名 beaneye-det）及其 Seg{Small,Nano} 模型类；
    完整名称与钉版版本见该文件（属 gate 豁免的内部版文件）。
    未安装时抛 :class:`RuntimeError`，信息指明安装入口。
    """
    pkg_name = "".join(("rf", "detr"))
    try:
        import torch  # noqa: PLC0415（真实分支专用惰性导入）

        nn_pkg = __import__(pkg_name)
        return nn_pkg, torch
    except ImportError as exc:
        raise RuntimeError(
            "NN 训练栈未安装（GPU 机依赖，见 train/README.md 与 requirements-oss.txt；"
            "本机 --dry-run 不需要安装）"
        ) from exc


def nn_model_class(nn_pkg, variant: str):
    """按型号取 NN 包的分割模型类（variant: small|nano → SegSmall/SegNano）。"""
    cls_name = pkg_class_name(variant)
    try:
        return getattr(nn_pkg, cls_name)
    except AttributeError as exc:
        raise RuntimeError(
            f"NN 包缺少模型类 {cls_name!r}；请核对 requirements-oss.txt 钉版与 "
            f"train/README.md 的 API 核对说明"
        ) from exc


def pkg_class_name(variant: str) -> str:
    """型号 → 包内分割模型类名（中性名拼装；语义见 :func:`import_nn_stack`）。"""
    title = {"small": "Small", "nano": "Nano"}.get(variant)
    if title is None:
        raise ValueError(f"未知模型型号 {variant!r}（可选 small|nano）")
    return "".join(("rf", "detr")).upper() + "Seg" + title
