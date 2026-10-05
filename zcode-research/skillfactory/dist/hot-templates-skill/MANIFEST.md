# MANIFEST — hot-templates-skill v1.0.0

四平台爆款内容结构模板技能包：把「主题 + 卖点列表」确定性地渲染为可直接交付的文案骨架（`骨架.md` + `structure.json`），覆盖抖音口播稿 / 小红书图文 / 公众号文章 / 短视频分镜表（6 镜 45 秒），`【占位:…】` 开放槽位不编造、产物逐字节可复现。

| 顶层条目 | 用途 |
|---|---|
| `SKILL.md` | 技能主文档（agent 读这个：输入格式、四平台模板表、使用步骤、退出码 0/2、红线与文档地图） |
| `README.md` | 面向使用者的快速开始、运行目录约定与边界说明 |
| `CHANGELOG.md` | 版本历史（含 1.0.1 模板常量对齐修复记录） |
| `EVALUATION.md` | 盲评与确定性评测结果及复现命令 |
| `LICENSE` | MIT 许可证 |
| `requirements.txt` | Python 运行依赖声明（无第三方依赖，纯标准库，Python >= 3.8） |
| `MANIFEST.md` | 本清单 |
| `scripts/` | 确定性引擎：`gen.py`（CLI 契约唯一入口，纯标准库） |
| `references/` | 四平台模板规范（dy/xhs/wx/video.md）+ `frozen-tokens.md`（接口常量表：占位符 token、要素命名、填充语义的权威清单） |
| `eval/` | 确定性评测：`runner.py`（8 case × 5 项机器检查）+ `golden.json`（黄金集 + 5 条 A/B 任务） |
| `reference/` | 官方样例：`inputs/` 输入 JSON ×8 与 `out/` 参照产物单元 ×8 |
