# OSS Manifest —— 上游开源件核实表

> 核实日期：2026-09-28（windev-01，经 WebFetch 直接读取 GitHub / PyPI / Hugging Face 权威页面；当日搜索接口限流，全部关键项以官方页面为准）。
> 用途：构建期版本固定依据 + 法务合规底稿（本文件为内部文件，不进公开仓库）。

## 一、主表

| 上游项目 | URL | 许可证（已核实） | 当前版本（2026-09-28 核实） | 我们用它什么 | 商用授权需求 | 替代备选 |
|---|---|---|---|---|---|---|
| Microsoft Presidio | https://github.com/microsoft/presidio | MIT | presidio-analyzer 2.2.364（2026-07-22，PyPI，支持 Py3.10–3.14） | ① 识别器框架形态参考（自定义中文 recognizer 组织方式）；② 测评基线 B（最小中文模式） | 无（MIT） | 自研正则引擎（MVP 主实现即自研，Presidio 不在主链路） |
| LiteLLM | https://github.com/BerriAI/litellm | MIT（PyPI License 表达式核实；企业版特性目录另计） | 1.103.0 stable（2026-09-27） | 可选的"多上游统一接入"生态兼容演示（改 baseURL 即接入）；不在 MVP 主链路 | 无（MIT，企业目录除外） | 自研 httpx OpenAI 兼容适配器（主实现） |
| Qwen3Guard | https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B （系列：Gen/Stream × 0.6B/4B/8B） | Apache-2.0 | HF 模型卡核实，transformers>=4.51 | 语义层第一档：prompt 侧越狱/注入/有害判定（0.6B，CPU 推理，采样执行） | 无（Apache-2.0） | 规则词表 + 上游 LLM-judge（P0 回退）；Stream 变体不进 MVP |
| hfl/chinese-roberta-wwm-ext | https://huggingface.co/hfl/chinese-roberta-wwm-ext | Apache-2.0 | HF 卡（注意：须用 Bert* 类加载） | NER 教师模型基座（large 变体同系列，训练期在 GPU 机） | 无（Apache-2.0） | hfl/chinese-macbert-base(large)（同为 Apache-2.0，已核实） |
| hfl/chinese-macbert-base | https://huggingface.co/hfl/chinese-macbert-base | Apache-2.0 | HF 卡 | NER 基座备选 | 无（Apache-2.0） | — |
| hfl/rbt3 | https://huggingface.co/hfl/rbt3 | Apache-2.0 | HF 卡（3 层 RoBERTa-wwm 蒸馏版） | NER 学生模型（CPU 部署目标） | 无（Apache-2.0） | rbt6（同系列更大） |
| ONNX Runtime | https://pypi.org/project/onnxruntime/ | MIT | 1.30.0（2026-09-10，Py3.11–3.14，Win x64 wheel 核实） | NER/OCR CPU 推理 + INT8 动态量化 | 无（MIT） | — |
| MinerU | https://github.com/opendatalab/MinerU | **已变更为"MinerU Open Source License"（基于 Apache 2.0 + 附加条件，历史上为 AGPL-3.0）——启用前必读 LICENSE.md** | 4.0.8（2026-09-27 tag） | P2：复杂版式 PDF 解析。Windows pip 原生可装（mineru>=4,<5；基础档 CPU/ONNX 约 0.8G 模型即可跑，但整体偏重） | 视附加条件，法务确认后再启用 | RapidOCR（MVP 唯一 OCR 路径）+ pypdfium2 文本层 |
| PaddleOCR | https://github.com/PaddlePaddle/PaddleOCR | Apache-2.0 | 3.7.0（2026-06-11；PP-OCRv5 在档，PP-OCRv6 已发布；PP-StructureV3 支持） | 仅作 P2 重解析路线候选；Windows CPU 官方支持但需 paddlepaddle 框架 wheel（未实测） | 无（Apache-2.0） | RapidOCR |
| RapidOCR | https://github.com/RapidAI/RapidOCR | Apache-2.0（代码+捆绑模型均 Apache-2.0，MODEL_LICENSES.md 核实） | v3.x（页内未见精确号；PyPI 安装时固化） | **MVP 扫描件 OCR 唯一路径**：`pip install rapidocr onnxruntime`，纯 CPU，Windows 无忧 | 无（Apache-2.0） | PaddleOCR（重） |
| PyMuPDF | https://pypi.org/project/PyMuPDF/ | **AGPL-3.0 或 Artifex 商业双授权**（PyPI 核实） | 1.28.2（2026-08-06） | PDF 彻底删除式导出的首选引擎（redaction 重写） | 闭源/许可证不兼容场景需商业授权；**公开仓库主许可证未定前是法务风险点** | **pikepdf（MPL-2.0）内容流手术 + pypdfium2**，已列入开发指令 D3 决策点 |
| pikepdf | https://pypi.org/project/pikepdf/ | MPL-2.0（可闭源链接，修改 pikepdf 本身需开放） | 10.14.0（2026-09-26，Win x64 wheel Py3.11–3.15 核实） | PDF 合规备选引擎：算子级内容流操作（删除 Tj/TJ 文本对象） | 无（MPL-2.0 条件宽松） | — |
| pypdfium2 | https://pypi.org/project/pypdfium2/ | Apache-2.0 / BSD-3-Clause 双许可（核实） | 5.13.0（2026-08-13，Win x64 wheel） | PDF 文本抽取+页面渲染（扫描件 OCR 前置、导出后验证） | 无（Apache/BSD） | pdfminer.six |
| Faker | https://pypi.org/project/Faker/ | MIT | 40.39.0（2026-09-14，Py>=3.10） | 合成测评集 zh_CN 人名/地址/电话槽位填充 | 无（MIT） | 自研姓名/区划表（部分必须自研：校验位号码、海南区划） |
| Open WebUI | https://github.com/open-webui/open-webui | **Open WebUI License**（BSD-3 系 + 保留"Open WebUI"品牌标识的附加要求，LICENSE/LICENSE_HISTORY 核实） | v0.11.4（2026-09-21） | 生态兼容演示（网关对其就是一个 OpenAI 后端）；**pip 安装硬性要求 Python 3.11**（本机 3.12，需 side-install 或仅文档演示） | 品牌条款需遵守；我们仅"指向性使用"，不修改不分发其代码 | 自研 webui（MVP 主演示 UI，已定） |
| Dify | https://github.com/langgenius/dify | Dify Open Source License（Apache 2.0 + 附加条件：多租户 SaaS 限制、品牌/版权条款；企业版另售） | 1.17.1（2026-09-10） | 仅计划书/演示叙事："现有 Dify 流程改一行 baseURL 即接入"（本机无 Docker，不做部署） | 自用接入无碍；不得多租户转售 | 文档级演示即可 |
| Langfuse | https://github.com/langfuse/langfuse | MIT（ee/ 目录除外——核实） | v4.46.0（2026-09-25） | P2：LLM 调用追踪看板（自托管）；MVP 审计用自研 SQLite | 无（MIT，避开 ee/ 功能） | 自研审计（MVP 即自研） |
| Label Studio | https://github.com/HumanSignal/label-studio | Apache-2.0（社区版核实） | 1.23.1（2026-09-25） | 训练期（延后）：NER 标注抽检/修正 | 无（Apache-2.0） | VSCode+JSONL 手改（样例少时） |
| thu-coai Safety-Prompts | https://github.com/thu-coai/Safety-Prompts | Apache-2.0（核实；10 万条中文安全/指令攻击 prompt） | 静态数据集 | 注入/越狱评测种子（含目标劫持/提示泄露/角色扮演等类别） | 无（Apache-2.0，保留声明于 third_party 内部目录） | 自造注入样例 |
| BAAI/bge-m3 | https://huggingface.co/BAAI/bge-m3 | MIT（核实） | HF 卡（~568M，8192 ctx） | P2：代答库语义匹配、引用核验 | 无（MIT） | MVP 用关键词匹配 |
| BAAI/bge-reranker-v2-m3 | https://huggingface.co/BAAI/bge-reranker-v2-m3 | Apache-2.0（核实） | HF 卡 | P2：检索重排 | 无（Apache-2.0） | — |
| openguardrails | https://github.com/openguardrails/openguardrails | Apache-2.0 | protocol v1.10 | **不可用作护栏备件**：2026-09 核实已转型为"AI 代理安全检测器中立协议/基准"，非内容安全护栏产品（概念文档此处已过时） | — | 规则词表+LLM-judge（已写入开发指令 §11） |

## 二、基础库（常规核实，无授权风险）

| 库 | 版本口径 | 许可证 | 用途 |
|---|---|---|---|
| fastapi / uvicorn / httpx / pydantic v2 / jinja2 / python-multipart | D0 安装当日最新 stable，freeze 到 constraints.txt | MIT / BSD-3 | 网关与前端 |
| python-docx | 最新 stable | MIT | Word 解析/改写 |
| openpyxl | 最新 stable | MIT | Excel 解析/改写/隐藏列检查 |
| pytest / ruff | 最新 stable | MIT | 测试与 lint |

## 三、训练数据源（延后使用，许可注意）

| 数据 | 来源 | 许可状态 | 处置 |
|---|---|---|---|
| CLUENER 2020 | GitHub 公开 | 无明确许可声明 | 仅竞赛/研究内部使用，不随公开仓库分发 |
| MSRA NER | LDC 授权语料的常见流通版 | **LDC 许可，不可再分发** | 不分发；仅本地训练参考 |
| Weibo NER / Resume NER | GitHub 公开 | 各自页面注明，多为研究用途 | 不分发 |
| Safety-Prompts | thu-coai | Apache-2.0 | 可用，保留声明 |
| 自研合成语料 | 本项目生成器 | 自有，全合成零真实 PII | 可公开（生成器+种子），是路演卖点 |

## 四、概念文档与核实结果的差异清单（构建/材料时须修正）

1. **MinerU 许可证已不是 AGPL-3.0**，现为 Apache 2.0 基础上的自定义附加条件许可（且 4.x Windows 原生安装比传闻轻）——计划书表述需更新；但仍偏重，MVP 不用。
2. **openguardrails 已转型**，不再是"带 PII 识别的护栏"，Qwen3Guard 的备件改为规则词表+LLM-judge。
3. **Open WebUI 许可证带品牌保留条款**，且 pip 安装锁定 Python 3.11——不能写成"直接开源替换/嵌入"。
4. **PyMuPDF AGPL 风险确认存在**——计划书中的 PDF"彻底删除"能力如以闭源/商业形态交付，需 Artifex 商业授权或切换 pikepdf 引擎；开源形态（整个仓库 AGPL）则可用，由法务定主许可。
5. PaddleOCR 最新为 3.7.0（PP-OCRv6 已出），概念文档写 PP-OCRv5/PP-StructureV3 仍有效但非最新。
6. 版本快照：presidio-analyzer 2.2.364 / litellm 1.103.0 / onnxruntime 1.30.0 / PyMuPDF 1.28.2 / pikepdf 10.14.0 / pypdfium2 5.13.0 / Faker 40.39.0 / Open WebUI v0.11.4 / Dify 1.17.1 / Langfuse v4.46.0 / Label Studio 1.23.1 / PaddleOCR 3.7.0 / MinerU 4.0.8（均 2026-09-28 核实）。
