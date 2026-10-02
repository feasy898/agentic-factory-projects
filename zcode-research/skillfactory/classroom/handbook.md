# 学员手册（K-2）——「裸 agent vs 带资产 agent」交付确定性三步课

> 三课用同一组三个 v5 入册资产：speaker-mapping（SM）、deploy-pack（DP）、hotwords（HW）。REGISTRY 行号 L162（HW）/ L163（DP）/ L164（SM）；本手册与之同步冻结于 2026-10-02 夜班。
>
> 承诺边界：本课只承诺「学员能走完三步交付 → 拿到三份真实产物」。不承诺任何就业、收入、效果、外加平台应用结果。**学员在课中出现卡点、卡死，先点落地**。

---

## 二、目标交付物

三份对应资产的学员最终产物（每节下课前必须存在）：

| 课 | 资产 | 学员交付物路径（仓库内相对） | 通过判据 |
|---|---|---|---|
| 第 1 课 | speaker-mapping | `zcode-research/skillfactory/v5/assets/speaker-mapping/out/student_run1/`（含 9 个 JSON/stderr 文件） | eval/runner.py 输出 12/12 pass、exit 0 |
| 第 2 课 | deploy-pack | `zcode-research/skillfactory/v5/assets/deploy-pack/out/student_pack1/`（含 docker-compose.yml + .env.example + DEPLOY.md） | eval/runner.py 输出 4/4 pass、exit 0 |
| 第 3 课 | hotwords | `zcode-research/skillfactory/v5/assets/hotwords/out/student_words.txt` | eval/runner.py 输出 4/4 pass、exit 0 |

**三件齐 = 课堂合格**。

---

## 三、前置环境（任一不合格不开课）

| 项 | 要求 | 自检命令 | 通过判据 |
|---|---|---|---|
| 操作系统 | Windows 10+ 或 macOS 或 Linux | `ver` / `sw_vers` / `lsb_release -a` | 输出版本号 |
| Python | 3.12.x，路径含 `Python312\python.exe`（不能是 LibreOffice 自带） | `python --version` 与 `where python` | 版本 3.12.x，首条命中 |
| Git | 任意版本 | `git --version` | 输出版本 |
| ZCode | 已安装 | `zcode --version` | 输出 CLI 版本号 |
| 工作区克隆 | `D:\new-workspace\agent-asset\agentic-factory-projects` 存在，main 在 0ab1c25 | `git -C "<路径>" log --oneline -1` | 输出含 `0ab1c25 docs: 接手文档` |

任一未过 → 去 `devsetup/README.txt` 与 `agent-knowledge/02-network-and-shell-pitfalls.md` 修好再回来，**不要带病上课**。

---

## 四、逐步指引（点 walkthrough.md）

读 [`walkthrough.md`](./walkthrough.md) 三课共 12 步。每步 = 操作 + 验证命令 + 预期输出特征。三课顺序：SM → DP → HW。

**课堂纪律**：

1. 每步在终端执行后，把「退出码 + 首行输出」写在课堂记录 `classroom/rehearsal/round-1/record.md` 里（PASS/FAIL + 实际摘要）；
2. 输出红路不是 ❌ 1 而是 ❌ 0：停课修评测器（不过你答应过复盘）；
3. 跨资产打包走出错：先看 `eval/runner.py` 输出 JSON 里的 `checks[*].detail`，是 oracle 哪条规则不达；
4. 不要绕路**：**手工拍 ∙ oracle 并不等于走通了；随机 walkthrough 则不算交付。

---

## 五、常见卡点与自检

### 5.1 红路 exit 0（评测器被破坏）

**症状**：5.2 步**不评估绿路**评**绿路**走**绿路**绿路**，绿路exit 0；走`eval/runner.py _red_empty oracle/out`得到 exit 0。

**原因**：能是 接受了 一个变动了 runner 的同学（赔罪钱包）改过 oracle 期望。

**自检**：
- `git status` 不应该再出 `v5/assets/<NAME>/eval/runner.py` 被改动；
- 如果有，跳变 commit 把 runner 还原为讲义记录的版本；记录在 record.md 里。

### 5.2 错走 `eval/runner.py <args>` 参数顺序错

**症状**：runner JSON 里 `reference_resolved: null` 或 `candidate_resolved: null`。

**原因**：参顺序弄成 `<oracle> <candidate>` 而不是 `<candidate> <oracle>`。

**自检**：看 walkthrough.md 第 1.3、2.2、3.2 步里的**第一个参数**是「产物」、**第二个**是「oracle」（`oracle/out`）。

### 5.3 oracle 产物缺失

**症状**：跑 `python eval/runner.py oracle/out oracle/out` 出 `"reference_resolved_via": "none"`。

**原因**：`oracle/out/` 被人清了，者仓库克隆不完整。

**自检**：`ls <repo>/v5/assets/<NAME>/oracle/out` 必须看到 pack-canonical/类子目录。仓库克隆不完整这一点，`git log -1` HEAD 是不是 0ab1c25。不是则重新克隆。

### 5.4 Python 不是 3.12

**症状**：启动就跑出 `SyntaxError`/`ImportError` 而本资产依赖 PyYAML 6.x。

**自检**：看 `where python` 第一条是不是 `C:\Program Files\Python312\python.exe`。不是，则看 `D:\agent-knowledge\01-windows-machine.md`。

---

## 六、不含人工兜底的承诺

学员从环境自检到拿到三份交付物都能由本手册 + walkthrough.md 完成。**不在场任何任何需要「手工跑某个含密钥的命令」「手动联系某某」的步骤**。如发现，按「记录卡点」提出，记入 `record.md`「blockers」节，本节课不合格。

---

## 七、课后交接

学员按以下三步交付：

1. 把 `classroom/rehearsal/round-1/record.md`（含每步 PASS/FAIL 与首行输出摘要）抄给 owner 看；
2. 在 `zcode-research/worklog.md` 追加一行：「2026-10-0X 第 N 次开课：N 学员三课走通，3 资产基线 6 门绿，3 份交付物就位」——按实情填，未达就不算「合格」、「不达标」就如实写「未达标+原因」；
3. 把三份交付物路径（`v5/assets/<SM|DP|HW>/out/student_*`）发给 owner，供下一轮课堂复演。

未交付以上三项 = 本次课堂不算走通，本纪要不计入课堂。