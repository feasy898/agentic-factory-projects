"""M0 基础设施验收：安装自检 + 配置加载 + 名称守卫 + 契约模型序列化往返。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m0_infra

exit 0 = 通过。检查项：
1. 运行于仓库 venv；``pip install -e .`` 生效（本项目发行版元数据存在）；
2. 主依赖与扩展组（dev/ocr/ml）全部可导入，版本钉子匹配 config/install_check.json；
3. config/app.yaml 加载 + 字段契约 + ANONGW_* 环境覆盖 + 密钥解析 + .env 加载；
4. config/dept_keys.yaml：3 个部门、sha256 格式合法；
5. ops/name_lint.py 全仓零命中（标准档），词表非空；
6. constraints.txt 存在且为 pip freeze 形态；.env.example/.gitignore 卫生；
7. §5 冻结契约六件（recognizers/routing/masking/audit/filechannel/gateway 的
   models.py）：字段名与 §5 一字不差、§5 示例 JSON 逐字可解析、序列化往返全等、
   UTC Z 时间戳、审计事件零 raw、枚举/字面量值域与边界约束生效；
   另对全部契约模型做未知字段拒绝负例（删掉 extra="forbid" 必须变红，审查 §C）。
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.config import (  # noqa: E402
    load_app_config,
    load_dept_keys,
    load_env_file,
    resolve_secret,
)
from ops import name_lint  # noqa: E402

INSTALL_CHECK = REPO_ROOT / "config" / "install_check.json"
RESULTS: list[tuple[bool, str]] = []


def _record(name: str, fn):
    try:
        detail = fn()
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _load_install_check() -> dict[str, Any]:
    data = json.loads(INSTALL_CHECK.read_text(encoding="utf-8"))
    for group in ("main", "extras"):
        if not data.get(group):
            raise ValueError(f"install_check missing group {group!r}")
    return data


def _version_matches(version: str, spec: str) -> bool:
    """spec 形如 '10.14.*' / '40.*'：按点分段前缀匹配。"""
    prefix = spec.replace(".*", "").split(".")
    actual = version.split(".")
    return len(actual) >= len(prefix) and actual[: len(prefix)] == prefix


def _version_at_least(version: str, floor: str) -> bool:
    def nums(v: str) -> list[int]:
        out = []
        for part in v.split(".")[: len(floor.split("."))]:
            digits = "".join(ch for ch in part if ch.isdigit())
            out.append(int(digits or 0))
        return out

    return nums(version) >= nums(floor)


# ── 1. 安装自检 ────────────────────────────────────────────────────
def check_venv() -> str:
    running = Path(sys.executable).resolve()
    expected = (REPO_ROOT / ".venv" / "Scripts" / "python.exe").resolve()
    if running != expected:
        raise AssertionError(f"not running under repo venv: {running}")
    return str(running)


def check_self_install() -> str:
    md.version("gov-anon-gateway")  # 未安装则 PackageNotFoundError
    for pkg in ("common", "ops", "evals"):
        importlib.import_module(pkg)
    return "editable install + project packages importable"


def check_deps(group: str):
    entries = _load_install_check()[group]

    def run() -> str:
        problems: list[str] = []
        versions: list[str] = []
        for entry in entries:
            dist = entry["dist"]
            try:
                ver = md.version(dist)
            except md.PackageNotFoundError:
                problems.append(f"{dist}: not installed")
                continue
            if "pin" in entry and not _version_matches(ver, entry["pin"]):
                problems.append(f"{dist}=={ver} !~ {entry['pin']}")
            if "min" in entry and not _version_at_least(ver, entry["min"]):
                problems.append(f"{dist}=={ver} < {entry['min']}")
            if "import" in entry:
                try:
                    importlib.import_module(entry["import"])
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"import {entry['import']}: {type(exc).__name__}: {exc}")
            versions.append(f"{dist}=={ver}")
        if problems:
            raise AssertionError("; ".join(problems))
        return f"{len(entries)} dists ok ({'; '.join(versions)})"

    return run


# ── 2. 配置加载 ────────────────────────────────────────────────────
def check_app_config() -> str:
    cfg = load_app_config()
    assert cfg.listen == 9000, f"listen={cfg.listen}"
    assert cfg.mask_key_env == "MASK_KEY"
    assert cfg.session_ttl_h == 24, f"session_ttl_h={cfg.session_ttl_h}"
    assert len(cfg.upstreams) >= 2, "need >=2 upstreams"
    routes = set()
    for upstream in cfg.upstreams:
        assert upstream.name and upstream.base_url and upstream.api_key_env
        assert upstream.models, f"{upstream.name}: empty models"
        assert upstream.route in {"INTERNET", "GOVCLOUD", "BLOCK"}
        routes.add(upstream.route)
    assert {"INTERNET", "GOVCLOUD"} <= routes, f"routes={routes}"
    assert cfg.ai_label, "ai_label empty"
    assert cfg.thresholds.batch_pii_to_govcloud == 3
    names = ",".join(u.name for u in cfg.upstreams)
    return f"listen={cfg.listen}, upstreams=[{names}], ai_label={cfg.ai_label!r}"


def check_env_override() -> str:
    injected = load_app_config(env={"ANONGW_LISTEN": "9100", "ANONGW_SESSION_TTL_H": "48"})
    assert injected.listen == 9100 and injected.session_ttl_h == 48
    label_case = load_app_config(env={"ANONGW_AI_LABEL": "测试标识"})
    assert label_case.ai_label == "测试标识"
    untouched = load_app_config(env={})
    assert untouched.listen == 9000 and untouched.session_ttl_h == 24

    key = "ANONGW_LISTEN"
    old = os.environ.get(key)
    os.environ[key] = "9200"
    try:
        assert load_app_config().listen == 9200, "os.environ override not applied"
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old
    return "ANONGW_* overrides apply (int + str), no cross-contamination"


def check_secrets() -> str:
    assert resolve_secret("M0_PROBE_SECRET", env={"M0_PROBE_SECRET": "abc"}) == "abc"
    assert resolve_secret("M0_PROBE_SECRET", env={}, required=False) is None
    try:
        resolve_secret("M0_PROBE_SECRET", env={})
    except RuntimeError:
        pass
    else:
        raise AssertionError("missing required secret did not raise")
    return "resolve_secret ok (present/optional/required-missing)"


def check_env_file() -> str:
    probe_dir = REPO_ROOT / "data"
    probe_dir.mkdir(exist_ok=True)
    probe = probe_dir / "m0_envfile_probe.env"
    probe.write_text("# comment\nM0_ENVFILE_PROBE=hello\n", encoding="utf-8")
    try:
        os.environ.pop("M0_ENVFILE_PROBE", None)
        loaded = load_env_file(probe)
        assert loaded == ["M0_ENVFILE_PROBE"], loaded
        assert os.environ.get("M0_ENVFILE_PROBE") == "hello"
        os.environ["M0_ENVFILE_PROBE"] = "keep-me"
        loaded2 = load_env_file(probe, override=False)
        assert loaded2 == [] and os.environ["M0_ENVFILE_PROBE"] == "keep-me"
    finally:
        os.environ.pop("M0_ENVFILE_PROBE", None)
        probe.unlink(missing_ok=True)
    return "load_env_file ok (parse / no-override)"


def check_dept_keys() -> str:
    departments = load_dept_keys()
    assert len(departments) == 3, f"expect 3 departments, got {len(departments)}"
    for dept, digest in departments.items():
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), dept
    return "3 departments, sha256 digests valid"


# ── 3. 名称守卫 ────────────────────────────────────────────────────
def check_name_lint() -> str:
    violations, scanned = name_lint.lint_repo(REPO_ROOT)
    assert not violations, "; ".join(f"{r}:{l}:{t}" for r, l, t in violations[:20])
    wordlist = (REPO_ROOT / "ops" / "forbidden_names.txt").read_text(encoding="utf-8")
    entries = [ln for ln in wordlist.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert len(entries) >= 10, f"wordlist too small: {len(entries)}"
    return f"{scanned} files scanned, 0 violations, {len(entries)} patterns"


def check_env_example_and_gitignore() -> str:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("MASK_KEY=", "MOCK_KEY="):
        assert key in env_example, f"missing {key} in .env.example"
    assert "UPSTREAM_" in env_example, "missing UPSTREAM_*_KEY placeholder"
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore and "!.env.example" in gitignore, ".gitignore must ignore .env but keep .env.example"
    return ".env.example placeholders + .gitignore exception ok"


def check_constraints() -> str:
    path = REPO_ROOT / "constraints.txt"
    assert path.exists(), "constraints.txt missing (run: pip freeze > constraints.txt)"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 20, f"constraints.txt too thin: {len(lines)} lines"
    assert not any(ln.startswith(("-e ", "common")) for ln in lines), "constraints must be pure freeze (no -e lines)"
    return f"{len(lines)} pinned distributions"


# ── 4. §5 冻结契约：序列化往返（T0.2）────────────────────────────
# §5 原文示例 JSON（逐字解析 = 契约兼容性的最直接证据）
FINDING_JSON = (
    '{"fid":"f_0001","type":"ID_CARD","layer":"rule","start":12,"end":26,'
    '"raw":"460022199003071234","normalized":"460022199003071234",'
    '"confidence":1.0,"whitelisted":false,"action_hint":"MASK"}'
)
ROUTE_DECISION_JSON = (
    '{"route":"INTERNET",'
    '"reasons":[{"code":"CLASSIFICATION_MARK","fid":"f_0007","detail":"命中 机密★"}],'
    '"upstream":"govcloud_local","mask_required":true,"labels":{"ai_generated":true}}'
)
MAPPING_ENTRY_JSON = (
    '{"placeholder":"〔手机号·9a1b2c3d〕","type":"PHONE_MOBILE",'
    '"normalized":"13800138000","first_seen":"2026-09-28T03:00:00Z",'
    '"session_id":"sess_demo","preserve_semantic":false}'
)
AUDIT_EVENT_JSON = (
    '{"ts":"2026-09-28T03:00:00Z","request_id":"req_a1","session_id":"sess_demo",'
    '"dept":"民政局","route":"GOVCLOUD","blocked":false,'
    '"reasons":["SENSITIVE_ATTR"],"class_counts":{"ID_CARD":2,"PHONE_MOBILE":3},'
    '"prompt_preview":"〔人名·7f3a2b1c〕提交的〔身份证·…〕…","response_preview":"…",'
    '"upstream":"govcloud_local","latency_ms":812,"flags":[]}'
)
FILE_REPORT_JSON = (
    '{"file_id":"file_demo","filename":"低保公示.pdf","sha256":"deadbeef",'
    '"kind":"pdf","pages":3,"findings":[{"page":1,"bbox":[10.0,20.0,110.0,40.0],'
    '"finding":' + FINDING_JSON + '}],'
    '"risk_level":"HIGH","summary":{"ID_CARD":12,"PERSON":30}}'
)
API_ERROR_JSON = (
    '{"error":{"code":"content_blocked",'
    '"message":"涉密/涉敏内容已拦截，请通过保密渠道办理",'
    '"reasons":[{"code":"CLASSIFICATION_MARK","fid":"f_0007","detail":"命中 机密★"}]}}'
)


def _pin_fields(model_cls, expected: set[str]) -> None:
    actual = set(model_cls.model_fields)
    if actual != expected:
        raise AssertionError(
            f"{model_cls.__name__} contract drift:"
            f" added={sorted(actual - expected)} removed={sorted(expected - actual)}"
        )


def _roundtrip(model_cls, payload_json: str):
    """§5 示例 JSON 逐字解析 → 序列化 → 再解析，两次结果必须全等。"""
    obj = model_cls.model_validate_json(payload_json)
    again = model_cls.model_validate_json(obj.model_dump_json())
    if again != obj:
        raise AssertionError(f"{model_cls.__name__} serialization round-trip mismatch")
    return obj


def _must_raise(fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 — 期望路径：契约校验拒绝非法输入
        return
    raise AssertionError(f"expected validation error, but {fn} succeeded")


def check_entity_catalog() -> str:
    rm = importlib.import_module("recognizers.models")
    expected = [
        "PERSON", "ADDRESS", "ID_CARD", "PHONE_MOBILE", "PHONE_LANDLINE",
        "BANK_CARD", "USCC", "PLATE", "EMAIL", "IP", "SECRET_KEY", "DATE_BIRTH",
        "SENSITIVE_ATTR", "WORK_SECRET", "CLASSIFICATION_MARK", "INJECTION",
        "ORG_INTERNAL", "DOC_NUMBER", "OTHER",
    ]
    actual = [m.value for m in rm.EntityClass]
    assert actual == expected, f"EntityClass drifted: {actual}"
    labels = [m.label for m in rm.EntityClass]
    assert all(labels) and len(set(labels)) == len(labels), f"labels not unique: {labels}"
    subtypes = {"病症", "残障", "低保特困", "社区矫正", "信访人",
                "金融账户", "行踪轨迹", "犯罪记录", "特定身份"}
    assert set(rm.SENSITIVE_ATTR_SUBTYPES) == subtypes
    return f"{len(expected)} entity classes, labels unique, 9 sensitive-attr subtypes"


def check_finding_contract() -> str:
    rm = importlib.import_module("recognizers.models")
    f_cls = rm.Finding
    _pin_fields(f_cls, {"fid", "type", "layer", "start", "end", "raw", "normalized",
                        "subtype", "confidence", "whitelisted", "action_hint"})
    f = _roundtrip(f_cls, FINDING_JSON)
    assert f.type is rm.EntityClass.ID_CARD and f.type.label == "身份证"
    assert (f.start, f.end) == (12, 26) and f.confidence == 1.0 and not f.whitelisted
    _must_raise(lambda: f_cls(fid="f_x", type=rm.EntityClass.ID_CARD, start=10, end=5))
    _must_raise(lambda: f_cls(fid="f_x", type=rm.EntityClass.ID_CARD, layer="llm"))
    _must_raise(lambda: f_cls(fid="f_x", type=rm.EntityClass.ID_CARD, action_hint="DROP"))
    _must_raise(lambda: f_cls(fid="f_x", type=rm.EntityClass.ID_CARD, subtype="低保特困"))
    _must_raise(lambda: f_cls(fid="f_x", type=rm.EntityClass.SENSITIVE_ATTR, subtype="不存在的子类"))
    ok = f_cls(fid="f_x", type=rm.EntityClass.SENSITIVE_ATTR, subtype="低保特困")
    assert ok.subtype == "低保特困"
    return "Finding: §5.1 JSON round-trip + span/layer/hint/subtype guards"


def check_route_contract() -> str:
    rt = importlib.import_module("routing.models")
    _pin_fields(rt.RouteReason, {"code", "fid", "detail"})
    _pin_fields(rt.RouteDecision, {"route", "reasons", "upstream", "mask_required", "labels"})
    d = _roundtrip(rt.RouteDecision, ROUTE_DECISION_JSON)
    assert d.route == "INTERNET" and d.upstream == "govcloud_local" and d.mask_required is True
    assert d.reasons[0].code == "CLASSIFICATION_MARK" and d.reasons[0].fid == "f_0007"
    assert d.labels == {"ai_generated": True}
    blk = rt.RouteDecision(route="BLOCK", reasons=[rt.RouteReason(code="INJECTION")])
    assert blk.upstream is None, "BLOCK must carry upstream=null"
    _must_raise(lambda: rt.RouteDecision(route="BLOCK", upstream="govcloud_local"))
    _must_raise(lambda: rt.RouteDecision(route="INTRANET"))
    return "RouteDecision: §5.2 JSON round-trip + BLOCK/upstream guard"


def check_mapping_contract() -> str:
    mm = importlib.import_module("masking.models")
    rm = importlib.import_module("recognizers.models")
    m_cls = mm.MappingEntry
    _pin_fields(m_cls, {"placeholder", "type", "normalized", "first_seen", "session_id",
                        "preserve_semantic"})
    e = _roundtrip(m_cls, MAPPING_ENTRY_JSON)
    assert e.type is rm.EntityClass.PHONE_MOBILE and e.normalized == "13800138000"
    assert '"first_seen":"2026-09-28T03:00:00Z"' in e.model_dump_json()
    naive = m_cls(placeholder="〔人名·7f3a2b1c〕", type="PERSON", normalized="张三",
                  first_seen="2026-09-28T03:00:00", session_id="sess_b")
    assert '"first_seen":"2026-09-28T03:00:00Z"' in naive.model_dump_json(), "naive ts must coerce to UTC"
    return "MappingEntry: §5.3.3 JSON round-trip + UTC Z timestamps"


def check_audit_contract() -> str:
    am = importlib.import_module("audit.models")
    a_cls = am.AuditEvent
    _pin_fields(a_cls, {"ts", "request_id", "session_id", "dept", "route", "blocked",
                        "reasons", "class_counts", "prompt_preview", "response_preview",
                        "upstream", "latency_ms", "flags"})
    assert "raw" not in a_cls.model_fields, "AuditEvent must never carry raw"
    ev = _roundtrip(a_cls, AUDIT_EVENT_JSON)
    assert ev.dept == "民政局" and ev.blocked is False and ev.latency_ms == 812
    assert ev.class_counts == {"ID_CARD": 2, "PHONE_MOBILE": 3}
    assert '"ts":"2026-09-28T03:00:00Z"' in ev.model_dump_json()
    _must_raise(lambda: a_cls(ts="2026-09-28T03:00:00Z", prompt_preview="密" * 501))
    _must_raise(lambda: a_cls(ts="2026-09-28T03:00:00Z", response_preview="答" * 501))
    ok = a_cls(ts="2026-09-28T03:00:00Z", prompt_preview="密" * 500)
    assert len(ok.prompt_preview) == 500
    return "AuditEvent: §5.4 JSON round-trip, no-raw, preview<=500"


def check_file_report_contract() -> str:
    fm = importlib.import_module("filechannel.models")
    rm = importlib.import_module("recognizers.models")
    _pin_fields(fm.FileFinding, {"page", "bbox", "location", "finding"})
    _pin_fields(fm.FileReport, {"file_id", "filename", "sha256", "kind", "pages",
                                "findings", "risk_level", "summary"})
    rep = _roundtrip(fm.FileReport, FILE_REPORT_JSON)
    assert rep.risk_level == "HIGH" and rep.summary == {"ID_CARD": 12, "PERSON": 30}
    assert rep.findings[0].bbox == (10.0, 20.0, 110.0, 40.0)
    assert rep.findings[0].finding.type is rm.EntityClass.ID_CARD
    _must_raise(lambda: fm.FileFinding(page=1, bbox=(1.0, 2.0, 3.0),
                                       finding={"fid": "f_9", "type": "EMAIL"}))
    _must_raise(lambda: fm.FileReport(kind="txt"))
    _must_raise(lambda: fm.FileReport(risk_level="EXTREME"))
    return "FileReport: §5.5 JSON round-trip + nested Finding + bbox-4 guard"


def check_api_error_contract() -> str:
    gm = importlib.import_module("gateway.models")
    _pin_fields(gm.ErrorBody, {"code", "message", "reasons"})
    _pin_fields(gm.ApiError, {"error"})
    ae = _roundtrip(gm.ApiError, API_ERROR_JSON)
    assert ae.error.code == "content_blocked"
    assert ae.error.reasons[0].code == "CLASSIFICATION_MARK"
    wire = json.loads(ae.model_dump_json())
    assert set(wire) == {"error"} and set(wire["error"]) == {"code", "message", "reasons"}
    built = gm.ApiError.content_blocked("涉密/涉敏内容已拦截")
    assert built.error.code == "content_blocked" and built.error.reasons == []
    return "ApiError: §5.6 envelope shape + content_blocked code"


def check_contract_extra_forbid() -> str:
    """每个契约模型对未知字段必须拒绝（``extra="forbid"`` 负例；审查 §C）。

    往 §5 示例 JSON 里塞一个多余字段再 ``model_validate``，必须抛校验错误——
    防止未来有人删掉 ``extra="forbid"`` 而往返用例仍然全绿（假绿灯盲区）。
    覆盖全部 9 个契约模型类（含嵌套的 RouteReason / FileFinding / 嵌套 Finding /
    ErrorBody）。
    """
    rm = importlib.import_module("recognizers.models")
    rt = importlib.import_module("routing.models")
    mm = importlib.import_module("masking.models")
    am = importlib.import_module("audit.models")
    fm = importlib.import_module("filechannel.models")
    gm = importlib.import_module("gateway.models")
    probe = "__extra_probe__"

    def reject(model_cls, data: dict, where: str) -> None:
        poisoned = json.loads(json.dumps(data, ensure_ascii=False))
        poisoned[probe] = 1
        _must_raise(lambda: model_cls.model_validate(poisoned))

    reject(rm.Finding, json.loads(FINDING_JSON), "Finding")
    route = json.loads(ROUTE_DECISION_JSON)
    reject(rt.RouteDecision, route, "RouteDecision")
    reject(rt.RouteReason, route["reasons"][0], "RouteReason")
    reject(mm.MappingEntry, json.loads(MAPPING_ENTRY_JSON), "MappingEntry")
    reject(am.AuditEvent, json.loads(AUDIT_EVENT_JSON), "AuditEvent")
    report = json.loads(FILE_REPORT_JSON)
    reject(fm.FileReport, report, "FileReport")
    reject(fm.FileFinding, report["findings"][0], "FileFinding")
    reject(rm.Finding, report["findings"][0]["finding"], "Finding(nested)")
    err = json.loads(API_ERROR_JSON)
    reject(gm.ApiError, err, "ApiError")
    reject(gm.ErrorBody, err["error"], "ErrorBody")
    return ("extra-field rejected on 9 contract models: Finding/RouteDecision/RouteReason/"
            "MappingEntry/AuditEvent/FileReport/FileFinding/ErrorBody/ApiError")


CONTRACT_CHECKS = (
    ("contract:entity-catalog", check_entity_catalog),
    ("contract:finding(5.1)", check_finding_contract),
    ("contract:route(5.2)", check_route_contract),
    ("contract:mapping(5.3.3)", check_mapping_contract),
    ("contract:audit(5.4)", check_audit_contract),
    ("contract:file-report(5.5)", check_file_report_contract),
    ("contract:api-error(5.6)", check_api_error_contract),
    ("contract:extra-forbid-negative", check_contract_extra_forbid),
)


def main() -> int:
    _record("venv", check_venv)
    _record("self-install", check_self_install)
    _record("deps:main", check_deps("main"))
    _record("deps:extras(dev/ocr/ml)", check_deps("extras"))
    _record("config:app.yaml", check_app_config)
    _record("config:env-override", check_env_override)
    _record("config:secrets", check_secrets)
    _record("config:env-file", check_env_file)
    _record("config:dept_keys.yaml", check_dept_keys)
    _record("name-lint", check_name_lint)
    _record("env-example+gitignore", check_env_example_and_gitignore)
    _record("constraints.txt", check_constraints)
    for name, fn in CONTRACT_CHECKS:
        _record(name, fn)

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M0 INFRA: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
