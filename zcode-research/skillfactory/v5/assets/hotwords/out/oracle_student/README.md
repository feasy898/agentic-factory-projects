# hotwords/oracle — 单位热词表管理器 · 参照软件（oracle）

确定性参照软件：管理一份单位热词表（词 + 类别 + 备注 + 权重），支持增删查与
FunASR / 纯文本导出。无网络、无时间戳、无随机数——同输入连跑两次，`out/` 逐字节一致
（实测：两次连跑 sha256 全树摘要一致，`030fd184…`）。

## 命令行契约（hotwords.py）

```
python hotwords.py [--store <json>] <add|list|remove|export> [参数...]
```

| 子命令 | 参数 | 语义 |
|---|---|---|
| `add` | `<词> [--category 类别] [--note 备注] [--weight N]` | 追加词条；与既有词**完全同字**即报重复（退出码 2，库不变）；库不存在自动新建。类别默认「默认」，备注默认空，权重默认 20 |
| `list` | — | 按类别分组列出：类别按字典序排序，类别内保持入库插入序 |
| `remove` | `<词>` | 按词删除；不存在则退出码 2 |
| `export` | `--format <funasr\|plain> [--out 文件]` | funasr：每行「词 权重」（权重缺省 20）；plain：每行一词。省略 `--out` 写标准输出 |

- `--store` 须写在子命令之前，默认 `./store.json`。
- **退出码**：`0` 成功；`2` 失败（重复 / 不存在 / 库缺失或损坏 / format 非法 / 参数语法错误）。
  业务错误 stderr 中文报错；参数语法错误由 argparse 报出（英文）。
- **热词库结构**（version 固定 1）：
  `{"version": 1, "words": [{"word": str, "category": str, "note": str, "weight": int}, ...]}`

## fixtures

| 文件 | 内容 |
|---|---|
| `fixtures/base.json` | 演示库：6 词条、3 类别（产品 / 售后 / 营销），权重含默认 20 与自定义 25/30 |
| `fixtures/script.json` | 10 步操作序列：初始 list → add → **add 重复（expect=fail）** → add 带权重 → remove → **remove 不存在（expect=fail）** → 最终 list → 导出 funasr / plain / stdout |

## 批量实跑（run_all.py）

```
python run_all.py        # 全部跑通退出码 0；任一步与 expect 不符退出码 1
```

1. 清空重建 `out/`，`base.json` 复制为工作库 `out/_work/store.json`（跨步延续）。
2. 每步以真实 CLI 子进程执行（cwd=该步快照目录，相对 `--out` 产物直接落入）。
3. **每步快照** `out/<序号>_<id>/`：`cmd.txt`（完整命令行）、`exit_code.txt`、
   `stdout.txt`、`stderr.txt`、`store.json`（该步执行后的库快照）、导出产物。
4. 汇总 `out/manifest.json`（各步 expect/exit_code/pass/artifacts + `all_pass`）。

expect=fail 的步骤要求退出码非 0——业务报错同样是被参照的确定性行为。
