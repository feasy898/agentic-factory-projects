# 素材来源与许可（materials sourcing）

> 状态：in-progress（采集暂停、工具就绪）。维护：2026-10-01 夜班 worker-A。
> 上游指令（windev 会话 2026-09-30，sess_686db8b4）：owner「短剧真实母盘素材：
> 自找公开素材，多找几个」。

## 1. 采集清单（3 部中国大陆公版经典片）

| 片名 | 年份 | 公版依据 | 来源 identifier | 目标件 | 状态 |
|---|---|---|---|---|---|
| 地道战 Tunnel Warfare | 1965 | 发表后 50 年 → 2015 年底届满 | `1-tunnel-warfare-1`（共 4 段，其余段待 `--discover`） | didaozhan_p1.mp4 | ⚠️ 已落盘但验版=TRUNCATED（2026-10-01 实测，见 §4），需重下 |
| 英雄儿女 Heroic Sons and Daughters | 1964 | 发表后 50 年 → 2014 年底届满 | `1964HeroicSonsAndDaughters`（整片 ~485MB） | yingxiongernu_1964.mp4 | 未下载 |
| 闪闪的红星 Sparkling Red Star | 1974 | 发表后 50 年 → 2024 年底届满 | `dailymotion-x5ik2wi`（共 2 段，文件名/第 2 段 identifier 待 `--discover`） | shanshandehongxing_p1.mp4 | 未下载 |

## 2. 许可说明与边界

- 三部影片均为中国大陆电影作品，依《中华人民共和国著作权法》电影作品财产权保护期
  为首次发表后 50 年，三部均已届满进入公有领域——影片本体（画面+原声）可自由使用。
- 拷贝来源为 Internet Archive 第三方上传件；**若上传件自带后续加工**（如修复版新增
  字幕/配乐），新增部分可能另有权利——母盘优先选原始拷贝，登记时在 manifest 注明来源。
- 本清单为工程侧公版自查口径；**对外发布的最终合规审查是人类专属事项**（org 红线 2：
  法律与 ToS 升级人类），发布前须 owner 确认。

## 3. 工具链（本批新增，均已实测）

```
python ops/material_fetch.py --list            # 采集清单
python ops/material_fetch.py --discover <id>   # 探测条目内视频件
python ops/material_fetch.py --fetch-all       # 断点续传全量下载 → materials/raw/
python ops/material_pipeline.py verify <file>  # 验版（全解码扫描+截断检测+sha256）
python ops/material_pipeline.py master <file> --title <NAME>   # 验版 OK → 母盘入库
python ops/material_pipeline.py plan           # raw/master 盘点差异
```

目录约定：`materials/raw/` 采集收件；`materials/master/` 母盘（验版通过件登记拷贝）
+ `master/manifest.json` 台账。**母盘不预裁竖屏、不预烧字幕**——竖屏化由 M1 ingest
承担（docs/assets/specs/m1-ingest.md §2.3 scale+pad 到 1080x1920@25fps），字幕硬烧
属 M11 域；母盘保持原始画面避免双重转码损失。

## 4. 当前阻塞（2026-10-01 实测，恢复窗口即续跑）

- **国际出口不通**：windev 与 GPU 两端 `archive.org` 直连均超时，且 DNS 解析被污染
  （GPU 端解析至无关 IP `162.220.12.226`；windev 端解析至 `104.244.46.85`）；
  国内网正常（GPU 端 baidu 200 / aliyun mirrors 301 实测）。
- 2026-09-30 会话中断致 `didaozhan_p1.mp4` 仅落 3.2MB（容器头声明 1541.8s、实际可
  解码止于 ~31.6s）——正是 verify 截断检测的真阳性标定样本，保留于 `materials/raw/`
  作回归用例，勿删。
- 恢复指引：网络窗口重跑 `--fetch-all --only-missing`（断点续传），逐件
  `verify` → `master` 入库，母盘齐后按 plan 对账。

## 5. 母盘齐备后的下游（接续指引）

1. `python -m pipeline.cli enqueue --ep <ep> --lang <lang>`（M14 队列）逐母盘建作业；
2. M1 ingest 规范化（1080x1920@25fps + 双路音频 + probe.json）；
3. M2→M15 全链按 configs/pipeline.yaml 默认步骤图推进；
4. 演示口径提醒（feedback.md D2）：时长对齐修复完成前，演示禁播全链成片。
