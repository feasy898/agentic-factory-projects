# M6 上下配对 spec（pairing · 两遍算法与阈值）

> 状态：冻结·已知回归（主路径 eval 全绿；密排统计 3 例确定性失败，见 §7）。
> 本页对照 `beaneye/pairing/hungarian.py` 与 `tests/test_pairing.py` 逐行核验于 2026-09-29。
> 定位：把 top/bottom 两面观测还原成「一粒豆」——配对错一粒，缺陷计数就错一粒。

---

## 1. 职责与边界

**做**：输入 top/bottom 两组 `BeanObservation`（质心已在盘面 mm 坐标系，M3 变换后），
代价 = 质心欧氏距离，门限 12mm，哑节点匈牙利全局最优（**「不配对」是一等选项**），
两遍整体配准残差矫正，单面豆一等保留，输出 `PairedBean` 列表（bean_id 稳定可复现）。

**不做**：不做任何类别/严重度判断（那是 M7）；不做亚门限相似度二次确认；
不处理非欧代价（v1 仅距离；`PairingConfig` 只有一个字段 `gate_mm`，后续加权只增字段）。

## 2. 魔法数字表（改任何一个都要回填本页并复跑 eval）

| 常量 | 值 | 位置 | 语义 |
|---|---|---|---|
| `DEFAULT_GATE_MM` | 12.0 | hungarian.py | 配对门限（mm）；**含等号**：`dist <= gate` 视为可配对；`PairingConfig` 校验正有限数 |
| `_DUMMY_EPS` | 1e-6 | hungarian.py | 哑节点代价 `lambda = gate + eps`——让「恰在门限上的对」严格优于双双落单 |
| BIG（inf 占位） | `lam × (n+m+1)` | `_solve_assignment` | scipy 的匈牙利在代价含 inf 且无避开 inf 的完全匹配时抛 `ValueError: cost matrix is infeasible`（.venv scipy 1.18.1 实测：两条 top 观测都只落进同一 bottom 的门限圈即触发）。用足够大的有限占位 + 哑节点保证恒可行，最优解不会取到 BIG 项 |
| 哑-哑块 | 整体置 0 | `_solve_assignment` | **只在对角置 0 是错的**：多余哑行与空闲哑列未必对角对齐（top 列表位置 ≠ bottom 列表位置），碰撞会逼最优解拆散真对以回避 BIG——实测修复过的坑 |
| `_REG_MIN_PAIRS` | 8 | hungarian.py | 粗配对少于 8 对不估配准残差（样本太少中位数不可信；`robust_shift_mm` 自身样本 <4 返回 None） |
| `_REG_MIN_SHIFT_MM` | 1.0 | hungarian.py | 成对位移中位数的模 <1mm 视作噪声，不触发第二遍 |

## 3. 两遍算法（整体配准残差矫正）

**为什么需要两遍**：上下两面标定若存在整体平移（eval 的 5mm 场景），真对距离被系统性拉大、
近邻错对反而更近，纯逐对距离不可分辨。

```
第一遍：_solve_assignment(txy, bxy, gate)            # 常规哑节点匈牙利
第二遍触发条件：粗配对 ≥8 对 且 |mu| = hypot(mu_x, mu_y) ≥ 1.0mm
    mu = 逐分量中位数( top质心 − bottom质心 )        # 对少数错配/伪观测鲁棒
    corrected = _solve_assignment(txy − mu, bxy, gate)
替换守卫：corrected 非空 且 _second_pass_wins(...) 才替换
```

**劣化守卫 `_second_pass_wins`（严格变优才替换）**：把第一遍的配对也放到矫正坐标系
（top − mu）下重算距离，两解同坐标系下按字典序比较——**先比对数（多者优先），再比总距离
（小者优先，round 9 位防浮点抖动）**；不变优（含完全相等）即保留第一遍。
没有守卫时，「中位数锁错模」的第二遍会把本来就对的配对改坏（W13 修复前真实发生过）。

**已知极限（如实记录）**：若多数观测呈规则点阵且偏移接近点阵间距的整分数，中位数会锁到
错误模式——守卫只能阻止第二遍变差，不能修正第一遍已锁错的方向。密排盘（间距 ≤8mm、
≥300 粒）恰接近该构型；本仓演示/评测默认稀疏盘（Mock 摆豆间距系数 1.15×半径和，不粘连）。

**pairing_cost 语义**：返回**配对判定坐标系**下的距离（无残差=原始欧氏距离；有残差=矫正后
距离，两者相差 ≤|mu|）。

## 4. 输出契约

- **单面豆**（遮挡/边缘漏检/丢面/伪观测）：单独成记录，`pairing_cost=-1`、
  `worst_side`=所在面（契约 `PairedBean` 校验器强制单面 cost 恒 -1、双面 cost ≥0）。
- **bean_id 稳定序**：每条记录挂锚定观测（top 优先，缺则 bottom），按锚定质心 `(x, y)` 升序、
  `obs_id` 兜底打破并列，顺序编号 `b0001..`——同输入必同输出。
- **输入校验**（`PairingError`）：列表内 side 不符 / obs_id 重复 / gate 非正非有限。
- `summarize()` → `PairingSummary{n_beans, n_paired, n_top_only, n_bottom_only}`（M8/M14 用）。

## 5. 与契约的衔接

输出经 `PairedBean.from_sides` 构造——契约校验器当场重跑 `_resolve_worst` 裁决
（见 [severity](severity.md)），配对层不写 final_* 字段，从根上杜绝两面不一致。

## 6. 复杂度与实测

哑节点法矩阵规模 (n+m)²；200 粒盘全流程 0.015s（≫1s 通过线余量充足）。
统计场景实测（合成观测，非现场承诺，口径见 docs/calibration-error-budget.md §3）：
基线 200 粒 σ=3mm、10% 丢面、5% 伪观测 → P 0.989 / R 0.994；5mm 整体平移 → P 0.995 / R 1.0。

## 7. eval 与已知回归（2026-09-29）

```bash
python -m pytest tests/test_pairing.py -q
# → 2026-09-29 实测：24 passed / 3 failed
```

| 失败用例 | 现象 | 根因（如实记录） |
|---|---|---|
| `test_statistical_dense_324_beans_pitch8mm` | precision 0.8818 < 0.90 回归下限（recall 0.919 ≥0.85 达标） | 提交 `943d8cc` 把随机源从标准库 random 切到 numpy `default_rng`——**种子值未变但随机流变了**，密排场景实例随之改变，precision 跌破下限 |
| `test_statistical_dense_rotation_perspective_residual` | 同上（密排 + 旋转/透视残差构型） | 同上；构型本身是 §3 已知极限的高压区 |
| `test_statistical_dense_small_offset_triggers_second_pass_safely` | 同上（小偏移第二遍安全） | 同上 |

修复归属 M6 属主（改算法或改场景钉线），本 spec 只记录不代改。该 3 例失败会传导
gate_d2 门项 ②③（M6 入口 FAIL）——复跑门禁前先看本节，避免误判为环境问题。
