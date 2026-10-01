# spec — office-guard-hooks（办公护栏 hook 包）

> 资产：可直接挂进 Claude Code 的「产物落盘校验 + 敏感信息拦截」hook 包。
> 参照实现：`skillfactory/v3/assets/office-guard-hooks/oracle/`（本 spec 全部规则依据 oracle 实际行为，
> 所引 exit code / stderr 判定均为本会话实跑验证，非转抄）。
> 被测实现：`skillfactory/v3/assets/office-guard-hooks/package/`（接口冻结见 contract.md，实现自由）。

## 1. 目标

模型用 Write/Edit 落盘交付物时，两个 PostToolUse hook 自动把关：

1. `validate_output.py` —— 产物结构校验（存在 / 非空 / 文本类严格 UTF-8 / .docx|.pptx 可打开），**fail-closed**：结构问题 exit 2 阻断。
2. `pii_guard.py` —— 文本类产物 PII 正则扫描（CN 手机号 / 18 位身份证），**对不可扫对象 fail-open**（放行并 stderr 说明），命中才 exit 2 阻断。

`hooks.json` 即资产本体：把两个 hook 绑定到 Claude Code 事件上，拿到目标仓库即可启用。

## 2. 输入 / 输出（两 hook 共同的 CLI 契约）

| 项 | 约定 |
|---|---|
| stdin | 一个 JSON 对象（Claude Code hook payload）。`file_path` 取值兼容两种 schema：顶层 `file_path`（本资产简化 schema）与 `tool_input.file_path`（Claude Code 真实 schema），前者优先 |
| stdout | **恒为空**（任何结局都不向模型上下文注入内容；validate_output.py:114-117、pii_guard.py 全部输出走 stderr） |
| stderr | 诊断 / 阻断原因，回传模型 |
| exit 0 | 通过（或无事可做，放行） |
| exit 2 | 阻断，stderr 原因回传模型 |
| 其他非零码 | 不使用（Claude Code 语义中为 non-blocking error，两实现均不产生） |

## 3. 行为规则（逐条可判定）

### 3.1 validate_output.py（判定顺序：首条命中即终局）

| # | 规则 | 判定 | 代码依据 |
|---|---|---|---|
| R1.1 | stdin 非法 JSON | exit 2，stderr 含 `not valid JSON`，且**无 Python Traceback** | validate_output.py:77-80 |
| R1.2 | stdin JSON 合法但非对象（数组/字符串等） | exit 2，stderr 含 `must be an object` | validate_output.py:81-82 |
| R1.3 | payload 无 file_path | exit 0 放行，stderr 含 `nothing to validate` | validate_output.py:85-89 |
| R1.4 | 文件不存在 | exit 2，stderr 含 `does not exist` | validate_output.py:92-93 |
| R1.5 | 路径存在但非 regular file | exit 2，stderr 含 `not a regular file` | validate_output.py:94-95 |
| R1.6 | 0 字节文件 | exit 2，stderr 含 `empty` | validate_output.py:97-99 |
| R1.7 | `.docx` 无法被 python-docx 打开 | exit 2，stderr 含 `python-docx`（`.pptx` 同逻辑、关键词 `python-pptx`） | validate_output.py:52-73 |
| R1.8 | 非办公后缀的文件字节流不是严格 UTF-8 | exit 2，stderr 含 `not decodable as UTF-8` | validate_output.py:107-112 |
| R1.9 | 全部检查通过 | exit 0，stderr 含 `OK` | validate_output.py:116-118 |

实测（本会话，oracle 根下运行）：good.txt→0、clean.docx→0（嵌套 schema）、pii.txt→0、bad_empty.txt→2（`file is empty`）、bad_encoding.txt→2（`not decodable as UTF-8`）、corrupt.docx→2（`python-docx`）、缺失文件→2；截断 JSON 与 `[1,2,3]` 均 exit 2、grep Traceback 计 0。`python run_tests.py` 12/12 PASS、自身 exit 0。

### 3.2 pii_guard.py

| # | 规则 | 判定 | 代码依据 |
|---|---|---|---|
| R2.1 | stdin 非法 JSON / 非对象 | exit 2，stderr 含 `FAIL`，无 Traceback | pii_guard.py:65-72 |
| R2.2 | 无 file_path | exit 0，stderr 含 `nothing to scan` | pii_guard.py:74-78 |
| R2.3 | 文件缺失 / 非 regular file | exit 0（存在性归 validate_output），stderr 含 `not a scannable file` | pii_guard.py:79-83 |
| R2.4 | 后缀 ∈ 二进制跳过集合 `{.docx,.pptx,.xlsx,.zip,.pdf,.png,.jpg,.jpeg,.gif,.exe,.dll}` | exit 0，stderr 含 `skipped` | pii_guard.py:38-44, 85-89 |
| R2.5 | 0 字节文件 | exit 0，stderr 含 `empty file` | pii_guard.py:91-95 |
| R2.6 | 非 UTF-8 文本 | exit 0，stderr 含 `WARNING` 与 `not scanned`（结构问题归 validate_output） | pii_guard.py:96-102 |
| R2.7 | 命中 `(?<!\d)1[3-9]\d{9}(?!\d)`（手机）或 `(?<!\d)\d{17}[\dXx](?!\d)`（18 位身份证） | exit 2；stderr 逐条 `  <path>:<行号>: [phone|cn-id] <脱敏>`，按（行号, 类别）排序；脱敏=手机前 3 位+`****`+后 4 位、身份证前 4 位+`*`×(len−8)+后 4 位；**不回显完整 PII** | pii_guard.py:35-36, 47-52, 104-118 |
| R2.8 | 干净文本 | exit 0，stderr 含 `no PII` | pii_guard.py:120-123 |
| R2.9 | 18 位身份证不被手机号规则二次命中（数字边界 lookaround 保证：fixture 第 3 行只产生一条 `[cn-id]`） | 由 R2.7 的输出条数隐含判定 | pii_guard.py:35-36 |

实测（本会话）：`printf '{"tool_name":"Write","file_path":"tests/fixtures/pii.txt"}' | python hooks/pii_guard.py` → exit 2，stderr 恰两行命中：`pii.txt:2: [phone] 138****5678`、`pii.txt:3: [cn-id] 1101**********4258`；good.txt → exit 0。

### 3.3 hooks.json（Claude Code 配置）

| # | 规则 |
|---|---|
| R3.1 | 合法 JSON；顶层为对象且含 `hooks` 映射 |
| R3.2 | 事件名 ⊆ 文档白名单（见 §5 口径来源）；oracle 仅用 `PostToolUse` |
| R3.3 | 每事件值为 matcher 组数组：`{matcher?: string, hooks: handler[]}`，handler 数组非空；`handler.type ∈ {command, http, mcp_tool, prompt, agent}`；`type=="command"` 时 `command` 为非空字符串 |
| R3.4 | oracle 绑定形态：`PostToolUse` × matcher `Write|Edit` × 依次两个 command handler（`pii_guard.py` 在前、`validate_output.py` 在后），命令经 `${CLAUDE_PROJECT_DIR}` 相对项目根定位 |

### 3.4 自测套件（package 随附）

| # | 规则 |
|---|---|
| R4.1 | `python tests/gen_fixtures.py` exit 0，幂等产出 6 个 fixture（文本 fixture 字节级确定，clean.docx 每次重建）；生成后自断言（18 位 ID 长度、GBK 严格解码必须失败） |
| R4.2 | `python run_tests.py` 实跑两 hook × 12 用例（validate_output 7 + pii_guard 5，见 run_tests.py:71-98），全过 exit 0，任一失败 exit 1 并写 `out/tests.json` |

## 4. 边界与非目标

- 只处理 payload 给定的**单个 file_path**；不做目录递归、不删改文件、不改写内容。
- PII 仅覆盖 CN 手机号 + 18 位身份证两类正则；**不承诺**邮箱/银行卡/护照等。
- 职责切分：结构问题（缺失/空/编码/损坏）只归 validate_output（fail-closed）；pii_guard 对一切不可扫对象一律 exit 0 放行（fail-open）——两 hook 同时挂载时整体不漏拦。
- `.docx|.pptx` 只验「可打开」，不验内容合规；`.xlsx` 不在 validate_output 检查范围（仅 pii_guard 跳过）。`.pptx` 分支为 oracle 代码行为（validate_output.py:64-73）但 **无 fixture 覆盖、runner 不断言**。
- exit 2 是唯一阻断通道；不使用 Claude Code 的其他非零码语义。
- `oracle/.mimosa/`（运行环境 hook-state 跟踪产物）与 `tests/__pycache__/`（import 缓存）非交付物，评测忽略。

## 5. 评测契约（eval/runner.py，路径约定写死）

```
python skillfactory/v3/assets/office-guard-hooks/eval/runner.py [<被测产物根>] [<参照产物根>]
```

- 相对路径按调用时 cwd 解析（建议在 `D:\workspace\zcode研究` 下执行）；省略参数时默认 被测根=`skillfactory/v3/assets/office-guard-hooks/package`、参照根=`skillfactory/v3/assets/office-guard-hooks/oracle`（runner 内同样写死该默认）。
- 根解析规则（写死，确定性）：传入根含全部必备文件 → 原样评测；传入根**非空**但缺必备文件 → 向上 ≤3 级解析最近同时含 `run_tests.py` 与 `hooks.json` 的祖先作为实际评测根（输出 JSON 以 `resolved_tested_root` / `resolved_reference_root` 透明记录，如误传 `oracle/out` 报告目录则解析到 `oracle` 包根）；传入根为**空目录或不存在** → 不解析、直接判红（红测契约不因解析松动）。
- checks 数组（7 项，全过 exit 0 打印 JSON 且 `"ok": true`，任一失败 exit 1 且 `"ok": false`）：
  1. `root-resolution` 被测/参照根按解析规则得到实际评测根（空目录/无候选祖先判失败）
  2. `reference-baseline` 参照根必备文件齐全（run_tests.py、hooks/validate_output.py、hooks/pii_guard.py、hooks.json、tests/gen_fixtures.py）
  3. `structure` 被测根必备文件齐全（同上 5 项）
  4. `fixtures-generated` `python tests/gen_fixtures.py` exit 0，且 6 个 fixture 就位、bad_empty.txt 为 0 字节、其余非空
  5. `self-suite` `python run_tests.py`（cwd=被测根）exit 0 —— 对全部 fixtures 断言通过
  6. `invalid-json-stdin` 两脚本对截断 JSON 与非对象 JSON 各一次（共 4 个子进程）均 exit 2 且 stderr 无 `Traceback`
  7. `hooks-json-config` hooks.json 合法 JSON、顶层 `hooks` 映射、事件名 ⊆ 白名单、组/handler 形状合法、command 类 handler 的 command 非空
- 事件名白名单与 handler 类型口径取自 Claude Code 官方文档（code.claude.com/docs/en/hooks，2026-09-30 取证）：SessionStart, Setup, UserPromptSubmit, UserPromptExpansion, PreToolUse, PermissionRequest, PermissionDenied, PostToolUse, PostToolUseFailure, PostToolBatch, Notification, MessageDisplay, SubagentStart, SubagentStop, TaskCreated, TaskCompleted, Stop, StopFailure, TeammateIdle, InstructionsLoaded, ConfigChange, CwdChanged, DirectoryAdded, FileChanged, WorktreeCreate, WorktreeRemove, PreCompact, PostCompact, PreModelSwitch, PostModelSwitch, Elicitation, ElicitationResult, SessionEnd。
- 红绿基线：被测根=oracle（参照根=oracle）必须判绿；被测根=空目录必须判红。

## 6. 环境事实（本会话实测）

- Python 3.12.10（Windows x64，本机）；python-docx 已装（gen_fixtures 实跑成功证明）；python-pptx 本机已装但无 fixture 覆盖。
- 两脚本内部已对 stdout/stderr `reconfigure(encoding="utf-8")`（validate_output.py:30-34、pii_guard.py:29-33），Windows 管道下中文路径不炸。
- runner 全部子进程 `shell=False` + `sys.executable`，无网络、无随机，确定性评测。
