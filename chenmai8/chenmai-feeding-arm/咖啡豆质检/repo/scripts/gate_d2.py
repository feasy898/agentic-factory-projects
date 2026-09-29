#!/usr/bin/env python3
"""转发入口（兼容层，勿编辑逻辑——断言以真实门脚本为准）。

背景：W13 修复复核第 1 轮，验收方以
cwd = D:/workspace/澄迈8项目/具身助餐机器人/repo
拼接相对路径 咖啡豆质检/repo/scripts/gate_d2.py 调用，该前缀在
具身助餐机器人 仓下不存在，Python 报 No such file or directory：
    <...>/具身助餐机器人/repo/咖啡豆质检/repo/scripts/gate_d2.py: [Errno 2]
真实门脚本（D:/workspace/澄迈8项目/咖啡豆质检/repo/scripts/gate_d2.py）
设计为任意 cwd 可用（内部以 __file__ 定位仓库根），W13 修复后实测
4/4 PASS（③现场重跑 oss_smoke，inlier_err=0.354mm 独立内点误差口径）。

本文件按上述错误拼接路径提供入口：以当前解释器子进程运行真实门脚本，
透传全部参数、stdio 与退出码；不复制、不改动任何检查逻辑。真实仓库根
按候选锚点推导（BEANEYE_REPO_ROOT 环境变量可显式覆盖）。本文件位于
具身助餐机器人 仓内、不纳入该仓跟踪，仅服务验收路径兼容；
与豆仓 8a3ce91(gate_d2)/005bbc7(gate_d3) 的同名 shim 同方案。
"""

import os
import subprocess
import sys

_NAME = os.path.basename(os.path.abspath(__file__))
_scripts_dir = os.path.dirname(os.path.abspath(__file__))  # .../具身/repo/咖啡豆质检/repo/scripts
_inner_repo = os.path.dirname(_scripts_dir)                # .../具身/repo/咖啡豆质检/repo
_shim_cq = os.path.dirname(_inner_repo)                    # .../具身/repo/咖啡豆质检
_base = os.path.dirname(_shim_cq)                          # .../具身/repo
_workspace = os.path.dirname(_base)                        # D:/workspace/澄迈8项目

_CANDIDATE_ROOTS = [
    os.environ.get("BEANEYE_REPO_ROOT"),
    os.path.join(_workspace, "咖啡豆质检", "repo"),
    r"D:\workspace\澄迈8项目\咖啡豆质检\repo",
]

_REAL = None
for _root in _CANDIDATE_ROOTS:
    if not _root:
        continue
    _probe = os.path.join(_root, "scripts", _NAME)
    if os.path.isfile(_probe):
        _REAL = _probe
        break

if _REAL is None:
    sys.stderr.write(f"[FAIL] 转发入口未找到真实门脚本 {_NAME}；候选: {_CANDIDATE_ROOTS}\n")
    sys.exit(1)

# 用当前解释器运行真实门脚本；透传参数/stdio/退出码。
# 不用 os.execv：Windows 上对含空格路径按空格拆参不可靠。
_raise = SystemExit(subprocess.run([sys.executable, _REAL, *sys.argv[1:]]).returncode)
raise _raise
