/**
 * CloudOps 360 — Chart.js helpers.
 * Every chart receives data rendered by the server from database queries.
 * Charts re-render on theme change and hide their loading skeleton once drawn.
 */
(function () {
  'use strict';

  var registry = [];
  var COLORS = {
    priority: { Critical: '#ef4444', High: '#f59e0b', Medium: '#0ea5e9', Low: '#64748b' },
    status: { 'Open': '#0284c7', 'Assigned': '#06b6d4', 'In Progress': '#f59e0b', 'Resolved': '#10b981', 'Closed': '#64748b' },
    series: ['#06b6d4', '#10b981', '#6366f1', '#f59e0b', '#ef4444', '#0284c7', '#a855f7', '#14b8a6']
  };

  function themeColors() {
    var dark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
    return {
      text: dark ? '#94a3b8' : '#475569',
      grid: dark ? 'rgba(148,163,184,0.12)' : '#e2e8f0',
      border: dark ? '#131c31' : '#ffffff'
    };
  }

  function markReady(canvas) {
    var box = canvas.closest('[data-chart-box]');
    if (box) box.classList.add('is-ready');
  }

  function build(canvasId, configFactory) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || typeof Chart === 'undefined') return null;
    var entry = { canvas: canvas, factory: configFactory, chart: null };
    entry.chart = new Chart(canvas, configFactory(themeColors()));
    markReady(canvas);
    registry.push(entry);
    return entry.chart;
  }

  function shortLabel(value) {
    var text = String(value);
    return text.length > 24 ? text.slice(0, 23) + '…' : text;
  }

  function legend(c) {
    return { position: 'bottom', labels: { color: c.text, padding: 14, boxWidth: 12, font: { family: 'Inter', size: 12 } } };
  }

  window.CloudOpsCharts = {
    doughnut: function (canvasId, labels, data, palette) {
      return build(canvasId, function (c) {
        return {
          type: 'doughnut',
          data: { labels: labels, datasets: [{ data: data, borderWidth: 2, borderColor: c.border,
            backgroundColor: labels.map(function (l, i) { return (palette && palette[l]) || COLORS.series[i % COLORS.series.length]; }) }] },
          options: { responsive: true, maintainAspectRatio: false, cutout: '68%', plugins: { legend: legend(c) } }
        };
      });
    },
    bar: function (canvasId, labels, data, opts) {
      opts = opts || {};
      return build(canvasId, function (c) {
        return {
          type: 'bar',
          data: { labels: labels, datasets: [{ label: opts.label || 'Tickets', data: data, borderRadius: 6,
            backgroundColor: opts.colors || 'rgba(6, 182, 212, 0.75)', borderColor: '#06b6d4', borderWidth: 1 }] },
          options: {
            responsive: true, maintainAspectRatio: false, indexAxis: opts.horizontal ? 'y' : 'x',
            plugins: { legend: { display: false }, tooltip: { callbacks: { title: function (items) { return items[0].label; } } } },
            scales: {
              x: { beginAtZero: true, ticks: { color: c.text, precision: 0, font: { family: 'Inter', size: 11 },
                     callback: function (v) { return opts.horizontal ? v : shortLabel(this.getLabelForValue(v)); } },
                   grid: { display: !!opts.horizontal, color: c.grid } },
              y: { beginAtZero: true, ticks: { color: c.text, precision: 0, font: { family: 'Inter', size: 11 },
                     callback: function (v) { return opts.horizontal ? shortLabel(this.getLabelForValue(v)) : v; } },
                   grid: { display: !opts.horizontal, color: c.grid } }
            }
          }
        };
      });
    },
    trend: function (canvasId, labels, created, resolved) {
      return build(canvasId, function (c) {
        return {
          type: 'line',
          data: {
            labels: labels,
            datasets: [
              { label: 'Created', data: created, borderColor: '#06b6d4', backgroundColor: 'rgba(6,182,212,0.15)', fill: true, cubicInterpolationMode: 'monotone', pointRadius: 2 },
              { label: 'Resolved', data: resolved, borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.08)', fill: true, cubicInterpolationMode: 'monotone', pointRadius: 2 }
            ]
          },
          options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            plugins: { legend: legend(c) },
            scales: {
              x: { ticks: { color: c.text, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }, grid: { display: false } },
              y: { beginAtZero: true, ticks: { color: c.text, precision: 0 }, grid: { color: c.grid } }
            }
          }
        };
      });
    },
    COLORS: COLORS
  };

  // Skeletons for boxes without a canvas (empty state) are removed immediately
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-chart-box]').forEach(function (box) {
      if (!box.querySelector('canvas')) box.classList.add('is-ready');
    });
  });

  window.addEventListener('themeChanged', function () {
    var c = themeColors();
    registry.forEach(function (entry) {
      if (entry.chart) entry.chart.destroy();
      entry.chart = new Chart(entry.canvas, entry.factory(c));
    });
  });
})();
