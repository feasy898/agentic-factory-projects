#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iso_week_probe.py — ab-002 treatment 周次口径探针（可原样复跑）。

验证 SKILL.md 中 ISO 8601 周次约定的实测依据：
- 报告周锚点：2026-09-29 → (2026, 40, 2)，与简报 L12 示例 周报-2026-W40.md 同口径；
- 周一锚点：fromisocalendar(2026, 40, 1) = 2026-09-28；
- 无外部依赖、无随机、无网络；输出仅 print。
"""
import datetime

CHECKS = [
    ("2026-09-29", datetime.date(2026, 9, 29)),
    ("2026-W40 monday", datetime.date.fromisocalendar(2026, 40, 1)),
    ("2026-10-02 (friday)", datetime.date(2026, 10, 2)),
]

for label, d in CHECKS:
    print("%-20s isocalendar=%s" % (label, tuple(d.isocalendar())))
