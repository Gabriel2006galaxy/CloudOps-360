/**
 * CloudOps 360 — core front-end behaviour
 * Theme, sidebar, notifications (polling + mark read), toasts, confirmation
 * dialogs, keyboard shortcuts, form submit feedback and session-expiry warning.
 * All data comes from the server; nothing here is a primary data store.
 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    initTheme();
    initSidebar();
    initToasts();
    initConfirmDialogs();
    initNotifications();
    initShortcuts();
    initFormFeedback();
    initAutoSubmitFilters();
    initSessionWarning();
  });

  function storage(op, key, value) {
    try {
      if (op === 'get') return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* private mode: preferences simply are not remembered */ }
    return null;
  }

  /* ---------------- Theme ---------------- */
  function initTheme() {
    var btn = document.getElementById('theme-toggle-btn');
    applyThemeIcon(document.documentElement.getAttribute('data-bs-theme'));
    if (!btn) return;
    btn.addEventListener('click', function () {
      var next = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-bs-theme', next);
      storage('set', 'cloudops-theme', next);
      applyThemeIcon(next);
      window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: next } }));
    });
  }

  function applyThemeIcon(theme) {
    var icon = document.getElementById('theme-toggle-icon');
    if (icon) icon.className = theme === 'dark' ? 'bi bi-sun-fill text-warning' : 'bi bi-moon-stars-fill text-primary';
  }

  /* ---------------- Sidebar ---------------- */
  function initSidebar() {
    var toggle = document.getElementById('sidebar-toggle');
    var mobileToggle = document.getElementById('sidebar-mobile-toggle');
    var backdrop = document.getElementById('sidebar-backdrop');

    if (document.documentElement.classList.contains('sidebar-pref-collapsed')) {
      document.body.classList.add('sidebar-collapsed');
    }
    if (toggle) {
      toggle.addEventListener('click', function () {
        var collapsed = document.body.classList.toggle('sidebar-collapsed');
        storage('set', 'cloudops-sidebar-collapsed', collapsed ? 'true' : 'false');
      });
    }
    function setMobile(open) {
      document.body.classList.toggle('sidebar-mobile-open', open);
      if (mobileToggle) mobileToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    if (mobileToggle) mobileToggle.addEventListener('click', function () {
      setMobile(!document.body.classList.contains('sidebar-mobile-open'));
    });
    if (backdrop) backdrop.addEventListener('click', function () { setMobile(false); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && document.body.classList.contains('sidebar-mobile-open')) setMobile(false);
    });
  }

  /* ---------------- Toasts ---------------- */
  function initToasts() {
    if (!window.bootstrap) return;
    document.querySelectorAll('.flash-toast').forEach(function (el) {
      bootstrap.Toast.getOrCreateInstance(el).show();
    });
  }

  function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  window.showToast = function (title, message, type) {
    var container = document.getElementById('toast-container');
    if (!container || !window.bootstrap) return;
    var tone = { success: 'success', danger: 'danger', warning: 'warning' }[type] || 'info';
    var el = document.createElement('div');
    el.className = 'toast align-items-center text-bg-' + tone + ' border-0 mb-2';
    el.setAttribute('role', tone === 'danger' ? 'alert' : 'status');
    el.innerHTML = '<div class="d-flex"><div class="toast-body"><strong>' + escapeHtml(title) + ':</strong> ' +
      escapeHtml(message) + '</div><button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div>';
    container.appendChild(el);
    var toast = new bootstrap.Toast(el, { delay: 5000 });
    el.addEventListener('hidden.bs.toast', function () { el.remove(); });
    toast.show();
  };

  /* ---------------- Confirmation dialogs ----------------
   * <form data-confirm="Delete this file?" data-confirm-button="Delete"> ... */
  function initConfirmDialogs() {
    var modalEl = document.getElementById('confirmModal');
    if (!modalEl || !window.bootstrap) return;
    var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    var body = document.getElementById('confirmModalBody');
    var okBtn = document.getElementById('confirmModalOk');
    var pendingForm = null;

    document.addEventListener('submit', function (e) {
      var form = e.target;
      if (!form.matches || !form.matches('form[data-confirm]') || form.dataset.confirmed === 'true') return;
      e.preventDefault();
      pendingForm = form;
      body.textContent = form.getAttribute('data-confirm');
      okBtn.textContent = form.getAttribute('data-confirm-button') || 'Confirm';
      okBtn.className = 'btn ' + (form.getAttribute('data-confirm-class') || 'btn-danger');
      modal.show();
    }, true);

    okBtn.addEventListener('click', function () {
      if (!pendingForm) return;
      pendingForm.dataset.confirmed = 'true';
      modal.hide();
      if (pendingForm.requestSubmit) pendingForm.requestSubmit(); else pendingForm.submit();
      pendingForm = null;
    });
  }

  /* ---------------- Notifications ---------------- */
  function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }
  window.getCsrfToken = getCsrfToken;

  function setUnreadCount(count) {
    document.querySelectorAll('[data-unread-count]').forEach(function (el) {
      el.textContent = count;
      el.classList.toggle('d-none', !count);
    });
    var markAll = document.getElementById('mark-all-notifications-read');
    if (markAll) markAll.classList.toggle('d-none', !count);
  }

  function initNotifications() {
    if (document.body.dataset.authenticated !== 'true') return;
    var markAll = document.getElementById('mark-all-notifications-read');
    if (markAll) {
      markAll.addEventListener('click', function () {
        fetch('/notifications/read-all', {
          method: 'POST',
          headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCsrfToken() },
          credentials: 'same-origin'
        }).then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        }).then(function () {
          setUnreadCount(0);
          document.querySelectorAll('.notification-item.unread').forEach(function (el) { el.classList.remove('unread'); });
          showToast('Notifications', 'All notifications marked as read.', 'success');
        }).catch(function () {
          showToast('Notifications', 'Could not update notifications. Please reload the page.', 'danger');
        });
      });
    }

    // Poll the unread counter; the header tells the server not to extend the idle session
    setInterval(function () {
      if (document.hidden) return;
      fetch('/api/notifications/unread-count', {
        headers: { 'X-Background-Poll': '1', 'Accept': 'application/json' },
        credentials: 'same-origin'
      }).then(function (res) {
        if (res.status === 401) { window.location.reload(); return null; }
        return res.ok ? res.json() : null;
      }).then(function (data) {
        if (data && typeof data.unread_count === 'number') setUnreadCount(data.unread_count);
      }).catch(function () { /* offline: try again next tick */ });
    }, 45000);
  }

  /* ---------------- Keyboard shortcuts ---------------- */
  function initShortcuts() {
    document.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        var input = document.getElementById('global-search-input');
        if (input && input.offsetParent !== null) { e.preventDefault(); input.focus(); input.select(); }
      }
    });
  }

  /* ---------------- Form feedback ----------------
   * Disables submit buttons on submit (prevents double posts) and shows a spinner. */
  function initFormFeedback() {
    document.addEventListener('submit', function (e) {
      var form = e.target;
      if (e.defaultPrevented || form.method.toLowerCase() !== 'post') return;
      if (form.matches('form[data-confirm]') && form.dataset.confirmed !== 'true') return;
      if (typeof form.checkValidity === 'function' && !form.checkValidity()) return;
      var btn = form.querySelector('button[type="submit"]:not([data-no-spinner])');
      if (btn && !btn.disabled) {
        btn.dataset.originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>' + btn.textContent.trim();
        setTimeout(function () { btn.disabled = true; }, 0);
      }
    });
    // Restore buttons when navigating back to a cached page
    window.addEventListener('pageshow', function () {
      document.querySelectorAll('button[data-original-html]').forEach(function (btn) {
        btn.innerHTML = btn.dataset.originalHtml;
        btn.disabled = false;
      });
    });

    // Client-side size check for file inputs (the server re-validates everything)
    document.querySelectorAll('input[type="file"][data-max-bytes]').forEach(function (input) {
      input.addEventListener('change', function () {
        var max = parseInt(input.dataset.maxBytes, 10);
        var file = input.files && input.files[0];
        input.setCustomValidity(file && file.size > max ? 'File is larger than ' + Math.round(max / 1048576) + ' MB.' : '');
        input.reportValidity();
      });
    });
  }

  /* Filter selects with data-autosubmit submit their form on change */
  function initAutoSubmitFilters() {
    document.querySelectorAll('[data-autosubmit]').forEach(function (el) {
      el.addEventListener('change', function () { if (el.form) el.form.submit(); });
    });
  }

  /* ---------------- Session expiry warning ---------------- */
  function initSessionWarning() {
    if (document.body.dataset.authenticated !== 'true') return;
    var minutes = parseInt(document.body.dataset.idleMinutes, 10);
    if (!minutes || minutes < 3) return;
    setTimeout(function () {
      showToast('Session', 'Your session will expire in about 2 minutes due to inactivity. Save your work or reload the page.', 'warning');
    }, (minutes - 2) * 60000);
  }
})();
