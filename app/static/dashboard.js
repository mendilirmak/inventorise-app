// Draws the two dashboard charts: the 10 products with the fewest units, and
// restocks per day. Data comes from the <script id="chart-data"> tag (same shape
// as GET /api/products/analytics). Kept in a file, not inline, so the
// Content-Security-Policy can forbid inline scripts.
(function () {
  const data = JSON.parse(document.getElementById("chart-data").textContent);
  const lowCanvas = document.getElementById("low-chart");
  const restockCanvas = document.getElementById("restock-chart");
  if (typeof Chart === "undefined" || data.products.length === 0 || !lowCanvas || !restockCanvas) {
    return;
  }

  // Colors and font come from style.css, so there is one source for them.
  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(name).trim();
  const ink = token("--ink");
  const muted = token("--ink-2");
  const rule = token("--rule");
  const cobalt = token("--cobalt");
  const amber = token("--amber");
  const threshold = data.low_stock_threshold;

  Chart.defaults.font.family = token("--font");
  Chart.defaults.font.size = 13;
  Chart.defaults.color = muted;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    Chart.defaults.animation = false;
  }

  const shorten = (text, max) => (text.length > max ? text.slice(0, max - 1) + "…" : text);

  // A dashed line at the low-stock threshold, with a label.
  const thresholdLine = {
    id: "thresholdLine",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const x = scales.x.getPixelForValue(threshold);
      ctx.save();
      ctx.strokeStyle = ink;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = ink;
      ctx.textBaseline = "top";
      const label = "Threshold: " + threshold;
      // Keep the label inside the canvas on a narrow screen.
      if (x + 6 + ctx.measureText(label).width > chart.width) {
        ctx.textAlign = "right";
        ctx.fillText(label, chart.width - 2, chartArea.top);
      } else {
        ctx.textAlign = "left";
        ctx.fillText(label, x + 6, chartArea.top);
      }
      ctx.restore();
    },
  };

  // The number at the end of each bar, so nobody has to read it off the axis.
  const valueLabels = {
    id: "valueLabels",
    afterDatasetsDraw(chart) {
      const { ctx } = chart;
      ctx.save();
      ctx.fillStyle = ink;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      chart.getDatasetMeta(0).data.forEach((bar, i) => {
        ctx.fillText(String(chart.data.datasets[0].data[i]), bar.x + 6, bar.y);
      });
      ctx.restore();
    },
  };

  // 1. The 10 products with the fewest units. Amber = below the threshold.
  const lowest = [...data.products]
    .sort((a, b) => a.stock_level - b.stock_level || a.name.localeCompare(b.name))
    .slice(0, 10);
  // Shorter names on a narrow screen. The tooltip still shows the full name.
  const nameLength = lowCanvas.clientWidth < 420 ? 15 : 24;
  new Chart(lowCanvas, {
    type: "bar",
    data: {
      labels: lowest.map((p) => shorten(p.name, nameLength)),
      datasets: [{
        data: lowest.map((p) => p.stock_level),
        backgroundColor: lowest.map((p) => (p.stock_level < threshold ? amber : cobalt)),
        borderRadius: 3,
        maxBarThickness: 18,
      }],
    },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      layout: { padding: { right: 24 } },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => lowest[items[0].dataIndex].name + " (" + lowest[items[0].dataIndex].sku + ")",
            label: (item) => item.parsed.x + (item.parsed.x === 1 ? " unit" : " units"),
          },
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          suggestedMax: Math.ceil(threshold * 2.5),
          ticks: { precision: 0 },
          grid: { color: rule },
        },
        y: { grid: { display: false } },
      },
    },
    plugins: [thresholdLine, valueLabels],
  });

  // 2. Restock entries per day, last 30 days.
  const dayLabel = (iso, long) =>
    new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      weekday: long ? "short" : undefined,
      timeZone: "UTC",
    });
  const days = data.restocks_per_day;
  new Chart(restockCanvas, {
    type: "bar",
    data: {
      labels: days.map((d) => dayLabel(d.date, false)),
      datasets: [{
        data: days.map((d) => d.count),
        backgroundColor: cobalt,
        borderRadius: 3,
        maxBarThickness: 14,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => dayLabel(days[items[0].dataIndex].date, true),
            label: (item) => item.parsed.y + (item.parsed.y === 1 ? " restock" : " restocks"),
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
        y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: rule } },
      },
    },
  });
})();
