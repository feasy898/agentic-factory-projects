#!/usr/bin/env python3
"""转发入口（兼容层，勿编辑逻辑——断言以真实门脚本为准）。

背景：D3 验收门第 1 轮以 cwd=仓库根（D:/workspace/澄迈8项目/咖啡豆质检/repo）
又拼接相对路径 咖啡豆质检/repo/scripts/gate_d3.py 调用，路径前缀重复导致
Python 报 No such file or directory。真实门脚本本身设计为任意 cwd 可用
（内部以 __file__ 定位仓库根），与 gate_d2 同约定。

本文件按上述错误拼接路径提供入口：直接用当前解释器运行真实门脚本，
不复制、不改动任何检查逻辑；真实脚本位置由本文件位置向上推导
（本文件在 <repo>/咖啡豆质检/repo/scripts/ 下，真门在 <repo>/scripts/）。
与 D2 的同名转发入口（咖啡豆质检/repo/scripts/gate_d2.py，提交 8a3ce91）同一方案。

本文件不含任何上游名清单内容，无论是否被 git 跟踪均不触碰门 ④ 中性名扫描。
"""

import os
import sys

# <repo>/咖啡豆质检/repo/scripts/gate_d3.py -> 向上 4 级到 <repo>，再进 scripts/
_HERE = os.path.abspath(__file__)
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
REAL = os.path.join(_REPO, "scripts", "gate_d3.py")

if not os.path.isfile(REAL):
    sys.stderr.write(f"[FAIL] 转发入口未找到真实门脚本: {REAL}\n")
    sys.exit(1)

# 用当前解释器运行真实门脚本；透传全部参数、stdio 与退出码。
# 不用 os.execv：Windows 上它对含空格的 "C:\Program Files\..." 路径按空格拆参，不可靠；
# subprocess.list2cmdline 会正确加引号。
import subprocess  # noqa: E402

_raise = SystemExit(subprocess.run([sys.executable, REAL, *sys.argv[1:]]).returncode)
raise _raise
