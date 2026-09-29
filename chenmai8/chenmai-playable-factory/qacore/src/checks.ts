/**
 * 检查项定义（M8 规划十项；当前实装 CHK01/03/04/05/07/08/09/10；
 * oracle checks.py 判定语义逐项移植）。
 *
 * 判定状态取值：pass / fail / skip。
 * - pass/fail：由本次无头打开过程真实测得；
 * - skip：检查项尚未实装（CHK02/06）或产物/配置不具备判定前提，不做任何假定结论。
 *   注意：渠道要求静音时（muteBeforeFirstInteraction 默认 true），CHK04 缺 PF 桥/
 *   探针不是 skip 而是 fail——无法证明静音合规即违规。
 * - skip 是显式声明"未测"，报告中保留 skip 字样，严禁标成 pass。
 */

export interface Check {
  id: string;
  name: string;
  status: "pass" | "fail" | "skip";
  detail: string;
}

// 采集事实为跨模块结构（与 oracle cli.py facts 同键），此处按松散键位访问。
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- facts 形状由 run.ts 组装并对齐 oracle
export type Facts = Record<string, any>;

function check(id: string, name: string, status: Check["status"], detail: string): Check {
  return { id, name, status, detail };
}

function skip(id: string, name: string, detail: string): Check {
  return { id, name, status: "skip", detail };
}

function clip(text: string, n = 5): string {
  return text.length <= n ? text : text.slice(0, n - 1) + "…";
}

/** Python %g 格式（6 位有效数字、整数不带小数点）的窄口径实现。 */
export function fmtG(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return String(Number(v.toPrecision(6)));
}

function num(v: unknown): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function optNum(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function fmtFixed(v: number, digits: number): string {
  return v.toFixed(digits);
}

export function evaluate(facts: Facts): Check[] {
  const checks: Check[] = [];

  // CHK01 包体大小 ≤ 渠道上限（channel-rules；未知渠道不判定）
  const limit = facts.channel_max_bytes;
  if (limit === null || limit === undefined) {
    checks.push(skip("CHK01", "包体大小 ≤ 渠道上限",
      `规则库无渠道 ${JSON.stringify(facts.channel)} 的上限，不判定`));
  } else if (num(facts.artifact_bytes) <= num(limit)) {
    checks.push(check("CHK01", "包体大小 ≤ 渠道上限", "pass",
      `${num(facts.artifact_bytes)} B ≤ 上限 ${num(limit)} B`));
  } else {
    checks.push(check("CHK01", "包体大小 ≤ 渠道上限", "fail",
      `${num(facts.artifact_bytes)} B > 上限 ${num(limit)} B`));
  }

  checks.push(skip("CHK02", "文件数 ≤ 渠道上限", "未实装（当前输入为单 HTML 文件，无目录清点）"));

  // CHK03 零外网连接（横竖屏两趟合并判定）：HTTP 请求由 route 拦截记账；
  // WebSocket 由 route_web_socket 记账（条目前缀 websocket:）；
  // WebRTC 不经过网络层，由页面探针计数 RTCPeerConnection。
  const external: string[] = facts.external_requests ?? [];
  const rtc = num(facts.rtc_connections);
  if (external.length > 0 || rtc !== 0) {
    const shown = external.slice(0, 5).map((u) => clip(u)).join("；");
    const more = external.length > 5 ? `（另 ${external.length - 5} 条略）` : "";
    const problems: string[] = [];
    if (external.length > 0) {
      problems.push(`发现 ${external.length} 条非本机请求/WebSocket，已拦截：${shown}${more}`);
    }
    if (rtc !== 0) {
      problems.push(`页面构造了 ${rtc} 次 RTCPeerConnection（WebRTC 外联尝试）`);
    }
    checks.push(check("CHK03", "零外网请求", "fail", problems.join("；")));
  } else {
    checks.push(check("CHK03", "零外网请求", "pass",
      `两趟共 ${num(facts.request_count)} 条请求均指向本地伺服地址，`
      + "无外网请求、无外部 WebSocket、无 WebRTC 构造"));
  }

  // CHK04 首交互前静音 + 首交互后允许出声（依赖 window.PF 与自动试玩）。
  const pfPresent = facts.pf_present;
  const probeOk = facts.probe_installed;
  const muteRequired = facts.channel_mute_required;
  const auto: Facts = facts.autoplay ?? facts.muteLoadTime ?? {};
  if (!pfPresent) {
    if (muteRequired) {
      checks.push(check(
        "CHK04", "首交互前静音", "fail",
        "渠道要求首交互前静音，但页面未装配 window.PF 桥，无法证明静音合规"));
    } else {
      checks.push(skip("CHK04", "首交互前静音",
        "页面未装配 window.PF 桥且渠道未强制静音，无可判定对象"));
    }
  } else if (muteRequired && probeOk !== true) {
    checks.push(check(
      "CHK04", "首交互前静音", "fail",
      "渠道要求首交互前静音，但 qacore 探针未安装（__pfprobe 缺失），无法采证"));
  } else {
    const firstMutedVal: boolean | null = typeof auto.firstMutedBeforeInteraction === "boolean"
      ? auto.firstMutedBeforeInteraction
      : null;
    const audioRunning = auto.audioRunningBeforeInteraction;
    const mediaUnmuted = Math.trunc(num(auto.mediaUnmutedBeforeInteraction));
    const mediaPlays = Math.trunc(num(auto.mediaPlaysBeforeInteraction));
    const after: boolean | null = typeof auto.mutedAfterFirstGesture === "boolean"
      ? auto.mutedAfterFirstGesture
      : null;
    const problems: string[] = [];
    if (firstMutedVal !== true) {
      problems.push(`首交互前 PF.isMuted()=${fmtPy(firstMutedVal)}`);
    }
    if (audioRunning !== 0 && audioRunning !== null && audioRunning !== undefined) {
      problems.push(`首交互前存在 running AudioContext（${num(audioRunning)}）`);
    }
    if (mediaUnmuted > 0) {
      problems.push(`存在 ${mediaUnmuted} 个未静音的媒体元素（<audio>/<video>）`);
    }
    if (mediaPlays > 0) {
      problems.push(`首交互前发生了 ${mediaPlays} 次媒体播放调用（play()/autoplay）`);
    }
    if (facts.autoplay_enabled && after !== false) {
      problems.push(`首交互后 PF.isMuted()=${fmtPy(after)}（应为 False，即解除静音）`);
    }
    if (problems.length > 0) {
      checks.push(check("CHK04", "首交互前静音", "fail", problems.join("；")));
    } else {
      let detail = "首交互前 PF.isMuted()=true，无未静音媒体元素";
      if (facts.autoplay_enabled) {
        detail += `，无 running AudioContext，首交互后 isMuted()=false`
          + `（已解除静音，gestures=${num(auto.gestures)}）`;
      } else {
        detail += "（未开自动试玩，仅判首交互前）";
      }
      checks.push(check("CHK04", "首交互前静音", "pass", detail));
    }
  }

  // CHK05 横竖屏渲染非空白（画布像素方差阈值）
  const shots: Facts = facts.viewport_shots ?? {};
  const portraitHasCanvas = Boolean(shots.portrait?.has_canvas);
  const landscapeHasCanvas = Boolean(shots.landscape?.has_canvas);
  if (!portraitHasCanvas && !landscapeHasCanvas) {
    checks.push(skip("CHK05", "横竖屏渲染非空白", "页面无画布，跳过渲染判定"));
  } else {
    const threshold = num(facts.variance_threshold ?? 30.0);
    const problems: string[] = [];
    for (const orient of ["portrait", "landscape"] as const) {
      const shot: Facts = shots[orient] ?? {};
      if (!shot.has_canvas) {
        problems.push(`${orient}: 无画布`);
        continue;
      }
      const v = optNum(shot.variance);
      if (v === null) {
        problems.push(`${orient}: 未取得截图方差`);
      } else if (v < threshold) {
        problems.push(`${orient}: 像素方差 ${fmtFixed(v, 1)} < 阈值 ${fmtFixed(threshold, 0)}（疑似空白）`);
      }
    }
    if (problems.length > 0) {
      checks.push(check("CHK05", "横竖屏渲染非空白", "fail", problems.join("；")));
    } else {
      const vp = num(shots.portrait?.variance);
      const vl = num(shots.landscape?.variance);
      checks.push(check("CHK05", "横竖屏渲染非空白", "pass",
        `390×844 与 844×390 双仿真像素方差 ${fmtFixed(vp, 0)}/${fmtFixed(vl, 0)} ≥ 阈值 ${fmtFixed(threshold, 0)}`));
    }
  }

  checks.push(skip("CHK06", "渠道退出接口调用", "未实装（渠道 stub 注入属 M8 后续里程碑）"));

  // CHK07 自动试玩到结束页（pf:end 真实触发 + 结束页可见）
  if (!facts.autoplay_enabled) {
    checks.push(skip("CHK07", "自动试玩到结束页", "未开启 --autoplay，不驱动试玩"));
  } else if (!auto.qcHooksPresent) {
    checks.push(check("CHK07", "自动试玩到结束页", "fail",
      "页面未暴露 __PF_QC__（hint/state），无法自动试玩"));
  } else {
    const timeout = num(facts.autoplay_timeout_sec ?? 45.0);
    const endMs = optNum(auto.pfEndMs);
    const problems: string[] = [];
    if (!auto.pfEndFired || endMs === null) {
      problems.push("pf:end 未触发");
    } else if (endMs > timeout * 1000) {
      problems.push(`pf:end 于 ${fmtFixed(endMs, 0)}ms 触发，超出 ${fmtFixed(timeout * 1000, 0)}ms 预算`);
    }
    if (auto.reachedState !== "end") {
      problems.push(`最终 state=${JSON.stringify(auto.reachedState)}（应为 end）`);
    }
    if (auto.endScreenVisible !== true) {
      problems.push(`结束页可见性=${fmtPy(auto.endScreenVisible)}`);
    }
    if (problems.length > 0) {
      checks.push(check("CHK07", "自动试玩到结束页", "fail", problems.join("；")));
    } else {
      checks.push(check("CHK07", "自动试玩到结束页", "pass",
        `pf:end 于 ${fmtFixed(endMs as number, 0)}ms 触发（win=${fmtPy(auto.pfEndWin)}，`
        + `gestures=${num(auto.gestures)}），结束页可见`));
    }
  }

  // CHK08 控制台零错误（两趟合并；网络源噪声已在采集侧按 blocked 集合过滤）
  const consoleErrors: string[] = facts.console_errors ?? [];
  if (consoleErrors.length > 0) {
    const shown = consoleErrors.slice(0, 3).map((e) => clip(e, 160)).join(" | ");
    const more = consoleErrors.length > 3 ? `（另 ${consoleErrors.length - 3} 条略）` : "";
    checks.push(check("CHK08", "控制台零错误", "fail",
      `${consoleErrors.length} 条 error/pageerror：${shown}${more}`));
  } else {
    checks.push(check("CHK08", "控制台零错误", "pass", "两趟均无 console error 与 pageerror"));
  }

  // CHK09 本地加载时长
  const loadMs = num(facts.load_ms);
  const maxLoadSec = num(facts.max_load_sec);
  if (loadMs <= maxLoadSec * 1000) {
    checks.push(check("CHK09", `本地加载 ≤${fmtG(maxLoadSec)}s`, "pass",
      `load 耗时 ${fmtFixed(loadMs, 0)}ms`));
  } else {
    checks.push(check("CHK09", `本地加载 ≤${fmtG(maxLoadSec)}s`, "fail",
      `load 耗时 ${fmtFixed(loadMs, 0)}ms 超过阈值 ${fmtFixed(maxLoadSec * 1000, 0)}ms`));
  }

  // CHK10 多语言文案与素材上屏（2026-09-29 实装 + 自证补强，判定语义照抄）：
  // - required_texts：每条都须在渲染文案集合中子串命中，且在 text_states 中有
  //   "曾在采样时刻 active+visible" 的证据；模板未提供 textStates 时从严 fail。
  // - required_sprites：每键都须页面内像素对账通过（asset_audit.replaced=true）。
  // - 两者都未提供时保持 skip（无判定对象，不算通过）。
  const requiredTexts: string[] = ((facts.required_texts ?? []) as unknown[])
    .map((s) => String(s)).filter((s) => s.length > 0);
  const requiredSprites: string[] = ((facts.required_sprites ?? []) as unknown[])
    .map((s) => String(s)).filter((s) => s.length > 0);
  if (requiredTexts.length === 0 && requiredSprites.length === 0) {
    checks.push(skip("CHK10", "多语言文案与素材上屏",
      "未提供 --require-text/--require-sprite，无判定对象（locale 仿真属后续）"));
  } else {
    const texts: string[] = facts.page_texts ?? [];
    const statesHook = facts.text_states_hook;
    const stateMap = new Map<string, Record<string, unknown>>();
    for (const s of facts.text_states ?? []) {
      if (s !== null && typeof s === "object") stateMap.set(String(s.text), s);
    }
    const audit = new Map<string, Record<string, unknown>>();
    for (const a of facts.asset_audit ?? []) {
      if (a !== null && typeof a === "object") audit.set(String(a.spriteKey), a);
    }
    const problems: string[] = [];
    const missing = requiredTexts.filter((s) => !texts.some((t) => t.includes(s)));
    if (missing.length > 0) {
      const shown = missing.slice(0, 6).map((m) => clip(m, 24)).join("、");
      const more = missing.length > 6 ? `（另 ${missing.length - 6} 条略）` : "";
      problems.push(
        `渲染文案集合（${texts.length} 条）中未找到：${shown}${more}`
        + (texts.length === 0 ? "；页面未上报任何渲染文案（无 __PF_QC__.texts？）" : ""));
    }
    if (statesHook === false) {
      problems.push(
        "模板未提供 __PF_QC__.textStates()，文案可见性无法自证"
        + "（上屏证据只有字符串登记，缺 active+visible 采样核验）");
    } else if (requiredTexts.length > 0) {
      const neverVisible = requiredTexts.filter((s) => {
        // oracle 语义：任一 state_map 条目满足（子串命中 且 everVisible=True）
        // 即有证据；全部条目皆无证据 → 从严列入 never_visible。
        for (const [t, v] of stateMap) {
          if (typeof t === "string" && t.includes(s) && v.everVisible === true) return false;
        }
        return true;
      });
      if (neverVisible.length > 0) {
        const shown = neverVisible.slice(0, 6).map((m) => clip(m, 24)).join("、");
        const more = neverVisible.length > 6 ? `（另 ${neverVisible.length - 6} 条略）` : "";
        problems.push(
          `这些文案在全部采样（驱动前/自动试玩各相位/结束页）中从未处于 `
          + `active+visible 状态：${shown}${more}`);
      }
    }
    for (const key of requiredSprites) {
      const a = audit.get(key);
      if (a === undefined) {
        problems.push(
          `替换素材 ${key}：页面未上报像素对账结果（无 __PF_QC__.assets 或该键未嵌入）`);
      } else if (a.replaced !== true) {
        problems.push(`替换素材 ${key}：像素对账未通过（${
          a.reason ? String(a.reason) : "平均差 " + String(a.mad)}）`);
      }
    }
    if (problems.length > 0) {
      checks.push(check("CHK10", "多语言文案与素材上屏", "fail", problems.join("；")));
    } else {
      const visNote = statesHook ? "，active+visible 采样核验通过" : "";
      checks.push(check(
        "CHK10", "多语言文案与素材上屏", "pass",
        `渲染文案命中 ${requiredTexts.length}/${requiredTexts.length}`
        + `（集合共 ${texts.length} 条${visNote}）`
        + (requiredSprites.length > 0
          ? `；替换素材像素对账通过 ${requiredSprites.length}/${requiredSprites.length}`
          : "")));
    }
  }
  return checks;
}

/** Python f-string 里 bool/None 的显示形式（True/False/None）。 */
function fmtPy(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (typeof v === "boolean") return v ? "True" : "False";
  return String(v);
}
