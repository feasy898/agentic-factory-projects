#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_inputs.py — 生成 20 条意图样例到 inputs/case1-20.txt（确定性，无随机）。

样例构成（编号与列表顺序一一对应）：
  清晰型（单一类别信号明确）        : case1-case9, case19, case20
  歧义型（无信号/跨类弱冲突）       : case10-case12
  混合型（两类以上信号，按优先级裁定）: case13-case18
"""

import os

CASES = [
    # ---- 清晰型 ----
    "把这份销售数据整理成汇报PPT，要带图表和表格，方便后面改数字",       # case1  editable
    "做一份9月运营月报，把台账里的数据填进去，下周例会用",               # case2  editable
    "用我们公司的品牌VI模板做一份对外介绍",                             # case3  template
    "直接套用上季度评审用过的模板，换内容就行",                         # case4  template
    "设计一张朋友圈转发用的宣传海报，一页就好",                         # case5  visual
    "把活动亮点做成一张信息图，视觉上要抓人",                           # case6  visual
    "下周例会要用，把项目进度数据做成可编辑的图表汇报页",               # case7  editable
    "按公司VI规范出一份提案模板",                                       # case8  template
    "做一张海报贴在展位，风格醒目一点",                                 # case9  visual
    # ---- 歧义型 ----
    "帮我做一个PPT",                                                    # case10 无信号→兜底
    "内容大概是产品介绍和团队情况，你看着办",                           # case11 无信号→兜底
    "做点有视觉冲击力的东西，里面还要放转化数据",                       # case12 跨类弱冲突
    # ---- 混合型（多类信号，按 template_fill > editable_pptx > visual_report 裁定）----
    "用公司模板把月报数据做出来",                                       # case13 template+editable
    "数据台账能不能做成海报风格发朋友圈",                               # case14 editable+visual
    "品牌部要一张一页海报",                                             # case15 template+visual
    "套用模板做几张图表",                                               # case16 template+editable
    "汇报页做得视觉化一点，像信息图那样",                               # case17 editable+visual
    "把月报做成朋友圈转发的一页图",                                     # case18 editable+visual
    # ---- 清晰型（续）----
    "对外介绍要贴合公司品牌调性",                                       # case19 template
    "客户要一份能自己改数据表格的汇报材料",                             # case20 editable
]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.join(here, "inputs")
    os.makedirs(outdir, exist_ok=True)
    for i, text in enumerate(CASES, 1):
        path = os.path.join(outdir, "case%d.txt" % i)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("written: %s <- %s" % (path, text))
    print("total: %d cases" % len(CASES))


if __name__ == "__main__":
    main()
