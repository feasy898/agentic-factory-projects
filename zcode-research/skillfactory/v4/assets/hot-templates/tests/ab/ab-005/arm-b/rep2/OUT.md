# hot-templates 工程性验收 · ab-005 / arm-b / rep2

- 日期：2026-09-30
- 执行机：windev-01（Windows Server 2022, x64），Python 3.12.10，Git Bash（find/cmp/sha256sum）
- 被测对象：hot-templates 技能（四平台爆款文案骨架确定性引擎）
- 本臂约束遵守情况：**全程未读取 `skillfactory/` 下任何文件的内容**。仅 (a) 列目录名以定位入口；(b) 盲执行程序并以 `--help` / 程序自身 stdout/stderr 获取 CLI 契约。

## 0. 技能定位（如何在不读 skillfactory 文件的前提下"使用技能"）

1. `Skill` 工具查询 `hot-templates`：`Skill not found`（本子代理会话未注册该技能）。
2. 全盘搜索安装副本：`find /d /c/Users/Administrator -iname "*hot-template*"`（剔除 skillfactory）0 命中；`grep -ril "hot-templates"` 于 /d/workspace、~/.codebuddy、~/.zcode、/d/agent-knowledge、/d/tools 0 命中；zcode `skills.roots=[]`；`ListSavedWorkflows` 为空。结论：**技能唯一存在于 `skillfactory/v4/assets/hot-templates/`**。
3. 故按盲测协议仅列目录名（`find ... -maxdepth` 不读内容），发现 `oracle/gen.py` 等入口；随后：
   ```
   $ python oracle/gen.py --help        # cwd = skillfactory/v4/assets/hot-templates
   usage: gen.py [-h] --platform {dy,video,wx,xhs} --topic TOPIC --points POINTS
                 --outdir OUTDIR
   四平台爆款文案骨架确定性引擎
   ```
   由此获得 CLI 契约（`--points` 接受 JSON 数组字符串；输出目录含 `骨架.md` 与 `structure.json`，与任务描述吻合）。

工作产物（运行痕迹）目录：`D:\workspace\zcode研究\_tmp_ab005_armb_rep2\`（det=测试①，err_*=测试②）。

## 1. 测试① 同输入连续两次生成 → 逐字节比对

**输入（两次完全相同）**：`--platform dy`，`--topic 确定性复跑主题`，`--points '["要点甲","要点乙","要点丙"]'`；输出目录分别为 `_tmp_ab005_armb_rep2/det/run1` 与 `.../det/run2`。

**命令（同一 shell 连续执行，cwd=skillfactory/v4/assets/hot-templates）**：
```
python oracle/gen.py --platform dy --topic 确定性复跑主题 --points '["要点甲","要点乙","要点丙"]' --outdir "$W/det/run1"
python oracle/gen.py --platform dy --topic 确定性复跑主题 --points '["要点甲","要点乙","要点丙"]' --outdir "$W/det/run2"
```
（$W = /d/workspace/zcode研究/_tmp_ab005_armb_rep2）

**运行输出与退出码**：
```
OK platform=dy topic=确定性复跑主题 elements=6 open_placeholders=6 filled_from_input=4 -> D:/workspace/zcode研究/_tmp_ab005_armb_rep2/det/run1
EXIT_RUN1=0
OK platform=dy topic=确定性复跑主题 elements=6 open_placeholders=6 filled_from_input=4 -> D:/workspace/zcode研究/_tmp_ab005_armb_rep2/det/run2
EXIT_RUN2=0
```
（`filled_from_input=4` = topic 1 + 3 个要点，证实 --points 被解析为 3 项。）

**产物**：两目录均恰好含 `structure.json`（4038 字节）与 `骨架.md`（2040 字节）。

**逐字节比对（cmp 即逐字节；另附 SHA-256 复核）**：
```
$ cmp run1/骨架.md  run2/骨架.md          → EXIT=0（无差异）
$ cmp run1/structure.json run2/structure.json → EXIT=0（无差异）

166692ba855c77fdb60636126ac8bf7f06b86bfef305a24bdb6445d08613b808  run1/骨架.md
166692ba855c77fdb60636126ac8bf7f06b86bfef305a24bdb6445d08613b808  run2/骨架.md
a331cdd8689e51a7675ffbf675ec1d61e02b3215309e6f8b56841888dad588d2  run1/structure.json
a331cdd8689e51a7675ffbf675ec1d61e02b3215309e6f8b56841888dad588d2  run2/structure.json
```

**结论①：通过。** 两份 `骨架.md`、两份 `structure.json` 均逐字节一致（cmp 退出码 0，SHA-256 完全相同）；且 `structure.json` 未嵌入 outdir 路径（输出到不同目录哈希仍一致），无时间戳/随机数泄漏。

## 2. 测试② 非法输入触发（各一次；stdout/stderr 分离捕获）

### 2.1 非法 platform = bilibili
```
$ python oracle/gen.py --platform bilibili --topic 确定性复跑主题 --points '["要点甲","要点乙","要点丙"]' --outdir "$W/err_bilibili/out"
```
| 观察项 | 结果 |
|---|---|
| 退出码 | **2** |
| stdout | 空（0 字节） |
| stderr | `usage: gen.py [-h] --platform {dy,video,wx,xhs} --topic TOPIC --points POINTS` / `              --outdir OUTDIR` / `gen.py: error: argument --platform: invalid choice: 'bilibili' (choose from dy, video, wx, xhs)` |
| 输出目录 | 创建前 not exists → 创建后仍 **not exists**（`err_bilibili/` 整个未创建） |

### 2.2 空 topic（空白串 = 三个 ASCII 空格 `"   "`，已用 `printf '   ' | wc -c` 复核为 3 字节）
```
$ python oracle/gen.py --platform dy --topic "   " --points '["要点甲","要点乙","要点丙"]' --outdir "$W/err_blanktopic/out"
```
| 观察项 | 结果 |
|---|---|
| 退出码 | **2** |
| stdout | 空（0 字节） |
| stderr | `[gen.py] 错误：--topic 不能为空` |
| 输出目录 | 创建前 not exists → 创建后仍 **not exists**（`err_blanktopic/` 整个未创建） |

**结论②：通过。** 两类非法输入均被拒绝：退出码统一为 2，诊断信息走 stderr（stdout 干净），且**均未创建输出目录**（无半成品残留）。空白 topic 会被 strip 后判空并显式报错，属于主动校验而非 argparse 层拦截——两条错误路径分属两层校验，均闭环。

## 3. 总验收结论

| # | 验收项 | 判定 | 关键证据 |
|---|---|---|---|
| ① | 同输入双跑确定性 | **通过** | cmp 两文件均 exit 0；`骨架.md` SHA-256 `166692ba…b808`、`structure.json` SHA-256 `a331cdd8…88d2` 双跑一致 |
| ②a | 非法 platform=bilibili | **通过** | exit 2；stderr=invalid choice；输出目录未创建 |
| ②b | 空白 topic `"   "` | **通过** | exit 2；stderr=`--topic 不能为空`；输出目录未创建 |

三项验收全部通过，未发现缺陷。
