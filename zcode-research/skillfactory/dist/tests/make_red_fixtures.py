#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_red_fixtures.py — 从 golden-min 最小变异生成 G0-5 红 fixtures（AC-2..AC-6）。

纪律（TESTS §1.1 AC-6 / 轨迹6 链 D-2 变异源单一化）：每个 fixture 从 golden
最小合规包复制后**只坏一处**；目标规则与 fixture 的映射固定，供 run_checks.py
断言「恰被目标规则拦截」。
"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden-min", "golden-demo")
WORK = os.path.join(HERE, "red-work")

# fixture 目录名 -> (目标规则, 变异函数)
FIXTURES = {}


def fixture(dir_name, target_rule):
    def deco(fn):
        FIXTURES[dir_name] = (target_rule, fn)
        return fn
    return deco


def read_skill(root):
    with open(os.path.join(root, "SKILL.md"), "rb") as f:
        return f.read().decode("utf-8")


def write_skill(root, text):
    with open(os.path.join(root, "SKILL.md"), "wb") as f:
        f.write(text.encode("utf-8"))


@fixture("r1-name-dir-mismatch", "name_equals_dir")
def _r1(root):
    # 只坏一处：产物目录名与 name 不一致（目录改名，SKILL.md 不动）
    return None


@fixture("r2-top-version", "top_fields_whitelist")
def _r2(root):
    text = read_skill(root).replace(
        "name: golden-demo\n", "name: golden-demo\nversion: 0.1.0\n", 1)
    write_skill(root, text)


@fixture("r3-top-permissions", "top_fields_whitelist")
def _r3(root):
    text = read_skill(root).replace(
        "name: golden-demo\n", "name: golden-demo\npermissions: [shell]\n", 1)
    write_skill(root, text)


@fixture("r4-unknown-field", "top_fields_whitelist")
def _r4(root):
    text = read_skill(root).replace(
        "name: golden-demo\n", "name: golden-demo\ncustom_field: x\n", 1)
    write_skill(root, text)


@fixture("r5-no-metadata-version", "metadata_version_present")
def _r5(root):
    text = read_skill(root).replace("  version: 0.1.0\n", "", 1)
    write_skill(root, text)


@fixture("r6-no-frontmatter", "frontmatter_present")
def _r6(root):
    text = read_skill(root)
    end = text.index("---\n", 3) + 4
    write_skill(root, text[end:])


@fixture("r7-no-name", "name_present")
def _r7(root):
    text = read_skill(root).replace("name: golden-demo\n", "", 1)
    write_skill(root, text)


@fixture("r8-desc-1025", "description_length")
def _r8(root):
    text = read_skill(root)
    start = text.index("description: ") + len("description: ")
    end = text.index("\n", start)
    text = text[:start] + ("长" * 1025) + text[end:]
    write_skill(root, text)


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    for name, (rule, mut) in FIXTURES.items():
        # 变异包一律放在与 name 同名的目录里（name_equals_dir 不旁支误红）；
        # r1 是唯一以目录名为变异点的 fixture（目录名改 foo-skill）。
        dst = os.path.join(WORK, name, "foo-skill" if name.startswith("r1")
                           else "golden-demo")
        shutil.copytree(GOLDEN, dst)
        if name != "r1-name-dir-mismatch":
            mut(dst)
        print("fixture %s -> target rule %s" % (name, rule))
    print("red fixtures -> %s" % WORK)


if __name__ == "__main__":
    main()
