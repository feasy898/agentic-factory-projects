# qacore/ — M8 判官（批次 2，M2.2 已落）

Node + Playwright 移植（TS/Node 22 单栈，零新增第三方运行时依赖——除 playwright 1.63.0 钉版）：
探针 PROBE_JS、手势表、魔法数字表逐字照抄；MUT-01/02/04 构造算法逐条照搬；
报告 JSON 字段 = pipeline-contract §4 逐字段；mini.html 夹具字节复用（REUSED-ASSETS.md #39）。
CLI 表面：`node qacore/cli.mjs`（`python -m qacore` 迁移，决策 §2.2）。

## 布局

```
cli.mjs            入口：argparse 语义（run/<artifact>/--channel/--out/--port/--max-load-sec/
                   --autoplay/--autoplay-timeout/--require-text/--require-sprite），
                   退出码 0/1/2（无 fail / 有 fail / 产物不存在或非 .html 或用法错误）
src/
  run.ts           编排：本地伺服→横竖屏双仿真（isMobile+DPR2+SW block）→请求/WS 记账
                   →探针注入→（--autoplay 竖屏驱动）→截屏→facts→报告
  server.ts        ArtifactServer（node:http，127.0.0.1 临时端口）+ 仓库根定位
  rules.ts         规则库消费（maxBytes/runtime 脚本/静音缺省：渠道 runtime > defaults > true）
  probe.ts         PROBE_JS（与 oracle autoplay.py 逐字节一致，机械比对 3119 字符全等）
  autoplay.ts      驱动与手势表（44px×4 步定向拖拽/tap 兜底）、__PF_QC__ 采集辅助
  checks.ts        CHK01–CHK10 判定（pass/fail/skip 语义与 oracle checks.py 逐项对齐）
  ev.ts            evaluate 适配（node 侧字符串函数源码 → 真函数；Python 自动识别的等价物）
  pngvar.ts        截图灰度方差（零依赖 PNG 解码 + Pillow 同式 L24 灰度 + 同核双三次 64×64）
tests/
  fixtures/mini.html   金标夹具（字节复用 #39，只读；mutant 构造按 universal-newline 归一）
  mutations.mjs        MUT-01/02/04 构造算法（gate_phase0 门项 6 逐条照搬；恰命中断言用）
  unit.test.mjs        纯逻辑向量（checks 判定/MUT 构造/方差/规则库）——root npm test 内含
  qacore.test.mjs      浏览器层：门项 5（金标夹具）+ 门项 6（三变异恰命中）+ 退出码契约
                       + CHK10 阴性对照（--require-sprite/--require-text 非永绿证明）
  templates.test.mjs   四模板本判官复验（构建→--autoplay 全过 + demo-zh CHK10 实装层）
```

## 命令

```bash
npm run test:qacore      # 浏览器层 eval（需 chromium：npx playwright install chromium，
                         #   本机缓存 chromium-1243 与 oracle Python 侧同 build，R2）
npm test                 # 含 unit.test.mjs（无浏览器层）
npm run typecheck:qacore # tsc --noEmit
```

## 移植留档（2026-09-30，详见 REUSED-ASSETS.md M2.2 注）

- **R2**：playwright 1.63.0 钉版，chromium-1243（153.0.8010.12）与 oracle Python 侧同 build；
- **R1**：方差实现按 Pillow 对齐（L24 整数式灰度 + 缩小时支撑窗按 1/scale 展宽的双三次），
  五模板截图对照相对差 ≤0.04%，空白/非空白状态全等（CHK05 只消费阈值状态）；
- **oracle 交叉对照**：四模板 golden + demo-zh 逐 CHK 状态 4/5 全等，唯一差异为 match3 那轮
  CHK09 墙钟抖动（该轮 oracle 自身 fail）——墙钟抖动双侧对称，非移植缺陷；
- **复验发现并回修的真实缺陷**（M2.1 模板，详见 REUSED-ASSETS.md）：vendor 引擎 WebAudio
  管理器启动期创建 AudioContext，浏览器授予 autoplay 时创建即 running——首交互前 running
  AudioContext 的真实 CHK04 违规（本判官实测 ~40% 触发，oracle 低触发率侥幸未暴露）；
  四模板按引擎原生 `audio: { noAudio: true }` 关闭（音效仍走 PF.audio；媒体探针不受扰），
  回修后 pullpin ×5 连跑全绿；
- **MUT-03**（结束页不可达）与 `mutation-test` 独立子命令仍列 M8 全量里程碑（spec §8）。
