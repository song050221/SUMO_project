function computeQuartiles(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const quantile = (arr, q) => {
    const pos = (arr.length - 1) * q;
    const base = Math.floor(pos);
    const rest = pos - base;
    return arr[base + 1] !== undefined ? arr[base] + rest * (arr[base + 1] - arr[base]) : arr[base];
  };
  return {
    min: sorted[0],
    q1: quantile(sorted, 0.25),
    median: quantile(sorted, 0.5),
    q3: quantile(sorted, 0.75),
    max: sorted[sorted.length - 1],
  };
}

const errorBarsPlugin = {
  id: "errorBars",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    chart.data.datasets.forEach((dataset, datasetIndex) => {
      if (!dataset.errorBars) return;
      const meta = chart.getDatasetMeta(datasetIndex);
      const yScale = chart.scales.y;
      meta.data.forEach((bar, index) => {
        const err = dataset.errorBars[index];
        if (err === undefined) return;
        const value = dataset.data[index];
        const { x } = bar.getProps(["x"], true);
        const yTop = yScale.getPixelForValue(value + err);
        const yBottom = yScale.getPixelForValue(Math.max(0, value - err));
        ctx.save();
        ctx.strokeStyle = "#e6e9f0";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x, yTop);
        ctx.lineTo(x, yBottom);
        ctx.moveTo(x - 6, yTop);
        ctx.lineTo(x + 6, yTop);
        ctx.moveTo(x - 6, yBottom);
        ctx.lineTo(x + 6, yBottom);
        ctx.stroke();
        ctx.restore();
      });
    });
  },
};

const boxWhiskerPlugin = {
  id: "boxWhisker",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    chart.data.datasets.forEach((dataset, datasetIndex) => {
      if (!dataset.boxStats) return;
      const meta = chart.getDatasetMeta(datasetIndex);
      const yScale = chart.scales.y;
      meta.data.forEach((bar, index) => {
        const stats = dataset.boxStats[index];
        if (!stats) return;
        const { x, width } = bar.getProps(["x", "width"], true);
        const halfWidth = Math.min(width, 40) / 2;
        const yMin = yScale.getPixelForValue(stats.min);
        const yMax = yScale.getPixelForValue(stats.max);
        const yQ1 = yScale.getPixelForValue(stats.q1);
        const yQ3 = yScale.getPixelForValue(stats.q3);
        const yMed = yScale.getPixelForValue(stats.median);
        ctx.save();
        ctx.strokeStyle = "#e6e9f0";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x, yMax);
        ctx.lineTo(x, yQ3);
        ctx.moveTo(x, yQ1);
        ctx.lineTo(x, yMin);
        ctx.moveTo(x - halfWidth / 2, yMax);
        ctx.lineTo(x + halfWidth / 2, yMax);
        ctx.moveTo(x - halfWidth / 2, yMin);
        ctx.lineTo(x + halfWidth / 2, yMin);
        ctx.stroke();
        ctx.beginPath();
        ctx.strokeStyle = "#4fd6ff";
        ctx.lineWidth = 3;
        ctx.moveTo(x - halfWidth, yMed);
        ctx.lineTo(x + halfWidth, yMed);
        ctx.stroke();
        ctx.restore();
      });
    });
  },
};

Chart.register(errorBarsPlugin, boxWhiskerPlugin);

async function main() {
  const grid = document.getElementById("metric-grid");
  const res = await fetch("/api/comparison");
  if (!res.ok) {
    grid.innerHTML = '<p style="color:#e0526b">results.csv가 아직 없습니다. run_experiments.py로 baseline/treatment 반복 실험을 먼저 실행하세요.</p>';
    return;
  }
  const data = await res.json();
  document.getElementById("meta-info").textContent = `baseline n=${data.n_baseline}, treatment n=${data.n_treatment}`;

  data.metrics.forEach((m, i) => {
    const panel = document.createElement("div");
    panel.className = "metric-panel";
    const badgeClass = m.significant ? "significant" : "not-significant";
    const badgeText = m.significant ? "유의미함 (p<0.05)" : "유의미하지 않음";
    panel.innerHTML = `
      <h2>${m.label} <span class="badge ${badgeClass}">${badgeText}</span></h2>
      <p class="p-values">t-test p=${m.t_p.toFixed(4)} &middot; Mann-Whitney p=${m.u_p.toFixed(4)}</p>
      <div class="chart-pair">
        <div><p class="chart-title">평균 &plusmn; 표준편차</p><canvas id="bar-${i}"></canvas></div>
        <div><p class="chart-title">분포 (boxplot)</p><canvas id="box-${i}"></canvas></div>
      </div>
    `;
    grid.appendChild(panel);

    new Chart(document.getElementById(`bar-${i}`), {
      type: "bar",
      data: {
        labels: ["baseline", "treatment"],
        datasets: [{
          data: [m.baseline_mean, m.treatment_mean],
          errorBars: [m.baseline_std, m.treatment_std],
          backgroundColor: ["#4a5578", "#3a8fd6"],
        }],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true } },
      },
    });

    const baseStats = computeQuartiles(m.baseline_values);
    const treatStats = computeQuartiles(m.treatment_values);
    new Chart(document.getElementById(`box-${i}`), {
      type: "bar",
      data: {
        labels: ["baseline", "treatment"],
        datasets: [{
          data: [[baseStats.q1, baseStats.q3], [treatStats.q1, treatStats.q3]],
          boxStats: [baseStats, treatStats],
          backgroundColor: ["rgba(74,85,120,0.35)", "rgba(58,143,214,0.35)"],
          borderColor: ["#4a5578", "#3a8fd6"],
          borderWidth: 1,
        }],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: false } },
      },
    });
  });
}

main();
