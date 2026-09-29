# 政务 AI 安全网关 · 公开版部署与运行说明（README.public）

放在任何大模型服务前面的"闸"：接口兼容 OpenAI 的 `/v1/chat/completions`，
入站先识别政务敏感信息并替换为**可还原占位符**，按敏感程度路由（互联网模型 /
政务云模型 / 直接拦截），出站加 AI 生成标识、代答拒答与内容风控；审计库只存
脱敏内容，全程可审计、可出具保密自查报告。

> 依赖安装记录见 `DEPS.txt`（导出工具自动生成，供部署者对照）；
> 仓库结构与模块说明见 `README.md`。

## 1. 环境要求

- Python ≥ 3.12（开发与验收均在 3.12 完成）；**本地模式全离线可跑**，不依赖
  任何外部模型服务与 API key。
- 可选：Docker / docker compose（见 §4，⚠ 未实测声明见该节）。

## 2. 一键起 · 本地模式（全离线，mock 上游）

两路 mock 上游把收到的 prompt **原样回显**，可完整体验
识别 → 脱敏 → 路由 → 还原 → 审计 全链路（密级样例被拦、敏感材切政务云腿）：

```bash
# 1) 安装（核心依赖清单与实测版本见 DEPS.txt 第二、三节）
python -m venv .venv
./.venv/Scripts/pip install -e ".[dev]"        # POSIX: .venv/bin/pip

# 2) 配置
cp .env.example .env                           # 至少填写 MASK_KEY（32 字节 hex）
#   演示部门 key（config/dept_keys.yaml 只存 sha256，明文仅演示用）：
#   县政府办 dk_1a2b3c4d / 民政局 dk_5e6f7a8b / 某镇 dk_9c0d1e2f

# 3) 起两路 mock 上游（:8901 互联网 / :8902 政务云；Windows 下用两个终端分别执行）
./.venv/Scripts/python -m gateway.mock_upstream --host 127.0.0.1 --port 8901
./.venv/Scripts/python -m gateway.mock_upstream --host 127.0.0.1 --port 8902

# 4) 起网关（:9000；默认每条路由绑定第一个上游，即两路 mock）
./.venv/Scripts/python -m gateway --host 127.0.0.1 --port 9000
```

冒烟验收（exit 0 = 通过）：

```bash
./.venv/Scripts/python -m pytest evals/m0_infra
```

体验（含身份证/手机的请求 → 上游只见占位符 → 客户端拿到还原答案）：

```bash
curl http://127.0.0.1:9000/v1/chat/completions \
  -H "Authorization: Bearer dk_1a2b3c4d" -H "Content-Type: application/json" \
  -d '{"model":"mock-chat","messages":[{"role":"user","content":"干部张三，身份证460022199003071234，电话13800138000，帮我看下低保材料"}]}'
```

聊天页（`http://127.0.0.1:9000/webui`）提供"上游实际收到内容"双屏对照：
客户端看到的是还原后的原文，上游收到的是全占位符版本。

## 3. 真实模式（接本地真实大模型 :9004，环境变量）

`config/app.yaml` 预置 `internet_real` / `govcloud_real` 两个真实上游 profile，
同指 `http://127.0.0.1:9004/v1`（本机 OpenAI 兼容大模型服务坐标），以两把不同
key 模拟「互联网 / 政务云」两路上游：

```bash
# 1) .env 填两把 key（服务侧只校验在位性；值不入任何配置文件/代码/日志）
REAL_LLM_KEY=<...>
GOVCLOUD_LLM_KEY=<...>

# 2) 保证本机 :9004 有 OpenAI 兼容服务（自有部署或隧道均可）；
#    端口不同则改 config/app.yaml 中两 profile 的 base_url。

# 3) 切换路由绑定：默认每条路由取第一个上游（两路 mock）。把 INTERNET /
#    GOVCLOUD 两路由的 mock 上游条目注释掉（或将 *_real 条目移到最前），
#    网关即切真实上游——网关代码与客户端零改动。
```

说明：真实模型仓库名/来源属部署环境信息，不入仓库（配置中只有中性模型名
`local-chat-8b` 与 `:9004` 端口坐标，key 只经 `.env` 环境变量注入）。

## 4. docker compose（⚠ 未实测声明）

> **如实声明：本项目构建环境无 Docker，`docker-compose.yml` 未在容器环境
> 实测**，属文档级交付物：镜像 tag、容器内安装命令、服务发现方式请按实际
> 环境调整后再用。容器内访问宿主机 `:9004` 真实上游需用 `host.docker.internal`
> （Linux 需 `extra_hosts` host-gateway，文件内已按此书写）；config 中两路
> mock 的 `127.0.0.1:8901/:8902` 同理需改为 `host.docker.internal` 或改用
> host 网络模式（文件头注释有说明）。

```bash
cp .env.example .env    # 填 MASK_KEY
docker compose up       # 起 mock-internet(:8901) / mock-govcloud(:8902) / gateway(:9000)
```

## 5. 公开导出说明（_BY_DEPLOYER_ 与 DEPS.txt）

本仓库由源仓库经 `ops/export_public.py` 导出，三点部署者需知：

- **导出面**：仅携带 git 跟踪文件（`.env`、`data/`、`tmp/` 等本地工件排除）；
  导出后跑严格档名称检查（含 yaml/toml/json 配置档），零命中才交付。
- **_BY_DEPLOYER_ 占位**：命中内部词表的依赖行已从 `pyproject.toml` 整行剔除；
  `config/*.yaml`、`config/install_check.json` 中需部署方自行提供的内部依赖
  坐标以 `_BY_DEPLOYER_` 占位——YAML/JSON 仍可解析，相关功能（PDF 清理引擎、
  OCR 引擎、合成语料库）未配置前**显式失败**，识别/脱敏/路由/审计主链路不受
  影响。注入位置与语义对照见 `DEPS.txt` 第四节。
- **不分发件**：内部依赖冻结清单与第三方参考件克隆脚本不随公开仓分发；
  保留依赖项的实测版本与安装命令见 `DEPS.txt`。

## 6. 安全注记

- `/v1/chat/completions` 与 `/internal/*` 均需部门 Key（`Authorization: Bearer dk_***`）；
  `/internal/*` 响应含识别明细与还原原文，只应经本机管理面（127.0.0.1）或
  受控内网访问，**不得暴露公网**。
- 审计库只存脱敏内容：入库前硬闸断言 + 全库文件 bytes 级扫描双保险；
  密钥只经环境变量 / `.env` 注入，不入任何配置文件与代码。
