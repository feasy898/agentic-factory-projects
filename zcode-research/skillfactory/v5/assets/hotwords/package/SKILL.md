---
name: hotwords
description: 单位如何从零建一份自己的 ASR 热词表：采集口径、权重分档建议、用 hotwords.py 维护并导出 FunASR 可直接使用的热词文件。适用于使用 FunASR 等支持热词偏置的中文语音识别引擎的业务单位。
---

# 单位热词表建设指南（hotwords skill）

## 1. 这份 skill 解决什么问题

通用中文 ASR 模型对**业务专有名词**的识别通常明显偏差：产品名、内部系统名、客户称谓、
型号、行话缩写、人名地名。这类词在话里占比不高，但识别错了直接损害可用性（客服记录、
质检关键词、合规留痕）。热词（hotword）偏置是成本最低的补救：不改模型、不动训练，
只需维护一份「词 + 权重」清单。

本 skill 配套工具 `hotwords.py`（同目录）负责清单的日常维护与导出：

```bash
python hotwords.py --store store.json add 通义听悟 --category 产品 --note 转写工具 --weight 30
python hotwords.py --store store.json list
python hotwords.py --store store.json remove 旧词
python hotwords.py --store store.json export --format funasr --out hotwords_funasr.txt
```

库是普通 JSON（`{"version":1,"words":[{word,category,note,weight},...]}`），可以进 git、
可以人工评审、可以用脚本批量加工。

## 2. 采集口径（哪些词该进表）

按下面四条筛，**同时满足才收**：

1. **业务专有**：通用模型没见过的——自研产品/系统名、组织内部称谓、专有型号、行业缩写。
   通用词（"退货""发票"）不收，模型本来就会。
2. **ASR 易错**：同音/近音字多的词优先（如「灵犀」易被写成「灵熙」「零息」）。拿一批真实
   录音跑一遍转写，把误识别率高的词挑出来，是最直接的证据。
3. **高频或高代价**：出现频次高，或错一次代价大（金额、型号、投诉关键词、合规词）。
4. **够短**：建议 ≤ 8 字的连续词。长句、口号不适合做热词，拆成核心名词。

配套纪律：

- **去重**：本工具按「完全同字」判重（重复 add 会退出码 2 报错），先在表内保证唯一。
- **同音变体**：原则上只收**正字**（希望转写出现的那个写法），变体写进 note 备查，
  不要把错拼也加进表——热词偏置会把错拼也"拽"出来。
- **类别**：产品 / 售后 / 营销 / 人名 / 地名 / 术语……类别只是管理维度，不参与导出，
  但坚持归类，便于按部门认领和定期复核。
- **备注**：每个词写清来源与依据（"10 月客服录音误识别 23 次"），复评时有据可查。
- **维护节奏**：上线后每周把新增误识别 top 词过一遍：新词 add，连续几周无收益的词
  remove。热词表是活的，不是一次性的。

## 3. 权重建议（怎么定 weight）

权重是**同表内的相对偏置强度**，只有相对大小有意义，不存在"标准值"。以下为起步分档
（本工具缺省 20，与 fixtures 演示库一致）：

| 档位 | 建议值 | 适用 |
|---|---|---|
| 常规 | 20 | 一般业务词：普通术语、低歧义专名 |
| 重点 | 25 | 高频专名、轻微同音歧义的词（演示库「灵犀引擎」档） |
| 强纠错 | 30 | 错误代价高/同音干扰强的品牌名、型号、活动名（演示库「618大促」档） |

两条经验规则：

- **不要全部拉满**。权重过高会把近音的常用词也偏置成热词，把原来对的转写改错——
  热词表的收益来自"拉开档次"，不是"全员最高"。
- **用数据调档**：某词加了仍错 → 升一档；加了以后把别的常用词带错 → 降一档或删。
  每次调整只动一小批词，否则说不清因果。

## 4. 与 FunASR 的接法

1. 导出 FunASR 热词文件（每行一个词，格式为「词 空格 权重」）：

   ```bash
   python hotwords.py --store store.json export --format funasr --out hotwords_funasr.txt
   ```

   产出示例（缺省权重统一显式写出为 20，避免不同引擎缺省行为不一致）：

   ```
   悟空客服 20
   灵犀引擎 25
   618大促 30
   ```

2. 把该文件交给 FunASR 的热词机制使用：FunASR 支持热词偏置的模型（如 SeACo-Paraformer
   系列）接受「每行 词 [权重]」格式的热词表——Python 侧通过 `AutoModel` 的 `hotword`
   参数传入（文件路径或同格式字符串），部署侧 `funasr-wss-server` 提供 `--hotword`
   热词文件参数。**具体参数名随 FunASR 版本变化，以你所用版本的官方文档为准。**

3. 只需要纯词列表的场景（如只支持词表的封装层），导出 plain 格式（每行一词）：

   ```bash
   python hotwords.py --store store.json export --format plain --out hotwords_plain.txt
   ```

4. 注意事项：
   - 热词是**偏置不是词典**：提高目标词的命中率，但不保证 100% 正确，也不能替代
     模型选型与音频质量治理。
   - **每次改表后做回归**：固定一小批真实音频（含热词句式），对比改表前后的转写，
     确认目标词变好、无误伤，再发布到生产。
   - 导出顺序 = 库插入序；FunASR 侧如对行序/数量有上限要求（部分实现对热词条数
     有限制），先查所用版本文档，超限时按 weight 从高到低截取。

## 5. 上手三步

```bash
# 1) 建表：把第 2 节筛出的词逐条录入
python hotwords.py --store store.json add 悟空客服 --category 产品 --note 智能客服机器人

# 2) 评审：list 按类别分组核对
python hotwords.py --store store.json list

# 3) 发布：导出给 FunASR
python hotwords.py --store store.json export --format funasr --out hotwords_funasr.txt
```

工具行为契约（参数面、退出码、库格式）见同目录 `README.md` 与资产根的 `contract.md`。
