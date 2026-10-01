#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen.py — 四平台爆款文案骨架确定性引擎（oracle 参照实现）

命令行契约：
    python gen.py --platform <dy|xhs|wx|video> --topic <主题> --points <卖点json> --outdir <dir>

产物（<outdir> 内，文件名冻结）：
    骨架.md          人读的爆款结构骨架（含占位符统计摘要）
    structure.json   机器可读的结构要素清单与占位符统计

确定性（MUST）：无时间戳、无随机数；同输入连跑两次，两份产物逐字节一致。

退出码：
    0  成功，写入两份产物
    2  参数非法（platform 非法 / topic 为空 / points 不可解析或不是字符串列表），
       stderr 打印中文错误信息，不产生产物、不建产物目录
"""

import argparse
import json
import os
import re
import sys

TEMPLATE_VERSION = "1.0"

PLATFORMS = {
    "dy": {"name": "抖音口播稿", "structure": "3秒钩子 + 痛点 + 价值点×3 + CTA"},
    "xhs": {"name": "小红书图文", "structure": "标题带数字 + emoji规则 + 正文分块 + 标签组"},
    "wx": {"name": "公众号文章", "structure": "引子 + 三段论 + 金句收尾"},
    "video": {"name": "短视频分镜表", "structure": "分镜表：时间轴/画面/口播/字幕"},
}

# 占位符形如 【占位:xxx】；括号内为待人工/AI 补写的槽位说明
PLACEHOLDER_RE = re.compile(r"【占位:([^】]*)】")


def fail(msg: str):
    print("[gen.py] 错误：%s" % msg, file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- 输入解析

def load_points(spec: str):
    """--points 接受：JSON 文件路径（纯列表，或含 points 键的对象）或内联 JSON 字符串。"""
    raw = None
    if os.path.isfile(spec):
        try:
            with open(spec, "r", encoding="utf-8-sig") as f:
                raw = f.read()
        except OSError as e:
            fail("卖点文件无法读取：%s（%s）" % (spec, e))
    else:
        raw = spec
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        fail("--points 不是合法 JSON（既非可读文件，也非内联 JSON）：%r" % spec[:80])
    if isinstance(data, dict):
        if "points" not in data:
            fail("--points 指向的 JSON 对象缺少 points 键：%r" % (list(data.keys()),))
        data = data["points"]
    if not isinstance(data, list):
        fail("--points 解析结果不是列表（got %s）" % type(data).__name__)
    for i, item in enumerate(data, 1):
        if not isinstance(item, str):
            fail("--points 第 %d 项不是字符串（got %s）" % (i, type(item).__name__))
    return [p.strip() for p in data]


def normalize_points(points):
    """规整为恰好 3 条（模板冻结为价值点×3）：不足用占位补齐，超出截断并记录。"""
    used, filled_flags = [], []
    for i in range(3):
        if i < len(points) and points[i]:
            used.append(points[i])
            filled_flags.append(True)
        else:
            used.append(None)
            filled_flags.append(False)
    unused = points[3:]
    return used, filled_flags, unused


def point_slot(idx: int, val):
    """卖点槽位：有值填值，缺失则落占位符。"""
    return val if val else "【占位:价值点%d】" % idx


def clean_tag(text: str) -> str:
    """话题标签用：去掉 # 与所有空白。"""
    return re.sub(r"[\s#]+", "", text)


# ---------------------------------------------------------------- 骨架构建
# 每个 element：{id, name, text, filled_from_input, meta}

def build_dy(topic, pts, filled, unused):
    p1, p2, p3 = (point_slot(i + 1, v) for i, v in enumerate(pts))
    els = []
    els.append({
        "id": "hook_3s", "name": "3秒钩子（0-3s）", "order": 1,
        "text": "别划走！还在为「%s」反复内耗的人，这条视频就是给你准备的——【占位:可替换为你的原创钩子强句，一句制造好奇或冲突】" % topic,
        "filled_from_input": ["topic"],
        "meta": {"beat": "0-3秒留住人：反问+利益点，语速快、重音落在主题词"},
    })
    els.append({
        "id": "pain_point", "name": "痛点共鸣", "order": 2,
        "text": "我太懂这种痛了：【占位:痛点场景，写目标人群最扎心的一个具体瞬间】。不是你不努力，是方法从一开始就错了。",
        "filled_from_input": [],
        "meta": {"beat": "说中一件事，让观众对号入座"},
    })
    for i, (pv, ok) in enumerate(zip(pts, filled), 1):
        els.append({
            "id": "value_%d" % i, "name": "价值点%d" % i, "order": 2 + i,
            "text": "第%s招：%s。【占位:一句话展开：怎么做/效果/案例】" % ("一二三"[i - 1], point_slot(i, pv)),
            "filled_from_input": (["point#%d" % i] if ok else []),
            "meta": {"beat": "一条卖点一句展开，信息密度拉满"},
        })
    els.append({
        "id": "cta", "name": "行动号召（CTA）", "order": 6,
        "text": "方法就这三条，现在就去用。觉得有用就点赞收藏，评论区扣「1」，我把【占位:配套资料/下期选题】整理给你。",
        "filled_from_input": [],
        "meta": {"beat": "点赞+收藏+评论三连指令，给一个扣词降低互动门槛"},
    })
    return els


def build_xhs(topic, pts, filled, unused):
    p1, p2, p3 = (point_slot(i + 1, v) for i, v in enumerate(pts))
    tag_topic = clean_tag(topic)
    els = []
    els.append({
        "id": "title", "name": "标题（带数字）", "order": 1,
        "text": "🔥亲测有效｜%s的3个方法，【占位:目标人群，如：打工人/新手宝妈】看完直接抄作业" % topic,
        "filled_from_input": ["topic"],
        "meta": {"emoji": "🔥", "rule": "标题带数字（3=价值点数，模板冻结为3）+人群词，emoji 置顶"},
    })
    els.append({
        "id": "hook_block", "name": "正文·开头钩子块", "order": 2,
        "text": "✅ 开头钩子\n%s这件事，我真的走过太多弯路——【占位:一句真实经历/翻车现场】。这篇一次性讲透，先收藏再看！" % topic,
        "filled_from_input": ["topic"],
        "meta": {"emoji": "✅", "rule": "钩子块固定 ✅：身份代入+收藏指令"},
    })
    for i, (pv, ok) in enumerate(zip(pts, filled), 1):
        els.append({
            "id": "point_block_%d" % i, "name": "正文·干货块%d" % i, "order": 2 + i,
            "text": "💡 干货%d｜%s\n【占位:2-3步操作拆解，越具体越好】" % (i, point_slot(i, pv)),
            "filled_from_input": (["point#%d" % i] if ok else []),
            "meta": {"emoji": "💡", "rule": "干货块固定 💡：小标题=卖点，正文=步骤"},
        })
    els.append({
        "id": "summary_block", "name": "正文·总结块", "order": 6,
        "text": "📌 划重点\n%s的核心就三点：%s、%s、%s。【占位:一句互动引导，如：你最想先试哪个？评论区聊聊】" % (topic, p1, p2, p3),
        "filled_from_input": ["topic"] + ["point#%d" % (i + 1) for i in range(3) if filled[i]],
        "meta": {"emoji": "📌", "rule": "总结块固定 📌：三点复述+互动引导"},
    })
    els.append({
        "id": "tag_group", "name": "标签组（5个）", "order": 7,
        "text": "#%s #干货分享 #方法论 #自我提升 【占位:2个垂直领域标签，如：#时间管理 #精力管理】" % tag_topic,
        "filled_from_input": ["topic(派生标签)"],
        "meta": {"emoji": "🏷️", "rule": "标签组=主题大词+流量泛词+垂直长尾，首标签由主题派生"},
    })
    return els


def build_wx(topic, pts, filled, unused):
    p1, p2, p3 = (point_slot(i + 1, v) for i, v in enumerate(pts))
    els = []
    els.append({
        "id": "lead_in", "name": "引子", "order": 1,
        "text": "【占位:用一个具体场景/对话/新闻切入，150字左右】——这背后，其实是同一个问题：%s。" % topic,
        "filled_from_input": ["topic"],
        "meta": {"beat": "场景化开场，把读者拉进问题现场"},
    })
    els.append({
        "id": "thesis_what", "name": "三段论·一（是什么）", "order": 2,
        "text": "一、是什么\n%s的本质，不是【占位:常见误解】，而是【占位:一句话给出你的定义】。" % topic,
        "filled_from_input": ["topic"],
        "meta": {"beat": "先破后立，给出定义"},
    })
    els.append({
        "id": "thesis_why", "name": "三段论·二（为什么）", "order": 3,
        "text": "二、为什么\n大多数人在%s上反复失败，根源有三：【占位:根因1】；【占位:根因2】；【占位:根因3】。" % topic,
        "filled_from_input": ["topic"],
        "meta": {"beat": "归因，三条根因对齐后文三个抓手"},
    })
    how_lines = ["落到操作层面，给你三个抓手："]
    for i, (pv, ok) in enumerate(zip(pts, filled), 1):
        how_lines.append("%d. %s——【占位:展开：具体做法+一个例子】" % (i, point_slot(i, pv)))
    els.append({
        "id": "thesis_how", "name": "三段论·三（怎么办）", "order": 4,
        "text": "三、怎么办\n" + "\n".join(how_lines),
        "filled_from_input": ["point#%d" % (i + 1) for i in range(3) if filled[i]],
        "meta": {"beat": "三个抓手一一对应三条根因，可执行"},
    })
    els.append({
        "id": "golden_ending", "name": "金句收尾", "order": 5,
        "text": "「%s这件事，【占位:金句主体——句式建议：真正的…不是靠…，而是靠…】」\n共勉。" % topic,
        "filled_from_input": ["topic"],
        "meta": {"beat": "一句话收束，可直接被读者摘抄转发"},
    })
    return els


# 分镜时长表（秒）：冻结为 6 镜 45 秒
SHOT_DURATIONS = [3, 7, 10, 10, 10, 5]


def _timeline():
    spans, t = [], 0
    for d in SHOT_DURATIONS:
        spans.append((t, t + d))
        t += d
    return spans


def _fmt(sec):
    return "%02d:%02d" % (sec // 60, sec % 60)


def build_video(topic, pts, filled, unused):
    p1, p2, p3 = (point_slot(i + 1, v) for i, v in enumerate(pts))
    spans = _timeline()

    def sub(i, ph, vo, st, tr, order, beat):
        return {
            "id": "shot_%d" % i, "name": "分镜%d（%s-%s）" % (i, _fmt(tr[0]), _fmt(tr[1])), "order": order,
            "text": "| %d | %s-%s | %s | %s | %s |" % (i, _fmt(tr[0]), _fmt(tr[1]), ph, vo, st),
            "filled_from_input": [],
            "meta": {"shot_no": i, "time_range": "%s-%s" % (_fmt(tr[0]), _fmt(tr[1])),
                     "duration_sec": tr[1] - tr[0], "visual": ph, "voiceover": vo, "subtitle": st, "beat": beat},
        }

    els = [
        sub(1, "【占位:画面1：冲突感特写/大字标题卡】",
            "别划走！还在为「%s」头疼？这条一次讲透。" % topic,
            "大字花字：%s，%d秒讲透" % (topic, sum(SHOT_DURATIONS)),
            spans[0], 1, "0-3秒钩子：画面+花字同时制造停顿"),
        sub(2, "【占位:画面2：痛点情景再现（空镜+人物）】",
            "你是不是也这样：【占位:痛点行为描述】？结果越努力越乱。",
            "字幕：【占位:痛点一句话字幕】",
            spans[1], 2, "痛点具象化：情景再现让观众对号入座"),
    ]
    for i, (pv, ok) in enumerate(zip(pts, filled), 1):
        els.append(sub(
            2 + i,
            "【占位:画面%d：卖点%d演示（实操/录屏/对比）】" % (2 + i, i),
            "第%s招，%s。【占位:口播补充一句效果】" % ("一二三"[i - 1], point_slot(i, pv)),
            "字幕要点：%s" % point_slot(i, pv),
            spans[1 + i], 2 + i, "价值点逐条演示：一镜一招，画面与口播同频"))
    els.append(sub(
        6, "【占位:画面6：结尾定格+关注引导贴纸】",
        "三条方法都在这了。点赞收藏，关注我，下期讲【占位:下期选题】。",
        "花字：关注不迷路",
        spans[5], 6, "CTA：口播+贴纸双引导"))
    for i, (pv, ok) in enumerate(zip(pts, filled), 1):
        if ok:
            els[1 + i]["filled_from_input"] = ["point#%d" % i]
    els[0]["filled_from_input"] = ["topic"]
    return els


BUILDERS = {"dy": build_dy, "xhs": build_xhs, "wx": build_wx, "video": build_video}


# ---------------------------------------------------------------- 统计与渲染

def count_placeholders(text: str):
    """返回（出现次数, 去重后按序 token 列表）。"""
    toks = PLACEHOLDER_RE.findall(text)
    seen = list(dict.fromkeys(toks))
    return len(toks), seen


def build_stats(elements):
    by_element, total_open, filled_slots = {}, 0, []
    for el in elements:
        n, _ = count_placeholders(el["text"])
        by_element[el["id"]] = n
        total_open += n
        filled_slots.extend(el["filled_from_input"])
    unique_tokens = []
    for el in elements:
        _, toks = count_placeholders(el["text"])
        for t in toks:
            if t not in unique_tokens:
                unique_tokens.append(t)
    return {
        "total_open": total_open,
        "total_filled_from_input": len(filled_slots),
        "by_element": by_element,
        "open_tokens_unique": unique_tokens,
        "filled_slots": filled_slots,
    }


def render_markdown(platform, topic, points_in, used, filled, unused, elements):
    info = PLATFORMS[platform]
    lines = []
    lines.append("# %s · 爆款骨架" % info["name"])
    lines.append("")
    lines.append("- 主题：%s" % topic)
    lines.append("- 平台/模板：`%s` @ v%s（%s）" % (platform, TEMPLATE_VERSION, info["structure"]))
    lines.append("- 卖点输入：%d 条 → 规整为 3 条（缺失补占位 %d 条，超出截断 %d 条）"
                 % (len(points_in), sum(1 for f in filled if not f), len(unused)))
    lines.append("")
    lines.append("---")
    lines.append("")
    for el in elements:
        lines.append("## %d. %s" % (el["order"], el["name"]))
        lines.append("")
        if platform == "video":
            lines.append("| 序号 | 时间轴 | 画面 | 口播 | 字幕 |")
            lines.append("|---|---|---|---|---|")
            lines.append(el["text"])
            m = el["meta"]
            lines.append("")
            lines.append("- 画面：%s" % m["visual"])
            lines.append("- 口播：%s" % m["voiceover"])
            lines.append("- 字幕：%s" % m["subtitle"])
        else:
            lines.append(el["text"])
        beat = el.get("meta", {}).get("beat") or el.get("meta", {}).get("rule")
        if beat:
            lines.append("")
            lines.append("> 写法要点：%s" % beat)
        lines.append("")
    lines.append("---")
    lines.append("")
    if platform == "video":
        lines.append("## 分镜总表（时间轴 %s-%s，共 %d 秒）"
                     % (_fmt(_timeline()[0][0]), _fmt(_timeline()[-1][1]), sum(SHOT_DURATIONS)))
        lines.append("")
        lines.append("| 序号 | 时间轴 | 画面 | 口播 | 字幕 |")
        lines.append("|---|---|---|---|---|")
        for el in elements:
            lines.append(el["text"])
        lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("## 占位符统计")
    lines.append("")
    stats = build_stats(elements)
    lines.append("- 未填占位符（待人工/AI 补写）：**%d 处**" % stats["total_open"])
    lines.append("- 已从输入填充：%d 处（%s）" % (stats["total_filled_from_input"],
                                                 "、".join(stats["filled_slots"]) or "无"))
    for el in elements:
        n = stats["by_element"][el["id"]]
        lines.append("  - %d. %s：%d 处" % (el["order"], el["name"], n))
    lines.append("")
    lines.append("> 说明：所有 `【占位:…】` 为开放槽位，由使用者补写；"
                 "`structure.json` 为机器可读的结构要素清单与占位符统计，与本文同源同构。")
    lines.append("")
    return "\n".join(lines)


def build_structure_json(platform, topic, points_in, used, filled, unused, elements):
    info = PLATFORMS[platform]
    els_out = []
    for el in elements:
        n, toks = count_placeholders(el["text"])
        els_out.append({
            "id": el["id"],
            "name": el["name"],
            "order": el["order"],
            "required": True,
            "text": el["text"],
            "placeholder_count": n,
            "open_placeholders": toks,
            "filled_from_input": el["filled_from_input"],
            "meta": el["meta"],
        })
    return {
        "template_version": TEMPLATE_VERSION,
        "platform": platform,
        "platform_name": info["name"],
        "structure_name": info["structure"],
        "topic": topic,
        "points_input_count": len(points_in),
        "points_used": [u if u else None for u in used],
        "points_unused": unused,
        "element_count": len(els_out),
        "elements": els_out,
        "placeholder_stats": build_stats(elements),
    }


# ---------------------------------------------------------------- 主流程

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="四平台爆款文案骨架确定性引擎")
    ap.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--points", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    topic = args.topic.strip()
    if not topic:
        fail("--topic 不能为空")
    points = load_points(args.points)
    used, filled, unused = normalize_points(points)

    elements = BUILDERS[args.platform](topic, used, filled, unused)
    md = render_markdown(args.platform, topic, points, used, filled, unused, elements)
    sj = build_structure_json(args.platform, topic, points, used, filled, unused, elements)

    os.makedirs(args.outdir, exist_ok=True)
    md_path = os.path.join(args.outdir, "骨架.md")
    sj_path = os.path.join(args.outdir, "structure.json")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    with open(sj_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(sj, f, ensure_ascii=False, indent=2)
        f.write("\n")

    stats = sj["placeholder_stats"]
    print("OK platform=%s topic=%s elements=%d open_placeholders=%d filled_from_input=%d -> %s"
          % (args.platform, topic, sj["element_count"], stats["total_open"],
             stats["total_filled_from_input"], args.outdir))
    sys.exit(0)


if __name__ == "__main__":
    main()
