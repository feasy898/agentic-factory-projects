# K-3 彩排记录 — round-1（2026-10-02 夜班）

> 学员角色：zcode 主会话以零上下文姿态执行（仅依据 handbook.md + walkthrough.md）。
> 时间盒：约 40 分钟。环境：Windows Server 2022 / Python 3.12.10 / Git Bash。
> 判定：**全部步骤 PASS，三课交付物齐备，彩排通过。**

## 逐步结果

### 第 0 步 环境自检 — PASS
python 3.12.10；where python 首条 C:\Program Files\Python312\python.exe；git log 首行 0ab1c25 docs: 接手文档。

### 第 1 课 speaker-mapping（REGISTRY L164）
- 1.1 基线绿路 `python eval/runner.py oracle/out oracle/out` → **PASS**（exit 0）
- 1.1 红路 `python eval/runner.py _red_empty oracle/out` → **PASS**（exit 1，4/4 fail-closed）
- 1.3 学员复刻 24 产物（oracle/ 为 cwd、相对路径、`2>` stderr 存档）→ **PASS**（24 文件，零命令失败）
- 1.3 评测 `python eval/runner.py out/student_run1 oracle/out` → **PASS**（exit 0，4/4：replacement / unmapped_warnings / discover_stats / reference_agreement_100pct 全 True）
- 交付物：`v5/assets/speaker-mapping/out/student_run1/`（24 文件）✅

### 第 2 课 deploy-pack（REGISTRY L163）
- 2.2 绿路 → **PASS**（exit 0，4/4；compose 三服务/env 双向一致/validate ALL GREEN 7 pass/文本一致率 100%）
- 2.2 红路 → **PASS**（exit 1）
- 2.3 `python oracle/gen_deploy.py --services asr,minutes,todo --out out/student_pack1` + `python oracle/validate.py --pack out/student_pack1` → **PASS**（ALL GREEN — 7 pass / 0 fail）
- 2.4 评测 `python eval/runner.py out/student_pack1 oracle/out` → **PASS**（exit 0，4/4）
- 交付物：`v5/assets/deploy-pack/out/student_pack1/`（docker-compose.yml / .env.example / DEPLOY.md）✅

### 第 3 课 hotwords（REGISTRY L162）
- 3.2 绿路 → **PASS**（exit 0，4/4）；红路 → **PASS**（exit 1）
- 3.3 复制 oracle→`out/oracle_student` 后跑 `run_all.py` → **PASS**（exit 0，manifest.json all_pass=true + 10 步快照）
- 3.3 CLI 实操（scratch store）add/list/export → **PASS**（export 产 `校园环境专区 30` funasr 行）
- 3.4 评测 `python eval/runner.py out/oracle_student/out oracle/out` → **PASS**（exit 0，4/4，54 文件一致率 100%，cmd.txt 归一化吸收平台路径）
- 交付物：`v5/assets/hotwords/out/oracle_student/out/` + `out/student_words.txt` ✅

### 终检：6 门全表复跑 — PASS
SM green=0 red=1；DP green=0 red=1；HW green=0 red=1。

## 彩排发现的缺陷与修复（已全部回写 walkthrough.md / handbook.md）

| # | 缺陷 | 修复 |
|---|---|---|
| D1 | 走查初稿 SM 命令漏 `--transcript/--mapping` 参数名、DP 漏 `--services/--pack`、HW export 漏 `--format`（共 5 处 CLI 参数错误） | 按 `--help` 实测逐一改正 |
| D2 | SM 学员流程首版从资产根以绝对相对路径跑，导致 discover JSON transcript 回显与基线不符 + stderr 存档缺失（评测 1/4 → 2/4 fail） | 改为 contract §3 规定的「oracle/ 为 cwd + 相对路径 + 2> 存档」，评测 4/4 |
| D3 | HW 学员流程首版让学员原地跑 `oracle/run_all.py`——该脚本硬编码 OUT=oracle/out，**会清空重建评测参照区**（实际触发一次，cmd.txt 被写入 Windows 绝对路径） | 已 `git checkout` 恢复参照区；走查改为「复制 oracle→out/oracle_student 再跑」，并加红线警告 |
| D4 | 学员流程初版让学员向 `oracle/out/_work/store.json`（参照区内工作库）添加词条 | 改为 scratch store（out/student_store.json） |
| D5 | REGISTRY 行号引用初稿误指 dist 包行（L14-16）；v5 资产与 dist 包是不同代际不同功能 | 改为真实登记行 L162/L163/L164 |

## 红线核查

- 评测器/阈值零改动（git diff runner.py 全部为 0 行变更，仅换行噪声）；
- 参照区 oracle/out 恢复后与 HEAD 一致（git status 0 变更），恢复后绿门复跑 exit 0；
- 课堂产物全部落在各资产 out/（untracked scratch），未污染任何 tracked 文件。

## 遗留（不阻塞彩排判定）

- 学员产物 out/ 目录与 scratch helper（fix_student.py / rehearse_hw.py）为彩排证据，保留在 untracked 区，不入课堂提交口径（如需留档由 owner 裁定是否 git add）。
