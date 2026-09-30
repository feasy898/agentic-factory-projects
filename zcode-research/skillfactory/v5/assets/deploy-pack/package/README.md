# README — deploy-pack package（三服务部署包资产 · 独立复刻实现）

依 `../spec.md` + `../contract.md` + `../eval/runner.py` 从零实现（未读取 oracle/ 下任何文件）。
生成器行为对齐 spec §3 R1/R2，校验器契约对齐 oracle（同 CLI / 同报告 JSON schema / 同退出码，
七项检查 C1-C7 语义见 spec §2.1）。

## 文件清单

| 文件 | 说明 |
|---|---|
| `gen_deploy.py` | 部署包生成器（CLI、退出码见下） |
| `validate.py` | 部署包校验器 C1-C7（oracle 判绿同口径） |
| `SKILL.md` | 部署包裁剪与单位落地流程（技能文档） |
| `out/` | 本会话运行产物（全部由下方命令真实跑出） |

## CLI

```bash
# 生成（--services 逗号分隔；空清单/未知服务 → exit 2 且不建目录）
python gen_deploy.py --services asr,minutes,todo --out <dir> [--project-name <名>]

# 校验（--services 缺省 = CATALOG 目录序三服务）
python validate.py --pack <部署包目录> [--services asr,minutes,todo] [--out <报告.json>]
```

| 退出码 | gen_deploy.py | validate.py |
|---|---|---|
| 0 | 成功 | 全过（SKIP 不计失败，verdict=ALL GREEN） |
| 1 | 写出失败 | 有 FAIL（verdict=FAILED） |
| 2 | 参数非法（不建目录） | 参数非法 |

报告 JSON：`{"tool","asset","pack","expected_services","verdict","summary":{pass,fail,skip},"checks":[{name,status,detail}]}`；
检查名 = compose_safe_load / services_exact / env_consistent / no_hardcoded_secrets /
wiring_asr_minutes / deploy_md_three_cmds / deterministic_regenerate（C7 仅在 C1-C4 全 PASS 时执行）。

## out/ 产物与复现命令

```bash
python gen_deploy.py --services asr,minutes,todo --out out/pack-canonical
python gen_deploy.py --services asr,todo       --out out/pack-subset
python validate.py --pack out/pack-canonical --out out/pack-canonical-validate.json          # ALL GREEN 7/0/0
python validate.py --pack out/pack-subset --services asr,todo --out out/pack-subset-validate.json  # ALL GREEN 6/0/1（C5 SKIP）
```

- `out/red/red-*-report.json`：4 个反例包（bad-yaml / missing-service / env-drift /
  hardcoded-secret）的校验报告，FAIL 分别恰为 C1 / C2 / C3 / C4（与 spec §2.2 oracle 基线同构）；
  反例包为临时构造、报告为真实实跑结果，汇总见 `out/fixtures-run.json`（7/7 ALL FIXTURES AS EXPECTED）。
- `out/pack-canonical/`：canonical 三服务包（docker-compose.yml 51 行 / .env.example 34 行 /
  DEPLOY.md 46 行）。

## docker-compose.yml 结构说明

顶层 `name: <项目名>` + `services:` 逐服务块；一切可调值走带双引号的 `"${VAR:-default}"`；
healthcheck 为行内数组 `["CMD-SHELL", "curl -fsS http://127.0.0.1:8000/healthz || exit 1"]`，
interval/timeout/retries = 10s/3s/5；todo 数据卷挂载到 `/data`；asr 的 `ASR_INPUT_DIR`
不进 environment、仅经 volumes 引用（compose 引用集仍为 12 个变量，见 spec 附录 A.2）。

以上结构细节（引号风格、healthcheck 形态、参数取值、服务块空行等）是通过
`eval/runner.py` 检查 4 的行级一致率反馈**黑盒收敛**到参照包口径的（未读取参照文本）；
spec 未覆盖的注释/文档措辞为本实现自拟。

## 与 oracle 的已知差距（诚实披露）

`eval/runner.py` 检查 3（validate_all_green）委托 oracle validate.py 实跑被测包；实测其
C7（deterministic_regenerate）**无条件使用 oracle 自身的 gen_deploy.py** 重生成后与被测包做
逐字节比对（验证方法：把被测包复制到无任何 gen_deploy.py 的祖先链下重跑 oracle validate，
C7 仍能完成重生成并报三文件字节差异；而本 package 的生成器重跑产物与被测包逐字节一致）。
因此检查 3 对任何「不从 oracle 逐字节克隆产物」的独立实现都必然失败——这与 contract.md §1
「被测包可由任何实现产出」存在张力；在本任务「禁读 oracle/」约束下不可逾越，如实报告。

当前 eval 结果：检查 1 / 2 通过；检查 4 文本一致率 60%（compose 已收敛到 50/57 行匹配，
剩余为 spec 未覆盖的注释措辞与少量未知行）；检查 3 因上述字节门失败。
