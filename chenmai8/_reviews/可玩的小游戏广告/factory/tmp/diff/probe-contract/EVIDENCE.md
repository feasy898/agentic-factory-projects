# 旗子真值锚定与机器层竞态取证（2026-09-30，第 1 轮施工实机记录）

本目录全部为本轮 tmp/ 实验，产品树（qacore/src、packages、pf）零触碰；
oracle 仓库（../repo）只读，未写入任何文件。

## 实验 1：oracle A 产物音频时间线（probe_oracle_timeline.mjs）
命令：`node --experimental-strip-types tmp/diff/probe-contract/probe_oracle_timeline.mjs "tmp/diff/oracle-matrix/preview/golden-match3-en.html"`
（qacore 同款仿真：390×844 / isMobile / DPR2 / serviceWorkers block / route 拦截 / 现行 PROBE_JS；全程无指针事件）
结果：created=1；running=0、flag=false 贯穿 12 次采样（t≈823→2102ms，pf:ready≈183ms）。
→ 与批次 3 差分轮 trace-n2/3/4（t≈797–879ms 即读 running=1）对照：**同一产物同一探针，
running 翻转本身随机器/会话状态抖动**——今日会话无手势下上下文恒 suspended。
这正是 QC-02 假阴/假阳双向竞态的机器层根源，也是旗（事件驱动）优于瞬时采样的实证。

## 实验 2：无手势 resume 落定性（probe_cli_sequence.mjs，逐字复刻 CLI 非 autoplay 读序列）
3 连跑：flag=false / running=0（page-t 475–648ms 首读、980–1154ms 复读均 0）；
另 1 次（probe_oracle_timeline 同款夹具采样版）观察到 ~554ms 翻转——落定概率不稳定。
Chrome 无手势 autoplay 策略告警原文：`The AudioContext was not allowed to start. It must
be resumed (or created) after a user gesture on the page.`

## 实验 3：免手势确定性 running 路径（probe_postload_create.mjs）
CDP evaluate（playwright 页函数求值带 userGesture）内 `new AudioContext()` →
构造即 running，qacore-exact(isMobile) 与 plain-default 两上下文各 2/2。
→ 页级旗契约测试（qacore/tests/autoplay-flag.test.mjs）据此以 evaluate 触发确定性翻转；
CLI 层只断言阴性/接线（B-like ×5、慢桥 ×3），阳性不落在机器抖动面上。

## 实验 4：解析期创建的上下文不可解锁（probe_resume_after_load.mjs）
解析期创建（suspended）→ load+100ms resume()：promise 永不落定，flag 恒 false。
→ 引擎（Phaser unlock）在页面脚本上下文内同样受此约束；diff 轮 observed 翻转应为
引擎上下文创建/恢复时序与判官 evaluate 链、机器音频端点状态的组合竞态。

## PROBE_JS 契约修订存档（contract-change）
- probe-js-before.ts.txt：oracle 冻结版（3119 字符，与 oracle autoplay.py PROBE_JS 逐字节一致，实锚）
- probe-js-after.ts.txt：factory 修订版（3397 字符，新增 everBeforeFirstGesture 粘性旗）
- probe-js.diff：unified diff
- lab-fixture-a-like.html：真实 WebAudio A-like 夹具（真实翻转随会话抖动，不作 CLI 层门禁断言）
- 登记处：docs/specs/qacore-amendments.md（docs/specs/qacore.md 本体为登记册冻结字节副本，不可改）

## 判定输入口径修复（run.ts facts 组装）
oracle checks.py:82 `facts.get("autoplay") or facts.get("muteLoadTime") or {}`——
快速质检 autoplay={} 为 falsy 回落 muteLoadTime；JS `??` 不回落（移植偏差，曾致快速质检
CHK04 恒读空 → isMuted=None 假阴性，见 e10b-n-traced.json）。实现：未开 autoplay 时
facts.autoplay=null（报告 facts 组装本就剔除该键，报告 JSON 字段签名零变化）。

## PKG-02 复验（tmp/diff/postfix-r1/pkg02/）
match3-zh mintegral 重打包（改动后 html.mjs）：
- zip sha256 新旧全等：`9712fb7b9efc24112cdae2a488d7cce74e29b42c2a79b6ccc06ca7bc940b516f`（产品字节零影响）
- pack-manifest.warnings：[] → ["dist 内没有外链 <script>，build.js 为空占位"]（与 oracle html.mjs:167 逐字同条件同文案）
