#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deploy.py — deploy-pack 部署包生成器（oracle 参照软件）

用法:
    python gen_deploy.py --services asr,minutes,todo --out <dir>
    [--project-name <名>]   # 缺省: 服务名按目录序以 - 连接（如 asr-minutes-todo）

产出（写入 <dir>/，UTF-8、LF 行尾）:
    docker-compose.yml   各服务占位镜像名 + 环境变量接线
                         （asr 的 ASR_OUTPUT_DIR 与 minutes 的 MINUTES_INPUT_DIR 指向同一路径）
    .env.example         全部变量带中文注释；全部为占位/示例值，不含任何真实凭据
    DEPLOY.md            三条命令部署：复制 env → compose up → 健康检查

服务目录（--services 取值）: asr, minutes, todo；允许任意子集，输出顺序按目录表固定
（不随 --services 书写顺序变化，保证确定性）。
退出码: 0=成功；2=参数非法（服务清单为空或含未知服务，且不建目录）；1=写出失败
确定性: 同参数重复运行产物逐字节一致（由 validate.py C7 复核）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CONTAINER_PORT = "8000"      # 各服务容器内统一监听端口（占位约定，宿主端口走变量）
HEALTH_PATH = "/healthz"     # 各服务健康检查路径（占位约定）

# 服务目录：键序即输出序；env 元组 = (变量名, 缺省值, 中文注释)
CATALOG = {
    "asr": {
        "cn": "语音识别",
        "image_ph": "placeholder/asr:dev",
        "port": "8001",
        "env": [
            ("ASR_INPUT_DIR", "./data/incoming", "asr 输入目录（上传音频落盘处）"),
            ("ASR_OUTPUT_DIR", "./data/asr-out", "asr 输出目录（转写结果落盘处；即 minutes 的输入目录）"),
            ("ASR_MODEL", "base", "asr 模型档位（占位示例）"),
        ],
        "mounts": [("ASR_INPUT_DIR", "/data/in"), ("ASR_OUTPUT_DIR", "/data/out")],
    },
    "minutes": {
        "cn": "会议纪要",
        "image_ph": "placeholder/minutes:dev",
        "port": "8002",
        "env": [
            ("MINUTES_INPUT_DIR", "./data/asr-out", "minutes 输入目录（必须与 asr 的 ASR_OUTPUT_DIR 同一路径——管线接线）"),
            ("MINUTES_OUTPUT_DIR", "./data/minutes-out", "minutes 输出目录（纪要落盘处）"),
        ],
        "mounts": [("MINUTES_INPUT_DIR", "/data/in"), ("MINUTES_OUTPUT_DIR", "/data/out")],
    },
    "todo": {
        "cn": "待办清单",
        "image_ph": "placeholder/todo:dev",
        "port": "8003",
        "env": [
            ("TODO_DATA_DIR", "./data/todo", "todo 数据目录（SQLite 落盘处）"),
        ],
        "mounts": [("TODO_DATA_DIR", "/data")],
    },
}

# 管线接线契约：(生产侧服务, 生产侧变量) / (消费侧服务, 消费侧变量) —— 两值必须相同
WIRING = (("asr", "ASR_OUTPUT_DIR"), ("minutes", "MINUTES_INPUT_DIR"))

PACK_FILES = ("docker-compose.yml", ".env.example", "DEPLOY.md")


def ref(var: str, default: str) -> str:
    """compose 变量引用 + 内联缺省值（与 .env.example 缺省值一致，validate C3 防漂移）"""
    return "${%s:-%s}" % (var, default)


def image_var(name: str) -> str:
    return name.upper() + "_IMAGE"


def port_var(name: str) -> str:
    return name.upper() + "_PORT"


def _env_default(name: str, var: str) -> str:
    for v, d, _c in CATALOG[name]["env"]:
        if v == var:
            return d
    raise KeyError(var)


def _service_block(name: str) -> str:
    s = CATALOG[name]
    L = []
    L.append("  %s:" % name)
    L.append('    image: "%s"' % ref(image_var(name), s["image_ph"]))
    L.append("    restart: unless-stopped")
    L.append("    environment:")
    for var, dft, _cmt in s["env"]:
        L.append('      %s: "%s"' % (var, ref(var, dft)))
    L.append("    volumes:")
    for var, target in s["mounts"]:
        L.append('      - "%s:%s"' % (ref(var, _env_default(name, var)), target))
    L.append("    ports:")
    L.append('      - "%s:%s"' % (ref(port_var(name), s["port"]), CONTAINER_PORT))
    L.append("    healthcheck:")
    L.append('      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:%s%s || exit 1"]'
             % (CONTAINER_PORT, HEALTH_PATH))
    L.append("      interval: 10s")
    L.append("      timeout: 3s")
    L.append("      retries: 5")
    return "\n".join(L)


def compose_text(services, project) -> str:
    wired = all(s in services for s, _ in WIRING)
    L = []
    L.append("# docker-compose.yml — 由 gen_deploy.py 自动生成（勿手工编辑；调参改 .env 即可）")
    L.append("# 项目: %s" % project)
    L.append("# 服务: %s" % ", ".join(services))
    if wired:
        L.append("# 管线接线: asr 的 ASR_OUTPUT_DIR 与 minutes 的 MINUTES_INPUT_DIR 指向同一路径")
    L.append("")
    L.append("name: %s" % project)
    L.append("")
    L.append("services:")
    L.append("\n\n".join(_service_block(s) for s in services))
    return "\n".join(L) + "\n"


def env_text(services) -> str:
    L = []
    L.append("# ==========================================================")
    L.append("# deploy-pack 环境变量示例 — 由 gen_deploy.py 自动生成")
    L.append("# 用法: cp .env.example .env 后按需修改；docker compose 自动读取同目录 .env")
    L.append("# 安全: 本文件全部为占位/示例值，不含任何真实凭据；.env 请勿提交版本库")
    L.append("# ==========================================================")
    L.append("")
    for name in services:
        s = CATALOG[name]
        L.append("# ---- %s（%s）----" % (name, s["cn"]))
        L.append("# %s 服务镜像（占位名，上线前替换为真实镜像）" % name)
        L.append("%s=%s" % (image_var(name), s["image_ph"]))
        L.append("# %s 宿主机端口" % name)
        L.append("%s=%s" % (port_var(name), s["port"]))
        for var, dft, cmt in s["env"]:
            L.append("# %s" % cmt)
            L.append("%s=%s" % (var, dft))
        L.append("")
    return "\n".join(L).rstrip("\n") + "\n"


def deploy_md(services, project) -> str:
    wired = all(s in services for s, _ in WIRING)
    L = []
    L.append("# DEPLOY — %s 部署包" % project)
    L.append("")
    L.append("> 由 `skillfactory/v5/assets/deploy-pack/oracle/gen_deploy.py` 生成。")
    L.append("> 服务: %s。镜像名为占位符（`placeholder/*`），上线前在 `.env` 中替换为真实镜像。"
             % ", ".join(services))
    L.append("")
    L.append("## 前置条件")
    L.append("")
    L.append("- Docker Engine ≥ 20.10 且带 compose v2 插件（`docker compose version` 可用）")
    L.append("- 端口 %s 未被占用（可在 `.env` 修改）"
             % "/".join(CATALOG[n]["port"] for n in services))
    L.append("")
    L.append("## 部署三步（三条命令）")
    L.append("")
    L.append("```bash")
    L.append("# 1) 复制并按需修改环境变量（Linux/macOS/Git Bash）")
    L.append("cp .env.example .env")
    L.append("#    Windows PowerShell 等价: Copy-Item .env.example .env")
    L.append("")
    L.append("# 2) 启动服务")
    L.append("docker compose up -d")
    L.append("")
    L.append("# 3) 健康检查：先看容器健康状态，再逐服务探测 /healthz")
    L.append("docker compose ps")
    for name in services:
        L.append("curl -fsS http://localhost:%s%s   # %s" % (CATALOG[name]["port"], HEALTH_PATH, name))
    L.append("```")
    L.append("")
    L.append("三条命令执行完，`docker compose ps` 中各服务 STATUS 为 healthy、各 `/healthz` 返回 2xx，即部署成功。")
    L.append("")
    L.append("## 服务与端口")
    L.append("")
    L.append("| 服务 | 镜像（占位） | 宿主端口 | 健康检查 | 数据目录 |")
    L.append("|---|---|---|---|---|")
    for name in services:
        s = CATALOG[name]
        dirs = " / ".join("`%s`" % v for v, _d, _c in s["env"] if v.endswith("_DIR"))
        L.append("| %s | `%s` | %s | `%s` | %s |" % (name, s["image_ph"], s["port"], HEALTH_PATH, dirs))
    L.append("")
    if wired:
        L.append("## 管线接线")
        L.append("")
        L.append("asr 的输出目录 `ASR_OUTPUT_DIR` 与 minutes 的输入目录 `MINUTES_INPUT_DIR` 指向同一路径"
                 "（默认 `./data/asr-out`）：asr 把转写结果落盘，minutes 直接读同一目录。")
        L.append("两值必须一致；改动时同步修改 `.env` 中两行。")
        L.append("")
    L.append("## 注意")
    L.append("")
    L.append("- `.env.example` 中全部为占位值，不含任何真实凭据；接入真实服务时把 key 写进 `.env`"
             "（该文件不要提交版本库）。")
    L.append("- 占位镜像 `placeholder/*` 不可拉取，需替换为真实镜像后 `docker compose up -d` 才能成功。")
    L.append("- 数据目录由 bind mount 指定，容器首启会自动创建（相对路径基于 compose 文件所在目录）。")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="deploy-pack 部署包生成器：--services asr,minutes,todo --out <dir>")
    ap.add_argument("--services", required=True,
                    help="逗号分隔服务清单，可用: %s" % ",".join(CATALOG))
    ap.add_argument("--out", required=True, help="输出目录（不存在则创建）")
    ap.add_argument("--project-name", default=None, help="compose 项目名，缺省按服务名连接")
    a = ap.parse_args(argv)

    req = [x.strip() for x in a.services.split(",") if x.strip()]
    unknown = [x for x in req if x not in CATALOG]
    if not req or unknown:
        print("[GEN-FAIL] 非法 --services: %r（未知: %s）；可用服务: %s"
              % (a.services, ",".join(unknown) or "<空清单>", ",".join(CATALOG)),
              file=sys.stderr)
        return 2

    services = [s for s in CATALOG if s in set(req)]   # 目录序，保证确定性
    project = a.project_name or "-".join(services)
    out = Path(a.out)
    try:
        out.mkdir(parents=True, exist_ok=True)
        texts = {
            "docker-compose.yml": compose_text(services, project),
            ".env.example": env_text(services),
            "DEPLOY.md": deploy_md(services, project),
        }
        for fn, text in texts.items():
            (out / fn).write_text(text, encoding="utf-8", newline="\n")
    except OSError as e:
        print("[GEN-FAIL] 写出失败: %s" % e, file=sys.stderr)
        return 1

    for fn in PACK_FILES:
        print("[GEN] %s" % (out / fn))
    print("[GEN] 服务: %s | 项目名: %s" % (", ".join(services), project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
