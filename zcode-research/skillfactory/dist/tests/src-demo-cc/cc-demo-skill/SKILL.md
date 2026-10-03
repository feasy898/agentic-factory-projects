---
name: cc-demo
version: 0.3.0
license: MIT
description: claude-code 变体测试源（正文带 cc-only 标注段）。当用户要求「测试 cc 变体」时使用；不用于真实业务。边界段：不用于任何真实任务。
permissions: []
metadata:
  domain: cc-fixture
---

# cc-demo

BP-3「含标注时恰生成对应字段」路径：下方标注段在 claude-code 变体应生成为顶层
allowed-tools 私有字段并在所有变体正文中剥离。

<!-- cc-only:allowed-tools -->
Read, Bash(git status)
<!-- /cc-only:allowed-tools -->

## 文档地图

| 文档 | 何时读 |
|---|---|
| （无 references） | — |
