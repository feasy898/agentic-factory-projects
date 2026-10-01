# SKILL.md — mcp-office-pack 配置包：安装与裁剪方法

> 办公场景（文件 / Excel / Word / PPT / 浏览器 / 搜索）可用的 MCP server 精选配置包。
> 选型同源 `skillfactory/v2/CATALOG.md`（2026-09-30 时点），全部 10 条经真实 MCP 协议握手 /
> HTTP initialize 实测可达（实测环境：Windows x64 / Python 3.12.10 / Node v22.23.2 /
> npm 10.9.8 / uvx 0.12.15；逐条 serverInfo 见 `mcp.office.json` 的 `_meta.verified`）。

## 包结构

```
package/
├── mcp.office.json    # 配置清单：mcpServers 模板（标准字段）+ _meta 元数据与选型溯源
├── validate.py        # 自校验器（七项检查，全绿 exit 0）
├── run_samples.py     # 样例实跑器（可选件）：对每条 entry 做真实协议握手，写 out/samples.json
├── SKILL.md           # 本文件
├── docs/<name>.md     # 每条 entry 一份手册：安装前提/配置步骤/常用调用/注意事项
└── out/               # 产物：validate.json（结构自检）+ samples.json（实跑记录）
```

六格场景覆盖：文件=`filesystem`；Excel=`excel`、`excel-npm`（两维护者版本并行）；
Word=`word`；PPT=`powerpoint`；浏览器=`playwright`；搜索=`tavily`。
槽位外补充：`google-workspace`（办公协同一体化）、`gmail-official`（官方远程邮件）、
`context7`（库文档检索）。

## 一、安装（并入 Claude Code `.mcp.json`）

1. **并入条目**：把 `mcp.office.json` 的 `mcpServers` 对象整体（或裁剪后的子集，见下节）
   并入你的 `.mcp.json` 的 `mcpServers` 字段。字段均为标准 MCP 配置（`type/command/args/url/env`），
   外加包级溯源字段（`secret_env/scenario/catalog/doc`，宿主不识别会忽略，建议保留以便自检）。

2. **注入占位符真值**（环境变量，勿写进任何文件）：

   | 变量 | 类别 | 用于 | 说明 |
   |---|---|---|---|
   | `OFFICEPACK_FILES_ROOT` | 本地目录 | filesystem | 必须真实存在，否则 server 拒绝启动 |
   | `OFFICEPACK_EXCEL_DIR` | 本地目录 | excel | 工作簿沙箱，建议先建目录 |
   | `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | **密钥** | google-workspace | Google Cloud OAuth 客户端凭据 |
   | `TAVILY_API_KEY` | **密钥** | tavily | tavily.com 的 key（服务按量计费） |

   PowerShell 示例：`$env:OFFICEPACK_FILES_ROOT="D:\office-docs"`；
   cmd 示例：`set TAVILY_API_KEY=tvly-...`。密钥类条目（google-workspace / tavily）协议握手
   不需要真值，真值只在工具调用层需要——可先空占位装好再补。

3. **重启会话**加载配置，用各手册「配置步骤」一节的挂载确认法逐条验证
   （`docs/<name>.md` 与条目一一对应，排障先读对应手册的「注意事项」）。

## 二、裁剪（只保留要用的场景）

裁剪 = 改配置 + 对齐手册目录，两步缺一不可（本包校验器强制"条目 ↔ 手册"一一对应）：

1. **删条目**：从 `mcp.office.json` 的 `mcpServers` 删掉不要的键。注意场景底线：
   六格（文件/Excel/Word/PPT/浏览器/搜索）至少各留一条，删 `tavily` 前确认没有别的
   `search` 名条目顶替搜索槽位。
2. **删手册**：同步删除 `docs/` 下对应条目的手册（如删 `powerpoint` 条目则删
   `docs/powerpoint.md`），否则自检报"孤儿手册"。
3. **软裁剪替代**：不想删文件可把条目 `"enabled": false`（条目与手册对应关系保持，
   宿主不启用该 server）。
4. **复检**：`python validate.py` 必须回到全绿（exit 0）再交付。

典型裁剪样例：只做本地文档处理 → 留 `filesystem/excel/word/powerpoint`；
做联网调研 → 加留 `playwright/tavily/context7`；涉密内网 → 删 `playwright/tavily`
（两个出网面）与 `gmail-official/context7`（远程端点）。

## 三、自检

```
python validate.py                # 裸跑：校验包内 mcp.office.json + docs/，写 out/validate.json
python validate.py --config <path> --out <path>   # 缺省相对本脚本目录定位
```

七项检查：`json_valid` / `fields_complete` / `names_unique` / `no_real_secrets` /
`placeholders_intact` / `docs_exist` / `artifacts_exist`。全绿 exit 0，任一失败 exit 1；
报告落 `out/validate.json`（schema：`checks[] + summary{total,passed,failed,all_green}`）。

可选的连通性实跑（哑值注入，绝不用真密钥）：

```
python run_samples.py --timeout 600   # stdio 握手 / http initialize 逐条实测，写 out/samples.json
```

- `${VAR}` 占位符按哑值注入：`_DIR/_PATH/_ROOT` 结尾变量替换为真实临时目录（filesystem 类
  server 否则拒绝启动），其余替换为 `oracle-probe-dummy`；真值密钥永不参与实跑。
- http 条目判活双口径：HTTP 200 + 合法 initialize result = `pass`；401/403/响应含 oauth 证据
  = `pass_auth_required`（端点活性证实，计入通过）。
- 退出码 0 = 全部条目 status 以 `pass` 开头。workspace-mcp 冷拉包可达数分钟，超时给足 600s。

## 四、升级与再验证

- 版本漂移：`@latest` 类条目（playwright/excel-npm/tavily）升级后重做协议握手；
  `powerpoint` 的 `--with "mcp<2"` 依赖钉子在确认上游兼容 mcp 2.x 前不要摘。
- 密钥纪律：本包任何文件都不该出现真值密钥（11 条正则族由 `no_real_secrets` 把关）；
  换 key 只改环境变量，不动包。
- 上游状态注记：`word`/`powerpoint` 上游仓库 2026-03-03 起归档（PyPI 仍可装可跑，已实测），
  归档不是失败判据但意味着没有上游修复，升级需自查。
