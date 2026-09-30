"""镜头卡与叙事模板的 JSON 校验 (SPECS §5.2 / §5.7)。

校验失败抛 SchemaError, 错误信息全部中文, 一次性收集所有错误。
风险表(强制): subject 涉及人脸/手部/多主体/文字数字 → 必须 lane=ken_burns, 否则拒绝。
negative 必含人脸/手/文字三类语义项。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

LANES = {"first_frame_i2v", "t2v", "ken_burns", "future_3d_guided"}
ORIENTATIONS = {"portrait", "landscape"}
FALLBACK_MOTIONS = {"zoom_in_1.06", "zoom_out", "pan_left", "pan_right"}
CAMERA_KEYS = ("scale", "angle", "motion", "depth")
ACCEPTANCE_KEYS = (
    "clip_ref_min",
    "clip_text_min",
    "temporal_clip_min",
    "vlm_overall_min",
    "vlm_defect_max",
    "duration_tol",
)
REQUIRED_FIELDS = (
    "shot_id",
    "narrative_slot",
    "lane",
    "orientation",
    "duration_sec",
    "resolution",
    "fps",
    "camera",
    "subject",
    "prompt_en",
    "first_frame_asset",
    "negative",
    "n_best",
    "retry_max",
    "acceptance",
    "fallback",
)

# ---- 风险表关键词 (中英混合; 英文按词边界匹配, 中文按子串匹配) ----
RISK_KEYWORDS: dict[str, list[str]] = {
    "人脸": ["人脸", "面孔", "面部", "脸庞", "脸部", "face", "faces", "facial"],
    "手部": ["手部", "手指", "手掌", "手势", "双手", "hands", "hand", "fingers", "finger"],
    "多主体": ["多主体", "多人", "两个人", "两个", "两位", "三个人", "三个", "人群", "众人", "多个人物", "多个主体", "多个人",
             "crowd", "group of people", "two people", "multiple people", "several people"],
    "文字数字": ["文字", "数字", "字幕", "标语", "价签", "价格牌", "菜单", "招牌字", "标牌",
              "text", "numbers", "number", "letters", "letter", "price tag", "signage", "subtitle"],
}

# negative 必须覆盖的三类语义项
NEGATIVE_REQUIRED: dict[str, list[str]] = {
    "人脸": ["face", "人脸", "面孔", "面部"],
    "手部": ["hand", "hands", "finger", "fingers", "手指", "手"],
    "文字": ["text", "文字", "字幕", "watermark", "logo", "水印", "水印文字"],
}


class SchemaError(ValueError):
    """镜头卡/模板校验失败。message 为中文, errors 为逐条中文错误列表。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("镜头卡校验失败: " + "; ".join(errors))


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _match_keyword(text: str, kw: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", kw):
        return kw in text
    return re.search(rf"\b{re.escape(kw)}\b", text, flags=re.IGNORECASE) is not None


def risk_categories(subject_text: str) -> list[str]:
    """返回 subject 文本命中的风险类别列表 (人脸/手部/多主体/文字数字)。"""
    hits = []
    for cat, kws in RISK_KEYWORDS.items():
        if any(_match_keyword(subject_text, kw) for kw in kws):
            hits.append(cat)
    return hits


def _validate_risk(card: dict, errors: list[str]) -> None:
    subject = card.get("subject") or {}
    text = " ".join(
        str(subject.get(k, "")) for k in ("type", "desc_zh", "desc_en") if subject.get(k)
    )
    hits = risk_categories(text)
    if hits and card.get("lane") != "ken_burns":
        errors.append(
            f"高风险主体(涉及{'、'.join(hits)})禁止进入生成车道, "
            f"必须 lane=ken_burns (当前 lane={card.get('lane')!r})"
        )


def _validate_negative(negative, errors: list[str]) -> None:
    if not isinstance(negative, list) or not negative or not all(isinstance(x, str) for x in negative):
        errors.append("negative 必须为非空字符串列表")
        return
    joined = " | ".join(negative)
    for cat, kws in NEGATIVE_REQUIRED.items():
        if not any(_match_keyword(joined, kw) for kw in kws):
            errors.append(f"negative 缺少必含的{cat}语义项 (需覆盖人脸/手/文字)")


def validate_shotcard(data: dict) -> dict:
    """校验镜头卡 dict, 通过则返回深拷贝。所有错误以中文一次性抛出。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        raise SchemaError(["镜头卡必须是 JSON 对象"])

    for f in REQUIRED_FIELDS:
        if f not in data:
            errors.append(f"缺少必填字段: {f}")
    unknown = sorted(set(data) - set(REQUIRED_FIELDS))
    if unknown:
        errors.append(f"存在未定义字段(字段定死): {unknown}")

    if errors:
        raise SchemaError(errors)

    if not isinstance(data["shot_id"], str) or not data["shot_id"].strip():
        errors.append("shot_id 必须为非空字符串")
    if not isinstance(data["narrative_slot"], str) or not data["narrative_slot"].strip():
        errors.append("narrative_slot 必须为非空字符串")
    if data["lane"] not in LANES:
        errors.append(f"lane 必须是 {sorted(LANES)} 之一(生成车道枚举), 当前: {data['lane']!r}")
    if data["orientation"] not in ORIENTATIONS:
        errors.append(f"orientation 必须是 {sorted(ORIENTATIONS)} 之一, 当前: {data['orientation']!r}")

    d = data["duration_sec"]
    if not _is_num(d) or d <= 0 or d > 60:
        errors.append("duration_sec 必须为 (0, 60] 内的数值")
    res = data["resolution"]
    if (
        not isinstance(res, list)
        or len(res) != 2
        or not all(isinstance(x, int) and not isinstance(x, bool) and 64 <= x <= 4096 for x in res)
    ):
        errors.append("resolution 必须为 [宽, 高] 两个 64..4096 的整数")
    fps = data["fps"]
    if not isinstance(fps, int) or isinstance(fps, bool) or not (1 <= fps <= 60):
        errors.append("fps 必须为 1..60 的整数")

    cam = data["camera"]
    if not isinstance(cam, dict) or any(k not in cam for k in CAMERA_KEYS):
        errors.append(f"camera 必须为含 {list(CAMERA_KEYS)} 的对象")
    subj = data["subject"]
    if not isinstance(subj, dict) or "type" not in subj or "desc_zh" not in subj:
        errors.append("subject 必须为含 type 与 desc_zh 的对象")
    if not isinstance(data["prompt_en"], str) or not data["prompt_en"].strip():
        errors.append("prompt_en 必须为非空字符串")
    if not isinstance(data["first_frame_asset"], str) or not data["first_frame_asset"].strip():
        errors.append("first_frame_asset 必须为非空路径字符串")

    _validate_negative(data["negative"], errors)

    nb = data["n_best"]
    if not isinstance(nb, int) or isinstance(nb, bool) or not (1 <= nb <= 8):
        errors.append("n_best 必须为 1..8 的整数")
    rm = data["retry_max"]
    if not isinstance(rm, int) or isinstance(rm, bool) or not (0 <= rm <= 5):
        errors.append("retry_max 必须为 0..5 的整数")

    acc = data["acceptance"]
    if not isinstance(acc, dict) or any(k not in acc for k in ACCEPTANCE_KEYS):
        errors.append(f"acceptance 必须含 {list(ACCEPTANCE_KEYS)}")
    else:
        for k in ACCEPTANCE_KEYS:
            if k == "duration_tol":
                if not _is_num(acc[k]) or acc[k] <= 0:
                    errors.append("acceptance.duration_tol 必须为正数")
            elif not _is_num(acc[k]) or not (0.0 <= acc[k] <= 1.0):
                errors.append(f"acceptance.{k} 必须为 0..1 数值")

    fb = data["fallback"]
    fb_ok = isinstance(fb, dict)
    if not fb_ok:
        errors.append("fallback 必须为对象")
    else:
        for k in ("type", "asset", "motion", "duration_sec"):
            if k not in fb:
                errors.append(f"fallback 缺少字段: {k}")
        if fb_ok and fb.get("type") != "ken_burns":
            errors.append("fallback.type 本期只支持 ken_burns")
        if fb_ok and fb.get("motion") not in FALLBACK_MOTIONS:
            errors.append(f"fallback.motion 必须是 {sorted(FALLBACK_MOTIONS)} 之一")

    if not errors:
        _validate_risk(data, errors)

    if errors:
        raise SchemaError(errors)
    return copy.deepcopy(data)


def load_shotcard(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return validate_shotcard(data)


# ---------------- 叙事模板 (SPECS §5.7) ----------------

TEMPLATE_REQUIRED = ("template_id", "name_zh", "duration_range", "orientation", "variables", "numbers", "scenes")
SCENE_REQUIRED = ("slot", "narrative_slot", "duration_sec", "narration", "role")


def total_duration(scenes: list[dict]) -> float:
    return round(sum(s["duration_sec"] for s in scenes), 6)


def validate_narrative_template(data: dict) -> dict:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise SchemaError(["叙事模板必须是 JSON 对象"])
    for f in TEMPLATE_REQUIRED:
        if f not in data:
            errors.append(f"缺少必填字段: {f}")
    if errors:
        raise SchemaError(errors)

    dr = data["duration_range"]
    if not isinstance(dr, list) or len(dr) != 2 or not all(_is_num(x) and x > 0 for x in dr):
        errors.append("duration_range 必须为 [最小秒, 最大秒]")
    if data["orientation"] not in ORIENTATIONS:
        errors.append(f"orientation 必须是 {sorted(ORIENTATIONS)} 之一")
    for k in ("variables", "numbers"):
        if not isinstance(data[k], dict):
            errors.append(f"{k} 必须为对象(数字字段独立存放于 numbers)")

    scenes = data["scenes"]
    if not isinstance(scenes, list) or not scenes:
        errors.append("scenes 必须为非空数组")
    else:
        allowed_vars = set(data["variables"]) | set(data["numbers"])
        for i, sc in enumerate(scenes):
            for f in SCENE_REQUIRED:
                if f not in sc:
                    errors.append(f"scenes[{i}] 缺少字段: {f}")
            if not _is_num(sc.get("duration_sec")) or sc.get("duration_sec", 0) <= 0:
                errors.append(f"scenes[{i}].duration_sec 必须为正数")
            narration = sc.get("narration", "")
            for var in re.findall(r"\{(\w+)\}", narration):
                if var not in allowed_vars:
                    errors.append(
                        f"scenes[{i}].narration 引用了未定义变量 {{{var}}} "
                        f"(只允许 variables/numbers 中已定义的字段)"
                    )
        if not errors:
            total = total_duration(scenes)
            lo, hi = data["duration_range"]
            if not (lo <= total <= hi):
                errors.append(f"各幕时长合计 {total}s 超出区间 [{lo}, {hi}]s")

    if errors:
        raise SchemaError(errors)
    return copy.deepcopy(data)


def load_template(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return validate_narrative_template(data)
