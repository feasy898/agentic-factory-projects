"""执行包：机械臂接口抽象 + Mock 臂（仿真内速度受限积分）+ 真机串口通道 + 安全包络执行器。

安全包络执行器包装任意 ArmInterface：限速 / 禁入区 / 急停锁存 / 看门狗。
一切 ArmCommand 只能经 SafetyEnvelope 下发到底层（契约 §3.1 SafetyState）。
"""
