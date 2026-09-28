# llmgw spec（chat-completions 通用客户端）

> 状态：frozen，**正在收紧中（另一代理修改 python/llmgw）——以 eval 命令为最终真源**。
> 对照 `python/llmgw/{client,selftest,__init__}.py` 逐行核验于 2026-09-28。
> 仅依赖 Python 标准库（urllib/json/base64/http.client），零第三方依赖；代码零厂商/端点/模型名硬编码。

---

## 1. 职责与边界

**做**：chat-completions 协议（业界通用 HTTP 形态）的客户端——普通对话、图片 base64 输入、JSON 模式
（`response_format=json_object` + schema 提示注入）、超时/重试/多模型降级、错误归因。

**不做**：不做任何具体厂商适配（一切 env 注入）；不含提示词工程（那是 director 的职责）；无生产调用方
（现状如实记录——director/repair-loop 暂缓，见 model-adapter 页）。

## 2. 环境变量契约（冻结，默认值在此）

| 变量 | 必填 | 默认 | 语义 |
|---|---|---|---|
| `PF_LLM_BASE_URL` | 是 | — | 服务根地址，需含版本前缀（如 `https://host/v1`；**仅主机名时自动补 `/v1`**） |
| `PF_LLM_API_KEY` | 否 | — | `Authorization: Bearer <key>`（本地推理服务常免鉴权） |
| `PF_LLM_MODEL` | 是 | — | 主模型名 |
| `PF_LLM_FALLBACK_MODELS` | 否 | 空 | 备用模型，逗号分隔，按序降级（与主模型去重保序成 model_chain） |
| `PF_LLM_TIMEOUT` | 否 | **30** 秒 | 单次 HTTP 超时 |
| `PF_LLM_MAX_RETRIES` | 否 | **2** | 单模型最大重试次数（耗尽后降级下一模型） |
| `PF_LLM_BACKOFF` | 否 | **0.8** 秒 | 指数退避基数：`min(backoff * 2^attempt, 8.0)` 封顶 |
| `PF_LLM_ALLOW_LOCAL` | 否 | 关 | SSRF 防线放行开关：非回环的非公网地址（私网/链路本地/保留，含云元数据 169.254.x）任何情况下都在发请求前 ConfigError 拒绝；回环地址（127.x/::1）默认同样拒绝，置 1 仅供离线 mock 自测放行（范围仅限回环） |

端点拼接 `endpoint_for(base)`：去尾 `/` → path 为空时补 `/v1` → 追加 `/chat/completions`；
scheme 必须 http(s)，否则 `ConfigError`。
SSRF 防线：`chat()` 与请求汇入点 `_post()` 双处在发出任何网络字节前校验 host
（DNS 解析后逐 IP 断言）：非回环的非公网地址一律 `ConfigError` 拒绝（无放行开关）；
回环地址默认拒绝，`allow_local=True`（env `PF_LLM_ALLOW_LOCAL`）放行且范围仅限回环。

## 3. 对外契约（Gateway / chat）

```python
gw = Gateway(base_url=None, api_key=None, model=None, fallback_models=None,
             timeout=None, max_retries=None, backoff=None,
             allow_local=None)   # 缺省逐项回退 env；allow_local=SSRF 防线放行（默认拒绝本地/内网端点）
resp = gw.chat(messages, images=None, json_schema=None, *, json_mode=False,
               timeout=None, max_retries=None, backoff=None, extra=None)
text_of(resp) -> str          # choices[0].message.content；缺失抛 LLMError
json_of(resp) -> dict         # 解析助手文本为 JSON；失败抛 LLMError
chat(messages, ...)           # 模块级便捷入口（临时 Gateway）
Client = Gateway              # 别名
```

**模块级 `chat()` 便捷函数参数表（冻结）**：`chat(messages, images=None, json_schema=None, **call_kwargs)`，
其中 `call_kwargs` 逐项透传 `Gateway().chat(...)`：

| 参数 | 类型/默认 | 语义 |
|---|---|---|
| `messages` | 非空序列 | 必填，规则同 Gateway.chat |
| `images` | None / 图片列表 | 见 §3.1 |
| `json_schema` | None / dict | 开 JSON 模式 + 提示注入 |
| `json_mode` | False | 仅开 JSON 模式不注 schema |
| `timeout` | None → env(30) | 逐次覆盖 |
| `max_retries` | None → env(2) | 逐次覆盖 |
| `backoff` | None → env(0.8) | 逐次覆盖 |
| `extra` | None / dict | 透传请求体（如 temperature） |

- 行为 = **每次调用临时构造 `Gateway()`**（配置每次现读 env），再发起一次 chat；不共享连接/状态。

- `messages`：**非空**序列，每项含 `role`/`content`（原样透传，逐项浅拷贝）；空/非序列 → `ValueError`，
  元素缺 role/content → `ValueError`（带下标）。
- **json_schema 提示注入（schema 的请求内形态 = 文本序列化）**：system 消息插入位置 = 首条已是 system 则
  index 1，否则 index 0；内容精确形态 ＝ 固定中文前缀 + `json.dumps(json_schema, ensure_ascii=False)`
  （紧凑单行、无缩进、保持 dict 原键序）：

  ```
  只输出一个 JSON 对象：不要解释、不要 markdown 围栏，字段与类型必须符合以下 JSON Schema：
  {"type": "object", "required": ["ok"], ...}
  ```

  `json_schema is not None 或 json_mode=True` 时请求体加 `response_format={"type":"json_object"}`。
  **schema 只走提示注入、不进 response_format**（json_object 协议本身不携带 schema 字段——通用兼容做法；
  mock selftest 的 `schema_seen` 断言即验证提示随请求到达）。
- **JSON 剥围栏（json_of 容错）**：strip 后以 ``` 开头 → `strip("`")` → lstrip → 若前 4 字符小写为 "json"
  则去掉 → `json.loads`；失败抛 LLMError（含原文前 200 字）。
  **json_of 不校验返回类型**：解析成功即**原样返回**——助手输出合法 JSON 数组/字符串/数字时会得到非 dict，
  dict 期望由调用方自行校验（仅解析失败抛 LLMError）。
- `extra`：透传请求体额外字段（如 temperature）。

### 3.1 图片输入的三种形状（+1 透传）

| 形状 | 示例 | 处理 |
|---|---|---|
| 裸 base64 字符串 | `"iVBORw..."` | 默认按 `image/png` |
| `(mime, base64)` 元组/列表 | `("image/webp", "...")` | 指定 mime |
| 字典 | `{"mime_type": "...", "data": "..."}`（兼容 `mime` 键） | 指定 mime |
| 完整 data URL | `"data:image/png;base64,..."` | 原样透传 |

- base64 先做紧凑化（去空白）+ `b64decode(validate=True)` 校验，非法抛 `ValueError`。
- 并入规则：最后一条是 user 且 content 为纯文本 → 升级为 `[text, image_url...]` 数组；否则追加一条仅含图片的
  user 消息。`image_url.url` 为 `data:<mime>;base64,<data>`。

## 4. 重试 / 降级矩阵（冻结）

| 错误类别 | 触发 | 行为 |
|---|---|---|
| 可重试 `_Transient` | 网络异常/超时、HTTP **408/409/429/5xx**、200 但响应体非 JSON 或缺 `choices` | 同模型指数退避重试至多 max_retries 次；耗尽 → 降级下一模型 |
| 跳模型 `_SkipModel` | HTTP **404**（模型不存在） | 不重试，直接降级下一模型 |
| 致命 `_Fatal` | 其余 4xx（400/401 参数或密钥问题） | 立即抛 `LLMError`（不再重试或降级） |

- 全链失败：`LLMError("全部模型均失败：主 → 备...")`，属性 `{status, model, attempts[]}`；
  `attempts` 每项 `{model, attempt, status, error}`；`summary()` 输出人读清单。
- **attempts 序号基与退避指数的精确关系（冻结）**：`attempt` 为 **0 基**（0..max_retries，0 = 首次尝试）。
  第 `attempt` 次 `_Transient` 失败后，若不是最后一次（`attempt == max_retries` 则不再 sleep、直接降级），
  睡眠 `min(backoff * 2**attempt, 8.0)` 秒——默认 backoff=0.8 时等待序列为 **0.8s(attempt0 失败后) →
  1.6s(attempt1 失败后) → 3.2s…** 封顶 8s。`_SkipModel`(404) 首次即记录 attempt=0 并降级（不 sleep）；
  `_Fatal` 记录后立即抛出（不 sleep）。
- 错误信息提取：响应体 JSON 的 `error.message`（dict 或 str）优先，否则截 200 字节原文。

## 5. 行为规格（边界——错误类型速查）

- `messages` 空或非序列、元素缺 role/content → **`ValueError`**（参数校验，非 LLMError）。
- 缺 `PF_LLM_BASE_URL` / `PF_LLM_MODEL` → **`ConfigError`**（chat() 时抛；模块级 `chat` 亦同）。
- `PF_LLM_BASE_URL` 非 http(s) → **`ConfigError`**（`endpoint_for` 内抛）。
- **数值型 env 非法**（`PF_LLM_TIMEOUT`/`PF_LLM_MAX_RETRIES`/`PF_LLM_BACKOFF` 不是数字）→ 构造 `Gateway`
  时抛**原生 `ValueError`**（`float()`/`int()` 未捕获直传）——如实记录：它不是 `ConfigError`/`LLMError`。
- 401（密钥错）→ `_Fatal` → `LLMError(status=401, attempts=[...])`。
- 客户端超时后服务端写回失败 → 服务端 `handle_error` 静默（selftest 的慢模型路由即此场景）。
- 响应非 dict 或 `choices` 空 → `_Transient`（视为服务端异常，可重试）。

## 6. eval：精确命令与通过线

```bash
# 在 python/ 目录（或已装 venv 任意目录）
python/.venv/Scripts/python.exe -m llmgw.selftest     # → 6 项全过，打印 SELFTEST PASS，exit 0
```

6 项（内置 mock 服务，全程仅 127.0.0.1，零外网）：
① env 驱动/鉴权/端点拼接（含错误密钥→401、缺 env→ConfigError）；② 普通对话回声 + usage；
③ JSON 模式（response_format 到达 + schema 提示到达 + json_of 解析）；④ 图片 base64（两种形状，mock 解码
比对字节一致；坏 base64 被客户端拦截）；⑤ 500→自动重试成功（恰两次请求）；⑥ 慢模型超时→降级
（降级耗时 < 慢模型时长；慢模型恰被尝试 1 次）。

- 红线扫描（gate_phase0 门项 4）：`python/llmgw/**/*.py` 对厂商端点/厂商名黑名单正则
  （词表权威 = `scripts/gate_phase0.py` 的 `VENDOR_ENDPOINT_RE`，本 spec 不复制 枚举词表）零命中。
- **禁止事项**：不许 mock 被测物（selftest 的 mock 是服务端替身，客户端本体真实走 HTTP）；不许把任何厂商
  端点写进代码或默认值（一切 env 注入）。真实连通性由主会话注入 key 后手测一次（非 eval 项）。

## 7. 重生成注意事项

- **最小 eval 环境（第二批再生试点实录）**：llmgw 零第三方依赖，再生试点目录**不含 `.venv`、不含
  gate_phase0** 也能裁定——eval 只需 `python -m llmgw.selftest`（任一 Python 3 可跑，实测 3.12.10；
  `from llmgw import ...` 是包内相对导入，须以包形态运行：`python/` 在 cwd 或包父目录入 sys.path）。
  本 spec 中写 `python/.venv/Scripts/python.exe` 全路径是**本机约定，非环境依赖**。
- 零第三方依赖：重建时只允许标准库（保持 `pip -r requirements.txt` 之外无新增）。
- selftest 的 mock 用 `ThreadingHTTPServer` + 端口 0（系统分配）；路由按请求内容（RETRY-MARKER /
  IMAGE-MARKER / response_format / 慢模型名）而非 path。
- 收紧期间的变更以 `python -m llmgw.selftest` + gate_phase0 门项 4 双绿为准。
- 变更史：commit `4eb5975`（M6 冻结）→ 收紧提交见 git log python/llmgw。
