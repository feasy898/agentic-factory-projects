# spec.md — 办公 MCP 配置包（mcp-office-pack）行为规格

- 版本：1.0（固化于 2026-09-30）
- 语义权威：本文是行为语义的唯一权威；`contract.md` 只冻结对外接口与结构，冲突时以本文为准。
- 依据：本文全部规则提炼自 `oracle/`（参照包：`mcp.office.json` + `docs/` + `validate.py` +
  `run_samples.py`）的**实测行为**。oracle 作者实测环境（2026-09-30）：Windows x64（windev-01）/
  Python 3.12.10 / Node v22.23.2 / npm 10.9.8 / uvx 0.12.15；本次固化复测记录见附录 A
  （全部命令为本资产固化时实跑）。

---

## 1. 目标

把「办公场景（文件 / Office 三件套 / 浏览器自动化 / 搜索）可用的 MCP server」固化为可分发的
配置包，含三件套：

1. **curated 配置清单** `mcp.office.json`：可直接并入 Claude Code `.mcp.json` 的 `mcpServers`
   模板（标准字段）+ 包级元数据与选型溯源字段（`_` 前缀与自定义字段）；
2. **接入手册** `docs/<name>.md`：每个 server 一份，含安装前提 / 配置步骤 / 常用调用 / 注意事项；
3. **自带校验器与样例实跑器**：`validate.py`（结构 / 密钥 / 手册对应自检）与
   `run_samples.py`（对每条 entry 做真实 MCP 协议握手）。

做到：密钥零真值（一律 `${VAR}` 占位符，启用时经环境变量注入）、场景覆盖矩阵齐全
（文件 / Excel / Word / PPT / 浏览器 / 搜索 六格至少各一）、条目可溯源（目录实录 URL +
CATALOG 行号）、全套产物可程序逐条判定。

## 2. 术语与目录约定

| 术语 | 含义 |
|---|---|
| **资产根** | `skillfactory/v4/assets/mcp-office-pack/`（本文件所在目录） |
| **参照包（oracle）** | `<资产根>/oracle/`；含 `mcp.office.json`、`validate.py`、`run_samples.py`、`docs/`、`out/` |
| **被测包（package）** | `<资产根>/package/`（候选配置包，结构见 contract §1，与参照包同构） |
| **包根** | 一个直接含 `mcp.office.json`、`validate.py`、`docs/` 的目录；被测包根 / 参照包根均此结构。runner 参数给到包根下的子目录（如 `oracle/out`）时，若其父目录是包根则自动上溯一级（仅一级，contract §2） |
| **条目（entry）** | `mcpServers` 对象的一个键值对；键 = name，值 = entry 对象 |
| **场景槽位（slot）** | 六格固定覆盖矩阵：`文件` / `Excel` / `Word` / `PPT` / `浏览器` / `搜索` |

## 3. 配置清单 mcp.office.json 规范

### 3.1 顶层

- 恰含 `mcpServers`（非空对象）与元数据键；oracle 另含 `_meta`（对象，含 `pack` / `version` /
  `target` / `comment` / `placeholder_policy` / `catalog_source` / `scenario_scope`）。
  元数据键自由扩展，`mcpServers` 键名冻结。
- UTF-8，JSON 可解析。

### 3.2 条目字段表（name → entry，oracle 10 条实录见 §8）

| 字段 | 必备 | 约束 |
|---|---|---|
| `type` | 是 | ∈ {`stdio`, `http`} |
| `command` | stdio 必备 | 非空字符串（可执行名，如 `npx` / `uvx`） |
| `args` | stdio 必备 | 字符串数组 |
| `url` | http 必备 | 非空字符串（远程 MCP 端点） |
| `env` | 是 | 对象（可为空 `{}`）；密钥类值只写 `${VAR}` |
| `secret_env` | 是 | 字符串数组：声明 env 中哪些键是密钥占位；无密钥也要给空列表 |
| `description` | 是 | 非空字符串 |
| `enabled` | 是 | 布尔 |
| `scenario` | 是 | 非空字符串；槽位判定依据之一（§4 S2） |
| `catalog` | 是 | 对象；必备 `record_url`（http/https URL）与 `form`（非空形态注记）；推荐 `section` / `catalog_line` |
| `doc` | 是 | 手册相对路径；缺省语义为 `docs/<name>.md`（oracle 10 条全部显式给出） |

### 3.3 name 规范

`^[a-z][a-z0-9\-]{1,63}$` 且在 `mcpServers` 内唯一（oracle：filesystem / excel / word /
powerpoint / google-workspace / gmail-official / playwright / excel-npm / tavily / context7）。

### 3.4 密钥政策（零真值，MUST）

- `secret_env` 声明的每个键，其 env 值必须保持 `${VAR_NAME}` 占位形态（正则
  `^\$\{[A-Z][A-Z0-9_]*\}$`）。
- 配置全文 + 全部 env 值不得命中 11 条密钥真值正则族（§6 C1 no_real_secrets 所列）。
- oracle 实录：google-workspace 声明 `GOOGLE_OAUTH_CLIENT_ID/SECRET`、tavily 声明
  `TAVILY_API_KEY`，均为占位符；真密钥不入包。

### 3.5 目录溯源（curated 的可判定锚点）

- 每条 `catalog.record_url` 必须是 http/https URL，且为该条目录实录的权威来源页；
  oracle 全部同步写 `catalog_line`（`skillfactory/v2/CATALOG.md:<行号>`，行号为 2026-09-30 时点）。
- oracle 溯源对照：filesystem→`:187`（A4.1）、excel→`:198`、excel-npm→`:199`、word→`:200`、
  powerpoint→`:201`、google-workspace→`:202`、gmail-official→`:203`（A4.3）、context7→`:209`、
  tavily→`:214`、playwright→`:215`（A4.4）。
- 手册正文必须含本条 `record_url`（§5）。

### 3.6 选型实录（oracle 踩坑，已写入手册与配置，候选可对照）

- `powerpoint`：PyPI `office-powerpoint-mcp-server` 2.0.x 可执行名为 `ppt_mcp_server` 且未钉死
  `mcp` 依赖，拉到 mcp 2.x 即崩（`ModuleNotFoundError: mcp.server.fastmcp`）→ 配置加
  `--with "mcp<2"`（oracle `mcp.office.json` powerpoint.args 实录）。
- `excel-npm`：npm 无 scope 的 `excel-mcp-server`（维护者 lichard）不是 negokaz 的包，Windows
  启动器缺 pandas 崩溃 → 用 `@negokaz/excel-mcp-server`（`docs/excel-npm.md`「包名陷阱」节实录）。
- 原候选 cloudflare/playwright-mcp 经官方 README 核实仅 Workers 部署 / 远程 SSE 形态、npm 包无
  bin 无法本地实跑 → 按 CATALOG「两维护者版本并行收录」先例换成可实跑的微软官方
  `@playwright/mcp` 与 negokaz 版。

## 4. 场景覆盖矩阵（S1–S3，逐条程序可判）

- **S1 六格固定**：`文件`、`Excel`、`Word`、`PPT`、`浏览器`、`搜索`；每格至少 1 条
  entry 覆盖（矩阵齐全）。
- **S2 槽位判定规则（冻结）**：对 entry 的 `(name, scenario)`，满足任一关键词即占该格
  （name 检索大小写不敏感）：

| 槽位 | scenario 含 | name（小写）含 |
|---|---|---|
| 文件 | `文件` | `file` |
| Excel | `Excel` | `excel` |
| Word | `Word` | `word` |
| PPT | `PPT` / `PowerPoint` / `幻灯片` | `powerpoint` / `ppt` / `slide` |
| 浏览器 | `浏览器` | `playwright` / `browser` / `puppeteer` |
| 搜索 | `搜索` | `search` / `tavily` |

- **S3 与参照等价**：被测覆盖的槽位集合 ⊇ 参照覆盖的槽位集合。**条目与参照同名不做要求**——
  允许整包换成不同 server 实现，但六格场景必须补齐（换实现不换场景）。
- oracle 覆盖实录（按 S2 规则对 oracle 10 条计算）：文件=filesystem；Excel=excel、excel-npm；
  Word=word；PPT=powerpoint；浏览器=playwright；搜索=tavily；六格各 ≥1。
  google-workspace / gmail-official / context7 为槽位外补充条目（办公协同 / 文档检索），
  不占格也不影响判定。

## 5. 手册规范（docs/，D1–D3，逐条程序可判）

- **D1 一一对应（双向）**：每条 entry 的 `doc`（缺省 `docs/<name>.md`）文件存在；
  `docs/` 下每个 `.md` 恰被一条 entry 引用（无缺失、无孤儿）。oracle：10 条 ↔ 10 份。
- **D2 必备四小节**：手册正文含 `安装前提`、`配置步骤`、`常用调用`、`注意事项` 四个小节标题；
  正文 ≥200 字符。oracle 10 份实测全部满足。
- **D3 目录实录 URL**：手册正文含本条 `catalog.record_url`（oracle 各手册头部
  「目录实录」行）。

## 6. validate.py 行为规则（C1–C4，均已实测）

- **C1 七项检查，id 固定**：`json_valid`、`fields_complete`、`names_unique`、`no_real_secrets`、
  `placeholders_intact`、`docs_exist`、`artifacts_exist`。其中 `no_real_secrets` 的 11 条正则族
  （oracle `validate.py:32-44`）为：tavily `tvly-…`、OpenAI 系 `sk-…`、GitHub `gh[pousr]_…`、
  fine-grained `github_pat_…`、Google `AIza…`、OAuth client secret `GOCSPX-…`、Google access
  token `ya29.`、AWS `AKIA…`、Slack `xox[baprs]-…`、32 位以上十六进制串、43 位以上 base64 形态串。
- **C2 产物**：写 `out/validate.json`，schema 见 contract §3；`summary.all_green == true`
  当且仅当全部 check `pass` 且 checks 非空。
- **C3 退出码**：全绿 exit 0，任一失败 exit 1（oracle 实测：7/7 全绿 → exit 0，附录 A-1）。
- **C4 参数**：`--config`（缺省脚本同目录 `mcp.office.json`）、`--out`（缺省
  `out/validate.json`），均相对脚本所在目录定位（BASE）；裸跑 `python validate.py` 必须可直接工作。

## 7. run_samples.py 行为规则（R1–R4，oracle 实测）

- **R1 stdio 条目**：启动进程，发送 `initialize`（protocolVersion `2025-03-26`）→
  `notifications/initialized` → `tools/list`；收到 id==1 合法 result 即协议握手成功
  （status=pass），记录 `serverInfo` / `protocolVersion` / 工具数。
- **R2 http 条目**：POST `initialize` 到远端端点；HTTP 200 + 合法 result → pass；HTTP
  401/403、JSON-RPC error code −32001/−32002、或响应前 800 字符含 `oauth` →
  `pass_auth_required`（端点活性证实、要求 OAuth，计入通过）；其余 → fail。
- **R3 占位符哑值注入**：实跑时 `${VAR}` 以哑值替换——以 `_DIR` / `_PATH` / `_ROOT` 结尾的
  变量替换为真实存在的临时目录（否则 filesystem 类 server 拒绝启动），其余替换为
  `oracle-probe-dummy`；**绝不使用真实密钥**。
- **R4 产物与退出码**：写 `out/samples.json`（逐条 status + 证据 + elapsed_s）；exit 0
  当且仅当全部条目 status 以 `pass` 开头。oracle 预置记录（`out/samples.json`，2026-09-30
  10:11）：10/10 pass——stdio 8 条握手成功（filesystem=secure-filesystem-server 0.2.0、
  excel=excel-mcp-server 1.1.1、word=Word Document Server 4.0.10、powerpoint=ppt-mcp-server
  1.30.0/37 工具、google-workspace=google_workspace 4.0.10、playwright=Playwright 1.64.0-alpha、
  excel-npm=0.12.0-SNAPSHOT、tavily=0.2.22），http 2 条 initialize 返回合法 result
  （gmail-official=StatelessServer/ESF 匿名可达、context7=Context7 4.1.1）。

## 8. oracle 条目清单（10 条实录，槽位按 §4 S2 计算）

| name | type | 槽位 | 要点 |
|---|---|---|---|
| filesystem | stdio (npx) | 文件 | MCP 官方参考 Filesystem server，`${OFFICE_FS_ROOT}` 授权目录 |
| excel | stdio (uvx) | Excel | haris-musa 版，`EXCEL_FILES_PATH` 沙箱目录，26 工具 |
| word | stdio (uvx) | Word | GongRzhe 版（上游 2026-03-03 归档，PyPI 仍可装），54 工具 |
| powerpoint | stdio (uvx) | PPT | `--with "mcp<2"` 钉版本（§3.6），37 工具 |
| google-workspace | stdio (uvx) | —（补充） | OAuth 2.1 PKCE，密钥占位符 ×2 |
| gmail-official | http | —（补充） | 官方远程端点，匿名 initialize 可达，OAuth 在工具调用层 |
| playwright | stdio (npx) | 浏览器 | 微软官方 @playwright/mcp，accessibility snapshot |
| excel-npm | stdio (npx) | Excel | @negokaz scope 包（§3.6 陷阱），7 工具 |
| tavily | stdio (npx) | 搜索 | `TAVILY_API_KEY` 占位符 |
| context7 | http | —（补充） | 远程文档检索端点，匿名 initialize 可达 |

## 9. 评测口径（runner，接口冻结见 contract §4）

runner 对被测包根做四类判定（参照包根用于 §4 S3 等价比对）：

1. **被测包自带校验器全绿**：裸跑 `python validate.py`（cwd=被测包根）exit 0，且
   `<被测根>/out/validate.json` 满足——`summary.all_green==true`、summary 计数与 checks 自洽、
   C1 七个 id 齐全且全部 pass（防「零检查假绿」）；
2. **配置可解析**：`mcp.office.json` 合法且 `mcpServers` 非空；
3. **场景覆盖矩阵齐全**：六格每格 ≥1（§4 S1/S2）；
4. **手册与配置条目一一对应**：§5 D1 双向对应。

条目与参照重合不做要求；场景覆盖必须 ⊇ 参照（§4 S3）。全过打印 JSON 且 exit 0，
任一失败打印 JSON（失败项 `pass=false`）且 exit 1。

## 10. 边界与非目标

- **不做工具调用实跑**：`run_samples.py` 止步于协议握手 + `tools/list`；google-workspace 与
  tavily 的握手用哑值占位密钥启动（真 OAuth key / API key 不在包内，工具调用层才需真值）。
- **gmail-official 实际调工具**需 Google Workspace Developer Preview 资格，本包不保证、不评测。
- **上游维护状态不构成失败**：word / powerpoint 上游仓库已归档（2026-03-03）但 PyPI 包可装可跑，
  选型注记已写入手册；归档与否不是 runner 判定项。
- **平台**：Windows 优先（`npx`/`npm` 的 `.cmd` shim 解析为 Windows 实现）；不保证其他平台。
- **不评测**：手册文案质量（只判 §5 结构必备项）、server 性能/延迟、工具调用正确性、
  条目数量上限（≥覆盖六格即可）。
- **不含 `package/`**：本资产固化 spec / contract / eval；候选包由实现方按 contract §1 自建。

---

## 附录 A：本 spec 固化时的实测记录（2026-09-30，本机实跑）

1. `python oracle/validate.py` → 7 项 check 全部 PASS，`summary.all_green=True`，**exit 0**
   （与 oracle 预置 `out/validate.json` 一致：7/7）。
2. `grep` 扫 `oracle/docs/*.md`：10 份手册全部含 安装前提/配置步骤/常用调用/注意事项 四小节，
   长度 1749–2548 字符（均 ≥200）。
3. `python oracle/run_samples.py --timeout 300 --out out/samples-recheck.json` → 首轮 9/10：
   google-workspace 握手超时（>300s，含首次拉包时间，复跑时与其他进程争用包缓存）；**以
   `--timeout 600` 复跑 → 10/10 pass、exit 0**（`out/samples-recheck.json`，2026-09-30T11:01
   落盘，serverInfo 与预置记录逐一吻合）。教训：workspace-mcp 冷拉包可达数分钟，实跑超时
   建议给足 600s（oracle 预置 `out/samples.json` 为同日 10:11 的 10/10 pass 原始记录，未被覆盖）。
4. 槽位规则（§4 S2）对 oracle 10 条的映射：文件×1、Excel×2、Word×1、PPT×1、浏览器×1、搜索×1、
   不占格×3（google-workspace / gmail-official / context7）——与 §8 表一致（由 eval/runner.py
   对 oracle 的绿检实测复核，见附录 A-1 同批运行）。
5. runner 红绿矩阵（`python eval/runner.py <被测> oracle`，构造样例为 oracle 副本改笔，验毕即删）：
   `oracle oracle` → 全过 exit 0（含无参数写死默认；连跑两次输出逐字节一致=确定性）；
   空目录 → exit 1（5 项全败：validate.py 不在盘/配置不在盘/槽位与对应不可算/缺参照槽位）；
   删 powerpoint 条目+手册 → exit 1（`scenario_coverage_matrix` 报「槽位缺失 ['PPT']」、
   `coverage_equivalent_to_reference` 报「被测缺参照槽位: ['PPT']」）；
   删 tavily.md → exit 1（`docs_one_to_one` 报「条目手册缺失: docs/tavily.md」，
   且被测自带 validate.py 同步判 docs_exist 未过=双重拦截）；
   假校验器（零 check 写 all_green=true）→ exit 1（`package_validate_all_green` 报
   「checks 缺失或为空（零检查不允许判绿）」=防假绿拦截生效）；
   六格条目全部改名（file-server/sheets-excel/docx-word/ppt-engine/browser-mcp/web-search）
   → 仍 exit 0（换实现不换场景，条目重合不做要求的等价通道实测可用）。
