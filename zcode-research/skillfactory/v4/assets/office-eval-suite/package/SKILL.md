# SKILL.md — 中文办公评测集 v2（office-eval-suite package）使用法

> 本目录是「中文办公评测集 v2」的**打包形态（package 布局）**：50 道自含材料的中文办公任务题，
> 八域精确配比 × 易/中/难三档 × 每题 3–5 条可判定检查要点（checks），另附 v1 黄金集兼容导出器。
> 接口契约见上级 `contract.md`；行为细则见上级 `spec.md`；本目录所有产物按该契约独立实现。

---

## 1. 目录内容

| 文件 | 作用 |
|---|---|
| `suite.json` | 评测套件本体：`version` + `description` + `items[50]`；每题 `id / domain / difficulty / instruction / checks` 五键 |
| `validate.py` | 套件结构校验器（9 项检查，全绿 exit 0） |
| `export_legacy.py` | v1 黄金集兼容导出器（缺省严格导出 25 题六域子集 6/5/3/3/4/4，移除 `difficulty`） |
| `out/` | 自检产物目录（`validate.py` 缺省报告写 `out/validate.json`） |

## 2. 套件规格（速览）

- **八域精确配比**（总 50 题）：文档写作 8 / 表格数据 6 / 会议纪要 6 / PPT要点 5 / 邮件沟通 7 / 流程规范 6 / 信息抽取 6 / 改写润色 6。
- **难度三档**：`易 / 中 / 难`；每域三档齐备且**中档占该域多数（>50%）**，全局中档亦占多数（本套件全局 易10/中32/难8）。
- **题干自含**：`instruction` 长度 80–2000 字符，内嵌全部输入材料，且含材料标记（18 词 cue 表：如下/材料/背景/原文/要点/数据/记录/笔记/素材/时间线/规则/条文/条款/对话/邮件/说明/简历/议程）。
- **checks**：每题 3–5 条；`type ∈ {contains, regex, semantic}`（缺省 semantic）；`contains/regex` 必带非空 `value`（regex 须可编译）；`name` 题内唯一。
- **id 规则**：`^[a-z0-9][a-z0-9._-]{1,63}$`，全局唯一；本套件 id 前缀按域命名（dw/td/mm/po/ec/ps/ie/rp + 序号）。

## 3. 常用命令

```bash
PKG=skillfactory/v4/assets/office-eval-suite/package

# 1) 结构自检（报告写 $PKG/out/validate.json；全绿 exit 0）
python $PKG/validate.py --suite $PKG/suite.json

# 2) 导出 v1 兼容黄金集（缺省严格模式：六域 6/5/3/3/4/4 共 25 题，按文件顺序取前 N）
python $PKG/export_legacy.py --suite $PKG/suite.json \
    --out /tmp/golden-legacy.json --report /tmp/export-legacy.json

#    变体：自定义各域抽取数 / 全量导出
python $PKG/export_legacy.py --counts doc-writing=6,table-data=5,email-comm=4 --suite $PKG/suite.json
python $PKG/export_legacy.py --all --suite $PKG/suite.json

# 3) 用确定性评测器验收本产物（4 项检查；候选根给 $PKG 或 $PKG/out 均可，
#    给报告目录 $PKG/out 时 runner 按 contract §1 单层回退到父目录）
python skillfactory/v4/assets/office-eval-suite/eval/runner.py $PKG skillfactory/v4/assets/office-eval-suite/oracle/out
```

runner 的 4 项检查：`validate_all_green`（被测校验器全绿）、`ratio_difficulty_per_spec`（配比与难度直查 suite.json）、`no_dup_vs_reference`（内部唯一 + 与参照集相同题 ≤10）、`legacy_export_v1_green`（legacy 导出实证通过 v1 校验器）。

## 4. 如何用本套件评一个模型

1. 逐题把 `instruction` 原文发给被测模型（题目自含全部材料，无需额外上下文）。
2. 对模型答案逐条执行 `checks` 判分：
   - `contains`：答案包含 `value` 子串 → 通过（机械判定）；
   - `regex`：答案匹配 `value` 正则 → 通过（机械判定）；
   - `semantic`：交由裁判模型按 `desc` 判定（本套件不含裁判，runner 也不调模型）。
3. 题得分 = 通过 checks / 总 checks；域分、难度分按 `domain` / `difficulty` 聚合即可。

## 5. 改动与红线

- **改题/加题**：在新产物根按 contract §2 修改 `suite.json` 后跑 `validate.py` 自检，再以 runner 与 `oracle/out` 参照比对验收；50 题内部归一化互异、与参照套件完全相同题 ≤10。
- **`oracle/` 只读**：参照实现不得修改；`eval/` 检查只增不删。
- **报告目录回退**：`out/validate.json` 存在且父目录三件套齐备时，runner 可直接以 `package/out` 为候选根（留痕 `resolved_via=report-dir-parent`）。
