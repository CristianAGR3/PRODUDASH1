const orderModel = window.ProduOrders;
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const MODULES = {
  orders: {
    eyebrow: "ACTIVIDAD",
    title: "Pedidos y notificaciones",
    subtitle: "Revisa los últimos ingresos y escucha el reporte completo del asistente.",
  },
  search: {
    eyebrow: "CONSULTA",
    title: "Buscador avanzado",
    subtitle: "Filtra por cliente, ticket, estatus, operador o fecha.",
  },
  cutters: {
    eyebrow: "PRODUCCIÓN",
    title: "Operadores",
    subtitle: "Avance, carga de trabajo y pedidos terminados por responsable.",
  },
  charts: {
    eyebrow: "ANÁLISIS",
    title: "Gráficas de operadores",
    subtitle: "Distribución de pedidos y estado operativo por responsable.",
  },
};

const CHART_COLORS = ["#3f7f63", "#b78336", "#8f3630", "#557aa4", "#80629d", "#4f9698", "#bc6d45", "#728048"];
const DATA_REFRESH_INTERVAL = 75000;
const DATA_URL = ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)
  ? "data/produccion.json"
  : "https://api.github.com/repos/CristianAGR3/PRODUDASH1/contents/data/produccion.json?ref=main";

const state = {
  dataset: { meta: {}, orders: [] },
  query: "",
  movement: "Todos",
  cutter: "Todos",
  production: "Todos",
  dateFrom: "",
  dateTo: "",
  activeNotificationId: "",
  activeModule: "orders",
};

let deferredInstallPrompt = null;
let assistantUtterance = null;
let tonyRecognition = null;
let tonyVoiceEnabled = false;
let tonyRecognitionRunning = false;
let tonyRestartTimer = null;
let tonyNudgeTimer = null;
let tonyChatTurn = 0;
let tonyDragged = false;
let dataRefreshInFlight = null;
let dataRefreshTimer = null;
let serviceWorkerReloaded = false;

function normalize(value) {
  return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatTimestamp(value) {
  if (!value) return "Sin registro";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("es-MX", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "America/Mexico_City",
  }).format(date);
}

function showMessage(tone, message) {
  const node = $("#refreshMessage");
  node.className = `publish-notice ${tone}`;
  node.innerHTML = `<span aria-hidden="true"></span>${escapeHtml(message)}`;
  node.hidden = false;
}

function applyTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.setAttribute("content", dark ? "#090d0a" : "#efe3cc");
  $("#themeBtn").setAttribute("aria-pressed", String(dark));
  $("#themeIcon").textContent = dark ? "☀" : "☾";
  $("#themeBtnText").textContent = dark ? "Modo claro" : "Modo oscuro";
  try { localStorage.setItem("produ-theme", dark ? "dark" : "light"); } catch (error) { /* Preferencia opcional. */ }
}

function unique(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "es-MX"));
}

function isCr(order) {
  return order.movement === "CR" || order.movement === "Cliente recoge";
}

function movementValue(order) {
  return isCr(order) ? "CR" : order.movement;
}

function isFinished(order) {
  return ["Terminado", "Entregado a cliente"].includes(orderModel.status(order));
}

function isDelivered(order) {
  return orderModel.status(order) === "Entregado a cliente";
}

function isQueuedForDelivery(order) {
  return orderModel.status(order) === "En resguardo";
}

function isUnassignedCutter(value) {
  return ["", "pendiente", "sin asignar", "sin registro"].includes(normalize(value).trim());
}

function productionValue(order) {
  return orderModel.status(order).toUpperCase();
}

function orderDate(order) {
  const recorded = order.created_at || order.recordAt;
  if (!recorded) return "";
  const date = new Date(recorded);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Mexico_City", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const part = type => parts.find(p => p.type === type).value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function filteredOrders() {
  const query = normalize(state.query.trim());
  return state.dataset.orders.filter((order) => {
    const date = orderDate(order);
    const searchable = `${order.ticket || order.id} ${order.client} ${order.operator || order.cutter} ${order.receiver || ""} ${order.driver || ""}`;
    return (!query || normalize(searchable).includes(query))
      && (state.movement === "Todos" || movementValue(order) === state.movement)
      && (state.cutter === "Todos" || normalize(order.cutter) === normalize(state.cutter))
      && (state.production === "Todos" || productionValue(order) === state.production)
      && (!state.dateFrom || (date && date >= state.dateFrom))
      && (!state.dateTo || (date && date <= state.dateTo));
  });
}

function metrics(orders) { return orderModel.metrics(orders); }

function renderHeader() {
  const meta = state.dataset.meta;
  $("#updatedAt").textContent = formatTimestamp(meta.generatedAt);
  $("#sourceName").textContent = "SQLite · GitHub";
  $("#footerMeta").textContent = `PRODU Control · ${meta.totalOrders || 0} pedidos · revisión ${meta.revision || 0}`;
}

function renderFilterOptions() {
  const select = $("#cutterFilter");
  const current = state.cutter;
  const cutters = unique(state.dataset.orders.map((order) => order.cutter));
  select.innerHTML = `<option value="Todos">Todos los operadores</option>${cutters.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
  select.value = cutters.includes(current) ? current : "Todos";
  if (!cutters.includes(current)) state.cutter = "Todos";
}

function renderAdvancedCounts() {
  const values = metrics(state.dataset.orders);
  $("#advancedCrFinished").textContent = values.process;
  $("#advancedCrProcess").textContent = values.stored;
  $("#advancedShipmentFinished").textContent = values.finished;
  $("#advancedShipmentProcess").textContent = values.delivered;
  $$(".advanced-status-grid button").forEach(button => {
    const selected = button.dataset.advancedStatus === state.production;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function renderKpis(v) {
  const rate = v.total ? Math.round(v.completed / v.total * 100) : 0;
  const processRate = v.total ? v.process / v.total * 100 : 0;
  const storedRate = v.total ? v.stored / v.total * 100 : 0;
  const finishedRate = v.total ? v.finished / v.total * 100 : 0;
  const values = { kpiTotal: v.total, kpiPickup: v.process, kpiShipments: v.stored, kpiFinished: v.finished, kpiDelivered: v.delivered, kpiPending: v.pending };
  Object.entries(values).forEach(([id, value]) => $("#" + id).textContent = String(value).padStart(2, "0"));
  $("#kpiPickupNote").textContent = "Producción en curso";
  $("#kpiFinishedNote").textContent = "Listos, pendientes de entrega";
  $("#kpiDeliveredNote").textContent = "Entregados a cliente";
  ["ordersCompletionBadge", "completionBadge"].forEach(id => $("#" + id).textContent = rate + "%");
  ["ordersCompletionProgress", "completionProgress"].forEach(id => {
    $("#" + id + " span").style.width = rate + "%";
    $("#" + id).setAttribute("aria-label", `${rate}% de producción completada`);
  });
  $("#ordersFinishedCopy").textContent = `${v.completed} con producción completada`;
  $("#ordersProcessCopy").textContent = `${v.process + v.stored} en proceso o resguardo`;
  $("#ordersFinishedStat").textContent = v.finished;
  $("#ordersProcessStat").textContent = v.process;
  $("#ordersDeliveredStat").textContent = v.delivered;
  $("#finishedCopy").textContent = `${v.completed} con producción completada`;
  $("#pendingCopy").textContent = `${v.pending} pendientes de entrega`;
  $("#routeCount").textContent = v.total;
  $("#donutTotal").textContent = v.total;
  $("#routeDonut").style.background = v.total ? `conic-gradient(#b78336 0 ${processRate}%, #80629d ${processRate}% ${processRate + storedRate}%, #3f7f63 ${processRate + storedRate}% ${processRate + storedRate + finishedRate}%, #557aa4 ${processRate + storedRate + finishedRate}% 100%)` : "conic-gradient(#d8ded8 0 100%)";
  $("#routeDonut").setAttribute("aria-label", `${v.process} en proceso, ${v.stored} en resguardo, ${v.finished} terminados, ${v.delivered} entregados`);
  $("#pickupLegend").textContent = `${v.process} pedidos`;
  $("#shipmentLegend").textContent = `${v.stored} pedidos`;
  $("#finishedLegend").textContent = `${v.finished} pedidos`;
  $("#deliveredLegend").textContent = `${v.delivered} pedidos`;
  $("#pickupPercent").textContent = Math.round(processRate) + "%";
  $("#shipmentPercent").textContent = Math.round(storedRate) + "%";
  $("#deliveredStrip").textContent = v.delivered;
  $("#pendingDeliveryStrip").textContent = v.pending;
}

function orderRows(orders, emptyMessage) {
  if (!orders.length) return `<tr><td colspan="7" class="empty-state">${escapeHtml(emptyMessage)}</td></tr>`;
  return orders.map((order) => {
    const ticket = order.ticket || order.id || "—";
    const operator = order.operator || order.cutter || "SIN REGISTRO";
    const status = operationalStatus(order);
    const statusClass = isDelivered(order) ? "delivered" : status === "Terminado" ? "done" : "pending";
    const created = order.created_at || order.recordAt;
    const updated = order.updated_at || order.updatedAt;
    const deliveredAt = order.delivered_at || order.deliveredAt;
    return `<tr>
      <td data-label="Ticket"><strong class="order-id">#${escapeHtml(ticket)}</strong></td>
      <td data-label="Cliente"><strong class="client-name">${escapeHtml(order.client || "SIN REGISTRO")}</strong></td>
      <td data-label="Operador">${escapeHtml(operator)}</td>
      <td data-label="Estatus"><span class="status ${statusClass}"><i></i>${escapeHtml(status)}</span></td>
      <td data-label="Registro">${escapeHtml(formatTimestamp(created))}</td>
      <td data-label="Último cambio">${escapeHtml(formatTimestamp(updated))}</td>
      <td data-label="Entrega">${deliveredAt ? escapeHtml(formatTimestamp(deliveredAt)) : "—"}</td>
    </tr>`;
  }).join("");
}

function operationalStatus(order) {
  return orderModel.status(order);
}

function formatGroupDate(value) {
  if (!value) return "Sin fecha";
  const date = new Date(`${value}T12:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  const label = new Intl.DateTimeFormat("es-MX", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function groupDescription(mode, key, groupOrders) {
  if (mode === "date") return key ? `Pedidos registrados el ${groupOrders[0]?.date || key}` : "Pedidos sin fecha de registro";
  if (mode === "movement") return key === "CR" ? "Pedidos que recoge el cliente" : "Pedidos programados para salida de producción";
  return {
    "En proceso": "Producción en curso",
    Terminado: "Producción terminada; pendiente de entrega",
    "En resguardo": "Pedidos bajo resguardo",
    "Entregado a cliente": "Entrega completada",
  }[key] || "Estado operativo del pedido";
}

function buildOrderGroups(mode, orders = state.dataset.orders) {
  const grouped = new Map();
  orders.forEach((order) => {
    let key = orderDate(order);
    if (mode === "status") key = operationalStatus(order);
    if (mode === "movement") key = movementValue(order) || "SIN REGISTRO";
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(order);
  });

  const statusOrder = { "En proceso": 0, "En resguardo": 1, Terminado: 2, "Entregado a cliente": 3 };
  const movementOrder = { CR: 0, "Envío producción": 1, "SIN REGISTRO": 2 };
  return [...grouped.entries()].map(([key, groupedOrders]) => ({
    key,
    label: mode === "date" ? formatGroupDate(key) : key,
    description: groupDescription(mode, key, groupedOrders),
    orders: groupedOrders,
  })).sort((a, b) => {
    if (mode === "date") return String(b.key).localeCompare(String(a.key));
    if (mode === "status") return (statusOrder[a.key] ?? 99) - (statusOrder[b.key] ?? 99);
    return (movementOrder[a.key] ?? 99) - (movementOrder[b.key] ?? 99) || a.label.localeCompare(b.label, "es-MX");
  });
}

function orderDisclosure(order) {
  const status = operationalStatus(order);
  const ticket = order.ticket || order.id || "—";
  const operator = order.operator || order.cutter || "SIN REGISTRO";
  const created = order.created_at || order.recordAt;
  const updated = order.updated_at || order.updatedAt;
  const deliveredAt = order.delivered_at || order.deliveredAt;
  const statusClass = isDelivered(order) ? "delivered" : status === "Terminado" ? "done" : "pending";
  return `<details class="order-record">
    <summary>
      <span class="order-record-id"><small>Ticket</small><strong>#${escapeHtml(ticket)}</strong></span>
      <span class="order-record-client"><strong>${escapeHtml(order.client || "SIN REGISTRO")}</strong><small>Operador: ${escapeHtml(operator)}</small></span>
      <span class="order-record-tags">
        <span class="status ${statusClass}"><i></i>${escapeHtml(status)}</span>
      </span>
      <span class="order-record-action"><b>Ver detalle</b><i aria-hidden="true">⌄</i></span>
    </summary>
    <div class="order-record-details">
      <div><small>Ticket</small><strong>#${escapeHtml(ticket)}</strong></div>
      <div><small>Cliente</small><strong>${escapeHtml(order.client || "SIN REGISTRO")}</strong></div>
      <div><small>Operador</small><strong>${escapeHtml(operator)}</strong></div>
      <div><small>Estatus</small><strong>${escapeHtml(status)}</strong></div>
      <div><small>Registro</small><strong>${escapeHtml(formatTimestamp(created))}</strong></div>
      <div><small>Último cambio</small><strong>${escapeHtml(formatTimestamp(updated))}</strong></div>
      <div><small>Entrega</small><strong>${deliveredAt ? escapeHtml(formatTimestamp(deliveredAt)) : "—"}</strong></div>
    </div>
  </details>`;
}

function latestOrders(orders, limit = 5) {
  return orders.map((order, index) => {
    const timestamp = new Date(order.recordAt || "").getTime();
    return { order, index, timestamp: Number.isNaN(timestamp) ? 0 : timestamp };
  }).sort((a, b) => b.timestamp - a.timestamp || a.index - b.index).slice(0, limit).map((item) => item.order);
}

function stageClass(order) {
  return normalize(operationalStatus(order)).replace(/\s+/g, "-");
}

function notificationItem(order, index) {
  const selected = String(order.id) === state.activeNotificationId;
  const shipment = movementValue(order) === "Envío producción";
  return `<button class="recent-notification-item ${selected ? "selected" : ""}" type="button" data-notification-id="${escapeHtml(order.id)}" aria-pressed="${selected}">
    <span class="notification-sequence">${String(index + 1).padStart(2, "0")}</span>
    <span class="notification-order-copy">
      <small>Pedido #${escapeHtml(order.id)} · ${escapeHtml(order.date)} · ${escapeHtml(order.time)} h</small>
      <strong>${escapeHtml(order.client)}</strong>
      <span>${escapeHtml(order.cutter || "Operador pendiente")}</span>
    </span>
    <span class="notification-tags">
      <span class="movement-pill ${shipment ? "shipment" : "pickup"}">${escapeHtml(movementValue(order))}</span>
      <span class="order-stage-tag stage-${stageClass(order)}">${escapeHtml(operationalStatus(order))}</span>
    </span>
    <span class="notification-arrow" aria-hidden="true">→</span>
  </button>`;
}

function assistantCounts(orders) {
  const v = metrics(orders);
  return { total: v.total, pending: v.pending, process: v.process, queued: v.stored, finished: v.finished, delivered: v.delivered };
}

function assistantMetric(label, value, tone) {
  return `<div class="assistant-metric ${tone}"><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></div>`;
}

function orderReportLine(order, index) {
  return `<li>
    <span>${index + 1}</span>
    <div>
      <strong>Pedido #${escapeHtml(order.id)} · ${escapeHtml(order.client)}</strong>
      <p>Movimiento: ${escapeHtml(movementValue(order))}. Operador: ${escapeHtml(order.cutter || "SIN REGISTRO")}. Producción: ${escapeHtml(productionValue(order))}. Entrega: ${escapeHtml(order.delivery || "SIN REGISTRO")}. Registro: ${escapeHtml(order.date)} a las ${escapeHtml(order.time)} h.</p>
    </div>
  </li>`;
}

function renderAssistant(recent) {
  const orders = state.dataset.orders;
  const selected = orders.find((order) => String(order.id) === state.activeNotificationId);
  const listenLabel = $("#listenAssistantBtn span:last-child");
  if (selected) {
    $("#assistantContext").textContent = "DETALLE DE NOTIFICACIÓN";
    $("#assistantHeadline").textContent = `Pedido #${selected.id}`;
    $("#assistantMetrics").innerHTML = [
      assistantMetric("Movimiento", movementValue(selected), "blue"),
      assistantMetric("Operador", selected.cutter || "SIN REGISTRO", "gold"),
      assistantMetric("Producción", productionValue(selected), "red"),
      assistantMetric("Entrega", selected.delivery || "SIN REGISTRO", "green"),
    ].join("");
    $("#assistantMessage").innerHTML = `<div class="assistant-selected-report">
      <p class="assistant-greeting">Notificación completa</p>
      <h4>${escapeHtml(selected.client)}</h4>
      <p>El pedido <strong>#${escapeHtml(selected.id)}</strong> fue recibido por <strong>${escapeHtml(selected.receiver || "SIN REGISTRO")}</strong>. Su movimiento es <strong>${escapeHtml(movementValue(selected))}</strong> y el operador responsable es <strong>${escapeHtml(selected.cutter || "SIN REGISTRO")}</strong>.</p>
      <p>Producción: <strong>${escapeHtml(productionValue(selected))}</strong>. Entrega: <strong>${escapeHtml(selected.delivery || "SIN REGISTRO")}</strong>. Chofer: <strong>${escapeHtml(selected.driver || "SIN REGISTRO")}</strong>.</p>
      <p class="assistant-record-time">Registrado el ${escapeHtml(selected.date)} a las ${escapeHtml(selected.time)} h.</p>
    </div>`;
    $("#assistantSummaryBtn").hidden = false;
    if (listenLabel) listenLabel.textContent = "Escuchar detalle";
    return;
  }

  state.activeNotificationId = "";
  const counts = assistantCounts(orders);
  $("#assistantContext").textContent = "RESUMEN GENERAL";
  $("#assistantHeadline").textContent = orders.length ? `${orders.length} pedidos bajo seguimiento` : "Sin pedidos registrados";
  $("#assistantMetrics").innerHTML = [
    assistantMetric("Total", counts.total, "blue"),
    assistantMetric("Pendientes", counts.pending, "red"),
    assistantMetric("En resguardo", counts.queued, "gold"),
    assistantMetric("Entregados", counts.delivered, "green"),
  ].join("");
  $("#assistantMessage").innerHTML = recent.length ? `<div class="assistant-complete-report">
    <p class="assistant-greeting">Reporte completo de actividad reciente</p>
    <p>Tienes <strong>${counts.process} en proceso</strong>, <strong>${counts.queued} en resguardo</strong>, <strong>${counts.finished} terminados</strong> y <strong>${counts.delivered} entregados</strong>. Estos son los cinco ingresos más recientes:</p>
    <ol class="assistant-report-list">${recent.map(orderReportLine).join("")}</ol>
  </div>` : `<p>No hay notificaciones de pedidos por el momento.</p>`;
  $("#assistantSummaryBtn").hidden = true;
  if (listenLabel) listenLabel.textContent = "Escuchar las 5 notificaciones";
}

function renderOrdersModule() {
  const orders = state.dataset.orders;
  const recent = latestOrders(orders);
  if (!orders.some((order) => String(order.id) === state.activeNotificationId)) state.activeNotificationId = "";
  $("#recentNotificationsCount").textContent = `${recent.length} ${recent.length === 1 ? "reciente" : "recientes"}`;
  $("#recentNotifications").innerHTML = recent.length
    ? recent.map(notificationItem).join("")
    : `<p class="empty-state">No hay pedidos recientes.</p>`;
  renderAssistant(recent);

  const speechAvailable = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  $("#listenAssistantBtn").disabled = !speechAvailable || !recent.length;
  if (!speechAvailable) $("#assistantSpeechStatus").textContent = "La lectura en voz alta no está disponible en este navegador.";
}

function renderSearchModule() {
  const orders = filteredOrders();
  const hasFilters = Boolean(state.query || state.movement !== "Todos" || state.cutter !== "Todos" || state.production !== "Todos" || state.dateFrom || state.dateTo);
  $("#filterSummary").textContent = hasFilters
    ? `Resultado: ${orders.length} de ${state.dataset.orders.length} pedidos`
    : `Vista general · ${state.dataset.orders.length} pedidos · Último registro ${formatTimestamp(state.dataset.meta.lastRecordAt)}`;
  $("#searchCountLabel").textContent = `${orders.length} ${orders.length === 1 ? "resultado" : "resultados"}`;
  $("#resetBtn").disabled = !hasFilters;
  $("#searchOrdersBody").innerHTML = orderRows(orders, "No hay pedidos que coincidan con la búsqueda.");
  renderAdvancedCounts();
}

function renderCutterModule() {
  const stats = orderModel.ranks(state.dataset.orders);
  $("#cutterSummary").innerHTML = `<div><span>Operadores activos</span><strong>${stats.length}</strong></div><div><span>Con pendientes</span><strong>${stats.filter(s => s.pending).length}</strong></div><div><span>Con entregas</span><strong>${stats.filter(s => s.delivered).length}</strong></div>`;
  $("#cutterGrid").innerHTML = stats.length ? stats.map((s, index) => `
    <article class="cutter-card"><div class="cutter-card-head"><span class="avatar ${index % 2 ? "avatar-green" : "avatar-blue"}">${escapeHtml(s.name.charAt(0))}</span><div><p>OPERADOR</p><h3>${escapeHtml(s.name)}</h3></div><strong class="cutter-rate">${s.total}</strong></div>
    <div class="cutter-card-stats"><div><span>Total</span><strong>${s.total}</strong></div><div><span>Pendientes</span><strong>${s.pending}</strong></div><div><span>En proceso</span><strong>${s.process}</strong></div><div><span>En resguardo</span><strong>${s.stored}</strong></div><div><span>Terminados</span><strong>${s.finished}</strong></div><div><span>Entregados</span><strong>${s.delivered}</strong></div></div>
    <button class="view-cutter-orders" type="button" data-cutter-name="${escapeHtml(s.name)}">Ver pedidos de ${escapeHtml(s.name)} →</button></article>`).join("") : `<div class="empty-state">No hay operadores registrados.</div>`;
}

function pieBackground(items) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (!total) return "conic-gradient(#d8ded8 0 100%)";
  let cursor = 0;
  const segments = items.map((item) => {
    const start = (cursor / total) * 100;
    cursor += item.value;
    const end = (cursor / total) * 100;
    return `${item.color} ${start}% ${end}%`;
  });
  return `conic-gradient(${segments.join(", ")})`;
}

function cutterChartStats(orders) {
  return orderModel.ranks(orders).map((s, i) => ({ ...s, queued: s.stored, color: CHART_COLORS[i % CHART_COLORS.length] }));
}

function renderChartsModule() {
  const v = metrics(state.dataset.orders);
  const stats = cutterChartStats(state.dataset.orders);
  const leader = stats[0];
  $("#chartLeaderName").textContent = leader ? leader.name : "Sin datos";
  $("#chartLeaderCopy").textContent = leader ? `${leader.total} pedidos · ${leader.pending} pendientes` : "0 pedidos";
  $("#chartActiveCutters").textContent = stats.length;
  $("#chartDeliveredTotal").textContent = v.delivered;
  $("#chartDeliveredCopy").textContent = `${v.pending} pendientes de entrega`;
  $("#cutterPieTotal").textContent = v.total;
  $("#cutterPieCount").textContent = `${v.total} pedidos`;
  $("#cutterPie").style.background = pieBackground(stats.map(s => ({ value: s.total, color: s.color })));
  $("#cutterPie").setAttribute("aria-label", stats.map(s => `${s.name}: ${s.total}`).join(", ") || "Sin pedidos");
  $("#cutterPieLegend").innerHTML = stats.map((s, i) => `<div class="pie-legend-row ${i ? "" : "leader"}"><i style="background:${s.color}"></i><p><strong>${escapeHtml(s.name)}${i ? "" : "<em>Más pedidos</em>"}</strong><small>${s.pending} pendientes</small></p><b>${s.total}</b></div>`).join("") || `<p class="chart-empty">No hay datos para mostrar.</p>`;
  const stages = [{ label: "En proceso", value: v.process, color: "#b78336" }, { label: "En resguardo", value: v.stored, color: "#80629d" }, { label: "Terminado", value: v.finished, color: "#3f7f63" }, { label: "Entregado a cliente", value: v.delivered, color: "#557aa4" }];
  $("#deliveryPieTotal").textContent = v.total;
  $("#deliveryPieRate").textContent = (v.total ? Math.round(v.delivered / v.total * 100) : 0) + "%";
  $("#deliveryPie").style.background = pieBackground(stages);
  $("#deliveryPie").setAttribute("aria-label", stages.map(s => `${s.label}: ${s.value}`).join(", "));
  $("#deliveryPieLegend").innerHTML = stages.map(s => `<div class="pie-legend-row"><i style="background:${s.color}"></i><p><strong>${s.label}</strong></p><b>${s.value}</b></div>`).join("");
  $("#chartCutterGrid").innerHTML = stats.map((s, i) => `<article class="chart-cutter-card"><div class="chart-cutter-head"><span class="chart-avatar" style="background:${s.color}22;color:${s.color}">${escapeHtml(s.name.charAt(0))}</span><div><strong>${escapeHtml(s.name)}</strong><small>${s.pending} pendientes de entrega</small></div><b>${s.total}</b></div><div class="chart-stage-grid"><span><b>${s.process}</b><small>En proceso</small></span><span><b>${s.stored}</b><small>En resguardo</small></span><span><b>${s.finished}</b><small>Terminado</small></span><span><b>${s.delivered}</b><small>Entregados</small></span></div></article>`).join("") || `<p class="chart-empty">No hay operadores registrados.</p>`;
}

function spokenOrderReport(order, index) {
  const prefix = Number.isInteger(index) ? `Notificación ${index + 1}. ` : "";
  return `${prefix}Pedido ${order.id}, cliente ${order.client}. Movimiento ${movementValue(order)}. Operador ${order.cutter || "sin registro"}. Producción ${productionValue(order)}. Entrega ${order.delivery || "sin registro"}. Registrado el ${order.date} a las ${order.time}.`;
}

function assistantNarration() {
  const orders = state.dataset.orders;
  const recent = latestOrders(orders);
  const selected = orders.find((order) => String(order.id) === state.activeNotificationId);
  if (selected) {
    return `Hola, soy Tony. ${spokenOrderReport(selected)} Recibió ${selected.receiver || "sin registro"}. Chofer ${selected.driver || "sin registro"}.`;
  }
  if (!recent.length) return "No hay notificaciones de pedidos por el momento.";
  const counts = assistantCounts(orders);
  const intro = `Hola, soy Tony. Este es tu reporte completo. Hay ${counts.total} pedidos bajo seguimiento: ${counts.process} en proceso, ${counts.queued} en resguardo, ${counts.finished} terminados y ${counts.delivered} entregados. Los cinco ingresos más recientes son los siguientes.`;
  return `${intro} ${recent.map(spokenOrderReport).join(" ")}`;
}

function setAssistantSpeaking(active, message) {
  $(".virtual-assistant-panel")?.classList.toggle("speaking", active);
  $("#listenAssistantBtn").disabled = active || !latestOrders(state.dataset.orders).length;
  $("#stopAssistantBtn").hidden = !active;
  $("#assistantSpeechStatus").textContent = message;
  setTonyCompanionMood(active ? "speaking" : (tonyRecognitionRunning ? "listening" : "idle"), message);
}

function setAssistantThinking(active) {
  $(".virtual-assistant-panel")?.classList.toggle("thinking", active);
  if (!assistantUtterance && !tonyRecognitionRunning) setTonyCompanionMood(active ? "thinking" : "idle", active ? "Estoy revisando los datos…" : "Listo para ayudarte");
}

function stopAssistantSpeech(message = "Tony detuvo la lectura. Puedes seleccionar otra notificación.") {
  assistantUtterance = null;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  setAssistantSpeaking(false, message);
  queueTonyRecognition();
}

function speakTonyText(text) {
  if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
    $("#assistantSpeechStatus").textContent = "La lectura en voz alta no está disponible en este navegador.";
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "es-MX";
  utterance.rate = 0.97;
  utterance.pitch = 1.08;
  utterance.volume = 0.44;
  const spanishVoice = window.speechSynthesis.getVoices().find((voice) => normalize(voice.lang).startsWith("es-mx"))
    || window.speechSynthesis.getVoices().find((voice) => normalize(voice.lang).startsWith("es"));
  if (spanishVoice) utterance.voice = spanishVoice;
  assistantUtterance = utterance;
  if (tonyRecognitionRunning && tonyRecognition) tonyRecognition.abort();
  utterance.onstart = () => {
    if (assistantUtterance === utterance) setAssistantSpeaking(true, "Tony está leyendo las notificaciones…");
  };
  utterance.onend = () => {
    if (assistantUtterance !== utterance) return;
    assistantUtterance = null;
    setAssistantSpeaking(false, "Tony terminó la lectura. Puedes seleccionar un pedido para escuchar su detalle.");
    queueTonyRecognition();
  };
  utterance.onerror = () => {
    if (assistantUtterance !== utterance) return;
    assistantUtterance = null;
    setAssistantSpeaking(false, "No fue posible completar la lectura. Inténtalo nuevamente.");
    queueTonyRecognition();
  };
  window.speechSynthesis.speak(utterance);
}

function speakAssistant() {
  speakTonyText(assistantNarration());
}

function normalizeVoiceText(value) {
  return normalize(value).replace(/[^a-z0-9\s]/g, " ").replace(/\s+/g, " ").trim();
}

function voiceRequest(transcript) {
  const text = normalizeVoiceText(transcript);
  const wake = text.match(/\b(?:oye|hey)?\s*ton[yi]\b/);
  if (!wake) return null;
  return text.slice((wake.index || 0) + wake[0].length).trim();
}

function orderedOrders() {
  return latestOrders(state.dataset.orders, state.dataset.orders.length);
}

function findTonyOrder(command) {
  const orders = orderedOrders();
  const number = command.match(/\b\d{3,}\b/)?.[0];
  if (number) {
    const exact = orders.find((order) => String(order.id) === number);
    if (exact) return { order: exact, matches: 1, query: number };
    const partial = orders.filter((order) => String(order.id).includes(number));
    if (partial.length) return { order: partial[0], matches: partial.length, query: number };
  }

  const directMatches = orders.filter((order) => {
    const client = normalizeVoiceText(order.client);
    return client.length > 2 && command.includes(client);
  });
  if (directMatches.length) return { order: directMatches[0], matches: directMatches.length, query: directMatches[0].client };

  const stopWords = new Set([
    "dime", "informacion", "sobre", "pedido", "pedidos", "numero", "nombre", "cliente", "del", "de", "la", "el", "los", "las",
    "por", "un", "una", "favor", "quiero", "saber", "datos", "dame", "busca", "buscar", "encuentra", "muestrame", "cuentame",
  ]);
  const queryTokens = command.split(" ").filter((token) => token.length > 2 && !stopWords.has(token));
  if (!queryTokens.length) return null;

  const candidates = orders.map((order) => {
    const clientTokens = new Set(normalizeVoiceText(order.client).split(" ").filter((token) => token.length > 2));
    const score = queryTokens.reduce((total, token) => total + (clientTokens.has(token) ? 2 : [...clientTokens].some((clientToken) => clientToken.startsWith(token) || token.startsWith(clientToken)) ? 1 : 0), 0);
    return { order, score };
  }).filter((candidate) => candidate.score > 0).sort((a, b) => b.score - a.score);
  if (!candidates.length) return null;
  const topScore = candidates[0].score;
  const best = candidates.filter((candidate) => candidate.score === topScore);
  return { order: best[0].order, matches: best.length, query: queryTokens.join(" ") };
}

function showTonyTranscript(label, text) {
  const node = $("#tonyTranscript");
  node.hidden = false;
  node.textContent = `${label}: ${text}`;
}

function tonyStatusAnswer(command) {
  const counts = assistantCounts(state.dataset.orders);
  if (!/\b(cuantos|cuantas|cuanto|estado)\b/.test(command)) return null;
  if (command.includes("pendiente")) return `Hay ${counts.pending} pedidos pendientes.`;
  if (command.includes("resguardo") || command.includes("fila")) return `Hay ${counts.queued} pedidos en resguardo.`;
  if (command.includes("proceso")) return `Hay ${counts.process} pedidos en proceso.`;
  if (command.includes("terminado")) return `Hay ${counts.finished} pedidos terminados.`;
  if (command.includes("entregado")) return `Hay ${counts.delivered} pedidos entregados.`;
  return `Hay ${counts.total} pedidos en total: ${counts.process} en proceso, ${counts.queued} en resguardo, ${counts.finished} terminados y ${counts.delivered} entregados.`;
}

function handleTonyCommand(transcript) {
  const command = voiceRequest(transcript);
  if (command === null) {
    $("#tonyCommandStatus").textContent = "Esperando “Oye Tony”";
    showTonyTranscript("Escuché", transcript);
    return;
  }
  showTonyTranscript("Comando", transcript);
  askTony(command, { speak: true });
}

function updateTonyVoiceUi(message) {
  const button = $("#voiceCommandBtn");
  button.classList.toggle("active", tonyVoiceEnabled);
  button.setAttribute("aria-pressed", String(tonyVoiceEnabled));
  button.querySelector("strong").textContent = tonyVoiceEnabled ? "Desactivar “Oye Tony”" : "Activar “Oye Tony”";
  button.querySelector("small").textContent = tonyVoiceEnabled ? "Tony está atento a tu voz" : "Toca una vez para conversar";
  $(".virtual-assistant-panel")?.classList.toggle("listening", tonyRecognitionRunning);
  $("#tonyCommandStatus").textContent = message || (tonyVoiceEnabled ? "Escuchando…" : "Desactivado");
  const companionVoice = $("#tonyVoiceToggle");
  if (companionVoice) companionVoice.setAttribute("aria-pressed", String(tonyVoiceEnabled));
  if (!assistantUtterance) setTonyCompanionMood(tonyRecognitionRunning ? "listening" : "idle", message || (tonyVoiceEnabled ? "Tony está atento a tu voz" : "Listo para ayudarte"));
}

function queueTonyRecognition(delay = 550) {
  clearTimeout(tonyRestartTimer);
  if (!tonyVoiceEnabled || assistantUtterance || document.hidden || !tonyRecognition) return;
  tonyRestartTimer = setTimeout(() => startTonyRecognition(), delay);
}

function startTonyRecognition() {
  if (!tonyVoiceEnabled || tonyRecognitionRunning || assistantUtterance || !tonyRecognition || document.hidden) return;
  try {
    tonyRecognition.start();
  } catch (error) {
    if (error.name !== "InvalidStateError") updateTonyVoiceUi("No fue posible activar el micrófono");
  }
}

function disableTonyVoice(message = "Desactivado") {
  tonyVoiceEnabled = false;
  clearTimeout(tonyRestartTimer);
  if (tonyRecognitionRunning && tonyRecognition) tonyRecognition.abort();
  tonyRecognitionRunning = false;
  updateTonyVoiceUi(message);
}

function initializeTonyVoice() {
  const VoiceRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const button = $("#voiceCommandBtn");
  if (!VoiceRecognition || !window.isSecureContext) {
    button.disabled = true;
    updateTonyVoiceUi(window.isSecureContext ? "No disponible en este navegador" : "Requiere una conexión segura");
    return;
  }

  tonyRecognition = new VoiceRecognition();
  tonyRecognition.lang = "es-MX";
  tonyRecognition.continuous = true;
  tonyRecognition.interimResults = true;
  tonyRecognition.maxAlternatives = 1;
  tonyRecognition.onstart = () => {
    tonyRecognitionRunning = true;
    updateTonyVoiceUi("Escuchando “Oye Tony”…");
  };
  tonyRecognition.onresult = (event) => {
    let interim = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index][0].transcript.trim();
      if (event.results[index].isFinal) handleTonyCommand(transcript);
      else interim += `${transcript} `;
    }
    if (interim.trim()) showTonyTranscript("Escuchando", interim.trim());
  };
  tonyRecognition.onerror = (event) => {
    if (["not-allowed", "service-not-allowed"].includes(event.error)) {
      disableTonyVoice("Permiso de micrófono denegado");
      return;
    }
    if (["audio-capture", "network"].includes(event.error)) {
      disableTonyVoice(event.error === "audio-capture" ? "No se encontró un micrófono" : "Reconocimiento de voz sin conexión");
      return;
    }
    if (!['aborted', 'no-speech'].includes(event.error)) updateTonyVoiceUi("No pude entenderte; inténtalo otra vez");
  };
  tonyRecognition.onend = () => {
    tonyRecognitionRunning = false;
    updateTonyVoiceUi(tonyVoiceEnabled ? "Preparando el micrófono…" : "Desactivado");
    queueTonyRecognition();
  };

  button.addEventListener("click", () => {
    if (tonyVoiceEnabled) {
      disableTonyVoice();
      return;
    }
    tonyVoiceEnabled = true;
    updateTonyVoiceUi("Solicitando acceso al micrófono…");
    startTonyRecognition();
  });
}

function setTonyCompanionMood(mood = "idle", status = "") {
  const orbit = $("#tonyOrbit");
  if (!orbit) return;
  orbit.dataset.mood = mood;
  const statusNode = $("#tonyCompanionStatus");
  if (statusNode && status) statusNode.textContent = status;
}

function appendTonyChat(role, text, { thinking = false } = {}) {
  const conversation = $("#tonyConversation");
  if (!conversation) return null;
  const message = document.createElement("div");
  message.className = `tony-chat-message ${role}${thinking ? " thinking" : ""}`;
  const bubble = document.createElement("span");
  if (thinking) {
    bubble.setAttribute("aria-label", text);
    bubble.innerHTML = "<i></i><i></i><i></i>";
  } else {
    bubble.textContent = text;
  }
  message.append(bubble);
  conversation.append(message);
  conversation.scrollTop = conversation.scrollHeight;
  return message;
}

function showTonyNudge(message, duration = 6500) {
  const nudge = $("#tonyNudge");
  const companion = $("#tonyCompanion");
  if (!nudge || !message || (companion && !companion.hidden)) return;
  window.clearTimeout(tonyNudgeTimer);
  nudge.textContent = message;
  nudge.hidden = false;
  tonyNudgeTimer = window.setTimeout(() => { nudge.hidden = true; }, duration);
}

function latestTonySummary() {
  const counts = assistantCounts(state.dataset.orders);
  const latest = latestOrders(state.dataset.orders, 1)[0];
  const lastOrder = latest ? ` El último es el pedido #${latest.id} de ${latest.client}.` : "";
  return `Hay ${counts.total} pedidos: ${counts.process} en proceso, ${counts.queued} en resguardo, ${counts.finished} terminados y ${counts.delivered} entregados.${lastOrder}`;
}

function tonyModuleFromCommand(command) {
  if (!/\b(abre|abrir|muestra|mostrar|ve|ir|cambia|cambiar)\b/.test(command)) return null;
  if (/\b(busqueda|buscador|buscar)\b/.test(command)) return "search";
  if (/\b(operador|operadores)\b/.test(command)) return "cutters";
  if (/\b(grafica|graficas|analisis)\b/.test(command)) return "charts";
  if (/\b(pedido|pedidos|inicio|actividad)\b/.test(command)) return "orders";
  return null;
}

function selectedOrderTonyAnswer(order, matches = 1) {
  const matchCopy = matches > 1 ? ` Encontré ${matches} coincidencias y te muestro la más reciente.` : "";
  return `Pedido #${order.id} de ${order.client}. Está ${operationalStatus(order).toLowerCase()}, con ${order.cutter || "operador sin asignar"}. Movimiento: ${movementValue(order)}. Entrega: ${order.delivery || "sin registro"}.${matchCopy}`;
}

function resolveTonyPrompt(rawPrompt) {
  const command = normalizeVoiceText(rawPrompt);
  if (!command) return { reply: "Escríbeme el pedido, un estado o lo que quieras revisar." };

  if (/\b(hola|buenos dias|buenas tardes|buenas noches)\b/.test(command) && command.split(" ").length < 5) {
    return { reply: "Hola. Estoy conectado a los datos de producción. Puedes pedirme un pedido, un resumen o abrir cualquier módulo." };
  }

  if (/\b(ayuda|puedes hacer|que puedes hacer|comandos)\b/.test(command)) {
    return { reply: "Puedo buscar por pedido o cliente, contar pendientes, en proceso, en resguardo, terminados o entregados; decir quién tiene mayor carga; mostrar los últimos pedidos y abrir Pedidos, Buscador, Operadores o Gráficas." };
  }

  if (/\b(resumen|notificaciones|ultimos|ultimo|recientes|reciente)\b/.test(command) && !/\bpedido\s+\d/.test(command)) {
    state.activeNotificationId = "";
    renderOrdersModule();
    setModule("orders");
    return { reply: latestTonySummary(), speech: assistantNarration() };
  }

  const requestedModule = tonyModuleFromCommand(command);
  if (requestedModule) {
    setModule(requestedModule, { focusPanel: true });
    return { reply: `Listo, abrí ${MODULES[requestedModule].title.toLowerCase()}.` };
  }

  if (/quien.*mas pedidos|mayor carga|mas carga/.test(command)) {
    const leader = cutterChartStats(state.dataset.orders)[0];
    return { reply: leader ? `El operador con más pedidos es ${leader.name}, con ${leader.total} pedidos asignados.` : "Aún no hay pedidos asignados a operadores." };
  }

  if (/\b(porcentaje|avance)\b/.test(command) && /\b(entregad|terminad)\b/.test(command)) {
    const counts = assistantCounts(state.dataset.orders);
    const delivered = state.dataset.orders.length ? Math.round((counts.delivered / state.dataset.orders.length) * 100) : 0;
    const finished = state.dataset.orders.length ? Math.round((counts.finished / state.dataset.orders.length) * 100) : 0;
    return { reply: `El avance es ${finished}% terminado y ${delivered}% entregado.` };
  }

  const looksLikeOrderLookup = /\b\d{3,}\b/.test(command) || /\b(pedido|cliente|busca|buscar|encuentra|informacion|información|detalle)\b/.test(command);
  if (looksLikeOrderLookup && !/\b(cuantos|cuantas|cuanto)\b/.test(command)) {
    const result = findTonyOrder(command);
    if (result) {
      state.activeNotificationId = String(result.order.id);
      renderOrdersModule();
      setModule("orders", { focusPanel: true });
      const reply = selectedOrderTonyAnswer(result.order, result.matches);
      return { reply, speech: `${reply} Recibió ${result.order.receiver || "sin registro"}. Chofer ${result.order.driver || "sin registro"}.` };
    }
    if (/\b\d{3,}\b/.test(command) || /\b(busca|buscar|encuentra|pedido|cliente)\b/.test(command)) {
      return { reply: "No encontré ese pedido o cliente. Prueba con el número completo del pedido o un nombre más específico." };
    }
  }

  const statusAnswer = tonyStatusAnswer(command);
  if (statusAnswer) return { reply: statusAnswer };

  const byName = findTonyOrder(command);
  if (byName) {
    state.activeNotificationId = String(byName.order.id);
    renderOrdersModule();
    setModule("orders", { focusPanel: true });
    return { reply: selectedOrderTonyAnswer(byName.order, byName.matches) };
  }

  return { reply: "No estoy seguro de cómo responder eso todavía. Prueba con “resume los pedidos”, “cuántos están pendientes”, “quién tiene más pedidos” o “busca el pedido 310965”." };
}

function askTony(prompt, { speak = false } = {}) {
  const cleanPrompt = String(prompt || "").trim();
  if (!cleanPrompt) return;
  appendTonyChat("user", cleanPrompt);
  const turn = ++tonyChatTurn;
  setTonyCompanionMood("thinking", "Estoy revisando producción…");
  const thinking = appendTonyChat("assistant", "Tony está pensando", { thinking: true });
  window.setTimeout(() => {
    if (thinking?.isConnected) thinking.remove();
    const answer = resolveTonyPrompt(cleanPrompt);
    appendTonyChat("assistant", answer.reply);
    if (!assistantUtterance && !tonyRecognitionRunning) setTonyCompanionMood("idle", "Listo para ayudarte");
    if (speak) speakTonyText(answer.speech || answer.reply);
    else if (turn === tonyChatTurn) showTonyNudge(answer.reply, 5200);
  }, 280);
}

function clampTonyPosition(x, y) {
  const launcher = $("#tonyLauncher");
  const size = launcher?.getBoundingClientRect().width || 88;
  return {
    x: Math.round(Math.min(Math.max(Number(x) || 8, 8), Math.max(8, window.innerWidth - size - 8))),
    y: Math.round(Math.min(Math.max(Number(y) || 8, 8), Math.max(8, window.innerHeight - size - 8))),
  };
}

function placeTony(x, y, { save = false } = {}) {
  const orbit = $("#tonyOrbit");
  if (!orbit) return;
  const point = clampTonyPosition(x, y);
  orbit.style.left = `${point.x}px`;
  orbit.style.top = `${point.y}px`;
  orbit.classList.toggle("tony-dock-left", point.x < window.innerWidth / 2);
  orbit.classList.toggle("tony-dock-top", point.y < window.innerHeight / 2);
  if (save) {
    try { localStorage.setItem("produ-tony-position", JSON.stringify(point)); } catch (error) { /* Preferencia opcional. */ }
  }
}

function setTonyCompanionOpen(open) {
  const orbit = $("#tonyOrbit");
  const companion = $("#tonyCompanion");
  const launcher = $("#tonyLauncher");
  if (!orbit || !companion || !launcher) return;
  companion.hidden = !open;
  orbit.classList.toggle("is-open", open);
  launcher.setAttribute("aria-expanded", String(open));
  if (open) {
    $("#tonyNudge").hidden = true;
    setTonyCompanionMood(assistantUtterance ? "speaking" : (tonyRecognitionRunning ? "listening" : "idle"), assistantUtterance ? "Tony está hablando" : (tonyRecognitionRunning ? "Tony está escuchando" : "Listo para ayudarte"));
  }
}

function initializeTonyCompanion() {
  const orbit = $("#tonyOrbit");
  const launcher = $("#tonyLauncher");
  const companion = $("#tonyCompanion");
  if (!orbit || !launcher || !companion) return;

  let position = null;
  try { position = JSON.parse(localStorage.getItem("produ-tony-position") || "null"); } catch (error) { /* Preferencia opcional. */ }
  placeTony(position?.x ?? window.innerWidth - 106, position?.y ?? window.innerHeight - 124);

  launcher.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const initial = orbit.getBoundingClientRect();
    const start = { x: event.clientX, y: event.clientY, left: initial.left, top: initial.top };
    let moved = false;
    launcher.setPointerCapture(event.pointerId);
    const move = (moveEvent) => {
      const distance = Math.hypot(moveEvent.clientX - start.x, moveEvent.clientY - start.y);
      if (distance > 5) moved = true;
      if (!moved) return;
      moveEvent.preventDefault();
      placeTony(start.left + moveEvent.clientX - start.x, start.top + moveEvent.clientY - start.y);
    };
    const end = () => {
      launcher.removeEventListener("pointermove", move);
      launcher.removeEventListener("pointerup", end);
      launcher.removeEventListener("pointercancel", end);
      if (moved) placeTony(orbit.getBoundingClientRect().left, orbit.getBoundingClientRect().top, { save: true });
      tonyDragged = moved;
      window.setTimeout(() => { tonyDragged = false; }, 0);
    };
    launcher.addEventListener("pointermove", move);
    launcher.addEventListener("pointerup", end);
    launcher.addEventListener("pointercancel", end);
  });

  launcher.addEventListener("click", () => {
    if (tonyDragged) return;
    setTonyCompanionOpen(companion.hidden);
  });
  $("#tonyMinimizeBtn").addEventListener("click", () => setTonyCompanionOpen(false));
  $("#tonyVoiceToggle").addEventListener("click", () => {
    const voiceButton = $("#voiceCommandBtn");
    if (voiceButton.disabled) {
      showTonyNudge("La voz requiere HTTPS y un navegador compatible. Puedes escribirme aquí.");
      return;
    }
    voiceButton.click();
  });
  $("#tonyChatForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("#tonyChatInput");
    const prompt = input.value.trim();
    if (!prompt) return;
    input.value = "";
    askTony(prompt);
  });
  $$("[data-tony-prompt]").forEach((button) => button.addEventListener("click", () => askTony(button.dataset.tonyPrompt)));
  window.addEventListener("resize", () => {
    const current = orbit.getBoundingClientRect();
    placeTony(current.left, current.top, { save: true });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !companion.hidden) setTonyCompanionOpen(false);
  });
}

function notifyTonyOfNewOrders(previousOrders, nextOrders) {
  if (!previousOrders?.length || !nextOrders?.length) return;
  const oldKeys = new Set(previousOrders.map((order) => `${order.id}|${order.recordAt || ""}`));
  const additions = nextOrders.filter((order) => !oldKeys.has(`${order.id}|${order.recordAt || ""}`));
  if (!additions.length) return;
  const message = additions.length === 1
    ? `Detecté un nuevo pedido: #${additions[0].id} de ${additions[0].client}.`
    : `Detecté ${additions.length} pedidos nuevos. Ya actualicé el tablero.`;
  appendTonyChat("assistant", message);
  showTonyNudge(message, 7200);
}

function renderAll() {
  const values = metrics(state.dataset.orders);
  renderHeader();
  renderFilterOptions();
  renderKpis(values);
  renderOrdersModule();
  renderSearchModule();
  renderCutterModule();
  renderChartsModule();
}

function syncControls() {
  $("#searchInput").value = state.query;
  $("#movementFilter").value = state.movement;
  $("#cutterFilter").value = state.cutter;
  $("#productionFilter").value = state.production;
  $("#dateFromFilter").value = state.dateFrom;
  $("#dateToFilter").value = state.dateTo;
}

function resetFilters() {
  state.query = "";
  state.movement = "Todos";
  state.cutter = "Todos";
  state.production = "Todos";
  state.dateFrom = "";
  state.dateTo = "";
  syncControls();
  renderSearchModule();
}

function setModule(name, { updateUrl = true, focusPanel = false } = {}) {
  if (!MODULES[name]) name = "orders";
  state.activeModule = name;
  const copy = MODULES[name];
  $("#moduleEyebrow").textContent = copy.eyebrow;
  $("#moduleTitle").textContent = copy.title;
  $("#moduleSubtitle").textContent = copy.subtitle;

  $$('[data-module-panel]').forEach((panel) => {
    const active = panel.dataset.modulePanel === name;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  $$('.module-nav [data-module]').forEach((button) => {
    const active = button.dataset.module === name;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });

  try { localStorage.setItem("produ-module", name); } catch (error) { /* Preferencia opcional. */ }
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("module", name);
    history.replaceState({ module: name }, "", url);
  }
  if (focusPanel) {
    window.scrollTo({ top: 0, behavior: "smooth" });
    $(`[data-module-panel="${name}"]`)?.focus({ preventScroll: true });
  }
}

function updateConnectionStatus() {
  const online = navigator.onLine;
  const node = $("#connectionStatus");
  node.textContent = online ? "En línea" : "Sin conexión · mostrando datos guardados";
  node.classList.toggle("offline", !online);
}

async function loadData({ quiet = false } = {}) {
  if (dataRefreshInFlight) return dataRefreshInFlight;
  const button = $("#refreshBtn");
  if (!quiet) {
    button.disabled = true;
    $("#refreshBtnText").textContent = "Actualizando…";
  }
  setAssistantThinking(true);
  if (!quiet) showMessage("working", "Leyendo la versión más reciente del JSON publicado…");

  dataRefreshInFlight = (async () => {
    try {
      let dataset;
      let offline = false;
      try {
        const response = await fetch(DATA_URL, {
          cache: "no-store",
          headers: { Accept: "application/vnd.github.raw+json" },
          signal: AbortSignal.timeout(15000),
        });
        if (!response.ok) throw new Error(`No se pudo leer el JSON (${response.status}).`);
        dataset = await response.json();
        if (dataset.meta?.schemaVersion !== 4 || !Array.isArray(dataset.orders)) throw new Error("La publicación no tiene el formato SQLite esperado.");
        try { localStorage.setItem("produ-snapshot-v4", JSON.stringify(dataset)); } catch (_) { /* Cache opcional. */ }
      } catch (error) {
        try { dataset = JSON.parse(localStorage.getItem("produ-snapshot-v4") || "null"); } catch (_) { dataset = null; }
        if (!dataset || dataset.meta?.schemaVersion !== 4 || !Array.isArray(dataset.orders)) throw error;
        offline = true;
      }
      if (!dataset.meta || !Array.isArray(dataset.orders)) throw new Error("El JSON no tiene el formato esperado.");

      const currentVersion = `${state.dataset.meta?.generatedAt || ""}|${state.dataset.meta?.sourceModifiedAt || ""}|${state.dataset.orders.length}`;
      const nextVersion = `${dataset.meta.generatedAt || ""}|${dataset.meta.sourceModifiedAt || ""}|${dataset.orders.length}`;
      const changed = currentVersion !== nextVersion;
      if (changed) {
        const previousOrders = state.dataset.orders;
        state.dataset = dataset;
        renderAll();
        syncControls();
        notifyTonyOfNewOrders(previousOrders, dataset.orders);
      }
      if (offline) {
        showMessage("working", `No se pudo actualizar. Mostrando la copia guardada del ${formatTimestamp(dataset.meta.generatedAt)}.`);
      } else if (!quiet || changed) {
        showMessage("success", changed
          ? `Datos sincronizados: ${dataset.orders.length} pedidos disponibles.`
          : `Ya cuentas con la versión más reciente: ${dataset.orders.length} pedidos.`);
      }
    } catch (error) {
      if (!quiet) showMessage("error", `${error.message} Si estás sin conexión, vuelve a intentarlo cuando recuperes Internet.`);
    } finally {
      setAssistantThinking(false);
      if (!quiet) {
        button.disabled = false;
        $("#refreshBtnText").textContent = "Actualizar datos";
      }
      dataRefreshInFlight = null;
    }
  })();

  return dataRefreshInFlight;
}

function startDataRefresh() {
  if (dataRefreshTimer) window.clearInterval(dataRefreshTimer);
  dataRefreshTimer = window.setInterval(() => {
    if (!document.hidden && navigator.onLine) {
      loadData({ quiet: true });
      checkForAppUpdate();
    }
  }, DATA_REFRESH_INTERVAL);
}

function checkForAppUpdate() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.getRegistration().then((registration) => registration?.update()).catch(() => undefined);
}

async function installApp() {
  if (!deferredInstallPrompt) return;
  deferredInstallPrompt.prompt();
  const choice = await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
  $("#installBtn").hidden = true;
  if (choice.outcome === "accepted") showMessage("success", "PRODU se instaló como aplicación.");
}

function initialModule() {
  const fromUrl = new URLSearchParams(window.location.search).get("module");
  if (MODULES[fromUrl]) return fromUrl;
  try {
    const stored = localStorage.getItem("produ-module");
    if (MODULES[stored]) return stored;
  } catch (error) { /* Preferencia opcional. */ }
  return "orders";
}

$("#searchInput").addEventListener("input", (event) => { state.query = event.target.value; renderSearchModule(); });
$("#movementFilter").addEventListener("change", (event) => { state.movement = event.target.value; renderSearchModule(); });
$("#cutterFilter").addEventListener("change", (event) => { state.cutter = event.target.value; renderSearchModule(); });
$("#productionFilter").addEventListener("change", (event) => { state.production = event.target.value; renderSearchModule(); });
$("#dateFromFilter").addEventListener("change", (event) => { state.dateFrom = event.target.value; renderSearchModule(); });
$("#dateToFilter").addEventListener("change", (event) => { state.dateTo = event.target.value; renderSearchModule(); });
$("#refreshBtn").addEventListener("click", () => loadData());
$("#themeBtn").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
$("#resetBtn").addEventListener("click", resetFilters);
$("#installBtn").addEventListener("click", installApp);

$$('.module-nav [data-module]').forEach((button) => button.addEventListener("click", () => setModule(button.dataset.module, { focusPanel: true })));

$(".module-nav").addEventListener("keydown", (event) => {
  const buttons = $$('.module-nav [data-module]');
  const current = buttons.indexOf(document.activeElement);
  if (current < 0) return;
  let next = current;
  if (["ArrowDown", "ArrowRight"].includes(event.key)) next = (current + 1) % buttons.length;
  else if (["ArrowUp", "ArrowLeft"].includes(event.key)) next = (current - 1 + buttons.length) % buttons.length;
  else if (event.key === "Home") next = 0;
  else if (event.key === "End") next = buttons.length - 1;
  else return;
  event.preventDefault();
  buttons[next].focus();
  setModule(buttons[next].dataset.module);
});

$$('.advanced-status-grid button').forEach((button) => button.addEventListener("click", () => {
  const sameSelection = state.movement === button.dataset.advancedMovement && state.production === button.dataset.advancedStatus;
  state.movement = sameSelection ? "Todos" : button.dataset.advancedMovement;
  state.production = sameSelection ? "Todos" : button.dataset.advancedStatus;
  syncControls();
  renderSearchModule();
}));

$("#recentNotifications").addEventListener("click", (event) => {
  const button = event.target.closest("[data-notification-id]");
  if (!button) return;
  stopAssistantSpeech("Tony tiene listo el detalle completo de esta notificación.");
  state.activeNotificationId = button.dataset.notificationId;
  renderOrdersModule();
});

$("#assistantSummaryBtn").addEventListener("click", () => {
  stopAssistantSpeech("Tony tiene listo el resumen general.");
  state.activeNotificationId = "";
  renderOrdersModule();
});

$("#listenAssistantBtn").addEventListener("click", speakAssistant);
$("#stopAssistantBtn").addEventListener("click", () => stopAssistantSpeech());

$("#cutterGrid").addEventListener("click", (event) => {
  const button = event.target.closest(".view-cutter-orders");
  if (!button) return;
  state.cutter = button.dataset.cutterName;
  state.query = "";
  syncControls();
  renderSearchModule();
  setModule("search", { focusPanel: true });
});

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  $("#installBtn").hidden = false;
});

window.addEventListener("appinstalled", () => {
  deferredInstallPrompt = null;
  $("#installBtn").hidden = true;
  showMessage("success", "PRODU quedó instalada en este dispositivo.");
});

window.addEventListener("online", () => {
  updateConnectionStatus();
  loadData({ quiet: true });
});
window.addEventListener("offline", updateConnectionStatus);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    if (tonyRecognitionRunning && tonyRecognition) tonyRecognition.abort();
  } else {
    queueTonyRecognition(250);
    if (navigator.onLine) {
      loadData({ quiet: true });
      checkForAppUpdate();
    }
  }
});
window.addEventListener("pagehide", () => disableTonyVoice());

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (serviceWorkerReloaded) return;
    serviceWorkerReloaded = true;
    window.location.reload();
  });
  window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").then((registration) => {
    registration.update().catch(() => undefined);
  }).catch(() => {
    showMessage("error", "No se pudo activar el modo sin conexión en este navegador.");
  }));
}

if (window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone) {
  $("#installBtn").hidden = true;
}

initializeTonyCompanion();
initializeTonyVoice();
applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
setModule(initialModule(), { updateUrl: false });
updateConnectionStatus();
loadData({ quiet: true });
startDataRefresh();

