# 组件注册表与 Volta 降级链 spec（configs/models.yaml 部署矩阵）

> 状态：frozen（字段结构 T1 冻结；条目随批次实测回填）。对照 `configs/models.yaml`（374 行全文）、
> `docs/gpu_asr_align_deps.md`、`docs/tts_service_deps.md` 核验于 2026-09-29。
> 本文件全用中性名；真名对照仅登记于 docs/*_deps.md（依赖安装记录）与内部台账。

## 1. 文件结构（models.yaml）

- `schema_version: 1`。
- `routing`（语种/条件 → 组件链，四个表）：
  - `tts`：en=[dub-tts, dub-tts-base, alt-tts-a, alt-tts-b] / es=[dub-tts, alt-tts-a, alt-tts-b] /
    ar=[dub-tts, alt-tts-b]——**:9002 服务 ROUTING 是本表的冻结镜像**（service.py:72-77，eval 断言逐字一致）。
  - `mt`：en/es/ar = [mt-core, mt-api]。
  - `align`：default=align-core；**ar=align-proportional**（主对齐器不含阿语 → 字符比例内插，MVP 内置）。
  - `separation`：default=audiosplit（cpu 分块）；cuda=audiosplit-cuda（整轨）。
  - `lip`：default=none（不合格原画）；frontal_closeup=lip-fast；top10pct=lip-pro（与 pipeline.yaml lip 段配合）。
- `components`：每条目字段（T1 冻结）：`task / langs / device / precision / attn / weights / version / fallback /
  volta_status` + 可选 `runtime_notes`（实测回填）与 `model`/`chunk_s`/`threads` 等组件特化字段。
- 顶部**部署矩阵**注释（服务→venv→torch→transformers，B1 冻结）：见 §3。

## 2. Volta 总纲（2×V100S-32GB，sm_70）

- 有 fp16；**无 bf16**；无 FA2 系注意力算子——**注意力实现固定 `attn: sdpa`**；
  全部推理不依赖重型服务化运行时（重型推理引擎官方支持线压线且新引擎不保证，**不作为必需依赖**）。
- 每组件 `volta_status`：`pending | ok | degraded | fail`——**纪律：未实测不写 ok**（D1/T3 冒烟回填）。
- gate_b0 ② 断言：每条目含 fallback 字段；四个已冒烟组件（dub-tts / alt-tts-b / lip-fast / asr-core）
  的 volta_status 严格 = "ok"，且 dtype 定案 dub-tts=fp32 / alt-tts-b=fp32 / lip-fast=fp16 / asr-core=fp16。

## 3. 部署矩阵（服务 → venv → torch → transformers）

| 服务/批次 | 解释器 | torch | transformers | 组件 |
|---|---|---|---|---|
| asr_align(:9001, B1/M4) | `/data/xdng/venv-asr` | 2.5.1+cu118（.pth 复用主 venv） | **5.13.0**（原生架构下限） | asr-core, align-core, emo-tag |
| tts(:9002, T12/M7) | `/data/xdng/venv` | 2.5.1+cu118 | 4.52.1 | dub-tts（fp32 常驻 cuda:0）；alt-tts-b 懒加载 cuda:1 |
| mt(:9004, T12/M6) | `/data/xdng/venv` | 2.5.1+cu118 | 4.52.x（T12 核实钉版；不兼容则照 venv-asr .pth 复用法另建 venv-mt） | mt-core |
| 本机 windev（CPU） | `<repo>/.venv` | 2.14.0(cpu) | 无（paddle 组） | cap-ocr, facemesh, cap-clean |

- **两组 transformers（4.52.x 与 5.13）不可共存于同一解释器**——双 venv 的唯一原因。
- 显存：#0 卡 = asr_align 三模型 + dub-tts（7062MiB 实测）+ mt（≈5GB）同驻 32GB；
  **#1 卡 = lip-pro（≈18GB 独占）与 alt-tts-b（≈8GB 懒加载）互斥**——lip-pro 起来时 alt-tts-b 必须退出。

## 4. 降级链总表（fallback 字段；为空 [] = 无降级，失败如实记 FAIL）

| 组件 | fallback 链 | 状态与定案 |
|---|---|---|
| asr-core | [asr-multi-fb]（多语 CPU 兜底，TBD） | asr-core ok（fp16，2026-09-28 冒烟）；asr-multi-fb pending |
| align-core | [align-proportional] | align-core ok（fp16+sdpa，12 字全字级时间戳实测）；align-proportional ok（内置算法无权重） |
| emo-tag | [] | ok（框架默认 fp32 装载，模型小无 fp16 开关；0.1s/句） |
| dub-tts | [dub-tts-base, alt-tts-a, alt-tts-b] | **ok**；fp32 唯一实测档（引擎仅 use_bf16 开关、无 fp16 档；Volta 禁 bf16 → use_bf16=False 定案）；text_normalization=False |
| dub-tts-base | [] | pending（上一代 fp16 仅 zh/en；权重未部署，链上如实 skip） |
| alt-tts-a | [] | pending（en/es ~10 语种无 ar；权重未部署；装载参数经 env 注入） |
| alt-tts-b | [] | **ok**（fp32 默认档；torch>=2.5 SDPA enable_gqa 硬约束 → GPU 机 torch 2.5.1+cu118 定版；cuda:1 与 lip-pro 互斥；单路参考克隆无情绪通道 → emo_ref_used=false 如实回） |
| mt-core | [mt-api] | pending（T12 部署冒烟后回填） |
| mt-api | [] | na（OpenAI 兼容 env 三件注入，key 不落盘） |
| audiosplit / audiosplit-cuda | [] | CPU 路径 T4 已验收（ckpt sha256 前缀登记）；cuda 路径 pending |
| cap-ocr | [] | ok（CPU；3.7.0；mkldnn 关闭 + 0.5 降采样见 m2 spec） |
| cap-clean | [] | pending（重型擦除后端接口预留不安装；M11 生产走 delogo/inpaint 轻量路径） |
| lip-fast | [] | ok（D1：2s/50 帧片段全流程 41s，fp16） |
| lip-pro | [lip-pro-1.5, lip-fast] | pending（18GB 独占 #1） |
| lip-pro-1.5 | [lip-fast] | pending（8GB 降级版） |
| voxdia / shot-cut / facemesh / actspk | [] | ok（全本机 CPU；runtime_notes 记录线程帽/路径坑/自实现架构） |
| audmark / provenance | [] | pending / na（M12 批） |
| align-m8 / mix-m9 | [] | na（纯本地编排，无权重；T14/T15 登记） |

## 5. eval / 自检

```bash
python scripts/gate_b0.py    # ② models.yaml 断言（fallback 全存在 + 四组件 volta ok + dtype 定案）
                             # ③ data/gpu_smoke_report.json 产物可核（artifact 实测或内联 sha256 摘要）
```

- runtime_notes 回填纪律：每批实测结论（耗时/显存/坑）写回条目 `runtime_notes`，与 commit 记录同源；
  **未实测字段维持 pending/TBD，不写 ok**（范例：mt-core version="TBD-T12"）。
- 修改 routing 表必须同步 ：9002 服务 ROUTING 冻结镜像与 eval（两处一致性有测试钉住）。

## 6. 重生成注意事项

- 权重路径 `models/<中性名>/` 为相对缓存约定（不入公开仓；公开版只留占位+校验和，由法务统一处理引用声明）。
- GPU 机模型真名 ID 经 `/data/xdng/etc/model_ids.env` 注入（文件留 GPU 机）——脚本读 env 不拼真名，
  公开文本零真名（运行时经拼接构造动态加载，同 gpu-services 命名纪律）。
- 版本固化位格式：`"<日期> (<快照/commit/sha256 前缀>)"`——重建时按此回填。
