"""COS 中转（training-plan §1.3；延后资产——本机只生成命令序列）。

职责：数据集/训练产物在采集机 ↔ COS ↔ GPU 机之间的传输计划——7z 分卷
（按 config/datasets.json 的 volume_mb）+ coscmd 上/下行命令。生成**命令
清单**供操作者核对执行；本机默认不执行任何传输。

红线（开发指令 §10.4）：COS 写入只用 coscmd；密钥只在本机 coscmd 配置
文件（--coscmd-conf / 环境变量 COSCMD_CONF / 缺省 ~/.cosconf），永不入库。

用法（仓库根）::

    python -m chengshao.training.transfer.cos_transfer --entry spoon_scooping_v1 up
    python -m chengshao.training.transfer.cos_transfer --entry runs down --out plan.json
    # --execute 需 --yes 且 coscmd 在 PATH；缺省只打印/落计划

退出码：0=成功；2=参数/环境错误（含 execute 拒绝）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chengshao.training.common import (  # noqa: E402
    ConfigError,
    dump_json,
    fail,
    load_json,
    safe_rel_output,
    utc_now_iso,
)

_MODULE = "training.transfer.cos_transfer"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "datasets.json"


def build_plan(entry_name: str, direction: str, cfg: dict[str, Any],
               coscmd_conf: str, local_root_override: str | None) -> dict[str, Any]:
    entries = cfg.get("entries")
    if not isinstance(entries, dict) or entry_name not in entries:
        raise ConfigError(f"--entry 未在 config/datasets.json 声明：{entry_name!r}")
    e = entries[entry_name]
    local = safe_rel_output(local_root_override or e["local_dir"], field="local_dir")
    remote = str(e["remote"]).strip("/")
    bucket = cfg["cos"]["bucket"]
    volume_mb = int(e.get("volume_mb", 2048))
    conf_opt = f"--config-file {coscmd_conf}" if coscmd_conf else ""
    conf_argv = ["--config-file", coscmd_conf] if coscmd_conf else []
    if direction == "up":
        cmds = [
            f"7z -t7z -v{volume_mb}m a {entry_name}.7z.7z {local}",
            f"coscmd {conf_opt} -b {bucket} upload -r {entry_name}.7z_*.7z {remote}/",
            f"coscmd {conf_opt} -b {bucket} ls {remote}/  # 核对分卷数量",
        ]
        # 执行面走结构化 argv（--execute 专用）：无 shell、无字符串拼解析，
        # 展示串里的行内注释不进入实际命令行
        argvs = [
            ["7z", "-t7z", f"-v{volume_mb}m", "a", f"{entry_name}.7z.7z", str(local)],
            ["coscmd", *conf_argv, "-b", bucket, "upload", "-r",
             f"{entry_name}.7z_*.7z", f"{remote}/"],
            ["coscmd", *conf_argv, "-b", bucket, "ls", f"{remote}/"],
        ]
    else:
        cmds = [
            f"coscmd {conf_opt} -b {bucket} download -r {remote}/ {entry_name}_vols/",
            f"7z x {entry_name}_vols/{entry_name}.7z.001 -o{local}",
            # 分卷完整性：核对 7z 自身 CRC（7z t），不另造校验
            f"7z t {entry_name}_vols/{entry_name}.7z.001",
        ]
        argvs = [
            ["coscmd", *conf_argv, "-b", bucket, "download", "-r", f"{remote}/",
             f"{entry_name}_vols/"],
            ["7z", "x", f"{entry_name}_vols/{entry_name}.7z.001", f"-o{local}"],
            ["7z", "t", f"{entry_name}_vols/{entry_name}.7z.001"],
        ]
    size_est_gb = None
    if local.is_dir():
        from chengshao.training.common import dir_size_bytes

        size_est_gb = round(dir_size_bytes(local) / 1e9, 2)
    speed = float(cfg["cos"].get("upload_speed_mbps_estimate", 20))
    est_minutes = round(size_est_gb * 1024 / (speed * 3600 / 8), 1) if size_est_gb else None
    return {
        "entry": entry_name,
        "direction": direction,
        "bucket": bucket,
        "remote": remote,
        "local_dir": str(local),
        "volume_mb": volume_mb,
        "local_size_gb_est": size_est_gb,
        "transfer_minutes_est": est_minutes,
        "coscmd_conf": coscmd_conf or "(缺省 ~/.cosconf)",
        "commands": cmds,
        "command_argv": argvs,
        "executed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.transfer.cos_transfer",
        description="COS 中转命令清单生成（缺省不执行；执行需 --execute --yes + coscmd）")
    parser.add_argument("--entry", required=True, help="config/datasets.json 的条目名")
    parser.add_argument("direction", choices=["up", "down"], help="up=上行 / down=下行")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--local-dir", type=str, default=None,
                        help="覆盖条目的 local_dir（仓库相对）")
    parser.add_argument("--coscmd-conf", type=str, default=None,
                        help="coscmd 配置文件（缺省环境 COSCMD_CONF / ~/.cosconf）")
    parser.add_argument("--out", type=Path, default=None, help="计划 JSON 输出路径")
    parser.add_argument("--execute", action="store_true",
                        help="逐条执行生成的命令（需 --yes；本机需已配好 coscmd）")
    parser.add_argument("--yes", action="store_true", help="执行确认（防误触）")
    args = parser.parse_args(argv)

    if not args.config.is_file():
        fail(f"配置不存在：{args.config}")
    try:
        cfg = load_json(args.config)
        conf = (args.coscmd_conf or os.environ.get("COSCMD_CONF") or "").strip()
        plan = build_plan(args.entry, args.direction, cfg, conf, args.local_dir)
    except ConfigError as exc:
        fail(str(exc))

    if args.execute:
        if not args.yes:
            fail("--execute 需要显式 --yes（防误触）")
        if shutil.which("coscmd") is None:
            fail("coscmd 不在 PATH——安装/配置见 COS 使用指南（本机不装则只生成计划）")
        import subprocess

        # 加固后的执行面：结构化 argv（build_plan 产出 command_argv，与展示串
        # 一一对应），程序名白名单 + shutil.which 解析出绝对路径作 argv[0]，
        # 全程无 shell、无字符串拼解析——展示串中的行内注释不进入实际命令行。
        allowed = {"coscmd", "7z"}
        argv_list = plan.get("command_argv") or []
        if len(argv_list) != len(plan["commands"]):
            fail("计划缺少结构化命令（command_argv）——请重新生成计划后再 --execute")
        resolved: dict[str, str] = {}
        for prog in sorted(allowed):
            path = shutil.which(prog)
            if path is not None:
                resolved[prog] = path
        if "coscmd" not in resolved:
            fail("coscmd 不在 PATH——安装/配置见 COS 使用指南（本机不装则只生成计划）")
        for cmd, argv in zip(plan["commands"], argv_list):
            prog = str(argv[0]).lower() if argv else ""
            if prog not in allowed or prog not in resolved:
                fail(f"命令程序不在白名单（{'/'.join(sorted(allowed))}）：{argv[:1]}")
            print(f"$ {cmd}")
            r = subprocess.run([resolved[prog], *argv[1:]], shell=False)
            if r.returncode != 0:
                fail(f"命令失败（exit={r.returncode}）：{cmd}")
        plan["executed"] = True
    print("PLAN:", plan)
    if args.out is not None:
        plan["generated_at"] = utc_now_iso()
        dump_json(args.out, {"module": _MODULE, "plan": plan})
        print(f"WROTE: {args.out}")
    if not args.execute:
        print("NOTE: 未执行任何命令（传输红线：写入只用 coscmd，操作者核对后自行执行）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
