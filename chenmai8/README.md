# chenmai8 —— 参赛项目群（资产化协议：spec+eval 可稳定再生可工作的软件）

> 接手文档（项目群级）｜ 任务卡见 [TASK.md](TASK.md)（按 5 条并行子线分节）
> 全景状态表与收账队列：[_交付/调度台.md](_交付/调度台.md)——**接手先读这个**
> 资产化协议与模块契约登记簿：[_交付/资产总文件-模块契约与spec-eval.md](_交付/资产总文件-模块契约与spec-eval.md)

## 项目群是什么

「澄迈杯」赛事的 owner 自参赛项目群：**5 个真实子项目 + 交付支撑层**，按统一「资产化协议」开发——

> 核心主张：**spec + eval 能稳定再生可工作的软件；跑通 ≠ 交付；模块内可重生成、模块间契约冻结。**

「模式 M」成品化 = 全新生成成品（factory）+ 原实现封存为 oracle + 两者差分终审 PASS。

⚠️ 注意区分：本目录（R1 澄迈8项目群，自参赛）与「澄迈杯 50 份模拟申报材料」（另一条线，**已关闭**，不在本仓）完全无关。

## 子项目索引（5 条并行子线 + 双仓）

| 子目录 | 是什么 | 语言栈 | 一键门禁 | 最近基线 |
|---|---|---|---|---|
| `chenmai-feeding-arm/` | C1 具身助餐机器人（澄勺）：失能老人桌面助餐机械臂（舀取/口部定位/安全送达/语音交互） | Python | `python scripts/gate_g1.py` | **8/8 PASS**（09-30）+ 独立复核一致；Mock 链路 frozen，真机延后 |
| `chenmai-playable-factory/` | C2 可玩小游戏广告·成品线：spec→模板构建（真实可玩单 HTML）→七渠道打包→判官试玩质检→二维码 | TypeScript / Node 22 | `npm run gate:m3` | **4/4 PASS** + 122 件 node --test + 差分终审 PASS 零回归 |
| `chenmai-playable-ads/` | C2 可玩广告·oracle 仓（原实现封存，供差分） | TypeScript / Python | phase 门 | 6/6 在档 |
| `chenmai-bean-eye/` | C3 咖啡豆质检（啡眼 BeanEye）：海南罗布斯塔生豆 AI 质检台（双面成像逐粒分割、ArUco 毫米标定、三语质量护照、无数据集合成链） | Python | `python scripts/gate_d4.py` | 四项口径过（pytest 全量 508 + e2e_synth 产物在档：trays:3、粒数恢复率 1.0078） |
| `chenmai-gov-ai-gateway/` | C4 政务AI脱敏网关：大模型前置「闸」（OpenAI 兼容，敏感识别→可还原占位符脱敏→敏感度路由→AI 标识+风控，全程可审计） | Python | 七门链 + `gate_final` | **9/9 PASS exit 0**（09-30 run5；其后 5 提交未整门复跑，需在最终代码态新跑认证） |
| `chenmai-drama-dub/` | C5 短剧多国出海（一剧N国）：人声分离/对齐→时长可控翻译→音色迁移配音→口型同步→硬字幕擦除→合规报告 | Python / GPU | `gate_b4` | **6/6 PASS**（09-30，墙钟 3104s/3600s；其后 T21–T23 + 夜班 3 提交未复跑） |

支撑层（本目录根）：`_交付/`（调度台/资产总文件/开源清单/硬件采购/训练延后计划五文档）、`plan--*/`（五个子项目的开发指令等五件套）、`_regen/` `_regen2/`（重生成试点与盲实现）、`_reviews/`（独立盲评/审查）、`specs-eval/`、`CONTEXT.md`、`worklog.md`。

## 构建与运行

**六仓的 venv/node_modules 不在仓内**——接手后先按各仓 `README` / `REGENERATE` 说明重建环境，再跑门禁：

- Python 仓（feeding-arm / bean-eye / gov-gateway / drama-dub）：Python 3.12 + `pip install -r requirements.txt`（gov-gateway 用 `constraints.txt`；drama-dub 的 GPU 服务链需 ffmpeg 与本地推理服务端口，见其 README）。
- Node 仓（playable-factory / playable-ads）：Node 22 + `npm install`。
- 咖啡仓的 sam2 模型权重（176M）不在 git 内，按其 README 自行下载。
- 短剧仓真素材不在仓内（体积），`material_fetch.py --fetch-all --only-missing` 可续跑（需外网）。

## 验收基线（2026-10-01 状态）

各线门禁最近一次实跑数字见上表（09-30 日志/报告实物）；**当前环境未重建，门禁不能开箱即跑**——先重建环境再复跑，复跑数字以新跑为准并与调度台对账。

## 已知问题

1. **政务 gate_final 需在最终代码态整门新跑认证**（其后有 5 提交未复跑；整门 ≥90 分钟 + 静窗 + 三条服务隧道），资产回填等此认证。
2. **短剧 D1 回炉（最高优先）**：B4/B5 五模块约 4,469 行零 spec，按资产化协议补 spec + 盲重生成试点；**D2 时长对齐**修复前全链成片禁播（红线）。
3. **短剧 VLM 腿 BLOCKED**：等 LLM 网关凭证供给；`materials/raw/didaozhan_p1.mp4` 迁移即坏（TRUNCATED 1.2%），需换源。
4. **C1 真机链路、C3 生豆自采链**：物理等待（从臂/生豆到货），到货前不占用会话。
5. 历史/文档中出现的 `198.51.100.x`、`203.0.113.x`、`100.100.0.x` 为公开化替换的示例地址，不是真实服务。
