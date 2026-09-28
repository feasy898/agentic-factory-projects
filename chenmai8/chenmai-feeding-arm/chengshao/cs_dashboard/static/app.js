/* 澄勺护理看板前端逻辑：口数 / 时长 / 克数 / 事件流（SSE 实时）。
 * 无任何外部网络引用：Chart.js 来自本地 /static/vendor/，离线可开。 */
"use strict";

const $ = (id) => document.getElementById(id);
const OUTCOME_CN = { success: "成功", retry: "重试", rejected: "拒食", aborted: "中止" };
const ALARM_OUTCOMES = new Set(["retry", "rejected", "aborted"]);

const state = {
  session: null,   // MealSession 契约对象
  summary: null,   // /api/summary 聚合
  events: [],      // 事件流（最新在前）
  chart: null,
};

/* ---------- 时间格式化 ---------- */
function fmtClock(ns) {
  if (ns === null || ns === undefined) return "--:--:--";
  const d = new Date(Number(ns) / 1e6);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${p(m)}:${p(s)}` : `${p(m)}:${p(s)}`;
}

/* ---------- 渲染 ---------- */
function render() {
  const { session, summary } = state;
  const stBadge = $("session-state");
  if (!session) {
    stBadge.textContent = "未开始";
    stBadge.className = "badge badge-idle";
    $("session-user").textContent = "";
    $("session-id").textContent = "";
    $("session-start").textContent = "";
  } else {
    const live = session.ended_ns === null || session.ended_ns === undefined;
    stBadge.textContent = live ? "进行中" : "已结束";
    stBadge.className = "badge " + (live ? "badge-live" : "badge-done");
    $("session-user").textContent = "用户: " + session.user_id;
    $("session-id").textContent = session.session_id;
    $("session-start").textContent = "开始 " + fmtClock(session.started_ns);
  }

  if (summary) {
    $("m-bites").textContent = summary.bite_count;
    $("m-success").textContent = summary.outcomes.success;
    const alarms = summary.outcomes.retry + summary.outcomes.rejected + summary.outcomes.aborted;
    $("m-alarms").textContent = alarms;
    $("card-alarm").classList.toggle("alarm", alarms > 0);
    $("m-alarms-note").textContent =
      alarms > 0
        ? `重试 ${summary.outcomes.retry} · 拒食 ${summary.outcomes.rejected} · 中止 ${summary.outcomes.aborted}`
        : "重试 / 拒食 / 中止";
    if (summary.total_grams === null || summary.total_grams === undefined) {
      $("m-grams").textContent = "—";
      $("m-grams-unit").textContent = "";
      $("m-grams-note").textContent = "无称重硬件，暂不统计";
    } else {
      $("m-grams").textContent = Math.round(summary.total_grams * 10) / 10;
      $("m-grams-unit").textContent = "g";
      $("m-grams-note").textContent = "按碗勺减重估计";
    }
  }
  renderDuration();
  renderChart();
  renderEvents();
}

function renderDuration() {
  const { session, summary } = state;
  if (!session || !summary) {
    $("m-duration").textContent = "--:--";
    $("m-duration-note").textContent = "开始后计时";
    return;
  }
  const live = session.ended_ns === null || session.ended_ns === undefined;
  let sec = summary.duration_s;
  if (live) {
    sec = (Date.now() * 1e6 - session.started_ns) / 1e9;
    $("m-duration-note").textContent = "进行中";
  } else {
    $("m-duration-note").textContent = "本餐总计";
  }
  $("m-duration").textContent = fmtDuration(sec);
}
setInterval(renderDuration, 1000);

/* ---------- 图表（本地 Chart.js） ---------- */
function chartData() {
  const s = state.session;
  if (!s || !s.bites.length) return { xs: [], cum: [], grams: [] };
  const t0 = Number(s.started_ns);
  const xs = [], cum = [], grams = [];
  let c = 0, g = 0, gramsKnown = true;
  for (const b of s.bites) {
    c += 1;
    xs.push((Number(b.ts_end_ns) - t0) / 1e9);
    cum.push(c);
    if (b.grams_before !== null && b.grams_before !== undefined &&
        b.grams_after !== null && b.grams_after !== undefined) {
      g += Math.max(0, b.grams_before - b.grams_after);
      grams.push(Math.round(g * 10) / 10);
    } else {
      gramsKnown = false;
      grams.push(null);
    }
  }
  return { xs, cum, grams, gramsKnown };
}

function renderChart() {
  const { xs, cum, grams, gramsKnown } = chartData();
  if (gramsKnown) $("chart-note").textContent = "克数按每口（舀前-舀后）累计。";
  if (!state.chart) {
    state.chart = new Chart($("chart").getContext("2d"), {
      type: "line",
      data: {
        labels: xs,
        datasets: [
          {
            label: "累计口数",
            data: cum,
            borderColor: "#4cc2ff",
            backgroundColor: "rgba(76,194,255,.12)",
            fill: true,
            tension: 0.25,
            pointRadius: 3,
            yAxisID: "y",
          },
          {
            label: "累计克数",
            data: grams,
            borderColor: "#3ddc97",
            spanGaps: true,
            tension: 0.25,
            pointRadius: 2,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { title: { display: true, text: "开餐后分钟/秒（秒）", color: "#8fa3b5" }, ticks: { color: "#8fa3b5" }, grid: { color: "#22303f" } },
          y: { beginAtZero: true, title: { display: true, text: "口", color: "#4cc2ff" }, ticks: { color: "#4cc2ff", precision: 0 }, grid: { color: "#22303f" } },
          y1: { beginAtZero: true, position: "right", title: { display: true, text: "克", color: "#3ddc97" }, ticks: { color: "#3ddc97" }, grid: { drawOnChartArea: false } },
        },
        plugins: { legend: { labels: { color: "#e8eef4" } } },
      },
    });
  } else {
    state.chart.data.labels = xs;
    state.chart.data.datasets[0].data = cum;
    state.chart.data.datasets[1].data = grams;
    state.chart.update("none");
  }
}

/* ---------- 事件流 ---------- */
function eventRow(ev) {
  const li = document.createElement("li");
  const ts = document.createElement("span");
  ts.className = "t";
  ts.textContent = fmtClock(ev.ts_ns);
  li.appendChild(ts);
  const p = ev.payload || {};
  if (ev.kind === "bite") {
    const b = p.bite || {};
    const tag = document.createElement("span");
    tag.className = "tag tag-bite-" + b.outcome;
    tag.textContent = `第 ${b.bite_id} 口 · ${OUTCOME_CN[b.outcome] || b.outcome}`;
    li.appendChild(tag);
    const detail = document.createElement("span");
    detail.textContent = `用时 ${(((Number(b.ts_end_ns) || 0) - (Number(b.ts_start_ns) || 0)) / 1e9).toFixed(1)}s`;
    li.appendChild(detail);
    if (ALARM_OUTCOMES.has(b.outcome)) li.classList.add("alarm");
  } else {
    const tag = document.createElement("span");
    tag.className = "tag tag-" + ev.kind;
    tag.textContent = ev.kind === "session_started" ? "开餐" : "本餐结束";
    li.appendChild(tag);
    if (p.user_id) {
      const u = document.createElement("span");
      u.textContent = "用户 " + p.user_id;
      li.appendChild(u);
    }
  }
  return li;
}

function renderEvents() {
  const ul = $("event-list");
  ul.textContent = "";
  if (!state.events.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "暂无事件 —— 开餐后这里实时滚动每一口";
    ul.appendChild(li);
    return;
  }
  for (const ev of state.events) ul.appendChild(eventRow(ev));
}

function prependEvent(kind, payload) {
  state.events.unshift({ ts_ns: Date.now() * 1e6, kind, payload });
  if (state.events.length > 100) state.events.pop();
  renderEvents();
}

/* ---------- 数据装载与 SSE ---------- */
function normalizeSummary(s) {
  return s && typeof s.bite_count === "number" ? s : null;
}

async function bootstrap() {
  try {
    const [cur, sum, evs] = await Promise.all([
      fetch("/api/session/current").then((r) => (r.ok ? r.json() : null)),
      fetch("/api/summary").then((r) => (r.ok ? r.json() : null)),
      fetch("/api/events?limit=50").then((r) => (r.ok ? r.json() : [])),
    ]);
    state.session = cur;
    state.summary = normalizeSummary(sum);
    state.events = Array.isArray(evs) ? evs : [];
  } catch (e) {
    console.error("初始化失败", e);
  }
  render();
}

function applyPayload(p, kind) {
  if (p.session) state.session = p.session;
  const sum = normalizeSummary(p.summary);
  if (sum) state.summary = sum;
  else if (p.summary && p.summary.session === null) {
    state.summary = null;   // 服务端无任何会话（全新实例）
    state.session = null;
  }
  if (kind === "bite" && p.bite) {
    state.events.unshift({ ts_ns: p.bite.ts_end_ns, kind, payload: p });
    if (state.events.length > 100) state.events.pop();
  }
  render();
}

function connectStream() {
  const badge = $("conn-state");
  const es = new EventSource("/api/stream");
  es.onopen = () => { badge.textContent = "实时连接 ✓"; badge.className = "badge badge-conn on"; };
  es.onerror = () => { badge.textContent = "连接断开，重试中…"; badge.className = "badge badge-conn off"; };
  for (const kind of ["snapshot", "bite", "session_started", "session_ended"]) {
    es.addEventListener(kind, (e) => {
      try { applyPayload(JSON.parse(e.data), kind); } catch (err) { console.error(err); }
    });
  }
}

bootstrap().then(connectStream);
