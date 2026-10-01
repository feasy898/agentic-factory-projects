---
name: batch-rename-files
version: 1.0.0
license: LicenseRef-skillfactory-internal
description: 把目录内匹配 pattern 的一批文件按「固定前缀 + 3 位序号 + 保留原扩展名」模板批量重命名：非递归 pattern 匹配、按原文件名排序分配序号、dry-run 预览与 apply 执行双模式、目标重名一律跳过绝不覆盖、产出含 renamed/skipped/would-rename 状态且顺序确定的重命名清单。当用户要求批量重命名文件、整理目录内文件名、给一批文件统一加编号前缀、按模式统一改文件名（如把 *.log 统一改成 report_001.log 式样）、batch rename / rename files by pattern / organize filenames in a directory 时使用。不用于修改文件内容；不用于递归子目录（除非用户明确要求）；不用于单个文件的偶发改名、正则重写式改名或按内容分类整理（转交通用脚本/编码任务）；不处理重命名期间的并发冲突。
permissions: [shell]
metadata:
  source: "skillfactory/assets/paper-to-skill/eval/ab_briefs/batch-rename-brief.md（capability 简报，本地文件，无外部 URL）"
  distilled-at: "2026-09-29"
  domain: "file-operations"
---

# batch-rename-files（批量重命名文件）

把指定目录下一批匹配给定模式的文件，按「固定前缀 + 3 位序号 + 保留原扩展名」模板安全地批量改名。读者为命令行使用者或 agent（简报 L13）。本技能按 paper-to-skill 方法论从能力简报 `eval/ab_briefs/batch-rename-brief.md` 成文（A/B 评测 ab-001，treatment 组，成文前完整读过 `package/SKILL.md`、`package/references/workflow.md` 与对照样例 `package/example/SKILL.md`）。需求要点逐条回溯「简报 L<行号>」；简报没写、照做必需的约定标 `[补充]` 并给独立依据（行为类依据为 2026-09-29 在 windev-01 / Windows Server 2022 / Python 3.12.10 / Git Bash（MSYS2 coreutils 8.32）的实测，见「来源引用」第 2 条）。

## 权威规则（置顶）

1. 【MUST RELOAD】多轮对话中出现新指令时，第一个工具调用必须是重新 Read 本 SKILL.md，禁止凭上轮记忆动手。
2. 【安全红线·dry-run 先行】任何 `apply` 之前必须先以 `dry-run` 模式产出「原路径 → 新路径」预览并经用户确认；未经 dry-run 预览禁止直接改名（简报 L10 双模式的设计用途即在此）。
3. 【安全红线·绝不覆盖】目标文件名已存在时一律跳过并在清单记 `skipped`，绝不覆盖已有文件（简报 L11）；禁止用会静默覆盖目标的裸 `mv` 或 `os.replace`（本机实测两者均无提示覆盖，见「来源引用」第 2 条）。
4. 【忠实简报】只做简报声明的能力（pattern 匹配 → 模板展开 → dry-run/apply → 重命名清单）；简报没有的功能（递归重命名、按内容整理、撤销/回滚、并发协调）不得擅自实现，用户提出时先声明超出边界（简报 L17）。

## 分步方法（从三要素输入到重命名清单落盘）

1. 收集并校验输入三要素：目录路径、匹配 pattern（如 `*.log`）、目标命名模板（固定前缀 + 3 位序号 + 保留原扩展名，成品形如 `report_001.log`）（简报 L9）。动作：用 `os.path.isdir(目录)` 校验目录存在，三要素任一缺失或目录不存在即停止并向用户要齐。成功判据：三要素齐备且目录校验通过；失败则零副作用退出、不产出任何文件。
2. pattern 匹配（非递归 · 只留文件 · 排序快照）：在目录当前层按 pattern 匹配，过滤出普通文件（剔除子目录名），按原文件名 `sorted()` 排序后固化为一次快照（顺序确定：简报 L12；不递归：简报 L17）。动作：非递归 glob；禁止递归 glob（`recursive=True` / `Path.rglob`）；pattern 为 `*` 这类宽匹配时用 `os.path.isfile` 过滤（实测 `Path.glob('*')` 会把子目录名列出来）。成功判据：得到已排序、只含文件的快照列表；空列表即如实报告「无匹配文件」并停止。
3. 模板展开编号：按快照顺序从 `001` 起分配 3 位零填充序号，以 `前缀 + %03d + os.path.splitext(原名)[1]` 生成新名，原扩展名原样保留（实测 `splitext('report_001.log')` → `('report_001', '.log')`）。动作：为快照逐条生成「原路径 → 新路径」映射表。成功判据：每个快照文件恰有一条映射，新名符合简报模板形状（前缀 + 3 位序号 + 原扩展名，简报 L9）；序号只取决于第 2 步的排序快照，与文件系统枚举顺序无关。
4. dry-run 预览：对映射表逐条查 `os.path.exists(新路径)` 定状态——目标已存在记 `skipped`、否则记 `would-rename`——逐条打印「原路径 → 新路径 [状态]」预览（简报 L10），并把同一份重命名清单写入产物 `rename-report.txt`（状态列此时为 `would-rename`/`skipped`）。此处「不落盘」指不改任何文件名、不动文件内容；清单文件本身仍要写出——依据：简报 L12 的清单明确含 `would-rename` 状态，该状态只有 dry-run 会产生。成功判据：stdout 出现逐条含 `→` 的预览且条数等于快照数；`rename-report.txt` 状态列全为 `would-rename`/`skipped`；复查目录内文件名与第 2 步快照完全一致（零改名）。
5. apply 执行并出清单：经用户确认后对同一快照逐条执行——先查 `os.path.exists(新路径)`，已存在则跳过并记 `skipped`（绝不覆盖，简报 L11），不存在才执行 `os.rename(原路径, 新路径)`（Windows 实测目标已存在时 `os.rename` 抛 `FileExistsError`，与预检构成双保险）。动作：执行重命名，并把重命名清单（原路径 → 新路径 + 状态 `renamed`/`skipped`）按快照顺序写入 `rename-report.txt`（简报 L12 要求一份重命名清单；文件名为本技能 `[补充]` 约定，简报未定名）。成功判据：`rename-report.txt` 落盘且 `renamed + skipped = 快照总数`；对已改过名的目录重跑 `apply` 应全部记 `skipped`（无二次改名）。

## 能力边界（简报 L17 原文三条）

- 不递归子目录，除非用户明确要求；即便要求也应先确认范围再执行。
- 不改文件内容，只改文件名。
- 不处理重命名过程中的并发冲突：多进程/多 agent 同时操作同一目录时结果未定义，执行前确保独占。

## 常见坑

- 裸 `mv` / `os.replace` 静默覆盖 → 现象：`mv a.txt b.txt`（b.txt 已存在）退出码 0、b.txt 内容被替换、a.txt 消失；`os.replace` 同样无报错覆盖（均实测）→ 原因：这两个调用的默认语义就是替换已存在目标 → 正确做法：先 `os.path.exists(新路径)` 预检，存在即记 `skipped`，绝不覆盖（简报 L11）。
- pattern 写成递归 glob → 现象：递归 glob（`recursive=True` 或 `Path.rglob`）把子目录里的 `sub/y.log` 也卷进清单（实测 `rglob` 额外命中 `sub\y.log`）→ 原因：递归匹配跨目录层级 → 正确做法：非递归匹配，守住简报 L17「不递归」边界。
- 宽 pattern 把子目录名当待改名条目 → 现象：`Path.glob('*')` 把子目录 `sub` 也列出（实测）→ 原因：目录也是目录项，glob 不过滤文件类型 → 正确做法：匹配后用 `os.path.isfile` 过滤，只留普通文件。
- 不排序直接用枚举顺序编号 → 现象：本机实测 NTFS 枚举返回 `a.log, B.log`，而简报要求的按原文件名排序 `sorted()` 给出 `B.log, a.log`——同一批文件序号不同（抖动）；且 Python 文档明言 `os.listdir` 顺序任意（文献依据），跨文件系统更不可复现 → 原因：文件系统枚举顺序无承诺，也不等于码点序 → 正确做法：先 `sorted()` 按原文件名排序再分配序号（简报 L12 要求顺序确定、按原文件名排序）。
- 扩展名丢失或多段扩展名 → 现象：模板只拼「前缀+序号」得到无扩展名的 `report_001`；`archive.tar.gz` 经 `splitext` 只取 `.gz`（实测）→ 原因：`splitext` 只分离最后一个点后的后缀 → 正确做法：新名必须拼回原扩展名；「多段扩展名按最后一段」是本技能口径（简报 L9 模板例为单段 `.log`），用户要求整段保留时先确认再执行。
- 边重命名边重扫目录 → 现象：apply 循环中重新扫描目录时，新名仍命中原 pattern（实测 `fnmatch('report_001.log', '*.log')` 为 True），同一批文件被二次重命名 → 原因：执行动作改变了第 2 步快照赖以建立的目录状态 → 正确做法：先固化排序快照、只对快照执行，禁止在执行循环中重扫目录。

## 来源引用

1. 设计依据（capability 简报）：`skillfactory/assets/paper-to-skill/eval/ab_briefs/batch-rename-brief.md`（本地文件，共 17 行，无外部 URL）——目标能力（L5）、三要素输入与模板示例 `report_001.log`（L9）、dry-run/apply 双模式（L10）、重名跳过绝不覆盖（L11）、清单产物三状态与按原文件名排序（L12）、适用对象（L13）、边界三条（L17）。本技能无简报之外的功能，超出项见「权威规则」第 4 条。
2. 系统调用行为依据（`[补充]`，2026-09-29 于 windev-01 / Windows Server 2022 / Python 3.12.10 / Git Bash（mv 为 MSYS2 GNU coreutils 8.32）实测，探针在系统临时目录执行后清理）：`os.rename(a, b)` 且 b 已存在 → `FileExistsError`（errno 17 / WinError 183，不覆盖）；`os.replace(a, b)` 且 b 已存在 → 无报错、b 内容被替换（静默覆盖）；裸 `mv a.txt b.txt`（b 已存在）→ 退出码 0、b 内容被替换；`mv -n` → 退出码 0、跳过不覆盖、源文件保留；`os.path.splitext('report_001.log')` → `('report_001', '.log')`、`splitext('archive.tar.gz')` → `('archive.tar', '.gz')`；非递归 `glob('*.log')` 只命中当前层，`Path.rglob`（等价 `recursive=True`）递归命中子目录，`Path.glob('*')` 列出子目录名；NTFS 枚举序 `a.log, B.log` ≠ `sorted()` 码点序 `B.log, a.log`；`fnmatch('report_001.log', '*.log')` → True。POSIX `rename(2)` 语义为「newpath 已存在则原子替换」（man 2 rename；本机为 Windows 无法直接实测，标注为文献依据）——正因各调用默认行为不一，「预检 + skipped」是唯一跨平台合规做法。
3. front-matter 约束依据：agentskills.io《Agent Skills Specification》——name 仅小写字母/数字/连字符、≤64 字符、禁首尾与连续连字符；description 1–1024 字符、写「做什么 + 何时用 + 具体关键词」（经 `package/example/SKILL.md` 转引，其标注原文 L29-36、L66-70、L106-108）。
4. 成文方法：paper-to-skill 方法论（`package/SKILL.md` 六步法；步骤「三选一」可判定标记口径见 `package/references/workflow.md` 第 3 步）；treatment 组成文前完整读过对照样例 `package/example/SKILL.md`。
5. 企业字段与 `[补充]` 声明：front-matter 的 `version`/`license`/`permissions` 沿用 skillfactory 企业标准（SKILL-SPEC-v0.1），非简报内容；清单文件名 `rename-report.txt` 为本技能 `[补充]` 约定（简报 L12 只要求「一份重命名清单」未定名）；序号「3 位、从 `001` 起」为简报 L9 模板示例 `report_001.log` 的直接读法；「dry-run 不落盘 = 零改名、清单仍要写出」的口径见分步方法第 4 步。
