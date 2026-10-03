# src-demo-skill 快速开始（人读层样本）

1. 安装依赖：无（纯标准库）。
2. 跑引擎：`python eval/runner.py reference/out reference/out`（应 exit 0）。
3. 红路自检：`python eval/runner.py <空目录> reference/out`（应 exit 1）。

常见卡点：被测目录为空时 runner 判红是预期行为（fail-closed）。
