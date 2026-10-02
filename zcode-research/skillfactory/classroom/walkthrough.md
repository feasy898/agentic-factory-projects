# 课程走查脚本（K-1）——「裸 agent vs 带资产 agent」交付确定性三步课

> 资产版本冻结于 v5（REGISTRY.md 2026-10-01 复跑）。三节课共用三个 v5 入册资产：speaker-mapping（SM，说话人标签映射）、deploy-pack（DP，三服务部署包）、hotwords（HW，热词表管理器）。REGISTRY 行号：SM→**L164**、DP→**L163**、HW→**L162**（2026-10-01 夜班轮追加登记节；均为内部就绪工具类资产，红路 fail-closed 已验证）。

---

## 第 0 步：环境自检（必须全绿才进第 1 节）

操作：用 PowerShell/cmd 跑以下三条命令，每条退出码预期 0。

```
python --version
where python
git -C "D:\new-workspace\agent-asset\agentic-factory-projects" log --oneline -1
```

预期输出特征：
- Python 3.12.x
- 路径含 `Python312\python.exe`（非 LibreOffice 自带那个）
- 提交含 `0ab1c25 docs: 接手文档...`

判断：任一非 0 退出码 → 停步，去 Python 安装页修环境，**不进第 1 步**。

---

## 第 1 课：SM 资产——一句话复刻「会议转写说话人映射」（学员目标交付物：3 份映射 JSON 文件）

操作指引指向的资产行号：REGISTRY.md **L164**（speaker-mapping，内部就绪 12/12）。本课用源资产 `v5/assets/speaker-mapping/`。

### 步骤 1.1：进入资产目录

cd "D:\new-workspace\agent-asset\agentic-factory-projects\zcode-research\skillfactory\v5\assets\speaker-mapping"
```

操作（带资产）：

```
python eval/runner.py oracle/out oracle/out
```

预期输出特征：JSON 输出末尾 `summary.checks.passed == total`（12/12），退出码 0。

验证命令（不带资产·裸跑）：

```
python eval/runner.py _red_empty oracle/out
```

预期：JSON 输出 `summary.checks.passed == 0`，**退出码 1**（红路 fail-closed）。红路退出码为 0 即评测器被破坏，**立即停步上报**。

### 步骤 1.2：用 oracle 参照实现产出一份映射产物（学员目标交付物）

操作：

```
python oracle/map_speakers.py --transcript oracle/fixtures/normal.txt --mapping oracle/fixtures/m_full.json --out out/student_run1
```

预期：stdout 含「已统计学生名」「草稿映射」之类日语，退出码 0，`out/student_run1/` 下产生 JSON。

复现评测：

```
python eval/runner.py out/student_run1 oracle/out
```

预期：12/12 checks pass，退出码 0。

### 步骤 1.3：交付物检查

操作（**在 oracle 目录为 cwd**、用相对路径逐条复刻 oracle 产出 3 transcripts × 3 mappings 共 9 个映射产物 + 3 次 discover + 12 个 stderr sidecar）：

```bash
cd "D:\new-workspace\agent-asset\agentic-factory-projects\zcode-research\skillfactory\v5\assets\speaker-mapping"
mkdir -p out/student_run1
cd oracle
for t in normal partial empty; do for m in m_full m_partial m_empty; do
  python map_speakers.py --transcript "fixtures/$t.txt" --mapping "fixtures/$m.json" \
    --out "../out/student_run1/${t}__${m}.txt" 2> "../out/student_run1/${t}__${m}.stderr.txt"
done; done
for t in normal partial empty; do
  python map_speakers.py --discover --transcript "fixtures/$t.txt" \
    --out "../out/student_run1/discover__${t}.json" 2> "../out/student_run1/discover__${t}.stderr.txt"
done
cd ..
ls out/student_run1
```

预期：24 个文件产出（9 个 .txt + 9 个 .stderr.txt + 3 个 .json + 3 个 .stderr.txt），每条命令退出码 0。

复现评测：

```
python eval/runner.py out/student_run1 oracle/out
```

预期：JSON 末 `summary.passed == 4`、exit 0。

学员最终交付物（路径必须存在才算本课合格）：

```
zcode-research/skillfactory/v5/assets/speaker-mapping/out/student_run1/
```

---

## 第 2 课：DP 资产——一句话生成「三服务部署包」（学员目标交付物：3 个部署文件）

### 步骤 2.1：进入资产目录

```
cd "D:\new-workspace\agent-asset\agentic-factory-projects\zcode-research\skillfactory\v5\assets\deploy-pack"
```

### 步骤 2.2：基线复跑

操作（带资产）：

```
python eval/runner.py oracle/out oracle/out
```

预期：JSON 末 `summary.checks.passed == 4`（4/4），退出码 0。

红路：

```
python eval/runner.py _red_empty oracle/out
```

预期：4/4 fail，**退出码 1**。红路非 1 = 停步。

### 步骤 2.3：产出一份三服务部署包（学员目标交付物）

```
python oracle/gen_deploy.py --services asr,minutes,todo --out out/student_pack1
python oracle/validate.py --pack out/student_pack1
```

预期：前者退出码 0 产 docker-compose.yml + .env.example + DEPLOY.md；后者 `verdict=ALL GREEN` + `7 pass / 0 fail`。

### 步骤 2.4：评测

```
python eval/runner.py out/student_pack1 oracle/out
```

预期：4/4 checks pass，退出码 0。

学员交付物：

```
zcode-research/skillfactory/v5/assets/deploy-pack/out/student_pack1/docker-compose.yml
zcode-research/skillfactory/v5/assets/deploy-pack/out/student_pack1/.env.example
zcode-research/skill_factory/v5/assets/deploy-pack/out/student_pack1/DEPLOY.md
```

---

## 第 3 课：HW 资产——一句话管理「单位热词表」（学员目标交付物：热词库 funasr 导出）

### 步骤 3.1：进入资产目录

```
cd "D:\new-workspace\agent-asset\agentic-factory-projects\zcode-research\skillfactory\v5\assets\hotwords"
```

### 步骤 3.2：基线复跑

绿路：

```
python eval/runner.py oracle/out oracle/out
```

预期：JSON `summary.checks.passed == 4`（脚本序列一致/重复 add 报错/funasr 格式/参照一致率 100%），退出码 0。

红路：

```
python eval/runner.py _red_empty oracle/out
```

预期：4/4 fail，**退出码 1**。

### 步骤 3.3：操作一遍热词库（学员目标交付物）

**红线**：`oracle/run_all.py` 会清空重建 `oracle/out`（评测参照区，只读）——**禁止在 oracle/ 原地运行**。学员把 oracle 复制一份到 scratch 再跑：

```
cp -r oracle out/oracle_student
python out/oracle_student/run_all.py
```

预期：退出码 0，`out/oracle_student/out/` 下出现 `manifest.json`（`all_pass: true`）与 10 个步骤快照目录。

再亲手操作一次热词 CLI（体会增删查导出；store 用 scratch，不碰参照区）：

```
python out/oracle_student/hotwords.py --store out/student_store.json add "校园环境专区" --category loc --note 学生课间 --weight 30
python out/oracle_student/hotwords.py --store out/student_store.json list
python out/oracle_student/hotwords.py --store out/student_store.json export --format funasr --out out/student_words.txt
```

预期：add 报「已添加」；list 显示词条分组；export 退出码 0 且文件每行 `词 权重`。

### 步骤 3.4：评测

```
python eval/runner.py out/oracle_student/out oracle/out
```

预期：4/4 checks pass，退出码 0。

学员交付物：

```
zcode-research/skillfactory/v5/assets/hotwords/out/oracle_student/out/   （manifest.json + 10 步快照）
zcode-research/skillfactory/v5/assets/hotwords/out/student_words.txt
```

---

## 课程合格线（三课任一未过 = 不合格）

1. 三资产基线绿路全 exit 0（SM 12/12 + DP 4/4 + HW 4/4）；
2. 三资产红路全 exit 1（红路 fail-closed 守住）；
3. 三份学员交付物路径真实存在且内容完整（按各课「最终交付物」节核对）；
4. 所有 git 状态保持干净（除课堂产物 out/ 与课堂 README/teaching 资产清单外）。

`classroom/rehearsal/round-1/record.md` 必须按本脚本逐步记录 PASS/FAIL，每步写实际输出首段（≤ 80 字）。