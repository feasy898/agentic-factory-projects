# OSS Manifest（上游项目与数据集核实表）

> 核实日期：2026-09-28 · 核实方式：GitHub API / PyPI JSON / Crossref API / Mendeley Data API / 论文全文抓取（jina reader）/ HF API。
> 本文件为内部规划文件，可写开源名；**公开仓库禁止出现下列项目名与许可证声明**（见 开发指令.md §10）。
> 红线先行：**AGPL 件禁用**（ultralytics、AlbumentationsX）；rfdetr 的 XL/2XL 权重为 PML 1.0，不用（Nano/Small/Medium/Large 与全部 Seg 变体是 Apache-2.0，可用）。

## 一、软件

| 上游项目 | URL | 许可证（已核实） | 版本锚点（已核实） | 我们用它什么 | 商用授权需求 | 替代备选 |
|---|---|---|---|---|---|---|
| RF-DETR / RF-DETR-Seg | github.com/roboflow/rf-detr | Apache-2.0（代码+Nano/Small/Medium/Large 及全部 Seg 权重；XL/2XL 为 PML 1.0，**不用**） | v1.11.0（2026-09-24），develop@9c8c4f9be171；PyPI rfdetr 1.11.0，py≥3.10 | 未来微调的检测/分割骨干；`RFDETRSegNano` COCO 权重做推理管线 smoke；训练脚本 | Apache-2.0 允闭源商用；公开仓库不提名字 | RT-DETR(v2, Apache-2.0, HF transformers)、DINOv2+MaskHead 自研 |
| SAM 2 | github.com/facebookresearch/sam2 | Apache-2.0（代码+checkpoint+训练码；第三方 cc_torch BSD-3、demo 字体 OFL） | main@2b90b9f5ceec（SAM 2.1，2024-12-16）；权重 `facebook/sam2-hiera-small`（HF，184MB，已验证可下载） | 无掩码数据集（USK-COFFEE）自动抠单粒素材；未来 SAM3 只当离线老师（Meta 自定义许可，不进公开链路） | Apache-2.0 允商用 | MobileSAM（Apache-2.0）、直接用 DCV 自带多边形掩码（首选，SAM2 非阻塞） |
| SAHI | github.com/obss/sahi | MIT | v0.12.7（2026-09-25） | 高分辨率整盘图切片推理（密集盘 + NN 模型阶段）；官方支持 RF-DETR（rfdetr≥1.6.2） | MIT 允商用 | 自写滑窗+NMS（200 行内） |
| Label Studio | github.com/HumanSignal/label-studio | Apache-2.0 | v1.23.1（2026-09-25） | 低置信度样本人工复核队列；D4 本地分拣照片复核 | Apache-2.0（企业版另收费，不用） | CVAT（MIT）、X-AnyLabeling |
| Albumentations | github.com/albumentations-team/albumentations | MIT（**仓库已归档 2025-06，终版 2.0.8**；后继 AlbumentationsX 为 AGPL/商业双许可，**禁用**） | albumentations==2.0.8（钉死） | 合成盘光照扰动/模糊/噪声 | MIT 允商用 | torchvision.transforms、kornia（Apache-2.0） |
| OpenCV (ArUco) | github.com/opencv/opencv（PyPI opencv-python） | Apache-2.0 | opencv-python==4.10.0.84（4.7 起 aruco 并入主库；PyPI 已出 5.0.0.93，**钉 4.x**） | ArUco 标定/单应变换、ClassicSeg（Otsu/分水岭）、LAB 色差、IO | Apache-2.0 | — |
| SciPy | github.com/scipy/scipy | BSD-3 | scipy==1.18.1 | `linear_sum_assignment` 上下配对；统计 | BSD | 匈牙利自实现（lapjv） |
| bge-m3 | huggingface.co/BAAI/bge-m3 | MIT | 已核：license:mit，1024 维，100+ 语（中/英/越覆盖），8192 ctx | 溯因知识库检索嵌入 | MIT | text-embedding API（需网）、rank_bm25 兜底 |
| Chroma | github.com/chroma-core/chroma | Apache-2.0 | chromadb==1.5.9 | 知识库向量库（本地持久化） | Apache-2.0 | rank_bm25（纯 Python 兜底） |
| vLLM | github.com/vllm-project/vllm | Apache-2.0 | v0.30.0（2026-09-22；**仅 Linux**） | （延后）GPU 机上服务化 Qwen | Apache-2.0 | Ollama、LMDeploy |
| Qwen3 | huggingface.co/Qwen/Qwen3-8B | Apache-2.0（已核 tags） | 部署时取最新小尺寸 | （延后）离线三语报告/溯因 | Apache-2.0 | GLM 开源系列 |
| segno + zxing-cpp | github.com/heuer/segno（BSD） / github.com/zxing-cpp/zxing-cpp（Apache-2.0，有 Windows wheel） | BSD / Apache-2.0 | 最新稳定 | 二维码生成（纯 Python）/ 解码（eval 用） | 均允许 | qrcode（BSD）+ pyzbar（需 zbar dll，Windows 麻烦，不用） |
| FastAPI / Gradio | fastapi 0.141.1（MIT） / gradio 6.28.0（Apache-2.0） | — | pinned | API + 演示页 | 均允许 | Flask |
| Jinja2 / matplotlib | BSD /（matplotlib PSF 兼容） | — | pinned | 报告模板 / 直方图 | 允许 | — |
| **禁用** | ultralytics（YOLOv8/11） | AGPL-3.0 | — | 不引入（论文里 YOLOv8 数字仅作对比引用） | — | RF-DETR（Apache） |
| **禁用** | AlbumentationsX | AGPL-3.0 | — | 不引入 | — | albumentations==2.0.8（MIT） |
| **禁用** | rfdetr[plus] XL/2XL 权重 | PML 1.0 | — | 不引入（PML 需单独评估） | — | RFDETRMedium/Large |

## 二、数据集（逐一核实，含许可证）

| 数据集 | 核实结果 | 许可证 | 下载 | 我们用它什么 | 替代备选 |
|---|---|---|---|---|---|
| **DefectosCafeVerde**（概念文档"MDPI 双面数据集"） | **已核实，主源。** 论文：Sandoval-Gonzalez et al., *Dual-Sided Green Coffee Bean Defect Inspection Using a Mechatronic System with AI-Powered Computer Vision*, Agriculture 2026, 16(16):1796，DOI 10.3390/agriculture16161796（2026-08-21，Crossref 核实）。墨西哥韦拉克鲁斯阿拉比卡，双 Q-grader 按 SCA 350g 协议分堆；机构化翻面装置双 16MP 相机；双面使平均单类检出 0.727→0.908；YOLOv8 P=97.4%/R=99.6%/mAP50=96.5%；RPi4 实时 38min/350g。12 类 = normal + sour/brocade/peaberry/shell/elephant/frozen/black_ear/broken/dry/triangle/black（11 缺陷+1 好豆）。论文写 9600 图（含增强），**公开发布版 4038 图、12 类、多边形掩码**（2025-06 上架） | **CC BY 4.0**（论文参考文献[35]明确） | universe.roboflow.com/redtraining/defectoscafeverde（需免费 Roboflow 账号+API key，导出格式选 coco-segmentation；页面反爬，浏览器可开） | **主源**：单粒素材库（有掩码，不依赖 SAM2）、合成引擎原料、RulesV0 规则阈值参考 | USK-COFFEE |
| **USK-COFFEE** | **已核实，辅源。** Febriana, Muchtar, Dawood, Lin, *USK-COFFEE Dataset: A Multi-Class Green Arabica Coffee Bean Dataset for Deep Learning*, IEEE CyberneticsCom 2022。8000 图、256×256、4 类（peaberry/longberry/premium/defect），印尼苏门答腊阿拉比卡生豆 | 官网**未明示**（描述为公开数据集；Roboflow Universe 镜像默认 CC BY 4.0） | 官方 coffee.comvislab-usk.org → Google Form 申请（forms.gle/4QSchCETdWrWrtfA8，人工审批）；Universe 有第三方镜像"USK-Coffe" | 粒型素材补充（peaberry/longberry 形态）；**4 类粗标 defect 不进缺陷训练映射** | DCV 已够用，此集属锦上添花 |
| **多豆场景数据集**（Marcelo 2026） | **论文已核实，下载通道未核实通。** *Computer vision-based multi-bean coffee grading using deep learning networks*, Procedia Computer Science 2026（S1877050926023045），6468 图/35413 标注，YOLOv8 最优。ScienceDirect 页面动态渲染抓不到 Data availability；Mendeley/Zenodo 检索无匹配 | 未知 | 未找到 → D1 花 1h：邮件作者（论文通讯邮箱）要链接；要不到就放弃 | 备选：密集场景预训练（训练期） | 放弃不阻塞（合成引擎本身产密集盘） |
| **孟加拉数据集**（概念文档说法**部分有误**） | **已核实并纠正**：实为 Sylhet Agricultural University（孟加拉）团队用的**东帝汶豆**。Gope et al., *Comparative analysis of YOLO models...*, Scientific Reports 2024（10.1038/s41598-024-78598-7）：5044 图、4 缺陷类（black/broken/fade/sour）；AIMS 2025 续作 4367 图 6 类。**未证实含罗布斯塔**（东帝汶以阿拉比卡为主） | 未声明 | **不公开**："available from corresponding author upon request"（hlgope@sau.ac.bd） | 备选：训练期补充缺陷样本 | 放弃不阻塞 |
| **泰国数据集**（AL-ViT） | **论文已核实，数据集未公开。** Vachmanus et al. 2025, *AL-ViT: Label-efficient Robusta coffee-bean defect...*（ScienceDirect）：泰国罗布斯塔 2098 图可控光照。"17 类"未在摘要证实；公开下载未找到 | 未知 | 未找到 | 备选（罗豆形态参考） | HN-Robusta 自建（D4 分拣拍照） |
| **HN-Robusta v0.1（自建）** | 不适用（自建） | 我们定（建议 CC BY 4.0 开源发布） | — | 罗豆本地适配唯一真源；D4"先分拣后拍照"（按 NY/T 1519 图谱分堆拍，SAM/掩码自动出） | — |
| 标准文本 | NY/T 604（生咖啡）、NY/T 1519-2007（缺陷参考图）、NY/T 1518-2007（取样）、DB46/T 642-2024（海南罗布斯塔）、DB46/T 278（初加工）、CQI Fine Robusta manual | 标准文本受版权保护，**只引用条款号+阈值做配置，不全文转载** | 全国标准信息公共服务平台核对现行状态（D1 任务） | 定级 YAML + 知识库摘要 | — |

## 三、不确定项清单（截至 2026-09-28）

1. DefectosCafeVerde 的 Roboflow 页面当前版本号/是否仍 CC BY 4.0 —— 下载时在页面确认（引用论文[35]为据）。
2. 多豆数据集/泰国数据集的公开下载 —— 均未找到，按备选处理，不阻塞 MVP。
3. USK-COFFEE Google Form 审批时效 —— 假期可能慢，不阻塞（DCV 是主源）。
4. RF-DETR ONNX 导出在 Windows CPU 的可用性 —— 未实测，oss_smoke 里验证；失败不阻塞（v1 直接 torch CPU 推理）。
5. SAM2 原生 Windows pip 安装 —— 官方称 CUDA 扩展失败仍可用（CPU 路径），未实测；备选 transformers 加载 HF 权重；素材库主路径根本不依赖 SAM2（DCV 有掩码）。
