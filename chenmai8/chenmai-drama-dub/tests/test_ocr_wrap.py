"""OCR 封装守护测试（B1 修订 2026-09-28）：锁死 Windows 两条硬约束。

对应 _reviews/drama-b0-review.md §E：先 torch 后 paddle、enable_mkldnn=False
此前只存在于文档；本组测试把两条变成可执行守护。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pipeline.ocr_wrap import assert_torch_first, ocr_kwargs

ROOT = Path(__file__).resolve().parents[1]


def test_ocr_kwargs_forces_mkldnn_off():
    """约束 2：构造参数出口强制 enable_mkldnn=False，外部同名覆盖被忽略。"""
    assert ocr_kwargs()["enable_mkldnn"] is False
    forced = ocr_kwargs(enable_mkldnn=True)  # 试图打开 oneDNN → 被无视
    assert forced["enable_mkldnn"] is False
    # 其余参数透传（构造仍可配置）
    kw = ocr_kwargs(lang="ch", use_gpu=False, enable_mkldnn=True)
    assert kw["lang"] == "ch" and kw["use_gpu"] is False and kw["enable_mkldnn"] is False


def test_bootstrap_import_order_guard():
    """约束 1：bootstrap() 后同进程再 import paddle，torch 仍在先 —— 顺序合法；
    守护器对合法序放行、对乱序报错（子进程实测，不污染本进程 sys.modules）。"""
    vpy = ROOT / ".venv" / "Scripts" / "python.exe"
    if not vpy.is_file():  # Linux CI 布局兜底
        vpy = ROOT / ".venv" / "bin" / "python"
    assert vpy.is_file(), "未找到 .venv 解释器"
    env = {**os.environ, "PYTHONUTF8": "1"}
    # 正向：bootstrap()（先 torch）→ import paddle → 守护器放行
    ok_script = (
        "import sys; sys.path.insert(0, r'%s');"
        "from pipeline.ocr_wrap import bootstrap, assert_torch_first;"
        "bootstrap(); import paddle; assert_torch_first(); print('ORDER_OK')" % ROOT
    )
    r = subprocess.run([str(vpy), "-c", ok_script], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300, env=env,
                       cwd=str(ROOT))
    assert r.returncode == 0, f"正向顺序不应报错: {r.stderr[-400:]}"
    assert "ORDER_OK" in (r.stdout or "")
    # 反向：不调 bootstrap 直接 import paddle → 守护器必须拦截（paddle 先于 torch）
    bad_script = (
        "import sys; sys.path.insert(0, r'%s');"
        "import paddle;"
        "from pipeline.ocr_wrap import assert_torch_first; assert_torch_first()" % ROOT
    )
    r2 = subprocess.run([str(vpy), "-c", bad_script], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=300, env=env,
                        cwd=str(ROOT))
    assert r2.returncode != 0, "乱序加载未被守护器拦截"
    assert "DLL 加载顺序硬约束" in (r2.stderr or "") or "DLL" in (r2.stderr or ""), \
        f"拦截原因不符: {r2.stderr[-400:]}"


def test_assert_torch_first_pure_logic():
    """不依赖真实 paddle 的纯逻辑守护：伪造模块序验证判定方向。"""
    import types

    saved = dict(sys.modules)
    try:
        fake = types.ModuleType("paddle_fake")
        clean = {k: v for k, v in sys.modules.items()
                 if not k.startswith("paddle") and not k.startswith("torch")}
        # paddle 系在册、torch 不在册 → 必须抛
        clean["paddle_fake"] = fake
        sys.modules.clear()
        sys.modules.update(clean)
        try:
            assert_torch_first()
            raise AssertionError("paddle 先于 torch 未被拦截")
        except RuntimeError as exc:
            assert "DLL 加载顺序硬约束" in str(exc)
        # torch 在册且更早 → 放行
        clean2 = {"torch_fake": types.ModuleType("torch_fake"), "paddle_fake": fake}
        sys.modules.clear()
        sys.modules.update({"torch": types.ModuleType("torch"), **clean2})
        # torch 在前（index 0），paddle 在后 → 不抛
        assert_torch_first()
    finally:
        sys.modules.clear()
        sys.modules.update(saved)
