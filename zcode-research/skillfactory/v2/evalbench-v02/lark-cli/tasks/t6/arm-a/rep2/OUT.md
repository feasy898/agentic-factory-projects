# lark-cli 连续 5 次调用输出解读与处置方案（t6 / arm-a / rep2）

> 判定总原则：**以 stderr 上的机器可读 JSON 契约为准（`ok` 字段 + `error` 对象），退出码作交叉验证**。两者一致即按契约处置；不一致按异常上报。以下每条判定均直接依据任务给出的输出摘录（stdout/stderr 归属、退出码、JSON 字段）。

## 速查总表

| 调用 | 输出流 | 退出码 | `ok` | 成败判定 | 错误类型 | 可自动重试？ | 核心下一步 |
|---|---|---|---|---|---|---|---|
| A | stdout | 0 | `true` | ✅ 成功 | — | —（无需） | 读取 `data.guid` 交付后续步骤 |
| B | stderr | 3 | `false` | ❌ 失败 | `authorization` / `missing_scope`（code 99991679） | **否**（确定性错误） | 引导用户开通 `base:record:create` scope，授权后原样重跑 |
| C | stderr | 4 | `false` | ❌ 失败 | `network`（connect refused） | **是**（`retryable:true`，等 ≥2s） | 退避重试，超限后上报 |
| D | stderr | 10 | `false` | ❌ 被安全门拦截 | `confirmation`（高危待确认） | **否**（须先征得人同意） | 同意后：原始 argv 末尾追加 `--yes` 重跑；拒绝则放弃 |
| E | stderr | 2 | `false` | ❌ 失败 | `validation` / `command_unavailable` | **否**（确定性错误） | 上报；升级/更换 lark-cli 分发或改用等价命令 |

---

## 一、逐条解读

### A（stdout，退出码 0）

```json
{"ok":true,"identity":"user","data":{"guid":"docx#V3mQ8x"},"meta":{"count":1}}
```

**① 成功还是失败：成功。**
依据（双信号一致）：
- 结构化字段 `"ok": true`，且携带业务数据 `data`（`guid: "docx#V3mQ8x"`）与元信息 `meta`（`count: 1`，返回 1 条）；
- 退出码 0，与 `ok:true` 相互印证；写在 stdout 而非 stderr，也符合「正常结果走 stdout」的契约。

**② 下一步动作：**
- 无需错误处理、无需重试、无需用户确认、无需上报。
- 正常路径：从 `data` 取业务结果（本例 guid=`docx#V3mQ8x`）传给后续步骤；可用 `meta.count` 校验返回条数是否符合预期。

---

### B（stderr，退出码 3）

```json
{"ok":false,"identity":"user","error":{"type":"authorization","subtype":"missing_scope","code":99991679,"message":"permission denied","hint":"guide user to grant missing scopes","missing_scopes":["base:record:create"]}}
```

**① 成功还是失败：失败。**
依据：`"ok": false` + 退出码 3（非零）+ 写在 stderr；错误对象 `type:"authorization"`、`subtype:"missing_scope"`、Lark 权限错误码 `99991679`，message 为 `permission denied`。

**② 下一步动作：**
- **脚本自身不可自动重试。** 依据：错误对象中没有 `retryable:true`，且授权/权限类错误是确定性的——在权限实际变更之前，原样重跑必然复现同一失败（`hint` 也明确指向「引导用户授权」而非重试）。
- **读取并使用 `error.missing_scopes`**（= `["base:record:create"]`）：把「缺少哪个权限」明确呈现给用户/管理员，引导其在 Lark 开放平台为应用开通 `base:record:create` scope 并完成授权/发布。
- 用户完成授权后，**用原始 argv 重跑同一命令**即可，无需改参数。
- 该次失败应记录/上报（含 `error.type`、`code`、`missing_scopes`），便于审计与排障。

---

### C（stderr，退出码 4）

```json
{"ok":false,"identity":"user","error":{"type":"network","message":"dial tcp 1.2.3.4:443: connect refused","retryable":true,"retry_after_seconds":2}}
```

**① 成功还是失败：失败（瞬时网络故障）。**
依据：`"ok": false` + 退出码 4 + stderr；`type:"network"`，报文 `dial tcp 1.2.3.4:443: connect refused`（对端 443 端口拒绝连接）。

**② 下一步动作：**
- **可以自动重试**，依据是错误对象自带的重试契约：`"retryable": true` 且给出 `"retry_after_seconds": 2`——工具明确告诉调用方「可重试、等 2 秒」。
- 做法：**等待 ≥2 秒后重试同一命令**；工程上建议指数退避并设最大重试次数上限（避免对拒绝连接的对端持续打流量）；重试期间不需要用户介入。
- 若连续多次重试仍失败，停止重试并**上报/告警**（可能是对端宕机、地址错误或本机网络故障），不要无限循环。

---

### D（stderr，退出码 10）

```json
{"ok":false,"identity":"user","error":{"type":"confirmation","message":"high-risk action needs --yes","action":"delete view vewFGH and its config","risk":"irreversible deletion","hint":"append --yes to the end of your original argv after explicit user consent"}}
```

**① 成功还是失败：失败——但不是执行出错，而是被「高危操作确认门」拦截（详见概念题 Ⅱ）。**
依据：`"ok": false` + 退出码 10 + stderr；`type:"confirmation"`，待执行动作 `delete view vewFGH and its config`（删除视图 vewFGH 及其配置），风险标注 `irreversible deletion`（不可逆删除）。

**② 下一步动作（标准人机确认流程）：**
1. 识别为确认门后**立即阻断自动化**，把 `action`（要删什么）与 `risk`（不可逆删除）如实转述给用户，征求**明确同意**。此门必须由人拍板，无人值守脚本不得自行通过。
2. **用户拒绝** → 放弃该操作，任务标记为取消/阻塞并记录原因，不做任何形式的重试。
3. **用户明确同意** → 取本次调用的**原始 argv**，**仅在末尾追加 `--yes`** 后整体重跑（严格按 `hint`：`append --yes to the end of your original argv after explicit user consent`）；不得改动 argv 的其他部分。
4. 红线：**绝不允许脚本在未获同意时自动补 `--yes`**；不得把本次的 `--yes` 缓存/复用到后续其他高危调用；对不可逆操作建议留痕（谁、何时、同意了哪个动作）以满足审计要求。

---

### E（stderr，退出码 2）

```json
{"ok":false,"identity":"user","error":{"type":"validation","subtype":"command_unavailable","message":"command not available in this distribution"}}
```

**① 成功还是失败：失败（校验/环境类错误）。**
依据：`"ok": false` + 退出码 2 + stderr；`type:"validation"`、`subtype:"command_unavailable"`，message 明确说明「该命令在当前分发版本中不可用」。

**② 下一步动作：**
- **不可重试。** 依据：这是确定性的静态校验失败——所调用的子命令在当前 lark-cli 分发里根本不存在，错误对象无 `retryable` 字段，原样重跑只会复现同一结果。
- 属于**脚本/环境缺陷**，应上报，修复方向是改环境而非重试：
  - 核对所调子命令的拼写，以及当前 lcli 版本/分发是否支持该命令（用版本清单/`--help` 核对）；
  - 升级或更换为包含该命令的 lark-cli 分发，或改用当前版本支持的等价命令/API。

---

## 二、概念题

### Ⅰ. 为什么「用 code == 0 判断成功」是危险的？

1. **退出码与业务结果可能不一致，而「假成功」是最危险的一类 bug。** 退出码是进程层面的粗粒度信号，经过 shell 包装、管道、后台/跨机调用、信号 kill、跨平台差异（Unix 下退出码按 256 取模、Windows 下 `ERRORLEVEL` 语义不同）后可能丢失或被改写；个别工具版本还会在 API 层失败时仍然退出 0。只看 `code == 0`，脚本会把失败当成功继续往下跑，拿着空数据/脏数据产出错误结果——这种静默错误远比一次显式报错难排查。
2. **本工具的契约给了双信号，应以结构化字段为准、退出码只作交叉验证。** lark-cli 的机器可读契约是 JSON 里的 `"ok"` 字段（失败时还有结构完整的 `error` 对象）。正确姿势是：主判 `ok == true` 并校验关键业务字段（如 `data`、`meta.count`），再交叉核对退出码为 0；两者不一致时按异常上报。只信退出码，等于丢掉了契约里信息量最大、最不受运行环境影响的那一半。
3. **非零退出码≠普通失败，退出码语义是分层的，二元判断驱动不了处置分支。** 本例中退出码 3（缺权限→找用户开 scope）、4（网络→可退避重试）、10（高危→等人工确认）、2（命令不存在→改环境）对应**完全不同的后续动作**；`code == 0 / != 0` 无法区分它们。尤其是 10：它是设计出来的「暂停等人」，若被当成一般失败送进自动重试逻辑，要么死循环，要么（更糟）诱导脚本去自动加 `--yes` 绕过安全门，造成不可逆删除。
4. **`code == 0` 也不保证业务语义满足。** 即使 `ok:true`，仍需检查 `data` 是否为空、`meta.count` 是否符合预期。成功判定应当是「`ok` 字段 + 关键业务字段」的复合校验，退出码只是其中一票，单独一票不足以裁决。

### Ⅱ. 退出码 10 意味着什么？标准处理流程是什么？

**含义**：10 = 「高危操作待确认」门（confirmation gate）。工具识别到该命令将执行不可逆/高危动作（本例：删除视图 vewFGH 及其配置，`risk: irreversible deletion`），按安全设计**拒绝在缺少 `--yes` 时执行**，并通过 stderr JSON 告知需要人工明确同意。它不是执行出错，而是「故意暂停、等人拍板」；原样重试必然复现。

**标准处理流程**：
1. **识别**：解析 stderr JSON，确认 `type == "confirmation"`（并以退出码 10 交叉印证）。
2. **阻断并征求同意**：暂停自动化，把 `action`（要做什么）与 `risk`（风险等级）如实呈现给用户，请求明确同意。此门必须人在环路中，无人值守的脚本不得自行通过。
3. **分支处置**：
   - 用户不同意 → 终止该操作，任务置为「已取消/被阻塞」并记录原因；不得重试。
   - 用户明确同意 → 取本次**原始 argv，仅在末尾追加 `--yes`** 后整体重跑（遵循 `hint`）；不修改其他参数，不缓存/复用该标志。
4. **复核结果**：重跑后仍按通用契约判定（`ok` 字段 + 退出码交叉验证），确认操作真正落地。
5. **留痕审计**：对不可逆操作，记录同意主体、时间与具体动作内容，满足事后审计要求。
