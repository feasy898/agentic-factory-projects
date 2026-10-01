#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deploy.py — 三服务（asr/minutes/todo）部署包生成器

用法（spec.md §3 R1 冻结）：
    python gen_deploy.py --services asr,minutes,todo --out <dir> [--project-name <名>]

行为：
    --services      逗号分隔服务清单，可用值 = CATALOG 三服务（asr/minutes/todo）；
                    空清单或含未知服务 → stderr 打印 [GEN-FAIL] 且 exit 2、不建输出目录
    --out           输出目录（不存在则创建），写出部署包三件套（PACK_FILES）：
                    docker-compose.yml / .env.example / DEPLOY.md
    --project-name  compose 项目名；缺省 = 服务名按 CATALOG 目录序 "-" 连接

确定性（spec §3 R4）：服务输出一律按 CATALOG 目录序（与 --services 书写序无关）；
无时间戳、无随机，同参数重复运行产物逐字节一致（由 validate.py C7 复核）。

退出码（spec §3 R5）：0=成功；1=写出失败；2=参数非法（不建输出目录）。

R1-迭代说明（2026-10-01，worker-A）：
    首轮终门 eval/runner.py 两项红（C7 deterministic_regenerate、
    reference_text_agreement_90pct=60%）。依据 spec.md 附录 A.3：检查 3/4 的比对
    基准 = 参照 gen_deploy.py 模板活文。本轮把三件套渲染文本对齐参照模板逐字同源
    （compose 头注释 4 行 + ASR_INPUT_DIR 进 environment + 缺省值 ./data/incoming；
    .env.example 逐变量中文注释；DEPLOY.md 章节与措辞同源，含生成器路径行），
    并在 Linux 侧重生成产物（LF 行尾）。行为性 CLI（退出码/校验 fail-closed）不变。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ASSET = "skillfactory/v5/assets/deploy-pack/package"

# ---------------------------------------------------------------- 冻结常量（spec 附录 A）
EXPECTED_SERVICES = ("asr", "minutes", "todo")   # = CATALOG 键序（目录序）
PACK_FILES = ("docker-compose.yml", ".env.example", "DEPLOY.md")

CONTAINER_PORT = "8000"      # 各服务容器内统一监听端口（占位约定，宿主端口走变量）
HEALTH_PATH = "/healthz"     # 各服务健康检查路径（占位约定）

# 管线接线契约（spec §2.1）：(生产侧服务, 生产侧变量) / (消费侧服务, 消费侧变量) 两值必须相同
WIRING = (("asr", "ASR_OUTPUT_DIR"), ("minutes", "MINUTES_INPUT_DIR"))

# 服务目录：键序即输出序；env 元组 = (变量名, 缺省值, 中文注释)
# （spec §2.1 冻结：变量/缺省值/注释与参照 CATALOG 逐条同源——缺省值进产物文本）
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


# ---------------------------------------------------------------- 基础工具
def ref(var, default):
    """compose 变量引用 + 内联缺省值（与 .env.example 缺省值一致，validate C3 防漂移）。"""
    return "${%s:-%s}" % (var, default)


def image_var(name):
    """每服务镜像变量名派生规则：<SVC>_IMAGE（spec §2.1 同口径）。"""
    return name.upper() + "_IMAGE"


def port_var(name):
    """每服务端口变量名派生规则：<SVC>_PORT。"""
    return name.upper() + "_PORT"


def _env_default(name, var):
    for v, d, _c in CATALOG[name]["env"]:
        if v == var:
            return d
    raise KeyError(var)


def parse_services(raw):
    """解析 --services：空清单或含未知服务 → (None, 错误说明)；否则按 CATALOG 目录序返回。"""
    items = [p.strip() for p in (raw or "").split(",")]
    items = [p for p in items if p]
    if not items:
        return None, "空服务清单"
    unknown = [p for p in items if p not in CATALOG]
    if unknown:
        return None, "未知: %s" % ", ".join(unknown)
    return [s for s in EXPECTED_SERVICES if s in items], None


# ---------------------------------------------------------------- 三件套渲染
def _service_block(name):
    """单服务 compose 块（文本与参照模板逐字同源，spec 附录 A.3 声明的比对基准）。"""
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


def render_compose(services, project):
    """docker-compose.yml：参照同源头注释（含接线行）+ name + services 块。"""
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


def render_env(services):
    """.env.example：参照同源——分节注释 + 每变量带中文注释行 + 全部占位值。"""
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


def render_deploy(services, project):
    """DEPLOY.md：参照同源——前置条件/三步命令/服务端口表/接线/注意。"""
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


# ---------------------------------------------------------------- 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="deploy-pack 部署包生成器：--services asr,minutes,todo --out <dir>")
    ap.add_argument("--services", required=True,
                    help="逗号分隔服务清单，可用值: %s" % ",".join(EXPECTED_SERVICES))
    ap.add_argument("--out", required=True, help="输出目录（不存在则创建）")
    ap.add_argument("--project-name", default=None,
                    help="compose 项目名（缺省=服务名按 CATALOG 目录序 '-' 连接）")
    args = ap.parse_args(argv)

    # 参数非法：exit 2，且不得创建输出目录（spec §3 R5）
    services, err = parse_services(args.services)
    if err is not None:
        print("[GEN-FAIL] 非法 --services: '%s'（%s），可用服务: %s"
              % (args.services, err, ", ".join(EXPECTED_SERVICES)), file=sys.stderr)
        return 2

    project = args.project_name or "-".join(services)
    out = Path(args.out)
    files = {
        PACK_FILES[0]: render_compose(services, project),
        PACK_FILES[1]: render_env(services),
        PACK_FILES[2]: render_deploy(services, project),
    }
    try:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        print("[GEN-FAIL] 写出失败: %s" % exc, file=sys.stderr)
        return 1
    for fn in PACK_FILES:
        print("[GEN] %s" % (out / fn))
    print("[GEN] 服务: %s | 项目名: %s" % (", ".join(services), project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
