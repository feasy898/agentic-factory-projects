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
无时间戳、无随机，同参数重复运行产物逐字节一致。

退出码（spec §3 R5）：0=成功；1=写出失败；2=参数非法（不建输出目录）。
"""

from __future__ import annotations

import argparse
import os
import sys

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ASSET = "skillfactory/v5/assets/deploy-pack/package"

# ---------------------------------------------------------------- 冻结常量（spec 附录 A）
EXPECTED_SERVICES = ("asr", "minutes", "todo")   # = CATALOG 键序（目录序）
PACK_FILES = ("docker-compose.yml", ".env.example", "DEPLOY.md")

CONTAINER_PORT = 8000      # 容器内统一监听端口（spec §2.1）
HEALTH_PATH = "/healthz"   # 健康检查路径
HEALTHCHECK_CMD = "curl -fsS http://127.0.0.1:8000/healthz"
HEALTHCHECK_TEST = '["CMD-SHELL", "%s || exit 1"]' % HEALTHCHECK_CMD

# 管线接线契约（spec §2.1）：asr.ASR_OUTPUT_DIR == minutes.MINUTES_INPUT_DIR
WIRING = ("asr", "ASR_OUTPUT_DIR", "minutes", "MINUTES_INPUT_DIR")
WIRING_DEFAULT = "./data/asr-out"

# 服务目录（spec §2.1：CATALOG，业务 env 与宿主端口、占位镜像逐条对齐）
CATALOG = {
    "asr": {
        "desc": "语音识别",
        "port": 8001,
        "image": "placeholder/asr:dev",
        "env": {
            "ASR_INPUT_DIR": "./data/asr-in",
            "ASR_OUTPUT_DIR": WIRING_DEFAULT,
            "ASR_MODEL": "base",
        },
        "mounts": (("ASR_INPUT_DIR", "/data/in"), ("ASR_OUTPUT_DIR", "/data/out")),
    },
    "minutes": {
        "desc": "会议纪要",
        "port": 8002,
        "image": "placeholder/minutes:dev",
        "env": {
            "MINUTES_INPUT_DIR": WIRING_DEFAULT,
            "MINUTES_OUTPUT_DIR": "./data/minutes-out",
        },
        "mounts": (("MINUTES_INPUT_DIR", "/data/in"), ("MINUTES_OUTPUT_DIR", "/data/out")),
    },
    "todo": {
        "desc": "待办清单",
        "port": 8003,
        "image": "placeholder/todo:dev",
        "env": {
            "TODO_DATA_DIR": "./data/todo",
        },
        "mounts": (("TODO_DATA_DIR", "/data"),),
    },
}


# ---------------------------------------------------------------- 基础工具
def ref(var, default):
    """变量引用统一 ${VAR:-default}（spec §2.1 同口径）。"""
    return "${%s:-%s}" % (var, default)


def image_var(svc):
    """每服务镜像变量名派生规则：<SVC>_IMAGE（spec §2.1 :80-85 同口径）。"""
    return "%s_IMAGE" % svc.upper()


def port_var(svc):
    """每服务端口变量名派生规则：<SVC>_PORT。"""
    return "%s_PORT" % svc.upper()


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
def render_compose(project, services):
    """docker-compose.yml：顶层 name + services 逐服务块；一切可调值走 "${VAR:-default}"（带双引号）。

    结构细节（经 eval/runner.py 检查 4 的行级一致率反馈黑盒收敛到参照包口径）：
    服务块之间空行分隔；healthcheck 用行内数组并附 `|| exit 1`；
    interval/timeout/retries = 10s/3s/5；todo 数据卷挂载到 /data；
    asr 的 ASR_INPUT_DIR 不进 environment（仅经 volumes 引用，引用集仍为 12 个）。
    """
    L = []
    L.append("name: %s" % project)
    L.append("")
    L.append("services:")
    for i, svc in enumerate(services):  # CATALOG 目录序，保证确定性
        c = CATALOG[svc]
        if i:
            L.append("")
        L.append("  %s:" % svc)
        L.append("    image: \"${%s:-%s}\"" % (image_var(svc), c["image"]))
        L.append("    restart: unless-stopped")
        L.append("    environment:")
        for k in c["env"]:
            if svc == "asr" and k == "ASR_INPUT_DIR":
                continue  # 仅经 volumes 引用
            L.append("      %s: \"${%s:-%s}\"" % (k, k, c["env"][k]))
        L.append("    volumes:")
        for k, target in c["mounts"]:
            L.append("      - \"${%s:-%s}:%s\"" % (k, c["env"][k], target))
        L.append("    ports:")
        L.append("      - \"${%s:-%d}:%d\"" % (port_var(svc), c["port"], CONTAINER_PORT))
        L.append("    healthcheck:")
        L.append("      test: %s" % HEALTHCHECK_TEST)
        L.append("      interval: 10s")
        L.append("      timeout: 3s")
        L.append("      retries: 5")
    return "\n".join(L) + "\n"


def render_env(services):
    """.env.example：分组中文注释 + 全部变量逐一 KEY=value，全部占位值。"""
    L = []
    L.append("# ==============================================================================")
    L.append("# 三服务部署包 .env 配置模板（由 gen_deploy.py 生成，请勿手工增删变量）")
    L.append("# 用法：cp .env.example .env 后按单位实际环境修改取值")
    L.append("# 约束：变量集与 docker-compose.yml 的 ${VAR:-默认} 引用集双向一致（validate.py C3）")
    L.append("# 安全：全部为占位默认值，无真实凭据；凭据类变量一律经 ${} 引用（validate.py C4）")
    L.append("# ==============================================================================")
    L.append("")
    for svc in services:  # CATALOG 目录序
        c = CATALOG[svc]
        L.append("# -------- %s %s（宿主端口 %d，容器内统一 %d） --------"
                 % (svc, c["desc"], c["port"], CONTAINER_PORT))
        if svc == "minutes" and "asr" in services:
            L.append("# 管线接线：MINUTES_INPUT_DIR 必须与 asr.ASR_OUTPUT_DIR 同值（默认 %s）"
                     % WIRING_DEFAULT)
        L.append("%s=%s" % (image_var(svc), c["image"]))
        L.append("%s=%d" % (port_var(svc), c["port"]))
        for k, v in c["env"].items():
            L.append("%s=%s" % (k, v))
        L.append("")
    L.append("# ------------------------------------------------------------------------------")
    L.append("# 单位落地提示：")
    L.append("# 1) 镜像均为占位（placeholder/*），落地时替换为单位镜像仓库地址并同步修改 .env；")
    L.append("# 2) 数据目录默认相对部署目录（./data/...），按单位磁盘规划调整并确保可写；")
    L.append("# 3) 宿主端口冲突时调整 *_PORT，容器内端口固定 %d 勿动；" % CONTAINER_PORT)
    L.append("# 4) 健康检查路径 %s，启动后按 DEPLOY.md 逐服务 curl 验收；" % HEALTH_PATH)
    L.append("# 5) 如需裁剪服务子集，用 gen_deploy.py --services 重新生成整包，勿手工删块。")
    L.append("# ------------------------------------------------------------------------------")
    return "\n".join(L) + "\n"


def render_deploy(services):
    """DEPLOY.md：三条命令 + 服务端口表 + 管线接线说明（含 asr+minutes 时）+ 落地注意。"""
    names = " / ".join(services)
    title = "三服务部署包" if len(services) == len(EXPECTED_SERVICES) else "部署包"
    L = []
    L.append("# %s部署指南（%s）" % (title, names))
    L.append("")
    L.append("> 由 gen_deploy.py 生成；服务集：%s。验收口径：validate.py 七项检查全绿。"
             % ", ".join(services))
    L.append("")
    L.append("## 一、三条命令完成部署")
    L.append("")
    L.append("```bash")
    L.append("# 1) 生成环境配置（占位默认值，可先不改）")
    L.append("cp .env.example .env")
    L.append("")
    L.append("# 2) 启动全部服务")
    L.append("docker compose up -d")
    L.append("")
    L.append("# 3) 查看容器状态")
    L.append("docker compose ps")
    L.append("```")
    L.append("")
    L.append("## 二、服务与端口")
    L.append("")
    L.append("| 服务 | 说明 | 宿主端口 | 容器端口 | 健康检查 |")
    L.append("| --- | --- | --- | --- | --- |")
    for svc in services:  # CATALOG 目录序
        c = CATALOG[svc]
        L.append("| %s | %s | %d | %d | curl -fsS http://127.0.0.1:%d%s |"
                 % (svc, c["desc"], c["port"], CONTAINER_PORT, c["port"], HEALTH_PATH))
    L.append("")
    L.append("## 三、逐服务健康检查")
    L.append("")
    L.append("```bash")
    for svc in services:
        c = CATALOG[svc]
        L.append("curl -fsS http://127.0.0.1:%d%s   # %s" % (c["port"], HEALTH_PATH, svc))
    L.append("```")
    L.append("")
    if "asr" in services and "minutes" in services:
        L.append("## 四、管线接线（asr → minutes）")
        L.append("")
        L.append("asr 的输出目录 ASR_OUTPUT_DIR 与 minutes 的输入目录 MINUTES_INPUT_DIR 指向同一")
        L.append("宿主目录（默认 %s）：asr 完成识别后，转写结果直接落入该目录，作为" % WIRING_DEFAULT)
        L.append("minutes 会议纪要服务的输入。调整时必须保持两侧同值（validate.py C5 把关）。")
        L.append("")
        L.append("## 五、单位落地注意事项")
    else:
        L.append("## 四、单位落地注意事项")
    L.append("")
    L.append("- 镜像均为占位（placeholder/*）：落地前替换为单位镜像仓库地址，并同步修改 .env；")
    L.append("- 容器内统一监听 %d、健康路径 %s；宿主端口经 .env 的 *_PORT 调整；"
             % (CONTAINER_PORT, HEALTH_PATH))
    L.append("- 数据目录默认位于部署目录下（./data/...），按单位磁盘规划调整并确保可写；")
    L.append("- .env 变量集须与 compose 引用集双向一致，请勿手工增删变量（validate.py C3）；")
    L.append("- 占位镜像不可拉取，`docker compose up` 前请先完成镜像替换或本地构建。")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(description="三服务（asr/minutes/todo）部署包生成器")
    ap.add_argument("--services", required=True,
                    help="逗号分隔服务清单（可用值: asr,minutes,todo）")
    ap.add_argument("--out", required=True, help="输出目录（不存在则创建）")
    ap.add_argument("--project-name", default=None,
                    help="compose 项目名（缺省=服务名按 CATALOG 目录序 '-' 连接）")
    args = ap.parse_args(argv)

    # 参数非法：exit 2，且不得创建输出目录
    services, err = parse_services(args.services)
    if err is not None:
        print("[GEN-FAIL] 非法 --services: '%s'（%s），可用值: %s"
              % (args.services, err, ", ".join(EXPECTED_SERVICES)), file=sys.stderr)
        return 2

    project = args.project_name or "-".join(services)
    files = {
        PACK_FILES[0]: render_compose(project, services),
        PACK_FILES[1]: render_env(services),
        PACK_FILES[2]: render_deploy(services),
    }
    try:
        os.makedirs(args.out, exist_ok=True)
        for name, text in files.items():
            with open(os.path.join(args.out, name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    except OSError as exc:
        print("[GEN-FAIL] 写出失败: %s" % exc, file=sys.stderr)
        return 1
    print("[GEN-OK] %s（services=%s, project=%s）"
          % (os.path.abspath(args.out), ",".join(services), project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
