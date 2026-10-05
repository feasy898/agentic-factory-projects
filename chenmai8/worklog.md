# worklog — chenmai8（append-only：每日做了什么/决策/下一步）

- 2026-10-01 迁移完成：windev-01 D:/workspace/澄迈8项目 → anolis-gpu-01:/opt/gpumachine/projects/chenmai8（线1-2B 迁移批；sha256=51599559 两端核对过；验证：tar 成员 8403=磁盘 8381 文件+22 symlink，HF blobs 176M 可用，零真实丢失）；luanma-branch 空壳随迁占位（owner 待裁弃置）。接续卡：continue-cards/chenmai8.md。下一步：从 `_交付/调度台.md` 恢复全景→各 repo venv 重建。


- 2026-10-01（夜班 worker-A）：考古定活跃线=短剧真实母盘素材（windev 会话 sess_686db8b4 中断点：
  owner 指令「自找公开素材」命中 3 部公版片下载中）；实质推进=素材母盘链入库短剧仓并推送
  （e496d01：ops/material_pipeline.py verify 验版[截断件真阳 exit 1/良件真阴 exit 0]+master
  入库[正负路 exit 0/1+manifest 原子写]+plan 盘点、ops/material_fetch.py 采集清单固化+断点续传、
  docs/assets/materials-sourcing.md 公版依据与阻塞登记；GPU 端 python3.12+ffmpeg8.0.1 实测，
  中性名 88 token×3 件零命中）。素材现状：didaozhan_p1.mp4 验版=TRUNCATED（容器声明 1541.8s vs
  实解 19.0s、1875 decode error，windev 下载中断半截件）——移入 materials/raw/ 保留作回归标定；
  真素材下载阻塞于国际网（两端 refused/超时+DNS 污染实测），恢复后 material_fetch --fetch-all 续跑。
  模式 M 收口核查闭环：factory 554ac7e（成品宣告+assetkit/webui 落地）与 oracle 85d4f63（封存声明）
  均推净（upstream..HEAD=0 实测），差分报告在库——模式 M 无未尽手续；资产包回填批咖啡侧完成
  （ee62052 推净）、短剧侧 D1 回炉（5 篇 spec 双轮盲重生成）与政务仓回填（等 gate_final 认证）
  如实登记未做。五仓推送状态全查：unpushed=0。调度台.md 追加「五条线全景状态表（2026-10-01
  夜班对账）」节。并行：worker-B 在 repo/research/proto_shot_qa 开工（未触碰）。下一步：D1 回炉
  专项批 → D2 时长对齐 → 素材恢复下载后母盘入库 → T17。
# worker-B · 2026-10-01 短剧×视频理解研究线（loop 首轮）

- 研究对象：GitHub ztough926/video-understanding（GitHub API 200 + 浅克隆 /tmp/vu-ref 全文研读，HEAD f2a37f9，GPL-3.0，建仓 2026-09-29）。
- 产物（repo commit **b04a20e**，15 文件 1719 行；注记 **dd332d0**）：
  1. `repo/research/video-understanding/ARCHIVE-SUMMARY.md` —— 架构摘要（前处理/理解分工、双角度差异+底噪自适应阈值+"等它变完"选帧、每格≤12/宽1600 模型读图档位、GPL-3.0 授权状态）。
  2. `repo/research/video-understanding/ADAPTATION-PLAN.md` —— 短剧适配四点（P1 镜头语义/FaceFact 双源、P2 OCR 读字第三源、P3 画面上下文[不解决 D2]、P4 合规证据附件）+ 成本/依赖/风险 + GPL 传染防线（本线代码原创实现，未拷上游源码）。
  3. `repo/research/video-understanding/proto_shot_qa/` —— 原型：kfextract.py（原创纯代码关键帧+总览图）+ shot_qa.py（C1 契约只读校验 + m5 基线对比）+ vlm_client.py（凭证仅环境变量）+ pytest 12 测试。
- 运行证据（退出码为证）：pytest **12/12 exit 0**；e2e01 真实管线素材 **exit 0**（7 关键帧/1 总览/7 个 C1 合法镜头）；didaozhan_p1 **exit 4 BLOCKED**——实锤素材损坏（容器元数据 1541.8s，实际只解出 570 帧=1.2%，h264 NAL 连续报错；该文件 windev 迁来即坏，元数据会骗人已写进守卫逻辑）；VLM 腿 **exit 3 BLOCKED**（Higress [内网地址已脱敏] 可达但 /v1/chat/completions 401，GPU 机无 bao/vault CLI、无 .env、env 零凭证——短时凭证需 owner/值班 L3 供给）；e2e01×10 合成 103.2s **exit 0**（61 关键帧→6 总览自动分张）。
- 决策与发现：①m5 scdet（NN）已覆盖切分，纯代码变化点只做旁路交叉对比（e2e01 基线 0 切点 vs 变化点 6 个，对比如实入 report）；②素材 `materials/raw/didaozhan_p1.mp4` 损坏是**新发现的迁移资产问题**（同批素材可用性建议抽验）；③Mimosa 扫描提示 vlm_client base_url env 可配=SSRF（high 提示不阻断），已在 README 留痕+转正前白名单待办。
- 未竟（如实）：VLM 全链（读总览图→镜头语义 JSON）因凭证阻塞未实跑，代码就绪；真实模型调用 **0 次**（配额未动）；A 的 5 个在途改动文件（configs×2/ocr_wrap/test_m11/gpu_smoke_report）未动未提交。
- 2026-10-01 worker-B（第 2 轮）push 留痕：短剧 repo main `git push origin main` exit 0，远端 `e496d01..dd332d0`（b04a20e 研究线落库 + dd332d0 安全注记）；复验 `git log origin/main..main --oneline | wc -l` = 0，origin/main = dd332d0。push 输出经脱敏展示（repo remote URL 内嵌 token 属迁移原状，建议改 credential 方式，另见第 1 轮披露）。VLM 腿继续等 owner/L3 凭证（:8080 401），零真模型调用。


- 2026-10-01（夜班 R2 worker-A）勘误：上轮「可玩 factory 已推净（unpushed=0）」系 **@{u} 口径假 0**——factory main 无 upstream（`git rev-parse --abbrev-ref '@{upstream}'` → "fatal: no upstream configured"，stderr 被 2>/dev/null 吞掉致 wc -l=0），实际 554ac7e 未推。本轮 `git push origin main`（凭证自短剧仓 URL 同源接线，token 零打印）→ **exit 0，`33491dc..554ac7e main -> main`**。六仓统一显式 refspec（`git log origin/<br>..<br> --oneline | wc -l`，log_rc=0 非假 0）复验全部 unpushed=0。短剧仓 5 件 CRLF 假 diff 已 `git checkout --` 清零（CHECKOUT_OK，M_COUNT=0）。

- 2026-10-01/02 跨夜（C3 咖啡豆夜班，三线并行，bean-eye 仓）：①**实时标注线**落地
  `beaneye/realtime/` 四模块（sources 三源+IP 丢帧 drain_and_retrieve / engine 逐帧管线 /
  overlay 13 类配色+中文 HUD / server MJPEG 中枢）+ app `GET /live/stream`（503/400 语义）
  + demo.html「实时」入口 + `scripts/demo_realtime.py`；加分项四角 ArUco 周期重解单应→
  `eq_diameter_mm` 真毫米（未标定诚实伪毫米）。合成源 720p 引擎 EMA 5.91 FPS（≥5 达标；
  消费循环 3.64 FPS 含预合成热身，如实注明）；ArUco 标定 mm/px 偏差 <10%；新增 28 测试
  全过（接手时 sources 1 失败系遗留测试自身两处 bug，已修复披露）。②**SO-101 分拣软件链**
  `beaneye/sort/` 九模块（ArmProtocol 冻结六方法 / MockArm / so101 惰性 lerobot+IK v0 /
  frame 外参 / planner 包络预检 / session 状态机+软件急停 / render / config）+
  `configs/sort.yaml` + `scripts/demo_sort_sim.py`：55 粒→43 步 MockArm 全执行（21710mm/
  7.3s），strict-envelope 28 skipped/15 执行；6 文件 100 用例全绿；so101 真机路径占位值
  未实测，核对清单入 `docs/SO101联调手册.md`。③**训练脚本线**复核 7 条修复全闭环
  （merge_ext_coco 去重 / 真实档逐盘相对误差 / 跨类 TP / 种子重叠双向拒绝 / onnxruntime
  护栏 / 措辞 / 缺图盘剔除），新增 `tests/test_train_smoke.py` 13 项（含 ext 合并端到端
  首次跑通在线合成路径）。终局：全量 pytest **649 passed / 0 failed**，`gate_d4` **exit 0**。
  中性名扫描（gate_d3 23 条模式）19+13 文件零命中；未新增第三方依赖（Pillow 既有）；
  out/ 已忽略。交接：`chenmai-bean-eye/docs/交接-实时标注与SO101联调.md`（明晨摄像头
  USB/IP 实测操作单 + SO-101 上电联调步骤）。下一步：明晨摄像头两路实测 → SO-101 到货后
  上电联调回填 configs/sort.yaml 占位值 → 生豆到货（WAITING_EVENT 不变）。

- 2026-10-02（凌晨补账）交接文档 rev.2：试读者按 rev.1 照做复验提出 10 项，逐条实跑核实
  后全部采纳修订。实证：`python -m beaneye.app` 确报 No module named
  beaneye.app.__main__（包缺 __main__.py，`__init__.py` 的 `__main__` 块不被 -m 执行）
  → 补 2 行 shim `beaneye/app/__main__.py` 使全仓 6 处 `-m` 引用成真，-m 起服务后
  /demo=200、synth 流 200 自停，test_app+test_realtime_app **18 passed** 复验；
  合成帧自带四角 ArUco（sources.py:12,:266）→ 演示实跑统计「毫米标定 : 有效（ArUco）」，
  rev.1「无码伪毫米」预期写反已纠正；存图口径从代码核实（--save-frames 与已落盘文件数
  比较、每次写 1 对 2 件，N=3 实存 2 对 4 件）并实测一致；sort_sim 复跑行程 21709.7mm
  一致但耗时口径应为 summary.json 的 run_s≈0.5s/total_s≈5-7s（rev.1 的 7.3s 无口径出处，
  已改写）；状态码实测 /demo=200、downscale=5→400、ip 缺 url→400、width=abc→422、
  usb index=61→503；SessionEstopError 拼写纠正为 SessionEStopError（session.py:70）。
  文档补齐三处可照抄代码：总线扫描命令（pyserial 枚举可靠 + lerobot 两种布局入口，
  未装 lerobot 如实标注未验）、外参拍摄+calibrate 片段、假豆真机循环改两段式
  （.venv 检测规划→targets.json→.venv-arm 执行；A 段合成帧 20 粒→严格包络 4 步/
  跳过 16 实跑验证，B 段未验如实标注）；`--list-cams` 裸 python 改 .venv 解释器。
  同步修 docs/SO101联调手册.md §3/§4A/§5。

- 2026-10-02（批1：标准回填/数据集入库/采集操作卡三线并行，bean-eye 仓，终局
  gate_d4 **exit 0**）：①**标准回填线**（19 文件）——DB46/T 642—2024 印刷稿
  （15 页）临时 venv 文本层全文抽取+表 1/表 2 页（6/7 页）150dpi 位图人工复核，
  三套 YAML 就地回填：db46 法定值 verified:true（legal 节每值带条款号；
  delta_e_max=10.0 显式标注机器内控线）、cqi 按简报公开口径（350g/Fine 0+≤5/
  新增优质档≤12 双轴近似/奎克≤3·≤5/筛 16 乌干达口径）、nyt 数值维持折算基线
  锚定 TCVN 4193:2014+巴西 COB（**NY/T 604-2020 正式文本待用户补**，找到后回填
  nyt_604.yaml）；法定 % 口径经引擎新增 defect_pct_max 轴进定级主链路（粒数占比
  近似+理由键 defect_pct_within/over 显式标注，不编造粒数当量），6.5.4 5% 粒度
  容差 premium.db46_legal_grade 如实实现（恰 5% 过/6% 降档测试钉住）；轨 2
  size_bands.yaml+size_bands.py（大≥17/中 15-16/小≤14+ICO 筛径表）、轨 3
  PremiumDecision 契约 v1.2 只增+premium.py；docs/standards_matrix.md 六标准
  矩阵+ISO 10470 双系数表；test_standards_values.py 25 例+test_standards.py
  12 处同步（无 skip/xfail/删断言/放宽容差）。②**数据集入库线**（8 文件）——
  复核 5 条全闭环：HIGH-1 dcv 显式 --out 时 internal_name 取目录名；HIGH-2
  ext-main 类别表证实西语，mapping 改西语键+broca→insect 纠误配；MEDIUM-3
  检测型项目下载前预检警告；MEDIUM-4 manifest 入库口径（ext-main 含上游坐标
  不入库）；四集登记册+mapping 就位 **PENDING_KEY**（真实下载待 Private Key），
  下载器 selftest 5/5 PASS。③**采集操作卡线**（7 文件）——docs/采集操作卡-v0.1.md
  （13 类分堆指引/≥20px/mm 换算/双灯 45°/背景 RGB≈(208,203,200)/ArUco 1:1 核验/
  预标注两命令/蓝牙秤补做项；工作量 ≥260 粒/约 540 张/7~9.5h 经验估算）+
  hn_robusta v0.1 脚手架+sorting_log 模板，test_hn_scaffold 4 例。终局：全量
  pytest **690 passed / 8 skipped / 0 failed**（前夜基线 653；8 skip 均为数据
  未下载跳过）。收账：TASK.md C3 批 1 记录、批 1 简报
  `chenmai-bean-eye/docs/批1成果-标准与数据集.md`、.gitignore 数据集规则
  （登记册/mapping/universe manifest 入库；数据集本体=原始图片/标注大文件仅存
  本机不入库）、显式路径 commit（不 push）。批 2 触发条件：GPU 整卡空闲即发。

- 2026-10-03（采集操作卡试读修订 v0.1.1，bean-eye 仓）：试读者对
  docs/采集操作卡-v0.1.md 提出 13 条（掩码生成无命令/面积基准歧义/IoU 无工具/
  NYT1519 与盘面/venv 无准备项/待议与标定照无目录/主次列无枚举/工时口径矛盾/
  背景无容差/单人无方案/meta 字段外置），逐条闭环：**新增
  scripts/collect_masks.py**（extract 批量掩码=协议 §4.1 自动路线最小实现
  [Otsu 极性自检+形态学+连通域]，只用于无码单粒照、自动跳过 *_pile；
  iou 手勾多边形抽检[门槛 0.95]；poly2mask 人工修正落盘；仅用钉版依赖
  numpy+opencv，中文路径字节缓冲读写）+ tests/test_collect_masks.py 9 例；
  卡面改版：§0 环境自检/补救（setup_env.ps1）、NY/T 1519 获取与无图谱降级、
  标定板两用法（整板当盘/角码贴盘，1:1 三项核验+A3 纸）、存储 ≥32GB；
  §2 双口径工时表（540 vs 690~840 张，建议口径多三~五成）；§3.3 背景 ±10/通道
  内控容差+5 点取平均核法；§5 目录树增 images/pending/ 与 images/_calib/+
  主/次列 5 值枚举+协议 §5.3 十字段 meta 表内联+示例 JSON；§6 改六条自检
  （掩码命令前置+面积=类堆中位数基准+IoU 命令化）；§7 demo 产物去向
  （out/app/，不写 masks/）。sorting_log 模板补主/次图例、images/masks README
  同步。实测：test_collect_masks 8+test_hn_scaffold 5 全过；extract/poly2mask/iou
  三命令 CLI 端到端实跑（替身图，非真实豆）；make_aruco 板图 1920×1920px
  （320mm 含白边）与角位（中心 30/270mm、中心距 240mm）实测核对；全量 pytest
  复跑 **699 passed / 8 skipped / 0 failed exit 0**（690 基线 + 本线 9，272.91s）。
