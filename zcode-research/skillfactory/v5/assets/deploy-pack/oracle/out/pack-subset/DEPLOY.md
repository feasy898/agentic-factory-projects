# DEPLOY — asr-todo 部署包

> 由 `skillfactory/v5/assets/deploy-pack/oracle/gen_deploy.py` 生成。
> 服务: asr, todo。镜像名为占位符（`placeholder/*`），上线前在 `.env` 中替换为真实镜像。

## 前置条件

- Docker Engine ≥ 20.10 且带 compose v2 插件（`docker compose version` 可用）
- 端口 8001/8003 未被占用（可在 `.env` 修改）

## 部署三步（三条命令）

```bash
# 1) 复制并按需修改环境变量（Linux/macOS/Git Bash）
cp .env.example .env
#    Windows PowerShell 等价: Copy-Item .env.example .env

# 2) 启动服务
docker compose up -d

# 3) 健康检查：先看容器健康状态，再逐服务探测 /healthz
docker compose ps
curl -fsS http://localhost:8001/healthz   # asr
curl -fsS http://localhost:8003/healthz   # todo
```

三条命令执行完，`docker compose ps` 中各服务 STATUS 为 healthy、各 `/healthz` 返回 2xx，即部署成功。

## 服务与端口

| 服务 | 镜像（占位） | 宿主端口 | 健康检查 | 数据目录 |
|---|---|---|---|---|
| asr | `placeholder/asr:dev` | 8001 | `/healthz` | `ASR_INPUT_DIR` / `ASR_OUTPUT_DIR` |
| todo | `placeholder/todo:dev` | 8003 | `/healthz` | `TODO_DATA_DIR` |

## 注意

- `.env.example` 中全部为占位值，不含任何真实凭据；接入真实服务时把 key 写进 `.env`（该文件不要提交版本库）。
- 占位镜像 `placeholder/*` 不可拉取，需替换为真实镜像后 `docker compose up -d` 才能成功。
- 数据目录由 bind mount 指定，容器首启会自动创建（相对路径基于 compose 文件所在目录）。
