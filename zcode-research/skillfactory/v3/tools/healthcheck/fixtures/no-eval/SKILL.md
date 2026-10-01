---
name: no-eval
version: 1.0.0
license: MIT
description: healthcheck 阳性骨架但缺 eval/ 的对照样本（用于验证「eval 缺失」红项与 B 级评级）。
permissions: [shell]
---

# no-eval

front-matter 齐全、脚本语法正常，但**没有** eval/ 目录。
预期：仅 `eval_present` 一项红（评级 B），`eval_smoke` 为 skip。
