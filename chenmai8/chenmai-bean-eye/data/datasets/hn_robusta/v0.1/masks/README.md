# masks/ — HN-Robusta v0.1 二值掩码

与 `../images/` 同名同相对路径的 8-bit {0,255} 二值掩码（自动提取→人工修正，
流程与质量门槛见 `docs/collect_protocol.md` §4）；掩码数必须等于图中豆数。
生成/抽检/修正命令：`scripts/collect_masks.py`（extract / iou / poly2mask，
操作步骤见 `docs/采集操作卡-v0.1.md` §6）。数据不入 git。
