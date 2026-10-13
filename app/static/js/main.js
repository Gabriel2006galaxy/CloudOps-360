/**
 * CloudOps 360: Front-End Core Interaction Scripts
 * Dark/Light Mode, Sidebar Collapsing, Notification Polling, Toasts
 */

document.addEventListener('DOMContentLoaded', function () {
  initTheme();
  initSidebar();
  initNotifications();
  initGlobalShortcuts();
  initAutoDismissAlerts();
});

/* ---------------- THEME MANAGEMENT (DARK / LIGHT) ---------------- */
function initTheme() {
  const themeToggleBtn = document.getElementById('theme-toggle-btn');
  const storedTheme = localStorage.getItem('cloudops-theme') || 'dark'; // Default to dark for high-tech cloud ops feel

  setTheme(storedTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener('click', function () {
      const currentTheme = document.documentElement.getAttribute('data-bs-theme');
      const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      setTheme(newTheme);
      localStorage.setItem('cloudops-theme', newTheme);
    });
  }
}

function setTheme(theme) {
  document.documentElement.setAttribute('data-bs-theme', theme);
  const icon = document.getElementById('theme-toggle-icon');
  if (icon) {
    if (theme === 'dark') {
      icon.className = 'bi bi-sun-fill text-warning';
    } else {
      icon.className = 'bi bi-moon-stars-fill text-navy';
    }
  }
  // Dispatch custom event for Chart.js theme refresh
  window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
}

/* ---------------- SIDEBAR COLLAPSE & MOBILE DRAWER ---------------- */
function initSidebar() {
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const mobileToggle = document.getElementById('sidebar-mobile-toggle');
  const backdrop = document.getElementById('sidebar-backdrop');

  if (sidebarToggle) {
    sidebarToggle.addEventListener('click', function () {
      document.body.classList.toggle('sidebar-collapsed');
      const isCollapsed = document.body.classList.contains('sidebar-collapsed');
      localStorage.setItem('cloudops-sidebar-collapsed', isCollapsed ? 'true' : 'false');
    });
  }

  // Restore saved collapse preference on desktop
  if (window.innerWidth >= 992 && localStorage.getItem('cloudops-sidebar-collapsed') === 'true') {
    document.body.classList.add('sidebar-collapsed');
  }

  if (mobileToggle) {
    mobileToggle.addEventListener('click', function () {
      document.body.classList.toggle('sidebar-mobile-open');
    });
  }

  if (backdrop) {
    backdrop.addEventListener('click', function () {
      document.body.classList.remove('sidebar-mobile-open');
    });
  }
}

/* ---------------- NOTIFICATIONS REALTIME / AJAX ---------------- */
function initNotifications() {
  const markAllBtn = document.getElementById('mark-all-notifications-read');
  if (markAllBtn) {
    markAllBtn.addEventListener('click', function (e) {
      e.preventDefault();
      fetch('/notifications/read-all', {
        method: 'POST',
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': getCsrfToken()
        }
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          const badge = document.getElementById('unread-notification-badge');
          if (badge) badge.style.display = 'none';
          document.querySelectorAll('.notification-unread-dot').forEach(el => el.remove());
          showToast('Notifications', 'All notifications marked as read.', 'info');
        }
      })
      .catch(err => console.error('Error marking notifications read:', err));
    });
  }
}

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}

/* ---------------- GLOBAL SHORTCUTS (CTRL+K) ---------------- */
function initGlobalShortcuts() {
  document.addEventListener('keydown', function (e) {
    // Ctrl+K or Cmd+K to focus search input
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      const searchInput = document.getElementById('global-search-input');
      if (searchInput) {
        searchInput.focus();
      }
    }
  });
}

/* ---------------- TOASTS & ALERTS ---------------- */
function initAutoDismissAlerts() {
  // Automatically dismiss non-danger flash alerts after 6 seconds
  setTimeout(function () {
    const alerts = document.querySelectorAll('.alert-dismissible:not(.alert-danger)');
    alerts.forEach(function (alert) {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    });
  }, 6000);
}

function showToast(title, message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toastId = 'toast-' + Date.now();
  const bgClass = type === 'success' ? 'text-bg-success' : type === 'danger' ? 'text-bg-danger' : 'text-bg-info';
  
  const html = `
    <div id="${toastId}" class="toast align-items-center ${bgClass} border-0 mb-2" role="alert" aria-live="assertive" aria-atomic="true">
      <div class="d-flex">
        <div class="toast-body">
          <strong>${title}:</strong> ${message}
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    </div>
  `;
  container.insertAdjacentHTML('beforeend', html);
  const el = document.getElementById(toastId);
  const toast = new bootstrap.Toast(el, { delay: 4000 });
  toast.show();
  el.addEventListener('hidden.bs.toast', () => el.remove());
}
