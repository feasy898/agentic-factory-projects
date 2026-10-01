"""pfcore CLI — python -m pfcore <subcommand>。

命令名冻结（pipeline-contract §1/§2）：
- validate   已实现：spec 校验（glob 内建展开；全部文件过才 exit 0）。
- make       全流水线冻结名（占位 → exit 2；任何代码不得引入第三名，占位 `run` 已废）。
- build / pack / rules-check / serve   占位 → exit 2。

退出码：0 = 全部通过；1 = 判定失败（任一校验 issue）；2 = 用法错误 / 占位子命令。
stdout：validate 每个目标一行 JSON：{"file", "ok", "issues":[{path, message, code}]}，
最后一行汇总 {"summary": {"files", "failed"}}。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .validation import expand_targets

PROGRAM = "pfcore"


def _cmd_validate(args: argparse.Namespace) -> int:
    results = expand_targets(args.specs)
    failed = 0
    for display, issues in results:
        ok = not issues
        if not ok:
            failed += 1
        print(
            json.dumps(
                {"file": display, "ok": ok, "issues": issues},
                ensure_ascii=False,
            )
        )
    print(json.dumps({"summary": {"files": len(results), "failed": failed}}, ensure_ascii=False))
    return 0 if failed == 0 else 1


def _make_placeholder(name: str):
    def _run(_args: argparse.Namespace) -> int:
        print(
            f"{PROGRAM}: subcommand '{name}' is a frozen-name placeholder "
            f"(pipeline-contract §1); not implemented in this pilot (exit 2).",
            file=sys.stderr,
        )
        return 2

    return _run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="PlayableSpec toolchain (regen pilot): validate is implemented; "
        "make/build/pack/rules-check/serve are frozen-name placeholders (exit 2).",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_validate = sub.add_parser(
        "validate",
        help="validate PlayableSpec file(s); globs expanded internally; "
        "exit 0 only if every target passes",
    )
    p_validate.add_argument("specs", nargs="+", metavar="spec", help="spec file path or glob pattern")
    p_validate.set_defaults(func=_cmd_validate)

    # 冻结名占位（exit 2）：全流水线 = make（run 已废除，不得回归）
    for name in ("make", "build", "pack", "rules-check", "serve"):
        p = sub.add_parser(name, help=f"frozen-name placeholder (not implemented; exits 2)")
        p.set_defaults(func=_make_placeholder(name))

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_usage(sys.stderr)
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
