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
docs/       架构、PlayableSpec schema、模块契约、spec + eval
templates/  玩法模板
builder/    配置→构建→渠道打包
assets/     素材处理流水线
qa/         自动质检器
web/        操作界面与预览
```

> 详细模块规格与验收标准见 `docs/`，逐模块 spec+eval 驱动开发。
