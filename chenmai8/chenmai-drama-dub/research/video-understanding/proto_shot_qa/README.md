# proto_shot_qa —— 短剧镜头 QA 原型（worker-B · 短剧×视频理解）

纯代码关键帧时间轴 → 契约 C1 兼容校验 → 与在役 m5 scdet 镜头表交叉对比 →（可选）VLM 读总览图。
思想来源与授权隔离见 `../ARCHIVE-SUMMARY.md`、`../ADAPTATION-PLAN.md`（上游 GPL-3.0，
本目录全部代码为本仓原创实现，未复制上游源码）。

## 文件

| 文件 | 作用 |
|---|---|
| `kfextract.py` | 原创纯代码关键帧提取 + "模型可读"总览图（numpy/Pillow/ffmpeg，零模型） |
| `shot_qa.py` | 编排：提取 → 候选切分 → `pipeline/contracts.py` C1 校验 → m5 基线对比 |
| `vlm_client.py` | OpenAI 兼容 VLM 读图客户端（凭证只走环境变量，缺失=BLOCKED） |
| `test_proto_shot_qa.py` | 离线 pytest（单元 + 契约 + 合成视频 e2e） |

## 运行

```bash
# 测试（离线）
.venv/bin/python -m pytest test_proto_shot_qa.py -v

# 真实素材（前处理 + 契约 + m5 基线对比；素材在项目层不在 repo 层，路径用绝对式）
P=/opt/gpumachine/projects/chenmai8/短剧多国出海
.venv/bin/python shot_qa.py $P/materials/raw/didaozhan_p1.mp4 \
  -o results/didaozhan_p1 --ep didaozhan_p1    # 该文件已实锤损坏 → exit 4 BLOCKED
.venv/bin/python shot_qa.py $P/clips/e2e01_raw.mp4 \
  -o results/e2e01 --ep e2e01 --baseline $P/jobs/e2e01/02_shots/shots.json

# VLM 腿（凭证到位后；缺失则 exit 3 BLOCKED——不伪造结果）
OPENAI_BASE_URL=http://100.100.0.6:8080/v1 OPENAI_API_KEY=<经bao注入> \
  VLM_MODEL=<模型名> .venv/bin/python shot_qa.py <video> -o results/x --vlm
```

## 退出码约定

`0` 成功；`2` 参数/运行错误；`3` VLM 凭证缺失（BLOCKED 语义，UNKNOWN≠PASS，绝不默认放行）；
`4` 源视频损坏——实际解码覆盖时长不足容器时长 50%（如 `materials/raw/didaozhan_p1.mp4`：
容器元数据 1541.8s，实际仅解出 570/46236 帧，h264 NAL 连续报错；ffmpeg 对坏流会静默早停，
本守卫把"残缺帧序列"显式挡下，不静默当全片结论）。

## 产物

`results/<ep>/`：`keyframes.json`（时间轴+diff 分值）、`overview*.jpg`（时序总览，VLM 输入）、
`frames/`（单帧原图）、`report.json`（含 m5 对比指标）；`results/` 只入库
`report.json`/`keyframes.json`（图片体量大，留盘不入库；目录名不用 `out/`——
仓库根 .gitignore:41 的全局 `out/` 会整树排除，祖先被排除后子级否定规则无效）。
