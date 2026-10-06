// Draws the stock-level bar chart on the dashboard.
// Data comes from the <script id="chart-data"> tag (same shape as
// GET /api/products/analytics). Kept in a file, not inline, so the
// Content-Security-Policy can forbid inline scripts.
(function () {
  const data = JSON.parse(document.getElementById("chart-data").textContent);
  const canvas = document.getElementById("stock-chart");
  if (!canvas || typeof Chart === "undefined" || data.products.length === 0) {
    return;
  }
  const threshold = data.low_stock_threshold;
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: data.products.map((p) => p.name),
      datasets: [{
        label: "Units in stock",
        data: data.products.map((p) => p.stock_level),
        // Low-stock bars in red, the rest in blue.
        backgroundColor: data.products.map((p) => (p.stock_level < threshold ? "#d9534f" : "#3b7dd8")),
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    },
  });
})();
