# deploy-pack · oracle（参照软件 + 机器可判验收）

用途：为 deploy-pack 资产提供"能跑、有确定性产出"的参照实现与验收门。
本机 windev-01 无 Docker（WSL1 无 VT-x），**容器实跑不在验收范围；验收 = validate.py 全过**。

## 文件

| 文件 | 作用 |
|---|---|
| `gen_deploy.py` | 部署包生成器：`--services asr,minutes,todo --out <dir>` → `docker-compose.yml` + `.env.example` + `DEPLOY.md` |
| `validate.py` | 校验器：C1-C7 七项检查（C1-C4 为验收主门），报告写 `--out` JSON，退出码即结论 |
| `run_fixtures.py` | 全量 fixtures 实跑入口，产物落 `out/` |
| `fixtures/` | 静态 fixtures：`services-*.txt` 服务清单正例/拒绝例 + `red-*/` 残缺包反例 |
| `out/` | 实跑产物（由 `run_fixtures.py` 生成） |

## 复跑

```bash
python run_fixtures.py          # 全量 fixtures（退出码 0 = 全部符合预期）
# 或分步：
python gen_deploy.py --services asr,minutes,todo --out out/pack-canonical
python validate.py --pack out/pack-canonical --out out/pack-canonical-validate.json
```

依赖：Python 3.12 + PyYAML（本机 6.0.3 实测）。已核实本机无 Docker，故不含容器实跑步骤。

## 检查项（validate.py）

| 项 | 内容 |
|---|---|
| C1 compose_safe_load | docker-compose.yml 可被 `yaml.safe_load` 解析 |
| C2 services_exact | 服务集与期望一致（缺省 asr,minutes,todo 三服务齐全） |
| C3 env_consistent | `.env.example` 变量集 == compose `${}` 引用集（双向）且内联缺省值不漂移 |
| C4 no_hardcoded_secrets | 密钥名必须 `${}` 引用；无凭据形态字面量（sk-/AKIA/ghp_/xox-/PEM/JWT/长HEX） |
| C5 wiring_asr_minutes | asr 输出目录 `ASR_OUTPUT_DIR` == minutes 输入目录 `MINUTES_INPUT_DIR`，compose 双侧接线 |
| C6 deploy_md_three_cmds | DEPLOY.md 含三命令要素（复制 env → compose up → 健康检查） |
| C7 deterministic_regenerate | 以包内服务集重跑生成器，三份产物逐字节一致 |

## fixtures 矩阵（每个残缺包恰好击穿一项主门检查）

| fixture | 期望 |
|---|---|
| `services-canonical.txt`（asr,minutes,todo） | 生成 exit 0 + 校验 ALL GREEN |
| `services-subset.txt`（asr,todo） | 生成 exit 0 + 校验 ALL GREEN（C5 SKIP） |
| `services-invalid.txt`（asr,wat） | 生成器 exit 2 且不建目录 |
| `red-bad-yaml/` | 校验 exit 1，C1 FAIL |
| `red-missing-service/`（合法双服务包） | 校验 exit 1，C2 FAIL |
| `red-env-drift/`（.env 缺 TODO_PORT） | 校验 exit 1，C3 FAIL |
| `red-hardcoded-secret/`（compose 假密钥字面量，串为 test/零填充/x 占位假串） | 校验 exit 1，C4 FAIL |
