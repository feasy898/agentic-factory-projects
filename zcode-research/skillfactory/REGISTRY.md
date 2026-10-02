# skillfactory 资产总台账（REGISTRY）

> 建账：2026-09-30（台账登记员会话）。盘点范围：`dist/` 三个分发包、`assets/`、`v3/assets/`、`v3/tools/`、`v4/assets/`、`v4/tools/` 全部资产目录、`v2/evalbench-v02/` 三个评测对象。
> **统计行：资产总数 18 ｜ 可分发 3 ｜ v0.2 达标 4**（v0.2 达标 = 按 `v2/standard/EVAL-SPEC-v0.2.md` 复合验收线盲评 accepted=true 的对象：meeting-minutes、office-templates、hot-templates、lark-cli）。
> 状态口径：**确定性评测通过 + 盲评达标 + 体检达标（A）三者齐 ⇒ 可分发**（发布动作另待雇主批准）；缺体检或缺盲评（工具类不适用盲评）但确定性过 ⇒ 内部就绪；任一门未过 ⇒ 待迭代。
> 数字口径：确定性一列为本轮（2026-09-30）**实际复跑**结果（命令见附录 A）；盲评 Δ/胜率/反向取自盘内 `ab_summary.json`（本轮逐份 python 实读对账，见附录 A2）；体检级为本轮**复跑体检工具**结果 + 盘内 report.json 双确认（附录 A3）。v0.1 协议轮（首批 4 资产）无 reverseTasks 字段，反向列按逐任务分数计负局数。

---

## A. 分发包（`dist/`，3 件）

| 名称 | 目录 | 形态 | 状态 | 确定性评测（轮数 · 本轮复跑） | 盲评（Δ/胜率/反向） | 体检级 | 许可 | 一句话用途 |
|---|---|---|---|---|---|---|---|---|
| meeting-minutes-skill v1.0.0 | `dist/meeting-minutes-skill`（git `29bd123`，26 文件） | skill 包 | **可分发**（待雇主批准） | v1.0 初轮过→重生成 2 连败→specfix 后对同一版 golden 20/20；本轮源资产复跑 **20/20 exit 0**；包内绿自检（体检 smoke）exit 0 | v0.2：8 任务 4.75→10.0，**Δ+5.25 / 100%（8/8）/ 反向 0**，accepted=true（2026-09-30 majority 修正后重算；包内 EVALUATION.md 载 v0.1 终轮 5.7→10） | **A**（5/5；本轮复跑复核 A） | MIT | 会议转写稿→决议/待办/风险三段式纪要（docx），逐字溯源红线 |
| office-templates-skill v1.0.0 | `dist/office-templates-skill`（git `1e4ada5`，38 文件） | skill 包 | **可分发**（待雇主批准；对外标 `single_round_signal`） | 打包时 8 条生成 + 68/68 全过；本轮源资产复跑 **68/68 exit 0**；包内绿自检 exit 0 | v0.2：5 任务 7.7→8.9，**Δ+1.20 / 100%（5/5）/ 反向 0**，accepted=true（单轮，二轮未做） | **A**（5/5；本轮复跑复核 A） | MIT | 周报/请示函/会议通知/工作总结四类中文办公 docx 模板生成（python-docx 引擎） |
| hot-templates-skill v1.0.0 | `dist/hot-templates-skill`（git `52187cf`，39 文件） | skill 包 | **可分发**（待雇主批准；五门复检欠账见注） | 开发管线 2 轮（r1 挂一致率、r2 修复后过）；发包时复跑 40/40 + 16 文件逐字节一致；本轮源资产复跑 **40/40 exit 0**（一致率 min 1.0）；包内绿自检 exit 0 | v0.2：5 任务 3.9→10.0，**Δ+6.10 / 100%（5/5）/ 反向 0**，accepted=true（每臂 2 重复，20 次运行） | **A**（5/5；本轮复跑复核 A） | MIT | 主题+卖点→四平台（抖音/小红书/公众号/视频分镜）爆款内容骨架确定性渲染 |

> 注 1：三包本轮实查——`.mimosa` 运行时污染 **0**（`find dist -name .mimosa` 零命中，V6 报告所记 mm 19 文件阻断项已清）；`requirements.txt` 三包齐备（V6 阻断项已清）；各自 git 仓 1 个 commit、工作区干净。
> 注 2：hot-templates-skill 按 SKILL-SPEC §4 五门口径仍有欠账（效率门未测、盲评每臂 2<3、`benchmark.json` 未落盘，v4/report/V7-FORGE-DELIVERY.md P0-1），V7 原文要求「复检通过前不进分发」；本包以 release-candidate 形态入 dist，**发布与否随三包一并待雇主批准**。

## B. 自产资产目录（12 件）

| 名称 | 目录 | 形态 | 状态 | 确定性评测（轮数 · 本轮复跑） | 盲评（Δ/胜率/反向） | 体检级 | 许可 | 一句话用途 |
|---|---|---|---|---|---|---|---|---|
| meeting-minutes（源） | `assets/meeting-minutes` | skill | **内部就绪**（已物化为 dist 包） | v1.0→v1.1 双版 golden 归档；本轮复跑 **20/20 exit 0** | v0.1：3 任务 5.67→10，Δ+4.33 / 100%（3/3）/ 负局 0，accepted（每臂 1 对首轮信号）；v0.2 复检见 C 表 | 未单独体检（dist 形态 A） | LicenseRef-skillfactory-internal（front-matter） | 首批唯一过线资产，mm-skill 包源 |
| monthly-report-ppt | `assets/monthly-report-ppt` | skill | **待迭代**（铸造时确定性门未过） | 下发 evalPassed=**false**；盘内存量产物本轮复跑 16/16 exit 0（不推翻下发判定，需按同一版 golden 复裁落盘） | 未进入盲评（确定性门拦截，无 `tests/`） | 未体检 | 未声明（front-matter 仅 name+description） | Excel 台账→图表+月度汇报 PPT 生成器 |
| ppt-method-router | `assets/ppt-method-router` | skill | **待迭代**（盲评未达线） | 本轮复跑 **6/6 exit 0**，路由一致率 1.0（20/20，阈值 0.8） | v0.1：3 任务 8.67→8.67，**Δ0 / 33%（1胜1负1平）/ 负局 1**，未达线 | 未体检 | 未声明（front-matter 仅 2 字段） | PPT 制作多方法意图路由（按意图选最优路径，路由对但端到端零增益） |
| paper-to-skill | `assets/paper-to-skill` | skill | **待迭代**（盲评未达线） | 本轮复跑 **3/3 exit 0**（五要素/步骤可判定/统计偏差 0.0%） | v0.1：2 任务 9→8.5，**Δ−0.5 / 0%（1负1平）/ 负局 1**，未达线 | 未体检 | LicenseRef-skillfactory-internal（front-matter） | 论文/官方文档→可运行 skill 的知识蒸馏器（全批唯一负增益） |
| office-templates（源） | `v3/assets/office-templates` | skill | **内部就绪**（已物化为 dist 包） | 重生成 1 轮过；本轮复跑 **68/68 exit 0**（字段填充一致率 100%，66/66） | v0.2：5 任务 7.7→8.9，**Δ+1.20 / 100% / 反向 0**，accepted=true（单轮信号） | 未单独体检（dist 形态 A；oracle/out 有 .mimosa 混入待清理，V3-R5） | 未声明（源 package/SKILL.md 无 front-matter；dist 形态 MIT） | 中文办公四类文书模板 skill 源（含盲评 20 份 run 报告） |
| office-guard-hooks | `v3/assets/office-guard-hooks` | tooling（hook 包） | **待迭代**（体检 C） | 重生成 1 轮过；本轮复跑 **7/7 exit 0**（自测套件双侧 12/12） | 未做（tooling 未安排） | **C**（2/5：缺 front-matter 三字段、缺 `eval/`、缺 `scripts/`，`v3/healthchecks/guard-hooks/report.json`） | 未声明（front-matter 仅 2 字段） | 办公护栏 hook 包：产物落盘校验 fail-closed + CN 手机号/身份证 PII 拦截 |
| healthcheck（体检流水线） | `v3/tools/healthcheck` | tooling（软件系统） | **内部就绪**（基建件） | 重生成 1 轮过；本轮复跑 **5/5 exit 0**（oracle 对拍一致率 15/15=100%；三样本基线 A/C/B） | 不适用（工具类） | 不适用（本件即体检器） | 未声明（README 工具形态） | skill 包结构体检工具：5 检查项 A/B/C 评级，体检报告即分发物料 |
| prompt-regression | `v3/assets/prompt-regression` | tooling（评测集） | **待迭代**（对外分发前须补对拍） | 重生成 1 轮过；本轮复跑 **4/4 exit 0 ×2**（oracle 自评 + package 独立再生成物）；25 题/125 checks 六域配比达标 | 不适用（评测集；自指对拍 ≥30 条未做，现仅 3 题抽样） | **C**（2/5，工具本体判定；数据包布局错配非质量缺陷，`v3/healthchecks/prompt-reg/report.json`） | 未声明（无 front-matter） | 中文办公 prompt 回归黄金集（25 题×5 checks，70.4% 程序化可判） |
| hot-templates（源） | `v4/assets/hot-templates` | skill | **内部就绪**（已物化为 dist RC 包） | 重生成 2 轮（r1 八 case 挂一致率→1.0.1 修复）；本轮复跑 **40/40 exit 0** | v0.2：5 任务 3.9→10，**Δ+6.10 / 100% / 反向 0**，accepted=true（每臂 2 重复；ab-001/arm-a/rep2 缺 OUT.md 已披露） | 未单独体检（dist 形态 A） | LicenseRef-skillfactory-internal（front-matter；dist 形态 MIT） | 四平台爆款内容结构模板 skill 源（厂史最高盲评 Δ） |
| mcp-office-pack | `v4/assets/mcp-office-pack` | tooling（MCP 配置包） | **内部就绪**（基建件，具备对内分发形态） | 重生成 1 轮过；本轮复跑 **eval 5/5 exit 0**（oracle validate 7/7 全绿） | 不适用（tooling） | 未体检（配置包形态，体检器 5 项不适用） | 未声明（package/SKILL.md 无 front-matter） | 办公六格场景 10 条 MCP server 精选配置包：零真值密钥 + 自带校验器 + 10/10 协议握手实录 |
| office-eval-suite | `v4/assets/office-eval-suite` | tooling（评测集） | **内部就绪**（基建件） | 重生成 1 轮过；本轮复跑 **4/4 exit 0**（validate 9/9，50 题/230 checks；与参照集相同题 0≤10） | 不适用（评测集；对拍法未做，自用可） | 未体检 | 未声明（package/SKILL.md 无 front-matter） | 中文办公评测集 v2：50 题×8 域×230 条 checks + v1 兼容导出 |
| content-evaluator | `v4/tools/content-evaluator` | tooling（评测器） | **内部就绪**（基建件） | 重生成 1 轮过；本轮复跑 **6/6 exit 0**（4 fixtures 红绿基线 + oracle 一致率） | 不适用（tooling） | 未体检 | 未声明（README 工具形态） | 内容文案 9 项确定性合规打分器（dy/xhs/wx，44 极限词+平台阈值，只报告不设门） |

## C. 评测对象（`v2/evalbench-v02/`，3 件）

| 名称 | 目录 | 形态 | 状态 | 确定性评测 | 盲评（Δ/胜率/反向） | 体检级 | 许可 | 一句话用途 |
|---|---|---|---|---|---|---|---|---|
| lark-cli（第三方） | `v2/evalbench-v02/lark-cli` | skill（外部仓 `larksuite/cli`） | **内部就绪**（评测达标·我方不自产不分发本体） | 不适用（文本直评对象） | v0.2：8 任务 7.9375→9.625，**Δ+1.6875 / 75%（6/8）/ 反向 0**，accepted=true（2026-09-30 majority 修正后；t1–t4 为文档比对级证据，实跑补验是打包前置） | 未体检 | MIT（ASSET-DOC.md 记载，2026-09-29 GitHub 页实抓） | 飞书官方 CLI + 26 agent skills；v0.1/v0.2 两轮达标，「飞书办公技能包部署模板」免费层打包候选 |
| hooks-mastery（第三方） | `v2/evalbench-v02/hooks-mastery` | hook 教学库（外部仓 `disler/claude-code-hooks-mastery`） | **待迭代**（不采用口径：我方不迭代，维持禁挂） | 不适用（文本直评对象） | v0.2：5 任务 9.1→9.8，**Δ+0.70 / 60%（3/5）/ 反向 0**，accepted=**false**（条件①Δ<1.0 不过；v0.1 曾 Δ−0.67） | 未体检 | 未记录（ASSET-DOC/CATALOG 均未载） | Claude Code Hooks 教学库；两轮未达增益线，仅作课程五 hooks 模块素材与「教学材料≠可用资产」反面教材 |
| meeting-minutes（v0.2 复检对象） | `v2/evalbench-v02/meeting-minutes` | 评测对象目录（8 任务×双臂×2 重复） | **内部就绪**（复检结论已转入 dist 包） | 不适用（盲评对象） | v0.2：8 任务 4.75→10.0，**Δ+5.25 / 100%（8/8）/ 反向 0**，accepted=true（majority 修正后；治疗臂 16 判词全满分） | 未体检 | 对应自产资产（源 LicenseRef-internal / dist MIT） | 自产旗舰的 v0.2 加厚复检评测现场（84 份产物与判词留档） |

> 范围注：`assets/_report_check/` 为评测复跑留档目录、`assets/.mimosa` 等为运行时产物，均非资产，未计入 18 条。

---

## 关键文件 sha256（三个分发包，本轮实算）

计算命令（2026-09-30 实际执行，工作目录 `D:/workspace/zcode研究/skillfactory`）：

```bash
python -c "
import hashlib, glob
for p in ['meeting-minutes-skill','office-templates-skill','hot-templates-skill']:
    files = [f'dist/{p}/SKILL.md'] + sorted(glob.glob(f'dist/{p}/scripts/*.py')) \
            + [f'dist/{p}/eval/runner.py', f'dist/{p}/eval/golden.json']
    for f in files:
        print(hashlib.sha256(open(f,'rb').read()).hexdigest(), f)
"
```

| 包 | 文件 | sha256 |
|---|---|---|
| meeting-minutes-skill | `SKILL.md` | `181c8daa8069640cf8a32e32e791d914e79fe4bfb1deca0f4dbdb7107cc56827` |
| meeting-minutes-skill | `scripts/gen_docx.py` | `2b252735a79a4e5df887b2ef079a9584510873167492cbe79b10c8cb9b823f0e` |
| meeting-minutes-skill | `scripts/minutes.py` | `630068f4d33206e863cf0f53d6111b6056fe481c25fffd030da8dd783e513f80` |
| meeting-minutes-skill | `eval/runner.py` | `51721efdf7fcb33bca866746c72e52ca3294eb8bd43a2e5d44402793788ab872` |
| meeting-minutes-skill | `eval/golden.json` | `b3be400ae3b4984a1537d4909b9ea379246d8b978d3c8a179c90182c5c854315` |
| office-templates-skill | `SKILL.md` | `a008db1642d72eea814e01f7aab75476cab7b53440bb535d758972f95abd084b` |
| office-templates-skill | `scripts/gen_doc.py` | `1171b5a3738c99b71f6decf4b9ce6dd1bb3709cd3211d1d5a476095a007cad8e` |
| office-templates-skill | `eval/runner.py` | `8eb51801b6fc9fce357be87e3f13f5903720e573dcf5988167bdd41bf1f08c67` |
| office-templates-skill | `eval/golden.json` | `2fa58b07481b44bc2840b2fdd757ef19faa5ebe37e1918baf936b2b923f4ecbf` |
| hot-templates-skill | `SKILL.md` | `6ba95aeeafcbf7b9f76787aa2961081f58f777d2765eeb308499520e965ab69d` |
| hot-templates-skill | `scripts/gen.py` | `ec0ffe6a065a5f690a992e2053ffbe5e254c7fe941b14e130ed626038f54a0aa` |
| hot-templates-skill | `eval/runner.py` | `a2e41bcefc9a9cb897929af0f9e14e4990f9f3cfe657daa4868aa789da923860` |
| hot-templates-skill | `eval/golden.json` | `19e4b6e11bee018ed8c0842a3a39a651a98c97f2fead0c8e16ee2ed6ddeff186` |

---

## 附录 A：本轮核验记录（2026-09-30 实跑，全部于本机执行）

**A1 确定性评测复跑（12 项，全部 exit 0）**：

```text
python assets/meeting-minutes/eval/runner.py assets/meeting-minutes/package/out assets/meeting-minutes/oracle/out
  → exit 0，20/20 检查过
python assets/monthly-report-ppt/eval/runner.py assets/monthly-report-ppt/package/out assets/monthly-report-ppt/oracle/out
  → exit 0，16/16（盘内存量产物；不推翻下发 evalPassed=false）
python assets/ppt-method-router/eval/runner.py assets/ppt-method-router/package/out assets/ppt-method-router/oracle/out
  → exit 0，6/6，一致率 1.0（20/20，阈值 0.8）
python assets/paper-to-skill/eval/runner.py assets/paper-to-skill/package/out assets/paper-to-skill/oracle/out
  → exit 0，3/3
# 以下于各资产目录内执行（runner 相对参数 CWD 敏感）
v3/assets/office-templates：  python eval/runner.py package/out oracle/out → exit 0，68/68
v3/assets/prompt-regression： python eval/runner.py oracle oracle → exit 0，4/4（ALL GREEN）
                              python eval/runner.py package oracle → exit 0，4/4（ALL GREEN）
v3/tools/healthcheck：        python eval/runner.py → exit 0，5/5（oracle 对拍 15/15=100%）
v4/assets/hot-templates（在 skillfactory 根）：python v4/assets/hot-templates/eval/runner.py <package/out> <oracle/out>
  → exit 0，40/40，一致率 min 1.0
v4/tools/content-evaluator：  python eval/runner.py → exit 0，6/6
v4/assets/mcp-office-pack：   python eval/runner.py package oracle → exit 0，5/5
v4/assets/office-eval-suite： python eval/runner.py package oracle → exit 0，4/4（ALL GREEN）
```

**A2 盲评数字实读对账**（python 逐份读 `ab_summary.json`）：

```text
v2/evalbench-v02/lark-cli/ab_summary.json          → tasks=8, 7.9375→9.625, delta=1.6875, winRate=0.75, reverse=0, accepted=true（含 correction）
v2/evalbench-v02/meeting-minutes/ab_summary.json   → tasks=8, 4.75→10,    delta=5.25,   winRate=1.0,  reverse=0, accepted=true（含 correction）
v2/evalbench-v02/hooks-mastery/ab_summary.json     → tasks=5, 9.1→9.8,    delta=0.70,   winRate=0.6,  reverse=0, accepted=false（含 correction）
v3/assets/office-templates/tests/ab_summary.json   → tasks=5, 7.7→8.9,    delta=1.2,    winRate=1,    reverse=0, accepted=true
v4/assets/hot-templates/tests/ab_summary.json      → tasks=5, 3.9→10,     delta=6.1,    winRate=1,    reverse=0, accepted=true
```

**A3 体检复跑**（`python v3/tools/healthcheck/package/healthcheck.py --target dist/<包> --out <临时目录>`，输出存 `D:/workspace/zcode研究/_tmp_registry_hc/`，未写入包内）：

```text
meeting-minutes-skill → rating A（5/5），generated_at 2026-09-30T15:48:29+0800
office-templates-skill → rating A（5/5），15:48:31
hot-templates-skill    → rating A（5/5），15:48:32
盘内佐证：v3/healthchecks/{mm-dist, meeting-minutes-skill-recheck, ot-dist, office-templates-skill-recheck, ht-dist}/report.json 均 A（5/5）；
         v3/healthchecks/guard-hooks 与 prompt-reg 均 C（2/5）
```

**A4 分发包含证（本轮实查）**：`find dist -name ".mimosa"` → 零命中；三包 `requirements.txt` 在位（mm 为 `python-docx>=1.1.0`）；`git -C dist/<包> log --oneline` 各 1 commit、`status --porcelain` 干净；front-matter 三包均 name/version/license:MIT/description/permissions 齐。

**A5 本轮未做（如实声明）**：未重跑任何双臂盲评（Δ/胜率为盘内 ab_summary.json 数字，本轮实读对账）；未在 dist 包内做被测-参照全量对拍（避免向包内写入 `out/`，以源资产 runner 复跑 + 包内体检绿自检替代）；未重跑 mcp-office-pack 真实协议握手（引三份落盘 samples.json）；未核验第三方仓（lark-cli/hooks-mastery）远端现况（引盘内 ASSET-DOC 2026-09-29 抓取记录）。

---

## 发布就绪汇总

| 包 | commit 短哈希 | commit 时间 | 体检评级 | 关键 sha256（SKILL.md） | 盲评 |
|---|---|---|---|---|---|
| `dist/meeting-minutes-skill` v1.0.0 | **`29bd123`**（29bd123981797a7ce2ddbef14a4406f4a9c823d2） | 2026-09-30 10:00:11 +0800 | **A**（5/5，本轮复跑复核） | `181c8daa…c56827` | v0.2 Δ+5.25 / 100% / 反向 0，accepted |
| `dist/office-templates-skill` v1.0.0 | **`1e4ada5`**（1e4ada539520e3653a7eb4095a15f978230d35d5） | 2026-09-30 10:00:31 +0800 | **A**（5/5，本轮复跑复核） | `a008db16…bd084b` | v0.2 Δ+1.20 / 100% / 反向 0，accepted（单轮信号） |
| `dist/hot-templates-skill` v1.0.0 | **`52187cf`**（52187cfa156fc343be2c1722a3d6a21dc797dae3） | 2026-09-30 15:42:21 +0800 | **A**（5/5，本轮复跑复核） | `6ba95aee…5ab69d` | v0.2 Δ+6.10 / 100% / 反向 0，accepted |

**三包均为评测门口径就绪（确定性门 + 盲评门 + 体检 A），待雇主批准后发布。**

对外必须随附的披露口径（引自盘内报告，未在本轮重测）：
1. 全批 `synthetic-passed ✓ / real-verified ✗`（真实复验门未做）；效率门（token/耗时）未测。
2. office-templates 一切对外文案标注 `single_round_signal`（第二轮盲评未做）。
3. meeting-minutes Δ+5.25 来自 2026-09-30 majority 判定反演修正后的重算（均值与 Δ 未受修正影响）。
4. hot-templates 按 SPEC §4 五门口径欠账未清（每臂 2<3 重复、benchmark.json 未落盘），V7 报告原要求复检通过前不上架——是否随本批放行，随三包一并待雇主裁决。
5. 发布打包最后一道工序：再次清点删除包内 `.mimosa/`（本轮实查三包为 0，动作本身须进发布 checklist）。

---

## 2026-10-01 夜班轮追加登记：v5 代三候选（评估与准入 · worker-B）

> 登记人：worker-B（CloudCrane 夜班 loop 自迭代批）；评估执行机 anolis-gpu-01（Python 3.12.13 + PyYAML 6.0.3）。
> 评估记录（跑分落盘，退出码为证）：`v5/eval-round-20261001/`＝scorecard.md + results.tsv（41 门逐项退出码）+ 45 份 stdout/stderr 原始输出 + keyfiles.sha256（19 个关键文件）+ healthcheck/ 三份 report.json。
> 口径：各候选自带 spec.md/contract.md 冻结红绿矩阵（未放宽任何阈值）；worker-A 本轮未落盘独立口径文档（考古如实记录），故按盘内冻结契约执行。全程离线，**零模型调用**。
> 本节为追加登记，不改上方任何既有行。

| 名称 | 目录 | 形态 | 状态 | 确定性评测（2026-10-01 本轮实跑） | 盲评 | 体检级 | 许可 | 一句话用途 |
|---|---|---|---|---|---|---|---|---|
| hotwords（热词表管理器） | `v5/assets/hotwords`（spec/contract/eval/oracle/package） | skill+CLI 工具 | **内部就绪**（工具/基建件） | 全过：oracle `run_all.py` 10 步 exit 0（基线重跑前后 diff 仅 cmd.txt 解释器路径形态 40 行，A.7 归一化吸收）；eval 4/4 exit 0＝绿自评 + package vs oracle **54 文件一致率 100%**（Windows 纪基线与新基线双跑均绿）；红（空目录）exit 1 拦截；用法错 exit 2；runner 双跑 stdout 逐字节一致 | 不适用（工具类） | **C**（2/5；3 失分项属形态错配，见注 1） | 未声明（SKILL.md 仅 name+description） | ASR 热词库增删查导出（funasr/plain），10 步真实 CLI 序列快照自证 |
| deploy-pack（三服务部署包生成器） | `v5/assets/deploy-pack` | tooling（生成器+校验器） | **内部就绪**（工具/基建件） | **12/12 全过**：oracle fixtures **7/7**（verdict=ALL FIXTURES AS EXPECTED，含 4 red 包各被恰一 C 项击穿）；eval 绿自评与 pack-canonical direct 均 exit 0（4/4，rate 1.0）；6 红矩阵（空目录/bad-yaml/missing-service/env-drift/hardcoded-secret/subset）全 exit 1 拦截；用法错 exit 2；runner 双跑逐字节一致 | 不适用（工具类） | **C**（2/5；同注 1） | 未声明（SKILL.md 仅 name+description） | 一条命令生成 asr/minutes/todo 三服务 docker-compose 部署包 + C1-C7 机器判验（密钥占位红线内嵌 C4） |
| speaker-mapping（说话人标签映射） | `v5/assets/speaker-mapping` | skill+CLI 工具 | **待迭代**（确定性门 3/4） | 4 项检查 3/4 过（9 映射产物逐字节/WARNING 集/discover 统计全过）；检查 4 红：12 主产物 9/12 一致，3 个 discover JSON 仅 transcript 路径形态不符（盘内 Windows 纪基线冻结 `fixtures\…` vs 本机重生成 `fixtures/…`）；对照证据：oracle 工具本机独立重生成 9 txt vs 基线 **9/9 逐字节一致**（真回归排除）；红空目录 exit 1、用法 exit 2 过 | 不适用（工具类） | **C**（2/5；同注 1） | 未声明（SKILL.md 仅 name+description） | diarization 转写稿 SPEAKER_XX→人名替换 / discover 说话人扫描（纯标准库确定性） |

> 注 1（体检形态备注，如实登记不推翻 C）：v3/tools/healthcheck 5 项按 dist skill 包形态设计；v5 三件为工具类，eval 在**资产级**（`assets/<a>/eval/runner.py`，本轮全实跑）而非 package/eval/，脚本在包根而非 scripts/，SKILL.md 仅 name+description。2 PASS=skill_md_exists+eval_smoke(skip)。同先例：B 表 mcp-office-pack「配置包形态，体检器 5 项不适用」。形态豁免与整改（补 front-matter 三字段）留待后续轮/owner 裁定。
> 注 2：三件均**不进 dist/**——可分发门=确定性+盲评+体检(A) 三者齐，且发布动作待雇主批准（红线）。
> 注 3：speaker-mapping 唯一红项修复路径＝contract §6 基线升版流程（Linux 重跑 12 命令重建 `oracle/out` + 同步 spec 附录 A.3 + 升版本号），属生成侧（worker-A）动作，本轮未代办。
> 注 4：本轮 worker-B 未重跑双臂盲评（Δ/胜率），未做被测-参照全量对拍以外的新增评测面；v0.2 及更早各行数字与本轮无涉。

### 更正（2026-10-01 R2，worker-B 终门复跑留档后；只追加，不改上方任何既有行）

> 证据：`v5/report/EVAL-RUN-20261001.md` + `v5/report/eval-records/`（8 门 JSON/gates.tsv/keyfiles.sha256 R2 刷新版）。R1 节（L153 起）两行更正如下，其余行（含 hotwords）复跑无变化。

| 名称 | 更正内容 |
|---|---|
| deploy-pack | 确定性评测更正：**package vs oracle 终门 4/4、rate 1.0**（复跑 exit 0；修复前 2/4、rate 0.6；R1 行内「dp05 绿 direct」实为 oracle 自评 self_eval=true，经 **2015999 模板对齐迭代修复**；本轮 deploy-pack.gate.json 为 self_eval=false 的 package 终门实证）。状态维持**内部就绪（工具/基建件）**，体检 C 形态备注不变。 |
| speaker-mapping | 状态更正：待迭代 → **内部就绪（12/12）**——复跑 gate/self 均 exit 0（4 项检查全过；contract v1.1 增补条款 A-2 平台路径归一，仅及 discover JSON transcript 字段，9 txt 仍逐字节）；空目录红路 exit 1 保持 fail-closed。体检 C 形态备注不变。 |


---

## 2026-10-02 夜班追加登记（zcode-nightshift；只追加，不改上方任何既有行）

> 证据：本夜三门实测（绿 exit 0 / 红空目录 exit 1 / 用法 exit 2）+ 4 评委双臂盲评（标签互换）+ classroom/rehearsal/round-1/record.md。全部离线零模型调用的确定性门均由脚本逐门复跑。

### 新资产扩线（两类形态首批）

| 名称 | 目录 | 形态 | 状态 | 确定性评测（2026-10-02 复跑） | 盲评（n=2 标签互换） | 体检级 | 许可 | 一句话用途 |
|---|---|---|---|---|---|---|---|---|
| zctl-mcp | `v5/assets/zctl-mcp` | MCP server 包 | **内部就绪**（工具/基建件） | 自评 7/7 检查 exit 0（serverInfo/工具集恰等/逐工具契约/变更类零暴露）；红空目录 exit 1；用法 exit 2 | **2/2 胜**（评委理由：只读守卫+变更类不暴露论证完整；裸臂 confirm 参数守卫被两评委一致判形同虚设） | 未体检（待 owner 裁定形态豁免） | 未声明 | zctl（闲时任务/额度重置 CLI）→ 只读 MCP server（4 工具，变更类不暴露） |
| acceptor-agent | `v5/assets/acceptor-agent` | agent 角色包 | **内部就绪**（基建件） | 自评 4/4 检查 exit 0（三节齐备/字段恰等/example 合法/零承诺措辞）；红空目录 exit 1；用法 exit 2 | **2/2 胜**（评委理由：JSON 输出契约+禁令直接命中不虚报/不越界；裸臂泛化描述被判易虚报） | 未体检（同上） | 未声明 | 验收员子代理角色包（verdict JSON 契约：verified/judged 分级 + 承诺边界） |

> 注 A1：两件为「skill 之外资产形态」（MCP / agent 定义）产线扩展首批，验证了「生成→确定性评测→双臂盲评→准入」产线对非 skill 形态的适配性；体检工具（v3 healthcheck）按 dist skill 包形态设计，对两形态不适用，豁免与整改待 owner 裁定（同 REGISTRY 注 1 先例）。
> 注 A2：盲评为小样本 n=2（标签互换，两臂各胜一次=无标签偏置），加厚（每臂≥3）欠账待模型配额。

### 课堂层（K 线）

| 事项 | 状态 | 证据 |
|---|---|---|
| K-1 走查脚本 / K-2 学员手册 / K-4 教学资产清单 | ✅ 成文（教学路径=v5 三资产：HW L162 / DP L163 / SM L164） | `classroom/{walkthrough,handbook,teaching-assets}.md`，tag `classroom-v0.1`（commit 0079419） |
| K-3 彩排 round-1 | ✅ 通过（零上下文走通三课，3 交付物评测 4/4，6 门基线复现；缺陷 D1-D5 已回写文档） | `classroom/rehearsal/round-1/record.md` |
| K-5 dist 发布 | ⛔ 受阻：`dist/` 三包不在 monorepo 快照内，CRLF 修复与包内自检无实物；**未代签未发布** | `evidence/publish-approval-REQUEST.md`（commit 34785e8） |

### P-2 队列项复核（不重复造轮子，复跑既有资产确定性门）

| 队列项 | 既有资产 | 2026-10-02 复跑 |
|---|---|---|
| 中文办公模板包 | v3/assets/office-templates | 自评 exit 0 ✅ |
| 办公护栏 hook | v3/assets/office-guard-hooks | 自评 exit 0 ✅ |
| 体检流水线 | v3/tools/healthcheck | 自评 exit 0 ✅ |
| prompt 回归集 | v3/assets/prompt-regression | candidate=oracle/out 双参 exit 0；红路 exit 1 ✅ |

### 欠账（如实，2026-10-02 夜班新增/沿袭）

- FunASR 彩排缺音频环境（沿袭）；hot-templates 盲评加厚缺模型配额（沿袭）；
- zctl-mcp / acceptor-agent 盲评加厚与体检裁定待补（新增）；dist 三包实物补迁或换候选待 owner 裁定（新增，K-5）；
- zctl-mcp 对 zcode.z.ai 真实端到端调用待真机（上游 zctl 同款欠账）。
