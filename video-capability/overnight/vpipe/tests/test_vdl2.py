# -*- coding: utf-8 -*-
"""VDL v2 编译器/校验器测试套件（pytest）。

覆盖：
  1. 契约层：v2 两份 schema draft-07 可编译；v1 shot.schema.json 对投影产物全过
  2. 闸门层：闸门 A 结构 / 闸门 B VPO 2020-12 深校验（含 R6 not-pattern 负例）
  3. 规则层：R1 悬空引用 / R2 api 通道约束 / R3 时长 / R4 单一事实源（单元级最小包）
  4. 编译产物：v1 投影契约、prompt_hash 可复算、compiled/handwritten 两种 prompt 源、
     L4 骨架（unknown≠pass，含 VPO 陷阱字段反向验证）、槽位定义、执行计划
  5. v1 兼容回放：gen_local --validate-only / gen_api --dry-run（0 HTTP）/ qc_orch --from-tonight
     + eval_run ACCEPT（v1 冻结管线回归）

运行（在 overnight/vpipe/ 下）：
  python -m pytest tests/test_vdl2.py -v
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
VPIPE = HERE.parent
sys.path.insert(0, str(VPIPE / "src" / "vdl2"))

from vdl2_validate import (validate_package, resolve_path, DEFAULT_VPO_ROOT)  # noqa: E402
from vdl2_compile import compile_package                                    # noqa: E402

EX = VPIPE / "examples" / "vdl2"
TMP = VPIPE / "out" / "vdl2_tests"
POS = ["10_shortdrama_ep01.yaml", "20_avatar_talk.yaml", "30_programmatic_loop.yaml"]
NEG = "99_negative_must_reject.yaml"
V1_SHOT_SCHEMA = VPIPE / "contracts" / "shot.schema.json"
VPO_ROOT = Path(DEFAULT_VPO_ROOT)


# ---------------------------------------------------------------- 契约层
def test_v2_schemas_compile_as_draft07():
    import jsonschema
    for f in ("vdl_package.schema.json", "shot_v2.schema.json"):
        doc = json.loads((VPIPE / "contracts" / "v2" / f).read_text(encoding="utf-8"))
        jsonschema.Draft7Validator.check_schema(doc)          # 断言不抛即通过


# ---------------------------------------------------------------- 正例：校验+编译
@pytest.mark.parametrize("name", POS)
def test_positive_examples_validate_and_compile(name):
    rep, _ = validate_package(EX / name, VPO_ROOT)
    assert rep["ok"], f"{name} 应通过校验，实得 errors={rep['errors']}"
    assert rep["gate_a"]["n_errors"] == 0 and rep["gate_b"]["n_errors"] == 0
    code, crep = compile_package(EX / name, TMP / name.split("_")[0], VPO_ROOT)
    assert code == 0 and crep["ok"], f"{name} 编译失败: {crep['errors']}"


def test_negative_example_rejected_with_all_expected_codes():
    rep, _ = validate_package(EX / NEG, VPO_ROOT)
    assert not rep["ok"]
    codes = {e["code"] for e in rep["errors"]}
    expected = {
        "GATE_A.structure",                       # duration_s=18 > schema maximum 15
        "GATE_B.intent_content",                  # predicate 含模型名 Wan2.1（R6 not-pattern）
        "R1.dangling_intent_ref", "R1.dangling_acceptance_ref",
        "R1.dangling_intent_path", "R1.dangling_postop_ref",
        "R1.dangling_intent_binding",
        "REF.dangling_shot_ref", "REF.dangling_slot_path",
        "R2.api_seed_policy", "R2.api_cache_strategy",
        "R3.duration_over_engine_limit", "R4.compiled_with_handwritten",
        "REF.head_shot_no_prev",
    }
    missing = expected - codes
    assert not missing, f"负例应有错误码未命中: {missing}；实得 {sorted(codes)}"


def test_negative_example_compile_refused():
    code, crep = compile_package(EX / NEG, TMP / "99", VPO_ROOT)
    assert code == 2, "负例必须被编译器拒收（exit 2）"
    assert crep["outputs"].get("n_v1_shots", 0) == 0
    assert not (TMP / "99" / "shots_v1").exists() or not list((TMP / "99" / "shots_v1").glob("*.json"))


# ---------------------------------------------------------------- 规则层单元（最小包）
def _min_pkg(**shot_over):
    shot = {"schema_version": "2.0", "shot_id": "s_unit_1", "duration_s": 5, "aspect": "9:16",
            "intent_refs": ["i-x"], "prompt_mode": "handwritten", "prompt": "单元测试手写",
            "engine": {"channel": "api_h3max"}, "acceptance_refs": []}
    shot.update(shot_over)
    return {"vdl_version": "2.0", "work_id": "unit_pkg", "default_prompt_mode": "handwritten",
            "intents": [], "shots": [shot]}


def _rule_errors(pkg):
    """只跑规则层（跳过闸门，最小包无意图）。"""
    from vdl2_validate import check_rules
    errs, warns, _ = check_rules(pkg)
    return {e["code"] for e in errs}


def test_r2_api_channel_seed_and_cache():
    codes = _rule_errors(_min_pkg(
        continuity={"seed_policy": "fix_for_iteration", "link": "none"},
        cache={"strategy": "content_fingerprint"}))
    assert "R2.api_seed_policy" in codes and "R2.api_cache_strategy" in codes


def test_r2_local_channel_allows_fix_seed():
    pkg = _min_pkg(engine={"channel": "local_ltx"},
                   continuity={"seed_policy": "fix_for_iteration", "link": "none"},
                   cache={"strategy": "content_fingerprint"})
    assert not (_rule_errors(pkg) & {"R2.api_seed_policy", "R2.api_cache_strategy"}), \
        "本地通道 fix_for_iteration/content_fingerprint 应合法（同种子字节级复现实测）"


def test_r4_compiled_forbids_handwritten_prompt():
    assert "R4.compiled_with_handwritten" in _rule_errors(_min_pkg(prompt_mode="compiled"))


def test_r3_duration_limit():
    assert "R3.duration_over_engine_limit" in _rule_errors(_min_pkg(duration_s=15.5))


def test_resolve_path_unit():
    doc = {"shots": [{"audio": {"speech": "hi"}}, {"characters": [None]}]}
    assert resolve_path(doc, "shots[0].audio.speech") == ("hi", None)
    v, err = resolve_path(doc, "shots[5].audio")
    assert v is None and err
    v, err = resolve_path(doc, "shots[1].characters[0]")
    assert v is None and err is None          # 索引内值为 null：路径存在
    assert resolve_path(doc, "shots[0].nope")[1]


def test_dangling_file_ref_rejected():
    pkg = {"vdl_version": "2.0", "work_id": "w", "default_prompt_mode": "handwritten",
           "intents": [{"$file": "intents/not_exist.json"}],
           "shots": [{"schema_version": "2.0", "shot_id": "s", "duration_s": 5, "aspect": "9:16",
                      "prompt": "x", "intent_refs": [], "prompt_mode": "handwritten",
                      "acceptance_refs": []}]}
    rep, _ = validate_package(EX / "10_shortdrama_ep01.yaml", VPO_ROOT, _pkg=pkg)
    assert any(e["code"] == "PKG.intent_file_missing" for e in rep["errors"])


# ---------------------------------------------------------------- 编译产物断言
def _compiled(name):
    d = TMP / name.split("_")[0]
    code, crep = compile_package(EX / name, d, VPO_ROOT)
    assert code == 0, crep["errors"]
    return d


def test_v1_projection_passes_frozen_contract():
    import jsonschema
    schema = json.loads(V1_SHOT_SCHEMA.read_text(encoding="utf-8"))
    v = jsonschema.Draft7Validator(schema)
    n = 0
    for name in POS:
        for f in sorted(_compiled(name).glob("shots_v1/*.json")):
            shot = json.loads(f.read_text(encoding="utf-8"))
            errs = list(v.iter_errors(shot))
            assert not errs, f"{f}: {errs}"
            assert shot["schema_version"] == "1.0"
            n += 1
    assert n == 5, f"三个示例应投影 5 个 v1 shot，实得 {n}"


def test_prompt_hash_recomputable_and_modes():
    d10 = _compiled("10_shortdrama_ep01.yaml")
    s42 = json.loads((d10 / "shots_v1" / "shot_ep01_0042.json").read_text(encoding="utf-8"))
    s43 = json.loads((d10 / "shots_v1" / "shot_ep01_0043.json").read_text(encoding="utf-8"))
    # hash 可复算（notes 里 vdl2:prompt_hash == sha256(v1 prompt)，三态统一口径）
    h42 = next(x for x in s42["notes"].split(" | ") if x.startswith("vdl2:prompt_hash=")).split("=")[1]
    assert h42 == hashlib.sha256(s42["prompt"].encode("utf-8")).hexdigest()
    # compiled 镜：prompt 来自编译器①（分段：镜头/主体/语义），不含手写
    assert s42["prompt"].startswith("镜头：") and "\n主体：" in s42["prompt"] and "\n语义：" in s42["prompt"]
    # handwritten 镜：prompt 为手写原文
    src = {"shot_ep01_0043": None}
    pkg_txt = (EX / "10_shortdrama_ep01.yaml").read_text(encoding="utf-8")
    assert s43["prompt"] in pkg_txt, "handwritten 镜的 v1 prompt 应原样来自包内手写字段"


def test_acceptance_skeletons_unknown_not_pass():
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    from vdl2_validate import build_vpo_registry

    reg, _ = build_vpo_registry(VPO_ROOT)
    l4 = json.loads((VPO_ROOT / "l4" / "acceptance-record.schema.json").read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(l4, registry=reg)
    n = 0
    for name in POS:
        for f in sorted(_compiled(name).glob("acceptance_records/*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            errs = list(v.iter_errors(rec))
            assert not errs, f"骨架未过 VPO acceptance-record: {f}: {errs}"
            assert rec["status"] == "vpo:delivery.record_status.unknown"
            assert "treated_as" not in rec and "gate_result" not in rec   # unknown≠pass 陷阱字段不设
            assert rec["evaluator_id"] and rec["evaluator_version"]
            n += 1
    assert n == 8, f"三个示例应产出 8 个验收骨架，实得 {n}"
    # 反向：approved_exception 无 reviewer → VPO 拒（证明骨架校验真能抓 L4 陷阱）
    rec = json.loads(next(_compiled("10_shortdrama_ep01.yaml")
                          .glob("acceptance_records/*.json")).read_text(encoding="utf-8"))
    rec["status"] = "vpo:delivery.record_status.approved_exception"
    assert list(v.iter_errors(rec)), "approved_exception 无 reviewer 必须被 VPO schema 拒收"


def test_slots_and_execution_plan():
    for name, tid, n_slots in (("20_avatar_talk.yaml", "avatar_talk_v1", 4),
                               ("30_programmatic_loop.yaml", "product_loop_9x16_v1", 4)):
        d = _compiled(name)
        slots = json.loads((d / "slots.json").read_text(encoding="utf-8"))
        assert slots["template_id"] == tid and len(slots["slots"]) == n_slots
        _, pkg = validate_package(EX / name, VPO_ROOT)   # 返回 (report, 展开后的包)
        for s in slots["slots"]:
            val, err = resolve_path(pkg, s["path"])
            assert err is None, f"{name} 槽位 {s['name']} 路径悬空: {s['path']}"
            assert val == s["current_value"], f"{s['name']} current_value 与包内实值不符"
        plan = json.loads((d / "execution_plan.json").read_text(encoding="utf-8"))
        assert plan["schema_version"] == "2.0" and plan["work_id"]
        for pm in plan["projection_manifest"]:
            f = d / pm["v1_shot"]
            assert f.is_file() and pm["prompt_hash"]
            assert all("@" in iv for iv in pm["intent_versions"])   # 意图带版本
    # avatar 执行段只出现在 v2 计划侧（v1 契约冻结不扩字段）
    plan20 = json.loads((TMP / "20" / "execution_plan.json").read_text(encoding="utf-8"))
    av = [s for s in plan20["shots"] if s.get("avatar")]
    assert len(av) == 2 and av[0]["avatar"]["tts_input"]


# ---------------------------------------------------------------- v1 兼容回放（子进程）
def test_v1_gen_local_validate_only_accepts_projections():
    for name in POS:
        for f in sorted(_compiled(name).glob("shots_v1/*.json")):
            r = subprocess.run([sys.executable, str(VPIPE / "src" / "gen_local.py"),
                                "--validate-only", "--shot", str(f)],
                               capture_output=True, text=True, cwd=str(VPIPE))
            assert r.returncode == 0, f"gen_local 拒收 {f}: {r.stdout} {r.stderr}"


def test_v1_gen_api_dryrun_accepts_projections_zero_http():
    r = subprocess.run([sys.executable, str(VPIPE / "src" / "gen_api.py"),
                        "--shots", str(TMP / "10" / "shots_v1"),
                        "--out-dir", str(TMP / "genapi_dryrun"), "--dry-run"],
                       capture_output=True, text=True, cwd=str(VPIPE))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "未发任何 HTTP" in r.stdout and '"n_shots": 2' in r.stdout


def test_v1_acceptance_path_replay_eval_accept():
    """编译产物就位的同一工作区里，v1 验收路径（qc_orch 回放 + eval_run）仍 ACCEPT——
    v2 落地零破坏（SPEC §6-4 回归条款）。"""
    out_qc = VPIPE / "out" / "qc_reports_v2check"
    r = subprocess.run([sys.executable, str(VPIPE / "src" / "qc_orch.py"), "--from-tonight",
                        "--judges-root", str(VPIPE.parent / "数据" / "judges"),
                        "--golden", str(VPIPE / "eval" / "golden_manifest.json"),
                        "--thresholds", str(VPIPE / "eval" / "thresholds.yaml"),
                        "--out-dir", str(out_qc),
                        "--manifest", str(VPIPE / "out" / "asset_manifest_v2check.json")],
                       capture_output=True, text=True, cwd=str(VPIPE))
    assert r.returncode == 0 and "回放 40 clips" in r.stdout, r.stdout + r.stderr
    r2 = subprocess.run([sys.executable, str(VPIPE / "eval" / "eval_run.py"),
                         "--qc-dir", str(out_qc)], capture_output=True, text=True, cwd=str(VPIPE))
    assert r2.returncode == 0 and "ACCEPT" in r2.stdout, r2.stdout + r2.stderr
    assert "与基线偏差: dR=0.0 dFPR=0.0 dF1=0.0" in r2.stdout
