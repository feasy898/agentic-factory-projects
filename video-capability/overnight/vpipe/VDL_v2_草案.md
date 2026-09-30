# VDL v2 草案 —— 基于 VPO 评估结论的分程度采纳设计

> 成稿：2026-09-30｜起草依据：VPO 评估结论（verdict=**分程度结论：语义与验收层直接采用，执行/生产图层不搬**）+ 本项目实测资产（工程方案v3 / 边界测试方案 / vpipe v1.0 冻结契约）。
> 定位：**VDL v2 与 v1 契约并存，v1 冻结不破坏**（vpipe 已冻结用于重生成，SPEC.md §0 契约纪律）；迁移工具后做（§7 只给规格不实现）。
> 铁律继承：金标永不入训练；判定阈值只存 `eval/thresholds.yaml`；失败如实记录不谎报；本草案全部引用逐条标注出处，未经实测处显式标注。

---

## 0. 评估结论与采纳裁定（本草案的唯一依据面）

**verdict（评估结论原文）**：分程度结论——语义与验收层直接采用，执行/生产图层不搬。

裁定落成三句话：

| 层 | 裁定 | 依据（全部实测或逐行核对） |
|---|---|---|
| VPO L2 指令层 + L4 验收层 | **直接采用** | ① 外部效度：VPO 附录 D0「文本控语义，图像控几何，API 参数控时长，参考视频控运动节律」（VPO开发指令书_v1.1_自包含版.md:681）与 D1 意图维度可靠性分级（:683-697）、D2 参考图vs文本命中差（:699-711），与本方边界测试独立实测互证（工程方案v3.md §2.1 九轴分工表 G1-G9 行，:48-60；API seed 零控制力，:37）；② 本会话 23 个 VPO schema 编译通过、4 类实例校验 0 错误、not-pattern/防线负例全部命中（§8 实测记录） |
| VDL 执行编排层 | **新建 v2（本草案）** | engine 选择/seed 策略/渲染参数/缓存键/edit-op 这些 VPO **刻意不承载**——CONTROL-MAPPING.md:70-76「提示词编译（主体+动作+场景结构、@Image1 槽位文案）：执行器职责；本体只约束槽位顺序与贡献合同」；本项目对这一层握有全部实测数据（确定性梯度 工程方案v3 §5.1，:153-160；缓存两层结论 §5.3，:166-170） |
| VPO L1 / L3 / L5 与生产图意图 | **不搬** | L3 executor-contract/work_items/capability-profile 与 VDL 定位重叠且绑定其 package 校验器体系；L1 工作级结构、L5 provenance 序列化在本方由 v1 asset_manifest（provenance 位实测承载）与外部剧本管理。借鉴其**纪律**而非结构：三数字体例 value+unit+measurement_basis（tolerance.schema.json:42-51 dependentRequired）、seed 非连续性钥匙、prompt_hash 留痕（executor-contract CE-19 G3）。逐条清单见 §9 |

**采纳的公共底座**（评估结论指名，本会话逐行核对）：
- `D:\workspace\video-Ontology\schemas\common\intent-common.schema.json` —— E6 十二元组（identity/intent_type/target/scope/temporal_extent/reference_context/predicate/strength/tolerance/exceptions/acceptance_ref/authority，:7-21）+ G5 增 `control_channel`（required，:238-245）与 `field_channels`（可选，:226-237）+ G3 缺省四态 `absence`（:180-184，四值注册于 concepts/registry.jsonl:586-590：explicitly_unconstrained/not_applicable/pending_upstream/unprovided）+ 工具名 not-pattern（:170-179，`predicate`/`value` 双字段黑名单）。
- `schemas/l2/*` —— 实测 19 个意图 schema 文件（本会话 `ls` 计数 19）。首批采纳评估结论指名的 9 个：**camera / performance / limited-motion / audio / text-overlay / transition / loop / deliverable-set / postprocess**，理由=覆盖短剧线 G1-G9 全轴（映射见 §4）。
- `schemas/l4/acceptance-spec.schema.json` + `acceptance-record.schema.json` —— AcceptanceSpec 执行前定（gate 三值 block/flag/human，:79-82；advisory_benchmark 隔离不进 gate 命名空间，:87-128）、AcceptanceRecord 执行后录（五态 status，:91-94；`treated_as`/`gate_result` 防 unknown≠pass 陷阱字段，:122-137）。
- 评估结论原文在「D:\workspace\video-Ontology\sc…」处截断，截断内容未采用、不臆测；L4 采纳以本会话实际读取的两份 schema 文件为准。

---

## 1. 五层栈与编译管线图

```
外部需求（剧本 / 口述 / 工单）
   │ 人工或上游结构化（本层 v2 不自动化）
   ▼
┌─ VPO L2 意图层【直接采用，schema 一字不改】──────────────────────┐
│ intents/*.json：首批 9 意图（19 备选），IntentCommon 十二元组底座   │
│  · control_channel 五值通道（registry.jsonl:631-635）：             │
│    text控语义 / image控几何与身份 / api_param控时长尺寸编码 /        │
│    post_comp后期合成 / video控运动节律   ←＝ D0 的机读形态          │
│  · absence 四态（G3）：未提供≠创作自由                              │
│  · 工具名 not-pattern（:170-179）：L2 禁模型名（实证拒 "Wan2.1"）   │
│  · tolerance 三分（G2）：工作容差 ≠ 测量不确定度 ≠ 记录置信度        │
└──────────────┬───────────────────────────────────────────────────┘
               │ 编译器①（意图→执行计划）：通道分派 + prompt 编译
               │  「提示词编译为执行器职责」（CONTROL-MAPPING.md:72-73）
               ▼
┌─ VDL v2 执行编排层【新建，本草案 §2-§3】─────────────────────────┐
│ vdl_package（YAML 表面 / JSON 落盘校验）                           │
│  ├ intents[]          VPO L2 实例内嵌或路径引用                    │
│  ├ shots[]            v1 超集 + engine/seed/cache/edit_ops/        │
│  │                    continuity 观测 / prompt_mode / acceptance   │
│  ├ deliverable        DeliverableSet 引用（包级，交付合同）        │
│  ├ post_ops           PostProcessIntent 落点（包级确定性后处理）   │
│  └ acceptance[]       L4 AcceptanceSpec 实例（执行前冻结）         │
└───────┬──────────────────────────────────┬───────────────────────┘
        │ 编译器②（投影，迁移工具后做 §7.4）│ 执行后记录
        ▼                                  ▼
┌─ vpipe ShotSpec v1【冻结】────────┐  ┌─ VPO L4 验收层【直接采用】─────┐
│ shot.json（schema_version=1.0）   │  │ AcceptanceSpec：执行前绑定      │
│ = gen_local.py / gen_api.py 唯一  │  │ AcceptanceRecord：执行后落盘    │
│ 输入（shot.schema.json:5）        │  │  evaluator ← J1/J3/J6 代码映射  │
│ v1 引擎对 2.0 fail-fast 拒收      │  │  evidence  ← QCReport / 判官    │
└───────┬───────────────────────────┘  │             原始输出            │
        │ 生成（本地 0 积分 / API 280积分·条）│  status 五态：unknown≠pass     │
        ▼                              └──────────┬─────────────────────┘
   clip.mp4 + gen_meta + asset_manifest(sha256)   │
        ▼                                         │
┌─ vpipe QC 体系【冻结 v1，v2 只加挂】─────────────┴────────────────┐
│ qc_orch：E10 = J1 ∨ J3@0.70（thresholds.yaml 唯一阈值来源）        │
│ QCReport v2 = v1 全字段 + acceptance 挂接段（§7.3）                │
│ eval_run.py 检出口径不变（verdict.defect_detected）→ eval 兼容     │
└───────────────────────────────────────────────────────────────────┘
```

**为什么这样分层（三条实测理由）**：
1. **互为外部效度**：VPO D0/D1/D2 的通道分工与维度可靠性分级，与本项目九轴实测独立吻合——G2 大字可靠小字必乱（API ◐，工程方案v3 §2.1 G2 行）对应 D0「文本控语义」的粒度警告；API seed 零控制力（同 seed 汉明 102.75 > 无 seed 51.75，工程方案v3 §1 表 :37）对应 VPO「seed 仅相似令牌/非连续性钥匙」（D3 第 9 条 :722；continuity-intent schema seed 字段注释 `Similar results only … seed is not a continuity key`）。
2. **职责零重叠**：VPO 刻意把执行编排留给执行器（CONTROL-MAPPING.md:70-76），VDL 恰好补位；反过来 VDL 不在 L2 字段里写引擎参数，保住「换引擎不改语义」。
3. **验收先于执行**：vpipe 的 QC 体系（E10 合议、阈值唯一来源、契约校验）实测可复跑（V3 复验 ACCEPT 零偏差，工程方案v3 §0.2 V3 :27）；L4 把「验收 spec 先于执行定稿」提升为结构约束，正好收编本方「判定阈值先于检视写定」的金标纪律（SPEC.md §3）。

---

## 2. VDL v2 包结构（顶层设计）

### 2.1 表面语法与落盘形态

- **人写 YAML**（1.2 核心 schema，JSON 超集），落盘校验时转 JSON。
- **校验两段式**（关键设计，理由：不复制 VPO schema 防漂移）：
  - **闸门 A · 结构校验**：`vdl_package.schema.json` / `shot_v2.schema.json` / `qc_report_v2.schema.json`（新增文件，JSON Schema **draft-07**，与 vpipe 工具链一致）。对 `intents[]` 只做结构占位校验（intent_id 引用完整性、`intent_type` pattern `^vpo:craft\.intent_object\.[a-z0-9_]+$`）——draft-07 无法执行 VPO 2020-12 专属关键词（`unevaluatedProperties` 等），故不做深度校验。
  - **闸门 B · 意图内容校验**：每个意图实例按 `intent_type` 分派到 **VPO 原版 2020-12 schema**，以 `$id` 经 registry 映射到本地 `D:\workspace\video-Ontology\schemas\`（`https://vpo.example/schemas/v1/...` → 本地路径）。本会话已用 jsonschema 4.26.0 + referencing.Registry 实测该路径全通（§8）。
  - 两道闸门都过才允许进入编译器②（投影）。任一失败写 `errors`，不许静默（SPEC.md §2 纪律）。

### 2.2 包级字段

| 字段 | 必填 | 类型/约束 | 设计理由 |
|---|---|---|---|
| `vdl_version` | ✓ | const `"2.0"` | 与 v1 `schema_version` 同位不同值：v1 引擎读 shot 时 fail-fast 拒收 2.0（shot.schema.json:13「不匹配则模块必须拒收」），天然防止 v2 文档误入冻结管线 |
| `work_id` | ✓ | `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$` | 集/作品 ID，QCReport v2 与 manifest 回链键 |
| `default_prompt_mode` | ✓ | enum `compiled/handwritten/hybrid` | 单一事实源裁定（§3.2）；默认 hybrid 兼容现有手写 prompt 工作流 |
| `intents[]` | ✓ | VPO L2 意图实例（内嵌或 `$file:` 路径引用） | 语义源；VPO schema 原样校验（闸门 B） |
| `shots[]` | ✓ | VDL Shot v2（§3） | 执行计划 |
| `deliverable` | ✗ | DeliverableSet 意图实例（包级唯一） | 交付合同（pixel_map/encode_contract/readability/optical，deliverable-set.schema.json），包级一份而非每镜重复 |
| `post_ops[]` | ✗ | PostProcessIntent 实例 | 确定性后处理一等意图（CONTROL-MAPPING §二.3 :36-38）：字幕烧录/转码/有序合并/GOP 裁剪——全部落本机 ffmpeg 确定性链（工程方案v3 §5.1 合成层字节级承诺 :158） |
| `acceptance[]` | ✗ | AcceptanceSpec 实例数组（L4 原样） | 执行前冻结验收判据；shot 经 `acceptance_refs` 引用 |
| `budget` | ✗ | `{credit_cap_total, wallet_check_uri_note}` | 积分硬上限继承（工程方案v3 §8 积分红线 :252）；执行器双拦截 exit 3 已实测（SPEC.md §2.2） |

---

## 3. VDL Shot v2 字段设计（核心）

### 3.1 与 v1 的关系：纯超集，零废弃

v1 全部 14 个字段（schema_version/shot_id/axis/duration_s/aspect/resolution/prompt/negative_prompt/seed/characters/camera/audio/engine_hint/notes）**语义不变、全部保留**。`schema_version` 由 const `"1.0"` 改 const `"2.0"`（这是唯一值变更，效果=v1 引擎拒收 v2 文档，保护冻结契约）。

### 3.2 新增字段逐条（含理由）

| # | 新增字段 | 约束 | 理由（为何 VDL 承载、为何这样设计） |
|---|---|---|---|
| 1 | `intent_refs[]` | string[]，每项必须解析到包内 `intents[].identity.intent_id` | 语义源链接。VPO 刻意不存引擎意图（CONTROL-MAPPING.md:70-76），VDL 用引用而非复制，意图修订（identity.version 升位）自动生效且可追溯 |
| 2 | `prompt_mode` | enum `compiled/handwritten/hybrid`（缺省继承包级） | **单一事实源裁定**：VPO D0 明示「四者混写一句 prompt，模型按训练先验重新加权」（:681）是失控源。compiled=编译器①从 intents 生成 prompt（禁手写）；handwritten=维持现状（intents 仅登记，编译器只做冲突登记不拦截）；hybrid=手写底稿+意图补丁。三态使两种工作流显式共存，避免隐性双源。词形对齐 IntentCommon `reference_context.prompt_mode`（intent-common.schema.json:162-164）但不复用其值域（那边是 new/reference_based/source_edit，语义是 prompt 边界模式不是作者归属） |
| 3 | `prompt_compiled` + `prompt_hash` | string + `^[0-9a-f]{64}$` | 编译产物与其指纹。留痕体例借鉴 VPO L3 `prompt_hash/prompt_ref`（CONTROL-MAPPING §24 G3 :248：「记录执行结果，不引入包内 prompt」）；`prompt_hash` 进投影后 v1 shot 的 notes 与 manifest provenance，使「同 prompt」可机判——这是 API 层缓存键与 best-of-N 统计（工程方案v3 §5.3-3 :170）的指纹基础 |
| 4 | `engine.channel` + `engine.fallback[]` + `engine.route_rule` | channel enum `local_ltx/local_wan/api_h3max/api_h3`（开放扩展） | v1 `engine_hint.preferred` 只有 api/local 二值，粗于实测分工表。channel 直接取工程方案v3 §2.1/§2.3 定稿：LTX 本地草稿主力（76.7s/条 0 积分 42/42 全成）、Wan 存档、H3-Max 终稿默认（33.4s/条 同价 4 倍速 4/4 判净）、H3 备胎。`route_rule` 引用九轴分工行（如 `G5_multi_identity`→必须 api，G5 本地 LTX 无 I2V 权重已实锤 :56）。`fallback` 显式声明降级链，降级发生时写 errors |
| 5 | `continuity`（连续性观测声明） | 对象，见 §3.3 | D3 长镜头拆分九条硬约束（VPO开发指令书 :713-723）+ 本方确定性实测的可执行化；**观测声明而非生成指令**（见 §3.3 理由） |
| 6 | `cache.strategy` + `cache.fingerprint_includes[]` | strategy enum `content_fingerprint/submit_params/none` | 工程方案v3 §5.3 实测修订：本地层内容指纹→像素级命中（同种子字节级复现，§5.1）；**API 层同指纹重提交必然新样本，缓存键只能命中「提交参数」层**（§5.3-2 :169）。策略值即两条实测结论的机读化，声明错层（api 镜头填 content_fingerprint）为校验错误 |
| 7 | `edit_ops[]` | `[{op, params?}]`，op 词表 `reseed/reprompt/trim/extend/merge_ordered/subtitle_burn/color_grade`（开放词表，首版） | 修订语义一等化。**API 层 reseed 退化为「强制重生成」**（工程方案v3 §5.3-2 :169——seed 零控制力，改种子=新样本）；本地层 reseed 是 0 积分探索（§5.3-3）。op 词表对齐 postprocess_op 思想但独立维护（那 24 值面向交付形态，这 7 值面向修订动作） |
| 8 | `acceptance_refs[]` | string[]（criterion_id），必须解析到包内 `acceptance[].criterion_id` | 验收绑定：每个镜头显式声明「执行前已冻结哪些判据」。与 L4 `intent_path` 双向锚定（spec 指向意图字段，shot 指向 spec） |
| 9 | `budget.credit_cap_per_shot` + `budget.max_retries` | integer | 单镜预算与重试上限（工程方案v3 §6.4 迭代循环：同镜修订 ≤2 轮仍不过→人工工单 :206）；API 每条 280 积分实测（§4.1 :125），预算守卫已在 gen_api 实测（exit 3，SPEC §2.2） |
| 10 | `engine_hint` | 保留（deprecated-for-v2） | 兼容位：投影器②从 `engine.channel` 自动生成写入投影产物；v2 手写文档中该字段出现即校验警告（避免双源） |

### 3.3 `continuity` 段设计（连续性观测声明）

```yaml
continuity:
  link: prev_tail_frame            # none | first_frame_condition | prev_tail_frame
  seed_policy: none                # fix_for_iteration | vary | none
  lock_restatement: [characters, camera_movement]   # D3-5：锁定项每段重申
  d3_split_declared: false         # >6s 或超单段上限时必须 true
  tail_source: real_rendered       # real_rendered | planned
```

- **为什么是 VDL 自有轻量段而不是搬 VPO continuity-intent**：评估结论首批九意图不含 continuity；其语义重心（状态要求/走位轴线/剧情钩子）属叙事层，短剧线当前由剧本管理。但 D3 的九条硬约束是**执行侧**纪律，且本方实测直接对应：D3-3「下一段生成条件=上段真实尾帧（非计划尾帧）」（:716）→ `tail_source: real_rendered`；D3-9「seed 不作连续性钥匙」（:722）+ API seed 零控制力实测 → `seed_policy` 在 api 通道**强制 `none|vary`，`fix_for_iteration` 仅本地通道合法**（校验规则）；D3-1「单段只承载一个意图峰值」→ 长镜拆分声明 `d3_split_declared`。后续若升格引入 continuity-intent，`intent_refs` 挂载即可，v2 结构零改动。
- `seed_policy` 词族名取自 VPO L3 `generation_params.seed_policy`（CONTROL-MAPPING §二.2 :32「fix_for_iteration|vary|none；跨镜锁角色仍非法」）——**借词表不搬结构**，且按本方实测加了通道约束（VPO 未承载的实测差异）。

### 3.4 校验规则（v2 新增，全部可机判）

| 规则 | 内容 | 依据 |
|---|---|---|
| R1 | `intent_refs`/`acceptance_refs` 悬空引用 → 拒收 | 借鉴 VPO 编译器 requirements_incomplete 防线（CONTROL-MAPPING §二.6 :54） |
| R2 | `engine.channel` 以 `api_` 开头时：`continuity.seed_policy=fix_for_iteration` → 拒收；`cache.strategy=content_fingerprint` → 拒收 | 工程方案v3 §5.1/§5.3 实测（API seed 零控制力、缓存只命中提交层） |
| R3 | `duration_s > 6` 且 `d3_split_declared=false` → 警告；> 引擎单段上限（H3 4-15s，shot.schema.json:28）→ 拒收 | D3 衰减规律（:713）+ H3 实测边界 |
| R4 | `prompt_mode=compiled` 时手写 `prompt`（v1 字段）非空 → 拒收 | 单一事实源（§3.2 #2） |
| R5 | `resolution` 与引擎能力不符 → 记 `capability_mismatch` 按请求方降级策略执行（沿 v1 语义，shot.schema.json:40） | v1 已实测 |
| R6 | 意图实例含模型名（闸门 B 的 not-pattern）→ 拒收 | intent-common.schema.json:170-179，本会话实测拒 "Wan2.1"（§8） |

---

## 4. VPO Intent → VDL Shot 段 → executor contract 映射表（首批九意图 × G1-G9）

> executor contract = vpipe 引擎落点：gen_api 的 DTO 白名单（顶层仅 `backend/model_id/prompt/filename/image_paths/params/source_tool`，SPEC.md §2.2 :109-111）与 gen_local 的 diffusers 参数（SPEC.md §2.1）。通道词 = control_channel 五值（registry.jsonl:631-635）。

| VPO Intent（首批） | 关键字段（schema 实读出处） | VDL v2 Shot 段 | executor contract 落点 | G 轴覆盖 |
|---|---|---|---|---|
| **CameraIntent** | shot_scale/subject_frame_ratio/camera_angle/movement/movement_direction/movement_speed/framing_anchor（camera-intent.schema.json:28-81）；hand_object_contact（:128-155）；orbit/whip_pan 缺 movement_direction 即拒（:196-199 编译防线，CONTROL-MAPPING §36 G1 :343） | `intent_refs` + v1 `camera{movement,description}`（标签编译进 prompt 镜头语言段） | **text 通道**→prompt 拼接（gen_api 顶层 prompt）；`hand_object_contact` 同时是 **QC 路由旗**：命中即 J1 手部专项 + MediaPipe 补位（J1 漏 2/5 实测，工程方案v3 §2.2 :70） | **G1**（手部约束）、**G6**（运镜。注意实测「语义非精确：环绕 180° 被渲成画面滚转」§2.1 G6 行——movement_direction 声明 + L4 flag 级验收兜底） |
| **PerformanceIntent** | beats[{anchor, window_ms, unit=ms, emotion_label(gate=human 必真), token_index/vo_token, emotion, action_units}]（performance-intent.schema.json:21-102） | `intent_refs`；台词节拍登记于 v1 `audio.speech`（v1 本就只登记不执行，SPEC §7 :244） | 暂无可执行通道（TTS 管线未建，v3 S3 计划 :186）；emotion 验收走 **L4 human gate**——与 VPO E6「beat.verify 自带人工签核」同构，且与本方「表演情绪属人工灰区」定稿一致（工程方案v3 §3 人工抽检行 :95） | **G4**（单镜事件顺序，D1 只承诺两步 A→B 按粗 :697）、**G9**（表演节拍） |
| **LimitedMotionIntent** | animatable_parts/frozen_parts/blink/breath/lips(set 三枚举)/motion_energy/behaviors；lips.max_error_frames const 3（schema 摘要，本会话实读） | `intent_refs` | **text 通道**prompt 化 + API 原生音轨；口型验收 lips 词表 → 时序类属 **QC 已知残余盲区**（三 VLM 全漏定格实测，工程方案v3 §3.4 :113-115）→ 显式降为人工抽检项，QC 报告时序结论不作自动放行依据（红线继承） | **G9**（数字人微动作） |
| **AudioIntent** | atmosphere/cues/loudness(target_lufs+R128 const)/dialogue_class 五分类/voice_identity_ref/music{tempo…}/audio_approach（schema 摘要，本会话实读） | `intent_refs` + v1 `audio`（generate/speech/music/sfx）升为可执行引用 | **api_param 通道**：`params.generate_audio`（字符串布尔，H3 原生出声实测，shot.schema.json:107）；TTS/配音走 v3 S3 `tts.py`（eval-first：同输入两遍 md5 一致再实现，:186） | **G9**（含音轨数字人） |
| **TextOverlayIntent** | kind/safe_area/min_font_height_pct/contrast_ratio_min const 4.5/standard const WCAG/diegetic{verbatim,surface,readability_note}/typography{render_owner…}（schema 摘要，本会话实读） | `intent_refs` + **绕行路由**：小字 → `post_ops.subtitle_burn` 程序渲染字牌 | **post_comp 通道**：render_owner=post（后期烧字）落本机 ffmpeg 确定性链（工程方案v3 §2.3 绕行定稿 :79「小字→程序渲染字牌」；G2 实测小字/密集必乱 §2.1 G2 行 :53）；diegetic.verbatim 逐字受控 | **G2**（画面内文字） |
| **TransitionIntent** | transition_type/incoming_shot_ref/outgoing_shot_ref/boundary_constraints{outgoing_tail,incoming_head,state_assertion}/sound_lead_in_frames（transition-intent.schema.json:20-61） | `shots[].continuity`（link/tail_source）+ 镜间接缝声明 | **image 通道**：上镜**真实渲染尾帧**作 i2v 首帧条件（D3-3 非计划尾帧）；本地 LTX-i2v 分支（v3 S2 :185，今晚脚本可移植）或 API 首帧条件；sound_lead_in_frames → post_ops 合并时音频先入（D3-8 声音先入引导 :721） | **G6/G7**（镜间衔接、身份跨镜延续） |
| **LoopIntent** | mode/seam_grade/first_last_match_tolerance{motion_px,luma_pct,allowed_dissolve_frames}/gop_policy const closed_idr_start/frame_rate_mode const cfr/tail_trim_policy（loop-intent.schema.json:20-94） | 包级 `post_ops` | **post_comp 通道**：ffmpeg 确定性转码 CFR+GOP 对齐+尾帧裁剪——合成层字节级复现实测成立（工程方案v3 §5.1 :158）；首尾帧匹配容差由 ffprobe/帧差脚本实算（J1 禁口算红线，judge 基准 §10.1） | 交付形态（循环物料） |
| **DeliverableSet** | display_target{venue_class,viewing_distance_m,motion_of_audience,ambient_class}/pixel_map{native_w×h,aspect_class,scale_policy}/encode_contract{container,codec,fps,max_bitrate,audio_policy,duration_exact_frames}/readability/optical（schema 摘要，本会话实读） | 包级 `deliverable`（一份） | **api_param 通道**：params.resolution/aspect_ratio（gen_api 映射已实测）；`duration_exact_frames` 与 report.py 对账（metadata↔manifest sha256 逐条核，v3 S5 :187）；本地只 480P 的能力边界照 v1 契约降级语义（shot.schema.json:40） | 交付合同（全部轴） |
| **PostProcessIntent** | ops[]（24 值词族：trim/transcode/mute/overlay/subtitle_burn/merge_ordered/upscale/…）/input_refs 有序/output_kind/subtitle_constraints{max_chars_per_line_cjk,break_policy,safe_*,anchor,max_lines_per_cue,outline}（postprocess-intent.schema.json:22-205） | 包级 `post_ops` | **post_comp 通道**：确定性 ffmpeg 链；op 参数强制 value+unit+measurement_basis 三数字体例（:39-78 裸数结构拒绝——与本方「精确计数绕行分镜改述」互补，**G3 精确计数的登记位+QC 拣选通道**：多采样后人工/规则拣选，工程方案v3 §2.3 :79） | **G2/G3 绕行**、交付（有序合并/裁剪） |

**G 轴覆盖核对（逐轴，不谎报）**：G1=CameraIntent.hand_object_contact+QC 专项；G2=TextOverlay+post_comp 绕行；G3=**无专意图字段**——九意图中不存在计数意图，按评估结论「九意图覆盖 G1-G9 全轴」的理解路径：空间关系由 CameraIntent.framing_anchor/custom_box + text 通道承载，精确计数走 D0「文本控语义」粗档 + PostProcessIntent 登记位 + 多采样 QC 拣选（§2.3 实测定稿）；G4=PerformanceIntent 事件节拍（两步按粗）；G5/G7=v1 `characters[].ref_image`（**image 通道**，API 双参考图 4/4 入 C 类干净对照实测，工程方案v3 §8.1 :58）+ `field_channels` 标注（intent-common :226-237）；G6=CameraIntent.movement 系；G8=**无专意图字段**（style-intent 未入首批）——风格词走 text 通道（D0 语义），`prompt_mode=handwritten|hybrid` 承载，待需求实证后升格挂 style-intent（§9）；G9=LimitedMotion+AudioIntent。

---

## 5. 完整 YAML 示例（短剧线 ep01 两镜：G6 推镜 + G1 手部特写 + G2 字幕绕行 + 转场）

> 示例中两个 VPO 意图实例与两个 L4 实例均为**本会话过 VPO 原版 schema 校验 0 错误的实例**改写（§8 实测记录）；`intent_id` 等占位值以 `…` 示意。

```yaml
# ============ VDL v2 包：shortdrama_ep01 ============
vdl_version: "2.0"
work_id: shortdrama_ep01
created: "2026-09-30T00:00:00Z"
default_prompt_mode: hybrid          # 兼容现有手写 prompt 工作流
budget:
  credit_cap_total: 560              # 两镜 API 预算（280 积分/条实测，工程方案v3 §4.1）

# ---- VPO L2 意图（闸门 B 按 intent_type 分派 VPO 原版 schema 校验）----
intents:
  - $file: intents/i-cam-0042.json   # CameraIntent：外置文件亦可，内嵌亦可
  - identity:
      intent_id: i-cam-0043
      version: "1.0.0"
    intent_type: vpo:craft.intent_object.camera_intent
    target: { kind: shot, ref: shot_ep01_0043 }
    scope: { level: vpo:delivery.scope.shot, ref: shot_ep01_0043 }
    temporal_extent: { time_base: { rate_num: 24, rate_den: 1 }, start_frame: 0, end_frame: 120 }
    reference_context: { prompt_mode: vpo:delivery.prompt_mode.new }
    predicate: "双手交叠持杯特写，杯面不遮挡手指"
    value: "手部特写镜头"
    strength: vpo:delivery.strength.must
    tolerance: { evidence_status: vpo:delivery.evidence_status.prior }
    exceptions: []
    acceptance_ref: "acc-hand-ep01-0043:v1.0.0"     # 指向 L4 AcceptanceSpec（VPO 侧回链）
    authority: director
    control_channel: [vpo:delivery.control_channel.text]
    field_channels:                                  # G5 字段级通道标注（intent-common:226-237）
      "characters[0].ref_image": [vpo:delivery.control_channel.image]
      "duration_s": [vpo:delivery.control_channel.api_param]
    shot_scale: vpo:cine.shot_scale_coarse.close
    subject_frame_ratio: vpo:cine.subject_frame_ratio.50pct
    camera_angle: vpo:cine.angle_coarse.eye_level
    movement: vpo:cine.movement_primary.static
    movement_speed: vpo:cine.movement_speed.slow
    framing_anchor: vpo:cine.framing_anchor.center
    hand_object_contact:                             # G1 轴承载：手部约束 → QC 路由旗
      constraint: "五指可见，持杯不穿模"
      held_object_ref: prop_cup_01
      tolerance: { evidence_status: vpo:delivery.evidence_status.prior }

  - identity: { intent_id: i-pp-ep01-sub, version: "1.0.0" }
    intent_type: vpo:craft.intent_object.postprocess_intent
    target: { kind: shot, ref: shot_ep01_0042 }
    scope: { level: vpo:delivery.scope.shot, ref: shot_ep01_0042 }
    temporal_extent: { time_base: { rate_num: 24, rate_den: 1 } }
    reference_context: {}
    predicate: "片名小字确定性烧录，逐字受控"
    value: "程序渲染字牌替换生成侧小字"
    strength: vpo:delivery.strength.must
    tolerance: { evidence_status: vpo:delivery.evidence_status.prior }
    exceptions: []
    acceptance_ref: "acc-sub-ep01-0042:v1.0.0"
    authority: director
    control_channel: [vpo:delivery.control_channel.post_comp]   # G2 实测：小字必乱→后期通道
    ops:
      - op: vpo:delivery.postprocess_op.subtitle_burn
        params:
          max_chars_per_line_cjk: { value: 10, unit: chars, measurement_basis: "deliverable 1080x1920" }
    input_refs: ["clip:shot_ep01_0042@MiniMax-H3-Max"]
    output_kind: vpo:delivery.deliverable_kind.master

# ---- 执行计划 ----
shots:
  - schema_version: "2.0"
    shot_id: shot_ep01_0042
    # ---- v1 继承字段（语义与 shot.schema.json v1.0 一致）----
    axis: G6
    duration_s: 5
    aspect: "9:16"
    resolution: 768P
    seed: 42
    characters:
      - char_id: heroine_a
        desc: "红衣女子，齐肩发"
        ref_image: "assets/heroine_a_portrait.png"   # G5/G7：image 通道身份锚（API 双参考实测）
    camera: { movement: push_in, description: "缓慢推进到面部" }
    audio: { generate: true, speech: "你终于回来了。", music: "" }
    # ---- v2 新增 ----
    intent_refs: [i-cam-0042]
    prompt_mode: compiled
    prompt_compiled: "（编译器①产物：镜头语言段+主体段+场景段）"
    prompt_hash: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    engine:
      channel: api_h3max               # 终稿档（v3 §2.3 定稿管线）
      fallback: [api_h3, local_ltx]
      route_rule: G6_camera_semantic   # v3 §2.1 G6 行
    continuity:
      link: none                       # 首镜
      seed_policy: none                # R2：api 通道禁 fix_for_iteration
      lock_restatement: [characters]
      d3_split_declared: false
      tail_source: real_rendered
    cache:
      strategy: submit_params          # R2：API 层只命中提交参数层（v3 §5.3-2）
      fingerprint_includes: [prompt_hash, duration_s, aspect, resolution, ref_shas]
    edit_ops: []
    acceptance_refs: [acc-cam-ep01-0042, acc-sub-ep01-0042]
    budget: { credit_cap_per_shot: 280, max_retries: 2 }

  - schema_version: "2.0"
    shot_id: shot_ep01_0043
    axis: G1
    duration_s: 5
    aspect: "9:16"
    resolution: 768P
    seed: 42
    characters:
      - { char_id: heroine_a, desc: "红衣女子，齐肩发", ref_image: "assets/heroine_a_portrait.png" }
    camera: { movement: static, description: "双手持杯特写" }
    audio: { generate: true, speech: "", music: "" }
    intent_refs: [i-cam-0043]
    prompt_mode: handwritten          # 现状工作流：intents 仅登记，编译器只登记冲突
    engine: { channel: api_h3max, fallback: [local_ltx], route_rule: G1_hand_qc_routed }
    continuity:                       # 连续性观测声明（§3.3）
      link: prev_tail_frame           # 转场：上镜尾帧作首帧条件（TransitionIntent 语义）
      seed_policy: vary
      lock_restatement: [characters, camera_movement]   # D3-5 锁定项重申
      d3_split_declared: false
      tail_source: real_rendered      # D3-3：真实尾帧，非计划尾帧
    cache: { strategy: submit_params, fingerprint_includes: [prompt_hash, duration_s, aspect, resolution, ref_shas] }
    edit_ops: []
    acceptance_refs: [acc-hand-ep01-0043]
    budget: { credit_cap_per_shot: 280, max_retries: 2 }

# ---- 包级确定性后处理（post_comp 通道）----
post_ops:
  - identity: { intent_id: i-pp-ep01-sub, version: "1.0.0" }   # 即上方 PostProcessIntent，此处标注其执行顺序位
    run_after: [shot_ep01_0042]

# ---- L4 验收层：执行前冻结（AcceptanceSpec 原样采用）----
acceptance:
  - schema: "https://vpo.example/schemas/v1/l4/acceptance-spec.schema.json"
    criterion_id: acc-cam-ep01-0042
    version: "1.0.0"
    intent_path: "i-cam-0042.movement"          # 指向 L2 意图字段（L4 schema :35-39）
    metric: "movement_direction_present"        # 编译期防线+成片目检双通道
    tolerance: { evidence_status: vpo:delivery.evidence_status.prior, notes: "G6 实测语义非精确，flag 级验收" }
    gate: vpo:delivery.gate.flag                # ↔ vpipe manual_review（§7.3 映射表）
    detector_id: J1_glm8
    detector_version: "vpipe1.0"
  - schema: "https://vpo.example/schemas/v1/l4/acceptance-spec.schema.json"
    criterion_id: acc-hand-ep01-0043
    version: "1.0.0"
    intent_path: "i-cam-0043.hand_object_contact"
    metric: "hand_anomaly_detected"
    tolerance: { evidence_status: vpo:delivery.evidence_status.prior }
    gate: vpo:delivery.gate.block               # P0：B 类手部缺陷打回（J1 命中即回）
    detector_id: J1_glm8
    detector_version: "vpipe1.0"
  - schema: "https://vpo.example/schemas/v1/l4/acceptance-spec.schema.json"
    criterion_id: acc-sub-ep01-0042
    version: "1.0.0"
    intent_path: "i-pp-ep01-sub.ops[0]"
    metric: "subtitle_verbatim_match"
    tolerance: { evidence_status: vpo:delivery.evidence_status.prior }
    gate: vpo:delivery.gate.block               # 确定性烧录：逐字不符即拒（可仪表验收）
    detector_id: J6_detectors
    detector_version: "vpipe1.0"
```

---

## 6. 与现 v1 字段对照表

### 6.1 Shot 契约（shot.schema.json v1.0 → shot_v2 2.0）

| v1 字段 | v2 处置 | 说明 |
|---|---|---|
| `schema_version` | **值变更** const 1.0→2.0 | 唯一值变更；v1 引擎对 2.0 fail-fast 拒收（shot.schema.json:13），即冻结保护本身 |
| `shot_id` `axis` `duration_s` `aspect` `resolution` `prompt` `negative_prompt` `seed` `characters` `camera` `audio` `notes` | **不变** | 全部保留原语义；`axis` 保留（溯源双写：可由 intent_refs 推导，登记值优先） |
| `engine_hint` | **deprecated-for-v2** | 保留兼容位；投影器②从 `engine.channel` 自动生成；v2 手写文档中出现即校验警告（防双源） |
| （新增）`intent_refs` `prompt_mode` `prompt_compiled` `prompt_hash` `engine` `continuity` `cache` `edit_ops` `acceptance_refs` `budget` | **新增** | 逐条理由见 §3.2 |

**废弃字段：无**（v2 为纯超集；`prompt` 的语义变化——手写输入 → 可编译产物——由 `prompt_mode` 显式声明，不删除字段、不破坏 v1 字段存在性）。

### 6.2 QCReport 契约（qc_report.schema.json v1.0 → qc_report_v2 2.0）

| v1 段 | v2 处置 |
|---|---|
| `schema_version/clip_id/generated_at/qc_mode/verdict/defects/scores/spans/judges/inputs/errors` | **全不变**。`verdict.defect_detected` 仍是 eval_run 唯一检出口径（qc_report.schema.json:38），eval 兼容零成本 |
| （新增）`work_id` | 可选；v2 包回链键 |
| （新增）`acceptance[]` | 可选数组：`{criterion_ref{id,version}, status, gate_result, evaluator_id, evaluator_version, confidence, evidence_refs[]}` —— AcceptanceRecord 的挂接视图，完整记录独立落盘（§7.3） |

### 6.3 AssetManifest 契约

| v1 | v2 处置 |
|---|---|
| 全部不变 | **新增 kind 枚举值**：`acceptance_record`（L4 执行后记录）、`vdl_package`（VDL 文档自身登记，sha256 身份）——其余 8 种 kind 原样 |

---

## 7. 契约迁移说明

### 7.1 新增/变更文件清单（v1 文件一律不动）

| 文件 | 状态 | 内容 |
|---|---|---|
| `vpipe/contracts/shot.schema.json` 等 v1 三份 | **冻结不动** | vpipe 重生成规程（SPEC §6）照旧；eval 基线（§4 验收记录）不重定 |
| `vpipe/contracts/v2/vdl_package.schema.json` | 新增 draft-07 | §2.2 包级结构 + §3.4 校验规则 R1/R4 的 structural 部分 |
| `vpipe/contracts/v2/shot_v2.schema.json` | 新增 draft-07 | v1 超集 + §3.2 新增字段（R2/R3 规则写在 description 与编译器，schema 层表达 R2 需 if/then 组合，draft-07 可表达） |
| `vpipe/contracts/v2/qc_report_v2.schema.json` | 新增 draft-07 | v1 超集 + work_id + acceptance 段 |
| `vpipe/contracts/v2/asset_manifest_v2.schema.json` | 新增 draft-07 | kind 枚举 +2 |
| VPO 侧 | **零改动** | video-Ontology 红线（只读、禁 push）；v2 经 registry 引用其 `$id`，不复制任何 VPO schema 文本进 vpipe |

### 7.2 双版本共存与隔离

- v1 引擎（gen_local/gen_api/qc_orch）**不需要任何修改**：它们只见过投影产物（v1 shot JSON，schema_version=1.0）与 v1 QCReport。
- v2 的一切新概念（intents/acceptance/engine/continuity/cache/edit_ops）都止步于**编译器①②与验收记录器**——三个新进程，互不 import，只靠契约 JSON 通信（继承 SPEC §0 纪律）。
- 版本判定：文件级（`schema_version` 值）而非目录级，防错放目录。

### 7.3 qc_report 如何挂 acceptance record（裁定与理由）

**裁定：QCReport v2 内嵌「挂接视图」，AcceptanceRecord 完整实例独立落盘并登记 manifest（kind=acceptance_record）。**

1. QCReport v2 新增可选 `acceptance[]`：每项 = `{criterion_ref{id,version}, status, gate_result, evaluator_id, evaluator_version, confidence, evidence_refs[]}`。status 五态原样采用 VPO 词族（pass/fail/unknown/approved_exception/inconclusive，acceptance-record.schema.json:91-94）；`unknown ≠ pass` 由 L4 的 `treated_as`/`gate_result` 陷阱字段机制保障（:122-137，本会话实测 approved_exception 无 reviewer 即拒）。
2. 完整 AcceptanceRecord（含 expected/observed/evidence_refs）独立成文件落盘、sha256 登记 manifest——理由：a) AcceptanceRecord 是跨执行的一等审计资产（生命周期长于单次 QC）；b) v1 eval_run 只读 verdict/defects/scores，新增可选字段零影响（契约向后兼容，SPEC §6.4 回归条款自动满足）；c) 与 asset_manifest 以 sha256 为身份的既有机制一致。
3. **gate ↔ vpipe 处置映射**（验收门类型 → 判定路径，依据两侧实测）：

| L4 gate | vpipe decision 映射 | 实测依据 |
|---|---|---|
| `block`（P0，假阳性代价<漏检代价） | `auto_reject` | J3 单通道 P≥0.90 区间 8/8 全对（thresholds.yaml auto_reject_p；judge 基准 §5） |
| `flag`（P1） | `manual_review` | 0.70-0.90 灰区 100% 人工（工程方案v3 §3 表 :90-95） |
| `human`（表演/风格/连贯性/品牌整体感） | 人工工单 | J1 是 B 类唯一有效判官但手部漏 2/5（§2.2 :70）；时序缺陷人工抽检（§3.4 红线） |

   方向澄清：vpipe decision 是对「缺陷检出」的处置，L4 gate 是对「验收判据」的门类型；映射语义 = **该判据 fail 时的处置路径**，不是字段级换算。advisory_benchmark（VBench 等）不进 gate 命名空间（acceptance-spec :87-128）——与本方 J4 弃用教训同构（任意阈 F1≤0.744 无工作点：基准型信号不得作闸门，thresholds.yaml J4 deprecated 行）。

4. evaluator_id 映射：`J1_glm8/J3_omnijev/J6_detectors/J5_videochat3`（vpipe 判官代码）→ L4 `detector_id/detector_version`；版本取 `thresholds.yaml` version + 模块版本，禁止 "latest"（L4 schema :31-33、:50-53 硬约束）。

### 7.4 迁移工具规格（后做，本草案只定规格）

| 工具 | 方向 | 规格 |
|---|---|---|
| 投影器② `vdl_project.py` | vdl_package → N×v1 shot + 投影清单 | ①逐镜生成 v1 shot JSON（intent_refs→prompt 拼接[compiled]或原样[handwritten]；engine.channel→engine_hint.preferred+model；其余 v1 字段直拷）；②输出投影清单（shot_id→intent 版本/prompt_hash/验收引用），供对账；③R1-R6 校验前置 |
| 反向骨架器 `vdl_scaffold.py` | v1 shot → v2 包骨架 | prompt_mode=handwritten、intents=[]、acceptance=[]；存量金标/矩阵文档可无痛升格登记 |
| 验收记录器 `acceptance_recorder.py` | QCReport(v1/v2) + acceptance[] → AcceptanceRecord 文件 | evaluator 映射表（§7.3-4）；unknown 传递不吞；落盘即登记 manifest |
| 两段校验器 `validate_vdl.py` | v2 包 → 闸门A+B | 本会话已验证可行性脚本（§8）；正式版随迁移工具固化 |

迁移顺序：v2 契约文件与校验器 → 投影器 → 试点 1 集（走 §6.4 迭代循环）→ 反向骨架器扫存量。

---

## 8. 可编译性验证记录（本会话实跑，非转抄）

环境：本机 Python + jsonschema 4.26.0 + referencing（一次性 heredoc 脚本，未落盘为正式工具——正式版随 §7.4 迁移工具固化）。

| # | 检查 | 命令要点 | 结果 |
|---|---|---|---|
| V1 | VPO schema 全量编译 | `Draft202012Validator.check_schema` + registry（`$id`→本地文件映射）对 `schemas/l2/*.json`(19) + l4 两份 + intent-common + tolerance | **23/23 编译 OK** |
| V2 | CameraIntent 合法实例 | 十二元组+control_channel+九意图字段的完整实例 | **0 errors** |
| V3 | not-pattern 负例 | 同实例 `predicate` 改含 "Wan2.1" | **被拒**（intent-common:170-179 生效） |
| V4 | absence 四态 | 删 `value`、填 `absence: vpo:delivery.absence.explicitly_unconstrained` | **0 errors**（value/absence 二选一生效） |
| V5 | PostProcessIntent 实例 | subtitle_burn op + 三数字体例 params | **0 errors** |
| V6 | L4 两实例 | AcceptanceSpec（gate=flag, detector_id=J1_glm8）+ AcceptanceRecord（pass, confidence） | **各 0 errors** |
| V7 | L4 防线负例 | status=approved_exception 而无 reviewer_or_approval_ref | **被拒**（if/then 生效） |

结论：**评估结论的采纳面（L2 公共底座 + 九意图 + L4 双 schema）在本机可直接编译、可校验、防线可机判**——「直接采用」具备工程可执行性，非纸面结论。

---

## 9. 不采纳与暂缓清单（「别硬塞」条款的正面清单）

| 项 | 裁定 | 理由 |
|---|---|---|
| VPO L1 五轴（creative-work/narrative/editorial/production/asset-axis 等 6 schema） | 不搬 | 工作级叙事结构；短剧线由剧本+包级 work_id 承载；引入即要求全套 package 校验器，收益当前不可见 |
| VPO L3 executor-contract/work_items/capability-profile/forbidden-actions | **不搬结构，借纪律** | 与 VDL 定位重叠且绑定其编译器防线体系（requirements_incomplete/conflict_detected 全家）。借鉴四点：三数字体例（tolerance :42-51）、seed_policy 词族与「跨镜锁角色仍非法」、prompt_hash/prompt_ref 留痕（§24 G3 :248）、负面词≤5/时长超限等可机判防线思想（§二.6） |
| VPO L5 provenance 序列化（json/turtle 三表示） | 不搬 | v1 asset_manifest.provenance 位已实测承载（asset_manifest.schema.json:65-81；build_metadata 模式） |
| 其余 10 个 L2 意图（brand-kit/character-bible/color/continuity/lighting/media-integration/motion-graphics/panel-presentation/scene-environment/style） | 暂缓（结构上零成本升格） | 评估结论首批指名九个。G5/G7 身份一致性已由 v1 characters[].ref_image 实测承载（API 双参考 4/4 入 C 类，工程方案v3 §8.1）；G8 风格化走 text 通道。升格路径：`intents[]` 直接挂载新意图实例即可，v2 结构无需改动 |
| VPO 的 vendor 能力档案（profiles/capabilities，如 minimax-h3-video 卡） | 暂缓 | 有真实价值（H3 4-15s/768P·2K/首帧必需等与实测吻合），但其 wilson=0/reliable=false 先验口径（CE-27 G4）与本项目已有实跑台账重叠；等 v2 试点后决定是否映射为 `engine.route_rule` 的规则源 |
| 编译器①的意图-prompt 冲突拦截 | 第一版只登记不拦截 | conflict 词表先验不足（VPO 用 26 轮词族积累才做到机判）；hybrid 模式下冲突写 errors/notes，人工处置 |

---

## 10. 开放问题（如实记录）

1. **评估结论截断处**：原文「D:\workspace\video-Ontology\sc…」被截断，所指文件未确证；本草案 L4 采纳以实际读取的 `acceptance-spec/acceptance-record.schema.json` 为准，截断内容未采用。
2. **G3/G8 的九轴覆盖**：评估结论称九意图覆盖 G1-G9 全轴；G3（计数）与 G8（风格）在九意图中无专字段，本草案按 D0 通道论 + 绕行策略如实标注承载路径（§4 末段），不做字段硬塞。若后续判断需专字段，升格引入 scene-environment/style-intent 走 §9 暂缓通道。
3. **prompt_mode=hybrid 的冲突登记规则**需编译器①实现时定稿（含最小冲突示例集）。
4. **detector_id↔J1-J7 映射表**的固化依赖 J6 五条规则修复与 J7 金标补跑（工程方案v3 §7 P0-1/P0-2）完成后的席次定稿。
5. 本草案为设计稿：v2 schema 文件、校验器、投影器均未实现（§7.4 迁移顺序），不构成本轮可执行交付。

---

## 附：本草案引用文件一览（全部本会话实读）

- 本项目：`overnight/工程方案v3.md`、`边界测试方案.md`（位于仓库根）、`overnight/vpipe/SPEC.md`、`overnight/vpipe/contracts/{shot,qc_report,asset_manifest}.schema.json`、`overnight/vpipe/eval/thresholds.yaml`
- video-Ontology（只读）：`schemas/common/{intent-common,tolerance}.schema.json`、`schemas/l2/` 19 个意图 schema（其中 camera/performance/limited-motion/audio/text-overlay/transition/loop/deliverable-set/postprocess 九个精读，其余摘要）、`schemas/l4/{acceptance-spec,acceptance-record}.schema.json`、`schemas/l3/executor-contract.schema.json`（对照面）、`CONTROL-MAPPING.md`、`VPO开发指令书_v1.1_自包含版.md`（附录 D）、`concepts/registry.jsonl`（absence/control_channel 词族）
