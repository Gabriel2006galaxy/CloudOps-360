/**
 * CloudOps 360: Chart.js Analytics Helper Functions
 */

let priorityChartInstance = null;
let statusChartInstance = null;
let categoryChartInstance = null;

function renderPriorityChart(canvasId, labels, data) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
  const textColor = isDark ? '#94a3b8' : '#64748b';

  if (priorityChartInstance) {
    priorityChartInstance.destroy();
  }

  priorityChartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: [
          '#ef4444', // Critical - Red
          '#f59e0b', // High - Amber
          '#0ea5e9', // Medium - Cyan
          '#64748b'  // Low - Slate
        ],
        borderWidth: 2,
        borderColor: isDark ? '#131c31' : '#ffffff'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: textColor, padding: 15, font: { family: 'Inter', size: 12 } }
        }
      },
      cutout: '70%'
    }
  });
}

function renderStatusChart(canvasId, labels, data) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
  const textColor = isDark ? '#94a3b8' : '#64748b';

  if (statusChartInstance) {
    statusChartInstance.destroy();
  }

  statusChartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: [
          '#0284c7', // Open - Blue
          '#06b6d4', // Assigned - Cyan
          '#f59e0b', // In Progress - Amber
          '#10b981', // Resolved - Emerald
          '#475569'  // Closed - Slate
        ],
        borderWidth: 2,
        borderColor: isDark ? '#131c31' : '#ffffff'
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: textColor, padding: 15, font: { family: 'Inter', size: 12 } }
        }
      },
      cutout: '70%'
    }
  });
}

function renderCategoryChart(canvasId, labels, data) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
  const textColor = isDark ? '#94a3b8' : '#64748b';
  const gridColor = isDark ? '#1e293b' : '#e2e8f0';

  if (categoryChartInstance) {
    categoryChartInstance.destroy();
  }

  categoryChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Incidents Count',
        data: data,
        backgroundColor: 'rgba(6, 182, 212, 0.75)',
        borderColor: '#06b6d4',
        borderWidth: 1,
        borderRadius: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          ticks: { color: textColor, font: { family: 'Inter', size: 11 } },
          grid: { display: false }
        },
        y: {
          beginAtZero: true,
          ticks: { color: textColor, stepSize: 1, font: { family: 'Inter', size: 11 } },
          grid: { color: gridColor }
        }
      },
      plugins: {
        legend: { display: false }
      }
    }
  });
}
