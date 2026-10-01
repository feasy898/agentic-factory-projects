"""镜头卡与叙事模板的 JSON 校验 (SPECS §5.2 / §5.7; v4 三车道, SPECS_V2 §5.1-§5.5)。

校验失败抛 SchemaError, 错误信息全部中文, 一次性收集所有错误。
风险表(强制): subject 涉及人脸/手部/多主体/文字数字 → 必须 lane=ken_burns, 否则拒绝。
negative 必含人脸/手/文字三类语义项。
三车道规则(强制): 食物/产品 subject 禁止 pure_gen_short 且该车道时长限 1-2s;
evidence_asset 仅 evidence_transfer 车道可用且必填 (SPECS_V2 §5.2/§5.4)。
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

# v4 三车道重构 (SPECS_V2 §5.1): first_frame_i2v 保留(纯生成 I2V, v1 兼容); t2v 删除;
# 新增 pure_gen_short(环境氛围专用) / compositing_2d5(食物产品默认) / evidence_transfer(证据转移);
# ken_burns 不变; future_3d_guided 枚举位保留不实现。
LANES = {
    "first_frame_i2v",
    "pure_gen_short",
    "compositing_2d5",
    "evidence_transfer",
    "ken_burns",
    "future_3d_guided",
}
# 程序化/确定性车道: 生成层不涉及扩散模型对主体的重绘 (ken_burns/2.5D 视差合成为纯代码)
DETERMINISTIC_LANES = {"ken_burns", "compositing_2d5"}
# Wan 消耗型车道(生成期占用扩散模型): 预算守卫计数口径 (orchestrator 同源)
WAN_CONSUMING_LANES = {"first_frame_i2v", "pure_gen_short", "evidence_transfer"}
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
# v2/v4 可选字段:
# - expected_static_mask (SPECS_V2 §3-G7c): 静态区蒙版 PNG 路径(白=不该动的区域, 首帧坐标系)。
#   缺省 null → G7c 在门禁期由 SAM(首帧 subject 分割)反选自动生成。
# - evidence_asset (SPECS_V2 §5.4): evidence_transfer 车道的源视频路径
#   (用户实拍视频或合成测试源); 其余车道必须为 null。
OPTIONAL_FIELDS = ("expected_static_mask", "evidence_asset")

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

# ---- 食物/产品红线 (SPECS_V2 §5.2: 食物镜头禁止进入 pure_gen_short 车道) ----
# 判定面 = subject.type + subject.desc_zh/desc_en (不含 prompt_en——场景 prompt 中的
# "hotpot restaurant" 属环境语义而非主体; subject 字段应描述主体本身)。
# 中文按子串匹配, 英文按词边界匹配 (与 risk 表同口径)。命中宁按食物处理(不对称原则)。
FOOD_SUBJECT_TYPES = {"food", "product"}
FOOD_SUBJECT_KEYWORDS: list[str] = [
    "食物", "美食", "菜品", "虾", "毛肚", "肥牛", "牛肉", "肉类", "锅底", "火锅",
    "汤底", "甜点", "甜品", "蛋糕", "糍粑", "饮品", "奶茶", "饮料", "果汁", "食材",
    "虾滑", "肉卷", "米饭", "粥", "烧烤", "炸鸡",
    "food", "shrimp", "tripe", "hot pot", "hotpot", "broth", "beef", "meatball",
    "dessert", "cake", "drink", "beverage", "soup", "noodle", "dumpling",
]
# pure_gen_short 时长红线 (SPECS_V2 §5.2: 漂移随时间累积, 压缩到 1-2s)
PUREGEN_DURATION_RANGE = (1.0, 2.0)


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


def is_food_or_product_subject(card: dict) -> bool:
    """判定主体是否食物/产品类 (SPECS_V2 §5.2 pure_gen_short 红线的判定函数)。

    判定面: subject.type ∈ {food, product} 直判; 否则 subject 的 type/desc_zh/desc_en
    文本命中食物关键词表 → 判为食物 (宁可误判, 红线从紧)。
    """
    subj = card.get("subject") or {}
    stype = str(subj.get("type") or "").strip().lower()
    if stype in FOOD_SUBJECT_TYPES:
        return True
    text = " ".join(str(subj.get(k, "")) for k in ("type", "desc_zh", "desc_en") if subj.get(k))
    return any(_match_keyword(text, kw) for kw in FOOD_SUBJECT_KEYWORDS)


def _validate_lane_rules(card: dict, errors: list[str]) -> None:
    """三车道专属规则 (SPECS_V2 §5.1-§5.4)。"""
    lane = card.get("lane")
    if lane == "pure_gen_short":
        if is_food_or_product_subject(card):
            errors.append(
                "食物/产品类 subject 禁止进入 pure_gen_short 车道 (SPECS_V2 §5.2 红线: "
                "纯生成的食物必形变; 改用 compositing_2d5 或 evidence_transfer)"
            )
        d = card.get("duration_sec")
        lo, hi = PUREGEN_DURATION_RANGE
        if _is_num(d) and not (lo <= float(d) <= hi):
            errors.append(
                f"pure_gen_short 时长必须 {lo}-{hi}s (SPECS_V2 §5.2: 漂移随时间累积), 当前 {d}s"
            )
    if lane == "evidence_transfer":
        ea = card.get("evidence_asset")
        if not (isinstance(ea, str) and ea.strip()):
            errors.append("evidence_transfer 车道必须提供 evidence_asset 源视频路径 (SPECS_V2 §5.4)")
    elif card.get("evidence_asset") is not None:
        errors.append(f"evidence_asset 仅 evidence_transfer 车道可用 (当前 lane={lane!r})")


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
    unknown = sorted(set(data) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS))
    if unknown:
        errors.append(f"存在未定义字段(字段定死): {unknown}")

    if errors:
        raise SchemaError(errors)

    esm = data.get("expected_static_mask")
    if esm is not None and (not isinstance(esm, str) or not esm.strip()):
        errors.append("expected_static_mask 必须为非空字符串(静态区蒙版 PNG 路径)或 null")

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
        _validate_lane_rules(data, errors)

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
