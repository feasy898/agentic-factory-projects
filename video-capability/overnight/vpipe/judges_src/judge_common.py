#!/usr/bin/env python3
"""Shared constants & helpers for the three judge batch runners (blind protocol).

Protocol JSON per clip (frozen by 边界测试方案.md §2.3):
  {"clip_id","defect_detected","defect_types","confidence","spans","notes"}
"""
import json
import os
import re

DEFECTS = ["frame_freeze", "flicker", "color_shift", "face_blur",
           "garble_text", "temporal_swap", "pixelate", "ghosting"]

DEFECT_ZH = {
    "frame_freeze": "画面定格（数秒不动）",
    "flicker": "帧闪（帧间明暗/内容快速交替闪烁）",
    "color_shift": "整体色偏（颜色异常偏移）",
    "face_blur": "人脸模糊（人脸区域异常模糊）",
    "garble_text": "乱码文字（画面出现乱码/无意义文字）",
    "temporal_swap": "段落错乱（时序跳变/场景切换不连贯）",
    "pixelate": "像素化（画面局部马赛克/像素块）",
    "ghosting": "拖影（运动残影/重影）",
}

THRESHOLD = 0.5


def omnijev_questions():
    """8 条缺陷 noul（「该视频是否存在<缺陷>」）+ 1 条总体 noul。"""
    q = {}
    for k in DEFECTS:
        q["q_" + k] = {"type": "noul",
                       "instructions": "该视频是否存在%s（%s）" % (DEFECT_ZH[k], k)}
    q["q_overall"] = {"type": "noul",
                      "instructions": "该视频是否存在上述任何一种缺陷或其他明显的画面异常/生成伪影"}
    return q


def visualjev_questions():
    """Visual-Jev 只支持 choice：同样 8+1 问，yes/no 二选一（单帧判定用）。"""
    qs = {}
    for k in DEFECTS:
        qs["q_" + k] = {"type": "choice",
                        "instructions": "该帧画面是否存在%s（%s）" % (DEFECT_ZH[k], k),
                        "criteria": {"yes": None, "no": None}}
    qs["q_overall"] = {"type": "choice",
                       "instructions": "该帧画面是否存在任何明显的缺陷或生成伪影",
                       "criteria": {"yes": None, "no": None}}
    return {"questions": qs, "state": ""}


def protocol_from_probs(clip_id, probs, spans, notes, threshold=THRESHOLD):
    """OmniJev / Visual-Jev 概率 → 协议 JSON。
    probs: {"frame_freeze": p, ..., "overall": p}（overall 可为 None）。
    defect_detected = 任一 8 类概率超阈 或 overall 超阈；
    defect_types = 超阈的 8 类键；confidence = 全部概率最大值。"""
    p_types = {k: float(probs.get(k, 0.0)) for k in DEFECTS}
    p_overall = probs.get("overall")
    p_overall = None if p_overall is None else float(p_overall)
    types = [k for k in DEFECTS if p_types[k] > threshold]
    pool = list(p_types.values()) + ([p_overall] if p_overall is not None else [])
    detected = bool(types) or (p_overall is not None and p_overall > threshold)
    return {"clip_id": clip_id,
            "defect_detected": bool(detected),
            "defect_types": types,
            "confidence": round(max(pool), 4) if pool else 0.0,
            "spans": spans,
            "notes": notes}


def protocol_from_types(clip_id, types, confidence, spans, notes):
    """VideoChat3 文本解析 → 协议 JSON（types 可含 other）。"""
    types = [t for t in types if t in DEFECTS or t == "other"]
    return {"clip_id": clip_id,
            "defect_detected": len(types) > 0,
            "defect_types": types,
            "confidence": round(float(confidence), 4),
            "spans": spans,
            "notes": notes}


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def list_clips(clips_dir):
    out = []
    for name in sorted(os.listdir(clips_dir)):
        if name.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm")):
            out.append(os.path.join(clips_dir, name))
    return out


VC3_QA_PROMPT = (
    "请逐帧仔细检查该视频是否存在以下8种缺陷中的哪几种，并判断是否存在其他明显缺陷："
    "frame_freeze(画面定格数秒不动)、flicker(帧间明暗或内容快速交替闪烁)、"
    "color_shift(整体颜色异常偏色)、face_blur(人脸区域异常模糊)、"
    "garble_text(画面中出现乱码或无意义文字)、temporal_swap(段落或时序错乱、场景跳变不连贯)、"
    "pixelate(画面局部像素化或马赛克块)、ghosting(运动拖影或重影)。"
    "只输出一个JSON对象，不要输出其他内容，格式："
    "{\"defect_types\":[\"存在的缺陷英文键\"],\"other\":false,\"reason\":\"一句话依据\"}。"
    "缺陷英文键必须从上面8个中选；没有缺陷时 defect_types 为空数组、other 为 false。"
)


def parse_vc3_answer(text):
    """解析 VideoChat3 文本回答 → (types, other_flag, method, reason)。
    method: json=干净解析(conf 0.8) / keyword=关键词兜底(conf 0.5) / none(conf 0.3)。"""
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            raw_types = obj.get("defect_types") or []
            types = [t for t in raw_types if t in DEFECTS]
            other = bool(obj.get("other"))
            reason = str(obj.get("reason", ""))[:120]
            if other and "other" not in types:
                types = types + ["other"]
            return types, other, "json", reason
        except Exception:
            pass
    types = [t for t in DEFECTS if re.search(r"\b%s\b" % re.escape(t), text)]
    other = bool(re.search(r"其他明显缺陷|other", text, re.I)) and not types
    if types:
        return types, False, "keyword", ""
    if other:
        return ["other"], True, "keyword", ""
    return [], False, "none", ""
