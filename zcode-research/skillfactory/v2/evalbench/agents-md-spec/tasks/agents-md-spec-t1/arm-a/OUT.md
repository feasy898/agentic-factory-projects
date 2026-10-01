# 修复数量折扣边界 bug（满 10 件应享 9 折）

仓库约束（根 AGENTS.md）：改动前跑 `pytest -q` 确认基线全绿、改动后再跑一次；禁止引入新第三方依赖；commit message 用 `type(scope): subject`。

## 一、Bug 定位

`shop/utils.py` 第 4 行 `elif quantity > 10:` 与 docstring「满 10 件 9 折」矛盾：**恰好 10 件**时落入 `else` 分支按原价结算（rate=1.0），而「满 10 件」语义应为 rate=0.9。

- 实测复现：`discount(100, 10)` 返回 `1000.0`，期望 `900.0`。
- 现有测试 `discount(100, 5) == 500.0` 未覆盖 10 件边界，故基线仍绿、bug 长期潜伏。
- 50 件边界（`>= 50`）与「满 50 件」语义一致，无需改动。

## 二、执行计划（符合 AGENTS.md 工作流）

1. 运行 `pytest -q`，确认基线全绿（AGENTS.md：任何代码改动前）。
2. 在 `tests/test_discount.py` 新增回归测试 `test_discount_exactly_ten_items`（断言 `discount(100, 10) == 900.0`），跑一次确认它 **FAIL**——先让测试钉住 bug。
3. 修改 `shop/utils.py`：`quantity > 10` → `quantity >= 10`（单行改动；只用现有代码，不引入任何新依赖，符合 AGENTS.md 依赖红线）。
4. 再次运行 `pytest -q`，确认新旧测试全部通过。
5. 按 Conventional Commits 格式提交（message 见第四节）。

计划五步均已实际执行，命令与输出见第五节验证记录。

## 三、修复后的代码与新增回归测试

### shop/utils.py（修复后全文）

```python
def discount(price, quantity):
    """数量折扣：满 10 件 9 折，满 50 件 8 折。"""
    if quantity >= 50:
        rate = 0.8
    elif quantity >= 10:
        rate = 0.9
    else:
        rate = 1.0
    return round(price * quantity * rate, 2)
```

唯一改动：第 4 行 `> 10` → `>= 10`。

### tests/test_discount.py 新增回归测试

```python
def test_discount_exactly_ten_items():
    assert discount(100, 10) == 900.0
```

断言值推导：`100 × 10 × 0.9 = 900.0`（修复前实际返回 `1000.0`）。

边界值实测表（price=100，修复后逐点验证）：

| quantity | 结果 | 预期档位 |
|---|---|---|
| 5 | 500.0 | 原价（现有测试覆盖点） |
| 9 | 900.0 | 原价 |
| 10 | 900.0 | **9 折（原 bug 点，已修复）** |
| 11 | 990.0 | 9 折 |
| 49 | 4410.0 | 9 折 |
| 50 | 4000.0 | 8 折 |
| 51 | 4080.0 | 8 折 |

## 四、Commit message（Conventional Commits：type(scope): subject）

```
fix(shop): apply 10% discount at exactly 10 items (change > 10 to >= 10)
```

## 五、验证记录（本次任务实际执行的命令与输出）

- 环境：Python 3.12.10 + pytest 9.1.1（Windows x64）。
- **如实说明**：任务只提供文件内容，磁盘上不存在原仓库；我在 `C:\Users\Administrator\AppData\Local\Temp\agents-md-t1-repro\` 按任务原文逐字重建最小仓库（AGENTS.md、shop/utils.py、tests/test_discount.py），并在其中实际执行了 AGENTS.md 工作流。两处脚手架补齐（不影响被测代码）：① 空根级 `conftest.py`，使 `pytest -q` 能解析 `from shop.utils import discount`；② 测试文件的导入行（任务摘录未含，任何可运行的测试都必需）。
- `pytest -q`（改动前，仅原测试）→ `1 passed in 0.35s`（基线全绿 ✓）
- 新增回归测试后 `pytest -q` → `FAILED tests/test_discount.py::test_discount_exactly_ten_items - assert 1000.0 == 900.0 / 1 failed, 1 passed in 2.82s`（bug 实锤）
- 一行修复后 `pytest -q` → `2 passed in 0.22s`（全绿 ✓）

## 六、ASSET-DOC 使用说明

已完整读取 `ASSET-DOC.md`（agents.md 官网 + 官方仓合并条目）并按其方法执行：AGENTS.md 是仓库对 agent 的约束文件，其列出的测试命令必须实际运行并修复失败（FAQ：「会自动执行测试吗？会」）；官方示例明言「Add or update tests for the code you change, even if nobody asked」——回归测试据此添加；提交遵守文件内规范。ASSET-DOC 与本任务**无冲突**，故无需按任务要求作冲突注明（本节仅为合规说明）。就近约束原则下，本仓库根 AGENTS.md 为有效约束；工作区根 `D:\AGENTS.md` 是本机路书，与本任务无冲突。
