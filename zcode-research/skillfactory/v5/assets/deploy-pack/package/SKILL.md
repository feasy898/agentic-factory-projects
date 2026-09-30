---
name: deploy-pack
description: 三服务（asr/minutes/todo）部署包的生成、裁剪与单位落地。当需要为 asr/minutes/todo 生成 docker compose 部署包、按单位裁剪服务子集、或在单位环境完成落地部署与验收时使用。
---

# 部署包裁剪与单位落地流程（deploy-pack）

## 何时使用

- 需要一条命令产出三服务（asr 语音识别 / minutes 会议纪要 / todo 待办清单）的
  docker compose 部署包（docker-compose.yml + .env.example + DEPLOY.md 三件套）；
- 单位只要部分服务，需要**裁剪**出子集部署包；
- 把部署包交付到单位环境完成**落地**（换镜像 → 起服务 → 健康检查 → 验收）。

## 资产组成（本目录 package/）

| 文件 | 角色 |
|---|---|
| `gen_deploy.py` | 生成器：`--services` 裁剪服务集，产出三件套 |
| `validate.py` | 校验器：C1-C7 七项检查，**判绿唯一口径**（ALL GREEN + exit 0） |
| `out/` | 本会话运行产物（canonical 包 / subset 包 / 各 validate 报告 / 反例报告） |

## 流程

### 第 1 步：生成（按需裁剪）

```bash
# 全量三服务包
python gen_deploy.py --services asr,minutes,todo --out <部署目录>

# 裁剪：单位只要 asr + todo
python gen_deploy.py --services asr,todo --out <部署目录>

# 指定 compose 项目名（缺省 = 服务名按目录序 "-" 连接）
python gen_deploy.py --services asr,minutes,todo --out <部署目录> --project-name <单位项目名>
```

- 服务输出**一律按 CATALOG 目录序**（asr → minutes → todo），与 `--services` 书写序无关，保证可重现。
- 空清单或含未知服务 → stderr `[GEN-FAIL]` 且 **exit 2、不建目录**。

### 第 2 步：校验（交付前必须全绿）

```bash
python validate.py --pack <部署目录> --out validate-report.json
```

- 七项检查：C1 compose 可解析、C2 服务集恰等、C3 .env 与 compose `${}` 引用集双向一致且缺省不漂移、
  C4 无硬编码密钥、C5 asr→minutes 管线接线双侧同值、C6 DEPLOY.md 三命令要素、C7 用 gen_deploy.py
  重生成逐字节比对（确定性）。
- **验收口径：exit 0 且 verdict=ALL GREEN 且 summary.fail==0**（SKIP 不计失败）。

### 第 3 步：单位落地（在单位环境执行）

```bash
# 1) 生成环境配置（占位默认值即可先起，随后按实际环境修改）
cp .env.example .env

# 2) 修改 .env：镜像替换为单位仓库地址、端口/目录按单位规划调整
#    注意：不得手工增删变量（C3 把关变量集双向一致）

# 3) 启动与状态
docker compose up -d
docker compose ps

# 4) 逐服务健康检查（容器内统一 8000，路径 /healthz；宿主端口见 .env 的 *_PORT）
curl -fsS http://127.0.0.1:8001/healthz   # asr
curl -fsS http://127.0.0.1:8002/healthz   # minutes
curl -fsS http://127.0.0.1:8003/healthz   # todo
```

落地要点：

- 镜像均为占位（`placeholder/*`），**不可拉取**；`docker compose up` 前必须完成镜像替换或本地构建；
- 管线接线：`asr.ASR_OUTPUT_DIR` 与 `minutes.MINUTES_INPUT_DIR` 必须同值
  （默认同为 `./data/asr-out`，识别产物直接作为纪要输入），调整时两侧同步改（C5 把关）；
- 数据目录默认相对部署目录（`./data/...`），按单位磁盘规划调整并确保可写；
- 宿主端口冲突改 `.env` 的 `*_PORT`，容器内端口固定 8000 勿动。

### 第 4 步：验收

1. 交付前：`validate.py` 全绿（exit 0 / ALL GREEN / fail==0）；
2. 落地后：`docker compose ps` 全部 Up（healthy）+ 逐服务 `curl /healthz` 返回 200；
3. 如需机器判收，可跑上级 eval（`skillfactory/v5/assets/deploy-pack/eval/runner.py`，四项检查口径见 contract.md）。

## 红线

- `.env.example` 全部为占位值，**严禁写入真实凭据**；凭据类变量一律经 `${VAR:-默认}` 引用（C4 判红）；
- 服务集如需变更，用 `gen_deploy.py --services` 重新生成整包，勿手工删块；
- 同参数重复运行生成器产物**逐字节一致**（无时间戳/无随机），便于审计与 diff。
