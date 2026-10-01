# VDL v2 示例（examples/vdl2/）

四个包覆盖三条业务线 + 一个故意违规负例。全部可用仓库内编译器直接跑：

```bash
# 在 overnight/vpipe/ 下
python src/vdl2/vdl2_validate.py --pkg examples/vdl2/10_shortdrama_ep01.yaml
python src/vdl2/vdl2_compile.py  --pkg examples/vdl2/10_shortdrama_ep01.yaml --out-dir out/vdl2/10
# 测试套件（19 例，含 v1 管线兼容回放）
python -m pytest tests/test_vdl2.py -v
```

| 文件 | 线别 | 要点 | 预期 |
|---|---|---|---|
| `10_shortdrama_ep01.yaml` | 剧集线分镜 | 草案 §5 的可运行版：2 镜（compiled+handwritten 双模式）、CameraIntent×2（外置 `$file` + 内嵌）、TransitionIntent（跨镜引用）、PostProcessIntent（字幕绕行）、3 份 AcceptanceSpec（block/flag 混合）、api_h3max 终稿链 | 校验 PASS；编译出 2 个 v1 shot + 3 个验收骨架 |
| `20_avatar_talk.yaml` | 模板线口播（G9a） | TTS→Vidu avatar 专线（工程方案v3.1 §2.4）：LimitedMotionIntent（口型/眨眼/呼吸全套）+ AudioIntent（R128 响度）+ `template.slots`（台词/形象图/音乐 4 槽）；avatar 专属参数落 v2 执行计划侧（`execution_plan.json` 的 `shots[].avatar`），v1 契约冻结不扩字段 | 校验 PASS（2 条 R3 时长警告属预期）；编译出 2 shot + 3 骨架 + slots.json |
| `30_programmatic_loop.yaml` | 程序化模板 | 商品循环物料：LoopIntent（无缝循环/CFR/闭合 GOP）+ TextOverlayIntent（G2 小字→post_comp 绕行）+ 包级 DeliverableSet（完整交付合同）+ 本地 LTX 0 积分通道（本地合法 `fix_for_iteration` + `content_fingerprint` 与 R2 的 api 禁令对照）+ 4 槽位（含改交付像素的 `master_width`） | 校验 PASS；编译出 1 shot + 2 骨架 + slots.json |
| `99_negative_must_reject.yaml` | 负例（禁止当示例用） | 14 类埋雷：R1 悬空引用×4、跨镜悬空×3、R2×2、R3 超时长、R4 双源、首镜无上镜、闸门A/B 结构违规（含 predicate 写模型名触发 VPO not-pattern） | 校验 **REJECT（exit 1）**、编译器拒收（exit 2） |

`intents/i-cam-0042.json`：外置意图文件（演示 `$file` 引用形态；闸门 B 一样深校验）。

## 产物结构（--out-dir）

```
execution_plan.json        执行计划：每镜 engine/cache/budget/验收引用/意图版本/投影清单；avatar 段（G9a）
shots_v1/<shot_id>.json    v1 ShotSpec（schema_version=1.0）——直接喂 vpipe gen_local / gen_api
acceptance_records/*.json  L4 验收记录骨架：status=unknown（unknown≠pass，不设 treated_as/gate_result）
slots.json                 槽位定义（含 current_value，模板填充后重编译得实例包）
compile_report.json        编译日志：errors/warnings/冲突登记（hybrid 冲突只登记不拦截）
```

## 纪律

- 密钥不入包：预算只写端点语义（`wallet_check_uri_note`），调用方从 `overnight/secrets/api_keys.env` 或环境变量读取。
- VPO schema 只读引用（`D:/workspace/video-Ontology/schemas/`，经 `$id` registry），本目录零复制。
