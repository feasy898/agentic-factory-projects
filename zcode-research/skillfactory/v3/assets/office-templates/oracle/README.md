# oracle —— 四类中文办公文书参照生成器

用 python-docx 按 GB/T 9704 风格版式生成四类中文事务文书，并输出字段填充台账（fields.json），
作为评测候选文书生成能力的 oracle（参照实现）。

## 运行

```bash
python oracle.py --template <周报|请示函|会议通知|工作总结> --data <json> --outdir <dir>
```

- 产物：`<outdir>/文书.docx` + `<outdir>/fields.json`
- 退出码：0 = 产物写出成功（必填缺失属数据边界，如实记录不报错）；2 = 模板名非法 / 数据文件缺失 / JSON 非法 / 数据非对象
- 依赖：`pip install python-docx`

## 版式规范（oracle.py 实现，verify.py 校验）

| 规范 | 实现 |
|---|---|
| 标题居中 | 黑体二号（22pt），居中 |
| 称谓顶格 | 无首行缩进，段首即主送对象 |
| 正文首行缩进两字符 | `w:firstLineChars=200` + `w:firstLine` twips 兜底，三号仿宋（16pt），固定行距 28 磅 |
| 落款右对齐 | 右对齐 + 右空两字（单位/署名 + 日期两行） |
| 页面 | A4，版心 上3.7/下3.5/左2.8/右2.6 cm |

## 字段语义

- 必填缺失/空 → 文中 `____` 占位（列表字段渲染占位条目），fields.json 记 `missing`（required=true）
- 选填缺失/空 → 行内字段留空；独立条目/小节省略，fields.json 记 `missing`（required=false）
- 模板外多余键 → `summary.unknown_keys`
- 列表字段接受字符串（视为单项）或字符串数组

## 样例与校验

```bash
# 8 份样例（每类 2 份，case2 含必填缺失等边界）全部生成
for t in 周报 请示函 会议通知 工作总结; do for c in 1 2; do
  python oracle.py --template "$t" --data "inputs/$t/case$c.json" --outdir "out/$t/case$c"
done; done

# 版式不变量 + fields.json 自洽性校验（PASS=8 退出码 0）
python verify.py
```

## 各模板字段

- **周报**：部门\*、填报人\*、周期\*、本周工作内容\*(列)、下周工作计划\*(列)、问题与需协调事项(列)、报送日期
- **请示函**：请示事由\*、主送机关\*、请示缘由\*、请示事项\*、请示单位\*、联系人、联系电话、成文日期
- **会议通知**：会议名称\*、召开单位\*、主送对象\*、会议时间\*、会议地点\*、参会人员\*、会议议题、会议要求(列)、联系人、联系电话、发文日期
- **工作总结**：总结主体\*、总结时段\*、工作回顾\*(列)、主要成绩\*(列)、存在问题(列)、下一步工作打算\*(列)、成文日期

（\* = 必填；实测环境 python-docx 1.2.0 / Windows x64 / Python 3）
