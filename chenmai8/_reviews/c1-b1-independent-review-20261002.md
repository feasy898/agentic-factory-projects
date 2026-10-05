# C1-B1 bring-up 脚本包 · 独立复核记录（2026-10-02）

> 性质：只读独立评审（S-评审角色），对象为 tag `sw-b1-bringup-v1.0` 交付的
> bring-up 脚本包（calibrate_handeye / camera_check / safety_drill / cs_arm.eval_hw /
> cs_arm.eval_scoop + tests/test_hw_toolchain.py）。评审在进入 G1 全量门禁前完成，
> 结论 needs_fix → 修复后复跑门禁。本文件为复核结论与修复状态的留痕。

## findings（按严重度）

### [high] 失败标定会落 config/calib/ 被静默装载 —— 已修（2026-10-02）

- 位置：`chengshao/scripts/calibrate_handeye.py` main() npz 落盘段（原 :500-521），
  对照 `chengshao/cs_orchestra/core.py:99-111` load_t_flange_cam。
- 问题：np.savez 执行于 passed 判定之前；真机缺省 out_path=config/calib/；
  装载端只要 npz 存在且含 T_flange_cam 即返回，不校验 reproj_err_mm/pass 线。
  失败外参一旦落默认路径 → 腕部口部链路静默采用 → 口部基系坐标错 → 禁入区锚错位。
- 修复：passed 判定前移；未过线时（缺省真机路径 / --out 显式指向 config/calib/）
  一律改道 `reports/handeye_<cam>_failed.npz` 暂存并打印警告；mock 缺省仍写 reports/。
- 回归：`tests/test_hw_toolchain.py::test_calibrate_handeye_failed_line_not_written_to_config_calib`
  （monkeypatch 未过线结果，断言 config/calib/ 不落盘、暂存路径落盘）。
- 复核确认：运行输出含"拒绝写入 config/calib/，改落暂存路径"警告，22/22 用例绿。

### [low] eval_scoop 混合食物时参数来源失真 —— 已修（2026-10-02）

- 位置：`chengshao/cs_arm/eval_scoop.py` _run_mock 食物循环（原 :385-389）。
- 问题：`cfg = cfg if food in cfg.foods else cfg_builtin` 把 cfg 永久替换为内置兜底；
  混合"未注册食物+注册食物"时后续注册食物实际用内置卡，却被标注
  `config:scoop_params.json:card_present`——来源失真且配置卡数值被静默忽略。
- 修复：逐食物局部 cfg_food，不再改全局 cfg。
- 备注：今日"未注册食物"入口是 ValueError fail-closed，实际触发面是自定义
  config 注册子集 + DEFAULT_DISH_REGISTRY 的混合调用；缺省三食物不受影响。

### [low] camera_check 模块 docstring 表述过强 —— 已修（2026-10-02）

- 位置：`chengshao/scripts/camera_check.py` 模块 docstring（原 :7）。
- 问题：宣称 --mock"合成图像走同一检测与断言链"，但面部可辨项 mock 用暗斑连通域
  计数器、真机用 Haar 级联，检测器不同（其余三项指标函数确为共用）。
- 修复：docstring 订正为"同一断言链（面部可辨项检测器差异见函数级 docstring）"。

### [low] hw-toolchain spec 状态过时 —— 已修（2026-10-02）

- 位置：`docs/assets/specs/hw-toolchain.md` 序言（原 :5）。
- 问题：B1 之后"§3 清单中的真机 eval 命令当前均无实现入口"已过时。
- 修复：更新为"B1 已交付（mock 全绿 + 真机分支 fail-closed），真机 eval 结论待
  T10 硬件 bring-up 实测"，并附本次复核修复记录。

## 复核方法

只读代码与 spec（hw-toolchain / cs_arm / 开发指令 §5.9 与 §9），对照证据 JSON；
高危项 1 条经独立复核员二次确认（复现代码路径成立）；修复后以全量测试 + G1 门禁复跑验收。

## 未覆盖

- 真机 eval 结论（无硬件）：mock 只验证代码路径，真机数字以 3060 bring-up 实测为准。
- 09-29 轮 feeding-arm-review.md 中关于安全模型自证（eval 自采样自评分、IK 按构造
  可达、关节轨迹未弦检、停点与禁入球关系）的高危项为既有问题，B1 未触碰其修复面；
  3060 侧真机送餐前必须按该评审的修复清单先行处理（本包的安全断言只到
  "SafetyEnvelope+MockArm 注入违规被 100% 拒绝"这一层）。
