# contract.md — deploy-pack 资产接口契约

> 版本 v1.0（2026-09-30）。本文是 spec.md 的机械化配套：把「评测器怎么调、产物根长什么样、
> 四项检查怎么判、输出长什么样」冻结成契约。规则依据与证据行号见 spec.md（逐条可判定）。

## 1. 资产组成与评测对象

| 路径 | 角色 |
|---|---|
| `oracle/gen_deploy.py` | 参照生成器：`--services asr,minutes,todo --out <dir>` → 三件套 |
| `oracle/validate.py` | 参照校验器（C1-C7），**oracle 判绿的唯一口径** |
| `oracle/run_fixtures.py` + `oracle/fixtures/` | oracle 全量 fixtures 实跑入口（7/7）与静态正/反例 |
| `oracle/out/` | 参照产物（评测参照侧，只读；`pack-canonical/` = canonical 三服务包） |
| `spec.md` / `contract.md` | 规格 / 本契约 |
| `eval/runner.py` | 确定性评测器（本文 §2-§5） |

评测对象：**一份三服务部署包**（docker-compose.yml + .env.example + DEPLOY.md），而非生成器
脚本本身。被测包可由任何实现产出（oracle gen_deploy 或被测复刻实现），eval 只看包产物。

## 2. 评测器 CLI

```
python skillfactory/v5/assets/deploy-pack/eval/runner.py <被测产物根> <参照产物根> [--out <报告路径>]
```

- 两位置参数必填；缺参/多参由 argparse 拒绝 → **退出码 2**（用法错误）。
- `--out` 给出时把与 stdout 同一份 JSON 落盘（UTF-8 / LF）。
- 退出码：**0** = 四项全过；**1** = 任一项失败（含被测根未解析）；**2** = 用法错误。

## 3. 产物根布局与解析（被测/参照同构）

pack 目录 = 含 `docker-compose.yml` 的部署包目录（三件套完整性与否由检查项判定）。
产物根解析顺序（取第一个命中，`resolved_via` 留痕）：

1. `direct`：`<root>/docker-compose.yml` 存在 → root 即 pack 目录
2. `pack-canonical`：`<root>/pack-canonical/docker-compose.yml` 存在
3. `parent-out`：`<root>/out/pack-canonical/docker-compose.yml` 存在
4. 都不命中 → 未解析：四项检查全部判 FAIL 并注明已尝试路径（**空目录即此红路径**）

oracle 定位（供检查 3）：从参照 pack 目录沿祖先链找同时含 `validate.py` 与 `gen_deploy.py`
的目录；找不到回退 runner 同级 `../oracle`；再找不到 → 检查 3 判 FAIL。

## 4. 四项检查判据（名称冻结，恒 4 项）

| # | 名称 | 判据 | spec 依据 |
|---|---|---|---|
| 1 | `compose_yaml_three_services` | pack 的 docker-compose.yml 经 `yaml.safe_load` 成 dict 且含 services 映射，服务集**恰为** {asr, minutes, todo}（缺或多均败） | spec §3 R2/R3 |
| 2 | `env_compose_vars_consistent` | `.env.example` 的 KEY=VALUE 变量集（忽略空行/# 注释）== compose 全部字符串标量中 `${VAR}` / `${VAR:-d}` 引用集（双向；缺/多均败）。内联缺省值漂移不在本项（oracle C3 把关） | spec §3 R2 |
| 3 | `validate_all_green` | 以参照侧定位的 oracle `validate.py --pack <被测pack> --out <临时报告>` 实跑（validate.py 用其**缺省服务集** = canonical 三服务）：退出码 0 且报告 `verdict=="ALL GREEN"` 且 `summary.fail==0`。临时目录用后即删；子进程上限 120s | spec §3 R3 |
| 4 | `reference_text_agreement_90pct` | 被测 pack 与参照 pack 三文件**文本一致率 ≥ 0.90**：两侧 UTF-8（容忍 BOM）解码、CRLF→LF 归一、按行 splitlines；`rate = Σ2·matched_i / Σ(len_ref_i+len_cand_i)`（行级 difflib.SequenceMatcher，autojunk=False，matched=匹配行数）。被测缺文件记 0 匹配；参照侧任一文件缺失/不可读 → 本项直接 FAIL（参照不完整） | spec §3 R4 |

四检查互补（spec §2.3 探针 7 实测）：yaml 破损→检查 1；变量集失衡→检查 2；语义/密钥/确定性→
检查 3；文本漂移→检查 4。`red-hardcoded-secret` 仅检查 3 可击穿——检查 3 不可省。

## 5. 输出 JSON schema

stdout 打印**单一 JSON 文档**（UTF-8，无时间戳，同参数重复运行逐字节一致）：

```json
{
  "tool": "runner.py",
  "asset": "skillfactory/v5/assets/deploy-pack/eval",
  "candidate": "<原始参数>", "reference": "<原始参数>",
  "candidate_resolved": "<绝对路径或 null>", "candidate_resolved_via": "direct|pack-canonical|parent-out|none",
  "reference_resolved": "<绝对路径或 null>", "reference_resolved_via": "direct|pack-canonical|parent-out|none",
  "oracle_resolved": "<绝对路径或 null>", "oracle_resolved_via": "reference-ancestor(...)|runner-relative(...)|none",
  "self_eval": false,
  "ok": true,
  "summary": {"checks": {"total": 4, "passed": 4, "failed": 0}, "text_agreement_rate": 1.0},
  "checks": [{"name": "...", "passed": true, "detail": "...", "...可选审计字段": "..."}]
}
```

审计字段：检查 3 附 `oracle_resolved` / `oracle_resolved_via`；检查 4 附
`text_agreement_rate` / `threshold` / `per_file`（逐文件 ref_lines / cand_lines / matched）。

## 6. 依赖、环境与红线

- Python 3.12（本机 3.12.10 实测）+ PyYAML（本机 6.0.3 实测）；无其它第三方依赖。
- 无网络、无 Docker（本机实测不在 PATH）、无随机、无时间戳。
- `oracle/out/` 只读：评测不写参照树；检查 3 的临时报告写系统临时目录并清理；
  评测器不改动被测/参照任何文件。
- 密钥红线同 oracle：评测对象三件套必须全部占位值；凭据形态字面量由 oracle C4 判红
  （spec §2.3 探针 4 实测 red-hardcoded-secret 被检查 3 击穿）。

## 7. 红绿自校验口径（本会话 2026-09-30 实测，命令与退出码见 spec §2.3 探针 4）

- **绿**：`python eval/runner.py oracle/out oracle/out` → exit 0（self_eval=true，rate=1.0，
  4/4 过）；连跑两次 stdout 逐字节一致。
- **红**：被测传空目录 → exit 1（四项全败，前置失败注明，candidate_resolved_via=none）。
- **补充红**：oracle fixtures 四个残缺包 + pack-subset 作被测 → 均 exit 1，FAIL 项分布见
  spec §2.3 探针 4 表。
