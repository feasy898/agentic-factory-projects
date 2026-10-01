"""qacore 重生成试点 gate（供工作流调用；透传测试退出码）。

门项依据 SPEC.md（= docs/assets/specs/qacore.md）：
  G1 金标层（§7）：python -m qacore run python/qacore/tests/fixtures/mini.html
     --channel preview --autoplay → exit 0；报告 checks 非空、0 fail；
     已实装项（CHK01/03/04/05/07/08/09）零 skip（skip 不算过）、CHK03/08/09 必须 pass、
     pf:end ≤ 45000ms。
  G2 MUT-01 外链资源（§8）：外链 <img> → exit 1 且 fail 集合恰为 {CHK03}；CHK05/07/08 不受扰。
  G3 MUT-02 未静音（§8）：初始 muted=false → exit 1 且 fail 集合恰为 {CHK04}；CHK07 不受扰。
  G4 MUT-04 超体积（§8）：尾部注入垃圾字节 > maxBytes → exit 1 且 fail 集合恰为 {CHK01}。
  G5 退出码契约（§2）：产物不存在 → exit 2；非 .html 后缀 → exit 2。
  +  夹具冻结自检：mini.html sha256 全程不变（测试一字不改）。
MUT-03（结束页不可达）依 SPEC §8 实装状态不进本 gate（列 M8 全量里程碑）。

用法：python gate.py   → 退出码 0 = 全绿；1 = 任一门项失败。
纪律：先清旧产物再跑（报告/截屏/变异样本的存在 = 本次运行的真事实）。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(ROOT, "python", "qacore", "tests", "fixtures", "mini.html")
FIXTURE_REL = os.path.relpath(FIXTURE, ROOT)
FIXTURE_SHA256 = "72060c3062846f8fcb2cf621482ff99e0e3f5079bcb912a7dba2b5bd718bd0da"
TMP = os.path.join(ROOT, "tmp", "gate")
VENV_PY = os.path.join(ROOT, "python", ".venv", "Scripts", "python.exe")
PREVIEW_MAX_BYTES = 5242880

IMPLEMENTED = ["CHK01", "CHK03", "CHK04", "CHK05", "CHK07", "CHK08", "CHK09"]
ALL_IDS = [f"CHK{i:02d}" for i in range(1, 11)]

_failures = []


def _py():
    return VENV_PY if os.path.isfile(VENV_PY) else sys.executable


def _run_qacore(*cli_args, timeout=150):
    env = {**os.environ, "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [_py(), "-m", "qacore", "run", *cli_args],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return proc


def _load_report(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _check_map(report):
    return {c["id"]: c["status"] for c in report.get("checks", [])}


def _record(gate, ok, problems):
    tag = "PASS" if ok else "FAIL"
    print(f"[{gate}] {tag}" + (f" —— {'；'.join(problems)}" if problems else ""))
    if not ok:
        _failures.append(gate)


def _assert_fail_set(checks, expect_fail_ids, extra_expect_pass=()):
    """恰命中断言：fail 集合 == expect_fail_ids；extra_expect_pass 逐项核对。"""
    problems = []
    fail_set = {cid for cid, st in checks.items() if st == "fail"}
    if fail_set != set(expect_fail_ids):
        problems.append(f"fail 集合 {sorted(fail_set)} ≠ 预期 {sorted(expect_fail_ids)}")
    for cid in extra_expect_pass:
        if checks.get(cid) != "pass":
            problems.append(f"{cid} 应 pass 实为 {checks.get(cid)}（不受扰被破坏）")
    return problems


def _frozen_ok():
    h = hashlib.sha256(open(FIXTURE, "rb").read()).hexdigest()
    return h == FIXTURE_SHA256, h


def _clean_stale():
    """先清旧产物再跑：夹具旁的运行产物 + gate tmp。"""
    for name in ("mini.report.json", "mini.png", "mini-landscape.png"):
        p = os.path.join(os.path.dirname(FIXTURE), name)
        if os.path.exists(p):
            os.remove(p)
    if os.path.isdir(TMP):
        shutil.rmtree(TMP)
    os.makedirs(TMP, exist_ok=True)


def gate1_golden():
    proc = _run_qacore(FIXTURE_REL, "--channel", "preview", "--autoplay")
    report_path = os.path.join(os.path.dirname(FIXTURE), "mini.report.json")
    if proc.returncode != 0:
        _record("G1 金标层", False, [f"exit={proc.returncode}（预期 0）stderr={proc.stderr[-400:]}"])
        return
    if not os.path.isfile(report_path):
        _record("G1 金标层", False, ["报告未生成"])
        return
    report = _load_report(report_path)
    checks = _check_map(report)
    problems = []
    if len(checks) != 10:
        problems.append(f"checks 数 {len(checks)} ≠ 10")
    if any(c["status"] == "fail" for c in report["checks"]):
        problems.append("存在 fail：" + str([c['id'] for c in report['checks'] if c['status'] == 'fail']))
    for cid in IMPLEMENTED:
        if checks.get(cid) != "pass":
            problems.append(f"已实装项 {cid} 应 pass 零 skip，实为 {checks.get(cid)}")
    for cid in ("CHK02", "CHK06", "CHK10"):
        if checks.get(cid) != "skip":
            problems.append(f"{cid} 应 skip（夹具无对应钩子），实为 {checks.get(cid)}")
    end_ms = (report.get("pf") or {}).get("endMs")
    if not isinstance(end_ms, (int, float)) or end_ms > 45000:
        problems.append(f"pf:end={end_ms}ms 超预算/缺失（≤45000ms）")
    shot = report.get("screenshot")
    if not shot or not os.path.isfile(os.path.join(os.path.dirname(FIXTURE), shot)):
        problems.append(f"竖屏截屏缺失：{shot}")
    if not os.path.isfile(os.path.join(os.path.dirname(FIXTURE), "mini-landscape.png")):
        problems.append("横屏截屏缺失")
    _record("G1 金标层", not problems, problems)


def gate2_mut01_external():
    """MUT-01 外链资源：追加外链 <img> → 恰 CHK03 fail；CHK05/07/08 不受扰。"""
    src = open(FIXTURE, encoding="utf-8").read()
    mut = src.replace("</body>", '  <img src="https://cdn.example/x.png" alt="mut">\n</body>')
    assert "cdn.example" in mut, "变异构造失败"
    path = os.path.join(TMP, "mut01.html")
    open(path, "w", encoding="utf-8", newline="").write(mut)
    proc = _run_qacore(path, "--channel", "preview", "--autoplay")
    report_path = os.path.join(TMP, "mut01.report.json")
    if proc.returncode != 1:
        _record("G2 MUT-01 外链", False, [f"exit={proc.returncode}（预期 1）"])
        return
    problems = _assert_fail_set(_check_map(_load_report(report_path)),
                                ["CHK03"], extra_expect_pass=("CHK05", "CHK07", "CHK08"))
    _record("G2 MUT-01 外链", not problems, problems)


def gate3_mut02_unmuted():
    """MUT-02 未静音：初始 muted=false → 恰 CHK04 fail；CHK07 不受扰。"""
    src = open(FIXTURE, encoding="utf-8").read()
    assert "let muted = true;" in src, "夹具缺少预期静音语句，变异构造失败"
    mut = src.replace("let muted = true;", "let muted = false;")
    path = os.path.join(TMP, "mut02.html")
    open(path, "w", encoding="utf-8", newline="").write(mut)
    proc = _run_qacore(path, "--channel", "preview", "--autoplay")
    report_path = os.path.join(TMP, "mut02.report.json")
    if proc.returncode != 1:
        _record("G3 MUT-02 未静音", False, [f"exit={proc.returncode}（预期 1）"])
        return
    problems = _assert_fail_set(_check_map(_load_report(report_path)),
                                ["CHK04"], extra_expect_pass=("CHK07",))
    _record("G3 MUT-02 未静音", not problems, problems)


def gate4_mut04_oversize():
    """MUT-04 超体积：尾部注入垃圾字节使包体 > preview maxBytes → 恰 CHK01 fail。"""
    src = open(FIXTURE, encoding="utf-8").read()
    garbage = "<!--" + "A" * (PREVIEW_MAX_BYTES + 1024) + "-->"
    path = os.path.join(TMP, "mut04.html")
    open(path, "w", encoding="utf-8", newline="").write(src + "\n" + garbage)
    assert os.path.getsize(path) > PREVIEW_MAX_BYTES, "变异未超限"
    proc = _run_qacore(path, "--channel", "preview", "--autoplay")
    report_path = os.path.join(TMP, "mut04.report.json")
    if proc.returncode != 1:
        _record("G4 MUT-04 超体积", False, [f"exit={proc.returncode}（预期 1）"])
        return
    problems = _assert_fail_set(_check_map(_load_report(report_path)),
                                ["CHK01"], extra_expect_pass=tuple(IMPLEMENTED[1:]))
    _record("G4 MUT-04 超体积", not problems, problems)


def gate5_exit_codes():
    proc_missing = _run_qacore(os.path.join(TMP, "no-such.html"))
    non_html = os.path.join(TMP, "not-html.zip")
    shutil.copyfile(FIXTURE, non_html)
    proc_zip = _run_qacore(non_html)
    problems = []
    if proc_missing.returncode != 2:
        problems.append(f"产物不存在 exit={proc_missing.returncode}（预期 2）")
    if proc_zip.returncode != 2:
        problems.append(f"非 .html exit={proc_zip.returncode}（预期 2）")
    _record("G5 退出码契约", not problems, problems)


FIXTURE_REL = os.path.relpath(FIXTURE, ROOT)


def main() -> int:
    ok, got = _frozen_ok()
    if not ok:
        print(f"[FROZEN] FAIL —— mini.html sha256 变化：{got}")
        return 1
    print(f"[FROZEN] PASS —— mini.html sha256 未变（{FIXTURE_SHA256[:12]}…）")
    _clean_stale()
    gate1_golden()
    gate2_mut01_external()
    gate3_mut02_unmuted()
    gate4_mut04_oversize()
    gate5_exit_codes()
    ok2, got2 = _frozen_ok()
    if not ok2:
        _failures.append("FROZEN-AFTER")
        print(f"[FROZEN-AFTER] FAIL —— gate 结束后夹具被改动：{got2}")
    total, bad = 6, len(_failures)
    print(f"QACORE PILOT GATE: {'PASS' if bad == 0 else 'FAIL'} ({total - bad}/{total})")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
