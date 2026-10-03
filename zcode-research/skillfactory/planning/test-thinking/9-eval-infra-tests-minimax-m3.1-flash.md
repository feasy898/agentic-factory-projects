# 跑批基建测试面 · 思考轨迹（MiniMax-M3.1-Flash · 2026-10-03）

> **镜头**：PLAN §5「eval 执行运营」这一层需要的测试。模型矩阵、跑批 harness、任务包、看板、迭代决策规则——它们本身是**装置**，装置的测试面与资产测试面是两套问题。
> **范围红线**：只谈 skillfactory 线的规划实现。封存项目不出现。
> **本文件不是测试文档**。它是我的思考轨迹：拆解、每条主张的拦人对象、被否决的分支、置信度。成品由撰写者（GLM-5.3）落。

---

## 0. 一句话主张

**跑批基建测试面真正要拦的，不是「资产好不好」，是「装置在撒谎」。** 本机已经有两起装置自己撒谎的实证（一起是 infra 被算成被测失败的隐患，一起是看板统计量整体反演），所以这一层的测试优先级应该和资产测试面**平级甚至更高**——因为资产测试的全部结论都建立在这一层不撒谎之上。

---

## 1. 展开方法与信息源

### 1.1 先问「这个测试拦的是谁」

我给跑批基建的每一条测试都先归到一个「敌人」名下。归不进去的测试我怀疑它没有存在价值（这是 v5「先想清楚拦谁」纪律在本镜头的应用）：

| # | 敌人 | 具体表现 | 危害等级 |
|---|---|---|---|
| E1 | **装置失败伪装成被测失败** | rate_limited/timeout/crash 被计成「资产没用」 | 最高：结论方向反了，且数字仍看起来合理 |
| E2 | **开发者破坏 oracle 让资产好看** | 删/改参照区，或把手伸进冻结面 | 最高：整套 bench 归零 |
| E3 | **过程错误被产物轨掩盖** | K-3 D1–D5 五类缺陷 | 高：交付物「绿」但过程是错的 |
| E4 | **看板统计量说谎** | delta/winRate 算错、Δ 一词多义、跨族乱比 | 高：数字被引用、进入对外口径 |
| E5 | **并发互踩 / 状态覆盖** | 两臂同写一路径、两轮抢一目录 | 中高：结果污染且难以复现 |
| E6 | **落盘不是它自称的格式** | shell 重定向冒充 JSON、编码错、行尾漂移 | 中：下游 `json.load` 直接炸 |
| E7 | **惰性装置（永远返回绿）** | harness 断言写错/恒真，MVP 全绿但什么都没验 | 最高：**前面六条全部被它掩盖** |

**E7 是我这条线上最重要的发现之一**，它不在 PLAN 里，也不是任何现有文档提到的。它是元问题：一个从未在已知坏输入上失败过的断言，等价于没有断言。PLAN §5.4 的 MVP 四步全部是「跑通型」判据，没有一条是「必须抓到一个已知缺陷」的反向判据。详见 §2.6。

### 1.2 信息源清单（按可信度降序，含我本次实跑的）

1. **本机运行态库** `C:\Users\Administrator\.zcode\cli\db\db.sqlite`（只读打开）。我本次查了 `model_usage` / `session` / `tool_usage` / `turn_usage` / `part` 五张表的 schema 与内容（`sqlite3` via Python `sqlite3.connect('file:...?mode=ro', uri=True)`）。**这是本镜头最重要的信息源**——它决定了 infra_error 分类和效率门能不能实现。
2. **PLAN.md**（630 行，通读），重点 §3.2/§3.3/§3.4/§5.1–§5.6/§7 WS1/§8 O-5/O-6/O-7/O-8/O-17/O-18/§9.1。
3. **规划轨迹 5**（eval-ops，55KB，通读）——本镜头的直接上游。
4. **EVAL-SPEC-v0.2.md**（`v2/standard/`）§3.3–§3.8/§4.3/§4.4/§8.1/§8.2/附录 B。
5. **v5 实物**：`hotwords/oracle/run_all.py`、`hotwords/package/run_all.py`、`deploy-pack/oracle/run_fixtures.py`、三个 `eval/runner.py` 的 docstring 与退出码契约。
6. **v5/eval-round-20261001/**：`scorecard.md`（41 门 38 PASS / 3 FAIL 全诊断）、`results.tsv`、`keyfiles.sha256`。
7. **classroom/rehearsal/round-1/record.md**（K-3 缺陷 D1–D5 原文）。
8. **v2/evalbench-v02/*/ab_summary.json**（三份，含 `correction` 字段）。
9. **BASELINE.md** §2-19/20/21/22、并发互踩段、R-7 Windows 事故族。

### 1.3 走过的弯路与自我纠正（记录下来，因为它们直接改变了结论）

- **弯路 1：差点把「过程轨必须解析转录文本」当成前提。** PLAN §5.3 写「转录**步骤级断言**」，我第一反应是「要从 markdown/stream-json 里正则抽命令」。查库之后发现 `part.data` 存的是完整结构化 JSON，含 `state.input.command` 全文，且能 join 到 `tool_usage.exit_code` 与 `session.directory`。**过程轨可以做成确定性查询，不必解析自由文本。** 这条改变了整个过程轨的测试设计。
- **弯路 2：差点只按 PLAN 点名的一条路径做 oracle 保护测试。** PLAN §3.3 只点名 `hotwords/oracle/run_all.py:31,56-58`。我 grep 全树后发现**实际有三处参照区破坏点，其中两处 PLAN 没写**（详见 §2.2）。照 PLAN 写测试会漏掉两处，其中一处在**可分发的 package 里**。
- **弯路 3：差点报了一个不存在的编码缺陷。** 我用 Bash 工具 `head -c 600 hw_student_eval.json` 看到满屏乱码（`姝ュ簭鍒楄`），差点写成「文件编码损坏」。用 Python 逐编码试解才发现：**文件是合法 UTF-8**（`utf-8 -> OK, first 60: [PASS] script_sequence_consistent: 10 步序列…`，`gbk -> FAIL`），乱码是我 shell 控制台的显示层问题。**该文件唯一的缺陷是「不是 JSON」**（`json.load` → `JSONDecodeError: Expecting value: line 1 column 2 (char 1)`）。教训：显示层缺陷与文件层缺陷必须分开取证，否则会写出一条错误的测试需求。
- **弯路 4：差点假设「裸 sha256 树哈希就够」。** 我先算了一遍发现三棵树都能稳定复算，差一点就此收工。但我又查了行尾，���现参照区树是**混合行尾**（speaker-mapping 12 CRLF / 12 LF；hotwords 10 CRLF / 34 LF；deploy-pack 0/14），且本仓有过 autocrlf 登记口径翻转的实证。**裸字节哈希的稳定性是本机本时刻的偶然，不是性质。** 这条催生了「登记基准必须显式声明」的要求（§2.2）。

---

## 2. 关键推理链

### 2.1 链条 A：通道健康与被测失败分离——先解决「能不能关联」，再谈「怎么分类」

**先问一个 PLAN 没问的问题**：harness 拿到一个臂的失败，怎么知道它属于哪个模型/哪个臂？答案是必须有 join key。整个 infra_error 分类和效率门都挂在这个 key 上。

**我的实测（只读 sqlite）**：

```
model_usage 表 40 列，含：session_id / attempt_index / retry_count / retryable /
  error_type / error_code / context_exceeded / duration_ms / input_tokens / output_tokens
session 表含：id / directory / slug / trace_id
tool_usage 表 27 列，含：session_id / tool_call_id / tool_name / read_only / destructive /
  exit_code / status / error_type / retry_count / duration_ms
part 表含：session_id / data(TEXT)
```

关联链验证（我实际跑的查询与结果）：

- `SELECT COUNT(*) FROM model_usage mu JOIN session s ON mu.session_id=s.id` → **144708 / 144708 全命中**（`model_usage` 总行数也是 144708）。**`session_id` 是完整外键，无孤儿行。**
- `session.directory` 是每个会话的工作目录，本机实测 3386 个 session、**0 个 NULL/空 directory**。目录值明显按项目聚簇（`D:\workspace\zcode研究` 523、`D:\workspace\阿里agent能力全调研` 465 …）。
- `session.slug` 区分会话来源：工作流会话是 `sess_dwf-dwfrun-<runid>-...`，非工作流会话是 `sess_<uuid>-<hash>`。**这给了 harness 一个「这是不是工作流会话」的分型依据。**
- `query_source` 五值分布：`workflow_child` 87255 / `subagent` 30328 / `main_turn` 27069 / `session_title` 66 / `compact` 26。headless CLI 单轮应落 `main_turn`。本工作区（`directory LIKE '%agent-asset'`）下 `main_turn` 有 308 行、`workflow_child` 629 行、`subagent` 19 行。

**推论（置信度高）**：只要每臂以独立 `--cwd` 启动，臂 ↔ 遥测 的关联键就是 `session.directory`（或 slug）。`model_usage` 里的 `retry_count`/`retryable`/`attempt_index` 三列确实够判 PLAN §5.5 要求的「重试 1 次后仍失败才剔除」。

**但我必须诚实标出一个我没验证的关键前提**：**我没有跑过 `zcode -p` headless 来验证它是否真的在库里落一条带臂 cwd 的 session 行。** 轨迹 5 也把「per-actor cwd 未验证」列为 R-2。**如果 headless 不落 session 行，或不支持 per-arm cwd，这条关联链整个塌掉**，infra_error 分类和效率门都退化为「不可实现」。这应当是 harness 自测的第 0 号门，不是 WS1 第 2 步。

**分类本身是三桶，不是两桶。** PLAN §5.5 补了 `rate_limited`/`stream_idle_timeout` 进 infra_error，§5.6 又单独写了 `context_exceeded` →「**算装置设计缺陷**（任务包太大）不算被测失败」。所以实际分类器有三出口：

| 桶 | 触发 | 后果 | PLAN 出处 |
|---|---|---|---|
| `infra_error` | rate_limited(重试1次后) / stream_idle_timeout(连续2次) / harness 崩溃 / 非被测超时 / 平台错误 | 该 run 剔除，单独计数披露 | §5.5、§5.6、EVAL-SPEC §3.5-1 |
| `装置设计缺陷` | context_exceeded | 该臂作废，**触发「任务包瘦身」动作，不是「资产无效」** | §5.6 |
| `被测失败` | 答非所问、产物损坏、质量低分 | 正常计分 | EVAL-SPEC §3.5-1 末句 |

**三桶必须各有正例和反例**。特别是 `被测失败` 桶需要一个**故意做坏产物**的 fixture：否则「一切都是 infra」会变成万能借口，而这正是 E1 的终极形态。

**超时有一个机器指纹可用。** 我查了 `tool_usage.exit_code` 分布：`0`→163340、`1`→3524、`2`→2184、`255`→245、`127`→188、`128`→90、`143`→64、`28`→58。这几个非业务值全部来自 `Bash`（我查了 `WHERE exit_code IN (143,255,127,128)` 的 tool_name 分布，全是 Bash）。**143 = 128+15 = SIGTERM**，正是 harness 超时 kill 进程时留下的指纹；255/127 是 shell 错误。**所以「臂被超时杀掉」和「模型自己失败」在遥测里是可区分的**——分类器可以据此给出可审计的 reason，而不只是一句 `infra_error: true`。

**`retryable` 列提供降级链的判据**。我实测 `error_type × retryable` 交叉：`rate_limited` retryable=1 → 7430、retryable=0 → 57；`timeout` 1→1318；`stream_idle_timeout` 1→775 / 0→113；`cancelled` 0→217；`context_exceeded` 0→14。**「重试 1 次」这个条款至今没有在本机被执行过**（retryable=0 的 rate_limited 只有 57 次，说明多数是能重试的）。降级链的测试只能靠故障注入。

**限流率的量级决定了这条测试的优先级**（引自轨迹 5 §2.5 的 db 聚合，我未复算）：GLM-5.3-Flash 5.61%、GLM-5.3 6.53%，minimax 两族 0.00%、step 两族 0.4%–0.44%。**5.6% 的限流若被算成被测失败，摊到四族上就是每族约 1.4% 的臂被冤枉**——数字不大，但足以在 n=2 的小规模上翻转胜负判定（§3.6 复合线里「反向任务 ≤1」是硬条件）。

**通道探活测试**的独立价值：PLAN §5.1 已经按限流率决定矩阵排布（minimax/step 为主体、GLM 降并发）。这个排布本身应该有一条**数据驱动的回归测试**：从库里算出各族近 N 天的限流率，若 GLM 族限流率显著上升超过阈值，测试**红**，提示「矩阵排布假设已失效」。否则矩阵排布会静默腐化。

### 2.2 链条 B：oracle 保护——PLAN 点名了 1/3 的雷区

**实测：全树 grep `rmtree|shutil|os.remove|unlink`（`--include=*.py`）命中 20 行 = 7 处 `shutil.rmtree` + 7 处 `import shutil` + 6 处 `shutil.copyfile`（`os.remove`/`unlink` 零命中）。其中 3 处 rmtree 直接威胁参照区**：

| # | 位置 | 目标 | PLAN 是否点名 | 危害形态 |
|---|---|---|---|---|
| **B1** | `v5/assets/hotwords/oracle/run_all.py:57` `shutil.rmtree(OUT)`，OUT=`:31` `HERE/out` | 整棵 `hotwords/oracle/out`（54 文件） | **是**（§3.3 引 :31,:56-58） | 参照区整体消失 |
| **B2** | `v5/assets/hotwords/package/run_all.py:66` `shutil.rmtree(OUT_DIR)` | 整棵 `package/out` | **否** | **可分发包里同一颗雷**——课堂学员拿到的是 package |
| **B3** | `v5/assets/deploy-pack/oracle/run_fixtures.py:58` `shutil.rmtree(pack_dir)`，pack_dir=`OUT/("pack-"+tag)` | 参照区的**单个 pack 子目录** | **否** | **最阴**：只删一部分，看起来像「内容回归」而不是「参照区没了」 |
| B4 | `deploy-pack/eval/runner.py:247`、`oracle/validate.py:265`、`package/validate.py:353` `rmtree(tmp, ignore_errors=True)` | tempfile 临时目录 | 否 | 低（但应断言 tmp ∉ 资产树） |
| B5 | `v5/assets/hotwords/out/oracle_student/run_all.py:57` | D3 修复留下的 scratch 副本 | 否 | 这本身是**合规的**（K-3 D3 修复方案就是复制到 scratch 再跑），但它是 B1 的第二份活拷贝 |

**结论：oracle 保护测试必须是「属性扫描 + 登记表」，不能是「检查某个已知路径」。** 理由：B3 的危害形态与 B1 完全不同（部分删除伪装成内容回归），B2 在 PLAN 完全没出现。B5 更麻烦——**同一个脚本内容同时以「合法 scratch 副本」和「地雷」两种身份存在**，判据只能是**路径解析后的规范化位置**，不能是字符串包含。

**因此测试形态应是**：扫描资产树全部 `.py` → 找破坏性调用 → 解析其目标路径（处理 `HERE` 相对、`os.path.join` 拼接、`..` 穿越）→ 断言目标 ∉ `oracle/`，除非命中一张**人工审阅过的登记表**。B5 进登记表（合法），B1/B2/B3 不进（违规，但都是既有事实——**这张登记表第一次生成时会是红的，测试的首个工作就是让这张表显式化，而不是让测试假装全绿**）。

**扫描器本身要 meta-test。** 一个只匹配 `shutil.rmtree(` 字面量的扫描器会被四种形态绕过：字符串拼接路径、`os.chdir` 后相对路径、``..` 穿越（`oracle/../oracle`）、符号链接。**这四种各要一个合成 fixture。** 否则扫描器可能恒真——回到 E7。

**哈希门有两个我实测出来的、比 PLAN 更硬的约束：**

**(1) 参照区树里混着易变文件。** 我 grep `"(started_at|generated_at|duration_s|finished_at|timestamp)"` 于三棵 oracle/out：
- `hotwords/oracle/out`：**0 命中**
- `speaker-mapping/oracle/out`：**0 命中**
- `deploy-pack/oracle/out`：**8 命中**（`fixtures-run.json`、`pack-canonical-validate.json`、`pack-subset-validate.json`、`red/red-bad-yaml-report.json`、`red/red-env-drift-report.json`、`red/red-hardcoded-secret-report.json`、`red/red-missing-service-report.json`、`validate.json`）
源头是 `deploy-pack/oracle/run_fixtures.py:118-119`：`"started_at": datetime.now().astimezone().isoformat(...)` 和 `"duration_s": round(time.time()-t0, 2)`。

scorecard §2 第 3 条早就记了这件事：「deploy-pack `run_fixtures.py` 重跑 exit 0；oracle/out 重跑前后仅 5 类汇总报告 JSON 字节不同，差异字段=started_at/duration_s/generated_at（墙钟戳，非冻结面）」，§3.1 判定「dp01b 门按字节全等记 FAIL 属本台账自设口径过严，非资产缺陷」。

**所以 PLAN §5.4 第 0 步与第 2 步的 abort 判据「跑批后 oracle 哈希变化」，如果实现成整树裸哈希，在 deploy-pack 上会每一轮都误 abort。** 这不是理论风险，是 scorecard 已经踩过一次并诊断为「台账口径过严」的同一个坑。**哈希门必须带一张易变面登记表**（deploy-pack 是 8/14 = 57% 的文件，speaker-mapping 和 hotwords 是 0）。

**登记表会腐化，所以应该自标定**：跑两次生成器 → diff → 差异集合即易变面 → 再跑一次确认剩余冻结面稳定。**三跑法**：两跑学易变面，一跑验冻结面。我本次验证了这个方法的可行性——用「相对路径排序 + 逐文件 sha256 + 整体再哈希」的形态，三棵树都能稳定复算：speaker-mapping 24 文件、hotwords 54 文件、deploy-pack 14 文件，`rerun_identical=True`。

**(2) 行尾登记基准必须显式声明。** 我实测三棵参照区树的行尾分布：

| 资产 | 含 CRLF 的文件 | 纯 LF 文件 |
|---|---|---|
| speaker-mapping | **12** | 12 |
| hotwords | **10** | 34 |
| deploy-pack | 0 | 14 |

**混合行尾 + 裸字节哈希 = 哈希不稳定。** 我实测 raw 哈希与 LF 归一哈希**不相等**：speaker-mapping `c3729ed329ce` vs `84c1188e56fe`；hotwords `c7dca51c1518` vs `e9104784b5ec`。

而本仓恰好有这条事故的完整实证（BASELINE.md 并发警告段所在节的根因分析）：origin/main 线 `c025efe` 提交自述「**core.autocrlf=true 致全树 CRLF、登记口径=CRLF 字节**：LF 归一 338 文件……test_m1/test_m6 spec_hash 按 01 v2 §6 重登记」；盘点阶段本地是 `core.autocrlf=false`、文件均 LF，于是**声明 hash 与重算 hash 全不匹配**，被记为 SPEC_DRIFT，两个模块在跑任何用例前整体中止（51 个用例从未执行）。

**换句话说：peidian 那次事故同时证明了哈希门「能抓到真漂移」和「会在登记基准未声明时误报」两件事。** 而 PLAN §9.1 R-7 恰恰把 CRLF 列为已知 Windows 事故族。**所以 oracle 哈希门必须显式登记它的字节基准（建议：文本文件统一 LF 归一后哈希，二进制原样），并把「基准」写进哈希产物本身。** 我本次 `git config core.autocrlf` → `false`、仓库根**无 `.gitattributes`**，这意味着基准完全依赖每台机器的本地配置——正是 peidian 事故的土壤。

**既有先例 `keyfiles.sha256` 有两个缺陷，不能照抄**（我实测）：
- 19 条记录，**路径全是绝对 Linux 路径** `/opt/gpumachine/projects/zcode-research/...`。在 windev-01 上做 `sha256sum -c` 会 19/19 报文件不存在。**新门必须用相对路径。**
- **`oracle/out` 零覆盖**（`grep -c "oracle/out"` → 0）。它保护的是 spec/contract/runner/SKILL/CLI 脚本，**恰恰没有保护它要保护的东西**（参照区）。这反过来说明 PLAN §3.3 的 oracle 哈希门是全新工作，没有现成实现可抄。

**「跑前快照对比」的正确形态**：跑前算 → 跑 → 跑后算 → 不一致即 abort。但只有哈希不够——**B3 那种「只删一个子目录」的破坏，如果恰好删掉的内容不在冻结面登记里，可能算不出差异**。所以哈希门应当与「参照区文件清单 + 文件数」双断言（我实测三个资产分别是 24/54/14 个文件，数目本身就是一个廉价不变式）。

### 2.3 链条 C：过程轨断言——PLAN 的「转录步骤级断言」可以做得比它自己写的更硬

**核心发现（我实测）**：`part.data` 存的是结构化 JSON，含完整命令文本。实测样例：

```json
{"type":"tool","callID":"call_d3da1527387b4d768fee132b","tool":"Bash",
 "state":{"status":"completed",
          "input":{"command":"powershell -NoProfile -Command \"...\"","description":"查看已安装的开发工具与系统版本"},
          "output":"..."}}
```

而 `tool_usage` 里有同一 `tool_call_id` 的 `exit_code` / `status` / `read_only` / `destructive` / `error_type` / `duration_ms`。

**所以过程轨四类断言可以写成确定性查询，而不是正则**：
- 命令面 ← `part.data → state.input.command`
- 退出码面 ← `tool_usage.exit_code`
- 引用面 ← `state.input.command` 里的路径 + 文档静态扫描
- 禁止面 ← 同上 + 路径解析

**这带来一个额外好处：能用 `read_only` / `destructive` 做作用域判别。** 我查了 `tool_usage` 的工具分布：`Bash` 93466、`Read` 27653、`Edit` 17491、`Write` 10346、`TodoWrite` 6614、`mcp__node_repl__js` 5528、`WebFetch` 4638、`submit_result` 2027… **「只审状态变更型命令」这个作用域有现成字段支撑**，不需要靠命令文本猜。

**K-3 五类缺陷逐条映射到断言（含我发现的假阳性陷阱）**：

| 缺陷 | 原文（record.md:36-44） | 断言 | **假阳性陷阱（我发现的）** |
|---|---|---|---|
| **D1** CLI 参数错 | SM 漏 `--transcript/--mapping`，DP 漏 `--services/--pack`，HW export 漏 `--format`（5 处） | 每条状态变更命令的 flag 集合 ⊆ 任务包声明的 argv 签名 | 模型会**合法地跑 `--help` 探索**、会试错。作用域必须限定 `read_only=0`；且要允许「探索后改正」——**只断言最终有效命令集，不断言从未出错**（否则把正常的调试探索判红） |
| **D2** cwd/绝对路径 | 从资产根以绝对路径跑，discover JSON 回显与基线不符 + stderr 存档缺失（1/4→2/4） | 资产产物路径必须相对；cwd 必须是契约规定目录 | **严重**：`speaker-mapping/eval/runner.py:19-20` 明文「产出约定：在 oracle/ 目录为 cwd、以相对路径 --out 运行（contract.md §3），否则 stderr INFO 行与 discover transcript 字段的路径回显会与基线不同」；**增补条款 A-2** 又规定 discover JSON 的 transcript 路径按 `\`→`/` 对称归一后比对。scorecard 也记 `hw04` 的 `cmd.txt` 解释器路径形态属「跨机预期」。**所以「转录里不许出现绝对路径」这条断言在 Windows 上必然误报。** 正确形态：禁的是**资产产物路径**用绝对/跨 cwd，系统路径（解释器、shell）要豁免；并且要**单独测归一化器**对 `fixtures\normal.txt` 与 `fixtures/normal.txt` 两种输入给出同一判定 |
| **D3** 原地跑生成器 | 让学员原地跑 `oracle/run_all.py`，会清空重建参照区（**实际触发一次**） | 无任何命令的解析后目标落在 `oracle/` 下 | 必须**路径规范化后判定**（解析 `..`、符号链接），不能字符串包含——否则 `out/oracle_student/run_all.py`（**D3 的正确修法**）与 `oracle/run_all.py`（地雷）无法区分。两者目录名都含 "oracle" |
| **D4** 写参照区 | 学员向 `oracle/out/_work/store.json`（参照区内工作库）加词 | 无任何写操作指向 `oracle/` | **D4 是间接写**：它是「跑资产 CLI 并把 `--store` 指向参照区」，是 **Bash 命令**，不是 Edit/Write 工具。只查 Edit/Write 的断言会**整个漏掉 D4**。必须解析命令行参数指向 |
| **D5** 台账误指 | 走查引用的 REGISTRY 行号误指 dist 包行（L14-16）而非 v5 资产行（L162/163/164） | 走查/手册里每个 `REGISTRY L<n>` 引用解析到声明的资产 | 这是**纯静态检查，不需要跑模型**——最便宜的一条。且 v5/dist 是不同代际，断言要校验的是「行号 → 资产路径」的映射而非行号存在性 |

**过程轨的必要性实证**（PLAN §5.3 已引）：K-3 D1–D5 五条**全部在最终产物 diff 上不可见**。scorecard 也提供了同类证据：`sm05_green_pkg_vs_oracle` 判红的原因是「3 个 discover JSON 第 2 行 transcript 字段」路径分隔符形态，而 12 个主产物中 9/12 一致——**产物轨只告诉你「红了」，不告诉你「哪一步错」**，这正是 D2 的形态。

**一个必须说清的边界**：污染扫描（EVAL-SPEC §4.3-3「抽检任一 baseline 臂转录发现资产正文片段进入其上下文 → 判污染事故」）**仍然需要读文本**，因为它要匹配的是资产正文的 n-gram，不是结构化字段。所以是**双源**：结构化查询做过程轨断言，转录文本只做污染扫描。

**结构化源的脆弱性**：`model_usage`/`part`/`tool_usage` 是 zcode 内部库，**无版本契约**（我查了 `schema_migration` 表存在，说明会变）。把它当唯一依据是把 harness 绑死在一个未公开的内部 schema 上。所以：**结构化为主，转录为备**（双源交叉，两源不一致时判 infra_error 而非被测失败——又是 E1 的防线）。

### 2.4 链条 D：harness 自测的六个面

**(1) 臂间公平（同 nonce）——最便宜也最要紧的一条。** PLAN §3.5.1 要求 nonce 化实例。测试形态：跑批**开始前**（0 模型、0 成本）断言两臂输入树在**掩掉臂目录名与 nonce 后逐字节相同**，且 `brief.md` 两臂逐字节相同。这条拦的是最恶劣的一种不诚实——**臂 A 拿到了更容易的题**。它不需要模型、不需要网络，是整个测试面性价比最高的一条。

配套的 `brief.md` 静态断言（EVAL-SPEC §4.3-2）：任务指令里不得出现资产名、不得出现「你有一个技能可用」类暗示。测试形态 = 对已知资产名清单做精确匹配 + 对提示词模板做模式匹配。**这是纯静态、确定性、可放进 CI 的。**

**(2) 结果落盘 schema。** `benchmark.json`（EVAL-SPEC §8.1 三层结构，`asset`/`evalbench`+`model_pin`/`tasks`+`judge_consistency`+`infra_errors`/`aggregate`+`acceptance`+`disclosure`）+ 新增 `matrix.json`（PLAN §5.5）。schema 校验测试必须包含一个**写-读-断言的往返自测**：写入后立刻 `json.load` 回读并校验必填键。**这条不是假想需求——本工作区根目录的 `hw_student_eval.json` 就是反面教材**（我实测：合法 UTF-8，但 `json.load` 抛 `JSONDecodeError: Expecting value: line 1 column 2 (char 1)`，因为它是 shell 重定向捕获的 runner stdout，不是 JSON）。PLAN §9.1 R-7 已经记了这个前科。**落盘一律 Python `open(..., encoding="utf-8", newline="\n")`，不用 shell 重定向**（这是 R-7 的处置，测试要把它变成门）。

**(3) 失败重试与降级路径。** 「重试 1 次后仍失败才剔除」这个条款**在本机从未被执行过**（`rate_limited` 且 `retryable=0` 仅 57 次）。所以必须故障注入，而且要**两个方向都测**：
- 注入「第一次失败、第二次成功」→ 断言恰好 2 次 attempt（`attempt_index` 0 和 1 都有行）、断言该臂**不**被标 infra_error、断言两次的 token 都被计入效率门；
- 注入「两次都失败」→ 断言标 infra_error、断言该 run 从统计中剔除但**计数披露保留**（EVAL-SPEC §3.5 末句「【禁止】静默剔除」）。

`stream_idle_timeout` 的降级更深一层（PLAN §5.6：连续 2 次 → **该臂作废**，不是该 run 剔除）。臂级与 run 级作废的粒度差异必须有独立断言——**这是 EVAL-SPEC 原文没有的第三种粒度**（原文只有单任务与整轮，轨迹 5 §2.5 已指出并补了「族」这一级，PLAN §5.5 采纳了「单族整列作废」）。

**(4) 并发互斥。** 机制先例在 BASELINE.md 并发警告段：门禁 `runtime/` 状态不支持并发实跑，「首跑 m7 出现『任务已存在』×2，系与并行盘点员同时跑门禁互相覆盖 `runtime/eval_results.json` 所致，错峰后消失」；机制是 `src/m2_information/__init__.py:170 raise ValueError(f"任务已存在: {task_id}")` + 共享 `runtime/` 状态目录。**结论原文：「多 agent 验收同一仓必须错峰或隔离 runtime 输出目录」。**

映射到 harness：测试形态是**同时起 N 个臂 + 同时起两轮跑批**，断言 (a) N 个输出目录全部存在且非空；(b) 无两臂共享输出路径（路径由 `<run-id>/<arm>-<run>` 派生，断言唯一性）；(c) **参照区哈希在并发下不变**（这是并发对 oracle 门的压力测试，B1/B2/B3 就在这条路被触发）；(d) 第二轮跑批若前一轮未结束，harness **必须拒绝启动并给出明确错误**，而不是默默抢目录。

**(5) 超时分类。** 见 §2.1 的 exit 143 指纹。测试形态：注入一个必然超时的臂 → 断言它落 infra_error、reason 可区分于「模型自己失败」、**且不被计入被测失败**。同时断言按族分设的超时值（step 600s / minimax 1200s / GLM 1800s，PLAN §5.6）真的生效——**断言方法是「注入一个 700s 的臂，在 step 族应超时而在 GLM 族不应超时」**，这样一条测试同时验了超时表和分类器。

**(6) 单族整列作废。** PLAN §5.5：「某族整体崩 → 该族整列标 unjudgeable 退出本轮，其余族照常出结论，**禁止因单族失败宣布整轮无效**」。这条必须是一条**否定式测试**：构造「3 族全绿 + 1 族全崩」的矩阵，断言输出里 3 族仍有结论、1 族标 unjudgeable、**且没有出现「整轮无效」**。这是 EVAL-SPEC §3.5-2 没有的粒度（原文只在「单任务 infra_error 超有效重复一半」时作废任务），所以是最容易漏实现的一条。

### 2.5 链条 E：看板与回归——最有说服力的一条测试来自仓库自己的 bug

**我在 `v2/evalbench-v02/` 的三份 `ab_summary.json` 里读到了同一个 `correction` 记录**（meeting-minutes / hooks-mastery / lark-cli 三份**逐字相同**）：

> "v0.2 首测脚本 majority 计算把甲乙判反（`(better==='a')!==swap` 应为 `===swap`）：均值与 delta 未受影响，majority/winRate/reverseTasks/accepted 原值全部反演；本文件按留档 taskAggs 逐任务翻转 majority 后确定性重算。"

**这就是 delta/winRate 计算的元测试的现成论据**：
- 一个**符号/逻辑反转 bug** 同时污染了 `majority`、`winRate`、`reverseTasks`、`accepted` 四个字段；
- `均值` 与 `delta` **完全没受影响**——所以「均分对不对」这个检查**抓不到它**；
- 它同时发生在**三份文件**上（三份的 correction 文本逐字相同，说明是同一个脚本的同一次缺陷）；
- 最终是**人工**按留档逐条翻转后重算的，不是被自动测试抓到的。

**所以 delta_vs_prev / winRate / reverseTasks 的单测必须是「变形测试（metamorphic）」而不是「样例断言」**：
- 交换两臂标签 → 断言 `winRate → 1 - winRate`、`reverse_tasks` **不变**、`delta` 变号、`task_verdict` win↔loss 互换；
- 复制某个任务的 taskAgg 到自身 → 断言 `reverse_tasks` +1；
- 把所有 treatMean 设为 baselineMean → 断言 `delta=0`、`winRate` 符合平局口径、`accepted=false`（复合线三条件同时不过）。

**这三条变形测试恰好覆盖了那次真实 bug 的整个杀伤面。** 这是我在整个镜子里找到的**最强的单条测试论证**——不是假想风险，是已发货、已人工补救、至今无自动防线的缺陷。

**三臂迁移的具体陷阱。** 我实测 `ab_summary.json` 的 schema：`slug / name / assetType / tasks / baselineMean / treatmentMean / delta / winRate / reverseTasks / accepted / driftNote / taskAggs[] / correction{}`，其中 `taskAggs[]` 项为 `id / baseMean / treatMean / majority / repNotes`。**它是一个两臂结构，字段名是裸的 `delta`。** 而 EVAL-SPEC §8.1 的 `aggregate` 也是 `{"mean_baseline","mean_treatment","delta","task_win_rate","pair_win_rate","reverse_tasks","by_domain"}`——**同样有一个裸 `delta`**。

PLAN §3.2 说「落盘字段（固定，防『Δ』一词三种含义）」：`delta_vs_none` / `delta_vs_prev` / `delta_vs_none_prev`。**但迁移测试必须额外断言一件 PLAN 没写的事：旧的裸 `delta` 字段在新 schema 里必须消失或被显式别名到 `delta_vs_none`。** 否则「防 Δ 一词三义」的目标在迁移中自我挫败——新字段加了，老字段还在，下游读哪个？**这个断言是迁移测试的核心，也是最容易被漏掉的一条。**

**饱和检测的测试有真金输入。** 我实测 meeting-minutes 的 8 个任务 `treatMean` **全部 = 10**（t1..t8 的 treat 列：10,10,10,10,10,10,10,10），`baselineMean=4.75`、`delta=5.25`、`winRate=1.0`、`reverseTasks=0`、`accepted=true`。**这是 PLAN §3.2「现有主力题集 treatment 臂均分恒为 10.0」的直接核对，我确认属实。** 后果：按 Terminal-Bench 4.0 口径这轮已饱和，**这轮数字能回答「有没有资产」，不能回答「这版比上版好在哪」**。所以饱和检测器应该有一条**以这份真实文件为输入的测试**：喂进去 → 必须判 100% 饱和 → 必须拒绝用它计算 `delta_vs_prev`。**这是少数几条「有现成 golden input」的测试，应该优先写。**

**跨族不可比必须是代码门，不是文档纪律。** PLAN §5.5：「跨族 Δ 不可比（被测模型本身是变量），跨族只能比『同族内跨资产版本』；只对 Δ≤−1.0 的任务触发资产调查」。测试形态是**否定式**：给回归比较器喂两个不同族的基线，**断言它拒绝出数**（非零退出 + 明确消息），而不是给出一个误导性的 Δ。EVAL-SPEC §4.4-2 的先例语言是「【禁止】将不同钉版的 Δ 值并列比较或合并披露」——**禁令型条款必须有否定式测试，否则它会退化成约定**。同理「evalbench 版本变更 ⇒ 旧基线作废」也要一条版本不匹配的拒绝测试。

**效率门的输入已经齐了，但没人写过它的测试。** PLAN §5.5：「token 比率 ≤2.0 且耗时比率 ≤2.0（EVAL-SPEC §7.1 门 3；model_usage 已有逐请求 input/output tokens、duration_ms、ttft，按 session 聚合即可，**无需新埋点**）」。我确认列都在。但**「按 session 聚合」的聚合口径本身需要单测**：`computed_total_tokens` / `provider_total_tokens` / `input_tokens` / `cache_read_input_tokens` / `reasoning_tokens` 五列都在表里，**用哪一列、含不含 cache read、跨 attempt 怎么去重**——这三个问题任一搞错，效率门的数字就是错的，而 §3.8-3 要求「效率记录【必须】逐 run 落盘」。**这是「无需新埋点」这句话里被跳过的那一步。**

### 2.6 链条 F：MVP 试跑——把「管道正确性」重新定义为「能抓到已知坏」

**先重述 PLAN §5.4 的四步，然后指出它们各自其实是一个测试类**：

| 步 | PLAN 的内容 | 它其实是 | 零模型？ |
|---|---|---|---|
| 0 | 建骨架 / 绿路 exit 0 / 空目录红路 exit 1 / oracle 哈希基线 | **装置契约自检**（最便宜，且是 v5 已有的 A 级信用面） | 是 |
| 1 | 建两棵目录树 + **实测隔离** + 实测 R-1 装载路径 | **隔离断言** + 装载路径探针 | 是 |
| 2 | 2 族 × 2 臂 × n=1 = 4 臂 | 端到端管道 | 否 |
| 3 | 产物轨 + 过程轨四断言 + 落 matrix.json + 哈希终检 | **断言引擎自检** | 是 |

**关键判断：四步全部是「跑通型」判据，没有一条是「必须抓到一个已知缺陷」的反向判据。** 于是：

> **一个恒返回绿的 harness，和一个正确的 harness，在 MVP 里的表现完全一样。**

这就是 §1.1 的 E7。PLAN §5.4 的 abort 判据（退出码不符 / baseline 树摸到资产 / context_exceeded / 哈希变化）确实有几条是反向的，但它们检出的都是**粗粒度事故**（隔离失效、哈希变化），检不出**断言引擎本身是坏的**。

**因此我建议给 MVP 加一组「负控」（negative controls）——故意植入每一条已知缺陷，断言过程轨抓得住**：

| 负控 | 植入什么 | 必须被哪条断言抓到 |
|---|---|---|
| NC-1 | 在 oracle/ 下原地跑 `run_all.py`（**复刻 K-3 D3，真跑过的那种**） | 命令面 + oracle 哈希门**同时**红 |
| NC-2 | 把 `--store` 指向 `oracle/out/_work/store.json` 后加词（复刻 D4） | 禁止面红（且必须走 Bash 参数解析路径，不能只查 Edit/Write） |
| NC-3 | 从资产根用绝对路径跑（复刻 D2） | 引用面/路径面红，或归一化器给出与基线一致的判定 |
| NC-4 | 漏一个 CLI 参数（复刻 D1） | 退出码面/argv 面红 |
| NC-5 | 注入一次 `rate_limited` 后成功 | 分类器落「重试后成功」，**不**标 infra_error |
| NC-6 | 注入连续 2 次 `stream_idle_timeout` | 该臂作废（不是该 run 剔除） |
| NC-7 | 3 族全绿 + 1 族全崩 | 3 族出结论 + 1 族 unjudgeable，**无「整轮无效」** |
| NC-8 | 人为把某臂产物做坏 | 落**被测失败**桶（不是 infra_error）——防「一切都是 infra」 |

**NC-8 是最容易被忘、但最重要的一条**：它测的是「infra_error 分类器不会过度吞噬」。没有它，一个把所有失败都归 infra_error 的 harness 会让 MVP 全绿——**E1 与 E7 会在同一个测试里合谋**。

**MVP 的验收判据应该重写为**：
> 管道正确 = harness 能在 8 个负控上全部报错，且在 4 个正常臂上不误报。
>
> 而不是：管道正确 = 4 个臂跑完了。

**这个改写的成本很低**（负控都是 0 模型或故障注入），收益是让 MVP 从「演示」变成「验收」。PLAN §5.4 的三条纪律（「管线验证信号」命名、不更新 REGISTRY、不改既有文件）**应该原样保留并扩展一条：不许用负控的失败去更新 REGISTRY**——因为负控的失败是**故意制造的**，把它记进台账就是台账污染。这正好呼应 §3.4 的 holdout 纪律。

**资产选 speaker-mapping 的排除性证据我复核了一遍，成立**：我 grep `speaker-mapping/` 全树的 `rmtree|shutil|os.remove` → **零命中**；只有三个 `open(..., "w")` 写点（`oracle/map_speakers.py:108,:146`、`package/map_speakers.py:70`）。且它的 oracle 树**零时间戳**（我 grep 0 命中），24 文件，行尾 12 CRLF / 12 LF。**对比之下 deploy-pack 是 8/14 文件带时间戳。** 所以「MVP 用 speaker-mapping」不只是「没有原地重生成器」，还是「哈希门在它身上不会被易变文件污染」——**这是 PLAN 没写但成立的第二条理由**。

**但我要标一条风险**：speaker-mapping 的 24 文件树是 **12 CRLF / 12 LF 混合**。哈希门若用裸字节，在这棵树上同样不稳（我实测 raw ≠ LF 归一）。**MVP 选它并不能豁免登记基准问题。**

### 2.7 链条 G：开发者可见 vs holdout 的边界——判据是「真值锚在版本控制还是锚在秘密」

任务书要求我划这条线。我在这个镜头上的判据是：

> **一条测试能否对开发者可见，取决于它的真值是否锚在不可篡改的历史里（git blob / 已冻结登记），而不取决于它本身是否可见。**
> 锚在 git 历史里的测试，**完全公开也不会被绕过**——因为绕过它就得改历史，而改历史会留下 diff。锚在秘密里的测试才需要隐藏，而隐藏会引入「开发者不知道边界在哪」的代价。

按这个判据分：

| 类别 | 可见性 | 理由 |
|---|---|---|
| **oracle 完整性**（哈希门 + 文件清单 + 破坏点扫描） | **完全可见** | 真值锚在 git HEAD 的 blob。K-3 D3 的处置本身就是 `git checkout` 恢复——**这个机制已经证明「锚在历史」比「藏起来」有效**。而且开发者必须知道雷区在哪，B2/B3 尤其需要写进走查。 |
| **负控（NC-1…NC-8）** | **可见** | 它是**教学材料**。「原地跑 run_all.py 会 abort」这句话必须出现在手册里，否则它只是个会误伤人的陷阱。 |
| **臂间公平 / brief 逐字相同 / 无资产名泄漏** | **可见** | 真值是两份文件本身，比对是确定性的。藏起来没有意义。 |
| **holdout 实例与 nonce** | **holdout** | 资产作者/迭代者不得见。这条由 PLAN §3.4/§3.5.2 与 O-11 承接。 |
| **「资产是否真泛化」的测量** | **holdout** | 没有任何 harness 测试能替代真 holdout。**这是本镜头唯一必须 holdout 的东西。** |
| **裁判自偏好检测**（多族一致低 vs 单族低） | **可见** | 判据写在决策表里（PLAN §5.5），开发者应该知道自己的一轮会不会被判「裁判自偏好嫌疑」。 |

**给 holdout 的一条具体测试建议**（PLAN §3.5.2 提到「每轮结束对全部转录做资产正文片段扫描」）：**反向扫描比正向扫描更便宜也更狠**——因为 nonce 是程序化注入的一次性随机值，**如果 holdout 的 nonce 字符串出现在仓库任何文件里（含 SKILL.md、git 历史、笔记），那就是泄漏的铁证**，不需要判断「像不像」。**建议测试形态：全仓 grep holdout nonce 集合，期望 0 命中。** 这个测试有现成先例：BASELINE.md 记的 `scripts/ci_isolation.py` → `ISOLATION OK … zero hits`（holdout 零命中），是本仓已经跑通过的同类扫描。

### 2.8 被否决的设计分支（留痕）

| # | 分支 | 处置 | 理由 |
|---|---|---|---|
| X1 | 过程轨以 markdown/stream-json 转录正则为主证据 | **否决** | `part.data` 存结构化 JSON + 完整命令文本，且 join 得到 `tool_usage.exit_code` 与 `session.directory`。正则方案更脆且无假阳性分析。**残余风险**：db 无版本契约，所以保留转录为**备源**（双源交叉，不一致判 infra_error） |
| X2 | 只在真跑批时验证 infra 分离（等真限流出现） | **否决** | 分类器必须靠故障注入验证。GLM 限流 5.6% 会发生，但**不可复现、不可控、且一次就烧掉一轮跑批预算** |
| X3 | oracle 保护只查 `hotwords/oracle/run_all.py` 一条路径 | **否决** | 我 grep 出 3 处参照区破坏点，PLAN 只写了 1 处；B2 在**可分发 package** 里，B3 是更阴的部分删除 |
| X4 | 整树裸 sha256，无易变面登记 | **否决** | deploy-pack 8/14 文件带墙钟戳，scorecard §3.1 已把同类门判为「台账自设口径过严」。整树裸哈希会每轮误 abort |
| X5 | 整树裸 sha256，不声明行尾基准 | **否决** | 三棵树实测混合行尾；raw ≠ LF 归一；peidian 有 autocrlf 翻转导致 spec_hash 全不匹配、51 用例从未执行的完整实证 |
| X6 | 易变面用手工维护的白名单 | **否决** | 会腐化。改为**自标定三跑法**（两跑学易变面、一跑验冻结面），我已验证方法可行 |
| X7 | MVP 绿 = 管道正确 | **否决** | 恒真 harness 与正确 harness 在 MVP 里表现一样。改为「8 个负控全红 + 4 个正常臂不误报」 |
| X8 | 跨族 Δ 不可比写成文档纪律 | **否决** | 禁令型条款会退化成约定。必须是代码门 + 否定式测试（喂跨族数据必须拒绝出数） |
| X9 | delta/winRate 用样例断言测 | **否决** | 仓库里已有一次 `(better==='a')!==swap` 符号反转 bug，同时污染 majority/winRate/reverseTasks/accepted 三份文件而均值与 delta 毫发无损。必须用变形测试（标签互换不变量） |
| X10 | 照抄 `keyfiles.sha256` 作哈希门模板 | **否决** | 19 条全是绝对 Linux 路径（windev-01 上 19/19 找不到文件），且 `oracle/out` **零覆盖** |
| X11 | 把 `db.sqlite` 当唯一真值源 | **否决** | 内部 schema 无版本契约（存在 `schema_migration` 表）。改为结构化为主 + 转录为备 + 两源交叉 |
| X12 | 用「禁绝对路径」一条断言覆盖 D2 | **否决** | `runner.py:19-20` 契约要求特定 cwd、`:A-2` 条款对路径分隔符归一、scorecard 记 cmd.txt 解释器路径属跨机预期——该断言在 Windows 上必然误报 |
| X13 | 用「Edit/Write 未指向 oracle」覆盖 D4 | **否决** | D4 是**间接写**（Bash 调 CLI 且 `--store` 指向参照区），只查编辑类工具会整个漏掉 |
| X14 | 负控的失败记进 REGISTRY | **否决** | 负控失败是故意制造的，记进台账即台账污染。PLAN §5.4「MVP 不更新 REGISTRY」应扩展到负控 |

---

## 3. 证据

### 3.1 我本次亲手跑的命令与输出（逐条可复现，只读）

| # | 命令 | 结果 |
|---|---|---|
| E1 | `ls -la afp-clone/zcode-research/skillfactory/` | 顶层：REGISTRY.md / assets / classroom / course / dist / evidence / plan / report / standard / v2 / v3 / v4 / v5 |
| E2 | `sed -n '1,70p' v5/assets/hotwords/oracle/run_all.py` | `:31 OUT = os.path.join(HERE,"out")`；`:56-58 if os.path.isdir(OUT): shutil.rmtree(OUT); os.makedirs(OUT)`；docstring 声明「无时间戳、无随机数——同输入连跑两次，out/ 逐字节一致」 |
| E3 | `grep -rn "rmtree\|shutil\|os.remove\|unlink" v5/assets/ --include=*.py` | **20 行命中**（7 rmtree + 7 import + 6 copyfile；`os.remove`/`unlink` 零命中），含 **3 处参照区破坏点**（详见 §2.2 表 B1/B2/B3）+ 3 处 tmp + `out/oracle_student/run_all.py:57` |
| E4 | `sed -n '55,75p' v5/assets/hotwords/package/run_all.py` | `:66 shutil.rmtree(OUT_DIR)`——**package 形态同一颗雷** |
| E5 | `sed -n '48,65p' v5/assets/deploy-pack/oracle/run_fixtures.py` | `:56-58 if pack_dir.exists(): shutil.rmtree(pack_dir)`，pack_dir=`OUT/("pack-"+tag)` |
| E6 | `sed -n '238,252p' v5/assets/deploy-pack/eval/runner.py` / `sed -n '258,270p' oracle/validate.py` | 两处 `finally: shutil.rmtree(tmp, ignore_errors=True)`——tempfile 语义，风险低 |
| E7 | `grep -rn "rmtree\|shutil\|os.remove\|open(.*\"w\"" v5/assets/speaker-mapping/ --include=*.py` | **rmtree/shutil/remove 零命中**；仅 3 处 `open(...,"w")`：`oracle/map_speakers.py:108,:146`、`package/map_speakers.py:70` |
| E8 | `python -c "PRAGMA table_info(model_usage)"`（`mode=ro`） | 40 列，含 `attempt_index / session_id / duration_ms / input_tokens / output_tokens / reasoning_tokens / cache_read_input_tokens / retry_count / retryable / cancelled_by_user / context_exceeded / error_type / error_code / error_message` |
| E9 | 同上 `PRAGMA table_info(tool_usage)` | 27 列，含 `tool_name / read_only / destructive / approval_status / status / exit_code / stdout_bytes / stderr_bytes / truncated / retry_count / retryable / error_type` |
| E10 | 同上 `PRAGMA table_info(session)` | 含 `id / project_id / workspace_id / slug / directory / task_type / trace_id` |
| E11 | `SELECT COUNT(*) FROM model_usage mu JOIN session s ON mu.session_id=s.id` | **144708**（= `model_usage` 总行数 144708，**全命中**） |
| E12 | `SELECT COUNT(*) FROM session WHERE directory IS NULL OR directory=''` | **0**；`session` 总行数 3386 |
| E13 | `SELECT directory, COUNT(*) ... GROUP BY directory LIMIT 8` | `D:\workspace\zcode研究` 523 / `D:\workspace\阿里agent能力全调研` 465 / `D:\workspace\澄迈杯` 401 … |
| E14 | `SELECT s.id, s.directory, s.slug, COUNT(mu.id) ... WHERE s.directory LIKE '%agent-asset'` | 工作流会话 slug 形如 `sess_dwf-dwfrun-56c4fa86-eb3...`；非工作流形如 `sess_cad6cf65-...-c14811e0c10` |
| E15 | `SELECT query_source, COUNT(*) FROM model_usage GROUP BY 1` | `workflow_child` 87255 / `subagent` 30328 / `main_turn` 27069 / `session_title` 66 / `compact` 26；本工作区下 `main_turn` 308 / `workflow_child` 629 / `subagent` 19 |
| E16 | `SELECT * FROM tool_usage WHERE tool_name='Bash' LIMIT 1` | 该行**不含命令正文**（只有 callID/时间/exit_code/字节数） |
| E17 | `SELECT id,message_id,session_id,data FROM part WHERE data LIKE '%<tool_call_id>%'` | 命中 4 条；`json.loads` 后结构 = `{"type":"tool","callID":...,"tool":"Bash","state":{"status":...,"input":{"command":"<完整命令正文>","description":...},"output":...}}` |
| E18 | `SELECT tool_name, COUNT(*) FROM tool_usage GROUP BY 1` | `Bash` 93466 / `Read` 27653 / `Edit` 17491 / `Write` 10346 / `TodoWrite` 6614 / `mcp__node_repl__js` 5528 / `WebFetch` 4638 / `submit_result` 2027 / `Agent` 758 / `CreateWorkflow` 356 |
| E19 | `SELECT exit_code, COUNT(*) FROM tool_usage WHERE exit_code IS NOT NULL` | `0`→163340 / `1`→3524 / `2`→2184 / **`255`→245 / `127`→188 / `128`→90 / `143`→64** / `28`→58 / `3`→30 … |
| E20 | `... WHERE exit_code IN (143,255,127,128) GROUP BY 1,2` | 四者**全部 tool_name='Bash'** |
| E21 | `SELECT error_type, retryable, COUNT(*) FROM model_usage WHERE error_type IS NOT NULL` | `rate_limited` 1→7430 / 0→**57**；`timeout` 1→1318；`stream_idle_timeout` 1→775 / 0→113；`cancelled` 0→217；`network_error` 1→112；`context_exceeded` 0→**14**；`auth_failed` 1→19；`invalid_request` 0→12；`unknown` 1→66 / 0→25 |
| E22 | 三棵 `oracle/out` 的时间戳字段 grep | hotwords **0 命中** / speaker-mapping **0 命中** / deploy-pack **8 命中**（`fixtures-run.json`、`pack-{canonical,subset}-validate.json`、`red/red-{bad-yaml,env-drift,hardcoded-secret,missing-service}-report.json`、`validate.json`） |
| E23 | `grep -n "datetime\|started_at\|duration_s" v5/assets/deploy-pack/oracle/run_fixtures.py` | `:118 "started_at": datetime.now().astimezone().isoformat(timespec="seconds")`、`:119 "duration_s": round(time.time()-t0, 2)` |
| E24 | 行尾普查（Python 逐文件数 `\r\n` / 纯 `\n`） | speaker-mapping **12 CRLF / 12 LF**；hotwords **10 CRLF / 34 LF**；deploy-pack **0 / 14** |
| E25 | 相对路径排序树哈希（两跑比对） | speaker-mapping 24 文件 `c3729ed329ce8534` `rerun_identical=True`；hotwords 54 文件 `c7dca51c15186b07` True；deploy-pack 14 文件 `cfd004f20120260f` True |
| E26 | raw 哈希 vs LF 归一哈希 | speaker-mapping `c3729ed329c` vs `84c1188e56f` **不等**；hotwords `c7dca51c1518` vs `e9104784b5ec` **不等** |
| E27 | `find v5/assets/*/oracle/out -type f \| wc -l` | speaker-mapping 24 / hotwords 54 / deploy-pack 14 |
| E28 | `wc -l keyfiles.sha256` + `grep -c "oracle/out"` | **19** 条；`oracle/out` 覆盖 **0**；路径全为 `/opt/gpumachine/projects/zcode-research/...` |
| E29 | `git config core.autocrlf` + `ls .gitattributes` | **`false`**；仓库根**无** `.gitattributes` |
| E30 | `python -c "json.load(...)"` 四份根目录 eval JSON | `sm/zctlmcp/dp_student_eval.json` → **OK**；**`hw_student_eval.json` → FAIL `JSONDecodeError: Expecting value: line 1 column 2 (char 1)`** |
| E31 | `hw_student_eval.json` 逐编码试解 | **`utf-8 -> OK`**（`[PASS] script_sequence_consistent: 10 步序列（list_initial、add_o`）；`gbk -> FAIL`。**→ 文件编码正常，乱码是我 shell 显示层问题**（弯路 3 的纠正） |
| E32 | `json.load` 三份 `v2/evalbench-v02/*/ab_summary.json` | schema 均为 `slug/name/assetType/tasks/baselineMean/treatmentMean/delta/winRate/reverseTasks/accepted/driftNote/taskAggs[]/correction{}`；`taskAggs[]` 项 = `id/baseMean/treatMean/majority/repNotes` |
| E33 | meeting-minutes `taskAggs` 逐条读 | t1..t8 的 `treatMean` **全部 = 10**；`baseMean` = 5/3.5/3.5/7/2.5/9/4/3.5；`baselineMean=4.75` `delta=5.25` `winRate=1.0` `reverseTasks=0` `accepted=true` |
| E34 | 三份 `correction` 字段全文 | **三份逐字相同**：「v0.2 首测脚本 majority 计算把甲乙判反（`(better==='a')!==swap` 应为 `===swap`）：均值与 delta 未受影响，majority/winRate/reverseTasks/accepted 原值全部反演…」 |
| E35 | 读 `v5/eval-round-20261001/scorecard.md` + `results.tsv` | 41 门 38 PASS / 3 FAIL；FAIL = `dp01b_fixtures_out_byte_stable` / `sm05_green_pkg_vs_oracle` / `hw07_green_self_deterministic`；§3 三项**全部诊断为台账/基线侧问题，非资产缺陷** |
| E36 | 读 `classroom/rehearsal/round-1/record.md` 缺陷表 | D1–D5 原文（D3 含「**实际触发一次**」，D5 含「误指 dist 包行（L14-16）→ 改为 L162/L163/L164」） |
| E37 | 读 `v5/assets/speaker-mapping/eval/runner.py:1-30` | `:19-20`「产出约定：在 oracle/ 目录为 cwd、以相对路径 --out 运行（contract.md §3）」；**增补条款 A-2**「discover JSON 的 transcript 路径回显按 `\`→`/` 对称归一后比对——基线为 Windows 壳产出的平台路径分隔符差异不算行为差异；9 txt 仍逐字节严格比对」 |
| E38 | 读 `v5/assets/hotwords/eval/runner.py:1-25` + 退出码 grep | docstring：全过 exit 0 / 任一失败 exit 1 / argparse 用法错误 exit 2；`:496 return 0 if all_ok else 1`；`:500 sys.exit(main())` |
| E39 | 读 `v2/standard/EVAL-SPEC-v0.2.md:165-235, 330-400` | §3.5-1 infra_error 原文（**未点名限流**）、§3.6 复合线、§4.3 公平性禁令四条、§4.4 五元组、§8.1 benchmark.json 全文 schema、附录 B 检查单 |
| E40 | 读 `BASELINE.md:95-105, 140-155` | #19 四 runner 全绿（A）、#20 红路 fail-closed（A）、#21 学员产物可复评（A）、#22 **hw_student_eval.json 非纯 JSON**（B）、并发互踩段（含 peidian spec_hash 与 autocrlf 双因根因） |

### 3.2 我**没有**验证的（诚实标注，不得当作已验证）

- **未跑 `zcode -p` headless**。因此「headless 进程是否在 `db.sqlite` 落一条带臂 cwd 的 session 行」**未验证**。这是 §2.1 关联链的**唯一未验证前提**，也是我认为 harness 自测的第 0 号门。
- **未验证 `zcode -p` 是否支持 per-arm `--cwd`**。轨迹 5 把它列为 R-2（未验证）。若不支持，`session.directory` 关联键塌陷，臂无法分离。
- **未复算轨迹 5 的限流率/耗时分位数表**（5.61% / 0.00% / max 3786s 等）。我复算的是 `error_type × retryable` 交叉与 exit_code 分布（E19/E21），限流率按模型的那张表**直接引自轨迹 5**。
- **未跑 kimi.exe headless**，Step-3.7-Flash 通道（R-3）完全未触及。
- **未验证 `part.data` 在 `zcode` 升级后的 schema 稳定性**。`schema_migration` 表存在说明 schema 会变，但我没有版本契约文档。
- **未验证 db 里是否存在可用的 nonce / 污染扫描字段**。holdout nonce 反向扫描是**我的建议**，其可行性基于「nonce 是程序化注入的随机值」这一 PLAN §3.5.1 的设计前提，我未见到实际 nonce 产物。

---

## 4. 倾向性结论（标置信度）

1. **过程轨断言应当建立在结构化遥测（`tool_usage` + `part.data` + `session.directory`）上，而不是转录文本正则。** 命令全文、逐步 exit_code、逐步 read_only/destructive、每臂 cwd 四样都能确定性取到。**置信度：高**（E8–E20 实测；但受结论 6 的 schema 稳定性制约）。
2. **`session.directory` 是臂 ↔ 遥测的可行关联键**，`model_usage.session_id → session.id` 全命中无孤儿。**置信度：高（关联可行性）**；**「headless 每臂进程会落这种行」置信度：低—未验证**。
3. **PLAN §3.3 只点名了 1/3 的参照区破坏点。** 实测 3 处（`hotwords/oracle/run_all.py:57`、`hotwords/package/run_all.py:66`、`deploy-pack/oracle/run_fixtures.py:58`），其中 package 那处在**可分发形态**里、deploy-pack 那处是**部分删除伪装成内容回归**。oracle 保护测试必须是属性扫描 + 登记表。**置信度：高**（E3–E6 实测）。
4. **PLAN §5.4 的 oracle 哈希 abort 判据若实现为整树裸哈希，会在 deploy-pack 上每轮误 abort**（8/14 文件带墙钟戳，源头 `run_fixtures.py:118-119`；scorecard §3.1 已有同类「口径过严」判例）。必须带易变面登记 + **自标定三跑法**。**置信度：高**（E22/E23/E35 实测）。
5. **哈希门必须显式声明行尾登记基准。** 三棵参照区树实测混合行尾（12/12、10/34、0/14），raw 哈希 ≠ LF 归一哈希；本仓已有 autocrlf 翻转导致 spec_hash 全不匹配、51 用例从未执行的完整实证（peidian）。**置信度：高**（E24/E26/E29/E40 实测）。
6. **把 `db.sqlite` 当唯一真值源会把 harness 绑死在未公开的内部 schema 上**（`schema_migration` 表存在）。建议双源（结构化为主 + 转录为备 + 两源不一致判 infra_error）。**置信度：中**（schema 会变是事实；变化频率与破坏程度未量化）。
7. **`delta` / `winRate` / `reverseTasks` 的单测必须是变形测试（标签互换不变量），不是样例断言。** 仓库里已有一次 `(better==='a')!==swap` 符号反转 bug，同时污染三份文件的 majority/winRate/reverseTasks/accepted，而**均值与 delta 毫发无损**——即「均分对不对」抓不到它，最终靠人工重算补救。**置信度：高**（E32/E34 实测原文）。
8. **三臂迁移必须额外断言「旧裸 `delta` 字段消失或显式别名」**，否则 PLAN §3.2「防 Δ 一词三义」在迁移中自我挫败。现有 `ab_summary.json` 与 EVAL-SPEC §8.1 `aggregate` 都有裸 `delta`。**置信度：高**（E32/E39 实测 schema）。
9. **饱和检测有一条现成的 golden input**：meeting-minutes 8 任务的 `treatMean` 实测全为 10（E33），喂进去必须判 100% 饱和并拒绝据此算 `delta_vs_prev`。**置信度：高**。
10. **MVP 必须加负控（negative controls），否则「恒真 harness」与「正确 harness」不可区分。** 建议 8 条（NC-1…NC-8），其中 **NC-8（人为做坏产物必须落被测失败桶）** 最容易被忘也最重要——它防「一切都是 infra」这个万能借口。**置信度：高**（这是对 E7 的直接推论；成本低）。
11. **超时/装置失败有机器指纹可分**：`tool_usage.exit_code` 的 143（SIGTERM，128+15）/ 255 / 127 全部来自 Bash，可与「模型自己失败」区分。分类器应据此给可审计 reason。**置信度：中高**（E19/E20 实测分布；但「harness 超时 kill 一定产生 143」这一因果未在本机复现）。
12. **D2 与 D4 的朴素断言都会失效**：D2 的「禁绝对路径」会因契约要求特定 cwd + A-2 归一化条款 + cmd.txt 解释器路径形态而在 Windows 上必然误报；D4 是**间接写**（Bash 调 CLI 且 `--store` 指向参照区），只查 Edit/Write 会整个漏掉。**置信度：高**（E36/E37 实测契约原文）。
13. **MVP 选 speaker-mapping 有两条独立理由**（PLAN 只写了一条）：无破坏性调用（E7 零命中）**且** oracle 树零时间戳（E22 零命中），后者是哈希门不被易变文件污染的前提。**置信度：高**。**但它不豁免行尾基准问题**（其树 12 CRLF / 12 LF 混合，E24）。
14. **可见性边界判据 = 真值是否锚在不可篡改历史里。** oracle 完整性 / 负控 / 臂间公平全部可完全公开（K-3 D3 的 `git checkout` 恢复已经证明这个机制有效）；**唯一必须 holdout 的是 holdout 实例与「资产是否真泛化」的测量**。**置信度：中高**（判据本身是方法论主张）。
15. **`keyfiles.sha256` 不能照抄**：19 条绝对 Linux 路径（本机 19/19 找不到文件）+ `oracle/out` 零覆盖。**置信度：高**（E28 实测）。
16. **限流分离测试的优先级由量级决定**：GLM 5.61%/6.53% vs minimax 0.00%——按四族均摊约每族 1.4% 的臂会被冤枉，在 n=2 小规模上足以翻转「反向任务 ≤1」这条硬条件。（限流率引自轨迹 5，我未复算）**置信度：中**。

---

## 5. 未决问题

1. **[阻塞性，最高优先] `zcode -p` headless 是否落带臂 cwd 的 session 行、是否支持 per-arm `--cwd`？** 我未跑。**若否，infra_error 分类与效率门在 process-driven 拓扑下不可实现**，必须退到工作流拓扑（拿记账）或自建埋点。**这条应当先于 WS1 第 2 步回答。**
2. **`context_exceeded` 这一「装置设计缺陷」桶在 `benchmark.json` 里落在哪个字段？** EVAL-SPEC §8.1 的 `tasks[].arms[].runs[]` 只有 `infra_error: boolean`，装不下第三种语义。需要 schema 决断：是加字段、加枚举、还是映射到 `unjudgeable`。
3. **易变面自标定的三跑法在真实跑批时是否稳定？** deploy-pack 的生成器若在某轮恰好不写时间戳（如某条早退路径），两跑 diff 会漏掉该文件，第三跑就会误 abort。需要「三跑不一致时判 infra_error 并要求人工登记」的兜底条款。
4. **`part.data` / `tool_usage` 的 schema 稳定性契约从哪来？** 没有公开契约。是否接受把它当主源（配转录备源）？若不接受，过程轨的主证据只能是转录正则，测试成本与假阳性率都要重估。
5. **负控的「故意失败」如何与真实失败在事后区分？** 建议负控跑在独立目录树 + 独立 `run-id` 前缀（如 `nc-`），且禁止其输出进 `baseline/<family>/`。但 PLAN 未给负控留位置——需要决断是否把负控纳入 WS1 交付物。
6. **臂间公平的 nonce 掩码规则**：模型可能主动改写输入里的值。断言「两臂输入树逐字节相同」在跑批**开始前**成立，但跑批**中**模型改了值就不可比了。这个边界要不要管？
7. **效率门的 token 口径**：`computed_total_tokens` vs `input_tokens + output_tokens`、`cache_read_input_tokens` 含不含、跨 attempt 去重规则。这三问不定，效率门数字无意义。
8. **`model_catalog_unavailable` 的宿主范围**（轨迹 5 R-5，PLAN §9.1 R-8 承继）仍未定——影响全量矩阵拓扑选型，进而影响 §2.1 的关联链是否需要重做。
9. **kimi 通道（Step-3.7-Flash）的转录归一化器**未设计未验证；它的臂能不能进同一套 `session.directory` 关联链**完全未知**（kimi 是独立 CLI，可能根本不写这个 db）。若不写，第四列在 infra_error 分类上是盲区。

---

## 6. 给测试撰写者（GLM-5.3）的建议

按「先做/先定」排序，不按重要性。

1. **把 harness 自测第 0 号门定为「臂 ↔ 遥测关联可建立」**：跑一个 `zcode -p`（哪怕 PONG 级最小任务），断言 `db.sqlite` 里出现一条 `session` 行、其 `directory` 等于臂目录、且有 `model_usage` 行 join 上。**这一条不绿，§2.1 的全部 infra 测试都无从写起。** PLAN §5.4 把它排在第 1 步的「装载路径」旁边，我建议**提到第 0 步之前**。
2. **oracle 保护写成「属性扫描 + 登记表 + 扫描器 meta-test」三件**，不要写成对某条路径的检查。扫描器必须对四种绕过形态（字符串拼接 / `chdir` 相对 / `..` 穿越 / 符号链接）各有合成 fixture。登记表第一次生成**预期是红的**（B1/B2/B3 三处都在），让它显式化，不要让测试假装全绿。
3. **把 B2 写进走查与学员手册**：`hotwords/package/run_all.py:66` 在可分发包里也会 `rmtree`——这是 K-3 D3 修复（复制到 scratch 再跑）在 package 形态上的对应要求，PLAN 与走查都没提。
4. **哈希门的设计文档必须先写清三件事**：相对路径（不是 `keyfiles.sha256` 的绝对路径）、行尾登记基准（建议文本统一 LF 归一）、易变面自标定三跑法。**并把「基准」写进哈希产物本身**，这样换机时能立刻看出是不是基准漂移而不是资产变了。
5. **哈希门断言用「哈希 + 文件清单 + 文件数」三合一**：我实测三个资产是 24 / 54 / 14 个文件，数目本身是廉价不变式，能抓住 B3 那种「只删一个子目录」的破坏。
6. **过程轨断言建立在 `tool_usage` + `part.data` + `session.directory` 上，转录文本只留给污染扫描。** 双源交叉，不一致时判 infra_error（不是被测失败）。作用域用 `read_only` / `destructive` 限定为状态变更型命令。
7. **D2 与 D4 单独写假阳性分析章节**，别混在别的断言里：
   - D2 禁的是**资产产物路径**用绝对/跨 cwd，系统路径豁免；另写一条**归一化器的单测**（`fixtures\normal.txt` 与 `fixtures/normal.txt` 必给同一判定），依据是 `runner.py` 的增补条款 A-2。
   - D4 必须解析 Bash 命令行参数指向（`--store <oracle path>`），**只查 Edit/Write 会整个漏掉**。
   - D3 必须路径规范化后判定，否则 `out/oracle_student/run_all.py`（合法 scratch 副本）与 `oracle/run_all.py`（地雷）无法区分。
8. **把 D5 写成纯静态检查**（`REGISTRY L<n>` 引用 → 资产路径映射），零模型零成本，且它已经真实发生过一次。
9. **MVP 加 8 条负控（NC-1…NC-8），并把 MVP 验收判据改写为「负控全红 + 正常臂不误报」。** NC-8（人为做坏产物必须落**被测失败**桶）单独强调——它是防「一切都是 infra」的唯一定位针。负控的失败**不得进 REGISTRY、不得进 `baseline/<family>/`**。
10. **`delta` / `winRate` / `reverseTasks` 用变形测试**：标签互换 → `winRate→1-winRate`、`reverse_tasks` 不变、`delta` 变号、`win↔loss` 互换。**把 `ab_summary.json` 那次 `(better==='a')!==swap` 的原文贴进测试文档的注释里**——这是本仓最硬的论据，比任何假想风险都有说服力。
11. **三臂迁移测试里加一条「旧裸 `delta` 字段不得残留」**。PLAN §3.2 说要防「Δ 一词三义」，但 EVAL-SPEC §8.1 的 `aggregate.delta` 和 `ab_summary.json` 的 `delta` 都还在——迁移不处理它，目标自我挫败。
12. **饱和检测用真实 golden input**：把 `v2/evalbench-v02/meeting-minutes/ab_summary.json` 当固定测试样本，断言判 100% 饱和并拒绝据此算 `delta_vs_prev`。这是少数「今天就能写、且输入已在盘上」的测试。
13. **跨族不可比、跨版本 bump 作废，都写成否定式测试**（喂不合规数据必须拒绝出数 + 明确消息），不是文档纪律。禁令型条款不给否定式测试就会退化成约定。
14. **矩阵排布假设做成数据驱动回归**：从库里算各族近 N 天限流率，GLM 族超阈值则红。**否则「minimax/step 为主体」的排布会静默腐化**，而腐化后的表现是「Δ 变小了」——会被误读成资产变差。
15. **落盘一律加写-读-断言往返自测**（写入 → `json.load` 回读 → 校验必填键 → 校验编码 → 校验行尾）。反面教材就在工作区根目录：`hw_student_eval.json` 是合法 UTF-8 但**不是 JSON**（shell 重定向的产物）。
16. **把「装置设计缺陷」（context_exceeded）作为第三桶写进测试的分类矩阵**，不要只写两桶。PLAN §5.6 已经这么规定，但 §5.5 的 infra_error 判据补丁只列了两类，**两处口径要统一**。
17. **未决问题 1（headless session 落库 + per-arm cwd）建议标为 WS1 的硬前置**，并写进 §7 WS1 的「依赖」列；O-17（落盘位置）可以照建议默认值先行，但这条不行——它决定 harness 架构。
