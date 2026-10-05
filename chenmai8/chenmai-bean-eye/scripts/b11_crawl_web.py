# -*- coding: utf-8 -*-
"""批11步骤1：图片搜索引擎抓取海南罗布斯塔生豆候选图（Bing/Baidu）。

查询分组：
  normal 组（好豆域样本）：海南罗布斯塔生豆 / 罗布斯塔生豆 特写 / 咖啡生豆 堆 / green coffee beans robusta
  defect 组（缺陷域样本）：咖啡缺陷豆 / 咖啡瑕疵豆 生豆 / 咖啡豆 黑豆 发酵
产物：data/datasets/web_hn/raw/<组>/<查询号>_*.jpg，之后去重 + 目检。
"""
from __future__ import annotations

import os
import sys

from icrawler.builtin import BingImageCrawler, BaiduImageCrawler

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "datasets", "web_hn", "raw")

QUERIES = {
    "normal": [
        ("bing", "海南 罗布斯塔 咖啡生豆"),
        ("bing", "罗布斯塔 生豆 特写"),
        ("bing", "咖啡生豆 堆"),
        ("bing", "green coffee beans robusta close-up"),
        ("baidu", "海南罗布斯塔咖啡豆"),
        ("baidu", "咖啡生豆 特写"),
    ],
    "defect": [
        ("bing", "咖啡 缺陷豆 生豆"),
        ("bing", "咖啡瑕疵豆 黑豆"),
        ("baidu", "咖啡豆 缺陷 瑕疵"),
    ],
}
MAX_PER_QUERY = 120


def main() -> int:
    total = 0
    for group, items in QUERIES.items():
        for i, (engine, q) in enumerate(items):
            outdir = os.path.join(OUT, group, "q%02d" % i)
            os.makedirs(outdir, exist_ok=True)
            before = len(os.listdir(outdir))
            try:
                if engine == "bing":
                    cr = BingImageCrawler(storage={"root_dir": outdir}, downloader_threads=4)
                else:
                    cr = BaiduImageCrawler(storage={"root_dir": outdir}, downloader_threads=4)
                cr.crawl(keyword=q, max_num=MAX_PER_QUERY)
            except Exception as exc:
                print("[NG]", group, engine, q, repr(exc)[:120])
                continue
            n = len(os.listdir(outdir))
            print("[OK] %s %s「%s」 +%d（目录 %d）" % (group, engine, q, n - before, n))
            total += n
    print("合计落盘图片（含历史）：", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
