"""pytest 根配置（仓库根 conftest）。

职责：
1) 兜底把仓库根加入 sys.path（pythonpath=. 之外的保险，任何 import 模式下可用）；
2) cs_schema 的 eval（tests/test_schema.py）跑完后，按开发指令 §10.2 的报告字段
   规范把证据 JSON 落到 chengshao/reports/schema_eval.json。
   本钩子只在本次会话确实运行了 schema 用例时才写报告，不影响其他模块的 eval。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # conftest 位于 <仓库根>/tests/ 下
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_TEST_PREFIX = "tests/test_schema.py::"
REPORT_PATH = REPO_ROOT / "chengshao" / "reports" / "schema_eval.json"


def pytest_terminal_summary(terminalreporter, exitstatus) -> None:  # noqa: ANN001
    """会话结束时写出 schema eval 报告（仅当 schema 用例在本次会话中运行）。"""
    stats = terminalreporter.stats

    def _nodeids(status: str) -> list[str]:
        return [
            getattr(rep, "nodeid", "")
            for rep in stats.get(status, [])
            if getattr(rep, "nodeid", "").startswith(SCHEMA_TEST_PREFIX)
        ]

    passed = _nodeids("passed")
    failed = _nodeids("failed")
    errors = _nodeids("error")
    if not (passed or failed or errors):
        return  # 本次会话未运行 schema 用例，不写报告

    report = {
        "module": "cs_schema",
        "date": date.today().isoformat(),
        "cmd": ".venv/Scripts/python.exe -m pytest tests/test_schema.py -q  (cwd=仓库根)",
        "metrics": {
            "passed": len(passed),
            "failed": len(failed),
            "errors": len(errors),
            "exit_status": int(exitstatus),
        },
        "thresholds": {
            "all_green": True,
            "negative_validation_cases_min": 12,
        },
        "pass": bool(passed) and not failed and not errors and int(exitstatus) == 0,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    terminalreporter.section(f"schema eval report -> {REPORT_PATH.relative_to(REPO_ROOT)}")
