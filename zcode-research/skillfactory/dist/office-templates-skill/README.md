# office-templates-skill

**四类中文事务文书 → GB/T 9704 风格 Word**：把周报 / 请示函 / 会议通知 / 工作总结的结构化数据 JSON，确定性地生成一份可直接交付的 **文书.docx**——

- GB/T 9704 公文版式：A4 版心（上 3.7/下 3.5/左 2.8/右 2.6 cm）、居中黑体二号标题、顶格称谓、正文首行缩进两字符（仿宋三号、28 磅固定行距）、右对齐落款
- 附 **fields.json** 字段填充台账：哪些字段填了、哪些缺了、缺的怎么渲染，程序可逐条判定

两条设计红线（也是它区别于"让大模型随手写公文"的地方）：

1. **缺数据不编造**——必填缺失以 `____` 占位、选填缺失留空或整节省略，如实记账，绝不语义猜测补内容；
2. **产物确定性可复现**——正文无当前时间、无随机源，同输入连跑两次产物一致（`fields.json` 除 outputs 路径外逐字节一致）。

## 快速开始

依赖：Python 3.12+，`pip install -r requirements.txt`（python-docx>=1.1）

```bash
# 1. 用官方引擎生成一份文书（输入样例见 reference/inputs/<模板>/case*.json）
python scripts/gen_doc.py --template 周报 --data reference/inputs/周报/case1.json --outdir out/周报/case1

# 2. 机器自检（六类确定性检查，8 个官方样例全跑；在分发包根目录运行）
python eval/runner.py out reference/out
```

**运行目录约定（重要）**：`eval/runner.py` 无参数时的写死缺省路径是开发资产内的 `<包根>/oracle/out`（contract §5），分发包内**不存在** `oracle/` 目录——无参数直接运行会 exit 1。因此在本包中必须**显式传两个位置参数**：第 1 个是被测产物根（如 `out`），第 2 个是参照产物根（固定 `reference/out`），并在**分发包根目录**下运行。配套地，`eval/golden.json` 沿用开发资产的资产根相对路径（`oracle/inputs/...`、`oracle/out/...`），在本包中分别对应 `reference/inputs/...` 与 `reference/out/...`。

`eval/runner.py` 六类检查：8 个产物单元（四类 × case1/case2）齐全且每单元恰含 `文书.docx`+`fields.json` / docx XML 安全（拒绝 DOCTYPE/ENTITY，防 XXE）且可打开 / 版式四要素（标题居中黑体二号且与 title 一致、称谓顶格、正文 firstLineChars=200 仿宋三号 28 磅、落款右对齐右空两字）/ fields.json 键集合与计数自洽 / 台账与 docx 实际内容一致且缺失记账正确 / 与参照产物字段填充一致率 ≥90%。全部通过 exit 0（打印 JSON，`ok=true`），任一失败 exit 1。

## 作为 agent skill 使用

把本目录放进你的 agent 技能目录（Claude Code / Codex CLI / TRAE / Qoder 等 SKILL.md 兼容宿主均可），agent 读取 `SKILL.md` 后即可按其工作流程处理「写周报 / 起草请示函 / 发会议通知 / 写工作总结」类请求。渐进披露：主说明在 `SKILL.md`（字段语义 F1–F6、退出码 0/2、agent 五步工作流），四类模板的版式与字段细则在 `references/`（同名四份）。

## 评测报告（本技能自带体检报告）

见 [EVALUATION.md](EVALUATION.md)：v0.2 双臂双重复盲评 5 任务，基线 **7.7 → 治疗 8.9（Δ +1.20）**，任务级胜率 **100%（5/5）**、反向任务 **0**，判定**达标**（原始数据见开发方评测存档，未随包分发）；确定性评测第 1 轮通过，评测脚本随包附带，任何人可按上文命令复跑验证（发包时实跑：68/68 checks 全过、字段一致率 100.0% 66/66）。

## 目录结构

```
SKILL.md              技能说明（agent 读这个）
scripts/gen_doc.py    确定性引擎（contract §2 唯一契约入口）
references/           四类模板的版式与字段规范（周报/请示函/会议通知/工作总结.md）
requirements.txt      依赖清单（python-docx>=1.1）
eval/                 确定性评测器 runner.py + 黄金集清单 golden.json（8 输入 + 5 条 A/B 任务）
reference/            官方样例（inputs 数据 JSON ×8 + out 参照产物单元 ×8）
EVALUATION.md         盲评与确定性评测报告
CHANGELOG.md          变更记录
LICENSE               MIT
MANIFEST.md           包内容清单
```

## 边界

- **不做**（spec §12 非目标）：模板定制、字段增删、多文档合并、docx→pdf、红头/公章/版记等公文要素；数据语义校验（日期格式、电话号码按原样字符串处理）；文辞润色/审美优化——文案由数据公式化推导。
- 一次调用生成一份文书，不做并发/增量/批量目录输入。
- 仿宋/黑体是 docx 内的字体**声明**（写入 XML 即达标），真实渲染字形取决于查看机字体库。
- 非法输入（模板名不在四类、数据文件不存在、非 JSON、顶层非对象）退出码 2、不产任何产物；**必填缺失不是错误**（退出码 0，`____` 占位并记账）。
