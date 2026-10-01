# office-guard-hooks / oracle

可独立 CLI 测试的 Claude Code hook 参照实现：产物校验 + PII 扫描。

## 布局

```
oracle/
├── hooks/
│   ├── validate_output.py   # 产物校验：存在/非空/UTF-8/docx|pptx 可打开
│   └── pii_guard.py         # 文本 PII 正则扫描：手机号 / 18位身份证
├── hooks.json               # Claude Code hook 配置示例（PostToolUse 绑定）
├── run_tests.py             # 自测入口：全 fixtures 组合断言 exit code
├── tests/
│   ├── gen_fixtures.py      # fixtures 生成器（幂等）
│   └── fixtures/            # good.txt bad_empty.txt bad_encoding.txt pii.txt clean.docx corrupt.docx
└── out/tests.json           # 自测报告（由 run_tests.py 产出）
```

## 运行

```bash
cd oracle
python tests/gen_fixtures.py   # 生成/刷新 fixtures
python run_tests.py            # 实跑两个 hook × 全 fixtures，写 out/tests.json
```

## Hook 语义（Claude Code 约定）

- stdin 收一个 JSON 对象：`file_path`（本简化 schema）或 `tool_input.file_path`（真实 schema）均支持。
- `exit 0` = 通过；`exit 2` = 阻断，stderr 原因回传给模型；本实现不使用其他非零码。
- 单脚本独立冒烟：

```bash
echo '{"tool_name":"Write","file_path":"tests/fixtures/bad_empty.txt"}' | python hooks/validate_output.py   # exit 2
echo '{"tool_name":"Write","file_path":"tests/fixtures/pii.txt"}'      | python hooks/pii_guard.py          # exit 2
```

## 范围决策

- `validate_output.py`：无 `file_path` → exit 0 放行（没东西可校验）；文件缺失/为空/非 UTF-8（文本类）/docx|pptx 打不开 → exit 2。
- `pii_guard.py`：只扫文本类；office/二进制跳过；非 UTF-8 不可扫 → 警告后 exit 0（结构问题归 validate_output）；命中 → exit 2，stderr 列 `path:line` + 脱敏样本（不回显完整 PII）。
- 规则仅正则 + 数字边界 lookaround：手机 `(?<!\d)1[3-9]\d{9}(?!\d)`，身份证 `(?<!\d)\d{17}[\dXx](?!\d)`；18 位身份证不会被手机号规则二次命中。
- stderr 消息用 ASCII，避免 Windows 管道 GBK 编码问题（脚本内部已强制 UTF-8 reconfigure 双保险）。
