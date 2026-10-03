#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build.py — skillfactory dist 渠道变体构建器 + G0-5 形式合规门

实现依据：
- SKILL-SPEC-v0.1.md §1.5.2（build 变体生成规则：standard / claude-code；
  learner 变体按 PLAN v1.1 §4.3-1 / O-13 建议默认值新增）
- PLAN v1.1 §7 WS2（build.py + G0-5 门 + dist 三包重打包）
- TESTS v1.1 §1.1 AC 组（G0-5 门 9 条）/ §1.2 BP 组（build.py 9 条）/ §1.6 HY 组

变体语义（canonical 源包只写一次，本工具生成渠道变体）：
  standard     严格 agentskills.io：顶层仅 name/description/license/metadata
               （+compatibility 如源已声明）；顶层 version/permissions 剥离并落入
               metadata.version / metadata.permissions；产物目录名==name；
               剥离 README.md（SPEC §1.1-2 禁止包内 README，人读层由 learner 承载）。
  claude-code  = standard + 把源 SKILL.md 正文中 `<!-- cc-only:<field> -->…<!-- /cc-only:<field> -->`
               标注段生成为顶层私有增强字段；无标注则零私字段（BP-3 absence）。
  learner      = standard + 保留人读层（README.md，白名单机制见 LEARNER_EXTRA_ALLOWLIST）
               且不剥离 eval/（三变体均带 eval/，learner 明示验收）。

声明的变换面（BP-6 判据基准，写进产物 MANIFEST.json transforms 节）：
  1. SKILL.md frontmatter 按 variant 重写（正文 LF 归一，其余字节不动）；
  2. 全部文本文件行尾归一 CRLF→LF（HY-2；基准声明对齐 TESTS §1.10 EI-4 思想）；
  3. 排除清单（见 EXCLUDE_DIRNAMES / EXCLUDE_FILENAMES / 变体附加剥离）；
  4. 新增 MANIFEST.json（逐文件 sha256，无时间戳——BP-7 重建确定性）。

排除语义（重要，处置留痕见 dist-compliance-tickets.md）：
  reference/  = 官方样例输入 + 参照产物（oracle 性质，判据面不进分发物；
               canonical 源包不动，最终删除/迁移待 owner 裁定，轨迹6 结论 12）。
  .git/ __pycache__/ 缓存 / Windows 保留名（HY-1）一律排除并扫描报错。

退出码：0=通过；1=违规/构建失败；2=用法错误；3=拒绝或 fail-closed
（外部校验器不可用、G0-5 被误用于 canonical 双根布局）。

用法：
  python build.py build <src_pkg> [--variant standard|claude-code|learner|all] [--out DIR]
  python build.py build --all [--out DIR]            # dist 三包 × 三变体
  python build.py g05 <pkg_root>                     # G0-5 形式合规门（仅作用于构建产物根）
  python build.py version                            # 构建器版本
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

BUILD_VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))

VARIANTS = ("standard", "claude-code", "learner")

# agentskills.io 开放标准顶层字段白名单（与 skills-ref 0.1.5 validate 白名单一致）
TOP_ALLOWED = ("name", "description", "license", "metadata", "compatibility", "allowed-tools")

# G0-5 门放行的 claude-code 私有增强字段（cc-only 生成目标；门作用对象是 standard
# 产物与 learner 产物，claude-code 产物按渠道契约放行下列私字段）
CC_PRIVATE_FIELDS = ("allowed-tools", "when_to_use", "effort", "paths", "context")

# learner 人读层白名单（BP-5 豁免边界；清单为建议默认值，T-O 决断占位可改）。
# standard / claude-code 变体剥离整个白名单集（SPEC §1.1-2 禁止包内 README 类
# 人读文件，O-13 裁定：canonical 守内部 SPEC，人读层由 learner 承载）。
LEARNER_EXTRA_ALLOWLIST = ("README.md", "QUICKSTART.md", "TROUBLESHOOTING.md")

# 三变体统一排除的目录（相对产物根的名字）
EXCLUDE_DIRNAMES = {
    "reference",      # 官方样例 inputs + 参照产物 out（oracle 性质）
    ".git",
    "__pycache__",
    ".hg", ".svn", ".DS_Store", "node_modules",
}

# standard / claude-code 变体剥离的人读层文件 = LEARNER_EXTRA_ALLOWLIST 全集
# （learner 变体放回白名单内且源里存在的那些）

# Windows 保留名（HY-1）
WINDOWS_RESERVED = re.compile(
    r"^(?:NUL|CON|PRN|AUX|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)

# cc-only 标注段：<!-- cc-only:<field> -->\n value lines \n<!-- /cc-only:<field> -->
CC_ONLY_RE = re.compile(
    r"[ \t]*<!-- cc-only:([a-z0-9_-]+) -->[ \t]*\n(.*?)[ \t]*<!-- /cc-only:\1 -->[ \t]*\n?",
    re.S)

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def die(code, msg):
    sys.stderr.write("build.py: %s\n" % msg)
    sys.exit(code)


def is_text_bytes(data):
    """utf-8 可解码且不含 NUL → 视为文本（LF 归一对象）。"""
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def normalize_text(data):
    """文本字节 LF 归一（声明变换面 2）。"""
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def scan_reserved_names(root):
    """HY-1：扫描 root 下 Windows 保留名，返回命中相对路径列表。"""
    hits = []
    for base, dirs, files in os.walk(root):
        for n in dirs + files:
            if WINDOWS_RESERVED.match(n):
                rel = os.path.relpath(os.path.join(base, n), root)
                hits.append(rel.replace(os.sep, "/"))
    return hits


# ---------------------------------------------------------------------------
# frontmatter 解析 / 序列化（YAML 子集：单行标量 + 平铺 metadata + flow list）
# ---------------------------------------------------------------------------

def parse_frontmatter(text):
    """解析 SKILL.md。返回 (meta, body, err)。

    meta = {"_order": [...], "name": str|None, "description": str|None,
            "license": str|None, "compatibility": str|None,
            "top": {field: raw_value}, "metadata": OrderedDict}
    只认可以 '---' 围栏开头的第一块 frontmatter。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, None, "frontmatter 缺失（首行不是 '---' 围栏）"
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, None, "frontmatter 未闭合（缺第二个 '---' 围栏）"

    meta = {"_order": [], "top": {}, "metadata": {}}
    in_meta = False
    for raw in lines[1:end]:
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith("  ") or line.startswith("\t"):
            if not in_meta:
                return None, None, "缩进行出现在 metadata 块之外: %r" % line
            kv = line.strip().split(":", 1)
            if len(kv) != 2:
                return None, None, "metadata 子键无法解析: %r" % line
            meta["metadata"][kv[0].strip()] = kv[1].strip()
            continue
        in_meta = False
        kv = line.split(":", 1)
        if len(kv) != 2:
            return None, None, "顶层字段行无法解析: %r" % line
        key, val = kv[0].strip(), kv[1].strip()
        if key == "metadata":
            in_meta = True
            continue
        meta["top"][key] = val
        meta["_order"].append(key)
    return meta, "\n".join(lines[end + 1:]), None


def parse_flow_list(raw):
    """解析 `[a, b]` / `[]` / 标量 → list[str]。"""
    v = raw.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    if not v:
        return []
    return [v]


def render_flow_list(items):
    return "[" + ", ".join(items) + "]"


def serialize_frontmatter(meta, top_order):
    """按给定顶层字段顺序序列化 frontmatter（单行标量、平铺 metadata）。"""
    out = ["---"]
    for key in top_order:
        if key == "metadata":
            continue
        if key in meta["top"]:
            out.append("%s: %s" % (key, meta["top"][key]))
    if meta["metadata"]:
        out.append("metadata:")
        for k, v in meta["metadata"].items():
            out.append("  %s: %s" % (k, v))
    out.append("---")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 变体变换
# ---------------------------------------------------------------------------

def transform_frontmatter(meta, body, variant):
    """按 variant 重写 frontmatter。返回 (new_text, transforms, err)。"""
    transforms = []
    top = dict(meta["top"])
    md = dict(meta["metadata"])

    # 渠道私有标注段一律从正文剥离（可剥离层语义；不剥离则渠道内容互相污染）
    cc_fields = {}
    for m in CC_ONLY_RE.finditer(body):
        field, value = m.group(1), m.group(2).strip()
        if field not in CC_PRIVATE_FIELDS:
            return None, None, "cc-only 标注字段 %r 不在私有增强字段清单内" % field
        cc_fields[field] = value
        transforms.append("cc-only body block stripped -> (claude-code only) top.%s" % field)
    if cc_fields:
        body = CC_ONLY_RE.sub("", body)

    # standard 基座：剥离顶层 version/permissions → metadata
    for field in ("version", "permissions"):
        if field in top:
            val = top.pop(field)
            md_key = field
            if md_key not in md:
                md[md_key] = val
                transforms.append("top.%s -> metadata.%s" % (field, field))
            else:
                transforms.append("top.%s dropped (metadata.%s already present)"
                                  % (field, field))
    # 白名单外顶层字段（除 cc 私有字段由 claude-code 生成外）一律剥离并记录
    for field in list(top.keys()):
        if field not in TOP_ALLOWED:
            val = top.pop(field)
            md["legacy-" + field] = val
            transforms.append("top.%s -> metadata.legacy-%s (non-whitelist)" % (field, field))

    order = [k for k in ("name", "description", "license", "compatibility") if k in top]

    if variant == "claude-code":
        # 无标注则零私字段（BP-3 absence）；有标注恰生成对应字段
        for field in ("allowed-tools", "when_to_use", "effort", "paths", "context"):
            if field in cc_fields:
                top[field] = cc_fields[field]
                order.append(field)

    new_meta = {"top": top, "metadata": md}
    text = serialize_frontmatter(new_meta, order) + "\n" + body
    return text, transforms, None


def read_pkg_frontmatter(src_root):
    skill = os.path.join(src_root, "SKILL.md")
    if not os.path.isfile(skill):
        return None, None, None, "SKILL.md 不存在于 %s" % src_root
    with open(skill, "rb") as f:
        raw = f.read()
    text = normalize_text(raw).decode("utf-8")
    meta, body, err = parse_frontmatter(text)
    if err:
        return None, None, None, err
    return meta, body, text, None


# ---------------------------------------------------------------------------
# 构建
# ---------------------------------------------------------------------------

def build_pkg(src_root, variant, out_root):
    """构建一个变体。返回 (product_root, report, err)。"""
    meta, body, _, err = read_pkg_frontmatter(src_root)
    if err:
        return None, None, err
    name = meta["top"].get("name")
    if not name:
        return None, None, "frontmatter 缺 name"
    if not NAME_RE.match(name) or not (1 <= len(name) <= 64):
        return None, None, "name 非法（须 1-64 个字符、仅小写字母/数字/连字符）: %r" % name
    for req in ("description", "license"):
        if req not in meta["top"]:
            return None, None, "frontmatter 缺必填字段 %s" % req

    # 源侧保留名扫描（HY-1，打包输入侧）
    reserved_hits = scan_reserved_names(src_root)
    if reserved_hits:
        return None, None, "源包含 Windows 保留名（HY-1）: %s" % reserved_hits

    product = os.path.join(out_root, variant, name)
    if os.path.isdir(product):
        shutil.rmtree(product)
    os.makedirs(product)

    new_skill, transforms, terr = transform_frontmatter(meta, body, variant)
    if terr:
        return None, None, terr

    excluded = []
    copied = []
    stripped = []
    for base, dirs, files in os.walk(src_root):
        rel_base = os.path.relpath(base, src_root)
        for d in list(dirs):
            if d in EXCLUDE_DIRNAMES:
                dirs.remove(d)
                excluded.append(os.path.join(rel_base, d).replace(os.sep, "/"))
        for fn in sorted(files):
            if WINDOWS_RESERVED.match(fn):
                return None, None, "源文件名命中 Windows 保留名（HY-1）: %s" % fn
            rel = os.path.relpath(os.path.join(base, fn), src_root).replace(os.sep, "/")
            top_rel = rel.split("/")[0]
            base_name = os.path.basename(rel)
            if top_rel in EXCLUDE_DIRNAMES or rel in EXCLUDE_DIRNAMES:
                continue  # 已通过 dirs.remove 剪枝，此行为防御性兜底
            if variant != "learner" and base_name in LEARNER_EXTRA_ALLOWLIST:
                stripped.append(rel)
                continue
            src_path = os.path.join(base, fn)
            with open(src_path, "rb") as f:
                raw = f.read()
            if rel == "SKILL.md":
                data = new_skill.encode("utf-8")
            elif is_text_bytes(raw):
                data = normalize_text(raw)
            else:
                data = raw
            dst = os.path.join(product, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
            copied.append(rel)

    # learner 白名单边界（BP-5）：learner 产物中新增于 standard 的文件必须 ⊆ 白名单
    if variant == "learner":
        std_root = os.path.join(out_root, "standard", name)
        if os.path.isdir(std_root):
            std_files = set()
            for b2, _d2, f2 in os.walk(std_root):
                for fn2 in f2:
                    std_files.add(os.path.relpath(os.path.join(b2, fn2), std_root)
                                  .replace(os.sep, "/"))
            extra = set(copied) - std_files - {"MANIFEST.json"}
            bad = sorted(p for p in extra
                         if os.path.basename(p) not in LEARNER_EXTRA_ALLOWLIST)
            if bad:
                return None, None, "learner 越界文件（不在人读层白名单）: %s" % bad

    # MANIFEST.json（SPEC §2.5-2；无时间戳 → BP-7 重建确定性）
    files_entries = []
    for base, _dirs, files in os.walk(product):
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(base, fn), product).replace(os.sep, "/")
            if rel == "MANIFEST.json":
                continue
            with open(os.path.join(base, fn), "rb") as f:
                data = f.read()
            files_entries.append({"path": rel, "sha256": sha256_bytes(data),
                                  "bytes": len(data)})
    files_entries.sort(key=lambda e: e["path"])
    manifest = {
        "manifest_version": "1",
        "skill": name,
        "skill_version": meta["metadata"].get("version") or meta["top"].get("version", ""),
        "variant": variant,
        "source_pkg": os.path.basename(os.path.normpath(src_root)),
        "built_by": "build.py v%s" % BUILD_VERSION,
        "transforms": {
            "frontmatter": transforms,
            "text_normalization": "utf-8 decode; CRLF/CR -> LF (text files only)",
            "excluded": sorted(set(excluded)),
            "stripped": sorted(stripped),
            "added": ["MANIFEST.json"],
        },
        "normalizations": {"text": "utf-8 + LF", "binary": "byte-identical"},
        "file_count": len(files_entries),
        "files": files_entries,
    }
    with open(os.path.join(product, "MANIFEST.json"), "wb") as f:
        f.write(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    report = {"variant": variant, "product": product, "skill": name,
              "copied": len(copied), "excluded": sorted(set(excluded)),
              "stripped": sorted(stripped), "transforms": transforms}
    return product, report, None


# ---------------------------------------------------------------------------
# G0-5 形式合规门（AC 组；仅作用于构建产物根）
# ---------------------------------------------------------------------------

SKILLS_REF_VERSION_PIN = {
    "tool": "skills-ref",
    "version": "0.1.5",
    "source": "npm registry.npmmirror.com skills-ref/-/skills-ref-0.1.5.tgz",
    "dist_shasum": "08bd74d5bc30038eaba26acbe4b58da8b051aa5e",
    "pinned_at": "2026-10-03",
}


def probe_skills_ref():
    """探测外部校验器。返回 (exe_path|None, detail)。"""
    exe = shutil.which("skills-ref") or shutil.which("skills-ref.cmd") \
        or shutil.which("skills-ref.exe")
    if not exe:
        return None, "PATH 中找不到 skills-ref（钉版记录：npm %s, shasum %s）" % (
            SKILLS_REF_VERSION_PIN["version"], SKILLS_REF_VERSION_PIN["dist_shasum"])
    return exe, "skills-ref @ %s（钉版 %s, shasum %s, %s 安装）" % (
        exe, SKILLS_REF_VERSION_PIN["version"],
        SKILLS_REF_VERSION_PIN["dist_shasum"], SKILLS_REF_VERSION_PIN["pinned_at"])


def run_skills_ref_validate(pkg_root):
    """跑 skills-ref validate。返回 (returncode|None, output)。None=不可用。"""
    exe, _detail = probe_skills_ref()
    if not exe:
        return None, "外部校验器不可用"
    try:
        proc = subprocess.run([exe, "validate", pkg_root],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
    except Exception as exc:  # noqa: BLE001 - fail-closed 上抛
        return None, "外部校验器调用失败: %s" % exc
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def g05_gate(pkg_root, allow_cc_private=False):
    """G0-5 门。返回 (report, exit_code)。

    exit 0=全部通过；1=形式违规；2=用法；3=拒绝或 fail-closed。
    allow_cc_private=True 时放行 claude-code 私有字段（渠道契约自身）。
    """
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    # AC-9 作用面防误用：canonical 双根布局（…/package/ 且父目录有 spec/contract/oracle）
    parent = os.path.dirname(os.path.normpath(pkg_root))
    if os.path.basename(os.path.normpath(pkg_root)) == "package" and any(
            os.path.exists(os.path.join(parent, m))
            for m in ("spec.md", "contract.md", "oracle")):
        rep = {"pkg": pkg_root, "refused": True, "checks": [],
               "detail": ("拒绝：输入疑似 canonical 资产根（双根 package/ 布局，父目录含 "
                          "spec.md/contract.md/oracle）。G0-5 仅作用于 build.py 构建产物根；"
                          "canonical 源包的结构性偏差（目录名=package）不构成分发违规结论。")}
        return rep, 3

    # 外部校验器前置（AC-7 fail-closed：不可用即门红，不得静默通过）
    exe, probe_detail = probe_skills_ref()
    if not exe:
        rep = {"pkg": pkg_root, "fail_closed": True, "checks": [],
               "detail": "外部校验器不可用（fail-closed）：%s" % probe_detail,
               "validator_pin": SKILLS_REF_VERSION_PIN}
        return rep, 3

    skill_path = os.path.join(pkg_root, "SKILL.md")
    if not os.path.isfile(skill_path):
        add("frontmatter_present", False, "SKILL.md 不存在")
        return {"pkg": pkg_root, "checks": checks,
                "validator_pin": SKILLS_REF_VERSION_PIN}, 1
    with open(skill_path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    meta, _body, fm_err = parse_frontmatter(text)
    if fm_err:
        # frontmatter 整体缺失时字段级检查全部级联不可用，并入本条报错
        # （AC-6 报错质量：单一可归因；name 缺失独立变异由 r7 覆盖）
        add("frontmatter_present", False,
            "%s（name/description/metadata 检查连带不可用）" % fm_err)
    else:
        add("frontmatter_present", True, "frontmatter 围栏在位且闭合")

    if not meta:
        # 级联短路：frontmatter 都没有时不再产出字段级红（单一可归因）
        reserved0 = scan_reserved_names(pkg_root)
        add("reserved_names_absent", not reserved0,
            "零命中" if not reserved0 else "命中: %s" % reserved0)
        violations0 = [c for c in checks if not c["pass"]]
        return {"pkg": pkg_root, "checks": checks,
                "validator_pin": SKILLS_REF_VERSION_PIN}, 1

    name = meta["top"].get("name") if meta else None
    if not name:
        add("name_present", False, "frontmatter 缺 name（AC-5）")
    else:
        add("name_present", True, name)
        if NAME_RE.match(name) and 1 <= len(name) <= 64:
            add("name_charset", True, "1-64 字符、[a-z0-9-] 合法")
        else:
            add("name_charset", False, "name 非法: %r" % name)
        dir_name = os.path.basename(os.path.normpath(pkg_root))
        if name == dir_name:
            add("name_equals_dir", True, "name == 产物根目录名 %r" % dir_name)
        else:
            add("name_equals_dir", False,
                "name %r != 产物根目录名 %r（AC-2；门作用面=构建产物根）" % (name, dir_name))

    if meta:
        allowed = set(TOP_ALLOWED)
        if allow_cc_private:
            allowed |= set(CC_PRIVATE_FIELDS)
        bad = sorted(k for k in meta["top"] if k not in allowed)
        if bad:
            add("top_fields_whitelist", False,
                "顶层自造/待剥离字段: %s（白名单: %s）" % (bad, sorted(allowed)))
        else:
            add("top_fields_whitelist", True, "顶层字段全部在白名单内")

        mv = meta["metadata"].get("version")
        if mv and re.match(r"^\d+\.\d+\.\d+$", mv):
            add("metadata_version_present", True, "metadata.version=%s" % mv)
        else:
            add("metadata_version_present", False,
                "metadata.version 缺失或非 semver: %r（AC-4：剥了顶层须落 metadata）" % mv)

        desc = meta["top"].get("description")
        if not desc:
            add("description_present", False, "description 缺失（AC-5）")
        else:
            add("description_present", True, "description 在位")
            if len(desc) <= 1024:
                add("description_length", True, "%d 字符（≤1024）" % len(desc))
            else:
                add("description_length", False, "%d 字符（>1024，AC-5）" % len(desc))
        if "\n" in (desc or ""):
            add("description_single_line", False, "description 含换行（禁块标量）")
        else:
            add("description_single_line", True, "单行标量")

    # HY-1 顺带：产物内保留名扫描
    reserved = scan_reserved_names(pkg_root)
    add("reserved_names_absent", not reserved,
        "零命中" if not reserved else "命中: %s" % reserved)

    # 外部校验器（AC-1 组成部分；输出原样转述）
    rc, out = run_skills_ref_validate(pkg_root)
    if rc is None:
        rep = {"pkg": pkg_root, "fail_closed": True, "checks": checks,
               "detail": "外部校验器调用失败（fail-closed）：%s" % out,
               "validator_pin": SKILLS_REF_VERSION_PIN}
        return rep, 3
    add("skills_ref_validate", rc == 0,
        "exit=%d；%s" % (rc, out.replace("\n", " | ")[:400]))

    violations = [c for c in checks if not c["pass"]]
    report = {"pkg": pkg_root, "checks": checks,
              "validator_pin": SKILLS_REF_VERSION_PIN}
    return report, (1 if violations else 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

DIST_PACKAGES = ("meeting-minutes-skill", "office-templates-skill", "hot-templates-skill")


def cmd_build(args):
    srcs = []
    if args.all:
        for p in DIST_PACKAGES:
            srcs.append(os.path.join(HERE, p))
    else:
        if not args.src:
            die(2, "build 需要源包路径或 --all")
        srcs.append(os.path.abspath(args.src))
    out_root = os.path.abspath(args.out) if args.out else os.path.join(HERE, "build")
    variants = VARIANTS if args.variant == "all" else (args.variant,)
    results = []
    failed = False
    for src in srcs:
        for v in variants:
            product, report, err = build_pkg(src, v, out_root)
            if err:
                sys.stderr.write("[FAIL] %s / %s: %s\n" % (src, v, err))
                failed = True
                continue
            # 构建后过 G0-5（standard/learner 全量；claude-code 放行私字段）
            greport, gcode = g05_gate(product, allow_cc_private=(v == "claude-code"))
            line = {"src": os.path.basename(os.path.normpath(src)),
                    "variant": v, "product": product,
                    "g05_exit": gcode,
                    "g05_failed_checks": [c["name"] for c in greport.get("checks", [])
                                          if not c["pass"]] if isinstance(greport, dict) else [],
                    "build": report}
            results.append(line)
            status = "OK" if gcode == 0 else ("G05_EXIT_%d" % gcode)
            print("[%s] %s -> %s (%s)" % (status, line["src"], v, product))
            if gcode != 0:
                failed = True
    summary_path = os.path.join(out_root, "build-summary.json")
    with open(summary_path, "wb") as f:
        f.write(json.dumps({"results": results}, ensure_ascii=False, indent=2)
                .encode("utf-8"))
    print("summary -> %s" % summary_path)
    sys.exit(1 if failed else 0)


def cmd_g05(args):
    report, code = g05_gate(os.path.abspath(args.pkg))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser(description="skillfactory dist 渠道变体构建器 + G0-5 门")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="构建渠道变体")
    b.add_argument("src", nargs="?", help="canonical 源包路径（缺省用 --all）")
    b.add_argument("--variant", default="all",
                   choices=list(VARIANTS) + ["all"])
    b.add_argument("--out", default=None, help="产物输出根（默认 dist/build/）")
    b.add_argument("--all", action="store_true", help="dist 三包全跑")
    b.set_defaults(func=cmd_build)
    g = sub.add_parser("g05", help="G0-5 形式合规门（仅作用于构建产物根）")
    g.add_argument("pkg", help="构建产物根路径")
    g.set_defaults(func=cmd_g05)
    v = sub.add_parser("version", help="构建器版本")
    v.set_defaults(func=lambda _a: print("build.py v%s" % BUILD_VERSION))
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
