# SECURITY-NOTES — 推送前扫描分诊记录

> 2026-10-03，zcode-nightshift。触发：Mimosa git-push 前扫描报 12 处 high。
> 分诊方法：逐条人工核对污点流（外部输入是否能到达危险汇聚点），不信模式匹配结论。

## 结论：1 真实（已修复）+ 11 误报（不改）

### 已修复：video-capability/overnight/vpipe/judges_src/prefetch_model.py

| 发现 | 位置 | 修复 |
|---|---|---|
| 路径穿越 ×4 | `os.path.join(a.dest, p)` 系列（L116/164/196/199 原行号）——`p` 来自**远端 API 文件清单响应**，恶意/被劫持端点可返回 `../` 路径写出目标目录 | 新增 `safe_rel(dest, rel)`：拒绝绝对路径/盘符/`..`/空段 + realpath 包含性断言；三处 join 全部改走 safe_rel |
| SSRF ×1 | `http()` 对 CLI 传入 endpoint 直接 urlopen（L47 原行号） | 强制 `https` scheme（拒绝 file://、http 明文等） |

验证：`py_compile` 通过；`safe_rel` 单元用例 7 恶意路径全拒 + 3 正常路径全过 + http 守卫拒绝 http:// 用例；`--help` 正常。未做真实下载回归（需拉模型，改动仅加校验不改下载逻辑）。

### 误报（11 处，不动代码）

| 文件 | 处数 | 误报理由（人工核对） |
|---|---|---|
| zcode-research/skillfactory/assets/ppt-method-router/tests/ab/ab2-ambiguous-fallback/treatment/verify.py | 6（L60/62/66/68/204/216） | 所有 join 段为字面量（`"run%d.stdout.txt"`、`"verify_result.json"`）或 `__file__` 派生常量（HERE/RUNS_DIR），无任何外部输入到达 open()；系本仓自产的评测留档工具 |
| xuexing-agent/tools/dual_agent_verify.py | 1（L153） | MANIFEST_PATH/QUEUE_PATH 由 `__file__` 派生目录 + 字面量文件名（L26/43/44），无污点流 |
| video-capability prefetch_model.py（同文件其余 5 处） | 计入上表修复面 | fetch_small 的 `.part` 临时路径与 `.ok` 标记均由已校验的 dest 派生，safe_rel 落地后一并收敛 |

> 维护提示：本仓评测/留档类脚本大量使用 `os.path.join(常量目录, 字面量名)` 模式，模式扫描必然反复命中；有新增 high 时先分诊污点流再动手，勿机械"修复"证据工具。
