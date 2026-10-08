/* Shared, testable interpretation of SQLite statuses. */
(function (root) {
  "use strict";
  const statuses = ["En proceso", "En resguardo", "Terminado", "Entregado a cliente"];
  const norm = value => String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  function status(order) {
    const explicit = statuses.find(s => norm(s) === norm(order.status));
    if (explicit) return explicit;
    if (norm(order.delivery) === "entregado") return statuses[3];
    if (norm(order.production) === "en resguardo") return statuses[1];
    if (norm(order.production) === "terminado") return statuses[2];
    return statuses[0];
  }
  function metrics(orders) {
    const count = s => orders.filter(o => status(o) === s).length;
    const process = count(statuses[0]), stored = count(statuses[1]);
    const finished = count(statuses[2]), delivered = count(statuses[3]);
    return { total: orders.length, process, stored, finished, delivered,
      pending: orders.length - delivered, completed: finished + delivered,
      pickup: process, shipments: stored };
  }
  function ranks(orders, field = "cutter") {
    const groups = new Map();
    orders.forEach(order => {
      const name = String(order[field] || "SIN ASIGNAR").trim();
      const key = norm(name);
      if (!groups.has(key)) groups.set(key, { name, orders: [] });
      groups.get(key).orders.push(order);
    });
    return [...groups.values()].map(g => ({ name: g.name, ...metrics(g.orders) }))
      .sort((a, b) => b.total - a.total || b.pending - a.pending || a.name.localeCompare(b.name, "es-MX"));
  }
  const api = { statuses, status, metrics, ranks };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ProduOrders = api;
})(typeof window !== "undefined" ? window : globalThis);
