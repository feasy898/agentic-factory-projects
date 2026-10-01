# AB4 · 非法输入拒绝 A/B 对照 — arm-a / rep1 / OUT.md

- **日期**：2026-09-30（本机 windev-01）
- **被测技能（A 臂）**：`package/scripts/gen_doc.py`（17286 B，按名称/大小核验存在）
- **参照实现（B 臂）**：`oracle/oracle.py`（17212 B，按名称/大小核验存在）
- **运行环境**：Windows Server 2022 / Python 3.12.10（`C:\Program Files\Python312\python.exe`）
- **运行器**：`D:\workspace\zcode研究\_ab4_arma_rep1_work\run_ab4.py`；10 次子进程运行（2 臂 × 5 组），每次 timeout 180 s，cwd=scratch（skillfactory 之外），逐次全树快照差分检测残留；逐次完整 stdout/stderr 存于 `_ab4_arma_rep1_work\logs\*.log`。
- **限制协议（禁止读取 skillfactory/ 任何文件）执行情况**：本 rep 未打开/未打印任何 skillfactory 文件的内容。仅 (a) 按任务要求**执行**上述两个入口脚本；(b) 对 ROOT 顶层、`package/out`、`oracle/out` 做了**名称/大小级**结构快照用于残留检测（无内容）。contract.md 原文**未读取**——§2 的一致性判定以参照实现（oracle）的观测行为为基准做 A/B 行为对照，见第六节声明。

---

## 一、任务与判定口径

任务：让 A、B 分别接受四组非法输入（①`--template 证书` ②`--data` 指向不存在文件 ③`--data` 内容不是 JSON ④`--data` 顶层为数组），另以 `oracle/inputs/周报/case1.json` 作合法对照；逐组记录退出码、stderr、产物残留；判定被测 CLI 契约（contract §2）与参照是否一致。

判定口径（因 contract.md 禁读，采用行为对照）：**一致** = 同组内 A/B 满足：退出码相同、均为"拒绝"语义（非法→非零退出+stderr 报错+stdout 空+零产物残留；合法→0+产物落盘），报错可归入同一失败类别。stderr 的**措辞/前缀差异**记为"表述微差"，不作为契约不一致，但逐条如实记录。

## 二、方法

CLI 契约命令行（与 ab2/ab3 rep 相同）：`python <entry> --template <模板名> --data <json> --outdir <scratch 内全新目录>`。

非法输入全部在本 scratch（skillfactory 之外）构造，内容逐字如下：

| 组 | 输入 | 构造方式 | 逐字内容/状态 |
|---|---|---|---|
| g1 | `--template 证书`（模板名非法） | 直接传参；`--data` 用合法 case1.json，使模板名成为唯一非法项 | `证书`（合法集：周报/请示函/会议通知/工作总结） |
| g2 | `--data` 文件不存在 | 传入从未创建的路径 | `...\_ab4_arma_rep1_work\inputs\nonexistent_不存在.json`（assert 不存在） |
| g3 | `--data` 内容不是 JSON | scratch 手写 69 B 文本文件 | `这不是JSON：键＝值；第二项 ＝ 值2。{未闭合的伪JSON` |
| g4 | `--data` 顶层非对象 | scratch 手写 23 B JSON | `["数组", "非对象"]` |
| g0 | 合法对照 | `oracle/inputs/周报/case1.json`（456 B），模板=周报 | — |

残留检测：每次运行前后对整个 scratch 工作树（跳过 `logs/`）做 路径→大小 快照差分；另对 skillfactory 的 ROOT 顶层、`package/out`、`oracle/out` 做运行前后名称/大小快照差分。

## 三、结果总表

| 组 | 臂 | 退出码 | stdout | stderr（要点） | 产物残留 |
|---|---|---|---|---|---|
| ① 模板=证书 | A | **2** | 空 | argparse：`invalid choice: '证书' (choose from 周报, 请示函, 会议通知, 工作总结)` | **无**（outdir 未创建） |
| ① | B | **2** | 空 | argparse：`invalid choice: '证书' (choose from 周报, 请示函, 会议通知, 工作总结)` | **无**（outdir 未创建） |
| ② data 不存在 | A | **2** | 空 | `错误：数据文件不存在：<路径>` | **无**（outdir 未创建） |
| ② | B | **2** | 空 | `[oracle] 数据文件不存在: <路径>` | **无**（outdir 未创建） |
| ③ 非 JSON | A | **2** | 空 | `错误：数据文件不是合法 JSON：<路径>（Expecting value: line 1 column 1 (char 0)）` | **无**（outdir 未创建） |
| ③ | B | **2** | 空 | `[oracle] JSON 解析失败: Expecting value: line 1 column 1 (char 0)` | **无**（outdir 未创建） |
| ④ 顶层数组 | A | **2** | 空 | `错误：数据 JSON 顶层必须是对象（键值对），实际为 list` | **无**（outdir 未创建） |
| ④ | B | **2** | 空 | `[oracle] 数据必须是 JSON 对象（键值对）` | **无**（outdir 未创建） |
| g0 合法对照 | A | **0** | 生成摘要 | 空 | `fields.json`(2011 B) + `文书.docx`(37164 B) |
| g0 合法对照 | B | **0** | 生成摘要 | 空 | `fields.json`(2011 B) + `文书.docx`(37227 B) |

skillfactory 残留检查：**无任何结构变化**（ROOT 顶层、`package/out`、`oracle/out` 运行前后快照一致；`package/out`/`oracle/out` 两个目录名亦未被新造）。

## 四、逐组明细（stderr 为日志原文逐字，无截断）

### 组① `--template 证书`（模板名非法）— 判定：**一致**
- A：exit=2；stderr：
  ```
  usage: gen_doc.py [-h] --template {周报,请示函,会议通知,工作总结} --data DATA --outdir
                    OUTDIR
  gen_doc.py: error: argument --template: invalid choice: '证书' (choose from 周报, 请示函, 会议通知, 工作总结)
  ```
- B：exit=2；stderr：同构（仅 prog 名为 `oracle.py`，usage 折行位置随 prog 名长度不同）。
- 两臂同为 argparse choices 拒绝、退出码 2、零残留、outdir 未创建。微差：usage 首行 prog 名。

### 组② `--data` 指向不存在文件 — 判定：**一致**
- A：exit=2；stderr：`错误：数据文件不存在：D:\workspace\zcode研究\_ab4_arma_rep1_work\inputs\nonexistent_不存在.json`
- B：exit=2；stderr：`[oracle] 数据文件不存在: D:\workspace\zcode研究\_ab4_arma_rep1_work\inputs\nonexistent_不存在.json`
- 同类失败（文件不存在）、均含完整路径、退出码 2、零残留。微差：前缀措辞（`错误：` vs `[oracle]`）与冒号全/半角。

### 组③ `--data` 内容不是 JSON — 判定：**一致**
- A：exit=2；stderr：`错误：数据文件不是合法 JSON：D:\workspace\zcode研究\_ab4_arma_rep1_work\inputs\not_json.txt（Expecting value: line 1 column 1 (char 0)）`
- B：exit=2；stderr：`[oracle] JSON 解析失败: Expecting value: line 1 column 1 (char 0)`
- 同类失败（JSON 解析错误），两臂透传了相同的底层解析错误文本。微差：A 额外附带文件路径，B 不带。

### 组④ `--data` 顶层为 `["数组","非对象"]` — 判定：**一致**
- A：exit=2；stderr：`错误：数据 JSON 顶层必须是对象（键值对），实际为 list`
- B：exit=2；stderr：`[oracle] 数据必须是 JSON 对象（键值对）`
- 同类失败（顶层类型校验）、退出码 2、零残留。微差：A 额外报告实际类型 `list`。

## 五、合法对照组（g0：周报/case1.json）— 判定：**一致（对照通过）**
- A：exit=0；stdout=`已生成：...\A\g0_合法对照\out\文书.docx（模板=周报，标题=研发部工作周报，字段 filled/total=7/7，必填缺失=无，模板外键=无）`；产物 `fields.json`(2011 B)、`文书.docx`(37164 B)。
- B：exit=0；stdout=`OK template=周报 docx=... fields=... filled=7 missing=0 missing_required=0`；产物 `fields.json`(2011 B)、`文书.docx`(37227 B)。
- 两臂 `fields.json` 均为 2011 B；逐键 JSON 化 diff 后**唯一差异**是其中回填的 docx/fields_json 绝对输出路径（各臂指向自己的 outdir，必然不同），其余内容完全一致。两臂 `文书.docx` 均为合法 zip（17 entries，含 `word/document.xml`，`testzip` 无损）。docx 字节数差 63 B 属 zip 元数据级差异，产物内容级对照属 ab1 范围，本 rep 不下结论。

## 六、契约 §2 一致性总判定

**判定：被测 CLI 契约（contract §2）与参照在四组非法输入上的行为一致。**

依据（全部来自本次实跑）：
1. 四组非法输入 A/B 均**非零退出且退出码逐组相同（全为 2）**——模板名校验走 argparse（usage+invalid choice），数据侧三项校验（存在性 / JSON 可解析 / 顶层为对象）两臂均在参数解析后主动拒绝。
2. 非法输入时 stdout 两臂均为空，错误全部走 stderr；报错均可归入同一失败类别，且两臂错误文本核心语义逐组对应（组③透传的底层错误串逐字相同）。
3. **产物残留两臂逐组全为"无"**：非法路径下连 `--outdir` 目录都未创建；scratch 全树差分与 skillfactory 三个受监视位置（ROOT 顶层 / `package/out` / `oracle/out`）快照差分均为空。
4. 合法对照下两臂 exit=0、`文书.docx + fields.json` 成对落盘、fields.json 除回填路径外完全一致——证明上述拒绝行为是输入合法性驱动，而非环境故障。

如实声明：
- contract.md 原文因「禁止读取 skillfactory/ 任何文件」**未读取**；本判定为"被测 vs 参照"的行为对照结论，contract §2 条文本身未核对。
- 记录到的差异仅有三类表述微差：stderr 前缀措辞（`错误：` vs `[oracle]`）、组③ A 附带文件路径而 B 不带、组④ A 额外报告实际类型 `list`；均不改变退出码/通道（stderr）/零残留的契约语义。
- 本 rep 为单次重复（rep1）；未做多次重复采样。

## 附录：运行日志清单（`D:\workspace\zcode研究\_ab4_arma_rep1_work\logs\`）

`A_g1_template_证书.log` `A_g2_data_文件不存在.log` `A_g3_data_非JSON.log` `A_g4_data_顶层非对象.log` `A_g0_合法对照.log` `B_g1_template_证书.log` `B_g2_data_文件不存在.log` `B_g3_data_非JSON.log` `B_g4_data_顶层非对象.log` `B_g0_合法对照.log`（各含 argv、exit、stdout、stderr、outdir 状态、残留差分）；控制台全程输出另存 `_ab4_arma_rep1_work\run_ab4.console.txt`。
