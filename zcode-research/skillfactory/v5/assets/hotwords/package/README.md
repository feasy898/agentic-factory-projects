# hotwords package — 单位热词表管理器（被测实现）

按资产根 `../spec.md` + `../contract.md` 从零实现的 `hotwords.py`，可见行为与 oracle
参照实现逐字节一致（`eval/runner.py` 四项检查全过，与 `oracle/out` 54 文件逐文件一致）。

## 文件清单

| 文件 | 说明 |
|---|---|
| `hotwords.py` | CLI 工具（自包含，仅 Python 标准库） |
| `run_all.py` | 按 `fixtures/script.json` 以真实 CLI 子进程执行 10 步操作序列，产出 `out/` |
| `fixtures/base.json` | 演示热词库（依 spec 附录 A.1 生成，632 字节） |
| `fixtures/script.json` | 10 步操作序列（依 spec 附录 A.2 生成，1728 字节） |
| `out/` | `python run_all.py` 的产物（54 个文件），即被测产物根 |
| `SKILL.md` | 单位热词表建设指南：采集口径 / 权重建议 / FunASR 接法 |
| `README.md` | 本文件 |

## CLI 用法

```bash
python hotwords.py [--store <json>] <add|list|remove|export> [参数...]
```

- `--store` 为全局选项，须写在子命令之前，默认 `./store.json`。
- `add <词> [--category 类别] [--note 备注] [--weight N]`：默认类别「默认」、备注空、
  权重 20；与既有词**完全同字**即重复 → 退出码 2、库不变、stderr 中文报错；库不存在自动新建。
- `list`：按类别分组（类别字典序、组内插入序）；空库输出 `（空库：共 0 词）`。
- `remove <词>`：按词删除；不存在 → 退出码 2、库不变。
- `export --format <funasr|plain> [--out 文件]`：funasr 每行「词 权重」（缺省 20）、
  plain 每行一词；省略 `--out` 写标准输出（与文件产物逐字节一致）；`--format` 取值非法
  → 退出码 2 中文报错（缺省该选项为 argparse 语法错误，退出码 2、英文提示）。
- 库 JSON：`{"version":1,"words":[{word,category,note,weight},...]}`，落盘
  `indent=2 + ensure_ascii=False + 末尾换行`、UTF-8 无 BOM、`\n` 行尾、词条保持插入序。
- 退出码：`0` 成功；`2` 失败（业务错误 stderr 中文、前缀「错误：」；argparse 语法错误英文）。
- 行为规则的权威全文见 `../spec.md` §4.1（R1-R9）与附录 A（逐字节常量）。

## 复现产物与评测

```bash
# 产出被测产物（先产出后评测）：
cd skillfactory/v5/assets/hotwords/package && python run_all.py
# 评测（两种写法等价）：
python skillfactory/v5/assets/hotwords/eval/runner.py skillfactory/v5/assets/hotwords/package/out skillfactory/v5/assets/hotwords/oracle/out
python skillfactory/v5/assets/hotwords/eval/runner.py skillfactory/v5/assets/hotwords/package skillfactory/v5/assets/hotwords/oracle
```

本实现于 2026-09-30 实跑验证：`run_all.py` 10/10 步 OK（03/06 步按预期 exit=2）、整体
退出码 0；runner 4/4 PASS、54/54 文件一致率 100%、退出码 0。

## 边界行为（实跑验证）

- `add` 于缺失库：自动建库，exit 0；`list` 于空库：输出 `（空库：共 0 词）`，exit 0。
- `list`/`remove`/`export` 于缺失库：exit 2（中文报错，契约 R7「库缺失」判失败）。
- `--format yaml`：exit 2 中文；坏 JSON 库：exit 2；读取容忍 UTF-8 BOM。
- 同输入重复运行全部输出逐字节一致（无时间戳/随机/网络）。

## 确定性

`hotwords.py` 与 `run_all.py` 均不含时间戳、随机数、网络调用；子进程 stdio 强制 UTF-8 +
`\n` 行尾，文件一律按字节写入，杜绝平台差异。同输入连跑两次，`out/` 全树逐字节一致。
