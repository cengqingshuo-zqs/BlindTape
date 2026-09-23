"use strict";

const DAY_SECONDS = 86400;

const state = {
  sessionId: null,
  totalBars: 0,
  dayIndex: -1,
  done: false,
  finished: false,
};

const el = {
  progressLabel: document.getElementById("progress-label"),
  positionLabel: document.getElementById("position-label"),
  sizeSlider: document.getElementById("size-slider"),
  sizeValue: document.getElementById("size-value"),
  logList: document.getElementById("log-list"),
  btnNext: document.getElementById("btn-next"),
  btnFinish: document.getElementById("btn-finish"),
  btnBuy: document.getElementById("btn-buy"),
  btnAdd: document.getElementById("btn-add"),
  btnSell: document.getElementById("btn-sell"),
  btnLiquidate: document.getElementById("btn-liquidate"),
  reviewOverlay: document.getElementById("review-overlay"),
  reviewIdentity: document.getElementById("review-identity"),
  reviewDates: document.getElementById("review-dates"),
  reviewStats: document.getElementById("review-stats"),
  btnExport: document.getElementById("btn-export"),
  btnRestart: document.getElementById("btn-restart"),
};

// ---- 训练中的盲测图（不带真实日期，timeScale整个隐藏掉） ----
const blindChart = LightweightCharts.createChart(document.getElementById("chart-container"), {
  layout: { background: { type: "solid", color: "#0f1117" }, textColor: "#c9d1e0" },
  grid: { vertLines: { color: "#1c2029" }, horzLines: { color: "#1c2029" } },
  timeScale: { visible: false, borderVisible: false },
  rightPriceScale: { borderVisible: false },
  autoSize: true,
});
const blindSeries = blindChart.addSeries(LightweightCharts.CandlestickSeries, {
  upColor: "#d94848", downColor: "#3a7fe0", borderVisible: false,
  wickUpColor: "#d94848", wickDownColor: "#3a7fe0",
});

let reviewChart = null;
let reviewCandleSeries = null;
let reviewMarkersPrimitive = null;
let equityChart = null;
let equityLineSeries = null;

async function api(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败 (${resp.status})`);
  }
  return resp.json();
}

function setActionButtonsEnabled(enabled) {
  [el.btnBuy, el.btnAdd, el.btnSell, el.btnLiquidate].forEach((b) => (b.disabled = !enabled));
}

function logAction(record) {
  const li = document.createElement("li");
  const label = { buy: "买入", add: "加仓", sell: "减仓", liquidate: "清仓" }[record.action] || record.action;
  li.textContent = `第${record.day_index + 1}天 ${label} @ ${record.price.toFixed(3)}  仓位 -> ${(record.position_after * 100).toFixed(0)}%`;
  el.logList.prepend(li);
}

async function startNewSession() {
  state.done = false;
  state.finished = false;
  state.dayIndex = -1;
  el.logList.innerHTML = "";
  blindSeries.setData([]);
  setActionButtonsEnabled(false);
  el.btnNext.disabled = false;

  const data = await api("POST", "/api/sessions");
  state.sessionId = data.session_id;
  state.totalBars = data.total_bars;
  el.progressLabel.textContent = `第 0 / ${state.totalBars} 天（代码和日期已隐藏）`;
  el.positionLabel.textContent = "仓位 0%";
}

async function revealNext() {
  if (!state.sessionId || state.done) return;
  const data = await api("POST", `/api/sessions/${state.sessionId}/reveal`);
  if (data.done) {
    state.done = true;
    el.btnNext.disabled = true;
    el.progressLabel.textContent = `窗口已走完（${state.totalBars}/${state.totalBars} 天），点"结束训练/揭晓"看结果`;
    return;
  }
  state.dayIndex = data.day_index;
  const bar = data.bar;
  blindSeries.update({
    time: state.dayIndex * DAY_SECONDS,
    open: bar.open, high: bar.high, low: bar.low, close: bar.close,
  });
  el.progressLabel.textContent = `第 ${state.dayIndex + 1} / ${state.totalBars} 天（代码和日期已隐藏）`;
  el.positionLabel.textContent = `仓位 ${(data.position * 100).toFixed(0)}%`;
  setActionButtonsEnabled(true);
}

async function doAction(action) {
  if (!state.sessionId || state.dayIndex < 0) return;
  const size = Number(el.sizeSlider.value) / 100;
  try {
    const record = await api("POST", `/api/sessions/${state.sessionId}/act`, { action, size });
    el.positionLabel.textContent = `仓位 ${(record.position_after * 100).toFixed(0)}%`;
    logAction(record);
  } catch (err) {
    alert(err.message);
  }
}

function renderStats(perf) {
  const items = [
    ["总收益", `${(perf.total_return * 100).toFixed(2)}%`],
    ["最大回撤", `${(perf.max_drawdown * 100).toFixed(2)}%`],
    ["在场天数占比", `${(perf.time_in_market_pct * 100).toFixed(1)}%`],
    ["操作次数", `${perf.num_actions}`],
  ];
  el.reviewStats.innerHTML = items.map(([label, value]) =>
    `<div class="stat-item"><div class="label">${label}</div><div class="value">${value}</div></div>`
  ).join("");
}

function ensureReviewCharts() {
  if (!reviewChart) {
    reviewChart = LightweightCharts.createChart(document.getElementById("review-chart-container"), {
      layout: { background: { type: "solid", color: "#0f1117" }, textColor: "#c9d1e0" },
      grid: { vertLines: { color: "#1c2029" }, horzLines: { color: "#1c2029" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      autoSize: true,
    });
    reviewCandleSeries = reviewChart.addSeries(LightweightCharts.CandlestickSeries, {
      upColor: "#d94848", downColor: "#3a7fe0", borderVisible: false,
      wickUpColor: "#d94848", wickDownColor: "#3a7fe0",
    });
  }
  if (!equityChart) {
    equityChart = LightweightCharts.createChart(document.getElementById("equity-chart-container"), {
      layout: { background: { type: "solid", color: "#0f1117" }, textColor: "#c9d1e0" },
      grid: { vertLines: { color: "#1c2029" }, horzLines: { color: "#1c2029" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      autoSize: true,
    });
    equityLineSeries = equityChart.addSeries(LightweightCharts.LineSeries, { color: "#4fd18b" });
  }
}

async function finishAndReveal() {
  if (!state.sessionId) return;

  await api("POST", `/api/sessions/${state.sessionId}/finish`);
  const answer = await api("GET", `/api/sessions/${state.sessionId}/answer`);
  state.finished = true;

  el.reviewIdentity.textContent = `真实标的：${answer.symbol}  ${answer.name}`;
  el.reviewDates.textContent = `真实区间：${answer.start_date} ~ ${answer.end_date}`;

  ensureReviewCharts();

  const candleData = answer.ohlcv.map((row) => ({
    time: row.trade_date, open: row.open, high: row.high, low: row.low, close: row.close,
  }));
  reviewCandleSeries.setData(candleData);

  const markerColor = { buy: "#d94848", add: "#e0873a", sell: "#3a7fe0", liquidate: "#c9d1e0" };
  const markers = answer.actions.map((a) => ({
    time: answer.ohlcv[a.day_index].trade_date,
    position: "belowBar",
    color: markerColor[a.action] || "#ffffff",
    shape: "arrowUp",
    text: `${a.action}@${a.price.toFixed(2)}`,
  }));
  // 每次揭晓都重新创建一个markers primitive绑到同一个series上会不断叠加旧标记，
  // 所以复用同一个primitive、每次都setMarkers()整体替换
  if (!reviewMarkersPrimitive) {
    reviewMarkersPrimitive = LightweightCharts.createSeriesMarkers(reviewCandleSeries, markers);
  } else {
    reviewMarkersPrimitive.setMarkers(markers);
  }
  reviewChart.timeScale().fitContent();

  const equityData = answer.equity_curve.map((v, i) => ({ time: answer.ohlcv[i].trade_date, value: v }));
  equityLineSeries.setData(equityData);
  equityChart.timeScale().fitContent();

  renderStats(answer.performance);
  el.reviewOverlay.classList.remove("hidden");
}

async function exportSession() {
  if (!state.sessionId) return;
  const data = await api("GET", `/api/sessions/${state.sessionId}/export`);
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const meta = data.session_meta;
  a.href = url;
  a.download = `session_${meta.symbol}_${meta.start_date}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

el.sizeSlider.addEventListener("input", () => {
  el.sizeValue.textContent = `${el.sizeSlider.value}%`;
});
el.btnNext.addEventListener("click", () => revealNext().catch((e) => alert(e.message)));
el.btnFinish.addEventListener("click", () => finishAndReveal().catch((e) => alert(e.message)));
el.btnBuy.addEventListener("click", () => doAction("buy"));
el.btnAdd.addEventListener("click", () => doAction("add"));
el.btnSell.addEventListener("click", () => doAction("sell"));
el.btnLiquidate.addEventListener("click", () => doAction("liquidate"));
el.btnExport.addEventListener("click", () => exportSession().catch((e) => alert(e.message)));
el.btnRestart.addEventListener("click", () => {
  el.reviewOverlay.classList.add("hidden");
  startNewSession().catch((e) => alert(e.message));
});

startNewSession().catch((e) => alert(e.message));
