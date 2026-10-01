# content.md — ab-001「批量重命名文件」baseline 组产物说明

- 组别：**baseline**（按任务要求，未阅读 `package/example/SKILL.md`、`oracle/`、`spec.md`，仅依据简报独立撰写）
- 需求依据：`eval/ab_briefs/batch-rename-brief.md`（已完整阅读）
- 本目录产物：
  - `SKILL.md` —— 主产物
  - `content.md` —— 本文件（完整文本 + 结构说明）
  - `verify/rename_files.py` —— 参考实现源文件（与 SKILL.md 内嵌代码逐字一致，已 diff 校验）
  - `verify/transcript.txt` —— 实测记录（P0–P2 探针 + T1–T7，本会话重新生成）
  - `verify/run_verification.sh` —— 可复现验证脚本（重建 fixtures → 探针 + T1–T7 → transcript.txt）
  - `verify/verify_os_rename.py` —— os.rename / os.replace 行为探针（transcript P2 调用）
  - `verify/qc_check.py` —— QC 脚本（front-matter 合规 / 结构 / 脚本一致性检查）
  - `verify/fixtures-log/`、`verify/fixtures-mixed/`、`verify/fixtures-case/`、`verify/probe/` —— 沙箱测试夹具（apply / 探针后状态）
  - `verify/rename-log.tsv` —— apply 实际产出的清单样例

---

## 一、SKILL.md 完整文本

（外层用四反引号围栏，内层 ` ``` ` 围栏均为原文内容）

````markdown
---
name: batch-rename-files
description: 当用户要求批量重命名文件、按模式整理目录内文件名、为一批文件添加统一前缀与序号时使用。把目录下匹配 glob 模式（如 *.log）的文件重命名为「固定前缀 + 3 位序号 + 原扩展名」（如 report_001.log），支持 dry-run 预览与 apply 执行两种模式；目标名已存在时一律跳过并记录，绝不覆盖；产出含 renamed / skipped / would-rename 状态的重命名清单，顺序按原文件名排序确定。触发词：batch rename、bulk rename、rename files by pattern、organize filenames、add prefix and numbering。
---

# 批量重命名文件（Batch Rename Files）

把指定目录下一批匹配给定模式的文件，按「固定前缀 + 3 位序号 + 原扩展名」的模板批量重命名。
例如 `*.log` → `report_001.log`、`report_002.log`……

## 输入与模式（与能力简报一致）

| 输入 | 说明 |
|---|---|
| 目录路径 | 只处理该目录，**不递归子目录**（除非用户明确要求） |
| 匹配 pattern | glob 模式，如 `*.log` |
| 目标命名模板 | 固定为「前缀 + 3 位序号 + 原扩展名」，可配置部分即前缀（如 `report_`） |

两种模式：`dry-run`（默认）只打印「原路径 → 新路径」预览清单，不落盘；`apply` 实际执行重命名并写出清单文件。
冲突处理：目标文件名已存在时**跳过并记录，绝不覆盖**。

## 方法：按以下 5 步执行

### 步骤 1：扫描目录，按 pattern 匹配文件

**动作**：在目标目录内做**非递归** glob 匹配（不要用 `**`，不要 walk 子目录）；过滤出普通文件（排除目录）；**按原文件名排序**——文件系统返回顺序不定，不排序会导致同一批文件两次运行序号不同（见坑 4）。

**产物（可判定）**：一份匹配清单——文件名列表及其数量 N。
检查点：清单不含子目录中的文件；不匹配 pattern 的文件（如 `*.log` 模式下的 `notes.txt`）不在清单中。

快速核对命令：

```bash
ls -1 <目录>/*.log          # POSIX；注意 win32 下 glob 大小写不敏感（见坑 6）
python -c "import glob; print(sorted(glob.glob(r'<目录>/*.log')))"
```

### 步骤 2：展开模板，生成目标名并预判冲突

**动作**：对排序后第 i 个文件（i 从 1 起），生成目标名 = `<前缀>` + `%03d` % i + 该文件**原扩展名**（用 `os.path.splitext` 取，原样保留大小写，不要手工切割字符串或写死扩展名）；随后逐个预判：目标名已存在 → 该文件标记 `skipped`（跳过，占号但不动它）。

**产物（可判定）**：一张「原路径 → 新路径」完整映射表。
检查点：映射表行数 = N；每个新扩展名与原扩展名完全一致（含大小写）；存在同名目标的行已标 `skipped`。

### 步骤 3：dry-run 预览（每次 apply 前必须执行）

**动作**：运行参考实现（见下节），**不带 `--apply`**。脚本逐行打印 `状态<TAB>原路径 -> 新路径`，状态只有两种：`would-rename`（目标名空闲）/ `skipped`（目标已存在）。**逐行核对预览**：确认匹配范围没有多、没有少，冲突跳过符合预期。

**产物（可判定）**：stdout 预览清单（如需留存可重定向保存，如 `> preview.tsv`），末行汇总 `N matched, M skipped, K would-rename`，退出码 0（无冲突）/ 1（有 skipped）/ 2（用法错误）。
检查点：清单中**没有任何一行状态是 `renamed`**；执行前后目标目录文件列表不变（`dry-run` 不落盘）。

```bash
python rename_files.py <目录> --pattern '*.log' --prefix 'report_' > preview.tsv
```

### 步骤 4：apply 执行，产出重命名清单

**动作**：预览确认无误后，**同一命令加 `--apply`** 重新运行。脚本按步骤 1 的同一排序逐个执行「存在检查 → `os.rename`」：目标空闲才改名（状态 `renamed`），已存在则跳过（状态 `skipped`）；同时把全部行写入清单文件 **`rename-log.tsv`**（表头 `status / src / dst`，写入**当前工作目录**而非目标目录，避免日志自身落入匹配范围）。

**产物（可判定）**：`rename-log.tsv` + stdout 汇总行 + 退出码。
检查点：清单行数（含表头）= N+1；`skipped` 行对应的旧文件仍在原名、内容未动，其目标名上的旧文件原样存在。

```bash
python rename_files.py <目录> --pattern '*.log' --prefix 'report_' --apply
```

### 步骤 5：对账验收

**动作**：以 `rename-log.tsv` 为准抽查对账：`renamed` 行 → 旧路径已不存在、新路径内容与原内容一致；`skipped` 行 → 双方文件均原样存在。把对账结果连同 `rename-log.tsv` 一并反馈给用户。

**产物（可判定）**：对账结论（N 个改名、M 个跳过、0 个覆盖）。

## 参考实现（已实测）

依赖仅 Python 3 标准库；核心策略 = 「排序定序 + 逐个存在检查 + `os.rename` + 跳过记录」，不使用 `mv`（默认覆盖）、不使用 `os.replace`（对已存在目标静默覆盖；win32 已实测，POSIX 侧为文档行为）。

```python
#!/usr/bin/env python3
"""批量重命名：把目录下匹配 pattern 的文件改名为 <前缀><三位序号><原扩展名>。

默认 dry-run（只打印预览，不改任何文件）；--apply 才真正重命名并写出 rename-log.tsv。
冲突策略：目标名已存在一律跳过并记录，绝不覆盖。
"""
import argparse
import glob
import os
import sys

LOG_NAME = "rename-log.tsv"


def iter_matches(directory: str, pattern: str):
    """在 directory 下做非递归 glob 匹配，只保留文件，按原文件名排序。"""
    full = os.path.join(directory, pattern)
    hits = []
    for path in glob.glob(full):
        name = os.path.basename(path)
        if os.path.isfile(path):
            hits.append(name)
    return sorted(hits)


def target_name(prefix: str, index: int, original: str) -> str:
    """目标名 = 固定前缀 + 3 位序号 + 原扩展名（含大小写，原样保留）。"""
    _, ext = os.path.splitext(original)
    return f"{prefix}{index:03d}{ext}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", help="目标目录（不递归子目录）")
    ap.add_argument("--pattern", required=True, help='相对 directory 的 glob 模式，如 "*.log"')
    ap.add_argument("--prefix", required=True, help="目标名固定前缀：<prefix><001><.ext>")
    ap.add_argument("--apply", action="store_true",
                    help="执行重命名并写出 rename-log.tsv（默认 dry-run 只预览）")
    args = ap.parse_args()

    if not os.path.isdir(args.directory):
        print(f"error: not a directory: {args.directory}", file=sys.stderr)
        return 2

    names = iter_matches(args.directory, args.pattern)
    rows = []  # (status, src_path, dst_path)
    skipped = 0
    for i, name in enumerate(names, start=1):
        src = os.path.join(args.directory, name)
        dst = os.path.join(args.directory, target_name(args.prefix, i, name))
        if os.path.lexists(dst):
            # 目标已存在（含目标名与原名相同的自指向）：跳过并记录，绝不覆盖
            rows.append(("skipped", src, dst))
            skipped += 1
        elif args.apply:
            os.rename(src, dst)  # 仅在 dst 不存在时才会走到这里
            rows.append(("renamed", src, dst))
        else:
            rows.append(("would-rename", src, dst))

    for status, src, dst in rows:
        print(f"{status}\t{src} -> {dst}")

    if args.apply:
        # 清单写到当前工作目录（而非目标目录），避免日志本身落入匹配范围
        with open(LOG_NAME, "w", encoding="utf-8", newline="") as fh:
            fh.write("status\tsrc\tdst\n")
            for status, src, dst in rows:
                fh.write(f"{status}\t{src}\t{dst}\n")
        print(f"log: {os.path.abspath(LOG_NAME)}")

    total = len(rows)
    print(f"summary: {total} matched, {skipped} skipped, "
          f"{total - skipped} {'renamed' if args.apply else 'would-rename'}")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
```

**实测结论**（Windows Server 2022 / win32，Python 3.12.10，2026-09-29；完整记录见随附 `verify/transcript.txt`）：
dry-run 不改任何文件；apply 中目标已存在的文件被跳过且双方原样（`beta.log` 内容保持 `BBB`，未覆盖）；`notes.txt`、`subdir/inner.log` 未被卷入；`c.TXT` → `report_003.TXT` 扩展名含大小写原样保留；目录被排除、不递归；重跑 apply 见坑 5。

## 常见坑（均为实测或简报明示的风险）

1. **目标重名覆盖**：`mv src dst`（不带 `-n`）在目标已存在时**静默覆盖**（本机实测：exit 0、旧内容丢失）；`os.replace` 静默覆盖（win32 本机实测；POSIX 侧为 Python 文档行为，本机未实测）。做批量重命名永远不用这两者裸执行——必须先做存在检查，存在即跳过并记录。
2. **`os.rename` 行为平台相关，不能裸依赖它兜底**：win32 上目标已存在报 `FileExistsError [WinError 183]`（本机实测），POSIX 上则会静默替换目标（Python 文档行为，本机未实测）。可移植的代码必须自己先查 `os.path.lexists(dst)`，把「跳过」作为显式逻辑。
3. **pattern 误匹配**：用了 `**` / `os.walk` 会把子目录文件卷进来（简报要求不递归）；glob 的 `*` 匹配结果还可能包含目录（需 `isfile` 过滤）；已有目标名文件本身可能匹配 pattern（实测：预置的 `report_002.log` 也被 `*.log` 匹配为源文件）。对策：非递归 glob + 文件过滤，并在 dry-run 清单里逐行核对范围。
4. **文件顺序不确定导致序号抖动**：`os.listdir`/`glob` 返回顺序由文件系统决定，不排序则两次运行对同一批文件给出不同序号。对策：始终按原文件名排序后再编号；序号按排序后位置分配（被跳过的文件同样占号），保证同一批文件两次 dry-run 结果完全一致。
5. **模板与 pattern 同族，重跑 apply 会继续扰动**：模板保留原扩展名，因此改名结果（`report_001.log`）仍匹配 `*.log`；对同一目录再次 `--apply` 会把已改名文件再次卷入（实测：`report_001.log` 被再次改名为 `report_002.log`）。对策：每次 apply 前必须重新 dry-run 核对当次预览；完成后以 `rename-log.tsv` 对账收尾，不要盲目重跑。
6. **glob 大小写跨平台不一致**：win32 下 `*.log` 能匹配 `X.LOG`（本机实测命中），POSIX 下不能。跨平台执行时 pattern 匹配范围会不同，扩展名大小写按原样保留，验收时逐字核对。
7. **扩展名丢失**：手工切割文件名（如 `split('.')`）或模板里写死扩展名，遇到多段名（`app.tar.log`）或大小写扩展名会丢后缀/改写。对策：用 `os.path.splitext` 取扩展名并原样拼接（实测 `c.TXT` → `report_003.TXT`）。

## 安全红线

- **先 dry-run 后 apply**：任何一次 `--apply` 之前，必须看过**当次**的 dry-run 预览并逐行核对；目录内容变过就要重新预览。
- **重名跳过，绝不覆盖**：目标名已存在（含与原名相同的自指向）一律 `skipped` 并记入清单；禁止 `mv -f`、禁止 `os.replace`、禁止「先删后改」、禁止任何形式的覆盖。
- **不越界**：不递归子目录（除非用户明确要求）；不改任何文件内容；不处理重命名过程中的并发冲突（能力简报边界）。
- 退出码非 0（存在 skipped 或用法错误）时，先解决问题再继续，不要带着冲突强行重跑。

## 来源与依据

每条来源给出五要素：**名称、类型/出处、日期、位置、引用内容与验证方式**。

1. **《能力简报：批量重命名文件（A/B 任务材料 · ab-001）》**——类型：任务需求文档（capability brief）；日期：文档未标注，读取于 2026-09-29；位置：`skillfactory/assets/paper-to-skill/eval/ab_briefs/batch-rename-brief.md`；引用内容：输入（目录/pattern/模板）、dry-run 与 apply 双模式、冲突跳过不覆盖、含 renamed/skipped/would-rename 状态的清单产物、按原文件名排序、不递归不改内容不处理并发（§需求要点、§边界）；用途：本技能全部功能性需求的唯一来源，未添加简报之外的功能。
2. **GNU Coreutils `mv`**——类型：系统工具（本机 `/usr/bin/mv`，Git Bash/MSYS）；日期：实测于 2026-09-29；位置：本机验证（探针见 `verify/transcript.txt` 前置记录）；引用内容与验证：`mv src dst` 目标已存在时静默覆盖（exit 0，内容被替换）；`mv -n` 跳过不覆盖（exit 0，源文件保留）——本机实测，结论是批量重命名不得依赖 `mv` 默认行为。
3. **Python `os.rename` / `os.replace`**——类型：标准库文档行为 + 本机实测；版本：Python 3.12.10，win32；日期：实测于 2026-09-29；位置：本机验证；引用内容与验证：win32 下 `os.rename` 撞名抛 `FileExistsError [WinError 183]`（实测），`os.replace` 静默覆盖（实测）；POSIX 侧「`os.rename` 静默替换已有目标」引自 Python 文档行为，**本机为 win32 未实测**，已据此在实现中统一改为显式存在检查。
4. **参考实现实测记录**——类型：本技能自带脚本 `rename_files.py` 的沙箱验收；日期：2026-09-29；位置：随附 `verify/transcript.txt`（T1–T7：dry-run 不落盘、冲突跳过不覆盖、非递归不误匹配、排序确定、扩展名原样保留、重跑扰动、大小写探测）；验证方式：fixtures 上先 dry-run 后 apply，逐文件核对内容与清单。
````

> 注：以上即为 SKILL.md 的逐字完整文本（含内嵌脚本全文，与 `verify/rename_files.py` 逐字一致，已做字符串等值校验，见第四节 QC-3）。

---

## 二、结构说明与评分点对照

| SKILL.md 章节 | 内容 | 对应要求 |
|---|---|---|
| front-matter | `name: batch-rename-files`（小写+连字符，18 字符，无首尾/连续连字符）；`description` 316 字符（≤1024，QC 实测），含触发场景（用户要求批量重命名/整理目录内文件名/加前缀序号）与能力、模式、冲突策略摘要 | front-matter 合规 |
| 输入与模式 | 目录/pattern/模板三输入表 + dry-run/apply 双模式 + 跳过不覆盖声明，与简报 §需求要点逐条对齐 | 忠实简报、不编造 |
| 方法：5 步 | ①非递归 pattern 匹配+排序 → ②模板展开（前缀+%03d+原扩展名）+冲突预判 → ③dry-run 预览 → ④apply 执行+`rename-log.tsv` → ⑤对账验收。每步含「动作」与「产物（可判定）+检查点」，并给出可复制命令 | 分步方法 ≥3 步，覆盖 pattern→模板→dry-run→apply 主流程 |
| 参考实现 | 仅标准库的完整 Python 脚本 + 本机实测结论（环境、日期、指向 transcript） | 产物「重命名清单」的落地形态 |
| 常见坑 | 7 条：重名覆盖（mv/os.replace 实测）、os.rename 平台差异（WinError 183 实测）、pattern 误匹配（递归/目录/目标文件自身被匹配，实测）、顺序不定序号抖动、重跑扰动（实测 report_001.log→report_002.log）、glob 大小写跨平台（实测）、扩展名丢失 | ≥2 条真实风险，覆盖 rubric 列举的四类 |
| 安全红线 | dry-run 先行（每次 apply 前）、重名跳过绝不覆盖（禁 -f / os.replace / 先删后改）、不递归不改内容不处理并发（简报边界） | 安全红线 |
| 来源与依据 | 4 条来源，每条按五要素（名称/类型出处/日期/位置/引用内容与验证方式）；POSIX 侧 os.rename 行为如实标注「本机未实测」 | 来源引用五要素 |

**未编造简报之外的功能**：无正则替换、无撤销/回滚、无递归选项、无自定义序号起始值、无冲突改名（如加 `(1)` 后缀）——冲突只有「跳过并记录」一种处理，与简报一致。`--prefix` 是简报「固定前缀 + 3 位序号 + 保留原扩展名」模板中唯一可自由命名的部分；`rename-log.tsv` 文件名、退出码 0/1/2 属实现细节而非新功能。

## 三、验证记录（本会话 2026-09-29 实际执行）

- 命令环境：Windows Server 2022（MINGW64_NT-10.0-20348 x86_64）、Git Bash（`/usr/bin/mv`）、Python 3.12.10（`C:\Program Files\Python312\python.exe`）。
- 复现方式：在 `verify/` 目录下运行 `bash run_verification.sh`——一键重建 fixtures、重跑探针与 T1–T7，输出逐字写入 `verify/transcript.txt`（本会话 07:35 生成；本节所有结论均出自该文件）。
- 前置探针（transcript P0–P2）：`mv src dst`（dst 已存在）→ exit 0、目标内容被替换、源消失；`mv -n` → exit 0、跳过且源保留；`os.rename` 撞名 → `FileExistsError [WinError 183]`，双方原样；`os.replace` 撞名 → 静默覆盖。
- T1–T7：dry-run 输出 would-rename/skipped 且目录零变化（T1/T2）；apply 后 `beta.log` 保持 `BBB` 未被覆盖，预置 `report_002.log` 自身被改名到 `report_004.log`（内容 R002 随行迁移，无覆盖，证明坑 3 真实）（T3/T4）；重跑 apply 出现 `report_001.log → report_002.log` 扰动（T5，坑 5 依据）；`*` 模式下扩展名 `c.TXT → report_003.TXT` 原样保留、目录排除（T6，坑 7 依据）；win32 下 `*.log` 命中 `upper.LOG`（T7，坑 6 依据）。
- 未运行/未实测项（如实声明）：POSIX 平台行为（Linux 下 `os.rename` 静默替换已有目标、`os.replace` 覆盖）未在本机验证；SKILL.md 中相关表述已标注来源为文档行为。

## 四、QC 清单结果（本会话运行 `python verify/qc_check.py`，输出 RESULT: ALL PASS，共 29 项）

- QC-1 name 合规（正则 `^[a-z0-9]+(-[a-z0-9]+)*$`、≤64 字符、无首尾/连续连字符）：通过（实测 18 字符）。
- QC-2 description ≤1024 字符且含触发场景：通过（实测 316 字符）。
- QC-3 SKILL.md 内嵌脚本与 `verify/rename_files.py` 逐字一致：通过（2694 字符字符串等值校验）。
- QC-4 编号步骤 5 个（≥3）且覆盖 pattern/模板/dry-run/apply、坑 7 条（≥2）、红线与来源章节存在、无编造功能（`--recursive`/`--undo`/`--rollback`/`--start` 缺席、无 `os.replace` 调用、`mv -f` 仅出现于禁止清单）：全部通过。
- content.md 哨兵行与内嵌脚本一致性：通过。
