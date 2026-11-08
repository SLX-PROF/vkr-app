// График Risk Score по датам проверок; границы статусов — 30 и 70 баллов
(function () {
  var node = document.getElementById("chart-data");
  var canvas = document.getElementById("risk-chart");
  if (!node || !canvas || typeof Chart === "undefined") return;
  var points = JSON.parse(node.textContent);
  var labels = points.map(function (p) { return p.date; });
  var line = function (value, color, label) {
    return { label: label, data: points.map(function () { return value; }), borderColor: color,
             borderDash: [6, 4], pointRadius: 0, borderWidth: 1 };
  };
  new Chart(canvas, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        { label: "Risk Score", data: points.map(function (p) { return p.score; }), borderColor: "#0d6efd",
          backgroundColor: "#0d6efd", tension: 0.25, pointRadius: 4 },
        line(30, "#d39e00", "Граница «Рискованный» (30)"),
        line(70, "#dc3545", "Граница «Опасный» (70)")
      ]
    },
    options: {
      maintainAspectRatio: false,
      scales: { y: { min: 0, max: 100, title: { display: true, text: "Баллы риска" } } },
      plugins: { legend: { position: "bottom" } }
    }
  });
})();
