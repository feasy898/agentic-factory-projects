# -*- coding: utf-8 -*-
"""临时转发垫片（构建修复工，2026-09-28）。

背景：复核工作流以错误的仓库根（具身助餐机器人/repo）运行相对路径
``政务AI脱敏网关/repo/ops/gate_d0.py``，Windows 下拼成
``<错误repo根>\\政务AI脱敏网关\\repo\\ops\\gate_d0.py`` 而找不到文件
（第 1 轮复核实报：can't open file ... 具身助餐机器人\\repo\\政务AI脱敏网关\\...）。

本垫片只做转发：用 runpy 以 ``__main__`` 方式执行真实门脚本，
``__file__`` 指向真实文件，因此真实门内 REPO_ROOT（parents[1]）
解析到真实仓库根，内部 chdir、.venv 解释器、四项检查全部零改动。
真实门：D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_d0.py
"""
import runpy
import sys

REAL_GATE = r"D:\workspace\澄迈8项目\政务AI脱敏网关\repo\ops\gate_d0.py"

if __name__ == "__main__":
    sys.argv[0] = REAL_GATE
    runpy.run_path(REAL_GATE, run_name="__main__")
