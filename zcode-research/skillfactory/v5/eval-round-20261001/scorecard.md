# scorecard — v5 代三候选离线评估（eval-round-20261001）

> 评估人：worker-B（CloudCrane 夜班 loop）｜日期：2026-10-01｜机：anolis-gpu-01
> 口径来源：各候选自带 spec.md/contract.md 冻结门（红绿矩阵）+ skillfactory/REGISTRY.md 状态口径；
> worker-A 本轮未落盘独立口径文档（考古结论），故按盘内冻结契约执行，未放宽任何阈值。
> 环境：Python 3.12.13 + PyYAML 6.0.3（python3.12）；全部离线，零模型调用。
> 原始证据：本目录 results.tsv + 各 `*.stdout`/`*.stderr`（逐项退出码）+ keyfiles.sha256。

## 汇总：41 项门，PASS 38 / FAIL 3（FAIL 3 项全部诊断完毕，见 §3）

## 1. 逐项门结果（results.tsv 全表）

| id | 实测退出码 | 期望 | 判定 |
|---|---|---|---|
| dp01_fixtures_run | 0 | 0 | PASS |
| dp01b_fixtures_out_byte_stable | 1 | 0 | FAIL |
| dp02_green_self | 0 | 0 | PASS |
| dp03_green_self_rerun | 0 | 0 | PASS |
| dp04_green_self_deterministic | 0 | 0 | PASS |
| dp05_green_direct | 0 | 0 | PASS |
| dp06_red_empty | 1 | 1 | PASS |
| dp07_red_badyaml | 1 | 1 | PASS |
| dp08_red_missingservice | 1 | 1 | PASS |
| dp09_red_envdrift | 1 | 1 | PASS |
| dp10_red_secret | 1 | 1 | PASS |
| dp11_red_subset | 1 | 1 | PASS |
| dp12_usage_zeroargs | 2 | 2 | PASS |
| sm01_regen12_ok | 0 | 0 | PASS |
| sm02_txt_normal__m_full | 0 | 0 | PASS |
| sm02_txt_normal__m_partial | 0 | 0 | PASS |
| sm02_txt_normal__m_empty | 0 | 0 | PASS |
| sm02_txt_partial__m_full | 0 | 0 | PASS |
| sm02_txt_partial__m_partial | 0 | 0 | PASS |
| sm02_txt_partial__m_empty | 0 | 0 | PASS |
| sm02_txt_empty__m_full | 0 | 0 | PASS |
| sm02_txt_empty__m_partial | 0 | 0 | PASS |
| sm02_txt_empty__m_empty | 0 | 0 | PASS |
| sm04_green_self | 0 | 0 | PASS |
| sm05_green_pkg_vs_oracle | 1 | 0 | FAIL |
| sm06_red_empty | 1 | 1 | PASS |
| sm07_usage_onearg | 2 | 2 | PASS |
| sm08_green_self_rerun | 0 | 0 | PASS |
| sm09_green_self_deterministic | 0 | 0 | PASS |
| hw01_pkg_regen | 0 | 0 | PASS |
| hw02_green_asis_pkg_vs_oracle | 0 | 0 | PASS |
| hw03_oracle_regen | 0 | 0 | PASS |
| hw05_green_self | 0 | 0 | PASS |
| hw06_green_self_rerun | 0 | 0 | PASS |
| hw07_green_self_deterministic | 1 | 0 | FAIL |
| hw08_green_pkg_vs_fresh_oracle | 0 | 0 | PASS |
| hw09_red_empty | 1 | 1 | PASS |
| hw10_usage_onearg | 2 | 2 | PASS |
| hc_hotwords | 0 | 0 | PASS |
| hc_speaker-mapping | 0 | 0 | PASS |
| hc_deploy-pack | 0 | 0 | PASS |

### 观察行（非门，信息记录）

- sm03_json_normal cmp_rc=1 (1=有差异,预期仅路径形态)
- sm03_json_partial cmp_rc=1 (1=有差异,预期仅路径形态)
- sm03_json_empty cmp_rc=1 (1=有差异,预期仅路径形态)
- hw04_oracle_regen_diff_lines=40 （>0 预期=cmd.txt 解释器路径形态）

## 2. 确定性复验（本轮补充，均离线实跑）

- deploy-pack eval runner：绿自评连跑两次 stdout **逐字节一致**（dp04，cmp 空）。
- hotwords eval runner：`oracle/out oracle/out` 无 `--out` 连跑两次 stdout **逐字节一致**（det_run1/det_run2，cmp 空，双 0）。
- hotwords `run_all.py` 基线重跑（spec §7.1 规定动作）exit 0；重跑前后 tree sha256 diff=40 行，
  全部为 cmd.txt 解释器绝对路径形态（Windows python.exe → Linux /usr/bin/python3.12），属跨机预期；
  评测侧由 contract §4/A.7 归一化吸收（hw08 对新基线绿实证）。
- deploy-pack `run_fixtures.py` 重跑 exit 0（7/7，verdict=ALL FIXTURES AS EXPECTED）；oracle/out 重跑前后仅
  5 类汇总报告 JSON 字节不同，差异字段=started_at/duration_s/generated_at（墙钟戳，非冻结面）；
  gen 产物三件套与 red 判定内容不变。dp01b 门按字节全等记 FAIL 属本台账自设口径过严，非资产缺陷。
- speaker-mapping 9 个映射产物：本机重生成（oracle 工具，同约定相对路径）vs 盘内基线 **9/9 逐字节一致**（sm02×9）。

## 3. FAIL 三项诊断（如实，未放宽口径）

1. **dp01b_fixtures_out_byte_stable**：如 §2 第 3 条——仅墙钟戳字段字节漂移，冻结面内容一致。判定：不构成资产缺陷。
2. **sm05_green_pkg_vs_oracle（exit 1）**：speaker-mapping 4 项检查 3/4 过；`reference_agreement_100pct` 红，
   不一致恰为 3 个 discover JSON 第 2 行 transcript 字段：期望（盘内 Windows 纪基线，spec 附录 A.3 冻结）
   `fixtures\normal.txt` vs 实测（Linux 重生成）`fixtures/normal.txt`。12 个主产物中 9/12 一致、9 个映射产物逐字节全等。
   按 contract.md §3 这属「路径回显约定」，但按冻结基线判即红——**按状态口径记：确定性门未全过 ⇒ 待迭代**；
   修复路径=契约 §6 基线升版流程（Linux 重跑 12 命令重建 oracle/out + 同步 spec 附录 A.3 + 升版本号），属生成侧（worker-A）动作。
3. **hw07_green_self_deterministic**：hw05 带 `--out` 而 hw06 不带，runner 在 stdout 尾部多打一行「报告: <路径>」；
   JSON 本体逐字节一致（diff 仅此一处）。已用双跑无 `--out` 复验为字节一致，判定：本台账对比口径问题，非资产缺陷。

## 4. 体检（v3/tools/healthcheck 1.0.0，只报告不设门；报告见 healthcheck/<资产>/）

| 资产（package 形态） | 评级 | 5 项 | 失分项 |
|---|---|---|---|
| hotwords | C | 2/5 | front-matter 缺 version/license/permissions；缺 eval/；缺 scripts/ |
| speaker-mapping | C | 2/5 | 同上 |
| deploy-pack | C | 2/5 | 同上 |

> 形态备注（如实登记，不推翻 C）：体检器 5 项按 dist skill 包形态设计；v5 三件为工具类资产，
> eval 在**资产级**（assets/<a>/eval/runner.py，本轮全实跑）而非 package/eval/，脚本在包根而非 scripts/。
> 同类先例：REGISTRY B 表 mcp-office-pack「配置包形态，体检器 5 项不适用」。

## 5. 准入结论（按 REGISTRY 状态口径：确定性+盲评+体检 三门；工具类盲评不适用）

| 候选 | 确定性门 | 盲评 | 体检 | 准入状态 |
|---|---|---|---|---|
| deploy-pack | **12/12 全过**（fixtures 7/7 + 绿自评/direct exit0 + 6 红全拦截 + 用法 2） | 不适用（工具类） | C（形态错配备注） | **内部就绪（工具/基建件）** |
| hotwords | **全过**（绿自评+包 vs 参照 54 文件 100% 双基线 + 红空目录 + 用法 2 + 确定性字节级） | 不适用（工具类） | C（形态错配备注） | **内部就绪（工具/基建件）** |
| speaker-mapping | 3/4 检查过；检查 4 因基线平台路径形态 9/12 | 不适用（工具类） | C（形态错配备注） | **待迭代**（基线升版流程，差距见 §3.2） |

> 三件均**不进 dist/**：可分发门=确定性+盲评+体检(A) 三者齐，且发布动作待雇主批准（红线）。
> 本轮零模型调用；双臂盲评未做（预算与口径归 worker-A/owner 裁定）。
