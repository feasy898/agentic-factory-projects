# 试玩广告生产线

面向小游戏 / 休闲游戏出海买量的 HTML5 试玩广告自动化生产线：输入模板选择 + 素材，几分钟输出多渠道、多语言、通过自动质检的可玩广告。

**核心能力**

- 模板库：三消 / 叠叠消、合成类、拔针救援、拧螺丝排序等副玩法模板，参数化配置
- 一份 PlayableSpec JSON 描述玩法、素材、流程、文案，驱动整条产线
- 多渠道导出：AppLovin、Unity、Google、Meta、TikTok/Pangle、Mintegral 规则内建
- 自动质检：包体大小、外网请求拦截、首次交互静音、横竖屏、跳转接口模拟、自动试玩
- 多语言：含阿拉伯语 RTL 排版
- 截图 / 录屏生成试玩（演示级）与 Cocos 工程接入

**仓库结构（建设中）**

```
packages/       Node 侧（npm workspaces，TS）
  spec/           PlayableSpec 模式与类型
  engine-bridge/  渠道运行时桥
  templates/      玩法模板（三消 / 合成 / 拔针 / 排序）
  packager/       配置驱动的多渠道打包器
python/         Python 侧（统一 venv）
  pfcore/         编排 CLI（validate / make 全流水线；build / pack 占位）
  llmgw/          LLM 网关抽象层
  director/       截图 / 录屏 → Spec 草稿（演示级）
  qacore/         无头自动质检器
  assetkit/       素材处理流水线
channel-rules/  渠道规则库（包形态 / 大小线 / 退出接口）
assets-cc0/     开源授权素材与字体
specs-eval/     验收基准 spec
artifacts/      构建产物（不入库）
webui/          操作界面与预览
scripts/        端到端验证脚本
```

> 详细模块规格与验收标准见 `docs/`，逐模块 spec+eval 驱动开发。
