"""冻结常量：结构尺寸、默认阈值与预注册词表。

只放结构与默认值；运行期可调参数一律从 config/ 装载（开发指令 §10.4）。
契约冻结（v1.0，2026-09-28）：常量名与语义只增不改。
"""

from __future__ import annotations

# ---- 结构尺寸（§3.1 冻结） -------------------------------------------------
N_ARM_JOINTS = 7  # 7 关节 = 6 个臂关节 + 1 个末端夹爪关节，统一编入数组
EE_POS_LEN = 3  # ee_pos：base 系位置 [x, y, z]，单位米
EE_QUAT_LEN = 4  # ee_quat：单位四元数 [w, x, y, z]（w 在前）
CARTESIAN_TARGET_POS_ONLY = 3  # cartesian 目标：仅位置（姿态保持）
CARTESIAN_TARGET_FULL = 7  # cartesian 目标：3 位置 + 4 四元数

# ---- 感知默认阈值（可被 config/ 覆盖；此处为缺省值） -----------------------
MOUTH_PRIOR_DEFAULT_M = 0.42  # 无深度时口部距离先验（config/mouth_prior.json 缺省）
JAW_OPEN_THRESHOLD = 0.35  # jaw_open > 此值判"张嘴"
HEAD_YAW_TURN_THRESHOLD_RAD = 0.4363  # head_yaw > 25° 判"转头"
FROWN_ASK_THRESHOLD = 0.5  # frown > 此值触发暂停+询问

# ---- 预注册菜名表（VoiceIntent select 的 dish 缺省词表，config 可扩展） ----
DEFAULT_DISH_REGISTRY: tuple[str, ...] = ("芋泥", "南瓜粥", "椰子冻")
