"""编排包：行为树（进食全流程 + 安全打断分支），开发指令 §5.6。

消费各模块契约接口（全部注入式依赖，见 :mod:`.core.Deps`）：cs_arm（MockArm +
SafetyEnvelope 硬闸）、cs_sim（FK/包络）、cs_mouth（口部三维，经 :mod:`.runtime`
的腕部双职通道）、cs_food（勺上检查/选碗）、cs_voice（语音意图/播报）、
cs_dashboard（口记录 HTTP sink）、cs_schema（契约模型与冻结常量）。

主序列（每口）::

    选碗 → 舀取（Scoop：参数化轨迹 + 腕部相机闭环检查，失败重舀 ≤2）
    → 勺上检查通过 → 发 camera_role 切换事件（scene→wrist_mouth，等曝光
    稳定 500ms 后才采口部帧；口部坐标经 cam_pose=(FK×腕部手眼) 换算基座系、
    IPD 瞳距估距——由 cs_mouth.MouthEstimator 的 v1.1 契约承载）→ 限速送达
    （IK+包络，至包络送达停点，停点在禁入球外、口前 5cm 叙事）→ 等咬合
    （几何口径比 jaw_open：张嘴→咬合→闭嘴）→ 勺空确认 → 撤回（撤回完成回
    scene）→ 写 BiteRecord。

状态转移表（打断分支 = root Selector 高优先级分支，自上而下；
tests/test_orchestra.py 逐条断言）::

    | #  | 触发（每 tick 检查）                      | 动作                                                            | 结局 |
    |----|------------------------------------------|----------------------------------------------------------------|------|
    | S1 | 软件急停（estop 源 latch 包络）           | 立即停 → camera_role→scene(estop_abort) → 本口记 aborted →       | 本口 |
    |    |                                          | 操作员 envelope.reset() → 原路退回+回家 → "继续/下一口" 恢复下口 | aborted |
    | S2 | 禁入区违规（violation=face_in_zone）      | 冻结（包络已 latch）→ camera_role→scene(zone_abort) → 本口记     | 本口 |
    |    |                                          | aborted → 侵入解除 reset() → 原路退回+回家 → "继续/下一口" 恢复  | aborted |
    | S3 | 语音"吃饱了"（done）                      | 本口记 rejected → 播报 → 撤回（完成沿回 scene, done_retract）    | 会话 |
    |    |                                          | → 结束会话（root 收敛）                                          | DONE |
    | S4 | 语音"等一下"（pause）                     | 保持悬停（在途段自然完成，不再下发新段）+ 播报 → resume 恢复     | - |
    | S5 | 转头（|head_yaw|>25°）或人脸丢失 >1s      | 保持 + 播报一次 → 姿态正常后原地恢复（仅 wrist_mouth 角色下      | 送达/ |
    |    | （仅送达/等待阶段检查）                   | 检查；等待咬合超时 25s → 本口记 rejected + 撤回）                | 等待段 |
    | S6 | 皱眉（frown>0.5）                         | 暂停 + 语音询问 → frown 回落或 resume 继续                       | - |
    | S7 | 语音"下一口"（next）                      | 等待咬合两阶段中：跳过等待，本口记 rejected 撤回；他阶段同 resume | 拒食 |
    | S8 | 张嘴触发（待机段）                        | v3.1 运行期口部职责在腕部（送达/等待），待机段该信号通常缺席，   | - |
    |    |                                          | 自动续口（RECORD 完成即开下一口）为默认驱动                      |      |
    | S9 | 语音 select（我想吃X）                    | 更新点菜偏好（菜序 → 碗序，下口选碗生效）                        | - |
    | S10| 舀取+勺上检查重舀 ≤2 次后仍空             | 本口记 retry，不进送达（camera_role 保持 scene，0 次切换）       | 会话继续 |
    | S11| 等咬合闭嘴等待超时（25s 未张嘴）          | 本口记 rejected + 撤回                                           | 超时 |
    |    |                                          |                                                                  | rejected |
    | S12| 咬合后勺不空（限次复检仍不空）            | 本口记 rejected + 撤回                                           | rejected |

camera_role 时序（契约 v1.1 冻结）：进送达的口**恰 2 次**——勺上检查通过→
开始送达前 scene→wrist_mouth（delivery_entry）；撤回完成/急停/禁入区中止/
"吃饱了"撤回完成时 wrist_mouth→scene（retract_complete/estop_abort/
zone_abort/done_retract，先发生者）。未进送达的口（S10）保持 scene、0 次
切换。切换事件全部写入 trace（reports/orchestra_trace.jsonl）供审计。

黑板键（冻结 §3.2/§5.6）：mouth / arm_state / safety / spoon / intent /
session / bowl_sel / camera_role。

tick 循环由 :class:`.nodes.MealRunner` 驱动（50Hz 仿真时钟）：感知更新
（arm.read / envelope.poll / mouth 采样 / voice.poll）→ tree.tick_once()。
全部节点按 ctx 相位幂等（进度只存在于 TickContext，选择器抢占/复位后原地
恢复）；打断型事件在 root Selector 高优先级分支处理（S3/S4/S5/S6/S7/S9 于
InteractionGate，S1/S2 于 SafetyGate）。

包结构：
- :mod:`.core`    运行参数 / trace / 相机角色台账 / 单口状态机 / 臂服务 / 路线跟随；
- :mod:`.nodes`   行为树全节点（py_trees）+ MealRunner tick 循环；
- :mod:`.mock`    mock 依赖注入（脚本化用户/场景/勺检/语音/记录池）+ 回合驱动；
- :mod:`.runtime` 生产接线（消费 cs_mouth/cs_food/cs_voice/cs_dashboard 契约）；
- :mod:`.eval`    mock 验收（30 回合 + camera_role 每口恰 2 次切换时序断言）。

验收 eval（§5.6 + v3.1 增补）::

    python -m cs_orchestra.eval --mock --episodes 30 --report reports/orchestra_eval.json
    # 仓库根亦可用：python -m chengshao.cs_orchestra.eval --mock 30
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[1]  # .../chengshao
_REPO_ROOT = _PKG_ROOT.parent  # 仓库根

for _p in (str(_REPO_ROOT), str(_PKG_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _alias(pkg: str) -> None:
    """把 chengshao.<pkg>（或已存在的 <pkg>）注册为顶层 <pkg> 别名（与 cs_arm 一致）。"""
    if pkg in sys.modules:
        return
    for modname in (f"chengshao.{pkg}", pkg):
        try:
            sys.modules[pkg] = importlib.import_module(modname)
            return
        except ImportError:
            continue
    raise ImportError(f"cs_orchestra: cannot import contract package {pkg!r}")


for _pkg in ("cs_schema", "cs_sim", "cs_arm"):
    _alias(_pkg)

from .core import (  # noqa: E402
    ArmService,
    BitePhase,
    BiteState,
    CameraRoleLedger,
    Deps,
    OrchestraParams,
    RouteFollower,
    STATE_TRANSITION_TABLE,
    TickContext,
    Trace,
    WRIST_PHASES,
    flange_pose_mat,
    load_t_flange_cam,
    quat_to_mat,
)
from .mock import (  # noqa: E402
    SPEC_MEAL_BITES,
    SPEC_MEAL_EXPECTED_OUTCOMES,
    SPEC_MEAL_SCRIPT,
    MemorySink,
    MockScoop,
    ScenarioDriver,
    ScriptState,
    ScriptedVoice,
    make_mock_episode,
)
from .nodes import (  # noqa: E402
    Deliver,
    InteractionGate,
    MealRunner,
    RecordBite,
    Retract,
    SafetyGate,
    Scoop,
    SelectBowl,
    SessionGuard,
    SpoonCheckGate,
    SpoonEmptyConfirm,
    WaitBite,
    build_tree,
)
from .runtime import (  # noqa: E402
    HttpDashboardSink,
    SceneBowlScanner,
    ScriptedScoop,
    VoiceBusLink,
    WristMouthChannel,
    WristSpoonSource,
)

__version__ = "1.0.0"

__all__ = [
    # core
    "ArmService",
    "BitePhase",
    "BiteState",
    "CameraRoleLedger",
    "Deps",
    "OrchestraParams",
    "RouteFollower",
    "STATE_TRANSITION_TABLE",
    "TickContext",
    "Trace",
    "WRIST_PHASES",
    "flange_pose_mat",
    "load_t_flange_cam",
    "quat_to_mat",
    # nodes
    "MealRunner",
    "SafetyGate",
    "InteractionGate",
    "SessionGuard",
    "SelectBowl",
    "Scoop",
    "SpoonCheckGate",
    "Deliver",
    "WaitBite",
    "SpoonEmptyConfirm",
    "Retract",
    "RecordBite",
    "build_tree",
    # mock
    "SPEC_MEAL_BITES",
    "SPEC_MEAL_EXPECTED_OUTCOMES",
    "SPEC_MEAL_SCRIPT",
    "MemorySink",
    "MockScoop",
    "ScenarioDriver",
    "ScriptState",
    "ScriptedVoice",
    "make_mock_episode",
    # runtime
    "HttpDashboardSink",
    "SceneBowlScanner",
    "ScriptedScoop",
    "VoiceBusLink",
    "WristMouthChannel",
    "WristSpoonSource",
]
