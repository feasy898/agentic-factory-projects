# -*- coding: utf-8 -*-
"""VDL v2 包（YAML）的两段式校验器。

依据：overnight/vpipe/VDL_v2_草案.md §2.1（校验两段式）、§3.4（R1-R6）、§7.4（validate_vdl 规格）。
契约：contracts/v2/vdl_package.schema.json + shot_v2.schema.json（draft-07，闸门 A）。
VPO 侧零改动红线（草案 §7.1）：不复制任何 VPO schema 文本进 vpipe；闸门 B 经 $id registry
把 https://vpo.example/schemas/v1/... 映射到本地 video-Ontology/schemas/ 原版 2020-12 schema。

闸门 A（结构，draft-07）: vdl_package.schema.json 全量 + shot_v2.schema.json（$ref registry）。
闸门 B（意图内容，2020-12）: intents[]/deliverable/post_ops 内嵌实例按 intent_type 分派
  VPO 原版 l2 schema；acceptance[] 按 schema 字段分派 l4/acceptance-spec。
规则层（机判，schema 表达不了的部分）:
  R1 intent_refs/acceptance_refs 悬空 → 拒收（借 VPO requirements_incomplete 防线思想）
  R2 engine.channel 以 api_ 开头时 seed_policy=fix_for_iteration 或 cache.strategy=
     content_fingerprint → 拒收（API seed 零控制力 / 缓存只命中提交参数层，工程方案v3 §5.1/§5.3 实测）
  R3 duration_s>6 且 d3_split_declared=false → 警告；>15 → 拒收（H3 单段 4-15s，shot.schema.json:28）
  R4 prompt_mode=compiled 且手写 prompt 非空 → 拒收（单一事实源）
  R5 resolution 与引擎能力不符 → 记 capability_mismatch（沿 v1 语义：不拒收，按请求方降级策略执行）
  R6 意图含模型名 → 闸门 B not-pattern 拒收（intent-common.schema.json:170-179）
跨镜头引用检查（任务要求）:
  - continuity.link=prev_tail_frame 但本镜是 shots[0]（无上镜）→ 拒收
  - transition 意图的 incoming_shot_ref/outgoing_shot_ref 必须解析到包内 shot_id
  - target/scope 的 ref（kind=shot）必须解析到包内 shot_id
  - post_ops[].intent_ref/run_after[] 必须解析到包内 intent_id / shot_id
  - acceptance[].intent_path 首段必须解析到包内 intent_id
  - template.slots[].path 必须解析到包内存在的位置（dotted/JSON-path）
  - identity 唯一性：intent_id / criterion_id / shot_id 重复 → 拒收

CLI:
  python vdl2_validate.py --pkg examples/10_shortdrama_ep01.yaml
      [--vpo-root D:/workspace/video-Ontology/schemas] [--out report.json]
  exit 0 = 通过；1 = 拒收（errors 非空）；2 = 输入/环境错误。
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import yaml

HERE = Path(__file__).resolve().parent
VPPIPE_ROOT = HERE.parent.parent                       # overnight/vpipe
CONTRACTS_V2 = VPPIPE_ROOT / "contracts" / "v2"
PKG_SCHEMA_PATH = CONTRACTS_V2 / "vdl_package.schema.json"
SHOT_V2_SCHEMA_PATH = CONTRACTS_V2 / "shot_v2.schema.json"
DEFAULT_VPO_ROOT = Path("D:/workspace/video-Ontology/schemas")

# 首批九意图（草案 §0 采纳面；其余 l2 意图可校验但登记「非首批」note）
FIRST_NINE = {
    "vpo:craft.intent_object.camera_intent",
    "vpo:craft.intent_object.performance_intent",
    "vpo:craft.intent_object.limited_motion_intent",
    "vpo:craft.intent_object.audio_intent",
    "vpo:craft.intent_object.text_overlay_intent",
    "vpo:craft.intent_object.transition_intent",
    "vpo:craft.intent_object.loop_intent",
    "vpo:craft.intent_object.deliverable_set",
    "vpo:craft.intent_object.postprocess_intent",
}
L4_ACCEPTANCE_SPEC_ID = "https://vpo.example/schemas/v1/l4/acceptance-spec.schema.json"
L4_ACCEPTANCE_RECORD_ID = "https://vpo.example/schemas/v1/l4/acceptance-record.schema.json"

KNOWN_CHANNELS = {"local_ltx", "local_wan", "api_h3max", "api_h3", "api_vidu_avatar"}
KNOWN_EDIT_OPS = {"reseed", "reprompt", "trim", "extend", "merge_ordered",
                  "subtitle_burn", "color_grade"}


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _err(code, where, msg):
    return {"code": code, "where": where, "msg": msg}


# =====================================================================
# VPO registry（闸门 B 底座；$id → 本地文件，VPO 只读零改动）
# =====================================================================
def build_vpo_registry(vpo_root: Path):
    """扫 VPO schemas/**/*.json，以各自 $id 注册进 referencing.Registry（2020-12）。
    返回 (registry, n_registered)。文件缺失/无 $id 的如实登记。"""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    if not vpo_root.is_dir():
        raise FileNotFoundError(f"VPO schema 根目录不存在: {vpo_root}（闸门 B 无法执行，fail-fast）")
    reg, n = Registry(), 0
    for p in sorted(vpo_root.rglob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue                                   # VPO 侧坏文件不静默吞：计数后由调用方暴露
        sid = doc.get("$id")
        if sid:
            reg = reg.with_resource(sid, Resource.from_contents(doc, default_specification=DRAFT202012))
            n += 1
    return reg, n


def build_gate_a_registry():
    """闸门 A 的 draft-07 registry：注册 shot_v2（供 vdl_package $ref 解析）。"""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7

    shot_doc = json.loads(SHOT_V2_SCHEMA_PATH.read_text(encoding="utf-8"))
    reg = Registry().with_resource(
        "vpipe/contracts/v2/shot_v2.schema.json",
        Resource.from_contents(shot_doc, default_specification=DRAFT7))
    return reg


def intent_type_to_schema_path(intent_type: str, vpo_root: Path):
    """vpo:craft.intent_object.X → l2 文件相对路径。先试 <stem>-intent 再试裸名
    （deliverable_set→deliverable-set.schema.json 等特例）。找不到返回 None。"""
    if not intent_type.startswith("vpo:craft.intent_object."):
        return None
    stem = intent_type.rsplit(".", 1)[1].replace("_", "-")
    for cand in (f"l2/{stem}-intent.schema.json", f"l2/{stem}.schema.json"):
        if (vpo_root / cand).is_file():
            return cand
    return None


# =====================================================================
# 意图展开（$file 引用）
# =====================================================================
def expand_intents(pkg: dict, base_dir: Path):
    """intents[] 的 $file 引用展开为内嵌实例。返回 (展开后包, errors)。
    悬空文件/坏 JSON/非对象 → 拒收级错误。展开后的实例保留 _src 注记（便于报错定位）。"""
    errors, out = [], []
    for i, it in enumerate(pkg.get("intents") or []):
        if isinstance(it, dict) and "$file" in it:
            rel = it["$file"]
            p = (base_dir / rel).resolve()
            if not p.is_file():
                errors.append(_err("PKG.intent_file_missing", f"intents[{i}].$file",
                                   f"意图文件不存在: {rel}（相对 {base_dir}）"))
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                errors.append(_err("PKG.intent_file_bad", f"intents[{i}].$file",
                                   f"解析失败 {type(e).__name__}: {e}"))
                continue
            if not isinstance(doc, dict):
                errors.append(_err("PKG.intent_file_bad", f"intents[{i}].$file",
                                   f"{rel} 根不是对象"))
                continue
            doc = dict(doc)
            doc["_src"] = rel
            out.append(doc)
        else:
            out.append(it)
    pkg = dict(pkg)
    pkg["intents"] = out
    return pkg, errors


# =====================================================================
# 闸门 A + 闸门 B
# =====================================================================
def gate_a(pkg: dict, reg_a):
    import jsonschema
    schema = json.loads(PKG_SCHEMA_PATH.read_text(encoding="utf-8"))
    v = jsonschema.Draft7Validator(schema, registry=reg_a)
    errs = []
    for e in sorted(v.iter_errors(pkg), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(x) for x in e.absolute_path) or "<root>"
        errs.append(_err("GATE_A.structure", loc, e.message[:400]))
    return errs


def gate_b(pkg: dict, reg_b, vpo_root: Path):
    """每个意图实例按 intent_type 分派 VPO 原版 2020-12 schema；acceptance 按 schema 字段
    分派 l4。R6（模型名 not-pattern）由 VPO intent-common 原样生效。"""
    import jsonschema
    errs, notes, checked = [], [], []

    def validate_instance(inst, where, want_type=None):
        itype = (inst or {}).get("intent_type", "")
        if want_type and itype != want_type:
            errs.append(_err("GATE_B.intent_type", where,
                             f"此处要求 intent_type={want_type}，实得 {itype!r}"))
            return
        rel = intent_type_to_schema_path(itype, vpo_root)
        if rel is None:
            errs.append(_err("GATE_B.unknown_intent_type", where,
                             f"intent_type {itype!r} 无法映射到 VPO l2 schema（本地 {vpo_root}）"))
            return
        try:
            sch_doc = json.loads((vpo_root / rel).read_text(encoding="utf-8"))
        except Exception as e:
            errs.append(_err("GATE_B.schema_load", where,
                             f"读取 {rel} 失败 {type(e).__name__}: {e}"))
            return
        body = {k: v for k, v in inst.items() if not k.startswith("_")}
        v = jsonschema.Draft202012Validator(sch_doc, registry=reg_b)
        inst_errs = sorted(v.iter_errors(body), key=lambda e: list(e.absolute_path))
        for e in inst_errs:
            loc = "/".join(str(x) for x in e.absolute_path) or "<root>"
            errs.append(_err("GATE_B.intent_content", f"{where}/{loc}", e.message[:400]))
        checked.append({"where": where, "intent_type": itype, "schema": rel,
                        "n_errors": len(inst_errs)})
        if itype not in FIRST_NINE:
            notes.append(f"{where}: intent_type={itype} 非草案首批九意图（可校验，升格路径见草案 §9）")

    for i, it in enumerate(pkg.get("intents") or []):
        validate_instance(it, f"intents[{i}]{'(' + it.get('_src', '') + ')' if isinstance(it, dict) and it.get('_src') else ''}")
    if pkg.get("deliverable"):
        validate_instance(pkg["deliverable"], "deliverable",
                          want_type="vpo:craft.intent_object.deliverable_set")
    for i, po in enumerate(pkg.get("post_ops") or []):
        if isinstance(po, dict) and "intent_ref" not in po:      # 内嵌完整实例形态
            validate_instance(po, f"post_ops[{i}]",
                              want_type="vpo:craft.intent_object.postprocess_intent")
    # acceptance[] → l4/acceptance-spec（VPO 原版，additionalProperties:false 全量深校验）
    l4_path = vpo_root / "l4" / "acceptance-spec.schema.json"
    if l4_path.is_file():
        l4_doc = json.loads(l4_path.read_text(encoding="utf-8"))
        v = jsonschema.Draft202012Validator(l4_doc, registry=reg_b)
        for i, sp in enumerate(pkg.get("acceptance") or []):
            for e in sorted(v.iter_errors(sp), key=lambda e: list(e.absolute_path)):
                loc = "/".join(str(x) for x in e.absolute_path) or "<root>"
                errs.append(_err("GATE_B.acceptance_spec", f"acceptance[{i}]/{loc}", e.message[:400]))
            checked.append({"where": f"acceptance[{i}]", "intent_type": "l4:acceptance-spec",
                            "schema": "l4/acceptance-spec.schema.json", "n_errors": 0})
    else:
        errs.append(_err("GATE_B.schema_load", "acceptance",
                         f"VPO l4 schema 缺失: {l4_path}"))
    return errs, notes, checked


# =====================================================================
# JSON-path 求值（template.slots[].path 校验用）
# =====================================================================
_PATH_TOKEN = re.compile(r"\.?([^\[\].]+)|\[(\d+)\]")


def resolve_path(doc, path: str):
    """dotted + [n] 路径求值。返回 (值, None) 或 (None, 错误消息)。叶子值为 null 仍算路径存在。"""
    cur = doc
    consumed = 0
    for m in _PATH_TOKEN.finditer(path):
        consumed += len(m.group(0))
        if m.group(1) is not None:
            key = m.group(1)
            if not isinstance(cur, dict) or key not in cur:
                return None, f"字段 '{key}' 不存在"
            cur = cur[key]
        else:
            idx = int(m.group(2))
            if not isinstance(cur, list) or idx >= len(cur):
                return None, f"索引 [{idx}] 越界或非数组"
            cur = cur[idx]
    if consumed < len(path.replace(" ", "")):
        return None, "路径含无法解析的残段"
    return cur, None


# =====================================================================
# 规则层 R1-R5 + 跨镜头引用 + 唯一性
# =====================================================================
def check_rules(pkg: dict):
    errors, warnings, cross = [], [], {"checked": 0, "errors": 0}

    intent_ids, criterion_ids, shot_ids = [], [], []
    for i, it in enumerate(pkg.get("intents") or []):
        iid = ((it or {}).get("identity") or {}).get("intent_id")
        if iid:
            intent_ids.append((iid, f"intents[{i}]"))
    intent_id_set = {x[0] for x in intent_ids}
    for i, sp in enumerate(pkg.get("acceptance") or []):
        cid = (sp or {}).get("criterion_id")
        if cid:
            criterion_ids.append((cid, f"acceptance[{i}]"))
    criterion_id_set = {x[0] for x in criterion_ids}
    for i, s in enumerate(pkg.get("shots") or []):
        sid = (s or {}).get("shot_id")
        if sid:
            shot_ids.append((sid, f"shots[{i}]"))
    shot_id_set = {x[0] for x in shot_ids}

    # 唯一性
    for name, seq in (("intent_id", intent_ids), ("criterion_id", criterion_ids),
                      ("shot_id", shot_ids)):
        seen = {}
        for val, where in seq:
            if val in seen:
                errors.append(_err("REF.duplicate", where,
                                   f"{name}={val!r} 重复（首次出现于 {seen[val]}）"))
            else:
                seen[val] = where
        cross["checked"] += len(seq)

    default_pm = pkg.get("default_prompt_mode", "hybrid")

    def add_cross(code, where, msg):
        nonlocal cross
        cross["errors"] += 1
        errors.append(_err(code, where, msg))

    # 意图侧跨引用：target/scope(shot) + transition refs + postprocess intent_ref
    for i, it in enumerate(pkg.get("intents") or []):
        it = it or {}
        where = f"intents[{i}]"
        tgt = it.get("target") or {}
        if tgt.get("kind") == "shot" and tgt.get("ref"):
            cross["checked"] += 1
            if tgt["ref"] not in shot_id_set:
                add_cross("REF.dangling_shot_ref", f"{where}.target.ref",
                          f"target.ref={tgt['ref']!r} 未解析到包内 shot_id")
        scope = it.get("scope") or {}
        if str(scope.get("level", "")).endswith(".shot") and scope.get("ref"):
            cross["checked"] += 1
            if scope["ref"] not in shot_id_set:
                add_cross("REF.dangling_shot_ref", f"{where}.scope.ref",
                          f"scope.ref={scope['ref']!r} 未解析到包内 shot_id")
        for fld in ("incoming_shot_ref", "outgoing_shot_ref"):
            if it.get(fld):
                cross["checked"] += 1
                if it[fld] not in shot_id_set:
                    add_cross("REF.dangling_shot_ref", f"{where}.{fld}",
                              f"{fld}={it[fld]!r} 未解析到包内 shot_id（transition 意图跨镜引用）")

    # post_ops：intent_ref / run_after
    pp_intent_ids = {v for v, _ in intent_ids
                     if any((it or {}).get("intent_type") == "vpo:craft.intent_object.postprocess_intent"
                            for it in (pkg.get("intents") or [])
                            if ((it or {}).get("identity") or {}).get("intent_id") == v)}
    for i, po in enumerate(pkg.get("post_ops") or []):
        po = po or {}
        where = f"post_ops[{i}]"
        if po.get("intent_ref"):
            cross["checked"] += 1
            if po["intent_ref"] not in intent_id_set:
                add_cross("R1.dangling_postop_ref", f"{where}.intent_ref",
                          f"intent_ref={po['intent_ref']!r} 未解析到包内 intent_id")
            elif po["intent_ref"] not in pp_intent_ids:
                errors.append(_err("REF.postop_type", where,
                                   f"intent_ref={po['intent_ref']!r} 不是 PostProcessIntent（post_ops 只挂后处理意图）"))
        for j, ra in enumerate(po.get("run_after") or []):
            cross["checked"] += 1
            if ra not in shot_id_set:
                add_cross("REF.dangling_shot_ref", f"{where}.run_after[{j}]",
                          f"run_after={ra!r} 未解析到包内 shot_id")
        if not po.get("intent_ref") and not po.get("intent_type"):
            errors.append(_err("REF.postop_form", where,
                               "post_ops 项须为 {intent_ref, run_after} 引用形或内嵌 PostProcessIntent 实例"))

    # acceptance[].intent_path 首段 → intent_id
    for i, sp in enumerate(pkg.get("acceptance") or []):
        ip = (sp or {}).get("intent_path") or ""
        first = ip.split(".")[0].split("[")[0].strip()
        if first:
            cross["checked"] += 1
            if first not in intent_id_set:
                add_cross("R1.dangling_intent_path", f"acceptance[{i}].intent_path",
                          f"intent_path 首段 {first!r} 未解析到包内 intent_id")

    # template.slots[].path / intent_binding
    tpl = pkg.get("template") or {}
    for i, slot in enumerate(tpl.get("slots") or []):
        slot = slot or {}
        where = f"template.slots[{i}]"
        if slot.get("path"):
            cross["checked"] += 1
            val, perr = resolve_path(pkg, slot["path"])
            if perr:
                add_cross("REF.dangling_slot_path", f"{where}.path",
                          f"path={slot['path']!r} 解析失败：{perr}")
        ib = slot.get("intent_binding") or ""
        first = ib.split(".")[0].split("[")[0].strip()
        if first:
            cross["checked"] += 1
            if first not in intent_id_set:
                add_cross("R1.dangling_intent_binding", f"{where}.intent_binding",
                          f"intent_binding 首段 {first!r} 未解析到包内 intent_id")

    # shot 级：R1/R2/R3/R4/R5 + continuity 首镜 + engine_hint 双源
    for i, s in enumerate(pkg.get("shots") or []):
        s = s or {}
        sid = s.get("shot_id", f"#{i}")
        where = f"shots[{i}]({sid})"
        pm = s.get("prompt_mode") or default_pm
        eng = s.get("engine") or {}
        ch = eng.get("channel", "")
        cont = s.get("continuity") or {}
        cache = s.get("cache") or {}

        # R1
        for j, r in enumerate(s.get("intent_refs") or []):
            cross["checked"] += 1
            if r not in intent_id_set:
                add_cross("R1.dangling_intent_ref", f"{where}.intent_refs[{j}]",
                          f"intent_ref={r!r} 未解析到包内 intents[].identity.intent_id")
        for j, r in enumerate(s.get("acceptance_refs") or []):
            cross["checked"] += 1
            if r not in criterion_id_set:
                add_cross("R1.dangling_acceptance_ref", f"{where}.acceptance_refs[{j}]",
                          f"acceptance_ref={r!r} 未解析到包内 acceptance[].criterion_id")
        # R2（api 通道）
        if ch.startswith("api_"):
            if cont.get("seed_policy") == "fix_for_iteration":
                errors.append(_err("R2.api_seed_policy", f"{where}.continuity.seed_policy",
                                   "api_* 通道禁 fix_for_iteration（API seed 零控制力实测，工程方案v3 §1；仅本地通道合法）"))
            if cache.get("strategy") == "content_fingerprint":
                errors.append(_err("R2.api_cache_strategy", f"{where}.cache.strategy",
                                   "api_* 通道禁 content_fingerprint（API 层同指纹重提交必然新样本，缓存只命中提交参数层，工程方案v3 §5.3-2）"))
        # R3
        dur = s.get("duration_s")
        if isinstance(dur, (int, float)):
            if dur > 15:
                errors.append(_err("R3.duration_over_engine_limit", f"{where}.duration_s",
                                   f"duration_s={dur} 超引擎单段上限 15s（H3 4-15s，shot.schema.json:28）"))
            elif dur > 6 and not cont.get("d3_split_declared"):
                warnings.append(f"{where}: duration_s={dur}>6 且 d3_split_declared=false（D3-1 单段只承载一个意图峰值，草案 R3 警告级）")
        # R4
        if pm == "compiled" and (s.get("prompt") or "").strip():
            errors.append(_err("R4.compiled_with_handwritten", f"{where}.prompt",
                               "prompt_mode=compiled 禁手写 prompt（单一事实源，草案 §3.2 #2/R4）"))
        if pm == "handwritten" and (s.get("prompt_compiled") or "").strip():
            warnings.append(f"{where}: prompt_mode=handwritten 但存在 prompt_compiled（双源嫌疑，登记不拦截）")
        # R5（能力不匹配登记，不拒收）
        if ch.startswith("local_") and s.get("resolution") not in (None, "480P"):
            warnings.append(f"{where}: capability_mismatch — 本地通道({ch})仅实测 480P，声明 {s.get('resolution')}（沿 v1 语义按请求方降级策略执行，R5）")
        # 跨镜：首镜 link=prev_tail_frame
        if cont.get("link") == "prev_tail_frame":
            cross["checked"] += 1
            if i == 0:
                add_cross("REF.head_shot_no_prev", f"{where}.continuity.link",
                          "首镜声明 link=prev_tail_frame，但本镜之前无镜头可取真实尾帧（D3-3）")
        # 通道/操作词表开放性（未知值登记警告）
        if ch and ch not in KNOWN_CHANNELS:
            warnings.append(f"{where}: engine.channel={ch} 不在已知值 {sorted(KNOWN_CHANNELS)}（开放扩展，编译时按未知通道处理）")
        for j, fb in enumerate(eng.get("fallback") or []):
            if fb not in KNOWN_CHANNELS:
                warnings.append(f"{where}.engine.fallback[{j}]: {fb} 不在已知通道表（开放扩展）")
        for j, eo in enumerate(s.get("edit_ops") or []):
            op = (eo or {}).get("op", "")
            if op and op not in KNOWN_EDIT_OPS:
                warnings.append(f"{where}.edit_ops[{j}].op={op} 不在首版词表 {sorted(KNOWN_EDIT_OPS)}（开放词表，编译时登记）")
        # engine_hint deprecated-for-v2
        if s.get("engine_hint") is not None:
            warnings.append(f"{where}: engine_hint 为 deprecated-for-v2 兼容位（投影器②从 engine.channel 自动生成；手写出现即双源警告，草案 §3.2 #10）")
        # prompt_hash 与 prompt_compiled 一致性（若都给了）
        ph, pc = s.get("prompt_hash"), (s.get("prompt_compiled") or "")
        if ph and pc:
            import hashlib
            real = hashlib.sha256(pc.encode("utf-8")).hexdigest()
            if real != ph:
                errors.append(_err("PKG.prompt_hash_mismatch", f"{where}.prompt_hash",
                                   f"prompt_hash 与 prompt_compiled 的 sha256 不符（应为 {real}）"))

    # 预算一致性：包级 credit_cap_total vs 每镜 credit_cap_per_shot 总和（超出→警告）
    total = ((pkg.get("budget") or {}).get("credit_cap_total"))
    if total is not None:
        ssum = sum(((s.get("budget") or {}).get("credit_cap_per_shot") or 0)
                   for s in (pkg.get("shots") or []))
        if ssum > total:
            warnings.append(f"budget: 每镜 credit_cap_per_shot 合计 {ssum} > 包级 credit_cap_total {total}（执行器按包级硬上限拦截）")

    return errors, warnings, cross


# =====================================================================
# 总入口
# =====================================================================
def validate_package(pkg_path: str | Path, vpo_root: Path = DEFAULT_VPO_ROOT,
                     _pkg=None):
    """校验一个 VDL v2 包。返回 (report_dict, 展开后的包 dict)。
    report['ok']=True 当且仅当 errors 为空（两道闸门 + 全部机判规则）。"""
    pkg_path = Path(pkg_path)
    report = {"package": str(pkg_path), "validated_at": now_iso(),
              "vpo_root": str(vpo_root), "ok": False,
              "gate_a": {"ok": False, "n_errors": 0},
              "gate_b": {"ok": False, "n_errors": 0, "n_checked": 0},
              "cross_refs": {"checked": 0, "errors": 0},
              "errors": [], "warnings": [], "notes": [], "stats": {}}
    if _pkg is not None:
        pkg, base_dir = _pkg, pkg_path.parent
    else:
        try:
            txt = pkg_path.read_text(encoding="utf-8")
        except Exception as e:
            report["errors"].append(_err("PKG.io", str(pkg_path), f"读取失败 {type(e).__name__}: {e}"))
            return report, {}
        try:
            pkg = yaml.safe_load(txt)
        except Exception as e:
            report["errors"].append(_err("PKG.yaml", str(pkg_path), f"YAML 解析失败: {e}"))
            return report, {}
        base_dir = pkg_path.parent
    if not isinstance(pkg, dict):
        report["errors"].append(_err("PKG.root", str(pkg_path), "包根不是映射对象"))
        return report, {}

    # 意图 $file 展开（先于两道闸门：闸门 B 需要展开后的实例）
    pkg, exp_errs = expand_intents(pkg, base_dir)
    report["errors"].extend(exp_errs)

    # 闸门 A
    try:
        errs_a = gate_a(pkg, build_gate_a_registry())
    except Exception as e:
        errs_a = [_err("GATE_A.env", "<gate_a>", f"{type(e).__name__}: {e}")]
    report["gate_a"]["n_errors"] = len(errs_a)
    report["gate_a"]["ok"] = not errs_a
    report["errors"].extend(errs_a)

    # 闸门 B（结构烂到没有 intents 字段时跳过内容校验，闸门 A 已拦）
    if isinstance(pkg.get("intents"), list):
        try:
            reg_b, n_reg = build_vpo_registry(vpo_root)
            errs_b, notes_b, checked_b = gate_b(pkg, reg_b, vpo_root)
            report["notes"].append(f"VPO registry 注册 {n_reg} 个 schema（$id → 本地 {vpo_root}）")
            report["notes"].extend(notes_b)
            report["gate_b"]["n_checked"] = len(checked_b)
            report["stats"]["gate_b_detail"] = checked_b
        except Exception as e:
            errs_b, checked_b = [_err("GATE_B.env", "<gate_b>", f"{type(e).__name__}: {e}")], []
    else:
        errs_b, checked_b = [], []
    report["gate_b"]["n_errors"] = len(errs_b)
    report["gate_b"]["ok"] = not errs_b
    report["errors"].extend(errs_b)

    # 规则层 + 跨引用
    errs_r, warns_r, cross = check_rules(pkg)
    report["errors"].extend(errs_r)
    report["warnings"].extend(warns_r)
    report["cross_refs"] = cross

    report["stats"].update({
        "n_intents": len(pkg.get("intents") or []),
        "n_intents_from_file": sum(1 for it in (pkg.get("intents") or [])
                                   if isinstance(it, dict) and it.get("_src")),
        "n_shots": len(pkg.get("shots") or []),
        "n_acceptance": len(pkg.get("acceptance") or []),
        "n_post_ops": len(pkg.get("post_ops") or []),
        "n_template_slots": len((pkg.get("template") or {}).get("slots") or []),
    })
    report["ok"] = not report["errors"]
    return report, pkg


def main():
    ap = argparse.ArgumentParser(description="VDL v2 两段式校验器（闸门A draft-07 + 闸门B VPO 2020-12 + R1-R6）")
    ap.add_argument("--pkg", required=True, help="VDL v2 包 YAML 路径")
    ap.add_argument("--vpo-root", default=str(DEFAULT_VPO_ROOT),
                    help=f"VPO schemas 根目录（默认 {DEFAULT_VPO_ROOT}，只读）")
    ap.add_argument("--out", default="", help="校验报告 JSON 输出路径（缺省打印到 stdout）")
    args = ap.parse_args()

    report, _ = validate_package(args.pkg, Path(args.vpo_root))
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[vdl2_validate] 报告 → {args.out}")
    print(f"[vdl2_validate] {'PASS' if report['ok'] else 'REJECT'} "
          f"gateA={report['gate_a']['n_errors']}err gateB={report['gate_b']['n_errors']}err "
          f"rules+cross={len(report['errors']) - report['gate_a']['n_errors'] - report['gate_b']['n_errors']}err "
          f"warnings={len(report['warnings'])}")
    for e in report["errors"]:
        print(f"  [ERROR] {e['code']} @{e['where']}: {e['msg']}")
    for w in report["warnings"]:
        print(f"  [WARN ] {w}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
