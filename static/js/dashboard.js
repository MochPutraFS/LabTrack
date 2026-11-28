/* LabTrack Staff Dashboard — Chart.js 4.x initialization with eye-friendly soft palette */
(function () {
  const root = document.getElementById('dashboard-charts-root');
  if (!root || typeof Chart === 'undefined') return;

  const apiUrl = root.dataset.chartsUrl;
  if (!apiUrl) return;

  Chart.defaults.font.family = '"Plus Jakarta Sans", "Inter", system-ui, sans-serif';
  Chart.defaults.color = '#475569';

  const palette = {
    emerald: '#34D399',
    blue: '#60A5FA',
    amber: '#FBBF24',
    rose: '#F87171',
    teal: '#0F766E',
    indigo: '#6366F1',
    amberLine: '#D97706',
    grid: '#E2E8F0',
  };

  const renderStatusChart = (data) => {
    const canvas = document.getElementById('chart-status-distribution');
    if (!canvas) return;
    new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: data.labels,
        datasets: [
          {
            data: data.values,
            backgroundColor: [palette.emerald, palette.blue, palette.amber, palette.rose],
            borderColor: '#FFFFFF',
            borderWidth: 2,
            hoverOffset: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '62%',
        plugins: {
          legend: {
            position: 'bottom',
            labels: { usePointStyle: true, boxWidth: 8, padding: 14, font: { size: 12 } },
          },
        },
      },
    });
  };

  const isMobile = window.matchMedia('(max-width: 639px)').matches;

  const renderConditionChart = (data) => {
    const canvas = document.getElementById('chart-condition-category');
    if (!canvas) return;
    new Chart(canvas, {
      type: 'bar',
      data: {
        labels: data.labels,
        datasets: [
          { label: 'Baik', data: data.good, backgroundColor: palette.emerald, borderRadius: 4 },
          { label: 'Rusak Ringan', data: data.minor_damage, backgroundColor: palette.amber, borderRadius: 4 },
          { label: 'Rusak Berat', data: data.major_damage, backgroundColor: palette.rose, borderRadius: 4 },
        ],
      },
      options: {
        indexAxis: isMobile ? 'y' : 'x',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            stacked: true,
            beginAtZero: isMobile,
            ticks: isMobile ? { precision: 0 } : { autoSkip: false },
            grid: { display: isMobile, color: palette.grid },
          },
          y: {
            stacked: true,
            beginAtZero: !isMobile,
            ticks: isMobile ? { autoSkip: false, font: { size: 11 } } : { precision: 0 },
            grid: { display: !isMobile, color: palette.grid },
          },
        },
        plugins: {
          legend: {
            position: 'bottom',
            labels: { usePointStyle: true, boxWidth: 8, padding: 14, font: { size: 12 } },
          },
        },
      },
    });
  };

  const renderMonthlyActivityChart = (data) => {
    const canvas = document.getElementById('chart-monthly-activity');
    if (!canvas) return;
    new Chart(canvas, {
      type: 'bar',
      data: {
        labels: data.labels,
        datasets: [
          {
            label: 'Pinjaman Online',
            data: data.loans_online,
            backgroundColor: 'rgba(99, 102, 241, 0.78)',
            borderRadius: 4,
          },
          {
            label: 'Pinjaman Walk-In',
            data: data.loans_walk_in,
            backgroundColor: 'rgba(15, 118, 110, 0.78)',
            borderRadius: 4,
          },
          {
            label: 'Pemeliharaan',
            type: 'line',
            data: data.maintenances,
            borderColor: palette.amberLine,
            backgroundColor: 'rgba(217, 119, 6, 0.15)',
            tension: 0.3,
            fill: false,
            pointRadius: 3,
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            grid: { display: false },
            ticks: { autoSkip: false, font: { size: isMobile ? 10 : 12 } },
          },
          y: {
            beginAtZero: true,
            ticks: { precision: 0 },
            grid: { color: palette.grid },
          },
        },
        plugins: {
          legend: {
            position: 'bottom',
            labels: { usePointStyle: true, boxWidth: 8, padding: 14, font: { size: 12 } },
          },
        },
      },
    });
  };

  fetch(apiUrl, { headers: { Accept: 'application/json' } })
    .then((res) => {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then((payload) => {
      renderStatusChart(payload.status_distribution);
      renderConditionChart(payload.condition_by_category);
      renderMonthlyActivityChart(payload.monthly_activity);
    })
    .catch(() => {
      root.querySelectorAll('[data-chart-fallback]').forEach((el) => {
        el.textContent = 'Gagal memuat data grafik.';
        el.classList.remove('hidden');
      });
    });
})();
