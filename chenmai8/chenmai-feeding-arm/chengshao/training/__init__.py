"""训练资产包（chengshao.training）——延后训练任务的全部脚本+配置（workflow T11）。

**只写不跑**：本包在本机构建期只做参数解析 / 路径检查 / dry-run 验证；
真实训练一律在 GPU 机（anolis-gpu-01）执行，且仅当延后的策略训练立项后启动
（开发指令 §10.3、plan/training-plan.md——仓库外）。

布局：
    act/         策略训练命令生成器（对接训练框架 CLI，入口名运行期注入）
    spoon_cls/   勺上分类器：帧数据导出/自动标注 → 训练 → ONNX 导出 → 评测
    transfer/    COS 中转（7z 分卷 + coscmd 上/下行）
    record/      拖动示教录制（无主臂方案的采数脚本，输出回合原始格式）
    config/      训练配置（结构与默认值；入口名等运行期注入项不入库）
    requirements-gpu.txt   GPU 机依赖清单（机器可读声明，按命名纪律豁免扫描）
    runbook_act.md / runbook_gpu.md   操作手册

命名纪律：仓库文本用中性名「训练框架」指代 requirements-gpu.txt 声明的
策略训练依赖栈；其 CLI 入口名不写入仓库（scripts/check_naming.py 把关），
经 --train-cmd / 环境变量 CS_TRAIN_CMD / config/train.local.json（gitignore）注入。
"""
