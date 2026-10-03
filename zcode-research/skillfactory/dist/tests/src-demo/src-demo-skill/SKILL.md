---
name: src-demo
version: 0.2.0
license: MIT
description: BP 组测试源包（canonical 形态：顶层 version/permissions + 目录名带 -skill 后缀）。当用户要求「测试 build.py」时使用；不用于真实业务。边界段：不用于任何真实任务。
permissions: [shell]
metadata:
  domain: build-fixture
---

# src-demo

BP 组 canonical 测试源包。期望构建变换：
- standard：顶层 version/permissions → metadata.version/metadata.permissions；
  产物目录名 = src-demo；剥人读层（README.md）；排除 reference/。
- claude-code：standard + 零私字段（本源无 cc-only 标注）。
- learner：standard + 保留 README.md；eval/ 不剥离。

## 文档地图

| 文档 | 何时读 |
|---|---|
| references/notes.md | 若需要夹具说明则读 |
