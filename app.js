const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  dataset: { meta: {}, orders: [] },
  query: "",
  movement: "Todos",
  cutter: "Todos",
  production: "Todos",
  dateFrom: "",
  dateTo: "",
};

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

function unique(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b, "es-MX"));
}

function isCr(order) {
  return order.movement === "CR" || order.movement === "Cliente recoge";
}

function movementValue(order) {
  return isCr(order) ? "CR" : order.movement;
}

function displayMovement(order) {
  return isCr(order) ? "CR" : order.movement;
}

function isFinished(order) {
  return normalize(order.production) === "terminado";
}

function productionValue(order) {
  return isFinished(order) ? "TERMINADO" : "EN PROCESO";
}

function displayProduction(order) {
  return isFinished(order) ? "TERMINADO" : "EN PROCESO";
}

function orderDate(order) {
  return String(order.recordAt || "").slice(0, 10);
}

function matchesAdvancedState(order, production) {
  return production === "Todos" || productionValue(order) === production;
}

function filteredOrders() {
  const query = normalize(state.query.trim());
  return state.dataset.orders.filter((order) => {
    const date = orderDate(order);
    const matchesQuery = !query || normalize(`${order.id} ${order.client} ${order.cutter} ${order.receiver} ${order.driver || ""}`).includes(query);
    return matchesQuery
      && (state.movement === "Todos" || movementValue(order) === state.movement)
      && (state.cutter === "Todos" || order.cutter === state.cutter)
      && matchesAdvancedState(order, state.production)
      && (!state.dateFrom || (date && date >= state.dateFrom))
      && (!state.dateTo || (date && date <= state.dateTo));
  });
}

function metrics(orders) {
  const total = orders.length;
  const pickup = orders.filter(isCr).length;
  const shipments = orders.filter((order) => movementValue(order) === "Envío producción").length;
  const finished = orders.filter(isFinished).length;
  const delivered = orders.filter((order) => normalize(order.delivery) === "entregado").length;
  return { total, pickup, shipments, finished, delivered };
}

function renderHeader() {
  const meta = state.dataset.meta;
  $("#updatedAt").textContent = formatTimestamp(meta.generatedAt || meta.sourceModifiedAt);
  $("#sourceName").textContent = `${meta.source || "PRODUCCION.xlsm"} · GitHub`;
  $("#footerMeta").textContent = `JSON generado desde ${meta.source || "PRODUCCION.xlsm"} · Excel guardado ${formatTimestamp(meta.sourceModifiedAt)}`;
}

function renderFilterOptions() {
  const select = $("#cutterFilter");
  const current = state.cutter;
  const cutters = unique(state.dataset.orders.map((order) => order.cutter));
  select.innerHTML = `<option value="Todos">Todos los cortadores</option>${cutters.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
  select.value = cutters.includes(current) ? current : "Todos";
}

function renderAdvancedCounts() {
  const count = (movement, production) => state.dataset.orders.filter((order) => movementValue(order) === movement && productionValue(order) === production).length;
  $("#advancedCrFinished").textContent = count("CR", "TERMINADO");
  $("#advancedCrProcess").textContent = count("CR", "EN PROCESO");
  $("#advancedShipmentFinished").textContent = count("Envío producción", "TERMINADO");
  $("#advancedShipmentProcess").textContent = count("Envío producción", "EN PROCESO");

  $$(".advanced-status-grid button").forEach((button) => {
    const selected = button.dataset.advancedMovement === state.movement && button.dataset.advancedStatus === state.production;
    button.classList.toggle("selected", selected);
  });
}

function renderKpis(values) {
  const pickupRate = values.total ? Math.round((values.pickup / values.total) * 100) : 0;
  const completionRate = values.total ? Math.round((values.finished / values.total) * 100) : 0;
  const shipmentRate = values.total ? 100 - pickupRate : 0;
  const pendingDelivery = Math.max(values.total - values.delivered, 0);

  $("#kpiTotal").textContent = String(values.total).padStart(2, "0");
  $("#kpiPickup").textContent = String(values.pickup).padStart(2, "0");
  $("#kpiShipments").textContent = String(values.shipments).padStart(2, "0");
  $("#kpiFinished").textContent = String(values.finished).padStart(2, "0");
  $("#kpiDelivered").textContent = String(values.delivered).padStart(2, "0");
  $("#kpiPickupNote").textContent = `${pickupRate}% del movimiento`;
  $("#kpiFinishedNote").textContent = `${completionRate}% de avance`;
  $("#kpiDeliveredNote").textContent = `${pendingDelivery} pendientes de entrega`;

  $("#completionBadge").textContent = `${completionRate}%`;
  $("#completionProgress span").style.width = `${completionRate}%`;
  $("#completionProgress").setAttribute("aria-label", `${completionRate}% de pedidos terminados`);
  $("#finishedCopy").textContent = `${values.finished} terminados`;
  $("#pendingCopy").textContent = `${Math.max(values.total - values.finished, 0)} en proceso`;

  $("#routeCount").textContent = values.total;
  $("#donutTotal").textContent = values.total;
  $("#routeDonut").style.background = `conic-gradient(#8fd14f 0 ${pickupRate}%, #3db8d5 ${pickupRate}% 100%)`;
  $("#routeDonut").setAttribute("aria-label", `${values.pickup} CR y ${values.shipments} envíos de producción`);
  $("#pickupLegend").textContent = `${values.pickup} pedidos`;
  $("#shipmentLegend").textContent = `${values.shipments} pedidos`;
  $("#pickupPercent").textContent = `${pickupRate}%`;
  $("#shipmentPercent").textContent = `${shipmentRate}%`;
  $("#deliveredStrip").textContent = values.delivered;
  $("#pendingDeliveryStrip").textContent = pendingDelivery;
}

function renderCutters(orders) {
  const names = unique(state.dataset.orders.map((order) => order.cutter));
  const stats = names.map((name) => {
    const assigned = orders.filter((order) => order.cutter === name).length;
    const finished = orders.filter((order) => order.cutter === name && isFinished(order)).length;
    return { name, assigned, finished, rate: assigned ? Math.round((finished / assigned) * 100) : 0 };
  }).filter((item) => item.assigned).sort((a, b) => b.finished - a.finished || b.assigned - a.assigned);

  $("#cutterList").innerHTML = stats.length ? stats.map((stat, index) => `
    <div class="cutter-row">
      <span class="avatar ${index % 2 === 0 ? "avatar-blue" : "avatar-green"}">${escapeHtml(stat.name.charAt(0) || "?")}</span>
      <div class="cutter-data"><div><strong>${escapeHtml(stat.name)}</strong><span>${stat.finished} de ${stat.assigned} terminados</span></div><div class="mini-bar"><span style="width:${stat.rate}%"></span></div></div>
      <b>${stat.rate}%</b>
    </div>`).join("") : `<div class="empty-state">Sin cortadores en esta búsqueda.</div>`;
}

function renderOrders(orders) {
  const cutters = unique(state.dataset.orders.map((order) => order.cutter));
  $("#ordersBody").innerHTML = orders.length ? orders.map((order) => {
    const shipment = movementValue(order) === "Envío producción";
    const finished = isFinished(order);
    const delivered = normalize(order.delivery) === "entregado";
    const avatarTone = cutters.indexOf(order.cutter) % 2 === 0 ? "avatar-blue" : "avatar-green";
    return `<tr>
      <td><strong class="order-id">#${escapeHtml(order.id)}</strong></td>
      <td><strong class="client-name">${escapeHtml(order.client)}</strong><small>Recibió: ${escapeHtml(order.receiver)}</small></td>
      <td><span class="movement-pill ${shipment ? "shipment" : "pickup"}">${escapeHtml(displayMovement(order))}</span></td>
      <td><div class="cutter-cell"><span class="avatar ${avatarTone}">${escapeHtml(order.cutter.charAt(0) || "?")}</span><p><strong>${escapeHtml(order.cutter)}</strong><small>${finished ? "Finalizó el pedido" : "Corte asignado"}</small></p></div></td>
      <td><span class="status ${finished ? "done" : "pending"}"><i></i>${displayProduction(order)}</span></td>
      <td><span class="status ${delivered ? "delivered" : "waiting"}"><i></i>${escapeHtml(order.delivery)}</span>${order.driver ? `<small>Chofer: ${escapeHtml(order.driver)}</small>` : ""}</td>
      <td><span class="date-cell">${escapeHtml(order.date)}<small>${escapeHtml(order.time)} h</small></span></td>
    </tr>`;
  }).join("") : `<tr><td colspan="7" class="empty-state">No hay CR o envíos que coincidan con la búsqueda.</td></tr>`;
}

function render() {
  const orders = filteredOrders();
  const values = metrics(orders);
  const hasFilters = Boolean(state.query || state.movement !== "Todos" || state.cutter !== "Todos" || state.production !== "Todos" || state.dateFrom || state.dateTo);
  $("#filterSummary").textContent = hasFilters
    ? `Resultado: ${orders.length} de ${state.dataset.orders.length} pedidos`
    : `Vista general · ${state.dataset.orders.length} pedidos · Último registro ${formatTimestamp(state.dataset.meta.lastRecordAt)}`;
  $("#resetBtn").disabled = !hasFilters;
  $$(".quick-tabs button").forEach((button) => button.classList.toggle("selected", button.dataset.status === state.production));
  renderAdvancedCounts();
  renderKpis(values);
  renderCutters(orders);
  renderOrders(orders);
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
  render();
}

async function loadData({ quiet = false } = {}) {
  const button = $("#refreshBtn");
  button.disabled = true;
  $("#refreshBtnText").textContent = "Actualizando…";
  if (!quiet) showMessage("working", "Leyendo la versión más reciente del JSON publicado…");

  try {
    const response = await fetch(`data/produccion.json?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`No se pudo leer el JSON (${response.status}).`);
    const dataset = await response.json();
    if (!dataset.meta || !Array.isArray(dataset.orders)) throw new Error("El JSON no tiene el formato esperado.");
    state.dataset = dataset;
    renderHeader();
    renderFilterOptions();
    syncControls();
    render();
    showMessage("success", `Datos actualizados: ${dataset.orders.length} pedidos disponibles.`);
  } catch (error) {
    showMessage("error", `${error.message} Ejecuta Iniciar-Vista-Web-Portable.bat para la vista local.`);
  } finally {
    button.disabled = false;
    $("#refreshBtnText").textContent = "Actualizar datos";
  }
}

$("#searchInput").addEventListener("input", (event) => { state.query = event.target.value; render(); });
$("#movementFilter").addEventListener("change", (event) => { state.movement = event.target.value; render(); });
$("#cutterFilter").addEventListener("change", (event) => { state.cutter = event.target.value; render(); });
$("#productionFilter").addEventListener("change", (event) => { state.production = event.target.value; render(); });
$("#dateFromFilter").addEventListener("change", (event) => { state.dateFrom = event.target.value; render(); });
$("#dateToFilter").addEventListener("change", (event) => { state.dateTo = event.target.value; render(); });
$("#refreshBtn").addEventListener("click", () => loadData());
$("#resetBtn").addEventListener("click", resetFilters);

$$('.quick-tabs button').forEach((button) => button.addEventListener("click", () => {
  state.production = button.dataset.status;
  syncControls();
  render();
}));

$$('.advanced-status-grid button').forEach((button) => button.addEventListener("click", () => {
  const sameSelection = state.movement === button.dataset.advancedMovement && state.production === button.dataset.advancedStatus;
  state.movement = sameSelection ? "Todos" : button.dataset.advancedMovement;
  state.production = sameSelection ? "Todos" : button.dataset.advancedStatus;
  syncControls();
  render();
  $("#pedidos").scrollIntoView({ behavior: "smooth", block: "start" });
}));

loadData({ quiet: true });
