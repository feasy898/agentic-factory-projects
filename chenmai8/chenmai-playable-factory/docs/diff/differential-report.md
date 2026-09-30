# 模式 M 差分终审报告（任务 D-1）

> 生成：2026-09-30T06:48:16.284Z。裁决依据：plan/模式M-技术选型决策.md §3（差分计划/预declare 清单/硬线 D1-D9）。
> oracle=repo/（封存只读，冻结 venv CLI 子进程驱动，零写入）；factory 批次 1+2 全绿基础上差分。
> 本报告所有数据均为本会话真实执行产物，证据文件路径逐条可溯。

## 0. 结论

- **回归（D 硬线违反）：2 项** → 判定 **FAIL**
- 非 P 清单差异：1 项（PKG-02 mintegral manifest.warnings 提示性告警未移植——产品字节无影响、无 D 线覆盖，按 §3.4/批次 3 出口门处置：修复或台账登记）
- 预declare P1-P6：逐项判定见 §5（P3/P4 带降级登记）

## 1. ① 48 包双实现出包差分（F2）

- 48/48 格结构等价：包文件集、manifest 键集与语义字段（rulesVersion/channel/locale/project/maxBytes/packageFiles/files[].path/role）、zip 条目名+顺序精确相等、tar.exe 独立解包文件集、零外链、mraid 渠道语义（meta 禁注入：双侧 0 个 mraid <script>；applovin 双侧 1 个）、入口脚本标记（PF_SPEC/PF_LOCALE/PF_ASSETS）、HTML 资源清单（script/style/data-URI/canvas/pf:ready 计数）。
- 字节级：模板重写预期不等（0/48 字节全等），**大小差 max 0.051%、中位 0.015%**（±5% 线内）。
- 实现内两次构建字节一致：oracle ✓ factory ✓（同输入同路径两遍，index.html+manifest 逐字节相同；tiktok zip 渠道 d3 pack-repro 双侧一致）。
- 数据资产字节复用核验（差分前提）：specs-eval 13 件 + playable-spec.schema.json + channel-rules.json（rulesVersion 1.1.0）+ vendor engine.js（1,207,764B）repo↔factory 全部 SHA-256 相等。
- **PKG-02（非 P 清单差异）**：mintegral 8 格 manifest.warnings oracle=["dist 内没有外链 <script>，build.js 为空占位"] vs factory=[]（repo packages/packager/src/html.mjs:167 的提示性告警未移植；build.js 55B 占位两侧逐字节相同，产品无影响）。

## 2. ② 交叉质检矩阵补全 48 件（F3/D5）

- 设 O=oracle 判官（venv python -m qacore）、N=新判官（qacore/cli.mjs）、A=oracle 产物、B=新产物。执行规模：48 格 × 2 判官 = 96 跑真实浏览器质检。执行账目：首轮并发 2 完成 91/96 跑（≈22min，单跑 ≈25-30s）后进程因系统资源紧张中断（宿主侧 fork 风暴，非差分缺陷）；断点续跑补齐 10 跑后出全量判等。全部报告留存 NA/OB 目录，被负载污染的首轮尝试留痕 tainted-attempts/（10 份，CHK09 毛刺，clean 复测已覆盖）。
  - **qacore_N(A) ≡ qacore_O(A)：43/48 格不等（回归，见 QC-02）**——不等项全部为 CHK04（首交互前静音）：N=fail / O=pass；facts 键集合 48/48 全等；5/48 格 statusEq（竞态获胜格）。
  - qacore_N(B) ≡ qacore_O(B)：48/48 逐 CHK 全等 ✓
  - facts 键集合相等（顶层/muteLoadTime/viewport_shots.portrait）：48×2 格全等 ✓
  - qacore_N(B) 0 fail：48/48 ✓（CHK02/CHK06 skip 为合法语义）
  - load_ms/endMs 同量级：带外比值 0 处（首轮 2 处带外为共享机负载毛刺，归档后 clean 复测带内，原始尝试留痕 tainted-attempts/）
  - 归因实验（E1-E10，tmp/audioprobe|drive-replica|drive-full|drive-e7|drive-e8|hook.cjs）：探针/引擎/浏览器开关字节级一致下，N 判官 iteration-1 采样相对引擎 AudioContext running 翻转窗晚几十毫秒 → 43/48 采到 1；solo 复现 N 3/3 fail、O 3/3 pass；非 autoplay 快速质检同族竞态（N 4/4 读 PF.isMuted()=None）。

## 3. ③ CLI 退出码矩阵（F7）

- 无浏览器组（20 组）：PASS（双实现同判）
  - validate：11 件 eval + glob + 无参数用法错 → 双实现 exit 全等（golden/demo-zh=0、bad×6=1、无参数=2=2）
  - make：无 --spec=2/2、坏 spec=1/1、未知渠道=2/2；packager：无参数=0/0（帮助）、未知渠道=1/1
  - 同输入两次构建字节一致（pack-repro）：oracle ✓ factory ✓
- 浏览器组（25 组）：不等 1 组
  - qacore：CHK09 阈值 0.001s 强制失败=1/1、产物不存在=2/2、无参数=2/2（手工复核）；serve：根不存在语义同判
  - pass 产物快速质检：N=1 / O=0 —— QC-02 同族 CHK04 时序竞态的非 autoplay 表现（同 factory 产物，N 读 PF.isMuted()=None 判 fail，O 读 true 判 pass）

## 4. F1/F6 复验（D1/D4 的 M1 面）

- F1 校验裁定 11/11：新 TS 校验器 vs oracle JS 镜像 vs oracle Python 权威三方 ok + issue 集 {path,code} 全等（本会话重跑 spec-eval-diff.mjs，PASS）。消息人读不锁（spec-contract §2.5）；ajv(jsonschema) 措辞差异见 d3 证据（如 required 字段消息措辞），path/code 全等。
- F6-M1 数值向量 14 组逐值全等（Lcg 三自由度/match3 board+findMove/pullpin roles/sort scramble+solved）。
- 全量矩阵：oracle 冻结 e2e 新跑 48/48 pass（wall 655.2s，jobs=2，0 retried）vs factory 批次 48/48 pass（wall 655.3s，jobs=2，7 retried）——同机同条件持平。

## 5. ④ 预declare P1-P6 逐项判定

- **P1**（predeclared）：可解性单一真源达成：factory/packages/spec/src/invariants.ts:231-246 registerTemplateCheck/listTemplateChecks/clearTemplateChecks 注册制接缝 + validate.ts:52-56 进程内消费（schema→不变式→注册 check，单一 TS 源）；oracle 为 python/pfcore/validation.py 权威 + packages/spec JS 镜像双实现。机制演示（本会话实跑 tmp/p1-demo.mjs）：模板侧 registerTemplateCheck({template:'match3',check}) 后 validateSpec 进程内消费其 issue（ok 翻转）；冻结单测 invariants.test.mjs:196-206 以第 5 玩法 'fifth' 注册断言 listTemplateChecks()==['fifth','match3']——新增玩法只需模板包一处注册。F1 11/11 全等不受影响（M1-01）
  - 证据：factory/packages/spec/src/invariants.ts；factory/packages/spec/test/invariants.test.mjs；factory/tmp/p1-demo.mjs；factory/artifacts/diff/M1.2a-spec-eval.json
- **P2**（predeclared）：单运行时达成（本机可验部分）：factory 产品树（pf/ qacore/ packages/ webui/ scripts/）0 个 .py、0 处 python 调用（grep 全扫，仅注释提及迁移来源）；本会话全部门/矩阵/CLI 由 node+playwright 驱动，oracle venv 仅作差分参照（决策 §3.1）。『干净 Windows 机两步安装演练』属破坏性验证（需清 factory node_modules），本差分未重复执行——README.md:9 已固化两步安装（npm ci + npx playwright install chromium），此前批次安装即按此完成
  - 证据：grep 实测；factory/README.md:9
- **P3**（predeclared（非劣达成；≤250s 目标线未达，降级登记））：P3 判定（给数据）：并行化已实现（两侧 e2e 默认 jobs=4/本机建议 2）；本共享机多代理负载下双方 jobs=2 实测 oracle 655.2s vs factory 655.3s（同条件持平，非劣达成；oracle 留档 422.8s 串行、本会话前 oracle 361.6s 为安静机数据）。决策目标线 48 包 ≤250s 未达（机器负载主导；CHK09 冻结 2.0s 阈值下并发上限 2）。『抽 4 格串行复跑对账』已执行：4/4 pass，逐格 CHK 与批次矩阵全等。『并行失败自动降级串行重判』未实现为自动机制，factory e2e-matrix.mjs 采用同判官抖动单重试（首检 FAIL 至多重跑一次，两跑留痕），48 格 7 格重试后全过——按 P 线未达标降级登记，不阻塞
  - 证据：两仓 scripts/e2e-matrix*；tmp/diff/oracle-matrix/summary.json；factory/artifacts/matrix/summary.json
- **P3-RUN4**（consistent）：抽 4 格（4 模板 × en × applovin）jobs=1 串行复跑：4/4 pass 0 fail，逐格 CHK 状态与批次矩阵报告全等
  - 证据：tmp/diff/rerun4/summary.json
- **P4**（predeclared（实质达成；schema 工件未落地，降级登记））：报告 schema 化：report.schema.json 文件在 factory 未创建（全仓 *.schema.json 仅 playable-spec.schema.json）——P4 工件缺失。实质（字段零增删）已达成并有数据：本会话 96 份报告（oracle 新跑 48 + factory 48）字段签名完全单一（顶层/facts/muteLoadTime/viewport_shots.portrait 键集 + CHK01-CHK10 逐项键集，distinct signatures=1），即新判官报告对 oracle 报告字段零增零删。按 P 线降级登记，不阻塞
  - 证据：factory/tmp/diff/crossqc/ 与 factory/tmp/diff/oracle-matrix/ 全部 report.json 签名聚类；factory/packages/spec/playable-spec.schema.json
- **P5**（predeclared）：zip 交叉验证去 venv 化达成：factory/packages/packager/test/run.mjs:137-141 以系统 tar.exe（bsdtar/libarchive）为独立读取器，CRC 损坏即非零退出；oracle run.mjs:137-155 为 python zipfile+venv 条件分支且带 SKIP 兜底（:155 '[SKIP ] mintegral: python zipfile 交叉验证（未找到 venv python）'）——factory 该 SKIP 分支已删除（grep 零命中），断言总数保持 46（本会话实跑 run.mjs：46/46 PASS exit 0），断言语义保持（条目名/入口引用/CRC）
  - 证据：factory/packages/packager/test/run.mjs（本会话 46/46 PASS）；repo/packages/packager/test/run.mjs:155
- **P6**（predeclared（仅登记，不阻塞））：make 墙钟实测（同机串行、--no-serve、en,zh × all 渠道、含首个 single-html 渠道 qacore --autoplay）：factory 38s vs oracle 40.5s（本会话同条件复测；oracle 留档 28.9s 见 repo/docs/assets/specs/pipeline-contract.md §5）。判定：factory ≤ oracle 留档 28.9s → 未达 28.9s，按决策 P6 仅登记不阻塞；factory vs oracle 同条件 更快/持平。demo-prebuilt+二维码随 make 产出（factory 已产出）
  - 证据：tmp/diff/p6-make-walls.json（含双方 make stdout 计时行原文）

## 6. 差异台账（逐项登记，不静默）

| # | 分类 | 维度 | 差异/判定 | 证据 |
|---|---|---|---|---|
| PKG-01 | consistent | F2/D2 辅助 | 48/48 格结构等价（包文件集/manifest 键集与语义字段/zip 条目名+顺序精确相等/tar.exe 独立解包/零外链/mraid 渠道语义/入口脚本标记/大小 ±5%）；字节级不等为模板重写预期，大小差 max 0.051%（±5% 线内）；字节全等格 0/48 | tmp/diff/d1-packages-evidence.json |
| PKG-02 | nonpre-diff | F2（manifest 字段语义） | mintegral 8 格 pack-manifest.warnings：oracle=["dist 内没有外链 <script>，build.js 为空占位"]（repo/packages/packager/src/html.mjs:167 的提示性告警），factory=[]（factory/packages/packager/src/html.mjs 保留 srcset/type=module 两条告警、未移植此条，factory 文档无此变更记录）。产品字节无影响（build.js 55B 占位两侧逐字节相同）。不在 P1-P6 预declare 清单；不触 D1-D9 任一硬线（D2 的 46 断言不含 warnings 内容断言，已实跑全过）。按决策 §3.4/批次 3 出口门处置：修复（移植该告警）或台账登记 | tmp/diff/d1-packages-evidence.json；两仓 packages/packager/src/html.mjs 对照 |
| PKG-03 | consistent | F2（实现内两次构建字节一致） | oracle 与 factory 各以冻结 CLI（模板 build.mjs + packager bin.mjs build）同输入同路径构建两遍：index.html 与 pack-manifest.json 逐字节相同（tiktok zip 渠道，d3 pack-repro 双实现均字节一致） | tmp/diff/d1-packages-evidence.json (repro)；tmp/diff/d3-cli-noBrowser-evidence.json (pack-repro) |
| QC-01 | consistent | F3/D5（其余腿） | 交叉质检矩阵 48 格补全（M2.2 的 4 件为 N(B) 腿，本差分补全 N(A)/O(B) 两腿共 96 跑真实浏览器质检，墙钟 0.4s 计费口径为续跑段）：qacore_N(B)≡qacore_O(B) 48/48 逐 CHK 全等 ✓；qacore_N(B) 0 fail 48/48 ✓；facts 键集合（顶层/muteLoadTime/viewport_shots.portrait）48×2 全等 ✓；load_ms/endMs 同量级带外 0 处 | tmp/diff/crossqc/crossqc-evidence.json（NA/OB 报告全量留存） |
| QC-02 | regression | F3/D5（N(A) 腿 CHK04） | qacore_N(A) ≢ qacore_O(A)：新判官在 oracle 产物上逐 CHK 与 oracle 判官判定不等 43/48 格，不等项全部为 CHK04（首交互前静音）：N=fail / O=pass（例："首交互前存在 running AudioContext（1）" vs O 同产物同探针读数 0）。已排除Harness 干扰：solo 复现 N 3/3 fail、O 3/3 pass（tmp/diff/e3a*-n-*.json、e3b-o-solo.json）；探针 PROBE_JS 3119 字符两侧逐字节一致；playwright 1.63.0 双侧默认 chromium 开关字节一致；engine bundle（含 +100ms suspend→resume 特性）字节一致。根因层：oracle 产物保留引擎真实 AudioContext（无 noAudio），其 running 态在亚秒窗口翻转；新判官（Node 异步 evaluate 链） iteration-1 采样相对翻转时刻比 oracle 判官（Python sync）晚几十毫秒 → 采到 1（ | tmp/diff/crossqc/crossqc-evidence.json；factory/tmp/diff/e3a*-*.json、e3b-o-solo.json、e9-n-*.json、e10b-n-traced.json、trace-n*.json；两仓 qacore checks 逐条对照（repo/python/qacore/checks.py:97-124 ↔ factory/qacore/src/checks.ts） |
| CLI-A | consistent | F7 | 20 组同输入探针：无浏览器组（validate 11 件/glob/用法、make、packager、字节复现）。双实现同判 | tmp/diff/d3-cli-noBrowser-evidence.json |
| CLI-B | regression | F7 | 25 组同输入探针：浏览器组（qacore 0/1/2、serve）。不等 1 组：qc-pair:pass-artifact(0) —— exit 不等 N=1 O=0（QC-02 同族 CHK04 时序竞态的非 autoplay 表现；用法类退出码经手工复核全等：oracle `python -m qacore run` 无参数实测 exit 2 = factory 2） | tmp/diff/d3-cli-browser-evidence.json |
| M1-01 | consistent | F1/D1 | F1 校验裁定 11 件（golden×4+demo-zh+bad×6）：新 TS 校验器 vs oracle JS 镜像 vs oracle Python 权威 三方 ok + issue 集 {path,code} 全等 = 11/11 | factory/artifacts/diff/M1.2a-spec-eval.json（本会话重跑） |
| M1-02 | consistent | F6/D4（M1 子集） | F6-M1 数值向量 14 组逐值全等（Lcg/pullpin roles/match3 board+findMove/sort scramble+solved）= true | factory/artifacts/diff/M1.2a-spec-eval.json（本会话重跑） |
| E2E-01 | consistent | D7 留痕 | 全量 48 包双实现 0 FAIL：oracle 冻结 e2e 本会话新跑 48/48 pass（0 retried，wall 655.2s，jobs=2）；factory 批次矩阵 48/48 pass（wall 655.3s，jobs=2，retried 7）。同机同并发墙钟差 0.1s（≈持平） | tmp/diff/oracle-matrix/summary.json；factory/artifacts/matrix/summary.json |
| P1 | predeclared | 预declare | 可解性单一真源达成：factory/packages/spec/src/invariants.ts:231-246 registerTemplateCheck/listTemplateChecks/clearTemplateChecks 注册制接缝 + validate.ts:52-56 进程内消费（schema→不变式→注册 check，单一 TS 源）；oracle 为 python/pfcore/validation.py 权威 + packages/spec JS 镜像双实现。机制演示（本会话实跑 tmp/p1-demo.mjs）：模板侧 registerTemplateCheck({template:'match3',check}) 后 validateSpec 进程内消费其 issue（ok 翻转）；冻结单测 invariants.test.mjs:196-206 以第 5 玩法 'fifth' 注册断言 listTemplateChecks()==['fifth','match3']——新增玩法只需模板包一处注册。F1 11/11 全等不受影响（M1-01） | factory/packages/spec/src/invariants.ts；factory/packages/spec/test/invariants.test.mjs；factory/tmp/p1-demo.mjs；factory/artifacts/diff/M1.2a-spec-eval.json |
| P2 | predeclared | 预declare | 单运行时达成（本机可验部分）：factory 产品树（pf/ qacore/ packages/ webui/ scripts/）0 个 .py、0 处 python 调用（grep 全扫，仅注释提及迁移来源）；本会话全部门/矩阵/CLI 由 node+playwright 驱动，oracle venv 仅作差分参照（决策 §3.1）。『干净 Windows 机两步安装演练』属破坏性验证（需清 factory node_modules），本差分未重复执行——README.md:9 已固化两步安装（npm ci + npx playwright install chromium），此前批次安装即按此完成 | grep 实测；factory/README.md:9 |
| P3 | predeclared（非劣达成；≤250s 目标线未达，降级登记） | 预declare | P3 判定（给数据）：并行化已实现（两侧 e2e 默认 jobs=4/本机建议 2）；本共享机多代理负载下双方 jobs=2 实测 oracle 655.2s vs factory 655.3s（同条件持平，非劣达成；oracle 留档 422.8s 串行、本会话前 oracle 361.6s 为安静机数据）。决策目标线 48 包 ≤250s 未达（机器负载主导；CHK09 冻结 2.0s 阈值下并发上限 2）。『抽 4 格串行复跑对账』已执行：4/4 pass，逐格 CHK 与批次矩阵全等。『并行失败自动降级串行重判』未实现为自动机制，factory e2e-matrix.mjs 采用同判官抖动单重试（首检 FAIL 至多重跑一次，两跑留痕），48 格 7 格重试后全过——按 P 线未达标降级登记，不阻塞 | 两仓 scripts/e2e-matrix*；tmp/diff/oracle-matrix/summary.json；factory/artifacts/matrix/summary.json |
| P3-RUN4 | consistent | P3 对账 | 抽 4 格（4 模板 × en × applovin）jobs=1 串行复跑：4/4 pass 0 fail，逐格 CHK 状态与批次矩阵报告全等 | tmp/diff/rerun4/summary.json |
| P4 | predeclared（实质达成；schema 工件未落地，降级登记） | 预declare | 报告 schema 化：report.schema.json 文件在 factory 未创建（全仓 *.schema.json 仅 playable-spec.schema.json）——P4 工件缺失。实质（字段零增删）已达成并有数据：本会话 96 份报告（oracle 新跑 48 + factory 48）字段签名完全单一（顶层/facts/muteLoadTime/viewport_shots.portrait 键集 + CHK01-CHK10 逐项键集，distinct signatures=1），即新判官报告对 oracle 报告字段零增零删。按 P 线降级登记，不阻塞 | factory/tmp/diff/crossqc/ 与 factory/tmp/diff/oracle-matrix/ 全部 report.json 签名聚类；factory/packages/spec/playable-spec.schema.json |
| P5 | predeclared | 预declare | zip 交叉验证去 venv 化达成：factory/packages/packager/test/run.mjs:137-141 以系统 tar.exe（bsdtar/libarchive）为独立读取器，CRC 损坏即非零退出；oracle run.mjs:137-155 为 python zipfile+venv 条件分支且带 SKIP 兜底（:155 '[SKIP ] mintegral: python zipfile 交叉验证（未找到 venv python）'）——factory 该 SKIP 分支已删除（grep 零命中），断言总数保持 46（本会话实跑 run.mjs：46/46 PASS exit 0），断言语义保持（条目名/入口引用/CRC） | factory/packages/packager/test/run.mjs（本会话 46/46 PASS）；repo/packages/packager/test/run.mjs:155 |
| P6 | predeclared（仅登记，不阻塞） | 预declare | make 墙钟实测（同机串行、--no-serve、en,zh × all 渠道、含首个 single-html 渠道 qacore --autoplay）：factory 38s vs oracle 40.5s（本会话同条件复测；oracle 留档 28.9s 见 repo/docs/assets/specs/pipeline-contract.md §5）。判定：factory ≤ oracle 留档 28.9s → 未达 28.9s，按决策 P6 仅登记不阻塞；factory vs oracle 同条件 更快/持平。demo-prebuilt+二维码随 make 产出（factory 已产出） | tmp/diff/p6-make-walls.json（含双方 make stdout 计时行原文） |

## 7. 执行清单（本会话真实运行的全部命令面）

- oracle 冻结 e2e：`repo$ python/.venv/Scripts/python.exe scripts/e2e_matrix.py --locales en,zh --jobs 2 --out factory/tmp/diff/oracle-matrix`（48 格，0 FAIL）
- 包差分：`node factory/scripts/diff/d1-packages.mjs <oracleMatrix> <factoryMatrix> <out>`
- 交叉质检：`node factory/scripts/diff/d2-crossqc.mjs <oracleMatrix> <factoryMatrix> factory/tmp/diff/crossqc 2`（96 跑）
- CLI 退出码：`node factory/scripts/diff/d3-cli-exitcodes.mjs <out> [--with-browser]`
- F1/F6：`node factory/scripts/diff/spec-eval-diff.mjs`（oracle venv 子进程）
- P5：`node factory/packages/packager/test/run.mjs`（46/46 PASS）
- P1 演示：`node factory/tmp/p1-demo.mjs`（注册制进程内消费）
- P6：双方 `make --spec specs-eval/golden-match3.json --locales en,zh --channels all --no-serve --out tmp/diff/p6/<impl>` 墙钟实测
- P3 对账：`node factory/scripts/e2e-matrix.mjs --locales en --channels applovin --jobs 1 --out tmp/diff/rerun4`

