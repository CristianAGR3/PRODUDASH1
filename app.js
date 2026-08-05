const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const MODULES = {
  orders: {
    eyebrow: "TRAZABILIDAD",
    title: "Todos los pedidos",
    subtitle: "Información completa de CR, envíos, producción y entrega.",
  },
  search: {
    eyebrow: "CONSULTA",
    title: "Buscador avanzado",
    subtitle: "Filtra por cliente, pedido, movimiento, estado, cortador o fecha.",
  },
  cutters: {
    eyebrow: "PRODUCCIÓN",
    title: "Cortadores",
    subtitle: "Avance, carga de trabajo y pedidos terminados por responsable.",
  },
};

const state = {
  dataset: { meta: {}, orders: [] },
  query: "",
  movement: "Todos",
  cutter: "Todos",
  production: "Todos",
  dateFrom: "",
  dateTo: "",
  activeModule: "orders",
};

let deferredInstallPrompt = null;

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
  return normalize(order.production) === "terminado";
}

function productionValue(order) {
  return isFinished(order) ? "TERMINADO" : "EN PROCESO";
}

function orderDate(order) {
  return String(order.recordAt || "").slice(0, 10);
}

function filteredOrders() {
  const query = normalize(state.query.trim());
  return state.dataset.orders.filter((order) => {
    const date = orderDate(order);
    const searchable = `${order.id} ${order.client} ${order.cutter} ${order.receiver} ${order.driver || ""}`;
    return (!query || normalize(searchable).includes(query))
      && (state.movement === "Todos" || movementValue(order) === state.movement)
      && (state.cutter === "Todos" || order.cutter === state.cutter)
      && (state.production === "Todos" || productionValue(order) === state.production)
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
  $("#footerMeta").textContent = `JSON desde ${meta.source || "PRODUCCION.xlsm"} · Excel guardado ${formatTimestamp(meta.sourceModifiedAt)}`;
}

function renderFilterOptions() {
  const select = $("#cutterFilter");
  const current = state.cutter;
  const cutters = unique(state.dataset.orders.map((order) => order.cutter));
  select.innerHTML = `<option value="Todos">Todos los cortadores</option>${cutters.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
  select.value = cutters.includes(current) ? current : "Todos";
  if (!cutters.includes(current)) state.cutter = "Todos";
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
    button.setAttribute("aria-pressed", String(selected));
  });
}

function renderKpis(values) {
  const pickupRate = values.total ? Math.round((values.pickup / values.total) * 100) : 0;
  const completionRate = values.total ? Math.round((values.finished / values.total) * 100) : 0;
  const shipmentRate = values.total ? Math.round((values.shipments / values.total) * 100) : 0;
  const pendingDelivery = Math.max(values.total - values.delivered, 0);
  const process = Math.max(values.total - values.finished, 0);

  $("#kpiTotal").textContent = String(values.total).padStart(2, "0");
  $("#kpiPickup").textContent = String(values.pickup).padStart(2, "0");
  $("#kpiShipments").textContent = String(values.shipments).padStart(2, "0");
  $("#kpiFinished").textContent = String(values.finished).padStart(2, "0");
  $("#kpiDelivered").textContent = String(values.delivered).padStart(2, "0");
  $("#kpiPickupNote").textContent = `${pickupRate}% del movimiento`;
  $("#kpiFinishedNote").textContent = `${completionRate}% de avance`;
  $("#kpiDeliveredNote").textContent = `${pendingDelivery} pendientes de entrega`;

  $("#ordersCompletionBadge").textContent = `${completionRate}%`;
  $("#ordersCompletionProgress span").style.width = `${completionRate}%`;
  $("#ordersCompletionProgress").setAttribute("aria-label", `${completionRate}% de pedidos terminados`);
  $("#ordersFinishedCopy").textContent = `${values.finished} terminados`;
  $("#ordersProcessCopy").textContent = `${process} en proceso`;
  $("#ordersFinishedStat").textContent = values.finished;
  $("#ordersProcessStat").textContent = process;
  $("#ordersDeliveredStat").textContent = values.delivered;

  $("#completionBadge").textContent = `${completionRate}%`;
  $("#completionProgress span").style.width = `${completionRate}%`;
  $("#completionProgress").setAttribute("aria-label", `${completionRate}% de pedidos terminados`);
  $("#finishedCopy").textContent = `${values.finished} terminados`;
  $("#pendingCopy").textContent = `${process} en proceso`;

  $("#routeCount").textContent = values.total;
  $("#donutTotal").textContent = values.total;
  $("#routeDonut").style.background = values.total
    ? `conic-gradient(#8fd14f 0 ${pickupRate}%, #3db8d5 ${pickupRate}% 100%)`
    : "conic-gradient(#d8ded8 0 100%)";
  $("#routeDonut").setAttribute("aria-label", `${values.pickup} CR y ${values.shipments} envíos de producción`);
  $("#pickupLegend").textContent = `${values.pickup} pedidos`;
  $("#shipmentLegend").textContent = `${values.shipments} pedidos`;
  $("#pickupPercent").textContent = `${pickupRate}%`;
  $("#shipmentPercent").textContent = `${shipmentRate}%`;
  $("#deliveredStrip").textContent = values.delivered;
  $("#pendingDeliveryStrip").textContent = pendingDelivery;
}

function orderRows(orders, emptyMessage) {
  if (!orders.length) return `<tr><td colspan="7" class="empty-state">${escapeHtml(emptyMessage)}</td></tr>`;
  const cutters = unique(state.dataset.orders.map((order) => order.cutter));
  return orders.map((order) => {
    const shipment = movementValue(order) === "Envío producción";
    const finished = isFinished(order);
    const delivered = normalize(order.delivery) === "entregado";
    const avatarTone = cutters.indexOf(order.cutter) % 2 === 0 ? "avatar-blue" : "avatar-green";
    return `<tr>
      <td data-label="Pedido"><strong class="order-id">#${escapeHtml(order.id)}</strong></td>
      <td data-label="Cliente"><strong class="client-name">${escapeHtml(order.client)}</strong><small>Recibió: ${escapeHtml(order.receiver)}</small></td>
      <td data-label="Movimiento"><span class="movement-pill ${shipment ? "shipment" : "pickup"}">${escapeHtml(movementValue(order))}</span></td>
      <td data-label="Cortador"><div class="cutter-cell"><span class="avatar ${avatarTone}">${escapeHtml(order.cutter.charAt(0) || "?")}</span><p><strong>${escapeHtml(order.cutter)}</strong><small>${finished ? "Finalizó el pedido" : "Corte asignado"}</small></p></div></td>
      <td data-label="Producción"><span class="status ${finished ? "done" : "pending"}"><i></i>${productionValue(order)}</span></td>
      <td data-label="Entrega"><span class="status ${delivered ? "delivered" : "waiting"}"><i></i>${escapeHtml(order.delivery)}</span>${order.driver ? `<small>Chofer: ${escapeHtml(order.driver)}</small>` : ""}</td>
      <td data-label="Registro"><span class="date-cell">${escapeHtml(order.date)}<small>${escapeHtml(order.time)} h</small></span></td>
    </tr>`;
  }).join("");
}

function renderOrdersModule() {
  const orders = state.dataset.orders;
  $("#ordersCountLabel").textContent = `${orders.length} ${orders.length === 1 ? "pedido" : "pedidos"}`;
  $("#ordersBody").innerHTML = orderRows(orders, "No hay pedidos registrados.");
}

function renderSearchModule() {
  const orders = filteredOrders();
  const hasFilters = Boolean(state.query || state.movement !== "Todos" || state.cutter !== "Todos" || state.production !== "Todos" || state.dateFrom || state.dateTo);
  $("#filterSummary").textContent = hasFilters
    ? `Resultado: ${orders.length} de ${state.dataset.orders.length} pedidos`
    : `Vista general · ${state.dataset.orders.length} pedidos · Último registro ${formatTimestamp(state.dataset.meta.lastRecordAt)}`;
  $("#searchCountLabel").textContent = `${orders.length} ${orders.length === 1 ? "resultado" : "resultados"}`;
  $("#resetBtn").disabled = !hasFilters;
  $("#searchOrdersBody").innerHTML = orderRows(orders, "No hay CR o envíos que coincidan con la búsqueda.");
  renderAdvancedCounts();
}

function renderCutterModule() {
  const orders = state.dataset.orders;
  const names = unique(orders.map((order) => order.cutter));
  const stats = names.map((name) => {
    const assignedOrders = orders.filter((order) => order.cutter === name);
    const values = metrics(assignedOrders);
    return {
      name,
      total: values.total,
      finished: values.finished,
      process: Math.max(values.total - values.finished, 0),
      pickup: values.pickup,
      shipments: values.shipments,
      delivered: values.delivered,
      rate: values.total ? Math.round((values.finished / values.total) * 100) : 0,
    };
  }).sort((a, b) => b.rate - a.rate || b.finished - a.finished || a.name.localeCompare(b.name, "es-MX"));

  const cuttersWithFinished = stats.filter((item) => item.finished > 0).length;
  const cuttersWithProcess = stats.filter((item) => item.process > 0).length;
  $("#cutterSummary").innerHTML = `
    <div><span>Cortadores activos</span><strong>${stats.length}</strong></div>
    <div><span>Con pedidos terminados</span><strong>${cuttersWithFinished}</strong></div>
    <div><span>Con trabajo en proceso</span><strong>${cuttersWithProcess}</strong></div>`;

  $("#cutterGrid").innerHTML = stats.length ? stats.map((stat, index) => `
    <article class="cutter-card">
      <div class="cutter-card-head">
        <span class="avatar ${index % 2 === 0 ? "avatar-blue" : "avatar-green"}">${escapeHtml(stat.name.charAt(0) || "?")}</span>
        <div><p>CORTADOR</p><h3>${escapeHtml(stat.name)}</h3></div>
        <strong class="cutter-rate">${stat.rate}%</strong>
      </div>
      <div class="cutter-progress" aria-label="${stat.rate}% terminado"><span style="width:${stat.rate}%"></span></div>
      <div class="cutter-card-stats">
        <div><span>Asignados</span><strong>${stat.total}</strong></div>
        <div><span>Terminados</span><strong>${stat.finished}</strong></div>
        <div><span>En proceso</span><strong>${stat.process}</strong></div>
        <div><span>CR / Envíos</span><strong>${stat.pickup} / ${stat.shipments}</strong></div>
      </div>
      <button class="view-cutter-orders" type="button" data-cutter-name="${escapeHtml(stat.name)}">Ver pedidos de ${escapeHtml(stat.name)} <span aria-hidden="true">→</span></button>
    </article>`).join("") : `<div class="empty-state">No hay cortadores registrados.</div>`;
}

function renderAll() {
  const values = metrics(state.dataset.orders);
  renderHeader();
  renderFilterOptions();
  renderKpis(values);
  renderOrdersModule();
  renderSearchModule();
  renderCutterModule();
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
    renderAll();
    syncControls();
    showMessage("success", `Datos actualizados: ${dataset.orders.length} pedidos disponibles.`);
  } catch (error) {
    showMessage("error", `${error.message} Si estás sin conexión, vuelve a intentarlo cuando recuperes Internet.`);
  } finally {
    button.disabled = false;
    $("#refreshBtnText").textContent = "Actualizar datos";
  }
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

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch(() => {
    showMessage("error", "No se pudo activar el modo sin conexión en este navegador.");
  }));
}

if (window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone) {
  $("#installBtn").hidden = true;
}

applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
setModule(initialModule(), { updateUrl: false });
updateConnectionStatus();
loadData({ quiet: true });
