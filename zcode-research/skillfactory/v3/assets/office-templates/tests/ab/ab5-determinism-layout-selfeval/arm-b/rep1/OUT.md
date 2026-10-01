# AB5 · arm-b · rep1 —— 确定性（spec D1）A/B 对照与交付自评

- **日期**：2026-09-30（运行时刻 07:10–07:21 +0800）
- **被测（arm-b）**：`package/`，唯一入口 `package/scripts/gen_doc.py`（黑盒：本次仅通过运行该入口交互）
- **参照实现**：`oracle/oracle.py`（同样黑盒运行）
- **输入**：`oracle/inputs/会议通知/case1.json`（按约束**未读取其内容**，字段信息仅来自工具 stdout：11/11 字段填充，标题「关于召开三季度质量评审会的通知」）
- **环境**：Windows Server 2022（win32 10.0.20348 x64），Python 3.12.10，MSYS bash；工作目录 `D:\workspace\zcode研究\skillfactory\v3\assets\office-templates`
- **约束遵守**：本次**未读取 `skillfactory/` 下任何文件内容**（含 spec.md、SKILL.md、gen_doc.py、oracle.py、eval/runner.py 源码、输入 JSON、oracle/out 产物）。接口一律经 `--help` 运行时获知；产物字节诊断在复制到 skillfactory **之外**的副本上进行。因此 **spec D1 原文不可读，判定按任务书表述操作化**（见 §6）。

---

## 1. 医嘱检查（exactly as prescribed，全部已执行）

### 1.1 入口发现（`--help`）

```
$ python package/scripts/gen_doc.py --help
usage: gen_doc.py [-h] --template {周报,请示函,会议通知,工作总结} --data DATA --outdir OUTDIR
四类中文事务文书生成引擎（周报/请示函/会议通知/工作总结）
```

### 1.2 同输入连跑两遍 → 同一 outdir（覆盖复写）

```
$ python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1
```

- **RUN 1**：EXIT=0，stdout：`已生成：package\out\会议通知\case1\文书.docx（模板=会议通知，标题=关于召开三季度质量评审会的通知，字段 filled/total=11/11，必填缺失=无，模板外键=无）`
- **RUN 2**（同命令覆盖复写）：EXIT=0，stdout 同上（逐字一致）

| 文件 | 预状态哈希（07:11 旧产物） | RUN 1 后 | RUN 2 后 | 两遍是否一致 |
|---|---|---|---|---|
| `fields.json` | `f21e402b…` | `f21e402b…` | `f21e402b…` | ✅ 三态逐字节一致 |
| `文书.docx` | `7ca17bd4…` | `9fabef53…` | `8a24141c…` | ❌ **每写一次哈希都变**（三者互不相同；大小均 37200 B） |

（完整 64 位哈希见 §7 附表 A。）

### 1.3 确定性评测（prescribed runner）

```
$ python eval/runner.py package/out oracle/out      →  EXIT=0
```

- **`"ok": true`，68/68 项检查全部 pass**（3 项全局：units_found / products_exact / reference_dir_has_units；8 单元 × 8 项：docx_opens_safe、layout_title_centered、layout_salutation_flush_left、layout_body_indent、layout_signature_right、fields_json_self_consistent、fields_match_docx、boundary_reported；1 项聚合：field_fill_agreement_ge_90pct=100.0%（66/66））。
- 其中 `会议通知/case1` 各项（在我 RUN 2 产物上评）：opens_safe ✅、标题居中/黑体/22pt ✅、称谓顶格 ✅、首行缩进 200 ✅、落款右对齐右缩进 32pt ✅、S1–S3 自洽（11 字段）✅、字段-正文一致 ✅、缺失记账 ✅。
- 注意：runner 各检查均为**语义/版式/字段**校验，输出中**没有**对 docx 整文件字节的比对项——它验证的是「产物有效且语义确定」，不验证「字节复现」。

---

## 2. 参照实现对照（同输入连跑两遍）

`oracle/oracle.py --help`：接口与被测完全同形（`--template/--data/--outdir`）。

**同 outdir 覆盖两遍**（镜像被测协议；写到 skillfactory 之外暂存区 `D:\workspace\zcode研究\_ab5_armb_rep1_work\ref_same`，**未触碰 golden `oracle/out`**）：

| 文件 | REF RUN 1 | REF RUN 2 | 两遍是否一致 |
|---|---|---|---|
| `fields.json` | `ba9f94dd…` | `ba9f94dd…` | ✅ 一致 |
| `文书.docx` | `397c8660…` | `833516cf…` | ❌ **与被测同型：每遍哈希都变** |

**A/B 对照结论（产物确定性）**：参照与被测在确定性上**完全同型**——内容/fields 层确定，docx 整文件字节层不确定。arm-b 相对参照**无确定性回退，也无优势**，缺陷为双臂共享。

---

## 3. 根因诊断（黑盒，副本在 skillfactory 之外）

对被测连跑两遍的存活副本（`_ab5_armb_rep1_work/pkg_diag_r1 vs r2`，诊断性追加运行，07:15:52 / 07:15:54）做 zip 结构分析：

- 18 个 zip 成员：**名称、大小、CRC 全部两两相同**，逐成员解压比对**零差异**（含 `word/document.xml`、`docProps/core.xml`；core.xml 内 created/modified 恒为模板冻结值 `2013-12-23T23:15:00Z`）。
- 唯一差异 = 每个成员的 **ZIP `date_time` = 保存时刻墙钟**（07:15:52 vs 07:15:54），写入于各 local file header 与 central directory → 解释 `cmp -l` 观察到的散布单字节增量（八进制 372→373，即 DOS 时间戳字段）。
- 即：**文档内容逐字节确定；非确定性仅来自 docx 容器（zip）内嵌的写盘时间戳**。
- 被测与参照的 docx **内容不相同**（`word/document.xml`、`word/styles.xml` CRC 不同）——两实现是各自序列化，但均过 runner 全部语义检查；故 byte 级「与 oracle/out 一致」本就对双臂都不成立（oracle/out 提交版 `75892979…` 无法被参照自身复现）。
- `fields.json` 跨运行差异**仅**在自记录的绝对输出路径两行（`"docx"` / `"fields_json"`）；同 outdir 协议下逐字节一致（环境相关，非运行相关）。

**附带发现（忠实记录）**：prescribed `eval/runner.py` 在评测时**回写了被评测产物**——RUN 2 后文件 mtime 07:13:25，runner 执行后变为 07:13:59；docx 哈希 `8a24141c… → b8a0e92d…`（第 4 个字节态），`fields.json` 字节不变仅换 mtime。即工具链**所有写方**（gen_doc、oracle、runner 自身）都把墙钟写进 docx 容器；空闲后哈希稳定（间隔 3 s 两次读取一致）。

---

## 4. 卫生核验

- 全树哈希对比（运行前 vs 全部运行后）：`package/out` 其余 7 个产物单元 16 个文件**逐字节未动**；仅 `会议通知/case1/文书.docx` 变化（即本测试对象）。`oracle/out` 全程未触碰。
- 本次运行期间无其他进程扰动（`sleep 3` 前后双读哈希一致）。

---

## 5. 分层确定性判定表

| 层级 | 检验方法 | 被测 arm-b | 参照 oracle | 一致性 |
|---|---|---|---|---|
| L1 内容层（zip 成员字节 + fields.json） | zip CRC/逐成员解压比对；同 outdir 两遍 SHA256 | ✅ 确定（2/2 遍内容零差异；fields.json 3/3 态同哈希） | ✅ 确定（同型） | 同型 |
| L2 语义/评测层（prescribed runner） | `eval/runner.py package/out oracle/out` | ✅ ok:true，68/68 | （医嘱仅要求对被测执行，参照侧未跑 runner） | — |
| L3 整文件字节层（`文书.docx` SHA256） | 同输入同 outdir 连跑两遍哈希 | ❌ 不确定（gen_doc 两遍即不同：`9fabef53…` vs `8a24141c…`；算上预态与 runner 回写共 4 写 4 态） | ❌ 不确定（`397c8660…` vs `833516cf…`，同型） | 同型（同因：容器墙钟时间戳） |

---

## 6. spec D1 判定

> 因约束不可读 spec.md，D1 原文未核；以下按任务书「可分发资产的确定性交付要求」的两种读法操作化，并给出主判定。

- **主判定（严格字节级读法：同一输入重复运行产出逐字节可复现、可发布稳定校验和）**：**不满足（FAIL）**——`文书.docx` 每写一次哈希必变，分发方无法为 docx 发布可复验的 SHA256。**但该结论对参照实现同样成立**（双臂同因：zip 成员 `date_time` 取保存时刻墙钟），属共享 docx 写盘行为的系统性缺口，**非 arm-b 特有缺陷**；arm-b 与参照在全部三层上表现一致，无相对回退。
- **次级读法（内容级/评测级：重复运行文档内容与 fields 逐字节一致、评测器稳定通过）**：**满足（PASS）**——L1、L2 全过，且与参照持平。
- 佐证评测级为 harness 实际口径的旁证：runner 不含任何 docx 字节比对项，且 golden `oracle/out` 的提交版 docx（`75892979…`）连参照实现自身都无法字节复现——字节级口径下该 A/B 将双臂全灭、失去区分度。
- **修复方向（黑盒推断，未实施、未改动任何 skillfactory 文件）**：冻结 zip 写入时间戳（写 zip 时对各成员用固定 `date_time`，或等价 SOURCE_DATE_EPOCH 机制），gen_doc / oracle / runner 三处写方同改即可同时满足严格字节级 D1。

**一句话结论**：被测 arm-b 以 `package/scripts/gen_doc.py` 为唯一入口，同输入同 outdir 连跑两遍→runner `ok:true`（68/68），产物**内容级确定性成立且与参照实现完全同型**；但 `文书.docx` **整文件字节级不确定**（容器内嵌墙钟时间戳），按严格字节口径的 spec D1 **不满足**——参照实现同因不满足，属双臂共性缺口而非被测回退。

---

## 7. 附录

### 附表 A：`package/out/会议通知/case1` 全部字节态（SHA256）

| 阶段（本地时间） | fields.json | 文书.docx |
|---|---|---|
| 预状态 07:11:44（旧产物） | `f21e402b9a8962c10cab3b90874d887246e49fc4ed4eb52b274f70b4e0feb266` | `7ca17bd414bbfd65553d2f879517f97c46d8d255e9b96058385c94f16ba2f342` |
| RUN 1 后（gen_doc） | 同上（未变） | `9fabef53c2938498c64f0b436fe446568c8679f0e49206ad2b13598bac92e88a` |
| RUN 2 后（gen_doc，覆盖） | 同上（未变） | `8a24141c0e8440bdf6afcc14633a5a9f57c18372c4955b7bd3f4d4db345cfa36` |
| runner 评测后（runner 回写，07:13:59） | 同上（字节未变，mtime 变） | `b8a0e92dee07699b7c7a3f4dc4ab8be0847df496bb71a11337b23741fdbd9ed4` |

### 附表 B：参照实现各字节态

| 产物 | SHA256 |
|---|---|
| ref_same RUN 1 `文书.docx` | `397c8660388533e05ef47b777e8e4ef955c12c85688beb882f3aad6ac1810c7d` |
| ref_same RUN 2 `文书.docx` | `833516cfea4249347d9e1d75d76d5ffaec4602e617892615be38f5a052f26580` |
| ref_same RUN 1/2 `fields.json`（同 outdir，一致） | `ba9f94dd6060be30d0cf92b667998551ab7547a1081b9964446e7bdf579f87d2` |
| ref1（异目录）/ ref2（异目录）`文书.docx` | `80f3d11bdf01d54dfe1702581c9285000fc6efd4893198f8d31e0a22fe47d25a` / `4bb41ad859b5d57e248df91323ad21b6ebec73ede99626ac7e88900a81976291` |
| ref1 / ref2 `fields.json`（异目录，仅路径两行不同） | `46bf2715e26e038ade5ba7be7c22551e5e1c894eb15b65bc05bcfcaf4f97ce71` / `7b638b76b8ca82effa511a24584319f246fc78f8754337975ea38dd92e81e987` |
| golden `oracle/out/会议通知/case1/文书.docx`（未触碰，仅供参照） | `7589297917396882302d7fc4257246a33472bf5750a7751ed34a3389bb51b14b` |
| golden `…/case1/fields.json`（未触碰） | `80ed165c2e37a90b1553d2c875a2f2f14c7632b2483a8ffd3ef60f4d9b723f5b` |

### 附表 C：诊断副本（skillfactory 之外 `_ab5_armb_rep1_work\`，07:15）

- `pkg_diag_r1\文书.docx` = `5fd3d8608a7d99820cf3d7f8ed3c6d7f06d124466da5146df2c69d77c6fd494b`；`pkg_diag_r2\文书.docx` = `4108985249aca383ab56de52d80ed762f832cc7a043d9e9bf03a7619c044c424`（两个新哈希态再次印证每次写入哈希必变；两副本 zip 成员 CRC 全同、date_time 07:15:52 vs 07:15:54）
- `pkg_diag_r1/r2\fields.json` = `3895c56467adbe4bc84f2ef441b43c48dd0fe27044a5e59a5c044548f59d9097` / `ee1f1b77f0efe2cbd0928977f2cb0e5b64c57d61433fa5e3fd4a51382268550f`（异目录，差异仅 109–110 行自记录绝对路径）
- PKG vs REF docx：成员名全同；内容差异成员 = `word/document.xml`、`word/styles.xml`。

### 附：完整命令日志（按序）

```bash
cd D:/workspace/zcode研究/skillfactory/v3/assets/office-templates
python --version                                     # Python 3.12.10
find package/out -type f -print0 | sort -z | xargs -0 sha256sum     # 预状态
python package/scripts/gen_doc.py --help
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1   # RUN 1
python package/scripts/gen_doc.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir package/out/会议通知/case1   # RUN 2（覆盖复写）
python eval/runner.py package/out oracle/out          # ok:true, 68/68
python oracle/oracle.py --help
python oracle/oracle.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir <workspace>/_ab5_armb_rep1_work/ref_same   # REF RUN 1
python oracle/oracle.py --template 会议通知 --data oracle/inputs/会议通知/case1.json --outdir <workspace>/_ab5_armb_rep1_work/ref_same   # REF RUN 2（覆盖）
# 追加诊断（超出医嘱，skillfactory 之外）：gen_doc ×2 → pkg_diag_r1/r2；zip 结构与逐成员解压比对；cmp -l；fields.json diff；全树哈希卫生核验
```

### 未做 / 受限事项（如实声明）

1. 未读取 `skillfactory/` 下任何文件内容（约束）→ spec D1 原文、gen_doc/oracle/runner 实现细节均未核，接口与结论全部来自运行时行为。
2. runner 按医嘱仅执行一次，未复跑其判定稳定性；其回写产物行为由 mtime/哈希证据推得，未读源码验证。
3. 参照侧未执行 runner（医嘱的 runner 命令仅指向 `package/out`）；参照 L2 层为"未运行"，非"通过"。
4. `oracle/out` 与 `package/out` 其余 7 单元未被本次任何运行修改（全树哈希核验）。
