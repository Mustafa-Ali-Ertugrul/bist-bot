/* Shared product navigation: CSP-safe logout for the product pages. */
(function () {
  'use strict';

  function authHeaders() {
    var token = localStorage.getItem('bistbot_token');
    return token ? { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' } : {};
  }

  function logout(button) {
    if (button.disabled) return;
    var original = button.textContent;
    button.disabled = true;
    fetch('/api/auth/logout', { method: 'POST', headers: authHeaders() })
      .then(function (res) {
        if (!res.ok) throw new Error('logout_failed');
        localStorage.removeItem('bistbot_token');
        localStorage.removeItem('bistbot_email');
        window.location.replace('/login');
      })
      .catch(function () {
        button.disabled = false;
        button.textContent = 'Çıkış yapılamadı';
        setTimeout(function () { button.textContent = original; }, 2500);
      });
  }

  function checkDataFreshness() {
    if (!localStorage.getItem('bistbot_token')) return;
    fetch('/api/data-status', { headers: authHeaders() })
      .then(function (res) {
        if (!res.ok) return null;
        return res.json();
      })
      .then(function (data) {
        if (!data || !data.stale) return;
        if (document.getElementById('stale-data-banner')) return;
        var banner = document.createElement('div');
        banner.id = 'stale-data-banner';
        banner.setAttribute('role', 'status');
        banner.className = 'w-full max-w-7xl mx-auto px-terminal-margin pt-space-sm font-body-sm text-body-sm text-outline';
        banner.textContent = 'Veri güncelliği uyarısı: Son piyasa verisi (' +
          (data.as_of || 'yok') + '), beklenen seans (' +
          (data.expected_session || '—') + ') gerisinde.';
        var main = document.querySelector('main');
        if (main && main.parentNode) {
          main.parentNode.insertBefore(banner, main);
        }
      })
      .catch(function () { /* optional */ });
  }

  function refreshAlertBadge() {
    if (!localStorage.getItem('bistbot_token')) return;
    var link = document.querySelector('a[href="/ui/alerts"]');
    if (!link) return;
    fetch('/api/alerts/events/unread-count', { headers: authHeaders() })
      .then(function (res) {
        if (!res.ok) return null;
        return res.json();
      })
      .then(function (data) {
        if (!data || !data.unread) return;
        if (link.querySelector('.nav-badge')) return;
        var badge = document.createElement('span');
        badge.className = 'nav-badge';
        badge.textContent = data.unread > 9 ? '9+' : String(data.unread);
        badge.setAttribute('aria-label', data.unread + ' okunmamış alarm');
        link.appendChild(document.createTextNode(' '));
        link.appendChild(badge);
      })
      .catch(function () { /* optional */ });
  }

  function wire() {
    document.addEventListener('click', function (event) {
      var target = event.target;
      if (!target || !target.closest) return;
      var button = target.closest('[data-action="logout"]');
      if (!button) return;
      event.preventDefault();
      logout(button);
    });
    checkDataFreshness();
    refreshAlertBadge();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();