# 10/15 团建报名汇总（chat_id: oc_reg42）

> 数据来源：任务给定的 `lark-cli im +chat-messages-list --chat-id oc_reg42 --format json` 输出（user 身份，共 6 条消息 om_9001–om_9006）；部门名单共 8 人。发送命令已对照本机 `lark-cli im +messages-send --help` 核对。

## ① 覆盖性判断

**已覆盖。** 依据：输出的 `meta.has_more: false` 表明分页拉取已到末页、群内没有更多消息，因此这 6 条（create_time 1759000101000 → 1759000500000 连续升序，含阿松的更正 om_9005 与小助手的截止通知 om_9006）就是当前可拉取的全部消息。

## ② 报名结果（每人以群内最新消息为准）

| 姓名 | 参加与否 | 忌口 |
|---|---|---|
| 阿岚 | 参加 | 香菜 |
| 阿荔 | 参加 | 无 |
| 阿松 | 参加 | **花生** |
| 阿玫 | 不参加 | —（当天出差） |

小计：参加 3 人，不参加 1 人。

理由：按 create_time 每人取最新一条——阿松的更正消息 om_9005（1759000450000）晚于原报名 om_9003（1759000222000），忌口以更正后的「花生」为准；阿玫 om_9004 明确表示「不参加，当天有出差」。

## ③ 尚未回复的成员

**阿柏、阿棠、阿榆、阿桂**

理由：部门名单 8 人中只有阿岚（ou_u1）、阿荔（ou_u2）、阿松（ou_u3）、阿玫（ou_u4）出现在消息里（ou_bot「团建小助手」是机器人、不在名单内），其余 4 人没有任何消息记录。

## ④ 发送汇总回群的命令

主命令（PowerShell / bash 可直接使用多行引号参数）：

```bash
lark-cli im +messages-send --chat-id oc_reg42 --as user --text "【10/15 团建报名汇总】
参加（3人）：
阿岚｜参加｜忌口香菜
阿荔｜参加｜无忌口
阿松｜参加｜忌口花生
不参加（1人）：
阿玫｜不参加｜当天出差
未回复（4人）：阿柏、阿棠、阿榆、阿桂
报名 10/10 24:00 截止，请未回复的同学尽快回复～"
```

cmd.exe 单行替代写法（先把上面的正文存入 `tuanjian-summary.txt`；`--text` 支持 `@file`，见其 `--help`）：

```bat
lark-cli im +messages-send --chat-id oc_reg42 --as user --text @tuanjian-summary.txt
```

理由：`im +messages-send` 是本 CLI 向群发消息的快捷命令（`lark-cli im --help` 列出，其 `--help` 标注 risk: write），`--chat-id oc_reg42` 指定目标群、`--as user` 采用 user 身份、`--text` 直接传纯文本并由 CLI 自动包装为 text 消息，从而把报名清单与未回复名单作为一条消息发出；如需先预览可再追加 `--dry-run`（只打印请求、不真正发送）。

## 验证记录（本机实测）

- `lark-cli --help`、`lark-cli im --help`、`lark-cli im +messages-send --help`：确认了发送命令名与 `--chat-id / --as / --text（支持 @file）/ --dry-run` 等参数，④ 的命令据此写出。
- `lark-cli im +messages-send --chat-id oc_reg42 --as user --text @%TEMP%\t5-summary.txt --dry-run`：参数解析通过，但本机 CLI 返回 `not_configured`（本机未执行过 `config init`），故未取得请求预览、也未发送任何消息；④ 以 `--help` 为准，实际发送需在已认证环境执行。
- 公平性限制：本次未读取 skillfactory/ 目录下任何文件，仅在指定产物目录写入本 OUT.md。
