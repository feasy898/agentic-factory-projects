# -*- coding: utf-8 -*-
"""临时转发垫片（构建修复工，2026-09-29）——机制同本目录 gate_d0.py / gate_b1.py 垫片。

背景：批次2 工作流以错误的仓库根拼接 ``政务AI脱敏网关/repo/ops/gate_b2.py``。
真实门：D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b2.py
"""
import runpy
import sys

REAL_GATE = r"D:\workspace\澄迈8项目\政务AI脱敏网关\repo\ops\gate_b2.py"

if __name__ == "__main__":
    sys.argv[0] = REAL_GATE
    runpy.run_path(REAL_GATE, run_name="__main__")
