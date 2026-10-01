# hot-templates/oracle — 四平台爆款文案骨架 · 参照引擎（oracle）

确定性参照软件：按四平台爆款结构模板，把「主题 + 卖点」渲染成可直接交付的文案骨架。
无网络、无时间戳、无随机数——同输入连跑两次，产物逐字节一致。

## 平台模板（冻结）

| 平台 | 产物形态 | 结构模板 |
|---|---|---|
| `dy` | 抖音口播稿 | 3秒钩子 + 痛点 + 价值点×3 + CTA（6 要素） |
| `xhs` | 小红书图文 | 标题带数字 + emoji规则 + 正文分块 + 标签组（7 要素） |
| `wx` | 公众号文章 | 引子 + 三段论（是什么/为什么/怎么办）+ 金句收尾（5 要素） |
| `video` | 短视频分镜表 | 6 镜 45 秒分镜表：时间轴/画面/口播/字幕 |

- `xhs` emoji 规则：标题 `🔥`、开头钩子块 `✅`、干货块 `💡`、总结块 `📌`、标签组 `🏷️`（映射表冻结在 gen.py）。
- `video` 时间轴：3/7/10/10/10/5 秒共 45 秒（`SHOT_DURATIONS` 冻结）。

## 命令行契约

```
python gen.py --platform <dy|xhs|wx|video> --topic <主题> --points <卖点json> --outdir <dir>
```

| 参数 | 语义 |
|---|---|
| `--platform` | 四平台之一，非法值退出码 2 |
| `--topic` | 非空主题字符串 |
| `--points` | 卖点 JSON：文件路径（纯列表，或含 `points` 键的对象）或内联 JSON 串，如 `["卖点1","卖点2","卖点3"]` |
| `--outdir` | 输出目录，不存在则递归创建 |

**卖点规整策略**：模板冻结为价值点×3。不足 3 条 → 缺失槽位落 `【占位:价值点N】`；
超出 3 条 → 取前 3，其余记入 `structure.json` 的 `points_unused`。

**退出码**：`0` 成功写产物；`2` 参数非法（platform 非法 / topic 空 / points 不可解析或非字符串列表），
stderr 中文报错，不产生产物、不建产物目录。

## 产物（<outdir> 内，文件名冻结）

| 文件 | 内容 |
|---|---|
| `骨架.md` | 人读骨架：按要素分节给出已填充文案与 `【占位:…】` 开放槽位，尾部附占位符统计 |
| `structure.json` | 机器可读：模板版本、平台、主题、卖点规整记录、结构要素清单（id/name/order/text/占位符明细/filled_from_input/meta）、`placeholder_stats`（total_open / total_filled_from_input / by_element / open_tokens_unique / filled_slots） |

## 目录结构

```
oracle/
├── gen.py                  # 唯一引擎入口
├── run_all.py              # 8 份样例批量驱动（子进程真实调用 gen.py CLI）
├── verify.py               # V1-V6 验收检查（存在性/自洽/确定性复跑/失败路径）
├── inputs/<platform>/case{1,2}.json   # 8 份主题样例（含满3条/不足/超出/0条边界）
└── out/<platform>/case{N}/{骨架.md,structure.json}
```

## 如何运行

```bash
# 单次生成
python gen.py --platform dy --topic 时间管理 --points inputs/dy/case1.json --outdir out/dy/case1

# 全部 8 份样例
python run_all.py

# 验收（存在性 + JSON 自洽 + 占位符重计数 + 确定性复跑比对 + 失败路径）
python verify.py
```
