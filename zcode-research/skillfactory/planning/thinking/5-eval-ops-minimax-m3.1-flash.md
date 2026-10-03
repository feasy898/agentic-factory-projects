# eval 执行运营 · 思考轨迹（MiniMax-M3.1-Flash · 2026-10-03）

> 镜头：本机「普通模型 + 资产 → 真实任务」eval 跑批体系怎么组织、怎么跑、跑多久、花多少、结果怎么变成资产迭代决策。
> 全部结论标注证据来源。凡「我本次实测」= 我在这个会话里亲手跑过并看到输出；凡「盘内」= 我本次读了仓库文件；凡「转引」= 仓库文档里记录的我未亲访的外部来源。
> **一条重要边界先说清楚：本会话 WebFetch 三次全部被 provider 拒绝（`Provider rejected the model request.`，分别试 arxiv.org/abs/2406.12045、其 v1、example.com），因此本轨迹没有任何一条我自己抓取的公开网页证据。所有公开标准引用均为盘内转引（EVAL-SPEC-v0.2.md 的【实访】条目），我标注为转引。**

---

## 1. 展开方法：我怎么拆解这个问题

### 1.1 拆成六个可独立证伪的子问题

原始问题「zcode 主 agent 如何在本机组织 eval 跑批」在信息上不够定形，我先把它切成六块，每块都要求自己能被一次命令证伪：

| # | 子问题 | 决定成败的是什么 |
|---|---|---|
| Q1 | **通道事实**：四个普通模型到底能不能在本机被程序化调用？ | 能用什么入口（工作流子代理 / CLI headless / 另一个 CLI），模型 ID 字符串怎么写 |
| Q2 | **跑批拓扑**：一个 run 内多模型并行，还是每族一个 run？ | 模型钉版是否可控、隔离是否成立 |
| Q3 | **任务包**：怎么组织「任务描述/输入素材/oracle/评分器」？ | 与 v5 `runner.py` 的复用/边界 |
| Q4 | **双轨评估**：过程 + 产物怎么拆？ | 什么证据进哪一轨，裁判判什么 |
| Q5 | **并发/超时/预算**：矩阵怎么排、多久、多大代价、失败怎么降级？ | 限流在哪一族、并发上限是多少 |
| Q6 | **看板与回归**：分数怎么存、跨版本怎么比、什么证据触发改资产？ | 决策规则能否写成可执行的门 |

### 1.2 信息源清单（按可信度降序）

1. **本机运行态数据库**（我发现的最高价值源）：`C:\Users\Administrator\.zcode\cli\db\db.sqlite`。里面有 `dwf_actor.resolved_model`（2708 行，每个工作流子代理实际跑在哪个模型）、`dwf_run`（401 次 run 的状态与并发上限）、`model_usage`（144,403 行逐请求：耗时/token/重试/错误类型）。这是**本机唯一的、机器级的、跨 3 个月的历史跑批遥测**，比任何文档声称都硬。
2. **zcode CLI 与 provider 配置**：`~/.zcode/cli/config.json`（v0.16.9 通道）、`~/.zcode/v2/provider_config.json`（桌面侧 new-provider/minimax 通道，被 `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` 环境变量指向）、`~/.kimi-code/config.toml`（Step 系）。
3. **仓库方法论**：`skillfactory/v2/standard/EVAL-SPEC-v0.2.md`（评测协议全文，430 行）、`skillfactory/REGISTRY.md`（18 资产台账 + 逐轮追加）、`v5/assets/*/eval/runner.py`（四个确定性评测器实物）、`v5/assets/hotwords/oracle/run_all.py`（生成器实物）、`classroom/rehearsal/round-1/record.md`（K-3 彩排记录）。
4. **BASELINE.md**（§2 能力总表、§3.6 zcode-research 基线卡、§7/§8 坑与维护建议）。
5. **本机命令实测**：`zcode --help/--version/skills list/mcp list/-p`、`kimi.exe --version`、两次 runner 自评计时、若干次 sqlite 聚合查询。

### 1.3 走过的弯路（记录下来，因为它们直接改变了结论）

- **弯路 1：把任务书给的通道清单当既成事实。** 任务书说「zcode 直连通道有 bigmodel、minimax、new-provider」。我先读 `~/.zcode/cli/config.json`，里面**只有 zai 与 builtin:bigmodel-coding-plan 两个 provider，没有 minimax、没有 new-provider**。差点据此写成「minimax 通道不存在」。随后发现 `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` 环境变量指向 `~/.zcode/v2/provider_config.json`，那里才有 new-provider(step) 与 minimax。**教训：桌面版与 CLI 版是两套 provider 配置体系，"zcode 的通道"这个说法本身不成立，必须指名是 CLI 通道还是桌面/工作流通道。**
- **弯路 2：以为工作流脚本里写了模型。** 读 `.zcode/workflow-drafts/盘点MiniMax-M3.1-Flash.dwf.ts` 全文 121 行，`agent("盘点员·MiniMax-M3.1-Flash", { system: PERSONA })` **没有任何模型参数**；再 grep 落盘的 `dwfrun-*.mjs`，也 grep 不到 model/subagent_model 字段。差点得出「工作流无法指定模型」的结论。最后是 `dwf_actor.resolved_model` 这张表推翻了它——模型是在 run 启动时被解析并记账的，脚本里不写。**教训：能力可能在运行时层而不在脚本层，先查记账表再下结论。**
- **弯路 3：在 Git Bash 里探 `/model`，被 MSYS 路径转换吃掉。** `zcode -p "/model"` 传进去的其实是 `C:\Program Files\Git\model`（Git Bash 把 `/` 开头参数当路径转换），模型还煞有介事地给我讲了一段 MSYS 路径转换原理。第二次加 `MSYS_NO_PATHCONV=1` 才拿到真答案：`/model` 是客户端内置命令，headless 下由客户端拦截，**并且它顺口报出了本次会话真实模型 = GLM-5.3 / provider `bigmodel-individual-coding-plan`**——这和 config.json 里写的 `GLM-5.3-Flash` 对不上。**教训：`D:\agent-knowledge\02` 那条 MSYS 坑是实打实的，不读会浪费一整轮探测。**
- **弯路 4：试图用 `zcode mcp connect` 挂 MCP 臂。** `zcode mcp list` 回「Unknown command: mcp」——`/mcp` 只是 TUI 斜杠命令，CLI 0.16.9 没有对应子命令。MCP 臂的挂载路径因此收窄（见 §2.4）。
- **弯路 5：想用 `zcode --model X` headless 选模型。** 直接回「Unknown option '--model'」。CLI 0.16.9 的 headless 入口没有模型开关（`--help` 全文我拉了两遍确认）。**教训：headless 选模型这件事在 CLI 层面是不通的，必须走工作流运行时或改共享配置。**

---

## 2. 关键推理链

### 2.1 Q1 通道事实：四个「普通模型」在本机的真实可达性（这一条改写了任务书的假设）

**考虑过的分支**

- (a) 全部四个都在 zcode 工作流里按 `subagent_model` 钉版跑。
- (b) 三个在 zcode 工作流里跑，第四个（Step-3.7-Flash）走 kimi CLI。
- (c) 全部走各自 CLI headless。
- (d) 缩减矩阵，用工作流已证可达的 step 模型替代 Step-3.7-Flash。

**实测证据**

`dwf_actor.resolved_model` 全表分布（2708 行）：

```
account:bigmodel-individual-coding-plan/GLM-5.3-Flash  1693
(None)                                                    394
account:bigmodel-start-plan/GLM-5.3-Flash                 136
account:bigmodel-individual-coding-plan/GLM-5.3           135
new-provider/step-router-v1                                 113
new-provider/step-5-preview                                 83
minimax/Minimax-M3.1-Flash-Preview                          76
minimax/MiniMax-M3                                           62
account:bigmodel-offpeak-idle-plan/GLM-5.3-Flash            14
minimax/MiniMax-M3.1-Flash-Preview                           2
```

- **分支 (a) 否决**：`Step-3.7-Flash` 在 `model_usage` 里 **0 行**、在 `dwf_actor` 里 **0 行**；`model_id like '%3.7%'` / `'%3.5%'` / `'%kimi%'` / `'%k3%'` 全部 0 命中。它只活在 `~/.kimi-code/config.toml:1`（`default_model = "stepfun-step-plan/step-3.7-flash"`，`max_context_size = 256000`）里。桌面 v2 provider 的 `personalModelIds` 是 `[step-5-preview, step-router-v1]`，没有 3.7。**Step-3.7-Flash 在本机不是 zcode 工作流可达的模型。**
- **分支 (c) 否决**：`zcode --model` 未知选项；`zcode -p "/model"` 被客户端拦截且明示要改 `config.json` 的 `model.main`。改共享配置文件 = 全局串行化，与「跑批」直接冲突。
- **分支 (b) 采纳（有保留）**：Step-3.7-Flash 走 `D:\tools\bin\kimi.exe`（实测 `kimi.exe --version` = **2.1.1**，注意 `D:\AGENTS.md` 第八节写的 0.41.0 已过期）。保留意见：kimi 的 `--output-format stream-json` 转录格式与 zcode 的不同，进同一评分流水线需要一个归一化器；且 kimi.exe 是 Electron 应用，`D:\AGENTS.md` 已注明「Git Bash 中可能无法直接运行，建议 PowerShell/cmd」——我的探测也印证了 Git Bash 传参会出问题（`/model` 那一幕）。
- **分支 (d) 作为降级预案保留**：若 kimi 通道在实施时不通，用 `new-provider/step-router-v1`（113 次子代理实跑、限流率 0.44%）顶替 Step-3.7-Flash 那一列，但**必须在报告里显式写「原定 Step-3.7-Flash 未覆盖，以 step-router-v1 代」**，不能静默换列。

**顺带挖到两个任务书没提、但对跑批极重要的事实**

1. **bigmodel 侧有三个不同的账号通道**：`bigmodel-individual-coding-plan`（1693 次）、`bigmodel-start-plan`（136 次）、`bigmodel-offpeak-idle-plan`（14 次）。这是**配额分池**，等价于同一模型的三份额度——排矩阵时应当把 GLM 那一列劈到三个账号上，而不是在一份配额里挤。
2. **模型 ID 字符串有大小写不一致的坑**：`minimax/Minimax-M3.1-Flash-Preview` 出现 76 次，`minimax/MiniMax-M3.1-Flash-Preview` 只有 2 次（我这次会话跑的就是后者）。同一个模型两种拼法都解析成功，但**钉版必须逐字抄 `dwf_actor.resolved_model` 的实际取值**，不能凭直觉拼——EVAL-SPEC §4.4 要求每轮落盘模型钉版五元组，拼错一个字母就是"钉版失败"。

**另一个必须上报的口径偏差**：headless `zcode -p` 实际跑的是 `GLM-5.3`（`bigmodel-individual-coding-plan`），而 `config.json:139` 写的是 `builtin:bigmodel-coding-plan/GLM-5.3-Flash`。**"配置文件里写的模型" ≠ "实际跑的模型"。** EVAL-SPEC §4.1 把 GLM-5.3-Flash 定标为全部评测臂的标准模型，这条定标与 headless 实测行为已经对不上，规划必须处理（要么显式钉 Flash 并验证，要么改钉 GLM-5.3 并升 evalbench 版本——§4.4-2 规定任一变更 ⇒ 版本 bump + 旧基线作废）。

### 2.2 Q2 跑批拓扑：三条路，选第三条

**考虑过的分支**

- (a) 单 run 内 N 个子代理，每个钉不同模型。
- (b) 每族一个独立 run（沿用 10-03 三路盘点的做法）。
- (c) 一个外部驱动脚本，按臂 spawn 独立 `zcode -p` / `kimi.exe -p` 进程。

**采纳 (c) 作为 MVP，(b) 作为全量矩阵；(a) 否决**

- **(a) 在本会话被硬性否掉**：`ListModels` 返回 `model_catalog_unavailable: this session cannot list models — the host did not provide a model catalog... Omit subagent_model on CreateWorkflow and AmendWorkflow; the workflow's subagents will run on the session model.`。同时 `ListWorkflowRuns` 返回 `workflow_introspection_unavailable`。**能力缺口，不是空配置**——意味着在「没有模型目录」的宿主上，钉版在语法层就不成立。
- **(a) 在有目录的宿主上成立**：`dwf_actor.resolved_model` 有 8 种取值、2708 行，说明按 actor 钉版是**被生产使用过的**能力，不是纸面功能。**结论不是"不能用"，而是"能用与否取决于启动 run 的那个会话有没有模型目录"——这是一个必须写进规划的启动前置条件。**
- **(b) 的问题**：工作流运行时把 bookkeeping 写进共享 db（`dwf_run` 已积累 401 行、跨多个项目），run 脚本还要在仓库 `.zcode/workflow-runs/` 落 `.mjs`（BASELINE §6-10 记的两份 46KB 生产 run）。**让 eval 跑批去挤这条公共管道，等于让评测产线和其他项目的编排互相干扰。**
- **(c) 的优势，逐条对应 EVAL-SPEC 的硬条款**：
  - §3.2-3 要求「每次运行为独立子代理会话（干净上下文）」→ 一臂一进程是最强的隔离形态，比子代理更彻底；
  - §4.3-1 要求「baseline 臂禁读资产，实现方式 = 工作目录物理隔离」→ 一臂一个 `--cwd` 树，隔离由文件系统保证而非靠约定；
  - 产物/转录落在自己的目录树里，天然可归档、可复评（延续 v5「归档学员产物可复评」的做法，README.md:23 / BASELINE §2-21）；
  - 崩溃、超时、限流都收敛在一个进程的退出码里，不需要解析工作流日志。

**(c) 的已知缺陷（必须诚实写进规划）**：进程级驱动拿不到 `dwf_actor.resolved_model` 这套记账，模型钉版要**自己**在臂目录里写一份 `model_pin.json`（EVAL-SPEC §4.4 五元组：模型 ID、provider baseURL、CLI/runtime 版本、日期、reasoning variant）。这是把工作流运行时替我们做的事自己重做一遍——**所以我建议 MVP 走 (c)，全量矩阵走 (b)，用 (b) 记账、用 (c) 隔离，两者不混。**

### 2.3 Q3 任务包：v5 runner.py 的复用与差异

**关键判断：runner.py 一个字都不改。**

依据不止是习惯，是三条硬证据：

1. `TASK.md:76` 明文红线：「禁止改评测阈值/判据凑绿（红路必须保持 exit 1——全卡信用底线）」。
2. BASELINE §2-20 记录 runner 的红路 fail-closed 是**四路独立实测过**的 A 级能力（缺失目录 → exit 1；篡改副本 → exit 1 并精确报 `empty__m_empty.txt: 第8行 期望='<缺行>' 实测=''`）。这是整个资产产线最值钱的信用资产。
3. runner 的确定性是被设计出来的：`hotwords/eval/runner.py:3-21` 的 docstring 写明「无随机/无网络/无时间戳」「同参数重复运行 stdout 逐字节一致」；我实测 `python eval/runner.py oracle/out oracle/out` → **exit 0，540ms**；speaker-mapping 同样命令 → **exit 0，377ms**。

**所以任务包与 runner 的关系是「包引用 runner，runner 不进包」**：

```
packs/<task-id>/
  brief.md          任务指令（两臂逐字相同；禁出现资产名 —— EVAL-SPEC §4.3-2）
  inputs/           黄金输入（两臂同等提供 —— §4.3-4，首夜教训：输入不可达导致连续 2 轮 15 项全红）
  rubric.md         维度×权重×0/6/10 分档（§5.1 L3）
  out/<arm>-<run>/  臂产物
  transcript/       过程轨原始转录（每臂每 run）
  records/          model_pin.json / exit_code / wall_ms / token
# oracle/ 不入包 —— 留在包外，只有裁判可见（§4.3-4）
```

**runner 怎么进包？两个选项，我倾向第二个**

- 选项 A：把 `v5/assets/<a>/eval/runner.py` 复制进 `packs/<id>/checks/`。坏处：复制出来的副本会漂移，冻结契约（`hotwords/eval/runner.py:41` 注释「修改须先改 spec.md/contract.md 并升版本号」）就断了。
- **选项 B（采纳）**：包里只放一个薄封套 `checks/run_check.py`，它 import/调用**资产树里的原版 runner.py**，把 exit code 透传。好处是「装置钉版」（EVAL-SPEC §4.4-2 / tau2 A4 的本地化：装置变更 ⇒ 分数不可比）在文件层面就是可查的——分数永远对着哪个版本的 runner 算，取决于资产树的 git 提交，不取决于包里躺了哪一份拷贝。

**一个必须写进红线的发现（并行跑批的头号杀手）**

`hotwords/oracle/run_all.py:31` 是 `OUT = os.path.join(HERE, "out")`，`:56-58` 是

```python
if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)
```

也就是**在资产目录里原地跑生成器会删掉 `oracle/out` 这个参照区**。这不是我推断出来的：K-3 彩排已经踩过一次，`classroom/rehearsal/round-1/record.md:42`（缺陷 D3）原文「学员流程初版让学员原地跑 `oracle/run_all.py`——该脚本硬编码 OUT=oracle/out，**会清空重建评测参照区**（实际触发一次，cmd.txt 被写入 Windows 绝对路径）」，处置是 `git checkout` 恢复 + 走查改成「复制 oracle→out/oracle_student 再跑」。

**推论（置信度高）**：4 模型 × N 任务的矩阵里，几十个臂并发跑在同一个资产目录上，只要有一个臂（或学员、或任何走查者）走错一步，**其余所有臂的参照区同时消失，评分变成"参照区不存在"的全红**。这与 BASELINE §3.3 记录的 peidian `runtime/` 并发互踩是同一类事故，但严重一级（那边是结果污染，这边是参照物被删）。

**因此任务包的第一条不变量是：每个臂的 cwd 是一份 inputs-only 的独立目录树，资产树与 oracle 树都不在其中；臂要跑生成器，必须先复制到自己的 scratch 副本。** 这条要写成可机检的门（跑批前后各算一次 oracle 树哈希，不一致即 abort），而不是写成文档里的一句注意事项。

### 2.4 Q4 双轨评估：过程轨为什么必须存在（有实测缺陷清单撑腰）

**「产物一致性」是 v5 runner 的口径**（BASELINE §3.6 首行：「runner 比对的是产物根目录……评的是产物一致性，不是源码单测」）。但真实任务里有一整类错误，在最终产物 diff 上**完全不可见**。K-3 彩排的缺陷清单就是这份类别的实测枚举（`record.md:36-44`）：

| 缺陷 | 内容 | 产物 diff 能看见吗 |
|---|---|---|
| D1 | 走查初稿 5 处 CLI 参数错误（SM 漏 `--transcript/--mapping`，DP 漏 `--services/--pack`，HW export 漏 `--format`） | **看不见**——参数错了但脚本可能仍产出可 diff 的东西 |
| D2 | 从资产根用绝对路径跑，discover JSON 回显与基线不符 + stderr 存档缺失（评测 1/4→2/4） | 半可见（评测掉到 2/4，但不知道错在哪一步） |
| D3 | 原地跑 `run_all.py` 清空参照区 | **看不见**——被破坏的是评分装置本身 |
| D4 | 学员向 `oracle/out/_work/store.json`（参照区内工作库）加词 | **看不见** |
| D5 | 走查引用的 REGISTRY 行号误指 dist 包行（v5 资产与 dist 包是不同代际） | **看不见**——文档引用错误 |

这五条全部是**过程错误**，全部只有靠一个干净上下文的执行体真刀真枪走一遍才会暴露。这正是"过程+产物双轨"的实证依据，而不是一句设计口号。

**双轨怎么切，我采纳的口径**

- **产物轨（机判、零模型、亚秒）**：直接调用资产原有 `runner.py`。证据基线 = 冻结的 `oracle/out`。它回答「最终交付物对不对」。成本实测 0.377–0.540 秒/臂，**几乎免费，可以每次必跑**。
- **过程轨（机判 + 转录断言，零模型）**：从 `transcript/` 里抽**步骤级断言**，而不是只抽最终状态。至少四类断言（都是从 D1–D5 反推的）：
  1. **命令面**：`oracle/run_all.py` 这类会删参照区的命令，只允许出现在 scratch 副本路径下，不允许出现在 `oracle/` 前缀下（→ 拦 D3/D4）；
  2. **退出码面**：每条命令的 exit code 落在 `expect ∈ {0,2}`（沿用 `hotwords/eval/runner.py:66-69` 的 `FAIL_STERR_KEYWORDS` 契约思路），命令行本身失败（exit 1 / usage error）记为装置失败而非被测失败；
  3. **引用面**：走查/手册里引用的 REGISTRY 行号、资产路径必须真实存在（→ 拦 D5）；
  4. **禁止面**：转录里不得出现 oracle 目录读取（→ 兑现 §4.3-4）。
- **质量轨（裁判，消耗模型）**：rubric 判「达成任务目标态」，**不得因实现路径与参照不同而扣分**（§3.8-7，端态判定原则的本地化）。裁判必须与被测模型**不同族**，否则就是自己给自己打分。

**裁判放在哪一格：一个我没有证据、必须标为未决的问题。** EVAL-SPEC §4.1-2 把 GLM-5.3-Flash 定为「treatment/baseline/裁判」三者统一的标准模型，§4.2-2 说首期裁判就用同一个 GLM、后续 D31–60 再升级跨模型家族互评。**我认为这条在"多族跑批"的新前提下已经过时**：当被测臂本身就包含 GLM/MiniMax/Step 三个族时，同族裁判会让某一族的分数被系统性抬高（自偏好），而跨版本分数又禁止合并（§4.4-2）。**建议：裁判固定为与当轮被测集无交集的第四族，或者裁判也按族跑、只做"同族 vs 跨族"两套并披露差异。** 置信度：中（推理强，缺本机实验）。

**裁判一致性校验的量纲问题**：§3.4-2 规定「同份产物两次评分差 >2 → 换裁判」。这条的前提是**分档尺度稳定**。跨族裁判的尺度天然不同（不同模型的 0/6/10 锚点理解不同）。**推论：跨族裁判必须各自跑一遍 §3.4 的自洽抽检，且阈值按族分别校准，不能用一个 2 分的绝对阈值横跨三族。** 置信度：中。

### 2.5 Q5 并发 / 超时 / 预算：限流是 GLM 族的问题，不是全局问题

**并发上限（有实测）**：`dwf_run.caps_max_concurrency` 分布 = **16（398 次）/ 4（2 次）/ 6（1 次）**，即默认上限 16。另外 `config.json:216-218` 的 `toolConcurrency.maxConcurrency = 10` 是**单会话内工具并发**，与 run 级 actor 并发是两件事，不要混。

**限流分布（这是本节最硬的数据）**——`model_usage` 逐请求错误类型：

| error_type | 次数 |
|---|---|
| rate_limited | **7487** |
| timeout | 1320 |
| stream_idle_timeout | 888 |
| cancelled | 217 |
| network_error | 136 |
| provider_overloaded | 25 |
| auth_failed | 24 |
| context_exceeded | 14 |
| invalid_request | 12 |

按模型拆开，结论立刻锋利：

| model | 请求数 | rate_limited | 限流率 | timeout 类 | 单请求 max |
|---|---|---|---|---|---|
| GLM-5.3-Flash | 108,650 | 6096 | **5.61%** | 990 | 3786s |
| GLM-5.3 | 20,786 | 1357 | **6.53%** | 501 | 1872s |
| step-5-preview | 4,814 | 20 | 0.42% | 277 | 441s |
| step-router-v1 | 3,182 | 14 | 0.44% | 141 | 331s |
| Minimax-M3.1-Flash-Preview | 3,312 | **0** | **0.00%** | 133 | 2031s |
| MiniMax-M3 | 3,669 | **0** | **0.00%** | 166 | 1248s |

**采纳的排矩阵规则（置信度高）**

1. **限流是 bigmodel 账号的专属问题。** 三条 bigmodel 通道合计 7453 次限流，minimax 与 step 合计 34 次。→ **矩阵的多数臂放在 minimax/step 上，GLM 臂单独排队并降并发。** 若反过来做（GLM 当主力），跑批会被限流切成碎片。
2. **限流必须分类为 infra_error，绝不能算成"被测失败"。** EVAL-SPEC §3.5-1 已经规定了 harness 崩溃/超时/平台错误标 `infra_error` 不入统计，但 `§3.5-1` 的原文列举里**没有点名限流**。踩这个坑的代价是灾难性的：一个 5.6% 的限流率会被均匀摊到 4 个族头上，让"资产有没有用"的结论被通道健康度污染。**规划必须把 `rate_limited` 显式写进 infra_error 判据，并要求重试一次后再判。**（`model_usage` 里有 `retry_count` / `retryable` / `attempt_index` 三列，分类所需的原始数据已经全在，不需要新埋点。）
3. **单臂超时按族分设。** 观察到的单请求最长耗时：GLM-5.3-Flash 3786s、M3.1-Flash 2031s、GLM-5.3 1872s、M3 1248s、step-5-preview 441s、step-router-v1 331s。用一个统一超时会让 step 臂"从不超时"（白丢检测）、GLM 臂"几乎必然超时"（误杀）。**建议初值：step 600s、minimax 1200s、GLM 1800s，并在头两轮后按实际分位数重设。** 全局兜底看 `config.json:146` 的 `modelStream.idleTimeoutMs = 60000` 与 `:160` 的 `network.timeout = 180000`——注意这两个是**流空闲**与**网络**超时，不是整臂超时，**不能拿来当臂超时用**。
4. **配额不是钱，是额度窗口。** 三个 bigmodel 通道（individual / start / offpeak-idle）+ minimax/step 都是订阅制 coding plan（provider 名里就写着 `coding-plan` / `step_plan` / `standard-personal`）。**我没有查到任何额度数字，也不打算编。** 规划里应写"额度窗口未知，首两轮以 1 臂/族 试跑测出限流拐点"，而不是写一个假的成本上限。

**单臂代价的实测标定（取自本工作区已完成 run 的子代理账）**

| 子代理 | 模型 | model_calls | input tok | output tok | ctx 超限 | error |
|---|---|---|---|---|---|---|
| 测试思考员-文档一致性与剧本检查表 | minimax/Minimax-M3.1-Flash-Preview | 45 | 2,921,325 | 29,395 | 0 | 2 |
| 测试思考员-门禁meta测试 | minimax/Minimax-M3.1-Flash-Preview | 64 | 5,156,769 | 46,437 | 0 | 0 |
| 测试思考员-holdout原则 | minimax/Minimax-M3.1-Flash-Preview | 39 | 2,416,231 | 56,578 | 0 | 1 |
| 规划思考员-互操作与证据链 | minimax/Minimax-M3.1-Flash-Preview | 44 | 2,896,039 | 31,851 | 0 | 0 |
| 规划思考员-协议运行时风险 | account:bigmodel-start-plan/GLM-5.3-Flash | 34 | 1,865,389 | 23,852 | 0 | 0 |
| 规划思考员-壳与真机交接面 | account:bigmodel-start-plan/GLM-5.3-Flash | 30 | 2,115,708 | 31,542 | 0 | 0 |
| 基线合拢员·GLM5.3Flash | account:bigmodel-individual-coding-plan/GLM-5.3-Flash | 40 | 4,643,935 | 44,681 | 0 | 0 |

读法（**注意这是外推，不是实测**）：一个"读材料→写报告→交结构化结果"的臂 ≈ 30–65 次模型调用、平均单请求 12–34s ⇒ **单臂模型时间 10–35 分钟**，input 约 1.5M–5.2M。**外推的警告**：这些臂是长上下文累积型研究任务，input 被重复重发撑大了；EVAL-SPEC §3.2-3 要求的"干净上下文"评测臂会短得多，input 大概率显著低于此。**所以我不给出一个"全量矩阵要 200M token"这种数字充门面——那是我没测过的外推。** 我能给的是有据的部分：单请求耗时分布（实测）、限流率（实测）、单臂调用次数量级（实测）、以及"矩阵墙钟 ≈ Σ单臂时长 ÷ 有效并发，且 GLM 族有效并发受 5.6% 限流压制"这个结构性结论。

**降级链（采纳）**

| 情形 | 处置 | 依据 |
|---|---|---|
| `rate_limited` | 退避重试 1 次；仍失败 → `infra_error` 剔除并披露 | §3.5-1 + `model_usage.retry_count` 实测 avg 0.049–0.204 |
| `stream_idle_timeout` | 同上；连续 2 次 → 该臂作废 | 实测 888 次，非罕见 |
| `context_exceeded` | **不算 infra_error，算装置设计缺陷**——任务包太大，超出模型上下文 | 实测仅 14 次，且全部集中在 `step-router-v1`（contextWindow 250,000） |
| Step-3.7-Flash 通道不通 | 换 `new-provider/step-router-v1` 代跑，报告显式标注代跑 | 见 §2.1 |
| 某族整体崩 | 该族整列标 `unjudgeable` 退出本轮，**其余族照常出结论**（禁止因单族失败宣布整轮无效） | §3.4-2 的精神；EVAL-SPEC §3.5-2 只在"单任务 infra_error 超有效重复一半"时作废任务，不牵连全轮 |

最后一行是我对 §3.5-2 的一处**收紧建议**：原文只规定了单任务作废与全轮无效的条件，没有规定"一整族作废"的处置。多族跑批必须补上这一条，否则一个族的通道故障会被人误当成"全盘失败"。

### 2.6 Q6 看板与回归：把 EVAL-SPEC 的产物接成"资产迭代触发器"

**可以直接复用的部分（不必重造）**

- `benchmark.json` 三层 schema（EVAL-SPEC §8.1，`asset`/`evalbench`+`model_pin`/`tasks`+`judge_consistency`+`infra_errors`/`aggregate`+`acceptance`+`disclosure`）——直接落盘，一个字段都不用改。
- 冻结纪律（§5.2「只增不改」，修订升版、旧版归档 `eval/archive/golden-v<N>-<date>.json`）。
- 跨版本不可比条款（§4.4-2：装置或模型任一变更 ⇒ evalbench 版本 bump，旧基线作废，禁止并列比较）。**多族场景下这条要加严一句：跨族 Δ 不可比，因为被测模型本身就是变量。** 跨族只能比"同一族内跨资产版本"。

**必须新增的部分（EVAL-SPEC 没有的）**

1. **矩阵视图**：benchmark.json 是单资产单轮的。新增一张 `matrix.json`：`rows = 任务`，`cols = {族×臂×run}`，单元 = `{process_pass, artifact_pass, quality_score, tokens, wall_ms, infra_error}`。一屏能回答"哪个族在哪类任务上崩"。
2. **回归基线**：每族一张 `baseline/<family>/<evalbench_version>.json`，存首轮全量分位。回归判定 = 同族同装置下逐任务比较，**只对 Δ≤−1.0 的任务触发资产调查**（阈值取自 §3.6-① 的 Δ≥1.0 反向对称）。
3. **效率门的数据**：`config.json` 侧无需埋点，`model_usage` 已经有 `input_tokens/output_tokens/duration_ms/time_to_first_token_ms` 逐请求，按 `session_id` 聚合即可。EVAL-SPEC §3.8-3 要求"逐 run 落盘 token 与耗时"、§7.1 门 3 要求"token 比率 ≤2.0 且耗时比率 ≤2.0"——**这些列全都已经在本机 db 里了，效率门第一次变得可算。** 这是我从 db 里挖出来的最有实用价值的一条。

**资产迭代决策规则（我要给撰写者写成可执行的门，而不是"看分数"）**

| 触发证据 | 判定 | 动作 |
|---|---|---|
| 产物轨红（runner exit 1），转录显示命令正确 | 资产**生成侧**缺陷 | 改资产，不改协议 |
| 产物轨红，转录显示命令错/路径错 | 课程/手册缺陷 | 改走查与手册（K-1/K-2），**不改资产**——D1/D2/D4 就是这一类 |
| 过程轨红（参照区被写、oracle 被读） | 任务包或臂隔离缺陷 | 改 harness，红路红线不动 |
| 产物+过程全绿，仅质量轨低分，且**多族一致低** | 资产**内容**增益不足 | 资产迭代（改 SKILL.md 触发描述/流程/契约） |
| 产物+过程全绿，质量轨低分但**单族低、跨族正常** | 裁判自偏好嫌疑 | 换裁判重评，不动资产 |
| `infra_error` 占比 > 20% | 装置不稳 | 本轮**不出验收结论**，先修通道；§3.5-2 精神 |
| 全部臂 `rate_limited` | 配额/并发问题 | 降并发重跑，**不得据此判资产无效** |

中间两行（多族一致 vs 单族低）是**多族跑批带来的新判据**，单族时代不存在——这是我认为最值得写进规划的一条增量。

### 2.7 端到端 MVP：先证管道，不证资产

**考虑过的分支**

- (a) 直接上 4 族 × 5 任务 × 2 臂 × n=2 = 80 臂的合规矩阵。
- (b) 4 族 × 1 任务 × 2 臂 × n=1 = 8 臂。
- (c) 2 族 × 1 任务 × 2 臂 × n=1 = 4 臂，外加 0 模型的管道自检。
- (d) 只做 0 模型的管道自检，模型接入留到下一步。

**采纳 (c)，(d) 是它的第 0 步。**

否决 (a)/(b) 的理由不是资源，是**认识论**：n=1、1 任务在任何统计意义上都**不能**产出 Δ。EVAL-SPEC §3.2-1 明文「n=1 出具验收结论【禁止】」，§3.1-1 明文少于 5 条任务「【禁止】出具验收结论（可出具中期信号，标注 n 并禁止用于入库判定）」。**MVP 的产出物必须被命名为「管线验证信号」而不是「验收结论」，并写进文件。** 这与本仓的诚实纪律一脉相承（REGISTRY.md:195 就诚实记着「盲评为小样本 n=2…加厚欠账待模型配额」）。

**资产选 speaker-mapping，不选 hotwords。** 依据：
- `speaker-mapping/oracle/` 只有 `fixtures/`、`map_speakers.py`、`out/`，**没有原地重生成器**——我 grep `rmtree|OUT *=|makedirs` 在 `oracle/*.py` 上**零命中**；而 hotwords 有 `run_all.py:56-58` 的 `shutil.rmtree(OUT)`。**MVP 要选没有破坏性面的资产，否则并行跑批的第一课就是"参照区没了"。**
- 自评 377ms（实测），比 hotwords 还快。
- 已有课堂交付物 `v5/assets/speaker-mapping/out/student_run1/`（24 文件，K-3 彩排实证），有现成的"真实交付物"语义可复用。
- 任务有天然的**可判定产物**（映射稿 + 未映射告警 + discover 统计），且 runner 已有 4 项检查（`eval/runner.py` 的 replacement / unmapped_warnings / discover_stats / reference_agreement_100pct），产物轨零改造可用。

**MVP 的四步（每步都有 abort 判据）**

- **第 0 步（0 模型调用，约 1 分钟）**：建 `packs/sm-mapping-01/` 骨架 → 跑 `python eval/runner.py oracle/out oracle/out`（预期 exit 0，实测 377ms）→ 跑空目录红路（预期 exit 1）→ 算 oracle 树 sha256 存基线。**abort 判据**：任一退出码不符，或 oracle 哈希与 git HEAD 不符。
- **第 1 步（0 模型调用，约 5 分钟）**：把 treatment/baseline 两棵目录树建起来并**实测隔离**——在 baseline 树里 `find` 一遍，确认不含 SKILL.md / oracle / eval；把 `/skill <name>` 与 `--cwd` 的实际行为摸清（见下方未决项）。**abort 判据**：baseline 树能摸到任一资产文件。
- **第 2 步（4 臂，模型调用）**：2 族（`minimax/Minimax-M3.1-Flash-Preview` + `account:bigmodel-individual-coding-plan/GLM-5.3-Flash`）× 2 臂（treatment / baseline）× 1 重复 = 4 臂并发。**预算**：按单臂 10–35 分钟、并发 4、GLM 族限流压制 → **墙钟估 20–40 分钟**（外推，标注为估计）。**abort 判据**：任一臂出现 `context_exceeded`，或 oracle 哈希在跑批后变化。
- **第 3 步（0 模型调用，约 10 分钟）**：过产物轨（薄封套调原版 runner）+ 过程轨四类断言 + 落 `matrix.json` + 跑批后 oracle 哈希比对。**这一步的产物是一张 4 单元的看板行，以及一份"管道是否可信"的判定。**

**MVP 明确不做**：不判 Δ、不判资产优劣、不出任何可外引的数字、不改任何既有文件（除了新增 `packs/` 与 run 输出目录）。台账（REGISTRY.md）**MVP 阶段不更新**——REGISTRY 的行是准入判据，MVP 不构成准入证据。

---

## 3. 证据

### 3.1 我本次亲手跑的命令与输出（节选，逐条可复现）

| # | 命令 | 结果 |
|---|---|---|
| E1 | `zcode --version` | `zcode 0.16.9` |
| E2 | `D:/tools/bin/kimi.exe --version` | `2.1.1`（`D:\AGENTS.md` 第八节写的 0.41.0 已过期） |
| E3 | `zcode --help`（拉两遍） | **无 `--model` 选项**；`/model` 是 Slash Command（客户端处理） |
| E4 | `zcode --model GLM-5.3-Flash --help` | `Unknown option '--model'` |
| E5 | `zcode mcp list` | `Unknown command: mcp`（`/mcp` 仅 TUI 斜杠命令） |
| E6 | `zcode -p "/model" --mode yolo`（Git Bash，未加 `MSYS_NO_PATHCONV`） | 参数被 MSYS 转成 `C:\Program Files\Git\model`，模型误答为路径问题 |
| E7 | 同上 + `MSYS_NO_PATHCONV=1` | 客户端拦截；回报本次模型 = **GLM-5.3 / `bigmodel-individual-coding-plan`**；同轮可见一次 `AI_APICallError`（`isRetryable: true`） |
| E8 | `zcode -p "Reply with exactly one token: PONG…" --mode yolo` | 输出 `PONG`，**WALL_SECONDS=17**（最小无工具单轮基线） |
| E9 | `zcode skills list` | 16 个可用 skill（plugin cache + bundled），含 `dynamic-workflows` |
| E10 | `zcode app-server` + `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}` | 进程起来并推 `startup/storageState` 通知（schemaVersion:1 / databaseKind:session / 迁移 `0022_backfilled_session_reasoning`）——**协议活着，但模型选择消息未验证** |
| E11 | `cd skillfactory/v5/assets/hotwords && python eval/runner.py oracle/out oracle/out` | **EXIT=0，540ms** |
| E12 | `cd skillfactory/v5/assets/speaker-mapping && python eval/runner.py oracle/out oracle/out` | **EXIT=0，377ms** |
| E13 | `grep -nE "OUT\|shutil\|rmtree\|makedirs\|open\(.w" hotwords/oracle/run_all.py` | `:31 OUT = os.path.join(HERE, "out")`；`:56-58 if os.path.isdir(OUT): shutil.rmtree(OUT); os.makedirs(OUT)` |
| E14 | 同类 grep 于 `speaker-mapping/oracle/*.py` | **零命中**（无原地重生成器） |
| E15 | `ListModels` | `model_catalog_unavailable`（本会话无模型目录；子代理只能继承会话模型） |
| E16 | `ListWorkflowRuns` | `workflow_introspection_unavailable` |
| E17 | `ListSavedWorkflows` | `count=0`（本项目 `.zcode/workflows/` 空） |
| E18 | `sqlite3 db.sqlite` 聚合（9 条查询，脚本见正文） | 见 §3.2 |
| E19 | `diff config.toml.bak-1003 config.toml` | 仅新增 `[models."stepfun-step-plan/step-5-preview"]` 块（kimi 2.1.1 今日新增模型） |
| E20 | `WebFetch` × 3（arxiv / arxiv v1 / example.com） | 全部 `Provider rejected the model request.` → **本轨迹无自采公开网页证据** |

### 3.2 本机 db 实测聚合（`C:\Users\Administrator\.zcode\cli\db\db.sqlite`）

- 表清单：`session, message, part, todo, dwf_run, dwf_activity, dwf_actor, dwf_node, dwf_event, model_usage, turn_usage, tool_usage, …`
- `dwf_actor` 2708 行；`resolved_model` 9 种取值（8 非空 + None 394），取值分布见 §2.1。
- `dwf_run` 401 行：completed 240 / cancelled 78 / failed 73 / running 10；`caps_max_concurrency` = 16（398）/ 4（2）/ 6（1）。
- `model_usage` 144,403 行；`status`：completed 143,938 / error 265 / cancelled 214。
- 错误类型分布与按模型的限流率见 §2.5 表。
- 子代理级 token 与调用数见 §2.5 表（11 个 actor 逐行）。
- `model_id like '%3.7%' / '%3.5%' / '%kimi%' / '%k3%'` → model_usage 与 dwf_actor **均 0 命中**。

### 3.3 盘内文件证据（path:line）

- `skillfactory/v2/standard/EVAL-SPEC-v0.2.md:139-144` 任务数 ≥5、目标 8，覆盖能力/难度/陷阱三维，<5 条禁止出具验收结论
- 同上 `:146-152` 每臂 n≥2、上下文隔离、轮换防顺序偏置、采样参数落盘
- 同上 `:154-161` 任务级多数判定（pass^k 本地化）与胜率口径
- 同上 `:163-169` 裁判一致性校验（复评抽检，分差 >2 换裁判）、裁判须有实测证据
- 同上 `:171-174` infra_error 剔除（**原文未点名限流**——见 §2.5 规则 2）
- 同上 `:176-186` 复合接受线 Δ≥1.0 且 胜率≥60% 且 反向任务≤1
- 同上 `:194-202` 流程控制清单：两臂唯一差异=资产挂载、任务三件套、**效率逐 run 落盘**、端态判定原则
- 同上 `:206-212` **标准评测模型定标 GLM-5.3-Flash**（与 E7 实测行为不符）
- 同上 `:220-226` 公平性禁令：baseline 物理隔离、prompt 逐字相同、禁暗示资产、oracle 两臂皆禁读、禁止事后补课
- 同上 `:228-231` 模型钉版五元组 + 装置变更 ⇒ 版本 bump + 旧基线作废
- 同上 `:237-255` 合成黄金集三层 SOP；程序化判分权重应 ≥50%
- 同上 `:261-271` 两级晋级（`synthetic-passed` / `real-verified`）与回退门
- 同上 `:275-305` 四形态适配（文本直评 / MCP 文档增益 / agent 整包 kit / 自指）
- 同上 `:334-354` `benchmark.json` 三层 schema
- `skillfactory/REGISTRY.md:4` 资产 18 / 可分发 3 / v0.2 达标 4；`:166` 体检 C 属形态错配；`:195` 盲评 n=2 加厚欠账；`:202` K-3 彩排通过；`:216-218` 欠账三条
- `skillfactory/classroom/rehearsal/round-1/record.md:3-5` 零上下文姿态、40 分钟时间盒、判定通过；`:36-44` 缺陷 D1–D5；`:48-50` 评测器零改动红线核查
- `skillfactory/classroom/walkthrough.md:1-45` 三课结构、REGISTRY 行号 L162/L163/L164、每步「操作+验证命令+预期输出特征」
- `skillfactory/classroom/teaching-assets.md:1-25` 「latest 不入课堂口径，必须钉版本」
- `skillfactory/v5/assets/hotwords/eval/runner.py:3-21` 确定性契约（无随机/无网络/无时间戳、逐字节可复跑）；`:41` 修改须升版本；`:48-59` 冻结 10 步；`:66-69` 失败步 stderr 关键词契约；`:394-400` 一致率阈值 100%；`:460-496` exit 0/1/2 与 JSON 输出
- `skillfactory/v5/assets/hotwords/oracle/run_all.py:31,56-58` 原地 `shutil.rmtree(OUT)`（参照区破坏源）
- `skillfactory/v5/assets/acceptor-agent/eval/runner.py:12-17` 四项检查；`:129-130` 参数数 ∉{0,2} → exit 2；`:143` exit 0/1
- `skillfactory/v5/assets/zctl-mcp/eval/runner.py:1-20` spawn server + initialize + tools/list 的 MCP 契约评测
- `.zcode/workflow-drafts/盘点MiniMax-M3.1-Flash.dwf.ts:88-90` `phase()` + `agent(name,{system})` + `ask<T>()`，**无模型参数**；`.zcode/workflow-runs/dwfrun-1095ea25-*.mjs` 头部与全文 grep 无 model 字段
- `C:\Users\Administrator\.zcode\cli\config.json:139-140` `model.main = builtin:bigmodel-coding-plan/GLM-5.3-Flash`（与 E7 实测不符）；`:146` idleTimeoutMs 60000；`:160` network.timeout 180000；`:167-169` features.subagent/skill/mcp 全 true；`:179-180` `mcp.servers = {}`；`:194-199` `skills.roots = []`；`:216-218` toolConcurrency 10
- `C:\Users\Administrator\.zcode\v2\provider_config.json` providerOrder `[new-provider, minimax]`；new-provider personalModelIds `[step-5-preview, step-router-v1]`（baseUrl `https://api.stepfun.com/step_plan/v1`）；minimax personalModelIds `["Minimax-M3.1-Flash-Preview"]`、modelOrder 9 项；`step-5-preview` contextWindow 1,000,000；`step-router-v1` contextWindow 250,000；`MiniMax-M2.7-highspeed` enabled:false
- `C:\Users\Administrator\.kimi-code\config.toml:1` `default_model = "stepfun-step-plan/step-3.7-flash"`（**`D:\AGENTS.md` 第八节写的 step-router-v1 已过期**）
- `BASELINE.md:99-101` 四 runner 全绿/红路 fail-closed/学员产物可复评（均为 A 级）；`:175-182` zcode-research 基线卡；`:147` peidian 并发互踩机制；`:267` NUL 保留名（Windows 路径事故的既有先例）
- 任务书原文（本次 ask 给出）：普通模型四指定、eval 由 zcode 主 agent 组织、产物三样（任务类型+bench+资产+迭代方案 / 完整课程 / 多资产混用）、skill 与 MCP 须合国际通行标准

### 3.4 转引（我未亲访，标注为盘内记录）

- tau2-bench 的 `pass^k = C(success_count,k)/C(num_trials,k)`、端态判定、`INFRASTRUCTURE_ERROR` 剔除、跨版本不可比公告、SABER 审计（EVAL-SPEC-v0.2.md `:75-88`，标注【实访】于 2026-09-29；含 arXiv:2406.12045 与 arXiv:2512.07850 转引）
- terminal-bench 的「任务指令 + 验证测试脚本 + 参考解法」三件套与数据集版本化（EVAL-SPEC `:89-95`，【实访】）
- tau2-bench 首夜访问经 WebFetch 两次 `TLS ECONNRESET` 失败、改用 web_reader 成功（EVAL-SPEC `:411`）

---

## 4. 倾向性结论

1. **四个"普通模型"在本机不是同一等级的可达性**：GLM-5.3-Flash / MiniMax-M3 / MiniMax-M3.1-Flash / step-router-v1 / step-5-preview 是 zcode 工作流**已实跑记账**的；**Step-3.7-Flash 是唯一只能走 kimi CLI 的**（model_usage 与 dwf_actor 均 0 命中）。规划必须把第四列写成"外部通道 + 归一化器"，不能默认它和前三列同构。**置信度：高**（两表 0 命中 + 配置文件反证，三重）。
2. **模型钉版必须在"有模型目录的宿主"上做，且模型 ID 逐字抄 `dwf_actor.resolved_model`**。本会话 `ListModels` 明确报 `model_catalog_unavailable` 并要求省略 `subagent_model`；DB 同时证明钉版在生产中被用过 2708 次。所以这不是"不支持"，是"取决于启动会话"。**置信度：高**。
3. **`v5/assets/*/eval/runner.py` 一行都不改，任务包用薄封套引用它。** 理由：TASK.md:76 红线 + 红路 fail-closed 是 A 级信用资产 + 确定性是可复现性的来源。**置信度：高**。
4. **并行跑批的头号事故是参照区被删，不是分数抖动。** 机制已实证（`hotwords/oracle/run_all.py:56-58` 的 `shutil.rmtree(OUT)`），事故已实证（彩排 D3），同构先例已有（BASELINE:147 peidian runtime 互踩）。必须做成"跑批前后 oracle 树哈希比对"的机检门。**置信度：高**。
5. **过程轨不可省，且必须是步骤级断言**。K-3 彩排 D1–D5 五条缺陷全部在最终产物 diff 上不可见——这是"真实任务必须双轨"的实证依据，不是设计偏好。**置信度：高**。
6. **限流是 bigmodel 账号的专属问题（5.61%/6.53% vs minimax/step 的 0.00%/0.4%），矩阵主体应放在 minimax+step 上，GLM 单独排队降并发**。**置信度：高**（14.4 万条逐请求记录）。
7. **`rate_limited` 必须显式进 infra_error 判据。** EVAL-SPEC §3.5-1 的原文列举没有点名限流，而本机 GLM 通道 5.6% 的限流率若被误算成"被测失败"，会直接把通道健康度污染成资产结论。**置信度：高**。
8. **效率门第一次在本机变得可算**：`model_usage` 已有逐请求 input/output tokens、duration_ms、time_to_first_token_ms，按 session 聚合即满足 §3.8-3 与门 3 的数据义务，无需新埋点。**置信度：高**。
9. **EVAL-SPEC §4.1「GLM-5.3-Flash 作三臂统一标准模型」在多族跑批下已过时**，且与 headless 实测行为（E7 实际跑 GLM-5.3 / individual-coding-plan 账号）双重不符。需要一次显式决策：改钉 Flash（并验证），还是改钉 GLM-5.3（并按 §4.4-2 bump evalbench 版本）。**置信度：高**（文档-实测冲突是事实）；**哪个更好：低**（属人类决断）。
10. **裁判与被测同族会造成自偏好**，建议裁判固定为与当轮被测集无交集的族；但 EVAL-SPEC §3.4-2 的"分差 >2 换裁判"阈值是绝对刻度，跨族必须按族分别校准。**置信度：中**（推理充分，本机无实验）。
11. **MVP 应为 2 族 × 1 任务 × 2 臂 × n=1 = 4 臂，资产选 speaker-mapping**（无原地重生成器、自评 377ms、已有课堂交付物与四项现成检查），且产出物必须命名为「管线验证信号」而非验收结论。**置信度：中高**（资产选择的排除性证据是实测的；规模判断是工程判断）。
12. **headless `zcode -p` 驱动是最强的隔离形态**（一臂一进程 = EVAL-SPEC §3.2-3/§4.3-1 的最强满足），但它没有模型开关，所以它能跑哪些族取决于共享配置——**这一条是 MVP 的头号技术风险**（见 §5.2）。

---

## 5. 未决问题与风险

### 5.1 需要人类决断的（我不该替他定）

- **D-1｜资产与 harness 的落盘位置。** 新建 `D:/new-workspace/agent-asset/evalkit/`（不进 git，先证后落），还是直接续代进 `skillfactory/v6/`？我倾向前者：`afp-clone` 现在本地 10 ahead / 25 behind（BASELINE §6-1）且推送受阻，往一个分叉中的克隆里塞未验证的 harness 代码，git 历史会很难看。**但** v6 才是这个仓库五代方法论的合法延续位。**这取决于 owner 对"仓库洁净度"与"产线连续性"的取舍。**
- **D-2｜评测模型钉版改不改。** EVAL-SPEC §4.1 钉 GLM-5.3-Flash，headless 实测跑的是 GLM-5.3。改钉要 bump evalbench 版本、存量 Δ 全部作废（§4.4-2）。这个代价要人点头。
- **D-3｜第四列用不用 kimi。** 走 kimi 2.1.1 出 Step-3.7-Flash（需写归一化器，且 Git Bash 调 kimi 有已知的参数坑），还是用 `step-router-v1` 代跑并显式标注。**代跑会偏离人类意图里点名的模型，我倾向不代跑。**
- **D-4｜裁判是否跨族。** 跨族更可信但要建 3 套校准；同族省事但有自偏好。这是方法论立场问题。
- **D-5｜额度窗口未知。** 三条 bigmodel 通道 + minimax + step 全是订阅制，我查不到任何额度数字。**"成本预算"在拿到首两轮实测之前只能写成"待标定"，不能写成数字。**
- **D-6｜对外可引用的边界。** MVP 的 4 臂结果显然不能对外。但"n=1、1 任务"的中期信号能否对内用于资产迭代决策？EVAL-SPEC §3.1-1 说可以出具中期信号但禁止用于入库判定——我理解对内资产迭代属于"入库判定"边缘，需要人划线。

### 5.2 我没能验证的技术风险（按严重度）

- **R-1（高）｜treatment 臂的资产装载路径没有可用开关。** 现状：`config.json:194-199` 的 `skills.roots = []`、`:179-180` 的 `mcp.servers = {}`、`zcode mcp` 根本不是 CLI 子命令、`zcode` 没有 `--skill`/`--mcp` 选项。唯一看到有希望的线索是 `/skill [name] [task]` 这个斜杠命令在 headless 下**被客户端拦截**（E7 证明了 `/model` 是这样被拦的），所以 `/skill` 有可能同样可用。**MVP 第 1 步必须先实测这件事。** 若不可用，退而求其次是 prompt 级注入资产文本——但那样测出的 Δ 只能标注为「文档增益下限」（EVAL-SPEC §6.2-3 的 provisional 口径），**不能声称是产品装载路径的增益**。这是一个会让结论降级的分叉，必须在 MVP 之前就定，不能等跑完再补。
- **R-2（中高）｜per-arm 进程驱动与模型选择互斥。** 走 `zcode -p` 拿不到隔离之外的模型控制，走工作流运行时拿不到每臂一进程。**折中方案（推荐）**：用工作流运行时做编排（拿记账 + 拿钉版），但要求每个 actor 的 `--cwd` 落在自己的目录树上（`agent()` 是否支持 per-actor cwd 我**没有验证**，这是 R-2 的具体待验点）。若不支持，才退到纯进程驱动 + 自建 model_pin.json。
- **R-3（中）｜Step-3.7-Flash 通道完全未验证。** 我只确认了它"存在配置"，**没有跑过一次 `kimi.exe -p`**。它的 headless 行为、退出码语义、转录格式（`--output-format stream-json` 的字段名）一概未知。
- **R-4（中）｜单臂墙钟是外推不是实测。** §2.5 的 10–35 分钟来自"研究型思考臂"，评测臂上下文更短，很可能更快，但**也可能因为要真跑 Python 工具链而更慢**。MVP 第 2 步的 4 臂跑完就能把这个外推换成实测。
- **R-5（中）｜`model_catalog_unavailable` 的宿主范围未知。** 我只知道本会话不可用。规划里如果写"工作流里钉 `subagent_model`"而不加前置条件，就可能在别的会话上翻车。
- **R-6（低中）｜Mimosa hook 会拦写操作。** BASELINE §2-26 记录 hook 活体拦截（连只读复验命令都被误放过一次，`Mimosa 拒绝了通过 Bash 直接写入 eval/runner.py 的操作`）。跑批要写大量产物文件，**必须先确认 hook 对"写 run 输出目录"放行**，否则第一批 run 会在 PreToolUse 全被拦。当前会话里我写的 `planning/thinking/5-...md` 顺利落盘，说明至少这条路径通。
- **R-7（低）｜Git Bash 参数转换会毁掉含 `/` 的命令行。** E6 实证。任何走查/驱动脚本传给原生 Windows 程序的参数，含 `/` 就必须 `MSYS_NO_PATHCONV=1` 或改 Windows 风格——而资产 runner 的命令里恰恰满是 `python eval/runner.py ...` 这种正斜杠相对路径。**这是课程（给学员的走查）与 harness（给 agent 的驱动）共同面对的坑**，应该进 K-2 学员手册的常见卡点。
- **R-8（低）｜NUL 保留名与 CRLF 两类 Windows 事故有前科**（BASELINE §7-1/§7-4）。跑批归档若用 shell 重定向写文件，可能再造 NUL；四份 eval JSON 留档里已经有一份不是纯 JSON（`hw_student_eval.json`，`json.load` 直接炸），**说明这个坑已经造成过一次实际损失**。新看板的落盘要用 Python 显式 `open(..., encoding="utf-8", newline="\n")`，不要用 shell 重定向。

---

## 6. 给最终规划撰写者（GLM-5.3）的具体建议

按"先做/先定"的顺序，不是按重要性排。

1. **把 §3.2 的 db 证据写进规划的"通道事实"一节。** 这是本机唯一机器级跑批遥测：2708 个子代理的 `resolved_model` 记账、401 次 run 的并发上限 16、14.4 万条逐请求的耗时/token/限流。**特别要写进去的两条**：(i) Step-3.7-Flash 在 zcode 侧 0 记账；(ii) 限流率 bigmodel 5.6% vs minimax/step 0.0–0.4%。这两条直接决定矩阵怎么排。
2. **规划里加一节「宿主能力前置条件」。** 明确写：`subagent_model` 钉版只在有模型目录的会话可用；本类会话实测不可用（`model_catalog_unavailable`）。**并附上那张已验证的模型 ID 白名单**（含 `minimax/Minimax-M3.1-Flash-Preview` 的正确大小写）。
3. **把任务包目录约定写成规范节，包含两条硬不变量**：(i) 每臂独立目录树，资产树与 oracle 树都不在其中；(ii) 跑批前后 oracle 树哈希比对，不一致即 abort。第二条要有 K-3 D3 的原文引用作为存在性理由。
4. **把「薄封套引用原版 runner、runner 零改动」写成不可协商的架构约束**，并引用 TASK.md:76 红线原文。任何人后续想"让 runner 支持 LLM 打分"都要被这条挡住。
5. **双轨写成三节：产物轨（v5 runner，亚秒，零模型）/ 过程轨（转录步骤级断言，零模型，四类断言逐条列）/ 质量轨（跨族裁判，消耗模型）**。过程轨的四类断言请直接采用我 §2.4 的四类（命令面 / 退出码面 / 引用面 / 禁止面），每类都注明它拦的是 D1–D5 里的哪一条。
6. **把 infra_error 判据补上 `rate_limited` 与 `stream_idle_timeout` 两条**（EVAL-SPEC §3.5-1 原文没有），并要求"重试 1 次后仍失败才剔除"——`model_usage` 里 `retry_count`/`retryable`/`attempt_index` 三列已经够判。另外补一条**单族整列作废**的处置（现规范只规定了单任务与整轮两种粒度，缺"族"这一级）。
7. **超时按族分设并给初值**（step 600s / minimax 1200s / GLM 1800s），并写明"依据是 model_usage 里各族单请求 max：441/2031/3786 秒"，避免被误读成随手拍的数。同时提醒不要拿 `idleTimeoutMs=60000` 或 `network.timeout=180000` 当臂超时。
8. **看板用两层**：`benchmark.json` 原样落盘（EVAL-SPEC §8.1 不改一个字段）+ 新增 `matrix.json` 矩阵视图。回归基线按"族 × evalbench 版本"分文件，**并写死一条：跨族 Δ 不可比**（被测模型本身是变量），跨族只能比"同族内跨资产版本"。
9. **把「多族一致低 vs 单族低」作为新的资产迭代判据写进决策表**（我 §2.6 的表）。这是单族时代不存在的判据，也是多族跑批真正的增量价值所在。
10. **MVP 按 §2.7 的四步写，并保留三条纪律**：(i) 资产选 speaker-mapping（无原地重生成器这一条是实测排除，不是偏好）；(ii) 产出物命名为「管线验证信号」，禁止称为验收结论；(iii) MVP 阶段**不更新 REGISTRY.md**（它承载准入判据，MVP 不构成准入证据）。
11. **把 R-1（treatment 臂装载路径）作为 MVP 第 1 步的必答项，并在规划里预置两条分支的后果声明**：`/skill` 可用 → 走真实装载路径；不可用 → prompt 注入 + Δ 标注为「文档增益下限（provisional）」。**这一条不能留到跑完再定，因为它决定结论的对外效力。**
12. **成本一栏写"待标定"，不要写数字。** 三个 bigmodel 通道 + minimax + step 全是订阅制，我查不到额度；per-arm 的 token 外推（1.5M–5.2M input）来自研究型臂，与评测臂不可直接类比。**规划里唯一可以给的硬成本是并发上限 16 与各族限流率**，其余以 MVP 实测回填。
13. **顺带提醒撰写者两处文档漂移**（影响规划引用）：`D:\AGENTS.md` 第八节写的 kimi 版本 0.41.0 与 default_model=step-router-v1 均已过期（实测 2.1.1 / step-3.7-flash）；EVAL-SPEC §4.1 的 GLM-5.3-Flash 钉版与 headless 实测的 GLM-5.3 不符。**规划若照抄这两处，会把错误固化进新文档。**
14. **把 Git Bash 的 `/` 参数转换（E6 实证）写进 K-2 学员手册的"常见卡点"**，并写进 harness 驱动脚本的规约。它是本轮唯一一个"学员和 harness 都会踩同一个坑"的项。
