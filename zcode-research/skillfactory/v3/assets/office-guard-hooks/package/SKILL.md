---
name: office-guard-hooks
description: 办公护栏 hook 包：模型用 Write/Edit 落盘交付物时，两个 PostToolUse hook 自动做产物结构校验（fail-closed）与 CN 手机号/18 位身份证 PII 拦截（fail-open）。含 hooks.json、两个 hook 脚本与自测套件。
---

# office-guard-hooks — 办公护栏 hook 包

## 1. 这是什么

把本包挂进 Claude Code 后，每当模型用 **Write/Edit** 工具把交付物写盘，两个
PostToolUse hook 自动把关：

| 脚本 | 职责 | 失败哲学 |
|---|---|---|
| `hooks/validate_output.py` | 产物**结构校验**：存在 / 非空 / 文本类严格 UTF-8 / `.docx`、`.pptx` 可打开 | **fail-closed**：结构问题 exit 2 阻断 |
| `hooks/pii_guard.py` | 文本产物 **PII 正则扫描**：CN 手机号 / 18 位身份证 | **对不可扫对象 fail-open**：放行并 stderr 说明；命中才 exit 2 阻断 |

两 hook 同时挂载时整体不漏拦：pii_guard 放过的一切不可扫对象（缺失、空、
非 UTF-8、二进制后缀），validate_output 都会兜住并阻断。

## 2. 安装

前置依赖：Python ≥ 3.9（用到 `sys.stdout.reconfigure`）；`python-docx`
（clean.docx 生成与 `.docx` 校验必需，`pip install python-docx`）。除此之外
零依赖（标准库 json/re/subprocess/pathlib）。Windows/Linux 均可。

步骤（目标仓库根 = `${CLAUDE_PROJECT_DIR}`）：

1. 把 `hooks/` 下两个脚本拷到目标仓库，例如 `<project>/hooks/`
   （保持文件名不变，或与第 2 步的 command 路径保持一致）。
2. 把 `hooks.json` 的内容合并进 Claude Code 配置
   （项目的 `.claude/settings.json`，或 `claude` 会话的 hooks 配置处）。
   本包自带口径：`PostToolUse` × matcher `Write|Edit` × 两个 command handler
   （`pii_guard.py` 在前、`validate_output.py` 在后），命令经
   `${CLAUDE_PROJECT_DIR}` 相对项目根定位：

   ```json
   {
     "hooks": {
       "PostToolUse": [
         {
           "matcher": "Write|Edit",
           "hooks": [
             { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/hooks/pii_guard.py\"" },
             { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/hooks/validate_output.py\"" }
           ]
         }
       ]
     }
   }
   ```

3. 验证安装：

   ```bash
   echo '{"tool_name":"Write","file_path":"README.md"}' | python hooks/validate_output.py   # 期望 exit 0, stderr 含 OK
   printf '手机号13812345678' > /tmp/x.txt
   echo '{"tool_name":"Write","file_path":"/tmp/x.txt"}' | python hooks/pii_guard.py        # 期望 exit 2
   ```

## 3. 运行语义（两 hook 共同的 CLI 契约）

| 项 | 约定 |
|---|---|
| stdin | 一个 JSON 对象（Claude Code hook payload）。`file_path` 双 schema 兼容：顶层 `file_path` 优先，回落 `tool_input.file_path` |
| stdout | **恒为空**（任何结局都不向模型上下文注入内容） |
| stderr | 诊断 / 阻断原因，回传模型 |
| exit 0 | 通过（或无事可做，放行） |
| exit 2 | 阻断，stderr 原因回传模型 |

不使用其他非零码（Claude Code 语义中为 non-blocking error）。非法 JSON /
非对象 payload 两脚本都**优雅 exit 2 并说明，绝不抛 Traceback**。

### 3.1 validate_output.py 判定顺序（首条命中即终局）

1. stdin 非法 JSON → exit 2（stderr 含 `not valid JSON`）
2. JSON 合法但非对象 → exit 2（`must be an object`）
3. payload 无 file_path → exit 0（`nothing to validate`）
4. 文件不存在 → exit 2（`does not exist`）
5. 路径存在但非 regular file → exit 2（`not a regular file`）
6. 0 字节文件 → exit 2（`empty`）
7. `.docx` 无法被 python-docx 打开 → exit 2（`python-docx`）；`.pptx` 同逻辑（`python-pptx`）
8. 非办公后缀的字节流不是严格 UTF-8 → exit 2（`not decodable as UTF-8`）
9. 全部通过 → exit 0（stderr 含 `OK`）

### 3.2 pii_guard.py 判定顺序

1. stdin 非法 JSON / 非对象 → exit 2（stderr 含 `FAIL`）
2. 无 file_path → exit 0（`nothing to scan`）
3. 文件缺失 / 非 regular file → exit 0（`not a scannable file`；存在性归 validate_output）
4. 后缀 ∈ 跳过集合 `{.docx,.pptx,.xlsx,.zip,.pdf,.png,.jpg,.jpeg,.gif,.exe,.dll}` → exit 0（`skipped`）
5. 0 字节 → exit 0（`empty file`）
6. 非 UTF-8 → exit 0（`WARNING` + `not scanned`）
7. 命中正则 → exit 2；stderr 逐条 `  <path>:<行号>: [phone|cn-id] <脱敏>`，
   按（行号, 类别）排序，**不回显完整 PII**：
   - 手机 `(?<!\d)1[3-9]\d{9}(?!\d)`，脱敏 = 前 3 位 + `****` + 后 4 位
   - 身份证 `(?<!\d)\d{17}[\dXx](?!\d)`，脱敏 = 前 4 位 + `*`×(len−8) + 后 4 位
   - 数字边界 lookaround 保证 18 位身份证不会被手机号规则二次命中
8. 干净文本 → exit 0（`no PII`）

## 4. 自定义扩展点

- **新增 PII 规则**：在 `hooks/pii_guard.py` 顶部加编译好的正则（建议带
  `(?<!\d)…(?!\d)` 数字边界），在 `scan()` 里 append `hits` 并给出类别名与
  脱敏函数；命中输出与排序逻辑自动生效。
- **调整脱敏格式**：改 `mask_phone()` / `mask_cn_id()`；原则是不回显完整 PII。
- **扩充二进制跳过集合**：改 `hooks/pii_guard.py` 的 `SKIP_SUFFIXES`。
- **扩展结构校验**：在 `hooks/validate_output.py` 的后缀分支里加新办公格式
  （参照 `.pptx` 分支：专用库打开失败 → exit 2）。
- **变更触发面**：改 `hooks.json` 的 `matcher`（如加 `MultiEdit`）或事件名
  （须为 Claude Code 文档白名单内事件，如 `PreToolUse` / `PostToolUseFailure`）。
- **多文件 / 目录递归**：当前只处理 payload 给定的单个 file_path，属非目标；
  如需批量可在 handler 外再包一层遍历脚本。

## 5. 自测

```bash
python tests/gen_fixtures.py   # 幂等生成 6 个 fixtures（--force 强制重写）
python run_tests.py            # 12 用例：validate_output 7 + pii_guard 5
                               # 全过 exit 0；报告写 out/tests.json
```

fixtures：`good.txt`（合法 UTF-8 无 PII）、`bad_empty.txt`（0 字节）、
`bad_encoding.txt`（GBK 字节）、`pii.txt`（第 2 行手机、第 3 行身份证、
第 4 行座机不命中）、`clean.docx`（有效文档，每次重建）、`corrupt.docx`
（`.docx` 后缀垃圾字节）。

## 6. 边界与非目标

- 只处理 payload 给定的**单个 file_path**；不做目录递归、不删改文件、不改写内容。
- PII 仅覆盖 CN 手机号 + 18 位身份证两类；不承诺邮箱/银行卡/护照等。
- `.docx|.pptx` 只验「可打开」，不验内容合规；`.xlsx` 不在结构校验范围（仅被 pii_guard 跳过）。
- exit 2 是唯一阻断通道。
