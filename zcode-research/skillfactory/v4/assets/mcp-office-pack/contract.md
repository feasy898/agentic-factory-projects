# contract.md — 办公 MCP 配置包（mcp-office-pack）模块契约（冻结）

- 版本：1.0（冻结于 2026-09-30）
- 效力：本文件冻结**对外接口**。接口之内（校验器/实跑器的内部实现、手册文案、条目选型）实现自由。
- 语义基准：行为语义以 `spec.md` 为准；冲突时以 spec.md 为语义权威。

---

## 1. package/ 必须包含的文件

```
package/
├── mcp.office.json      # 配置清单（schema 见 spec §3；文件名冻结）
├── validate.py          # 自校验器（行为见 spec §6；裸跑 python validate.py 必须全绿）
├── docs/                # 手册目录：与 mcpServers 条目一一对应（spec §5 D1–D3）
└── out/                 # 产物目录（validate.py 写 out/validate.json；缺省由校验器自建）
```

- `run_samples.py` 为**可选件**：含它则必须满足 spec §7（stdio 握手 / http POST / 哑值注入 /
  `out/samples.json`）；不含它不判失败。
- 允许 `package/` 内有其他内部文件，但**不得改变 §2/§3 的对外接口**。
- `validate.py` 必须自包含定位：以脚本所在目录为 BASE 解析缺省 `mcp.office.json` 与
  `out/`（spec §6 C4），**不得依赖调用方 cwd**。

## 2. 命令行契约（冻结）

```
python package/validate.py [--config <path>] [--out <path>]
#   缺省：--config <脚本同目录>/mcp.office.json  --out <脚本同目录>/out/validate.json
#   退出码：0 = summary.all_green==true；1 = 任一 check 失败

python package/run_samples.py [--config <path>] [--out <path>] [--timeout <秒>]   # 可选件
#   缺省：--config/--out 同上规则，out/samples.json；退出码：0 = 全部条目 pass*

python eval/runner.py <被测包根> <参照包根>
#   例：python eval/runner.py package oracle        # 常规评测（被测=package，参照=oracle）
#   自校验（无参数写死默认）：oracle oracle          → 全过 exit 0
#   oracle/out oracle/out                            # 等价自检：包根下的子目录自动上溯一级
#   红检：python eval/runner.py <空目录> oracle      → 报失败 exit 1
```

- runner 两参数均可省略，缺省值写死为 `<资产根>/oracle`（相对 runner 脚本定位）。
- **包根别名（冻结）**：参数路径自身无 `mcp.office.json` 而其**父目录**有 → 上溯一级到包根
  （兼容把 `oracle/out` 这类产物子目录当包根传入的调用习惯）；仅此一级、不递归，
  空目录/无关目录不解析、照常判红。
- runner 以 `sys.executable` 裸跑 `<被测包根>/validate.py`（cwd=被测包根，无附加参数），
  读取 `<被测包根>/out/validate.json` 判定（spec §9 第 1 条）；超时 120 秒按失败处理。

## 3. 产物约定（<包根>/out/，schema 冻结）

| 文件 | 冻结点 |
|---|---|
| `out/validate.json` | 顶层键 `{"oracle","generated_at","config","checks","summary"}`；`checks` 为数组，每项含 `{"id","name","pass","detail","problems"}`；`summary` 恰含 `{"total","passed","failed","all_green"}` 且计数自洽（`total==len(checks)`、`passed+failed==total`、`all_green == (failed==0 且 total>0 且全部 pass)`）；七个必备 check id 见 spec §6 C1 |
| `out/samples.json`（可选件） | 顶层含 `{"samples","summary"}`；每个 sample 含 `name`、`status`（`pass`/`pass_auth_required`/`fail`）、证据字段（`server_info`/`http_status`/`verdict` 等）；`summary.passed==summary.total` 当且仅当 runner/人读判定全过 |

**密钥政策（MUST）**：`mcp.office.json` 全文 + 全部 env 值零真值密钥（spec §3.4 十一条正则族）；
`secret_env` 声明的键保持 `${VAR}` 占位形态。

**确定性（MUST）**：`validate.py` 对同一包根重复运行，除 `generated_at` 时间戳外判定结果一致；
`runner.py` 无时间/随机源，同一输入两次运行输出一致。

## 4. eval/runner.py 契约（冻结）

```
python eval/runner.py [<被测包根> <参照包根>]
输出：单个 JSON {"ok", "tested", "reference", "checks":[{"name","pass","detail"}]}
全过 → exit 0；任一失败 → 同样打印 JSON（失败项 pass=false）且 exit 1
```

检查项（五个，name 冻结；判定语义见 spec §4/§5/§9）：

| # | name | 判定 |
|---|---|---|
| 1 | `package_validate_all_green` | 裸跑 `<被测根>/validate.py` exit 0，且 `out/validate.json`：`summary.all_green==true`、summary 与 checks 计数自洽、七个必备 id（spec §6 C1）齐全且全部 pass |
| 2 | `config_json_valid` | `<被测根>/mcp.office.json` 可解析且 `mcpServers` 为非空对象 |
| 3 | `scenario_coverage_matrix` | 按 spec §4 S2 冻结规则计算，六格（文件/Excel/Word/PPT/浏览器/搜索）每格 ≥1 条 |
| 4 | `docs_one_to_one` | spec §5 D1：每条 entry 的 doc 存在，且 docs/ 下每个 .md 恰被一条 entry 引用（无缺失、无孤儿） |
| 5 | `coverage_equivalent_to_reference` | 参照包覆盖槽位集合 ⊆ 被测包覆盖槽位集合（spec §4 S3；条目重合不做要求） |

- 被测包根 / 参照包根均为「包根」结构（§1，参照包=oracle 同构）。
- runner **不 import、不执行**参照包与被测包的任何 Python 模块，唯一例外是按 §2 裸跑被测包
  自带的 `validate.py`。
- runner 自身确定性：不含时间/随机源；对缺失文件/目录/非法 JSON 一律记失败项，不崩溃。

## 5. 冻结与变更管理

- §1 文件清单与文件名、§2 三条命令行、§3 产物 schema、§4 五个检查项与输出 JSON 结构 =
  **冻结接口**。
- 实现自由区：`validate.py`/`run_samples.py` 内部实现、条目数量（≥六格覆盖所需）与选型
  （允许与 oracle 全部不同名，但槽位覆盖必须等价）、手册文案、`_meta` 扩展字段、
  `catalog` 推荐字段之外的附加字段。
- 破坏性变更：必须升本文件版本号，并同步修订 spec.md 与 runner.py，在变更记录注明日期与原因。
  eval 只增不删：runner 既有检查项与 spec 判定口径不为通过评测而放宽。
