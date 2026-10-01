# spec.md — 三服务部署包生成资产（deploy-pack）规格

> 资产根：`skillfactory/v5/assets/deploy-pack/`
> 规格依据：oracle 参照软件 `oracle/gen_deploy.py`（254 行）、`oracle/validate.py`（294 行）、
> `oracle/run_fixtures.py`（136 行，均 wc -l 实测、本会话逐行读过）+ 实跑产物 `oracle/out/`
> （本会话读取核对）+ 本会话（2026-09-30）复跑与探针（§2.3，全部亲自实跑）。
> 本规格逐条可判定：每条规则都给出「判定方法」，`eval/runner.py` 据此机械化判分。
> 增补条款 A-1：eval 逐字节比对的常量全文列于附录 A（本 eval **无内嵌逐字节期望常量**，
> 以「冻结判定常量全文 + 委托声明」满足，见 §4/§5/附录 A.3）。

---

## 1. 目标

把「一条命令生成三服务（asr / minutes / todo）部署包 + 机器可判验收」的 oracle 行为固化为软件资产：

| 文件 | 角色 |
|---|---|
| `oracle/gen_deploy.py` | 参照生成器（CLI，行为在 §3 R1-R2 冻结） |
| `oracle/validate.py` | 参照校验器（C1-C7，§3 R3；**oracle 判绿的唯一口径**） |
| `oracle/run_fixtures.py` + `oracle/fixtures/` | 全量 fixtures 实跑入口与静态正/反例（§2.2） |
| `oracle/out/` | 实跑产物（评测的参照产物，只读；`out/pack-canonical/` = canonical 三服务包） |
| `spec.md` / `contract.md` | 规格（本文）与接口契约 |
| `eval/runner.py` | 确定性评测器：判「一份部署包」是否合格（§5） |

工具处理的对象是 **部署包三件套**（docker-compose.yml / .env.example / DEPLOY.md）；
eval 的对象是 **一份 pack 目录**（被测产物根按 contract.md §3 解析），与参照包做结构与文本比对。

## 2. oracle 实测基线（本规格的证据）

### 2.1 参照软件（本会话逐行读过；行号引用）

- `gen_deploy.py`：
  - 服务目录 CATALOG（:36-67）：**asr**（语音识别，宿主端口 8001，镜像占位 `placeholder/asr:dev`，
    业务 env：ASR_INPUT_DIR / ASR_OUTPUT_DIR / ASR_MODEL）、**minutes**（会议纪要，8002，
    `placeholder/minutes:dev`，MINUTES_INPUT_DIR / MINUTES_OUTPUT_DIR）、**todo**（待办清单，
    8003，`placeholder/todo:dev`，TODO_DATA_DIR）。容器内统一监听 8000、健康路径 `/healthz`
    （:32-33），healthcheck 为 `curl -fsS http://127.0.0.1:8000/healthz`（:110-111）。
  - 变量引用统一 `${VAR:-default}`（ref() :75-77）；compose 引用变量共 **12** 个
    （每服务 IMAGE+PORT 由 :80-85 规则派生，加业务 env：5+4+3）。
  - WIRING 契约（:70）：`asr.ASR_OUTPUT_DIR == minutes.MINUTES_INPUT_DIR`（同指 `./data/asr-out`）。
  - PACK_FILES（:72）= docker-compose.yml / .env.example / DEPLOY.md；服务输出按 CATALOG
    **目录序**而非 --services 书写序（:231），保证确定性。
  - 退出码（docstring :17，实现 :223-245）：0=成功；2=参数非法（服务清单空/含未知服务，
    **不建输出目录**）；1=写出失败。
- `validate.py`：七项检查（:124-265）——
  C1 compose_safe_load（:124-143，`yaml.safe_load` + 顶层 services 映射）、
  C2 services_exact（:146-153，服务集与期望**恰等**，缺省期望 = CATALOG 三服务 :49,:103-104）、
  C3 env_consistent（:155-176，`.env.example` 变量集与 compose `${}` 引用集双向一致 + 内联缺省值不漂移）、
  C4 no_hardcoded_secrets（:179-200，密钥名必须 `${}` 引用 + 凭据形态字面量扫描，模式表 :56-71）、
  C5 wiring_asr_minutes（:203-224，接线双侧同值且 compose 双侧接线；服务集不含 asr+minutes 时 SKIP）、
  C6 deploy_md_three_cmds（:227-236，DEPLOY.md 三命令要素）、
  C7 deterministic_regenerate（:239-265，以包内发现的服务集重跑 gen_deploy.py，三份产物**逐字节**比对；
  仅在 C1-C4 全 PASS 时执行，:239-241）。
  汇总与退出码（:268-290）：verdict = ALL GREEN / FAILED；**0=全过（SKIP 不计失败）、
  1=有 FAIL、2=参数非法**。
- `run_fixtures.py`：fixtures 矩阵与逐项预期写死于 docstring（:14-22）。

### 2.2 实跑产物（`oracle/out/`，本会话读取核对）

- `fixtures-run.json`：total 7 / passed 7 / verdict **"ALL FIXTURES AS EXPECTED"**。entries 全表实测：
  canonical（asr,minutes,todo）gen exit=0 + validate ALL GREEN；subset（asr,todo）同（C5 SKIP）；
  invalid（asr,wat）gen exit=2 且不建目录，stderr=`[GEN-FAIL] 非法 --services: 'asr,wat'（未知: wat）…`；
  四个 red 包 validate exit=1，FAIL 项分别**恰为** C1 / C2 / C3 / C4。
- `pack-canonical/`（三件套，本会话 `wc -l` 实测行数）：docker-compose.yml **57 行**、
  .env.example **35 行**、DEPLOY.md **47 行**；`pack-canonical-validate.json` verdict=ALL GREEN
  （7 pass / 0 fail / 0 skip）。
- `pack-subset/`（asr,todo 双服务包）与 `red/` 下四份 FAIL 报告。

### 2.3 本会话复现与探针（2026-09-30，全部亲自实跑）

1. **环境实测**：Python 3.12.10（`python --version`）、PyYAML 6.0.3（`import yaml`）。
2. **oracle 判绿第一手复核**：`python oracle/validate.py --pack oracle/out/pack-canonical --out <临时报告>`
   → exit 0，verdict=ALL GREEN，7 pass / 0 fail / 0 skip（含 C7 重生成逐字节一致——确定性第一手复核）。
3. **Docker 缺失实测**：`command -v docker docker-compose` 无结果 → 容器实跑不在验收范围
   （与 oracle README 口径一致：**验收 = validate.py 全过**）。
4. **eval 红绿矩阵**（`python skillfactory/v5/assets/deploy-pack/eval/runner.py <被测> oracle/out`，
   退出码实测；rate = 检查 4 文本一致率）：

   | 被测 | 退出码 | FAIL 项 | rate |
   |---|---|---|---|
   | `oracle/out`（自评，绿） | **0** | 无（4/4 过，self_eval=true，rate=1.0，278/278 行位） | 1.0 |
   | `oracle/out/pack-canonical`（direct 解析，绿） | **0** | 无 | 1.0 |
   | 空目录（红） | **1** | 4 项全败（被测根未解析，resolved_via=none） | — |
   | `fixtures/red-bad-yaml` | **1** | 检查 1（yaml 破损）+ 检查 2（依赖）+ 检查 3（oracle C1） | 0.9964 |
   | `fixtures/red-missing-service`（asr,minutes 双服务包） | **1** | 检查 1（缺 todo）+ 检查 3（oracle C2）+ 检查 4（<0.90） | 0.8538 |
   | `fixtures/red-env-drift`（.env 缺 TODO_PORT） | **1** | 检查 2（引用/定义集失衡）+ 检查 3（oracle C3） | 0.9964 |
   | `fixtures/red-hardcoded-secret`（compose 假密钥字面量） | **1** | 检查 3（oracle C4）——唯一防线，证明检查 3 不可省 | 0.9929 |
   | `oracle/out/pack-subset`（合法双服务包） | **1** | 检查 1（缺 minutes）+ 检查 3（oracle C2，缺省口径=三服务）+ 检查 4 | 0.8066 |

5. **确定性实测**：自评连跑两次，stdout `diff` 为空（逐字节一致）；无时间戳字段。
6. **用法错误实测**：零参数 / 单参数 → argparse exit 2。
7. **阈值判别力**（依据 4 的 rate 列）：整服务缺失把聚合一致率打到 0.85 以下（0.8066/0.8538），
   击穿 0.90；单行级残缺（缺 TODO_PORT 一行 / 加两行假密钥）仍在 0.99——由检查 2/3 负责击穿。
   四检查互补覆盖：yaml 破损→1，变量集失衡→2，语义/密钥/确定性→3，文本漂移→4。

## 3. oracle 行为规则（逐条可判定）

### R1 gen_deploy CLI（gen_deploy.py:214-250）
`python gen_deploy.py --services asr,minutes,todo --out <dir> [--project-name <名>]`
- `--services` 逗号分隔，可用值 = CATALOG 三服务；空清单或含未知服务 → stderr
  `[GEN-FAIL] 非法 --services: …` 且 **exit 2、不建目录**（:223-229）。
- 项目名缺省 = 服务名按目录序 `-` 连接（:232）。
- 判定：跑命令看退出码 / stderr / 产物（§2.2 fixtures-run.json 为实测基线）。

### R2 pack 三件套内容（gen_deploy.py:95-153,156-211）
- docker-compose.yml：顶层 `name: <项目>` + `services:` 逐服务块；每服务含
  image / restart / environment / volumes / ports / healthcheck；一切可调值走 `${VAR:-default}`。
- .env.example：分组中文注释 + 全部 12 变量逐一 `KEY=value`，全部占位值（12 变量清单见附录 A.2）。
- DEPLOY.md：三条命令（`cp .env.example .env` → `docker compose up -d` → `docker compose ps`
  + 逐服务 `curl /healthz`）+ 服务端口表 + 管线接线说明（含 asr+minutes 时）。
- 判定：eval 检查 1/2（结构 + 变量集）与检查 3（oracle C5/C6）。

### R3 validate 七项与判绿口径（validate.py:124-265,268-290）
C1-C7 语义见 §2.1。**oracle 判绿 = validate.py exit 0 且 verdict=="ALL GREEN" 且 summary.fail==0**；
校验时 `--services` 用其缺省（= CATALOG 目录序三服务），即「三服务齐全」的 canonical 口径。
- 判定：eval 检查 3 实跑 oracle validate.py（报告写临时目录，用后即删）。

### R4 确定性
同参数重复运行 gen_deploy.py 产物逐字节一致（validate C7 复核；服务输出按目录序 :231）。
eval 检查 4 以 **0.90 文本一致率**为门槛（ask 冻结；比字节级宽松，容纳行尾/个别行差异；
字节级门由检查 3 的 oracle C7 承担）。评测器自身确定性：无时间戳/无随机，同参数 stdout 逐字节
一致（§2.3 探针 5）。
- 判定：eval 检查 4 + 检查 3。

### R5 退出码（三个工具）
| 工具 | 0 | 1 | 2 |
|---|---|---|---|
| gen_deploy.py | 成功 | 写出失败 | 参数非法（不建目录） |
| validate.py | 全过（SKIP 不计失败） | 有 FAIL | 参数非法 |
| eval/runner.py | 四项全过 | 任一失败 | 用法错误（argparse） |

### R6 边界（记录，不判分）
- 占位镜像 `placeholder/*` 不可拉取；容器实跑不在验收范围（本机无 Docker，§2.3 探针 3）；
  `/healthz` 为占位约定，假设被部署服务实现该端点。
- eval 判「包产物」，不重跑被测生成器、不读 fixtures（期望固化为常量或委托 oracle）。
- `oracle/out/` 只读；评测过程只写系统临时目录。

## 4. 边界与非目标

- 不做真实镜像构建/推送、不做容器编排调优；镜像一律占位。
- 不验证 `docker compose up` 实跑；验收 = oracle validate.py 全绿 + eval 四项。
- eval **不内嵌任何「期望产物全文」常量**（区别于 speaker-mapping eval 的做法）：一致性判断一律
  被测 vs 参照活文件比对，或委托 oracle validate.py 活体重生成——故附录 A 列的是冻结判定常量
  而非期望文本（A-1 合规声明见 A.3）。

## 5. eval/runner.py 判分规则（写死在工具内；契约细节见 contract.md §2-§5）

- **CLI**：`python skillfactory/v5/assets/deploy-pack/eval/runner.py <被测产物根> <参照产物根>
  [--out <报告>]`；两位置参数必填，用法错误 exit 2（§2.3 探针 6）。
- **产物根解析**（contract.md §3）：direct → pack-canonical → parent-out；未解析 → 四项全 FAIL
  （空目录即此红路径）。
- **固定 4 项检查**（名称冻结，恒 4 项，全部通过 exit 0；任一失败 exit 1）：
  1. `compose_yaml_three_services` — compose 可 `yaml.safe_load` 且服务集**恰为**
     asr,minutes,todo（缺或多均败）。
  2. `env_compose_vars_consistent` — `.env.example` 变量集 == compose `${}` 引用集（双向；
     内联缺省值漂移由 oracle C3 把关）。
  3. `validate_all_green` — 以参照侧定位的 oracle validate.py 实跑被测包（缺省服务集），
     exit 0 且 ALL GREEN 且 fail=0。
  4. `reference_text_agreement_90pct` — 与参照 pack 三文件**文本一致率 ≥ 0.90**（行级
     difflib、CRLF→LF 归一、BOM 容忍、行位加权聚合 rate = Σ2·matched / Σ(len_ref+len_cand)；
     被测缺文件记 0 匹配；参照侧不完整 → 本项直接 FAIL）。
- **输出**：stdout 打印单一 JSON `{"ok", "summary": {checks:{total,passed,failed},
  text_agreement_rate}, "checks":[{name,passed,detail,…审计字段}]}`；无时间戳，
  同参数逐字节一致。
- **退出码**：0 = 全过；1 = 任一检查失败（含空目录/未解析）；2 = 用法错误。

---

## 附录 A：冻结常量全文（增补条款 A-1）

### A.1 判定常量（与 eval/runner.py 头部一致；修改须先改 spec.md/contract.md 并升版本）

```python
EXPECTED_SERVICES = ("asr", "minutes", "todo")   # canonical 三服务（= gen_deploy.py CATALOG 键序）
PACK_FILES = ("docker-compose.yml", ".env.example", "DEPLOY.md")  # = gen_deploy.py:72 PACK_FILES
TEXT_AGREEMENT_MIN = 0.90                        # 检查 4 阈值（ask 冻结：≥90%）
VALIDATE_TIMEOUT_S = 120                         # 检查 3 子进程上限（秒）
REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")  # = validate.py:52 REF_RE
```

### A.2 12 个 compose 引用变量（检查 2 绿路径的期望集合；来源 gen_deploy.py CATALOG :36-67 + :80-85 派生规则；绿路径实测「compose引用 12 个/.env 定义 12 个」）

```
ASR_IMAGE, ASR_PORT, ASR_INPUT_DIR, ASR_OUTPUT_DIR, ASR_MODEL,
MINUTES_IMAGE, MINUTES_PORT, MINUTES_INPUT_DIR, MINUTES_OUTPUT_DIR,
TODO_IMAGE, TODO_PORT, TODO_DATA_DIR
```

### A.3 A-1 合规声明

本 eval **不内嵌任何逐字节期望产物**（无期望文本常量）：检查 1-2 为结构/集合判定；
检查 3 委托 oracle validate.py——其 C7 的逐字节比对对象是 gen_deploy.py **活体重生成**产物
（比对基准即 gen_deploy.py:36-153 的模板代码本身，非 eval 内常量）；检查 4 比对被测 vs 参照
两份活文件。故「eval 逐字节比对的常量」为空集；以上 A.1/A.2 为全部冻结判定常量。

### A.4 行为常量（解析序与退出码）

- 产物根解析序（取首个命中，resolved_via 留痕）：
  `<root>/docker-compose.yml`（direct）→ `<root>/pack-canonical/`（pack-canonical）→
  `<root>/out/pack-canonical/`（parent-out）→ 未解析（四项全 FAIL）。
- oracle 定位：参照 pack 目录祖先链（须同时含 validate.py 与 gen_deploy.py）→
  回退 runner 同级 `../oracle` → 均无则检查 3 FAIL。
- 退出码：0 = 全过；1 = 任一失败；2 = 用法错误。
