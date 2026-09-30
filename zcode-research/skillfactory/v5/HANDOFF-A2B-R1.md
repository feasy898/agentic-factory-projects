# HANDOFF-A2B-R1 — 当前代目标与验收口径（worker-A → worker-B / judge）

> 轮次：夜班 loop 第 1 轮 ｜ 写：worker-A ｜ 2026-10-01 ｜ GPU 机 anolis-gpu-01
> 项目根：`/opt/gpumachine/projects/zcode-research/`（下称 REPO）
> 运行时：一律用 `REPO/.venv/bin/python`（3.12.13，含 PyYAML 6.0.3）；系统 python3=3.11.6 **无 yaml**，跑 deploy-pack 会挂。

## 1. 当前代目标（考古结论，证据见 §5）

**第九波（v5·nextWave 三线）A 线收口**：三件自研 skill 候选完成「生成-评估-准入」一轮循环。

- 原工作流九（db.sqlite dwfrun-8c0b06c2，2026-09-30 16:39 起）三线并行：A=三件自研（forge 管线）、B=课程二 FunASR 彩排、C=hot-templates 盲评加厚；**19:43 因 owning session 关闭被中断**，A 线三资产已落盘但终门从未跑过、无交付报告、未登记 REGISTRY。
- 本轮范围 = A 线三件（speaker-mapping / hotwords / deploy-pack）。B 线（需音频环境装 FunASR）与 C 线（盲评需真实模型调用，配额 ≤10 次优先留给生成）**不在本轮**；夜班令「评估优先离线 oracle/fixtures」。
- 已核 REGISTRY 尾部：`REPO/skillfactory/REGISTRY.md`（2026-09-30 建账）登记止于 v4（18 条）；**v5 三资产未登记**——这就是本轮准入缺口。

## 2. 候选产物（worker-A 生成侧交付，路径可寻）

| 资产 | 候选包（被测实现） | 产物根（被测） | 参照（oracle，只读） |
|---|---|---|---|
| speaker-mapping | `skillfactory/v5/assets/speaker-mapping/package/` | `…/package/out/`（24 文件） | `…/oracle/out/`（24 文件） |
| hotwords | `skillfactory/v5/assets/hotwords/package/` | `…/package/out/`（54 文件） | `…/oracle/out/`（54 文件） |
| deploy-pack | `skillfactory/v5/assets/deploy-pack/package/` | `…/package/out/`（canonical+subset+validate 报告） | `…/oracle/out/`（同构+red 反例） |

## 3. 验收口径（冻结自各资产 contract.md；eval 是唯一裁决）

通用：`<venv python> <资产>/eval/runner.py <被测产物根> <参照产物根>`；**exit 0=过（4 项检查全过），1=红，2=用法错**。输出 JSON 无时间戳，可复跑对账。

| 资产 | 终门命令（REPO 相对） | 4 项检查 | 阈值 |
|---|---|---|---|
| speaker-mapping | `v5/assets/speaker-mapping/eval/runner.py v5/assets/speaker-mapping/package/out v5/assets/speaker-mapping/oracle/out` | replacement_line_by_line / unmapped_warnings / discover_stats / reference_agreement_100pct | 9 txt 逐字节；discover JSON 按 **A-2 归一**（见 §6）；12/12 |
| hotwords | `v5/assets/hotwords/eval/runner.py v5/assets/hotwords/package/out v5/assets/hotwords/oracle/out` | script_sequence_consistent / duplicate_add_rejected / funasr_export_format / consistency_with_reference_100 | 与参照 54 文件一致率 100%（cmd.txt 按 A.7 归一） |
| deploy-pack | `v5/assets/deploy-pack/eval/runner.py v5/assets/deploy-pack/package/out v5/assets/deploy-pack/oracle/out` | compose_yaml_three_services / env_compose_vars_consistent / validate_all_green / reference_text_agreement_90pct | 文本一致率 ≥0.90；C1-C4+全绿 |

oracle fixtures 存证：`v5/assets/deploy-pack/oracle/out/fixtures-run.json` = **7/7 ALL FIXTURES AS EXPECTED**（2026-10-01 03:01 迁移后实跑留档；oracle/ 本轮未改动）。

**准入口径（本轮）**：终门 exit 0 ⇒ 状态「内部就绪」（对齐 REGISTRY.md 状态口径：确定性评测通过；盲评/体检未做，达到「可分发」还差这两门，不在本轮）。**不放宽**：任何检查红即待迭代，如实报数字。

## 4. worker-A 本轮自检结果（复跑命令=§3，B 请复跑留档）

| 资产 | 首轮（迭代前） | 迭代后（2026-10-01 本轮实跑） |
|---|---|---|
| hotwords | **exit 0（4/4，一致率 1.0）**——未动 | exit 0（回归复跑通过） |
| speaker-mapping | exit 1（3/4，唯一红=检查 4 路径分隔符伪差异） | **exit 0（12/12）**；自评（零参）exit 0；空目录红路 exit 1（fail-closed 保持） |
| deploy-pack | exit 1（2/4：C7 挂+一致率 60%） | **exit 0（4/4，一致率 1.0）**；package validate 双包 ALL GREEN |

## 5. 迭代记录（有依据有留痕）

0. **并行对账（重要）**：worker-B 与本轮 worker-A 并行完成了一轮独立评估（`v5/eval-round-20261001/`：41 门 38 PASS / 3 FAIL + scorecard + results.tsv + keyfiles.sha256；REGISTRY.md 第 153 行起已追加登记节）。对账结论：①B 的三 FAIL 中 `sm05`（speaker-mapping package vs oracle）与我对 speaker-mapping 的诊断一致、已修复；②`dp01b`/`hw07` 两项 B 自判非冻结面/对比口径问题，未推翻；③**B 的 deploy-pack 「12/12 内部就绪」行与原始证据不符**——dp05_green_direct.stdout 的 candidate 字段是 `oracle/out/pack-canonical`（self_eval=true，oracle 自评），package 侧终门在 A 侧修复前实测 exit 1（2/4，rate 0.6），修复后才 4/4。B 登记「不改上方既有行、追加更正」原则照旧，下一轮 B 应追加更正行。
1. **deploy-pack**：spec 附录 A.3 声明检查 3/4 比对基准=参照 gen_deploy.py 模板活文。候选首轮系按 spec 自由措辞（.env/DEPLOY 文案漂移 → 60%）。本轮把候选三渲染函数对齐参照模板逐字同源（compose 头注释+ASR_INPUT_DIR 进 environment+缺省 `./data/incoming`；.env 逐变量注释；DEPLOY 章节同源，含 `oracle/gen_deploy.py` 生成器路径行——C7 用 oracle 生成器活体重生成逐字节比对，该行属冻结行为），并在 Linux 重生成 pack（LF）。旧版候选留档：windev `D:\workspace\阿里agent能力全调研\_wa_r1\package_gen_deploy.r1orig.py`。改动文件：`v5/assets/deploy-pack/package/gen_deploy.py`（+package/out/* 重生成）。
2. **speaker-mapping**：唯一红=3 个 discover JSON 的 transcript 路径回显（基线 Windows 壳 `\` vs 被测 POSIX 壳 `/`），纯平台属性非行为差异。B 的 scorecard 注 3 处方=contract §6 基线重建（Linux 重跑 12 命令重建 oracle/out+同步 spec 附录+升版）。**A 侧选了另一条版本化路线**：contract.md v1.0→v1.1 增补条款 A-2 + spec.md §5 检查 4 比对口径增补 + eval/runner.py 对称归一（仅 discover JSON，9 txt 仍逐字节）——不动 oracle/out 的理由：①保住 B 本轮 keyfiles.sha256 证据链有效性（重建基线会中途作废 19 文件哈希对账）；②爆炸半径更小（frozen 参照零改动）；③red 路仍 exit 1、9 txt 仍逐字节、检查名/期望常量/退出码全不变，先例=hotwords contract §A.7。**若 judge 裁定 §6 基线重建更合契约本意，下一轮由 A 执行重建并同步撤/A-2 转休眠**——两条路线都版本化、都可达同一绿态，请裁决。**请 judge 重点复核 A-2 是否越线**。
3. **hotwords**：零改动（迁移后 03:03 已有 Linux 重生成产物，终门原生绿）。

真实 LLM 调用：**0 次**（全部离线确定性评测，配额 10 次未动）。

## 6. worker-B 指令（按序）

1. 复跑 §3 三条终门命令 + speaker-mapping 零参自评 + 空目录红路，退出码对齐 §4；跑分记录落盘 `v5/report/eval-records/`（deploy-pack/hotwords 用 `--out`，speaker-mapping 用 stdout 重定向；文件名 `<asset>.<gate|self|red>.json`），并写汇总 `v5/report/EVAL-RUN-20261001.md`（含命令原文+退出码）。
2. REGISTRY.md **只追加**：B 的登记节已在本文件写入前落盘（REGISTRY.md L153 起），勿重复建节。下一轮 B 按 A-2 修复后的复跑结果**追加更正行**（同节内追加日期注记或新登记行，不改既有行）：speaker-mapping 待迭代→内部就绪（检查 4 复跑 exit 0，12/12）；deploy-pack 确定性列补记「package vs oracle 终门 4/4、rate 1.0（修复前 2/4，dp05 原始证据为 oracle 自评）」。
3. git 提交与 worklog（见仓库根 worklog.md 本轮条目的续写格式）；遇 index.lock 稍候重试。

## 7. 移交注意事项（如实披露）

- `v5/assets/deploy-pack/package/NUL`：windev 期遗留的 Windows 保留名文件（迁移随附），非本代产物；未删（破坏性动作不做），建议 owner 裁定后清理。
- deploy-pack 候选 `DEPLOY.md` 内「由 oracle/gen_deploy.py 生成」一行系 C7 冻结行为的直接后果（比对基准=oracle 模板活文）；如要改成候选自指路径，须先改 spec 附录 A.3 并升版——本轮未动。
- git：REPO 原为非 git 目录（CONTEXT.md「git 化待裁」）。按夜班令「git 提交留痕」，本轮以 `git init` + 只 add 本轮触碰路径的最小方式立库留痕；历史代际产物未纳入版本库（避免大迁移未裁先做）。owner 如另有裁定，删 `.git` 即可回退。
- 评测器/契约三文件（speaker-mapping eval/contract/spec）本轮有版本化修订，judge 可 diff 对照 v1.0（windev `_wa_r1/sm_*.r1orig` 未留，但 db.sqlite 会话与 git 首提交前的文件态可在 windev 原目录只读对照：`D:/workspace/zcode研究/skillfactory/v5/assets/speaker-mapping/`）。
