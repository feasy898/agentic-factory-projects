# contract — office-guard-hooks/package 接口冻结

> 本文件冻结被测产物 `package/` 的**对外接口**；满足本契约的前提下实现自由。
> 行为规则的逐条判定见 spec.md；本契约只规定「必备什么、怎么调、怎么算过」。

## 1. 必备文件（相对 package 根，与 oracle 同构）

| 文件 | 状态 | 说明 |
|---|---|---|
| `run_tests.py` | 必备 | 自测入口，`python run_tests.py` 全过 exit 0 / 失败 exit 1 |
| `hooks/validate_output.py` | 必备 | 产物落盘校验 hook（spec §3.1） |
| `hooks/pii_guard.py` | 必备 | PII 扫描 hook（spec §3.2） |
| `hooks.json` | 必备 | Claude Code hooks 配置（spec §3.3，合法 JSON、事件名 ⊆ 文档白名单） |
| `tests/gen_fixtures.py` | 必备 | fixtures 生成器，`python tests/gen_fixtures.py` exit 0、幂等 |
| `tests/fixtures/good.txt` | 评测时生成 | 合法 UTF-8、无 PII（约 100B，2 行） |
| `tests/fixtures/bad_empty.txt` | 评测时生成 | 0 字节 |
| `tests/fixtures/bad_encoding.txt` | 评测时生成 | GBK 字节（严格 UTF-8 解码必须失败） |
| `tests/fixtures/pii.txt` | 评测时生成 | 第 2 行 CN 手机、第 3 行 18 位身份证、第 4 行座机（不得命中） |
| `tests/fixtures/clean.docx` | 评测时生成 | python-docx 可打开的有效文档（每次重建） |
| `tests/fixtures/corrupt.docx` | 评测时生成 | `.docx` 后缀的垃圾字节（python-docx 必须打不开） |
| `out/tests.json` | 产物 | 由 run_tests.py 产出；**不要求随包分发** |
| `tests/__pycache__/`、`.mimosa/` | 环境产物 | 非交付物，评测忽略 |

fixtures 目录允许随包预置；runner 无论如何会先跑 `tests/gen_fixtures.py` 刷新（幂等，见 oracle/tests/gen_fixtures.py:36-71 的 content-addressed 写法——缺失或字节不同才重写）。

## 2. 脚本命令行契约

### hooks/validate_output.py 与 hooks/pii_guard.py

```bash
echo '<JSON payload>' | python hooks/validate_output.py    # exit 0=通过 / 2=阻断
echo '<JSON payload>' | python hooks/pii_guard.py
```

- **stdin**：单个 JSON 对象；`file_path` 双 schema 兼容（顶层 `file_path` 优先，回落 `tool_input.file_path`）。
- **命令行参数**：无要求（不接受也不需要）。
- **stdout**：恒为空。
- **退出码**：仅 0 与 2；非法/非对象 JSON 必须 exit 2 优雅报错，**不得抛 Traceback 崩溃**（runner 唯一强制断言的 stderr 口径：无 `Traceback` 字样）。
- **stderr 内容措辞自由**（oracle 的 `FAIL:`/`OK`/`skipped` 等子串不是冻结接口，仅 oracle 自测使用）。

### tests/gen_fixtures.py

```bash
python tests/gen_fixtures.py [--force]    # exit 0；幂等产出 6 个 fixture
```

### run_tests.py

```bash
python run_tests.py    # cwd=package 根；全过 exit 0，任一失败 exit 1
```

- 必须以**真实子进程**方式调用两 hook（参照 run_tests.py:38-50），断言每用例 exit code。
- 失败时写出机器可读报告（oracle 写 `out/tests.json`，具体路径实现自定）。

## 3. hooks.json 契约

```json
{ "hooks": { "<事件名>": [ { "matcher": "<可选, string>",
                             "hooks": [ { "type": "command", "command": "<非空>" } ] } ] } }
```

- 顶层对象含 `hooks` 映射；事件名 ⊆ Claude Code 文档白名单（全集见 spec.md §5，取证 code.claude.com/docs/en/hooks，2026-09-30）。
- handler `type` ∈ `{command, http, mcp_tool, prompt, agent}`；本资产口径只用 `command`。
- 本资产的**绑定口径**：`PostToolUse` + matcher `Write|Edit` + 两个 command handler（`pii_guard.py` 先、`validate_output.py` 后），命令用 `${CLAUDE_PROJECT_DIR}` 定位（参照 oracle/hooks.json）。runner 只校验「合法 + 白名单 + 形状 + command 非空」，不强制绑定内容与顺序。

## 4. 依赖

- Python ≥ 3.9（`sys.stdout.reconfigure`）；Windows/Linux 均可（oracle 在 Windows 实测）。
- `python-docx` 必需（clean.docx 生成 + .docx 校验）；`python-pptx` 仅当实现包含 .pptx 校验分支时需要（本机已装，但无 fixture、runner 不断言）。
- 除此之外零依赖（标准库 json/re/subprocess/pathlib）。

## 5. 评测契约（eval/runner.py）

```bash
python skillfactory/v3/assets/office-guard-hooks/eval/runner.py [<被测产物根>] [<参照产物根>]
```

- 默认（与 spec.md §5 一致，runner 内写死）：被测根 `<asset>/package`，参照根 `<asset>/oracle`。
- 根解析规则（spec.md §5，写死）：传入根含全部必备文件 → 原样评测；非空但缺 → 向上 ≤3 级解析最近含 `run_tests.py`+`hooks.json` 的祖先（`resolved_*` 字段透明记录）；空目录/不存在 → 不解析、判红。
- 输出：stdout 打印一个 JSON 对象 `{"runner", "tested_root", "reference_root", "resolved_tested_root", "resolved_reference_root", "ok", "checks":[{"id","name","passed","detail"}…]}`。
- 退出码：7 项 check 全过 → exit 0；任一失败 → exit 1。
- check 清单（id 固定）：`root-resolution` / `reference-baseline` / `structure` / `fixtures-generated` / `self-suite` / `invalid-json-stdin` / `hooks-json-config`。
