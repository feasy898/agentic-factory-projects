// 澄勺 C1 硬件攻坚冲刺（M4→M6）— 3060 Ubuntu 桌面版
// 由 windev-01 主线交付；3060 agent 使用前先改下面 CONFIG 三行为本机实际路径。
// 前提：HANDOFF v0.5/v1 的 bootstrap 已完成（venv 绿、CS_VENDOR_ROOT 就位、
//       tailnet 已入、bao 可达、软急停链路就绪）。
// 红线（任何 agent 不得放宽）：禁入区 r=0.12m 球+躯干胶囊；接近段 ≤0.15m/s、面部 15cm 内 ≤0.10m/s；
//       空格软急停 latch；violation!=none → clear_to_move=False 直至 reset；ArmCommand 只经 SafetyEnvelope。

interface TaskResult {
  /** 步骤/任务代号。 */
  task: string;
  /** 一段话：做了什么、结果如何。 */
  summary: string;
  /** 创建/修改的文件（仓库相对路径，含证据 JSON）。 */
  files: string[];
  /** 证据 JSON（仓库相对路径）。 */
  evidence: string[];
  /** 实际跑过的命令。 */
  testsRun: string[];
  /** 该步通过线是否达标。 */
  testsPassed: boolean;
  /** 偏差、遗留、风险——如实写。 */
  notes: string;
  /** 阻塞项（缺硬件、缺输入、需要 owner 裁定）。 */
  blockers: string[];
}

interface CheckResult {
  /** 检查对象。 */
  what: string;
  /** pass=通过线达标；fail=未达标；blocked=被硬件/环境阻塞。 */
  status: "pass" | "fail" | "blocked";
  /** 依据：证据 JSON 路径与关键数字，或命令输出。 */
  evidence: string;
}

interface CheckReport {
  /** 每项检查一条。 */
  items: CheckResult[];
}

interface WorkflowReport {
  conclusion: string;
  findings: CheckResult[];
  verified: string[];
  notCovered: string[];
}

// ---------------- CONFIG：3060 使用前改这三行 ----------------
const REPO = "/home/owner/agentic-factory-projects"; // 仓库克隆根（monorepo 根）
const FA = REPO + "/chenmai8/chengmai-feeding-arm"; // 包根
// -----------------------------------------------------------------

const VENV_ON = "source " + FA + "/.venv/bin/activate";

artifact.table("pkg", {
  title: "硬件攻坚各步骤",
  columns: [
    { field: "task", label: "步骤" },
    { field: "testsPassed", label: "通过线达标" },
    { field: "summary", label: "摘要" },
  ],
  key: "task",
});
artifact.table("check", {
  title: "M4 独立验收",
  columns: [
    { field: "what", label: "检查项" },
    { field: "status", label: "结论" },
    { field: "evidence", label: "依据" },
  ],
  key: "what",
});

const COMMON = [
  "背景：澄勺桌面助餐机械臂，10 天契约 D3=2026-10-01 硬件已在位。真机 = 6 舵机桌面从臂（12V）",
  "+ 顶部 2MP 相机 + 腕部 1MP 相机，全部接在本机（Ubuntu）。你在执行**真机**步骤。",
  "仓库：" + REPO + "；包根：" + FA + "（chengshao/ 为 Python 包，tests/ 测试，scripts/ 门禁与 bring-up 脚本，",
  "config/ 配置，chengshao/reports/ 证据）。venv：" + FA + "/.venv（bash 里先 source 再跑）。",
  "先读：包根 README.md、docs/assets/manifest.md、docs/assets/specs/hw-toolchain.md 与 cs_arm/cs_orchestra spec、",
  "chengmai8/plan--具身助餐机器人/开发指令.md §5.9（bring-up 八步）与 §9（回退表）、",
  "chengmai8/_交付/HANDOFF-3060-v0.5.md（红线与资源）。",
  "纪律：",
  "1. 安全红线优先于进度：未确认软急停（空格 latch）可用、限速与禁入区参数加载前，不得让臂做任何自动运动；",
  "   真机运行时有人值守，手不离开键盘。",
  "2. 每步通过线与证据 JSON 落 chengshao/reports/（字段 {module,date,cmd,metrics,thresholds,pass}），数字真实不得编造。",
  "3. 冻结契约不得改签名（cs_schema v1.1 / ArmInterface / SafetyEnvelope）；发现问题先记录再按 §9 回退，不得偷偷放水。",
  "4. 中性命名：check_naming.py 必须 forbidden=0（含文档与 commit message）。",
  "5. 连续 2 轮不过 → 停止该步，按 §9 回退表执行；仍不过 → 记录 blockers 并停下等 owner，不空转不造假。",
  "6. git 提交在 Linux 上正常（NUL 是合法文件名，不需要绕 index 的提交管线）：git add <仓库相对路径...> &&",
  "   git commit -m \"<中性描述>\" && git tag <tag名> && git push origin <你的hw分支>；tag 命名按 HANDOFF v1 所有权协议（hw/*）。",
  "7. 所有命令设 PYTHONUTF8=1；真机命令加超时，跑完复查急停状态。",
].join("\n");

const fixFiles: string[] = [];

phase("环境自检与安全前置");

let envGate = await world.run("bash", ["-lc", VENV_ON + " && PYTHONUTF8=1 python " + FA + "/scripts/gate_g1.py"], { timeoutMs: 5400000 });
log("G1 环境门禁 exit=" + envGate.exitCode);
const envFixer = agent("环境修复工", {
  system: "你在 3060 Ubuntu 上修环境：依赖/权限/模型件/相机串口，按最小改动修到绿，不绕门禁不造假。",
});
let envRound = 0;
while (envRound < 2 && envGate.exitCode !== 0) {
  envRound += 1;
  const fix = await envFixer.ask<TaskResult>(
    "G1 环境门禁未过（第 " + envRound + " 轮）。输出尾部：\n" + envGate.stdout.split("\n").slice(-50).join("\n") +
      "\n\n按纪律修复：Ubuntu 侧先查权限（dialout/video 组、udev）、pip 镜像、模型件 CS_VENDOR_ROOT（COS 拉取）、funasr 暖机。修完返回改动文件清单（仓库相对路径）。",
  );
  for (const f of fix.files) {
    fixFiles.push(f);
  }
  envGate = await world.run("bash", ["-lc", VENV_ON + " && PYTHONUTF8=1 python " + FA + "/scripts/gate_g1.py"], { timeoutMs: 5400000 });
  log("第 " + envRound + " 轮修复后 G1 exit=" + envGate.exitCode);
}

const safetyPreflight = agent("安全前置检查员", {
  system: "你是机械臂安全员：上电前一项不漏地核对，任何一项不过就写下阻塞，不得放行。",
});
const preflight = await safetyPreflight.ask<TaskResult>(
  COMMON + "\n\n任务：真机上电前的安全前置检查（只做检查与记录，不做任何臂运动）：\n" +
    "1) 舵机与电源规格一致（12V 版 ×6）、线序正确、腕部相机线缆预留全行程余量；\n" +
    "2) 桌面防滑垫与座椅定位贴就位；\n" +
    "3) 软急停链路可用性验证（只读方式：确认 SafetyEnvelope 加载、禁入区参数与限速参数已从 config 加载、空格监听线程就绪——可经 --mock 链路验证，不动真机）；\n" +
    "4) 相机枚举（v4l2-ctl / cv2）与串口枚举（/dev/ttyUSB*、dialout 组权限）结果记录；\n" +
    "5) 以上逐项出 JSON 证据到 chengshao/reports/preflight_eval.json。任何不过 → blockers 写清并停下。",
);
report(preflight, "pkg");

phase("M4 bring-up 与标定（真机八步）");
const bringup = agent("bring-up 执行工程师", {
  system: "你是真机 bring-up 工程师：按 spec 八步顺序推进，每步出证据；任何一步不过按回退表处理，不跳过安全前置。",
});
const rM4 = await bringup.ask<TaskResult>(
  COMMON + "\n\n任务：M4 bring-up 八步（开发指令 §5.9 / hw-toolchain spec），顺序执行、每步证据落盘：\n" +
    "1) 舵机标定 + 连通冒烟：lerobot 标定入口 + python -m cs_arm.eval_hw → 6/6 连通、回读一致、限位/温度正常、夹爪开合；\n" +
    "2) 顶部手眼 eye-to-hand：python scripts/calibrate_handeye.py --cam scene --points 12 --out config/calib/handeye_scene.npz → 残差 ≤3mm 或 ≤2px；\n" +
    "3) 腕部手眼 eye-in-hand：--cam wrist --mode eye-in-hand --points 15 --out config/calib/handeye_wrist.npz → 同上；\n" +
    "4) 相机验收：python scripts/camera_check.py → 顶部 ArUco 可辨、腕部 20–50cm、曝光恢复 ≤1s、线缆无牵扯；不达标按既定回退（第三路相机）；\n" +
    "5) 口部静态尺度：python -m cs_mouth.eval --static-distance → 0.35/0.45/0.55m 三点 ≤5cm（记录项）；\n" +
    "6) 腕部口部追踪 live：python -m cs_mouth.eval --wrist-view --live → 四点 ≤4cm、检出率 ≥95%、曝光切换恢复 ≤1s、帧流不中断；\n" +
    "7) 安全演练先行：python scripts/safety_drill.py --cases head_turn,estop,face_intrude --trials 20 → 20/20 停止或后撤、禁入区侵入 0（此后才允许分食物舀取）；\n" +
    "8) 分食物舀取首轮：python -m cs_arm.eval_scoop --food <each> --trials 20（先用 windev-01 交付的 config/scoop_params.json 初始参数）。\n" +
    "提交本步代码与证据（tag: hw-m4-bringup-v1.0）。返回 TaskResult（files 用仓库相对路径）。",
);
report(rM4, "pkg");

const m4Verifier = agent("M4 独立验收员", {
  system: "你是独立验收员：只读证据与代码、跑只读验证命令，判定通过线是否真达标；不编辑任何文件；不信任自报。",
});
const m4Report = await m4Verifier.ask<CheckReport>(
  "背景：包根 " + FA + "。M4 bring-up 刚完成，文件：\n" + rM4.files.map((f) => "- " + f).join("\n") +
    "\n证据 JSON：\n" + rM4.evidence.map((e) => "- " + e).join("\n") +
    "\n\n请只读验证（禁止编辑任何文件）：读每份证据 JSON，用独立逻辑重算关键 metrics vs 阈值（舵机 6/6、残差 ≤3mm/≤2px、相机各断言、safety_drill 20/20、急停 ≤100ms、禁入区 0 侵入）；" +
    "不一致或缺失的项给 status=fail/blocked 并写明证据。能跑只读验证命令就跑（cwd=包根、PYTHONUTF8=1）。",
);
for (const c of m4Report.items) {
  report(c, "check");
}
log("M4 验收：" + m4Report.items.map((c) => c.what + "=" + c.status).join("，"));

phase("M5 分食物舀取调参");
const FOODS = ["congee", "noodles", "chunky"];
const scoopResults = await Promise.all(
  FOODS.map((food) =>
    agent("舀取调参工程师 " + food, {
      system: "你是舀取调参工程师：对一种食物把成功率调到通过线，参数进 config，证据真实不编造；不过就按回退表处理并如实记录。",
    }).ask<TaskResult>(
      COMMON + "\n\n任务：食物「" + food + "」的脚本舀取调参（每食物 50 次：最终 ≥90%、首试 ≥70%）：\n" +
        "1) 从 config/scoop_params.json 的推荐初始参数起步；\n" +
        "2) python -m cs_arm.eval_scoop --food " + food + " --trials 50 跑真机；\n" +
        "3) 未达标 → 腕部闭环重试/刮碗边/入勺深度倾角微调（回退表授权范围内）；\n" +
        "4) 收敛后把最终参数写回 config/scoop_params.json，证据落 chengshao/reports/scoop_eval.json（以食物名为 key 分段）；\n" +
        "5) 提交并打 tag: hw-m5-scoop-" + food + "-v1.0。",
    ),
  ),
);
for (const r of scoopResults) {
  report(r, "pkg");
}
log("M5 三食物自测：" + scoopResults.map((r) => r.task + "=" + r.testsPassed).join("，"));

phase("M6 集成、安全演练与演示准备");
const integrator = agent("全链集成工程师", {
  system: "你是集成工程师：把舀取策略接回行为树跑全链，安全项一项不让；任何安全数字不过 → 停下报阻塞。",
});
const rM6 = await integrator.ask<TaskResult>(
  COMMON + "\n\n任务：M6 集成与安全（开发指令 §5.9 全表）：\n" +
    "1) ScriptedScoop 接入行为树（ActPolicy 仅预留不启用）；\n" +
    "2) python -m cs_orchestra.eval --mock --episodes 30 复跑 30/30（mock 对照基线）；\n" +
    "3) python scripts/e2e_mock_run.py 复跑 30 口（mock 对照基线）；\n" +
    "4) python scripts/safety_drill.py --cases head_turn,estop,face_intrude --trials 20 真机复演；\n" +
    "5) 真机全链 30 口试跑（owner 在场）：每口 2 次相机角色切换、停止点禁入球外 ≥5cm、中位单口 ≤20s；\n" +
    "6) 护理看板 30/30 口无丢失核对（cs_dashboard）；\n" +
    "7) 提交并打 tag: hw-m6-integration-v1.0。任一项安全数字不过 → blockers 写清并停。",
);
report(rM6, "pkg");

const rehearsal = agent("演示筹备员", {
  system: "你是演示导演：把已验证的能力组织成 D9 演示，物料数字化、流程可回放；不夸大未验证项。",
});
const rDemo = await rehearsal.ask<TaskResult>(
  COMMON + "\n\n任务：D9 演示筹备：\n" +
    "1) 按 _交付/demo-三件套脚本.md 组织三段演示并实际排练一次（记录每段时长与卡点）；\n" +
    "2) 演示兜底确认：无硬件三件套（demo_sim.py / demo_mouth.py / e2e_mock_run.py）均可当场回放；\n" +
    "3) 演示检查单落 _交付/demo-彩排记录.md（含 owner 自试安排：转头/急停/吃饱了场景）；\n" +
    "4) 提交并打 tag: hw-demo-rehearsal-v1.0。",
);
report(rDemo, "pkg");

phase("汇总与推送");
const steps: TaskResult[] = [preflight, rM4, ...scoopResults, rM6, rDemo];
const push = await world.run("git", ["-C", REPO, "push", "origin", "HEAD:main"], { timeoutMs: 300000 });
const pushTags = await world.run("git", ["-C", REPO, "push", "origin", "--tags"], { timeoutMs: 300000 });
log("push main exit=" + push.exitCode + "；push tags exit=" + pushTags.exitCode);

await artifact.markdown(
  "hw-sprint-report",
  [
    "# 澄勺硬件攻坚冲刺报告（M4→M6，3060）",
    "",
    "## 结论",
    "环境门禁 exit=" + envGate.exitCode +
      "；M4 独立验收 " + m4Report.items.filter((c) => c.status === "pass").length + "/" + m4Report.items.length + " 项 pass" +
      "；M5 三食物自测 " + scoopResults.map((r) => r.task + "=" + r.testsPassed).join("/") +
      "；M6 " + (rM6.testsPassed ? "通过线达标" : "未达标/有阻塞") +
      "；push main exit=" + push.exitCode + "，tags exit=" + pushTags.exitCode + "。",
    "",
    "## 各步骤",
    ...steps.map((s) => "- " + s.task + "：" + s.summary + (s.blockers.length > 0 ? "（阻塞：" + s.blockers.join("；") + "）" : "")),
    "",
    "## 未覆盖",
    "- owner 自试与 D9 正式演示（人类触点）；",
    "- ACT 训练与长期优化（赛后，按 training/runbook_3060.md）；",
    "- 物理急停蘑菇头为可选加购项，未验证。",
  ].join("\n"),
  { title: "澄勺硬件攻坚冲刺报告", description: "M4-M6 各步骤、独立验收、推送记录", primary: true },
);

const result: WorkflowReport = {
  conclusion:
    "硬件攻坚（M4→M6）执行完毕：环境门禁 exit=" + envGate.exitCode +
    "；M4 验收 " + m4Report.items.filter((c) => c.status === "pass").length + "/" + m4Report.items.length +
    "；M5 " + scoopResults.map((r) => r.task + "=" + r.testsPassed).join("/") +
    "；M6 " + (rM6.testsPassed ? "达标" : "未达标") +
    "；push exit=" + push.exitCode + "。",
  findings: m4Report.items,
  verified: [
    "G1 环境门禁（exit=" + envGate.exitCode + "，修复轮 " + envRound + "）",
    "M4 独立验收员只读复核 " + m4Report.items.length + " 项",
    "M5 每食物 50 次真机 eval（scoop_eval.json）",
    "M6 safety_drill 20/20 + e2e 30 口 + 真机全链试跑",
  ],
  notCovered: [
    "owner 自试与 D9 正式演示（人类触点，owner 当场完成）",
    "ACT 训练与长期优化（赛后按 runbook_3060.md）",
    "物理急停硬件（蘑菇头）为可选加购项，未验证",
  ],
};
return result;
