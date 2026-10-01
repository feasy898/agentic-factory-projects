# -*- coding: utf-8 -*-
"""vdl2 — VDL v2 编译器与校验器（VDL_v2_草案.md 的可执行实现）。

模块：
  vdl2_validate  两段式校验（闸门A draft-07 + 闸门B VPO 2020-12 registry）+ R1-R6 + 跨镜头引用
  vdl2_compile   编译器①（意图→prompt）+ 编译器②（投影 v1 ShotSpec）+ L4 骨架 + 槽位定义

纪律：不 import 任何 vpipe v1 兄弟模块（SPEC.md §0）；VPO schema 只读引用零复制（草案 §7.1）。
"""
