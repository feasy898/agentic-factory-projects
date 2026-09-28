"""受控词表：跨模块共享的全部枚举。

契约冻结（v1.0，2026-09-28）：成员值一经冻结不得改名/改值/删除，只能追加。
字段声明处使用本模块枚举；其字符串取值即对外 JSON 字面量（StrEnum）。
"""

from __future__ import annotations

from enum import StrEnum


class MouthSource(StrEnum):
    """MouthPose.source：口部坐标的来源后端。"""

    DEPTH = "depth"  # 深度相机像素反演
    MONO = "mono"  # 单目 + 距离先验（config/mouth_prior.json）


class CommandMode(StrEnum):
    """ArmCommand.mode：指令目标空间。"""

    JOINTS = "joints"  # target = 7 关节目标（rad）
    CARTESIAN = "cartesian"  # target = base 系位姿（3 位置或 3+4 全量）


class CommandFrame(StrEnum):
    """ArmCommand.frame：指令参考系。MVP 冻结为 base 系。"""

    BASE = "base"


class ViolationKind(StrEnum):
    """SafetyState.violation：安全违规类别。

    任何非 NONE 取值都必须令 clear_to_move=False，直到显式 reset()。
    """

    NONE = "none"
    FACE_IN_ZONE = "face_in_zone"  # 禁入区（用户面部球域/躯干胶囊）侵入
    SPEED = "speed"  # 超速
    TORQUE = "torque"  # 力矩越限
    WATCHDOG = "watchdog"  # 看门狗：断连/心跳丢失/急停


class IntentKind(StrEnum):
    """VoiceIntent.intent：语音意图词表（四指令 + 选菜 + 迎宾 + 未识别）。"""

    NEXT = "next"  # 下一口
    PAUSE = "pause"  # 等一下/暂停
    RESUME = "resume"  # 继续
    DONE = "done"  # 吃饱了
    SELECT = "select"  # 我想吃 X（slots["dish"] ∈ 预注册菜名表）
    GREET = "greet"  # 迎宾/唤醒
    UNKNOWN = "unknown"  # 未识别


class BiteOutcome(StrEnum):
    """BiteRecord.outcome：单口结局。"""

    SUCCESS = "success"  # 咬走，正常完成
    RETRY = "retry"  # 勺上检查未过，重舀
    REJECTED = "rejected"  # 用户拒食（转头/皱眉/语音拒绝）
    ABORTED = "aborted"  # 急停/异常中止
