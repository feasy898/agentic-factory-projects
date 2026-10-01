#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
env_guard.py — PreToolUse 安全护栏：禁止 Claude 对 .env / .env.* 文件做任何写操作。

事件   : PreToolUse（任何工具执行前触发；此时拦截 = 工具根本不会执行）
匹配   : matcher "Write|Edit"（配置见 OUT.md）；脚本内再做一次 tool_name 双重校验
输入   : stdin 收到的 hook JSON，取 tool_input.file_path 判断目标文件
命中   : 目标是 .env 或 .env.* 变体（.env.local / .env.production / .env.20260929.bak ...）
         -> stderr 输出原因，退出码 2 = 阻断本次工具调用（stderr 自动反馈给 Claude）
未命中 -> 退出码 0 = 放行，工具正常执行
风格   : 参照 disler/claude-code-hooks-mastery 的 UV 单文件脚本——仅用 Python 标准库，
         无第三方依赖，`uv run` 或任意 python3 均可直接执行。
"""
import json
import sys

# 双重校验：即使配置 matcher 写漏，脚本也只对写类工具生效（读工具不受影响）
GUARDED_TOOLS = {"Write", "Edit"}
# Write / Edit 工具的目标路径字段；notebook_path 顺带覆盖，防御字段改名
PATH_FIELDS = ("file_path", "notebook_path", "path")
# 豁免名单（按需自行放开，例如把 .env.example 视为可写模板）：
# EXEMPT = {".env.example"}
EXEMPT = set()


def basename_of(raw_path: str) -> str:
    """取路径最后一段文件名；统一反斜杠/正斜杠，去空白与引号。"""
    path = raw_path.strip().strip('"').strip("'").replace("\\", "/")
    return path.rstrip("/").split("/")[-1]


def is_env_file(raw_path: str) -> bool:
    """命中规则：文件名 == '.env'，或以 '.env.' 开头的变体。Windows 大小写不敏感，故一律 lower。"""
    name = basename_of(raw_path).lower()
    if name in EXEMPT:
        return False
    return name == ".env" or name.startswith(".env.")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        # 输入损坏时放行（fail-open），但向用户留痕；改成 sys.exit(2) 即为 fail-closed。
        print(f"env_guard: 无法解析 hook 输入（{exc}），本次放行", file=sys.stderr)
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in GUARDED_TOOLS:
        return 0  # 与本护栏无关的工具，直接放行

    tool_input = payload.get("tool_input") or {}
    for field in PATH_FIELDS:
        target = tool_input.get(field)
        if isinstance(target, str) and is_env_file(target):
            print(
                f"BLOCKED: 已拦截对环境变量文件 '{target}' 的 {tool_name} 写操作。"
                f"原因：.env 及其变体（.env.*）通常含密钥/生产凭据，属敏感文件，"
                f"本护栏禁止 AI 直接改写，防止泄露或误改生产配置。"
                f"如确需变更，请由用户手工编辑，或在 env_guard.py 的 EXEMPT 中显式豁免。",
                file=sys.stderr,
            )
            sys.exit(2)  # 阻断工具调用，stderr 原因自动反馈给 Claude

    return 0  # 未命中：放行，工具照常执行


if __name__ == "__main__":
    sys.exit(main())
