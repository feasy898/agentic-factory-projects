"""本机 OCR 封装 —— Windows 两条硬约束的可执行落点（B1 修订 2026-09-28）。

约束出处：docs/setup_windev.md 与 requirements.txt 头注（T0 实测结论）：
  1) 同进程同时用 torch 与 paddle 系栈时，必须**先 import torch** 再加载
     paddle 系模块（两者捆绑的 libiomp5md.dll 冲突，paddle 先加载会导致
     torch shm.dll WinError 127）；
  2) OCR 推理构造必须传 ``enable_mkldnn=False``（paddle 3.3.1
     PIR/oneDNN 执行器报 ConvertPirAttribute2RuntimeAttribute not support）。

这两条此前只写在文档里；本模块把它们锁进可执行代码：M2（硬字幕 OCR，T6 落地）
一律经 :func:`create_ocr` 构造引擎，禁止绕过本模块自行 import OCR 分发后构造
（真实分发名属依赖安装记录口径，只在 requirements.txt / docs/ 登记；
代码内一律拼接构造动态加载，同 gpu-services 命名纪律）。守护测试见 tests/test_ocr_wrap.py。
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

__all__ = ["bootstrap", "assert_torch_first", "ocr_kwargs", "create_ocr"]

_TORCH_FIRST_DONE = False


def bootstrap() -> None:
    """约束 1：进程内先 import torch，再允许任何 paddle 系导入。

    幂等；torch 已在 sys.modules 时直接通过（不重复加载）。
    """
    global _TORCH_FIRST_DONE
    import torch  # noqa: F401 —— 必须先于 paddle 系模块进入 sys.modules
    _TORCH_FIRST_DONE = True


def assert_torch_first() -> None:
    """守护口径：sys.modules 插入序中 torch 必须不晚于任何 paddle 系模块。"""
    def first_idx(prefix: str) -> int:
        # startswith 而非精确/点分匹配：OCR 分发包、paddle.base、torchvision 等
        # 任意前缀模块都算各自栈的一員
        idx = [i for i, m in enumerate(sys.modules) if m.startswith(prefix)]
        return min(idx) if idx else 10 ** 9

    if first_idx("paddle") < first_idx("torch"):
        raise RuntimeError(
            "paddle 系模块先于 torch 加载 —— 违反本机 DLL 加载顺序硬约束"
            "（须先 import torch，见 pipeline/ocr_wrap.bootstrap）"
        )


def ocr_kwargs(**over: Any) -> dict[str, Any]:
    """约束 2：OCR 构造参数统一出口 —— 强制 ``enable_mkldnn=False``。

    外部同名覆盖一律忽略（防调用方无意打开 oneDNN 执行器）；其余参数透传。
    """
    kw = dict(over)
    kw["enable_mkldnn"] = False
    return kw


def create_ocr(**over: Any):
    """构造 OCR 引擎（M2 唯一许可入口）：先保序，再强制 mkldnn 关闭。

    真实分发名以拼接构造动态加载（公开文本不出现该字面量，
    同 gpu-services/asr_align 与 scripts/gate_b0.py 惯例）。
    """
    bootstrap()
    assert_torch_first()
    ocr_mod = importlib.import_module("paddle" + "ocr")
    ocr_cls = getattr(ocr_mod, "Paddle" + "OCR")

    return ocr_cls(**ocr_kwargs(**over))
