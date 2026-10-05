# M3 号码归一化表 spec（masking/normalize.py，§5.3.2 冻结）

> 状态：frozen（规则冻结，改动 = 破坏归一化等价契约）。对照 `masking/normalize.py`（85 行，全量）
> 逐行核验于 2026-09-29。原则：同一实体的不同写法 → 同 normalized → 同占位符（§5.3.1）。

## 1. 全角→半角（`to_halfwidth`，normalize.py:22-24, 42-44）

- 基准字符集 **0xFF01–0xFF5E ↔ 0x21–0x7E**（全角 ASCII 可打印区 94 字：０-９、Ａ-Ｚ、ａ-ｚ
  与常见全角符号），外加全角空格 **0x3000 → 半角空格**；
- `str.translate` 一次映射，1:1 长度不变——识别层影子扫描依赖此性质（span 与原文严格对齐，
  见 recognizers-rule spec §3）。

## 2. 数字串类公共归一（`normalize_digits`，normalize.py:27-36, 47-49）

适用类别 `ID_CARD / PHONE_MOBILE / PHONE_LANDLINE / BANK_CARD / USCC`：

1. 全角→半角；
2. 删除全部内部分隔符字符集：**半角+全角空格、`\t`、`\r`、`\n`、`-`、Unicode 连字符类
   （‐‑‒–—―）、全角减号 `－`、`.`、全角点 `．`、中文间隔点 `·`**（normalize.py:36 `_SEPARATORS`）。

## 3. 逐类别归一化表（`normalize_value`，normalize.py:52-84）

| 类别 | 规则 | 例 | 冻结细节 |
|---|---|---|---|
| `PHONE_MOBILE` | 公共归一后去 **+86/86 前缀**——仅当去掉后剩 11 位且第 3 位为 `1`、第 4 位 ∈ 3-9 才视为前缀（防误删普通数字）；`+` 号也在剥离序列里 | `＋86 138 0013 8000` → `13800138000` | normalize.py:63-69；检测端 span 回扩覆盖 `+`（detect.py:417-419） |
| `ID_CARD` | 公共归一后**末位 x→X** | `460022…123x` → 尾 `X` | normalize.py:71-73 |
| `PLATE` | 公共归一后**大写**（间隔点 `·` 已被公共归一删除） | `琼A·12345` → `琼A12345` | normalize.py:74-75 |
| `DATE_BIRTH` | 半角化后匹配 `YYYY<年/./-/、>M<月/./-/、>D[日]` 数字版式 → `YYYY-MM-DD`（补零）；无法解析原样返回（半角化后） | `1990年3月7日` → `1990-03-07` | normalize.py:38-39, 76-81 `_DATE_PARTS_RE` fullmatch |
| 其余数字串类（`PHONE_LANDLINE/BANK_CARD/USCC`） | 公共归一 | `6222 0210 0111 6295 763` → 连写 | normalize.py:82-83 |
| `EMAIL/IP/SECRET_KEY` 及词面类 | 仅全角→半角 + 首尾去空白（原样语义，保守安全） | — | normalize.py:84 |
| `PERSON/ADDRESS` | **不做串级归一化**（原样），仅精确匹配去重（§5.3.2 取向） | — | normalize.py:11, 84 |

## 4. 与识别层的耦合（冻结）

- 检测端先把 token 压缩后再做形状/校验位分类（`detect.py:33-35` 归一化等价口径说明）：
  生成器扰动 `digit_spacing / separator_variant / fullwidth` 三类变体必须同判；
- `evals.m8_generator` 数据质量检查独立重推导 normalized 全等（DATE_BIRTH 数字版式按数字组
  重推 ISO，中文版式仅验 ISO 形状）；
- 改本表任何一行 → 必须回归 `evals.m3_masking`（归一化等价项）+ `evals.m2_recognizers`
  （扰动变体召回）+ `evals.m8_generator`（独立重推导），并按 CONTRACTS 变更流程走。
