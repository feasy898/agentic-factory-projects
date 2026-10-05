# OSS Manifest —— 上游开源件清单（核实日期 2026-09-28）

> 核实方式：npm registry API / GitHub API / HuggingFace API / 官方文档实测。本文件为**内部文件**，可含上游名称；公开仓内一律中性名（见 开发指令.md §12）。

| 上游项目 | URL | 许可证 | 我们用它什么 | 商用授权需求 | 替代备选 |
|---|---|---|---|---|---|
| @smoud/playable-sdk | https://github.com/smoudjs/playable-sdk （npm 同名，v1.2.0，2026-09-04） | MIT | D1 spike 与对照轨：统一试玩运行时接口（MRAID/Google/Facebook/Vungle 等封装） | 无（MIT；公开仓中不直接依赖、不留名） | 自研 engine-bridge（已定为交付形态） |
| @smoud/playable-scripts | https://github.com/smoudjs/playable-scripts （npm 同名，v1.2.14，2026-09-02） | MIT | D1 跑通 6 渠道出包；D6 对自研 packager 做交叉验证 | 无（MIT；仅 devDependency/对照，不进公开仓） | 自研配置驱动 packager（主轨） |
| playable-template-phaser | https://github.com/smoudjs/playable-template-phaser （master，2026-02-11） | MIT | 模板工程骨架参考、Phaser 版本锚点 | 无（MIT；仅参考后重写，不复制入公开仓） | 自建模板骨架 |
| OpenGame（游戏智能体框架） | https://github.com/leigest519/OpenGame （Apache-2.0，~2957 星，2026-09-03 活跃） | Apache-2.0 | 仅参考其"验证-修复闭环"提示词与评测思路（M11） | 无（Apache-2.0；不 fork 入交付，仅内部参考） | 自研 repair-loop（已定） |
| GameCoder-27B（OpenGame 配套模型） | 无公开权重（HF/GitHub 均无官方发布，README 亦无下载链接） | — | **不用**。概念文档不确定性已证实：禁止作为依赖 | — | Qwen3.8-27B（Apache-2.0，公开权重） |
| Phaser | https://github.com/phaserjs/phaser （npm phaser@4.2.1，2026-07-09；实际钉模板锁定版） | MIT | 4 个模板的游戏运行时 | 无 | PixiJS 8.21.0（MIT，备选引擎） |
| PixiJS | https://github.com/pixijs/pixijs （v8.21.0，2026-09-17） | MIT | 备选引擎（包体更小）；不双实现 | 无 | — |
| BiRefNet（抠图） | https://github.com/ZhengPeng7/BiRefNet + HF ZhengPeng7/BiRefNet*（代码与权重均 MIT，4232 星活跃） | MIT | 路径 B 的主体抠图兜底（演示级，D3 可选） | 无（MIT，可商用） | sharp 矩形遮罩 / 用户提供带透明素材 |
| Qwen-Image-Layered（拆图层） | https://huggingface.co/Qwen/Qwen-Image-Layered （2025-12-17，Apache-2.0，diffusers 管线） | **Apache-2.0** | 路径 B：截图拆透明图层素材（演示级） | 无（**可商用**） | BiRefNet 兜底；或跳过（路径 B 降级） |
| Qwen-Image-2.1（生成/改图） | https://huggingface.co/Qwen/Qwen-Image-2.1 （2026-09-14，另有 -PE 变体 09-20） | **Qwen Research License —— 非商用** ⚠️ | 仅限比赛演示链路的透明素材生成/改字；交付物与公开版不依赖 | **商用需另行与 Qwen 签协议**（本项目中不签，商用版用 Kenney/自绘/用户素材替代） | Kenney CC0 素材 + assetkit 后处理；用户上传素材 |
| Qwen3.8-27B（多模态，文本+图+视频） | https://huggingface.co/Qwen/Qwen3.8-27B （2026-08-05，dense 27B，256K 上下文） | Apache-2.0 | 概念文档同名模型已核实存在；交付期私有化部署首选（vLLM/SGLang，V100S×2 可跑量化版）；开发期用远程 API 等价替代 | 无 | Qwen3.6-35B-A3B（MoE）、Qwen3-VL-8B（更小） |
| Qwen3.6-35B-A3B（多模态 MoE） | https://huggingface.co/Qwen/Qwen3.6-35B-A3B （2026-04-15，image-text-to-text） | Apache-2.0 | 路径 B 的 VLM 备选（激活 3B，推理成本低）；LoRA 训练候选之一 | 无 | Qwen3-VL-8B-Instruct（Apache-2.0，2×V100S 训练最稳） |
| Kenney 素材包 | https://kenney.nl/assets （CC0 1.0；下载后留档包内 License 文件） | CC0 | 全部 4 模板的默认素材与 golden spec 素材；合成数据工厂的素材池 | 无（CC0 公共领域） | 自绘矢量素材；OpenGameArt CC0 区 |
| Noto 字体 | https://github.com/notofonts （SIL OFL 1.1；含 Arabic/JP/KR 子集源） | SIL OFL 1.1 | 多语言 UI 字体，assetkit pyftsubset 子集化后内嵌 | 无（OFL 允许嵌入；保留许可声明于内部留档，公开仓按法务统一处理） | 系统 font stack（不内嵌，包体更小但渠道渲染不可控） |
| cocos-pnp（Cocos 多渠道打包插件） | https://github.com/ppgee/cocos-pnp （MIT，385 星，**2024-06 后停滞**） | MIT | 路径 C（已有 Cocos 工程接入）。**MVP 不用**（停滞风险 + 路径 C 出范围），仅二期评估 | 无（MIT） | 自写 Cocos web-mobile 构建后处理脚本 |
| OpenCode（编码智能体，概念文档备选） | github.com/sst/opencode（未深核） | MIT（概念文档称） | 不引入：M11 自研闭环已覆盖，少一个重型依赖 | — | OpenGame 思路（仅参考） |

## 关键提示（红线）

1. **非商用项只有一处：Qwen-Image-2.1（含 -PE 变体）= Qwen Research License**。规则：演示可、交付不可、公开依赖不可。替代路径（Kenney + assetkit + 用户素材）已保证交付链路零接触。
2. GameCoder-27B 无公开权重 —— 概念文档"说法不一致"已证实为**未公开**，任何计划不得引用。
3. 上游 MIT/Apache 件允许商用，但按法务要求**公开仓内不留上游名与许可证声明**（由统一法务处理）：技术上通过"仅 spike/对照使用 + 自研交付实现"达成。
4. ironSource 直投已于 2026-04-30 关停（概念文档核实项）：不列入渠道矩阵。
5. 微信小游戏试玩：需申请试玩广告 ID 且仅支持主包 → 二期，不进本期范围。
