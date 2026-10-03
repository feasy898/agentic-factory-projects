#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""最小确定性评测器 stub（golden-min 夹具用，非真实资产）。

用法：python runner.py <被测目录> <参照目录>
被测与参照目录均非空 → exit 0；任一为空/缺失 → exit 1；参数不对 → exit 2。
"""
import os
import sys


def count_files(p):
    n = 0
    for _b, _d, files in os.walk(p):
        n += len(files)
    return n


def main():
    if len(sys.argv) != 3:
        print("usage: runner.py <tested> <reference>")
        return 2
    if count_files(sys.argv[1]) == 0:
        print("red: tested dir empty")
        return 1
    if count_files(sys.argv[2]) == 0:
        print("red: reference dir empty")
        return 1
    print('{"ok": true}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
