# 数据集目录：规范与人工解锁步骤

> 内部文件（数据管线文档，按 D-3 不随公开仓库发布）。维护脚本：`scripts/download_datasets.py`。
> 状态：**2026-09-28**。数据本体一律不入库（.gitignore）；本 README 与下载器随 git 跟踪。

---

## 1. 目录规范（开发指令 §6）

```
data/datasets/
├─ dcv/                       主源（coco-segmentation 导出）
│  ├─ content/                解包后的导出内容（train/ valid/ test/ + _annotations.coco.json）
│  ├─ _downloads/*.zip        原始归档（sha256 已记入 manifest）
│  ├─ SHA256SUMS              清单：`sha256sum -c` 可直接校验（不含自身条目）
│  └─ manifest.json           来源/版本/许可证/导出id/逐split统计/类别表
├─ dcv_sample/                小样本（--sample N），结构与 dcv 相同，供 M12 先行验证
└─ usk_coffee/                辅源（人工表单获取后经 --usk-archive 登记，结构同上）
```

校验命令（Git Bash，在对应数据集目录内执行）：

```bash
cd data/datasets/dcv && sha256sum -c SHA256SUMS
```

manifest.json 为排序缩进的稳定 JSON，关键字段：`source_url / version / format /
license / archive.sha256 / totals / coco_validation.splits / categories`。

---

## 2. 主源 DCV（Roboflow Universe，coco-segmentation）

**是什么**：公开的生咖啡豆缺陷分割数据集——4038 图、12 类多边形掩码
（normal, sour, brocade, peaberry, shell, elephant, frozen, black_ear, broken,
dry, triangle, black），CC BY 4.0。论文：Agriculture 2026, 16(16):1796。
12 类 → 内部 taxonomy 的映射见 `configs/defect-taxonomy.yaml`（W1 产出）。

**现状（2026-09-28 实测）：BLOCKED —— 下载必须 API key，本机暂无。**

实测通道结论（本机真实执行）：

| 通道 | 结果 |
|---|---|
| `api.roboflow.com`（REST，下载器走这里） | **可达**；无 key → 401 `This method requires your API key` |
| `universe.roboflow.com` 网页（curl 带浏览器 UA） | 403（Cloudflare 反爬；不影响 API 下载通道） |
| HuggingFace / hf-mirror 镜像（`defectoscafeverde` / `defectos cafe verde` / `coffee bean defect` 等） | 无此镜像 |
| GitHub 搜仓 / 搜码 | 无镜像仓（代码搜索需登录，仓库搜索 0 命中） |
| ModelScope | 无镜像（仅无关 robotics 数据集） |
| MDPI 论文 Data Availability | 无直链，仅指向 Roboflow Universe |

### 人工解锁三步（约 5 分钟）

1. **注册**：Roboflow 官网注册免费账号（邮箱即可，无需绑卡）。
2. **取 key**：登录后 `Settings → Roboflow API Keys → Private API Key → 复制`。
3. **下载**（仓库根目录，key 只经命令行/环境变量注入，不会写进任何文件）：

```powershell
# 方式 A：--key 注入
.venv/Scripts/python.exe scripts/download_datasets.py --only dcv --key <你的PrivateKey>

# 方式 B：环境变量（适合把 key 留在本机会话，不进 shell 历史）
setx ROBOFLOW_API_KEY "<你的PrivateKey>"   # 重开终端生效
.venv/Scripts/python.exe scripts/download_datasets.py --only dcv
```

推荐流程（先小后大）：

```bash
# 1) 先看有哪些版本、确认 key 可用（不落盘）
.venv/Scripts/python.exe scripts/download_datasets.py --only dcv --key <KEY> --list-versions
# 2) 小样本验证全链路（每 split 抽前 50 张 → data/datasets/dcv_sample/）
.venv/Scripts/python.exe scripts/download_datasets.py --only dcv --key <KEY> --sample 50
# 3) 全量下载（4038 图，归档约 1~2 GiB；导出首次生成需等待，脚本自动轮询最多 30 分钟）
.venv/Scripts/python.exe scripts/download_datasets.py --only dcv --key <KEY>
```

常用参数：`--dry-run` 只解析导出直链不落盘；`--version <N>` 钉版本；
`--sample N` 产出小样本；`--max-gb` 大小上限（默认 8 GiB）。

### 常见错误对照

| 现象 | 含义 / 处理 |
|---|---|
| 401 `This API key does not exist` | key 抄错/失效；重新复制 Private API Key（注意别带空格） |
| 403 | workspace/project 不对或账号无权限；核对 `universe.roboflow.com/redtraining/defectoscafeverde` 可打开 |
| 404 | 版本号不存在；用 `--list-versions` 看实际版本 |
| 长时间 `导出生成中 x%` | coco-segmentation 导出首次生成慢，脚本会轮询；中断后重跑同命令会续上 |
| `sha256sum -c` 不一致 | 归档损坏；删 `_downloads/*.zip` 后重跑下载（脚本自动重下并重建清单） |

### 为什么不用 `pip install roboflow`

roboflow pip 包依赖 `opencv-python-headless`，会与本仓钉版的
`opencv-python==4.10.0.84`（doctor.py 逐项核对）冲突。下载器按
roboflow==1.5.1（Apache-2.0）的 REST 协议用已钉版的 httpx 直连实现，
行为对齐其 `Version.download()`：项目→版本→导出轮询（202→200 `export.link`）→流式下载。
认证优先 `Authorization: Bearer`（key 不进 URL），401 时自动回退 query 参数。

---

## 3. 辅源 USK-COFFEE（人工表单，无公开直链）

**是什么**：乌干达咖啡生豆数据集，4 类（peaberry / longberry / premium / defect）。
用途边界（开发指令 §3）：**只做素材粒型参考；`defect` 粗标不进训练映射。**

**人工申请步骤**：

1. 打开官方 Google Form：<https://forms.gle/4QSchCETdWrWrtfA8>，
   按表单填写姓名/机构/用途（写明学术与研究用途即可提交）。
2. 等待官方邮件回复下载链接（人工审核，通常数天；**不阻塞主线**——主源 DCV 优先）。
3. 拿到包后登记入库（本地 zip 路径或直链 URL 均可，自动算 sha256 + 建清单）：

```bash
.venv/Scripts/python.exe scripts/download_datasets.py --only usk --usk-archive "C:/Downloads/usk_coffee.zip"
```

注意：USK 的授权条款以官方回复为准（学术用途授权，非 CC 式再分发）；
解包后的 `content/` 与 sha256 清单同 §1 规范，勿对外转发原始包。

---

## 4. 与下游的衔接

- **W12a 素材库**：`python -m beaneye.synth.build_materials --src data/datasets/dcv --out data/materials/dcv/`。
  （开发指令 §4 的 M12 示例里写的是 `data/datasets/defectos_cafe_verde`，以本目录规范
  `data/datasets/dcv` 为准——M12 走 `--src` 传参，无需改契约。）
- 小样本路径：`data/datasets/dcv_sample/`（结构一致，可直接当 `--src` 先跑通）。

## 5. 2026-09-28 验收记录（本机真实执行）

| 检查 | 命令 | 结果 |
|---|---|---|
| 自检 5/5（合成链路回环/穿越拒绝/清单闭环/小样本/真实鉴权探针） | `python scripts/download_datasets.py --selftest` | `[SELFTEST] 5/5 PASS`，exit=0 |
| 无 key（预期 BLOCKED + 解锁步骤） | `python scripts/download_datasets.py --only dcv` | 打印解锁三步，exit=3 |
| 伪造 key 打真实 API（预期 401 分类 + key 脱敏） | `python scripts/download_datasets.py --only dcv --key RFfakeKEY…` | 真实 401 + 友好提示，exit=1，输出无 key 明文 |
| USK 无包（预期表单步骤） | `python scripts/download_datasets.py --only usk` | 打印 Form 步骤，exit=3 |
| 全量 DCV 下载 | 需真 key | **BLOCKED**：解锁动作 = §2 三步 |
