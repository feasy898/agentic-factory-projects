# M6 整集上下文翻译 + 时长预算 spec（三后端抽象）

> 状态：frozen-mock（模块与 eval 冻结；local 主后端 :9004 服务部署冒烟归 T12 批，volta_status pending 如实登记）。
> 对照 `pipeline/mt_backends.py`、`pipeline/m6_translate.py`、`gpu-services/mt/service.py`、
> `docs/mt_service_deps.md` 核验于 2026-09-29。组件中性名：mt-core / mt-api。

## 1. 职责与边界

**做**：①通读全部 C2 → 生成/校订角色卡（**增量合并**进 C3：只新增未见过的 char_id，绝不覆盖既有卡——
C3 权威归人工/M5）+ `06_mt/context.json` 工作纸（cast 摘要/glossary=C3 terms∪别名∪terms_seed/relations
共现占位/高频专名候选仅列出不自动注入）；②逐句 3–5 候选；③音素化估长；④in-budget-first 排序 → C4 出口。
**不做**：不合成（M7）、不对齐时长（M8 换译回路是消费方）、不做术语自动注入。

## 2. 后端抽象（同一 `MTBackend.translate` 接口，mt_backends.py）

| 后端 | 中性名 | 说明 |
|---|---|---|
| `LocalMtBackend` | mt-core | GPU :9004 服务 HTTP 客户端（env `M6_MT_URL` 默认 127.0.0.1:9004）；payload 与服务 pydantic 模型一一对应（`extra=forbid` 防口径漂移）：text/tgt/cast/terms/prev/next/budget/n_candidates → 候选[]+timing+versions；eval 以本地桩 HTTP 服务钉死 payload 契约 |
| `ApiMtBackend` | mt-api | OpenAI 兼容 chat.completions 兜底；env `MT_API_BASE/MT_API_KEY/MT_API_MODEL` **缺一构造即报错**，绝无默认 key，key 不落盘不入库 |
| `MockMtBackend` | mock | 内置离线词典+规则长短变体（同输入恒同输出）；收到的完整上下文存 `last_context` 供 eval 断言角色卡注入；术语一律走 ctx.terms 不入词典 |

- 上下文注入口径（与结构化模板同构）：`[背景信息]`（角色卡摘要）`[术语表（必须采用）]` `[对话前文]` `[原文]`
  `[对话后文]` `[时长预算]`；前文 ≤2 句优先取已定稿译文，后文 ≤2 句取源文（`CTX_WINDOW=2`）。
- 预算窗：`orig = C2.end − start`；`lo/hi = orig × pipeline.yaml budget.lo_ratio/hi_ratio`（0.9/1.1）。

## 3. 音节估算与排序

- `count_syllables`（规则占位 G2P，m6_translate.py:84-105）：zh/yue/ja=CJK 字数；en=每词元音簇 `[aeiouy]+`；
  es=元音数；ar=去叠符后长元音/软音计数。
- `est_dur = syl ÷ 速率`；速率来自 `models/syl2dur.json`（`{"en":{"syl_rate":4.1}}` 或 `{"en":4.1}`），
  缺表回退 `DEFAULT_SYL_RATE`（zh 4.2/en 4.0/es 4.4/ar 3.6，量级正确非最终口径）——**缺表不阻塞主链路**
  （isomt-lora 拟合回填钩子，接口已留）。
- 排序 `in-budget-first`：预算内优先 → q 降序 → |est−orig| 升序；`chosen` 取排序首位
  （无候选落窗时仍取首位，M8 以"全候选出窗"判换译）。
- C4 出口：`(utt_id, tgt)` 复合键 `upsert_jsonl`（en/es 行共存，重跑同语种按 id 替换不碰他语种）。

## 4. eval

```bash
bash scripts/eval_m6.sh   # = pytest tests/test_m6.py -v（mock 后端全离线，零网络零 GPU）
```

10 用例：角色卡注入探针 / 预算窗=C2 时间戳 / 候选 1–5 条 est=syl÷速率 / in-budget-first 排序复算 /
超预算句 100% 判出 / 术语命中 100%（角色名+别名+种子）/ C4 强校验 + CLI validate OK /
复合键 upsert 复跑不重复 / api env 缺失即报错 / local payload 桩服务契约。
规划冻结线（§4 M6，local/api 接通后验收）：50 句术语命中 100%；预算内命中 ≥55%（isomt-lora 后 ≥75%）；
LLM 评分 ≥3.8；超预算句 100% 进 M8 换译。

## 5. 重生成注意事项

- :9004 服务（`gpu-services/mt/`：service.py + run_gpu.sh + gpu/setup_mt_service.sh）：
  fp16+sdpa、无 bf16、单进程推理锁、监听 127.0.0.1:9004、≈5GB 与 :9001 同驻 cuda:0；
  结构化模板与 isomt-lora 训练模板同构（训练对齐用）；权重真名读 GPU 机
  `/data/xdng/etc/model_ids.env` 的 `MT_CORE_ID`（不入公开仓），对照 docs/mt_service_deps.md。
- transformers 版本待 T12 冒烟核实钉版（4.52.x 不兼容则照 venv-asr 的 .pth 复用法另建 venv-mt，
  详见 docs/mt_service_deps.md §2）。
- 纪律：未实测不写 ok——mt-core volta_status 维持 pending 直到冒烟回填。
