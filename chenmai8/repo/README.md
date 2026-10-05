# 试玩广告生产线

> ## 🧊 封存声明（2026-09-30，成品切换）
> **本仓自即时起冻结为回归参照（oracle）**：零新功能、零实现改动——后续一切修改仅限
> 差分/回归用途且不改变行为。**正式成品在 factory 仓**
> （`feasy898/chengmai-playable-factory`，TS/Node 22 单栈重写，模式 M 终审通过 + 独立复核）。
> 两仓对齐层 = 契约层（PlayableSpec 输入 → 产物 + 质检报告 + CLI 退出码）；
> 差分终审证据见 factory 仓 `docs/diff/differential-report.md`（PASS、零回归；
> GATE-M3 4/4）。本 README 以下内容为封存时的历史原貌，按封存时点理解，不再更新。

面向小游戏 / 休闲游戏出海买量的 HTML5 试玩广告自动化生产线：输入一份 PlayableSpec JSON，
一条命令产出通过自动质检的多渠道可玩广告包（演示默认语言：中文）。

**已接通**（仓库内可复现，2026-09-29 演示走查核实）

- 规格驱动：PlayableSpec JSON（schema v1 + 不变式）描述玩法、文案、渠道与质检预算；
  `python -m pfcore validate` 双校验（JSON Schema + Python 模型），`specs-eval/bad/` 6 个坏样本
  全部被拒且错误定位到字段路径
- 一条命令全流水线：`python -m pfcore make` = 校验 → 模板构建（三消 / 合成 / 拔针 / 排序
  四模板，真实可玩单 HTML）→
  按渠道规则库打包 → qacore 无头质检（真实指针事件自动试玩到胜利结束页）→
  汇总页 + 局域网二维码 + 墙钟计时 + `artifacts/demo-prebuilt/` 兜底目录；
  质检不过即退出 1，不产出二维码与兜底目录
- 四模板全矩阵验收（gate_phase2）：4 golden × {en, zh} × 6 冻结渠道 = 48 包全量
  真实构建 → 打包 → 逐包 qacore 质检，0 fail 且在预算内（`scripts/gate_phase2.py`）
- 六渠道打包（规则库已冻结的六投放渠道）：AppLovin / Meta 单 HTML；Mintegral zip
  （Template.html + build.js）；Google / Unity zip（入口 index.html 全内联）；TikTok/Pangle zip
  （index.html + config.json + js-sdk 桩），各带 pack-manifest 旁车
  （2026-09-29 实测：golden-match3×en 六渠道全出包且各过 qacore，84.5s）
- 自动质检（qacore 十项）：包体上限、外网请求拦截、首点前静音、横竖屏、文案与替换素材上屏
  （CHK10）等；未实装项如实标 skip，不算通过
- 演示走查：`python scripts/demo_walkthrough.py` 自动改 spec（中文标题 + seed+1）→ 跑 make →
  断言预览 / 三渠道 / 报告 / 二维码 / 兜底目录全部落盘并打印墙钟计时
  （留档 28.9s、最近 45.36s，均在 90s 反馈理想值内；预算 180s）
- 局域网伺服：`python -m pfcore serve` 伺服既有产物目录，现场重建汇总页与二维码（演示日兜底）
- Web 操作台（webui，M10）：`python -m webui.app --port 8788` 起本地界面（FastAPI + 单页、
  零外链、无登录仅局域网）——选模板 / 传 PNG 素材（按槽位键替换）/ 填文案（每语言内置可改缺省）
  → 组装 PlayableSpec（match3 seed 可解性与 pullpin orderSolution 复用 pfcore 校验器权威实现，
  组装后仍过 schema+不变式双校验）→ 后台跑 `pfcore make` 全流水线 → 状态轮询 →
  二维码（指向本机 LAN 地址）+ 质检报告 + 渠道包下载（/artifacts/webui/<任务> 挂载伺服）；
  也可直接上传 spec JSON。自验收 `python -m webui.selftest`：httpx 端到端（上传 demo spec →
  轮询 done → 产物链接逐个 200、质检 0 fail），2026-09-29 实测 68s exit 0
- 运行时桥（engine-bridge）：六渠道退出路由与静音策略有单元测试覆盖，零运行时第三方依赖
- LLM 网关（llmgw）：超时 / 重试 / 降级 / 图片 / JSON 模式 + 离线 mock 自测通过（暂无生产调用方）

**预留**（规格 / 占位，未接入演示路径）

- 模板与全矩阵已接通（见上）：三消 / 合成 / 拔针 / 排序四模板 48 包全矩阵 gate_phase2；
  尚留 `pfcore build` / `pack` / `rules-check` 占位子命令（exit 2，全流水线统一走 make）
- 渠道：六渠道规则已冻结并全出包实测；qacore 单命令仍只收单 HTML（zip 渠道包由
  e2e_matrix / finalize 先按规则库入口解包再质检）；CHK02 文件数、CHK06 退出接口两项未实装，
  各渠道报告如实记 skip
- AI 生成：director（截图 / 录屏 → spec 草稿）仅有包占位、修复循环未开工——
  模型接口已留，不演示生成
- 截图 / 录屏生成试玩、Cocos 工程接入：未实现；素材流水线 assetkit 已实现并在 make
  接线（见上）；webui 的 sort 模板入口待 specgen 注册后开放（当前可选三消 / 合成 / 拔针）

**仓库结构（建设中）**

```
packages/       Node 侧（npm workspaces，TS）
  spec/           PlayableSpec 模式与类型
  engine-bridge/  渠道运行时桥
  templates/      玩法模板（三消 / 合成 / 拔针 / 排序）
  packager/       配置驱动的多渠道打包器
python/         Python 侧（统一 venv）
  pfcore/         编排 CLI（validate / make 全流水线 / serve 演示伺服；build / pack 占位）
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
