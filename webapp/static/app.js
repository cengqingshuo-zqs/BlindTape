"use strict";

const DAY_SECONDS = 86400;

const state = {
  sessionId: null,
  totalBars: 0,
  contextDays: 0,
  dayIndex: -1,          // 训练窗口内的cursor（-1=还没揭示任何一根）
  done: false,
  finished: false,
  closesSoFar: [],       // 背景 + 已揭示窗口 的收盘价，用来算MA
  actionsSoFar: [],      // 本次训练目前为止的操作记录，用来算持仓成本
  position: 0,           // 0~1
  totalCapital: 100000,
  sizeCheng: 3,          // 1~10成
};

const el = {
  progressLabel: document.getElementById("progress-label"),
  positionLabel: document.getElementById("position-label"),
  maPeriodInput: document.getElementById("ma-period"),
  sizeValue: document.getElementById("size-value"),
  sizeMinus: document.getElementById("size-minus"),
  sizePlus: document.getElementById("size-plus"),
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

const MARKER_COLOR = { buy: "#d94848", add: "#e0873a", sell: "#3a7fe0", liquidate: "#c9d1e0" };
const MARKER_TEXT = { buy: "B", add: "B", sell: "S", liquidate: "S" };

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
const blindMaSeries = blindChart.addSeries(LightweightCharts.LineSeries, {
  color: "#f0d264", lineWidth: 1,
});
let blindMarkersPrimitive = null;
let blindCostLine = null;
let blindLatestLine = null;

let reviewChart = null;
let reviewCandleSeries = null;
let reviewMaSeries = null;
let reviewMarkersPrimitive = null;
let reviewCostLine = null;
let reviewLatestLine = null;
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

// ---- 通用计算：MA、持仓成本 ----

function computeMA(closes, period) {
  if (period < 2 || closes.length < period) return [];
  const points = [];
  let sum = 0;
  for (let i = 0; i < closes.length; i++) {
    sum += closes[i];
    if (i >= period) sum -= closes[i - period];
    if (i >= period - 1) points.push({ index: i, value: sum / period });
  }
  return points;
}

function computeFinalAvgCost(actions) {
  let position = 0;
  let avgCost = null;
  for (const a of actions) {
    if (a.position_delta > 0) {
      const prevContribution = avgCost === null ? 0 : avgCost * position;
      avgCost = (prevContribution + a.price * a.position_delta) / a.position_after;
    }
    position = a.position_after;
    if (position === 0) avgCost = null;
  }
  return avgCost;
}

function updateSizeLabel() {
  const yuan = (state.totalCapital * state.sizeCheng) / 10;
  el.sizeValue.textContent = `${state.sizeCheng}成（¥${yuan.toLocaleString()}）`;
}

function updatePositionLabel() {
  const yuan = state.totalCapital * state.position;
  el.positionLabel.textContent = `仓位 ${(state.position * 10).toFixed(1)}成（¥${Math.round(yuan).toLocaleString()}）`;
}

function setActionButtonsEnabled(enabled) {
  [el.btnBuy, el.btnAdd, el.btnSell, el.btnLiquidate].forEach((b) => (b.disabled = !enabled));
}

function logAction(record) {
  const li = document.createElement("li");
  const label = { buy: "买入", add: "加仓", sell: "减仓", liquidate: "清仓" }[record.action] || record.action;
  li.textContent = `第${record.day_index + 1}天 ${label} @ ${record.price.toFixed(3)}  仓位 -> ${(record.position_after * 10).toFixed(1)}成`;
  el.logList.prepend(li);
}

// ---- 盲测阶段图表更新 ----

function rebuildBlindMaSeries() {
  const period = Number(el.maPeriodInput.value) || 20;
  const points = computeMA(state.closesSoFar, period);
  blindMaSeries.setData(points.map((p) => ({ time: p.index * DAY_SECONDS, value: p.value })));
}

function updateBlindCostLine() {
  const avgCost = computeFinalAvgCost(state.actionsSoFar);
  if (avgCost === null) {
    if (blindCostLine) {
      blindSeries.removePriceLine(blindCostLine);
      blindCostLine = null;
    }
    return;
  }
  if (blindCostLine) {
    blindCostLine.applyOptions({ price: avgCost });
  } else {
    blindCostLine = blindSeries.createPriceLine({
      price: avgCost, color: "#f0d264", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: "成本",
    });
  }
}

function updateBlindLatestLine(price) {
  if (blindLatestLine) {
    blindLatestLine.applyOptions({ price });
  } else {
    blindLatestLine = blindSeries.createPriceLine({
      price, color: "#8b93a7", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted,
      axisLabelVisible: true, title: "最新价",
    });
  }
}

function pushBlindMarker(record) {
  const marker = {
    time: (state.contextDays + record.day_index) * DAY_SECONDS,
    position: record.action === "sell" || record.action === "liquidate" ? "aboveBar" : "belowBar",
    color: MARKER_COLOR[record.action] || "#ffffff",
    shape: "circle",
    text: MARKER_TEXT[record.action] || "?",
  };
  state._blindMarkers = state._blindMarkers || [];
  state._blindMarkers.push(marker);
  if (!blindMarkersPrimitive) {
    blindMarkersPrimitive = LightweightCharts.createSeriesMarkers(blindSeries, state._blindMarkers);
  } else {
    blindMarkersPrimitive.setMarkers(state._blindMarkers);
  }
}

// ---- 会话生命周期 ----

async function startNewSession() {
  state.done = false;
  state.finished = false;
  state.dayIndex = -1;
  state.position = 0;
  state.actionsSoFar = [];
  state._blindMarkers = [];
  el.logList.innerHTML = "";
  setActionButtonsEnabled(false);
  el.btnNext.disabled = false;

  if (blindCostLine) { blindSeries.removePriceLine(blindCostLine); blindCostLine = null; }
  if (blindLatestLine) { blindSeries.removePriceLine(blindLatestLine); blindLatestLine = null; }
  blindMarkersPrimitive = null;

  const data = await api("POST", "/api/sessions");
  state.sessionId = data.session_id;
  state.totalBars = data.total_bars;
  state.contextDays = data.context_bars.length;
  state.totalCapital = data.total_capital_yuan;
  el.maPeriodInput.value = data.default_ma_period;

  const contextData = data.context_bars.map((bar, i) => ({
    time: i * DAY_SECONDS, open: bar.open, high: bar.high, low: bar.low, close: bar.close,
  }));
  blindSeries.setData(contextData);
  state.closesSoFar = data.context_bars.map((b) => b.close);
  rebuildBlindMaSeries();
  if (state.closesSoFar.length > 0) {
    updateBlindLatestLine(state.closesSoFar[state.closesSoFar.length - 1]);
  }

  el.progressLabel.textContent = `第 0 / ${state.totalBars} 天（代码和日期已隐藏）`;
  updatePositionLabel();
  updateSizeLabel();
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
  const virtualIndex = state.contextDays + state.dayIndex;
  blindSeries.update({
    time: virtualIndex * DAY_SECONDS,
    open: bar.open, high: bar.high, low: bar.low, close: bar.close,
  });
  state.closesSoFar.push(bar.close);
  rebuildBlindMaSeries();
  updateBlindLatestLine(bar.close);

  el.progressLabel.textContent = `第 ${state.dayIndex + 1} / ${state.totalBars} 天（代码和日期已隐藏）`;
  setActionButtonsEnabled(true);
}

async function doAction(action) {
  if (!state.sessionId || state.dayIndex < 0) return;
  const size = state.sizeCheng / 10;
  try {
    const record = await api("POST", `/api/sessions/${state.sessionId}/act`, { action, size });
    state.position = record.position_after;
    state.actionsSoFar.push(record);
    updatePositionLabel();
    updateBlindCostLine();
    pushBlindMarker(record);
    logAction(record);
  } catch (err) {
    alert(err.message);
  }
}

function renderStats(perf, totalCapital) {
  const yuanPnl = perf.total_return * totalCapital;
  const items = [
    ["总收益", `${(perf.total_return * 100).toFixed(2)}%（¥${yuanPnl >= 0 ? "+" : ""}${Math.round(yuanPnl).toLocaleString()}）`],
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
    reviewMaSeries = reviewChart.addSeries(LightweightCharts.LineSeries, { color: "#f0d264", lineWidth: 1 });
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

  // 图表容器必须先变成可见（display!=none）再创建/画图，不然 autoSize 量到的是0宽度，
  // 之后整个chart的内部尺寸就是错的，表现为K线全挤在一小块、大片空白
  el.reviewOverlay.classList.remove("hidden");
  ensureReviewCharts();

  const fullRows = [...answer.context_ohlcv, ...answer.ohlcv];
  const candleData = fullRows.map((row) => ({
    time: row.trade_date, open: row.open, high: row.high, low: row.low, close: row.close,
  }));
  reviewCandleSeries.setData(candleData);

  const period = Number(el.maPeriodInput.value) || 20;
  const allCloses = fullRows.map((r) => r.close);
  const maPoints = computeMA(allCloses, period);
  reviewMaSeries.setData(maPoints.map((p) => ({ time: fullRows[p.index].trade_date, value: p.value })));

  const markers = answer.actions.map((a) => ({
    time: answer.ohlcv[a.day_index].trade_date,
    position: a.action === "sell" || a.action === "liquidate" ? "aboveBar" : "belowBar",
    color: MARKER_COLOR[a.action] || "#ffffff",
    shape: "circle",
    text: MARKER_TEXT[a.action] || "?",
  }));
  if (!reviewMarkersPrimitive) {
    reviewMarkersPrimitive = LightweightCharts.createSeriesMarkers(reviewCandleSeries, markers);
  } else {
    reviewMarkersPrimitive.setMarkers(markers);
  }

  // 成本线 + 最新价线（每轮训练的标的和数据范围完全不同，价格线整个重建而不是更新）
  if (reviewCostLine) { reviewCandleSeries.removePriceLine(reviewCostLine); reviewCostLine = null; }
  if (reviewLatestLine) { reviewCandleSeries.removePriceLine(reviewLatestLine); reviewLatestLine = null; }

  const finalAvgCost = computeFinalAvgCost(answer.actions);
  if (finalAvgCost !== null) {
    reviewCostLine = reviewCandleSeries.createPriceLine({
      price: finalAvgCost, color: "#f0d264", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: "成本",
    });
  }
  const latestClose = answer.ohlcv[answer.ohlcv.length - 1].close;
  reviewLatestLine = reviewCandleSeries.createPriceLine({
    price: latestClose, color: "#8b93a7", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted,
    axisLabelVisible: true, title: "最新价",
  });

  reviewChart.timeScale().fitContent();

  const equityData = answer.equity_curve.map((v, i) => ({ time: answer.ohlcv[i].trade_date, value: v }));
  equityLineSeries.setData(equityData);
  equityChart.timeScale().fitContent();

  renderStats(answer.performance, state.totalCapital);
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

el.maPeriodInput.addEventListener("change", () => rebuildBlindMaSeries());
el.sizeMinus.addEventListener("click", () => {
  state.sizeCheng = Math.max(1, state.sizeCheng - 1);
  updateSizeLabel();
});
el.sizePlus.addEventListener("click", () => {
  state.sizeCheng = Math.min(10, state.sizeCheng + 1);
  updateSizeLabel();
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
