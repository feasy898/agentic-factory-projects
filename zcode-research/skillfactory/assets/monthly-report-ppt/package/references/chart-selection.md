# 图表选型与渲染规则

> 对应 spec.md §5（C1–C3）。三张图文件名冻结：`月度趋势.png`、`类别分布.png`、`状态占比.png`。

## 选型决策表

| 要回答的问题 | 图型 | 本技能中的落点 | 关键参数 |
|---|---|---|---|
| 随月份变化的量是多少、走向如何 | 折线 + 每点数值标注 | `月度趋势.png`：各月数量合计 | figsize (8,4.5)、dpi 150、marker=o |
| 各类别有多少条、哪个最多 | 条形图 + 数值标注 | `类别分布.png`：各类别条目数 | 同上；条目按 S3 排序（降序、同名升序） |
| 整体由哪些部分构成、各占多少 | 饼图 + 百分比标注 | `状态占比.png`：各状态条目占比 | figsize (6.4,4.8)、startangle=90、counterclock=False |
| 该维度没有任何有效数据 | 不画空坐标系，居中灰色提示文案 | 月度→「无有效日期数据」；类别→「无类别数据」；状态→「无状态数据」 | 灰 #888、16pt、axis off |

选型理由（取舍）：

- **趋势用折线不用柱**：月份是有序时间维度，折线强调连续性与走向；数值标注让汇报时不读坐标轴。
- **类别用条形不用饼**：类别数可能 >5 且需要精确比较，条形+排序天然给出"谁最多"；饼图在类别多时不可读。
- **占比用饼不用条**：状态数少、语义是"部分-整体"，百分比标注直接回答"完成了多少"。
- **排序键统一** `(−条数, 名称)`：图表横轴、PPT 表格行序、summary dict 顺序三处一致，并列时取名靠前者，杜绝"并列谁第一"的歧义。

## 中文渲染（C2）

```python
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False
```

- `axes.unicode_minus=False` **必须设置**：否则负号渲染为方块（case3 含 −3 的月度趋势是验收点）。
- 每轴中文标签（月份/数量合计/条目数），标题中文。
- 类别/月份标签过多时旋转（rotation 25–30 并右对齐），避免重叠。

## 确定性（PNG 字节级可复现）

1. matplotlib 用 **Agg** 后端（无显示环境也可运行，且输出确定）。
2. `savefig(..., metadata={"Software": None})`——不写任何 metadata 块（去掉版本号等环境差异）；PNG 本身不含时间戳。
3. figsize/dpi/颜色/线宽全部常量，不依赖状态。

## PPTX 确定性清单（spec D2）

python-pptx 保存的 zip 默认带当前时间戳，必须归一化：

1. `core_properties` 全部写死常量：author/last_modified_by/title/revision 固定，`created=modified=datetime(1980,1,1)`，注释/关键词置空。
2. 保存后**重写 zip**：所有条目 `date_time=(1980,1,1,0,0,0)`、统一 `create_system=0`、固定 `external_attr`，按原条目顺序重打包。
3. 写最终文件遇 PermissionError（Windows 文件占用）允许有限次重试——只影响时机，不影响内容。
4. 验收：同输入连跑两次，5 个产物 md5 逐一相同。
