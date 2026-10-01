"""策略训练命令生成器（T11；只生成不执行——真实训练在 GPU 机，开发指令 §10.3）。

从 training/config/train_act*.json 生成训练框架 CLI 命令行并打印/落报告。
生成器自身零执行路径：没有任何子进程/训练调用，dry-run 即其唯一本机形态。

训练入口名解析优先级（命名纪律：入口名不写入仓库文本，check_naming.py 把关）：
  1) ``--train-cmd`` 命令行注入；
  2) 环境变量 ``CS_TRAIN_CMD``；
  3) 本地覆盖文件 ``--local-config``（缺省 training/config/train.local.json，
     已 gitignore）的 ``"train_cmd"`` 键；
  4) 训练配置 ``runtime.train_cmd``（入库缺省 null）。
全链未解析 → 拒绝生成并 exit 2（fail-closed）；``--allow-placeholder`` 允许以
占位符输出（仅供人检阅配置效果，不可直接执行）。

用法（仓库根）::

    python -m chengshao.training.act.build_train_cmd \
        --config chengshao/training/config/train_act.json
    python -m chengshao.training.act.build_train_cmd \
        --train-cmd <GPU 机依赖提供的训练入口名> \
        --out chengshao/reports/training_act_cmd.json

生成命令行之外的核对项（写在 runbook_act.md §4，操作者人工完成）：
- 与训练入口 ``--help`` 对读未覆盖超参（kl_weight/hidden_dim/lr/lr_scheduler），
  以 ``--extra`` 追加；
- V100=sm_70 只用 fp16 AMP，禁止 bf16；
- wandb 强制关闭（离线红线，本模块强校验）。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # 直接路径执行时自举仓库根
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chengshao.cs_schema import N_ARM_JOINTS  # noqa: E402
from chengshao.training.common import (  # noqa: E402
    REPORTS_DIR,
    REPO_ROOT,
    TRAINING_CONFIG_DIR,
    ConfigError,
    dump_json,
    fail,
    load_json,
    safe_rel_output,
    utc_now_iso,
)

DEFAULT_CONFIG = TRAINING_CONFIG_DIR / "train_act.json"
DEFAULT_LOCAL_CONFIG = TRAINING_CONFIG_DIR / "train.local.json"
ENV_TRAIN_CMD = "CS_TRAIN_CMD"
PLACEHOLDER = "<train-cli>"
REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9][A-Za-z0-9_.-]*)?$")

_MODULE = "training.act.build_train_cmd"

VALID_TOP_KEYS = {"$comment", "policy", "dataset", "train", "runtime"}


# ---------------------------------------------------------------------------
# 配置校验（结构与默认值纪律：未知键=拼写漂移，拒绝）
# ---------------------------------------------------------------------------

def validate_train_cfg(cfg: dict[str, Any], *, where: str = "train config") -> None:
    """校验训练配置结构与取值域；不合法抛 ConfigError。"""
    unknown = set(cfg) - VALID_TOP_KEYS
    if unknown:
        raise ConfigError(f"{where}：未声明的顶层键 {sorted(unknown)}（拼写漂移即拒绝）")
    for key in ("policy", "dataset", "train", "runtime"):
        if key not in cfg or not isinstance(cfg[key], dict):
            raise ConfigError(f"{where}：缺少必需顶层键 {key!r}（object）")

    policy, dataset, train, runtime = cfg["policy"], cfg["dataset"], cfg["train"], cfg["runtime"]

    if policy.get("type") != "act":
        raise ConfigError(f"{where}:policy.type 必须为 'act'，实际 {policy.get('type')!r}")
    chunk, n_act = policy.get("chunk_size"), policy.get("n_action_steps")
    for name, v in (("chunk_size", chunk), ("n_action_steps", n_act)):
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise ConfigError(f"{where}:policy.{name} 必须为正整数，实际 {v!r}")
    if chunk < n_act:
        raise ConfigError(f"{where}:policy.chunk_size({chunk}) 必须 ≥ n_action_steps({n_act})")
    for name in ("kl_weight", "hidden_dim", "lr"):
        v = policy.get(name)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise ConfigError(f"{where}:policy.{name} 必须为正数，实际 {v!r}")
    if policy.get("lr_scheduler") != "cosine":
        raise ConfigError(f"{where}:policy.lr_scheduler 只支持 'cosine'，实际 {policy.get('lr_scheduler')!r}")
    if policy.get("amp") != "fp16":
        raise ConfigError(f"{where}:policy.amp 必须为 'fp16'（V100 sm_70 无 bf16），实际 {policy.get('amp')!r}")

    repo_id = dataset.get("repo_id")
    if not isinstance(repo_id, str) or not REPO_ID_RE.match(repo_id):
        raise ConfigError(f"{where}:dataset.repo_id 格式非法：{repo_id!r}")
    if dataset.get("fps") != 30:
        raise ConfigError(f"{where}:dataset.fps 必须为 30（录制协议），实际 {dataset.get('fps')!r}")
    cams = dataset.get("cams")
    if not isinstance(cams, list) or not cams or not set(cams) <= {"scene", "wrist"}:
        raise ConfigError(f"{where}:dataset.cams 必须为 ['scene','wrist'] 的非空子集，实际 {cams!r}")
    if dataset.get("action_dim") != N_ARM_JOINTS:
        raise ConfigError(
            f"{where}:dataset.action_dim 必须与 cs_schema.N_ARM_JOINTS({N_ARM_JOINTS}) 一致，"
            f"实际 {dataset.get('action_dim')!r}"
        )
    res = dataset.get("resolution")
    if res != [640, 480]:
        raise ConfigError(f"{where}:dataset.resolution 必须为 [640, 480]（录制协议），实际 {res!r}")

    for name in ("batch_size", "steps", "save_freq", "log_freq"):
        v = train.get(name)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise ConfigError(f"{where}:train.{name} 必须为正整数，实际 {v!r}")
    if not isinstance(train.get("num_workers"), int) or isinstance(train["num_workers"], bool) \
            or train["num_workers"] < 0:
        raise ConfigError(f"{where}:train.num_workers 必须为非负整数，实际 {train.get('num_workers')!r}")
    if not isinstance(train.get("seed"), int) or isinstance(train["seed"], bool):
        raise ConfigError(f"{where}:train.seed 必须为整数，实际 {train.get('seed')!r}")

    if runtime.get("wandb_enable") is not False:
        raise ConfigError(f"{where}:runtime.wandb_enable 必须为 false（离线红线）")
    out_dir = runtime.get("output_dir")
    if not isinstance(out_dir, str) or not out_dir:
        raise ConfigError(f"{where}:runtime.output_dir 必须为非空仓库相对路径")
    safe_rel_output(out_dir, field=f"{where}:runtime.output_dir")  # 禁绝对路径/.. 越界
    cmd = runtime.get("train_cmd")
    if cmd is not None and (not isinstance(cmd, str) or not cmd.strip()):
        raise ConfigError(f"{where}:runtime.train_cmd 为 null 或非空字符串，实际 {cmd!r}")


# ---------------------------------------------------------------------------
# 入口名解析与命令构造
# ---------------------------------------------------------------------------

def resolve_train_cmd(
    *,
    cli_value: str | None,
    local_config_path: Path | None,
    cfg: dict[str, Any],
) -> tuple[str | None, str]:
    """按优先级解析训练入口名，返回 (值或 None, 来源描述)。"""
    if cli_value and cli_value.strip():
        return cli_value.strip(), "--train-cmd"
    env = os.environ.get(ENV_TRAIN_CMD, "").strip()
    if env:
        return env, f"env {ENV_TRAIN_CMD}"
    if local_config_path is not None and Path(local_config_path).is_file():
        local = load_json(Path(local_config_path))
        v = local.get("train_cmd")
        if isinstance(v, str) and v.strip():
            return v.strip(), f"local config {local_config_path}"
    v = cfg.get("runtime", {}).get("train_cmd")
    if isinstance(v, str) and v.strip():
        return v.strip(), "config runtime.train_cmd"
    return None, "unresolved"


def build_flags(cfg: dict[str, Any]) -> list[str]:
    """由配置构造训练命令参数表（顺序稳定，便于 diff 与评审）。"""
    p, d, t, r = cfg["policy"], cfg["dataset"], cfg["train"], cfg["runtime"]
    return [
        f"--policy.type={p['type']}",
        f"--policy.chunk_size={p['chunk_size']}",
        f"--policy.n_action_steps={p['n_action_steps']}",
        f"--dataset.repo_id={d['repo_id']}",
        f"--output_dir={r['output_dir']}",
        f"--batch_size={t['batch_size']}",
        f"--steps={t['steps']}",
        f"--save_freq={t['save_freq']}",
        f"--log_freq={t['log_freq']}",
        "--wandb.enable=false",
    ]


def build_command(cfg: dict[str, Any], train_cmd: str, extra: list[str] | None = None) -> str:
    """拼出完整训练命令字符串（只返回字符串，绝不执行）。"""
    validate_train_cfg(cfg)
    parts = [train_cmd, *build_flags(cfg), *(extra or [])]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.act.build_train_cmd",
        description="策略训练命令生成器（只打印不执行；入口名运行期注入）",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="训练配置 JSON（缺省 train_act.json；消融组 B 用 train_act_ab.json）")
    parser.add_argument("--train-cmd", default=None,
                        help="训练框架 CLI 入口名（优先级最高；不入仓库）")
    parser.add_argument("--local-config", type=Path, default=DEFAULT_LOCAL_CONFIG,
                        help="本地覆盖文件（缺省 config/train.local.json，已 gitignore）")
    parser.add_argument("--extra", action="append", default=[],
                        help="追加到命令尾部的原样参数（可多次，如超参对读后的补充项）")
    parser.add_argument("--allow-placeholder", action="store_true",
                        help="入口名未注入时以占位符输出（仅供检阅，不可执行）")
    parser.add_argument("--out", type=Path, default=None,
                        help="生成结果落 JSON 报告路径（§10.2 规范；缺省只打印）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not Path(args.config).is_file():
        fail(f"训练配置不存在：{args.config}")
    try:
        cfg = load_json(args.config)
        validate_train_cfg(cfg, where=str(args.config))
    except ConfigError as exc:
        fail(str(exc))

    entry, source = resolve_train_cmd(
        cli_value=args.train_cmd, local_config_path=args.local_config, cfg=cfg,
    )
    if entry is None:
        if not args.allow_placeholder:
            print(
                "[training] 训练入口名未注入（命名纪律：不入仓库文本）。注入方式任选：\n"
                f"  1) --train-cmd <入口名>          2) 环境变量 {ENV_TRAIN_CMD}\n"
                "  3) 本地覆盖文件 --local-config 的 train_cmd 键\n"
                "  入口名见 GPU 机 chengshao/training/requirements-gpu.txt 所装依赖提供的 CLI\n"
                "  （检视配置效果可加 --allow-placeholder）。",
                file=sys.stderr,
            )
            return 2
        entry, source = PLACEHOLDER, "placeholder(--allow-placeholder)"

    command = build_command(cfg, entry, extra=list(args.extra))

    print("CMD:", command)
    print(f"SOURCE: {source}")
    print(f"CONFIG: {Path(args.config).resolve().as_posix()}")
    print("NOTE: 本生成器只打印命令；真实训练在 GPU 机执行（开发指令 §10.3）。")

    if args.out is not None:
        dump_json(args.out, {
            "module": _MODULE,
            "date": utc_now_iso(),
            "cmd": "python -m chengshao.training.act.build_train_cmd (见 out 内容 cmd 字段)",
            "metrics": {
                "generated_command": command,
                "entry_source": source,
                "entry_resolved": entry != PLACEHOLDER,
                "config": str(Path(args.config).resolve().as_posix()),
                "flags": build_flags(cfg),
            },
            "thresholds": {
                "wandb_enable": False,
                "amp": "fp16",
                "repo_root": REPO_ROOT.as_posix(),
            },
            "pass": True,
        })
        print(f"REPORT: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
