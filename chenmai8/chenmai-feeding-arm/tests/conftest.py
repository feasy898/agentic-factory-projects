"""pytest 根配置（仓库根 conftest）。

职责：
1) 兜底把仓库根加入 sys.path（pythonpath=. 之外的保险，任何 import 模式下可用）；
2) 各模块 eval（tests/test_*.py）跑完后，按开发指令 §10.2 的报告字段规范把
   证据 JSON 落到 chengshao/reports/（schema → schema_eval.json，
   food → food_interface_eval.json）。
   本钩子只在本次会话确实运行了对应用例时才写报告，不影响其他模块的 eval。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # conftest 位于 <仓库根>/tests/ 下
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# (用例前缀, 模块名, 报告文件名, 额外阈值说明)
_REPORTED = [
    ("tests/test_schema.py::", "cs_schema", "schema_eval.json",
     {"all_green": True, "negative_validation_cases_min": 12}),
    ("tests/test_food_interface.py::", "cs_food", "food_interface_eval.json",
     {"all_green": True, "synthetic_food_cases_min": 4, "synthetic_empty_cases_min": 4,
      "aruco_bowls_registered": 3}),
]


def pytest_terminal_summary(terminalreporter, exitstatus) -> None:  # noqa: ANN001
    """会话结束时按模块写出 eval 报告（仅当对应用例在本次会话中运行）。"""
    stats = terminalreporter.stats

    for prefix, module, filename, thresholds in _REPORTED:

        def _nodeids(status: str) -> list[str]:
            return [
                getattr(rep, "nodeid", "")
                for rep in stats.get(status, [])
                if getattr(rep, "nodeid", "").startswith(prefix)
            ]

        passed = _nodeids("passed")
        failed = _nodeids("failed")
        errors = _nodeids("error")
        if not (passed or failed or errors):
            continue  # 本次会话未运行该模块用例，不写报告

        report = {
            "module": module,
            "date": date.today().isoformat(),
            "cmd": ".venv/Scripts/python.exe -m pytest " + prefix.rstrip(":") + " -q  (cwd=仓库根)",
            "metrics": {
                "passed": len(passed),
                "failed": len(failed),
                "errors": len(errors),
                "exit_status": int(exitstatus),
            },
            "thresholds": thresholds,
            "pass": bool(passed) and not failed and not errors and int(exitstatus) == 0,
        }
        report_path = REPO_ROOT / "chengshao" / "reports" / filename
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        terminalreporter.section(f"{module} eval report -> {report_path.relative_to(REPO_ROOT)}")

    _dashboard_report(terminalreporter, stats, exitstatus)


# ---- cs_dashboard（T5）：业务指标来自 test_dashboard.DASH_METRICS -----------

_DASH_PREFIX = "tests/test_dashboard.py::"


def _dashboard_report(terminalreporter, stats: dict, exitstatus) -> None:  # noqa: ANN001
    """dashboard 报告：pytest 结果 + 业务指标（30 口无丢失/SSE/离线可开等）。"""

    def _nodeids(status: str) -> list[str]:
        return [
            getattr(rep, "nodeid", "")
            for rep in stats.get(status, [])
            if getattr(rep, "nodeid", "").startswith(_DASH_PREFIX)
        ]

    passed = _nodeids("passed")
    failed = _nodeids("failed")
    errors = _nodeids("error")
    if not (passed or failed or errors):
        return  # 本次会话未运行 dashboard 用例，不写报告

    # 业务指标由 tests/test_dashboard.py 的 DASH_METRICS 提供（缺失视作未达成）
    mod = sys.modules.get("test_dashboard")
    extra: dict = {}
    if mod is not None and hasattr(mod, "DASH_METRICS"):
        extra = dict(getattr(mod, "DASH_METRICS"))

    metrics = {
        "passed": len(passed),
        "failed": len(failed),
        "errors": len(errors),
        "exit_status": int(exitstatus),
        **extra,
    }
    thresholds = {
        "all_green": True,
        "bites_expected": 30,
        "bites_loss_allowed": 0,
        "page_http_status": 200,
        "sse_required": True,
        "offline_external_refs_allowed": 0,
    }
    pass_flag = (
        bool(passed)
        and not failed
        and not errors
        and int(exitstatus) == 0
        and extra.get("page_http_status") == 200
        and extra.get("static_assets_all_200") is True
        and extra.get("first_party_external_refs") == 0
        and extra.get("bites_posted") == 30
        and extra.get("bites_recorded") == 30
        and extra.get("aggregation_match") is True
        and extra.get("sse_snapshot_ok") is True
        and extra.get("sse_bite_delivered") is True
        and extra.get("invalid_rejected_422") is True
        and extra.get("conflicts_409") is True
        and extra.get("grams_total_check") is True
    )
    report = {
        "module": "cs_dashboard",
        "date": date.today().isoformat(),
        "cmd": ".venv/Scripts/python.exe -m pytest tests/test_dashboard.py -q  (cwd=仓库根)",
        "metrics": metrics,
        "thresholds": thresholds,
        "pass": bool(pass_flag),
    }
    report_path = REPO_ROOT / "chengshao" / "reports" / "dashboard_eval.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    terminalreporter.section(f"cs_dashboard eval report -> {report_path.relative_to(REPO_ROOT)}")
