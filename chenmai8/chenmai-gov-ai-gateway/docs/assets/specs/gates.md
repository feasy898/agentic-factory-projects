# 六道门 spec（G0 + G-B1…G-B5：结构、门项、超时预算、附加断言）

> 状态：frozen（每批收工门 = 公开仓唯一裁定口径）。对照 `ops/{gate_d0,gate_b1,gate_b2,gate_b3,
> gate_b4,gate_b5}.py` 逐行核验于 2026-09-29。

## 1. 共同形态（自 gate_d0 起逐批沿用，冻结）

- **系统 python 任意 cwd 可跑**：门脚本只用标准库；内部 chdir 到仓库根、统一 `PYTHONUTF8=1`、
  stdout/stderr 重配 UTF-8，再用仓库 `.venv/Scripts/python.exe` 逐项执行（cwd=仓库根）；
- 每项透传完整输出，打印 `[PASS]/[FAIL]` 与退出码；末尾汇总表**抓取各 eval 自报摘要行**
  （正则匹配 `M0 INFRA: N/N` / `M2 RECOGNIZERS: …` / `e2e_smoke: N PASS / M FAIL / K DEFERRED`
  等行形——不重算判定，裁定权在被测 eval 自身）；
- 任何 FAIL（含超时）→ 本门退出码 1；
- **门内既有门回归**（b3 起）：用启动本门的解释器按其文档用法原样跑上一整门
  （gate_b3 回归 gate_b2 → b2 内含 b1 期全项；嵌套整链）。

## 2. 门项清单（编号 = 各任务单原文）

| 门 | 脚本 | 门项 | 附加断言 |
|---|---|---|---|
| G0 | ops/gate_d0.py | ① name_lint ② m0_infra ③ t0_stream ④ m10_e2e | U6 文件通道未上线时 DEFERRED 不计通过 |
| G-B1 | ops/gate_b1.py | ① name_lint ② m0_infra ③ m8_generator ④ m2_recognizers ⑤ m7_audit ⑥ t0_labels ⑦ m10_e2e | 汇总表附 m2 达标线常量（直接 import evals.thresholds，与 eval 同源） |
| G-B2 | ops/gate_b2.py | ① name_lint ②-1…②-6 回归（m0_infra / m10_e2e / m8_generator / m2_recognizers / m7_audit / t0_labels）③-1 m4_routing ③-2 m5_outguard ③-3 m3_masking | — |
| G-B3 | ops/gate_b3.py | ① name_lint ② m0_infra ③ m6_filesvc ④ m9_webui（体检页骨架口径）⑤ m10_e2e ⑥ 整门回归 gate_b2 | ⑤ **K 必须为 0**：U6 转正计入 PASS，摘要行 DEFERRED 计数非 0 即本门 FAIL |
| G-B4 | ops/gate_b4.py | ① name_lint ② m0_infra ③ m6_ocr ④ m2_semantic ⑤ m6_filesvc 回归 ⑥ m10_e2e（U1–U7）⑦ 整门回归 gate_b3 | ⑥ **K=0 且 `PASS U7 注入拦截` 逐用例行必须在位**（U7 或任何用例 DEFERRED/缺席即 FAIL） |
| G-B5 | ops/gate_b5.py | ① name_lint ② m0_infra ③ m7_audit 全量 ④ m9_webui 全量（聊天页+看板页 T5.2 口径）⑤ m10_e2e ⑥ 整门回归 gate_b4 | 沿用 b4 的 ⑥ 附加断言；各门摘要在位 |

`ops/name_lint.py`（每门第①项）：公开仓禁用词守卫——扫源码/文档（.py .md .txt .html .js
.ts .css .sh .bat .ps1；`--strict` 另扫 yaml/json 等），词表 `ops/forbidden_names.txt`
（上游项目名 + 许可证字样，大小写不敏感子串；`re:` 前缀 = 词边界正则），**零命中为过**；
排除目录 .git/.venv/plan/third_party/data 等；豁免面收窄为仓库根固定坐标
（pyproject.toml / constraints.txt / ops/clone_oss.sh / 词表自身）。

## 3. 超时预算（门脚本常量，冻结）

| 门 | 单项 | 整门回归项 |
|---|---|---|
| gate_d0 | `CHECK_TIMEOUT_S = 900` | — |
| gate_b1 | `CHECK_TIMEOUT_S = 1200`（m8 双跑复现 + m10 起服重放） | — |
| gate_b2 | `EVAL_TIMEOUT_S = 1800` | — |
| gate_b3 / b4 / b5 | `EVAL_TIMEOUT_S = 1800` | `GATE_TIMEOUT_S = 3600` |

超时按 `subprocess.TimeoutExpired` 捕获 → 该项 `[FAIL] TIMEOUT >Ns` → 门 exit 1。
门用系统 python 起跑、总时长无外层限制——嵌套整链（b5 内含 b4 内含 b3 内含 b2 十项）
实际跑完需小时级预算，**不要在窄超时窗口里启动整门**。

## 4. 实测基线（2026-09-29，本机 windev-01）

- 本会话逐项实测（各 eval 单跑，非整门）：m0_infra 20/20、t0_labels 8/8、m3_masking 8/8、
  m4_routing 43/43、m5_outguard 13/13、m2_recognizers 6/6、m2_semantic 11/11、m6_filesvc
  12/12、m6_ocr 6/6、m7_audit 16/16、m8_generator 4/4、m9_webui 14/14、t0_stream 11/11、
  **m10_e2e `7 PASS / 0 FAIL / 0 DEFERRED`**（≈337s）——全部 exit 0；
- gate_b5 收工实跑记录见 git log `827cdbf`（T5.4：6/6 全 PASS，m10_e2e 29 请求）；
- **整门复跑命令**（系统 python，任意 cwd）：
  `python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b5.py`
  （最新门；其 ⑥ 内嵌 b4→b3→b2→b1 期全项整链）。

## 5. 端口拓扑（门的隐含前置，详见 REGENERATE §3）

门内 m10_e2e / m9_webui / t0_gateway 系列需独占 9000 / 8901 / 8902 三端口——
**多批次并行跑门会端口竞争**；e2e 启动前 `_assert_port_free` 只清理命令行含本仓库路径 +
mock_upstream/e2e_smoke 标识的残留进程，无关占用者一概不碰、清理后仍被占即报错拒绝运行。
