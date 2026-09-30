# -*- coding: utf-8 -*-
"""VDL v2 编译器：包 YAML →（校验 +）编译产物。

依据：overnight/vpipe/VDL_v2_草案.md §1（编译器①意图→执行计划）、§7.4（投影器②规格）、
§7.3（AcceptanceRecord 骨架与 evaluator 映射）、任务新增面（槽位定义供模板线）。
前置：vdl2_validate.validate_package（两道闸门 + R1-R6 + 跨引用），任何 error 拒绝编译（fail-fast）。

产物（--out-dir 下）：
  execution_plan.json           执行计划（含每镜 v1 投影路径/engine/cache/budget/验收引用/投影清单）
  shots_v1/<shot_id>.json       v1 ShotSpec（schema_version=1.0，可直接喂 vpipe gen_local/gen_api；
                                逐条过 contracts/shot.schema.json 校验后才落盘）
  acceptance_records/*.json     L4 验收记录骨架（AcceptanceSpec 绑定；status=unknown，不设
                                treated_as/gate_result —— unknown≠pass，执行后由验收记录器定）
  slots.json                    槽位定义（模板线调用方按名填充；填充后重编译得实例包）
  compile_report.json           编译日志（警告/冲突登记/输出清单）

prompt 编译（编译器①，草案 §3.2 #2-#3）：
  compiled   = 从 intents 生成（镜头语言段 + 主体段 + 语义段 + 运镜说明 + 台词段），禁手写（R4）
  hybrid     = 手写底稿 + 意图补丁（冲突只登记不拦截，草案 §9 / 开放问题 3）
  handwritten= 原样（intents 仅登记）
  prompt_hash = sha256(prompt_compiled)，进投影后 v1 shot notes（草案 §3.2 #3）

CLI:
  python vdl2_compile.py --pkg examples/10_shortdrama_ep01.yaml --out-dir out/vdl2/10
      [--vpo-root D:/workspace/video-Ontology/schemas]
  exit 0 = 编译成功；1 = 编译产物异常；2 = 校验拒收；3 = IO/环境错误。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from vdl2_validate import (DEFAULT_VPO_ROOT, validate_package, resolve_path,
                           now_iso)

HERE = Path(__file__).resolve().parent
VPPIPE_ROOT = HERE.parent.parent
V1_SHOT_SCHEMA = VPPIPE_ROOT / "contracts" / "shot.schema.json"

COMPILER_ID = "vdl2_compile.py@vpipe2.0-dev"

# engine.channel → v1 engine_hint 投影（preferred, model）
CHANNEL_MODEL = {
    "local_ltx": ("local", "ltx"),
    "local_wan": ("local", "wan"),
    "api_h3max": ("api", "MiniMax-H3-Max"),
    "api_h3": ("api", "MiniMax-H3"),
    "api_vidu_avatar": ("api", "Vidu-avatar-offline"),   # G9a 口播专线（工程方案v3.1 §2.4）
}

# VPO cine 词表 → 中文镜头语言（编译器①的文本化层；通道论依据 D0「文本控语义」）
SCALE_ZH = {"extreme_wide": "大远景", "wide": "远景", "medium": "中景", "close": "近景特写",
            "extreme_close": "大特写", "macro": "微距"}
MOVE_ZH = {"static": "机位静止", "push": "推近", "pull": "拉远", "pan": "横摇", "tilt": "纵摇",
           "track": "跟随移动", "orbit": "环绕", "zoom": "变焦", "boom": "升降",
           "whip_pan": "甩摇", "dolly_zoom": "滑动变焦", "roll": "横滚"}
SPEED_ZH = {"slow": "慢速", "medium": "中速", "fast": "快速"}
ANGLE_ZH = {"eye_level": "平视", "high": "俯拍", "low": "仰拍", "overhead": "顶拍"}
RATIO_ZH = {"15pct": "主体占画面约15%", "30pct": "主体占画面约30%",
            "50pct": "主体占画面约50%", "80pct": "主体占画面约80%"}
ANCHOR_ZH = {"center": "居中构图", "thirds_left": "三分法左锚点", "thirds_right": "三分法右锚点"}

TEXT_CHANNEL = "vpo:delivery.control_channel.text"


def _tail(token):          # vpo:cine.xxx.yyy → yyy
    return str(token).rsplit(".", 1)[-1]


def _zh(map_, token, default=""):
    return map_.get(_tail(token), default)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(path: Path, buf=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# =====================================================================
# 编译器①：意图 → prompt
# =====================================================================
def compile_prompt(shot: dict, intents_by_id: dict, default_pm: str):
    """从镜头 v2 + 引用的意图实例生成 prompt。返回 (prompt_compiled, segments, conflicts)。
    冲突第一版只登记不拦截（草案 §9：conflict 词表先验不足）。"""
    segs, conflicts = [], []
    refs = shot.get("intent_refs") or []
    ch = (shot.get("engine") or {}).get("channel", "")

    # 镜头语言段：CameraIntent 优先，缺则用 v1 camera 登记位
    cam = next((intents_by_id[r] for r in refs
                if (intents_by_id.get(r) or {}).get("intent_type") == "vpo:craft.intent_object.camera_intent"), None)
    if cam:
        parts = []
        if cam.get("shot_scale"):
            parts.append(_zh(SCALE_ZH, cam["shot_scale"], cam["shot_scale"]))
        if cam.get("camera_angle"):
            parts.append(_zh(ANGLE_ZH, cam["camera_angle"], cam["camera_angle"]) + "机位")
        if cam.get("movement"):
            mv = _zh(MOVE_ZH, cam["movement"], cam["movement"])
            sp = _zh(SPEED_ZH, cam.get("movement_speed", ""), "")
            parts.append(f"{mv}（{sp}）" if sp else mv)
        if cam.get("movement_direction"):
            parts.append(f"方向：{cam['movement_direction'].rsplit('.', 1)[-1]}")
        if cam.get("subject_frame_ratio"):
            parts.append(_zh(RATIO_ZH, cam["subject_frame_ratio"], ""))
        if cam.get("framing_anchor"):
            parts.append(_zh(ANCHOR_ZH, cam["framing_anchor"], ""))
        if parts:
            segs.append("镜头：" + "，".join(parts))
        if cam.get("hand_object_contact"):
            segs.append(f"手部约束：{cam['hand_object_contact'].get('constraint', '')}".rstrip("："))
    elif (shot.get("camera") or {}).get("movement"):
        parts = [str(shot["camera"]["movement"])]
        if shot["camera"].get("description"):
            parts.append(shot["camera"]["description"])
        segs.append("镜头：" + "，".join(parts))

    # 主体段（v1 characters 登记位；image 通道 ref_image 不进 prompt —— 身份走参考图）
    descs = [c.get("desc") for c in (shot.get("characters") or []) if c.get("desc")]
    if descs:
        segs.append("主体：" + "；".join(descs))

    # 语义段：text 通道意图的 predicate（D0 文本控语义）
    sems = []
    for r in refs:
        it = intents_by_id.get(r)
        if not it:
            continue
        chans = it.get("control_channel") or []
        if any(str(c) == TEXT_CHANNEL for c in chans) and it.get("predicate"):
            sems.append(it["predicate"])
    if sems:
        segs.append("语义：" + "；".join(sems))

    # 场景说明段：v1 camera.description 自由文本
    if (shot.get("camera") or {}).get("description"):
        segs.append(f"运镜说明：{shot['camera']['description']}")

    # 台词段：非 avatar 通道才进 prompt（avatar 通道 speech 是 TTS 输入源，不重复进 prompt）
    audio = shot.get("audio") or {}
    if audio.get("speech") and not ch.startswith("api_vidu_avatar"):
        segs.append(f"台词（配音提示）：{audio['speech']}")
    if audio.get("music"):
        segs.append(f"氛围音乐：{audio['music']}")

    pm = shot.get("prompt_mode") or default_pm
    if pm == "compiled":
        prompt = "\n".join(segs)
    elif pm == "hybrid":
        base = shot.get("prompt") or ""
        patch = "；".join(sems) if sems else ""
        conflicts.append(f"hybrid：手写底稿 {len(base)} 字，追加 text 通道意图补丁 {len(sems)} 条"
                         + (f"（{patch[:60]}…）" if patch else "（无补丁）"))
        prompt = base + ("\n[意图补丁] " + "\n".join(segs) if segs else "")
    else:
        prompt = ""
    return prompt, segs, conflicts


# =====================================================================
# 编译器②：投影 v1 ShotSpec
# =====================================================================
V1_FIELDS = ["shot_id", "axis", "duration_s", "aspect", "resolution", "negative_prompt",
             "seed", "characters", "camera", "audio"]


# v2 超集值 → v1 冻结契约枚举的投影降级（v1 shot.schema.json enum 不含 G9a；不静默，进 notes+警告）
AXIS_V1_FALLBACK = {"G9a": "G9"}


def project_v1_shot(shot: dict, prompt: str, prompt_hash: str, intent_vers: list) -> dict:
    ch = (shot.get("engine") or {}).get("channel", "")
    if ch in CHANNEL_MODEL:
        pref, model = CHANNEL_MODEL[ch]
    else:
        pref = "api" if ch.startswith("api_") else "local"
        model = ch
    v1 = {"schema_version": "1.0"}
    for k in V1_FIELDS:
        if shot.get(k) is not None:
            v1[k] = shot[k]
    if v1.get("axis") in AXIS_V1_FALLBACK:
        v1["axis"] = AXIS_V1_FALLBACK[v1["axis"]]       # G9a→G9：口播子轴降级到 v1 九轴母轴
    v1["prompt"] = prompt
    v1["engine_hint"] = {"preferred": pref, "model": model}
    note_bits = []
    if shot.get("notes"):
        note_bits.append(str(shot["notes"]))
    if shot.get("axis") in AXIS_V1_FALLBACK:
        note_bits.append(f"vdl2:axis_v2={shot['axis']}")   # v1 enum 无 G9a，原值留痕
    if prompt_hash:
        note_bits.append(f"vdl2:prompt_hash={prompt_hash}")
    if intent_vers:
        note_bits.append("vdl2:intents=" + ",".join(intent_vers))
    v1["notes"] = " | ".join(note_bits)
    return v1


def validate_v1_shot(v1: dict):
    import jsonschema
    schema = json.loads(V1_SHOT_SCHEMA.read_text(encoding="utf-8"))
    errs = sorted(jsonschema.Draft7Validator(schema).iter_errors(v1),
                  key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(x) for x in e.absolute_path) or '<root>'}: {e.message[:300]}"
            for e in errs]


# =====================================================================
# 主编译流程
# =====================================================================
def compile_package(pkg_path: Path, out_dir: Path, vpo_root: Path = DEFAULT_VPO_ROOT):
    crep = {"package": str(pkg_path), "compiled_at": now_iso(), "compiler": COMPILER_ID,
            "ok": False, "errors": [], "warnings": [], "conflicts": [], "outputs": {}, "stats": {}}

    # ---- 前置校验（两道闸门 + R1-R6 + 跨引用）----
    vrep, pkg = validate_package(pkg_path, vpo_root)
    crep["validation"] = {"ok": vrep["ok"],
                          "gate_a_errors": vrep["gate_a"]["n_errors"],
                          "gate_b_errors": vrep["gate_b"]["n_errors"],
                          "total_errors": len(vrep["errors"]),
                          "warnings": len(vrep["warnings"])}
    crep["warnings"].extend(vrep["warnings"])
    if not vrep["ok"]:
        crep["errors"].extend(vrep["errors"])
        crep["outputs"]["validation_report"] = _write(out_dir, "compile_report.json", crep)
        return 2, crep

    intents_by_id = {}
    for it in pkg.get("intents") or []:
        iid = ((it or {}).get("identity") or {}).get("intent_id")
        if iid:
            intents_by_id[iid] = it
    acc_by_id = {sp.get("criterion_id"): sp for sp in (pkg.get("acceptance") or [])
                 if sp.get("criterion_id")}
    default_pm = pkg.get("default_prompt_mode", "hybrid")

    out_dir.mkdir(parents=True, exist_ok=True)
    src_sha = sha256_file(pkg_path)

    # ---- 编译器① + ②：逐镜 ----
    plan_shots, proj_manifest, rec_files = [], [], []
    for i, shot in enumerate(pkg.get("shots") or []):
        sid = shot.get("shot_id", f"#{i}")
        where = f"shots[{i}]({sid})"
        pm = shot.get("prompt_mode") or default_pm
        prompt, segs, conflicts = compile_prompt(shot, intents_by_id, default_pm)
        crep["conflicts"].extend(f"{where}: {c}" for c in conflicts)

        if pm == "compiled" and not prompt.strip():
            crep["errors"].append(f"{where}: prompt_mode=compiled 但编译器①产出了空 prompt（segments={len(segs)}）")
            continue
        if pm != "compiled" and not (shot.get("prompt") or "").strip():
            crep["errors"].append(f"{where}: prompt_mode={pm} 需要手写 prompt（v1 契约 prompt 必填非空）")
            continue
        # v1 投影的最终 prompt：compiled/hybrid 用编译器①产物，handwritten 用手写原稿；
        # prompt_hash 三态统一计算（缓存键成分 prompt_hash 对三态都有意义，草案 §3.2 #6）
        if pm == "handwritten":
            final_prompt = shot.get("prompt") or ""
        else:
            final_prompt = prompt
        prompt_hash = sha256_text(final_prompt) if final_prompt else ""

        intent_vers = []
        for r in shot.get("intent_refs") or []:
            it = intents_by_id.get(r) or {}
            ver = ((it.get("identity") or {}).get("version")) or "?"
            intent_vers.append(f"{r}@{ver}")

        v1 = project_v1_shot(shot, final_prompt, prompt_hash, intent_vers)
        if shot.get("axis") in AXIS_V1_FALLBACK:
            crep["warnings"].append(
                f"{where}: axis={shot['axis']} 超出 v1 冻结枚举，投影降级为 "
                f"{AXIS_V1_FALLBACK[shot['axis']]}（v2 原值留痕于 notes.axis_v2）")
        errs = validate_v1_shot(v1)
        if errs:
            crep["errors"].extend(f"{where}: v1 投影未过契约: {e}" for e in errs)
            continue
        rel = Path("shots_v1") / f"{sid}.json"
        _write(out_dir, rel, v1)
        rec_files.append(rel)

        ch = (shot.get("engine") or {}).get("channel", "")
        plan_shot = {
            "shot_id": sid, "prompt_mode": pm, "prompt_hash": prompt_hash,
            "engine": shot.get("engine") or {}, "cache": shot.get("cache") or {},
            "budget": shot.get("budget") or {},
            "acceptance_refs": shot.get("acceptance_refs") or [],
            "intent_refs": intent_vers, "continuity": shot.get("continuity") or {},
            "edit_ops": shot.get("edit_ops") or [], "v1_shot": str(rel).replace("\\", "/"),
        }
        if ch == "api_vidu_avatar":
            # G9a 口播专线执行提示（工程方案v3.1 §7-2 契约登记位；v1 shot 契约冻结不扩字段，
            # avatar 专属参数止步于 v2 执行计划侧）
            plan_shot["avatar"] = {
                "tts_input": (shot.get("audio") or {}).get("speech", ""),
                "image_ref": ((shot.get("characters") or [{}])[0]).get("ref_image"),
                "duration_follows": "audio",          # 成片时长 = ceil(音频秒)（V10 实测）
                "billing_rule": "1积分/s×ceil(音频秒)，失败不扣（b2_run.log credits=0）",
                "wallet_endpoint": "/ent/v2/credits", "watermark": False,
            }
        plan_shots.append(plan_shot)
        proj_manifest.append({
            "shot_id": sid,
            "intent_versions": intent_vers,
            "prompt_mode": pm, "prompt_hash": prompt_hash,
            "acceptance_refs": shot.get("acceptance_refs") or [],
            "v1_shot": str(rel).replace("\\", "/"),
            "model_hint": v1["engine_hint"]["model"],
        })

    # ---- L4 验收记录骨架（AcceptanceSpec 绑定；unknown≠pass）----
    n_rec = 0
    for ps in plan_shots:
        sid = ps["shot_id"]
        for ref in ps["acceptance_refs"]:
            sp = acc_by_id.get(ref)
            if not sp:
                continue                                    # 校验器已拦悬空引用，这里双保险
            rec = {
                "schema": "https://vpo.example/schemas/v1/l4/acceptance-record.schema.json",
                "criterion_ref": {"criterion_id": sp["criterion_id"], "version": sp["version"]},
                "artifact_ref": f"clip:{sid}@{ps['engine'].get('channel', 'unknown')}",
                "artifact_revision": ps["prompt_hash"] or "pending-generation",
                "target_ref": sid,
                "status": "vpo:delivery.record_status.unknown",
                "evaluator_id": sp.get("detector_id", ""),
                "evaluator_version": sp.get("detector_version", ""),
            }
            rel = Path("acceptance_records") / f"{ref}__{sid}.json"
            _write(out_dir, rel, rec)
            n_rec += 1
            rec_files.append(rel)

    # ---- 槽位定义（模板线）----
    tpl = pkg.get("template") or {}
    if tpl:
        slots_out = []
        for slot in tpl.get("slots") or []:
            s = dict(slot)
            val, perr = resolve_path(pkg, s.get("path", ""))
            s["current_value"] = val
            if perr:
                crep["errors"].append(f"template.slots[{s.get('name')}]: path 解析失败 {perr}")
            elif s.get("required") and (val is None or val == ""):
                crep["warnings"].append(
                    f"template.slots[{s.get('name')}]: required 槽位当前值为空（模板待填充；填充后重编译）")
            slots_out.append(s)
        slots_doc = {"schema_version": "2.0", "work_id": pkg.get("work_id"),
                     "template_id": tpl.get("template_id"),
                     "description": tpl.get("description", ""), "slots": slots_out,
                     "compiler": COMPILER_ID, "compiled_at": now_iso()}
        _write(out_dir, Path("slots.json"), slots_doc)
        rec_files.append(Path("slots.json"))
        crep["stats"]["n_slots"] = len(slots_out)

    # ---- 执行计划 ----
    plan = {
        "schema_version": "2.0", "work_id": pkg.get("work_id"), "compiled_at": now_iso(),
        "compiler": COMPILER_ID,
        "source_package": {"path": str(pkg_path), "sha256": src_sha},
        "validation": crep["validation"],
        "default_prompt_mode": default_pm,
        "budget": pkg.get("budget") or {},
        "deliverable": (((pkg.get("deliverable") or {}).get("identity") or {}).get("intent_id"))
                       if pkg.get("deliverable") else None,
        "post_ops": [
            ({"intent_ref": po.get("intent_ref"),
              **({"identity": po["identity"]} if po.get("identity") else {})}
             | {"run_after": po.get("run_after") or []})
            for po in (pkg.get("post_ops") or [])
        ],
        "shots": plan_shots,
        "projection_manifest": proj_manifest,           # 草案 §7.4 投影清单（对账用）
    }
    _write(out_dir, Path("execution_plan.json"), plan)
    rec_files.append(Path("execution_plan.json"))

    crep["outputs"] = {"execution_plan": "execution_plan.json",
                       "shots_v1": [str(p).replace("\\", "/") for p in rec_files
                                    if str(p).startswith("shots_v1")],
                       "acceptance_records": [str(p).replace("\\", "/") for p in rec_files
                                              if str(p).startswith("acceptance_records")],
                       "slots": "slots.json" if tpl else None,
                       "n_v1_shots": len(proj_manifest), "n_acceptance_records": n_rec}
    crep["stats"].update({"n_shots": len(plan_shots), "n_acceptance_records": n_rec})
    crep["ok"] = not crep["errors"]
    _write(out_dir, Path("compile_report.json"), crep)
    return (0 if crep["ok"] else 1), crep


def _write(out_dir: Path, rel: Path, doc: dict) -> Path:
    p = out_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return rel


def main():
    ap = argparse.ArgumentParser(description="VDL v2 编译器（校验 → 执行计划 + L4 骨架 + 槽位定义）")
    ap.add_argument("--pkg", required=True, help="VDL v2 包 YAML 路径")
    ap.add_argument("--out-dir", required=True, help="编译产物输出目录")
    ap.add_argument("--vpo-root", default=str(DEFAULT_VPO_ROOT),
                    help=f"VPO schemas 根目录（默认 {DEFAULT_VPO_ROOT}，只读）")
    args = ap.parse_args()
    try:
        code, crep = compile_package(Path(args.pkg), Path(args.out_dir), Path(args.vpo_root))
    except Exception as e:
        print(f"[vdl2_compile] FATAL {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    print(f"[vdl2_compile] {'OK' if code == 0 else 'FAIL(exit %d)' % code} "
          f"v1_shots={crep['outputs'].get('n_v1_shots', 0)} "
          f"acceptance_records={crep['outputs'].get('n_acceptance_records', 0)} "
          f"errors={len(crep['errors'])} warnings={len(crep['warnings'])}")
    for e in crep["errors"]:
        print(f"  [ERROR] {e}")
    for w in crep["warnings"]:
        print(f"  [WARN ] {w}")
    return code


if __name__ == "__main__":
    sys.exit(main())
