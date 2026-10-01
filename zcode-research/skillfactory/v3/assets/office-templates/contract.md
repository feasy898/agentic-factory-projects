# contract.md — 中文办公模板技能 模块契约（冻结）

- 版本：1.0（冻结于 2026-09-30）
- 效力：本文件冻结**对外接口**。接口之内（docx 生成细节、内部模块划分、代码组织）实现自由。
- 语义基准：行为语义以 `spec.md` 为准；冲突时以 spec.md 为语义权威。

---

## 1. package/ 必须包含的文件

```
package/
├── SKILL.md                      # 必备结构见 §4
├── scripts/
│   └── gen_doc.py                # 唯一入口脚本（文件名固定），CLI 见 §2
└── requirements.txt              # 至少：python-docx>=1.1
```

- 允许 `package/` 内有其他内部模块/资源文件，但**不得改变 §2/§3 的对外接口**。
- 入口脚本必须可直接以 §2 命令运行（允许内部 import 同目录模块）。
- 被测产物根约定为 `package/out/<模板>/case<N>/`（单元相对名与参照 `oracle/out` 一致，供 runner 配对）。

## 2. scripts 命令行契约（冻结）

```
python package/scripts/gen_doc.py --template <周报|请示函|会议通知|工作总结> --data <数据.json> --outdir <输出目录>
```

| 参数 | 必填 | 语义 |
|---|---|---|
| `--template` | 是 | 四类文书类型之一，恰为 `周报` / `请示函` / `会议通知` / `工作总结` 四个汉字名 |
| `--data` | 是 | 数据 JSON 文件路径（UTF-8，顶层为对象；字段表见 spec §3.3） |
| `--outdir` | 是 | 输出目录；不存在则递归创建 |

**退出码**：

| 码 | 条件 | 行为 |
|---|---|---|
| 0 | 成功（含必填缺失等数据边界，按 spec F1–F6 记账） | stdout 打印人读摘要（格式自由）；写入 §3 两个产物 |
| 2 | `--template` 非法；`--data` 文件不存在；JSON 解析失败；JSON 顶层非对象 | stderr 打印中文错误信息，**不产生产物、不建产物目录** |

- 不允许其他退出码语义；未捕获异常导致的崩溃按实现质量问题处理，不算合法契约行为。

## 3. 产物契约（<outdir> 内，文件名与 schema 冻结）

恰含 2 个文件（与 oracle 完全同名）：

| 文件 | 冻结点 |
|---|---|
| `文书.docx` | 版式按 spec §4（V1–V8）：A4 GB/T 9704 版心、居中黑体二号标题、顶格称谓（请示函/会议通知）、正文 firstLineChars=200 仿宋三号 28 磅固定行距、落款右对齐右空两字、必填缺失 `____` 占位；内容全部由输入推导，**禁止当前时间/随机内容** |
| `fields.json` | 顶层与 summary 键集合**完全等于** spec §6 所列（可判定：键集合相等）；字段语义与计数自洽同 spec §5/§6；UTF-8、`ensure_ascii=false` |

**确定性（MUST）**：同输入连跑两次，`fields.json`（除 `outputs` 键外）逐字节一致，`文书.docx`
解析后的段落文本/版式属性一致（spec §8 D1；zip 条目时间戳允许不同）。

**安全（MUST）**：任何解析候选 docx 的代码须按 spec §11 拒绝 DOCTYPE/ENTITY XML、不启用外部实体。

## 4. SKILL.md 必备结构

SKILL.md 必须包含以下小节（顺序不限、标题措辞可调，内容缺一不可）：

1. **名称与描述**：一句话说明"四类中文事务文书 → GB/T 9704 风格 docx + 字段填充台账 fields.json"。
2. **何时使用 / 何时不用**：使用场景（周报、请示、会议通知、工作总结的规范化成文）；不用场景
   （对应 spec §12 非目标：模板定制、pdf 转换、红头公章等）。
3. **输入要求**：四类模板字段表（spec §3.3）、必填/选填与列表语义（spec §5 F1–F6）。
4. **用法**：与 §2 完全一致的命令行示例（--template/--data/--outdir、退出码 0/2）。
5. **产物说明**：2 个文件清单 + fields.json 字段表（spec §6）。
6. **版式规范**：逐条引用 spec.md 规则编号（V1–V8），保证口径可追溯。
7. **错误处理**：§2 的退出码表与四种非法输入示例（spec §7 C2）。
8. **环境依赖**：Python 3.12+、python-docx 版本、Windows 假设、字体声明说明（spec §12）。

## 5. eval/ 契约（冻结）

- `eval/golden.json` 结构固定：`{"skill", "eval_inputs":[{"case","input","output"}],
  "ab_tasks":[{"id","instruction","input","rubric":[]}]}`；`eval_inputs` 恰 8 条（四类各 2 case），
  `input/output` 用**资产根相对路径**（如 `oracle/inputs/周报/case1.json`、`oracle/out/周报/case1`）；
  `ab_tasks` 恰 5 条。
- `eval/runner.py` 命令行契约（冻结）：

```
python eval/runner.py <被测产物根> <参照产物根>
# 例：python eval/runner.py package/out oracle/out        # 常规评测
# 自校验（无参数时的写死默认）：oracle/out oracle/out      → 全过 exit 0
```

  两参数均可省略，缺省值写死为 `<资产根>/oracle/out`（相对 runner 脚本定位）。
- runner 检查项（固定六类，输出 `{"ok", "tested", "reference", "checks":[{"name","pass","detail"}]}`）：
  1. `units_found` / `reference_dir_has_units`：被测/参照产物根恰含 8 个期望单元
     `<模板>/case{1,2}`，每单元恰含 `文书.docx` + `fields.json` 两个文件；
  2. `docx_opens_safe`：docx 的 XML 条目无 `<!DOCTYPE`/`<!ENTITY`（spec §11），python-docx 可打开；
  3. 版式要素（spec §4）：`layout_title_centered`（V2）、`layout_salutation_flush_left`（V3）、
     `layout_body_indent`（V4）、`layout_signature_right`（V5）；
  4. `fields_json_self_consistent`：spec §6 S1–S3 键集合与计数自洽；
  5. `fields_match_docx`：fields.json 与 docx 实际内容一致（title 相等、filled 值在文中出现、
     必填缺失处有 `____`）；`boundary_reported`：必填缺失正确记账且占位（F1/F4），选填缺失不误记必填（F2/F4）；
  6. `field_fill_agreement_ge_90pct`：与参照产物按 spec §10 口径的字段填充一致率 ≥90%。
- 全部通过 → 打印上述 JSON 且 **exit 0**；任一失败 → 同样打印 JSON（失败项 `pass=false`）且 **exit 1**。
- runner 自身确定性：不含时间/随机源，同一输入两次运行输出一致。

## 6. 冻结与变更管理

- §1 文件清单、§2 CLI、§3 产物名与 fields.json schema、§4 SKILL.md 结构、§5 eval 结构与检查项 =
  **冻结接口**。
- 实现自由区：docx 内部 XML 写法、样式组织、fields.json 中自由文本字段（如 stdout 摘要、outputs 路径
  写法）、代码组织。
- 破坏性变更：必须升本文件版本号，并同步修订 spec.md、golden.json、runner.py 三处，在变更记录注明
  日期与原因。eval 只增不删：golden.json 既有条目与 rubric 不为通过评测而放宽。
