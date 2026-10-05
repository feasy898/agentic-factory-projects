# -*- coding: utf-8 -*-
"""批12步骤1：第二轮网页抓取（新查询词组，写入 raw2/）。"""
from __future__ import annotations

import os
import sys

from icrawler.builtin import BingImageCrawler, BaiduImageCrawler

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "datasets", "web_hn", "raw2")

QUERIES = {
    "normal": [
        ("bing", "生咖啡豆 麻袋"),
        ("bing", "咖啡豆 筛选 分拣"),
        ("bing", "robusta green beans bag"),
        ("bing", "unroasted coffee beans macro"),
        ("bing", "咖啡生豆 日晒"),
        ("baidu", "罗布斯塔 豆特写"),
        ("baidu", "生咖啡豆 批发"),
        ("baidu", "咖啡豆 分拣机"),
        ("baidu", "云南 咖啡 生豆"),
        ("bing", "green coffee beans sorting"),
    ],
    "defect": [
        ("bing", "coffee beans defects black broken"),
        ("bing", "生豆 缺陷 特写"),
        ("baidu", "咖啡豆 霉变"),
        ("baidu", "咖啡 虫蛀豆"),
        ("bing", "defective green coffee beans"),
    ],
}
MAX_PER_QUERY = 130


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
            print("[OK] %s %s「%s」 +%d" % (group, engine, q, n - before))
            total += n
    print("本轮新增：", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
