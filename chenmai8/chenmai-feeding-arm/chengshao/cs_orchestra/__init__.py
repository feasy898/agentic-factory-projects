"""编排包：行为树（50Hz tick）——选碗→舀取→勺上检查→送达→等咬合→撤回→记录，
高优先级打断分支：急停/禁入区/转头/人脸丢失/暂停/吃饱了/皱眉。
黑板键冻结（v1.1）：mouth / arm_state / safety / spoon / intent / session /
bowl_sel / camera_role（"scene"|"wrist_mouth"，腕部双职角色开关：
"勺上检查通过→开始送达"置 wrist_mouth，"撤回完成/急停/中止"回 scene）。
"""
