# 安全门禁处置记录（2026-09-29，T9 期间）

> 触发：Mimosa L3 提交门禁在工作树扫描中发现大量 high 告警并硬拦截 commit。
> 两类问题、两类处置，均在 owner 授权下执行；本文为交付汇编用的简短记录。

## 一、上游参考克隆移出工作树（60 条告警，全部位于 _vendor/）

- 事实：60 条 high 全部位于 `_vendor/` 下四个本地参考克隆内部（第三方测试/源码）；
  `git ls-files` 证实 `_vendor/` 下 **0 个跟踪文件**（`.gitignore:42`），永不入库；
  克隆版本锁定见 `upstream_lock.md`。修复第三方参考件违反"参考件只读"约定。
- 处置（授权：整体移出工作树 + junction 保路径）：
  1. `_vendor/` 实体整体移至仓库工作树之外：`具身助餐机器人/_vendor-ref/`；
  2. 原位建 junction `_vendor -> ..\..\_vendor-ref`，`_vendor/<克隆>/…` 相对路径语义
     不变（模型回退链、复现命令不受影响）；
  3. `upstream_lock.md` 顶部已加位置变更记录；锁定 commit 不变。
- 效果：重扫后 60 条 vendor 告警全部消失（扫描口径与仓库内容对齐）。

## 二、四处工具脚本加固（自有代码真实加固点，独立 commit）

| # | 位置 | 原状 | 加固后 | 功能验证 |
|---|---|---|---|---|
| ① | `chengshao/training/transfer/cos_transfer.py` | `--execute` 用 `shell=True` 执行字符串命令 | `build_plan` 增产结构化 `command_argv`（与展示串一一对应）+ 程序白名单 `{coscmd, 7z}` + `shutil.which` 解析绝对路径作 `argv[0]` + `shell=False`；展示串（含行内注释）不变、不进命令行 | `tests/test_training_scripts.py` 22 绿；argv 结构断言（3 条、白名单、无 `#` token） |
| ② | `chengshao/scripts/fetch_models.py` | `--url` 任意地址直接 `urlopen`（SSRF 面） | 强制 https + 主机白名单（中性域名：官方模型桶 + 境内镜像；含中性名扫描禁用词的原始上游域名按仓库命名纪律不入库，镜像已覆盖场景） | `http://*` → exit 2 拒绝；非白名单 https → exit 2 拒绝；已存在短路不受影响 |
| ③ | `scripts/gate_g1.py`（看板冒烟） | `Popen` 未显式 `shell=False`，argv/cwd 未 resolve | 显式 `shell=False` + `venv/db_path/cwd` 全部 `resolve()` | gate_g1 全流程实跑通过（含冒烟步） |
| ④ | `chengshao/training/spoon_cls/prepare_data.py` | `write_outputs` 直写 `--out` 派生路径 | 入口 `resolve()` + `is_relative_to(REPO_ROOT)` 逃逸断言（纵深防御；入口 `safe_rel_output` 拦截不变） | 仓库外路径 → `ConfigError` 拒绝；仓库内正常写出后清理 |

## 三、重扫与回归证据

- 重扫（deep，2026-09-29）：`scan-2026-09-28T21-45-55.925Z-73d7cf79f6ca`，
  seal `sha256:7cc36f43a9431280f38a07664982854b1079377078394b85667bb1469ab2331e`。
  发现 **70 → 3**：①命令注入、②SSRF 两条消失。
- 残留 3 条为启发式误报性质（按授权"不续耗"，记录在案）：
  `export_onnx.py` 不安全反序列化（训练延后资产，torch 加载自有权重）、
  `prepare_data.py` / `gate_g1.py` 路径穿越（已加固仍被命中——数据流分析不识别
  `safe_rel_output`/白名单消毒器）。
- **提交门禁最终拦截文案（2026-09-29，加固与重扫之后）**：仅剩 2 条——
  `scripts/gate_g1.py:203 [high] 路径穿越`、
  `chengshao/training/spoon_cls/prepare_data.py:156 [high] 路径穿越`，
  "高危已强制拦截，请修复并重新扫描"。按授权不再继续对抗启发式：
  加固 commit 与 T9 delta **全部 git add 暂存**（未 commit），待主会话裁决。
- 回归：`tests/test_training_scripts.py` 22 绿；全量 pytest 297 绿 1 跳
  （ASR 大模型用例按需开启，两轮）；**gate_g1 全量 8/8 PASS**（加固后实跑，
  2026-09-29，`gate_g1.json`）；`check_naming` forbidden=0。

## 四、经验（供后续）

1. **门禁报告自我污染**：`gate_g1.json` 会内嵌 check_naming 失败详情（stderr 原文）；
   当失败详情含禁用词时，报告文件本身成为下一轮扫描的命中点，形成死循环。
   处置：重跑门禁前先删除上一轮被污染的 `gate_g1.json`。
2. **gitignore ≠ 扫描范围**：工作树级安全扫描会覆盖 gitignore 目录；本地参考件
   （只读第三方克隆）应放在工作树之外，原位用 junction 保路径。
3. 白名单域名不得含中性名扫描禁用词的原始上游域名——即使只是基础设施主机名，
   命名纪律按字面 grep 执行（`requirements` 的发行名白名单是唯一例外）。
