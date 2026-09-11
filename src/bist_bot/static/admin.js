/* BIST Bot – Admin page logic (CSP-safe, no inline handlers) */
(function () {
  'use strict';

  function authHeaders() {
    var t = localStorage.getItem('bistbot_token');
    return t ? { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' } : {};
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function loadAdminUsers() {
    var body = document.getElementById('admin-users-body');
    var q = (document.getElementById('admin-user-search') || {}).value || '';
    fetch('/api/admin/users?q=' + encodeURIComponent(q), { headers: authHeaders() }).then(function (res) {
      if (res.status === 403) {
        if (body) body.innerHTML = '<tr><td colspan="6" class="py-space-md text-center text-error">Yetkisiz erişim.</td></tr>';
        return;
      }
      return res.json().then(function (data) {
        if (!res.ok || !Array.isArray(data.users) || !data.users.length) {
          if (body) body.innerHTML = '<tr><td colspan="6" class="py-space-md text-center text-outline">Kullanıcı bulunamadı.</td></tr>';
          return;
        }
        body.innerHTML = data.users.map(function (u) {
          return '<tr class="border-t border-surface-container-highest/40">' +
            '<td class="py-space-2xs pr-space-sm font-label-code text-label-code">' + esc(u.id) + '</td>' +
            '<td class="py-space-2xs pr-space-sm">' + esc(u.email) + '</td>' +
            '<td class="py-space-2xs pr-space-sm">' + esc(u.role) + '</td>' +
            '<td class="py-space-2xs pr-space-sm text-primary font-bold">' + esc(u.plan) + (u.active ? '' : ' (pasif)') + '</td>' +
            '<td class="py-space-2xs pr-space-sm font-label-code text-label-code">' + esc(u.plan_expires_at || '—') + '</td>' +
            '<td class="py-space-2xs"><div class="flex gap-space-2xs">' +
            '<button class="px-space-xs py-space-3xs rounded bg-surface-container-high font-label-code text-label-code" data-action="set-plan" data-user-id="' + u.id + '" data-plan="pro">Pro</button>' +
            '<button class="px-space-xs py-space-3xs rounded bg-surface-container-high font-label-code text-label-code" data-action="set-plan" data-user-id="' + u.id + '" data-plan="pro_plus">Pro+</button>' +
            '</div></td></tr>';
        }).join('');
      });
    }).catch(function () {
      if (body) body.innerHTML = '<tr><td colspan="6" class="py-space-md text-center text-error">Bağlantı hatası.</td></tr>';
    });
  }

  function setUserPlan(userId, plan) {
    fetch('/api/admin/users/' + userId + '/plan', {
      method: 'POST', headers: authHeaders(), body: JSON.stringify({ plan: plan })
    }).then(function (res) {
      return res.json().then(function (data) {
        alert(res.ok ? ('Plan güncellendi: ' + data.plan + ' (bitiş: ' + data.plan_expires_at + ')') : ('Hata: ' + (data.message || res.status)));
        if (res.ok) loadAdminUsers();
      });
    }).catch(function () { alert('Bağlantı hatası.'); });
  }

  function loadAdminRequests() {
    var body = document.getElementById('admin-requests-body');
    fetch('/api/admin/requests?status=pending', { headers: authHeaders() }).then(function (res) {
      if (res.status === 403) {
        if (body) body.innerHTML = '<tr><td colspan="7" class="py-space-md text-center text-error">Yetkisiz erişim.</td></tr>';
        return;
      }
      return res.json().then(function (data) {
        if (!res.ok || !Array.isArray(data.requests) || !data.requests.length) {
          if (body) body.innerHTML = '<tr><td colspan="7" class="py-space-md text-center text-outline">Bekleyen ödeme yok.</td></tr>';
          return;
        }
        body.innerHTML = data.requests.map(function (r) {
          return '<tr class="border-t border-surface-container-highest/40">' +
            '<td class="py-space-2xs pr-space-sm font-label-code text-label-code">' + esc(r.id) + '</td>' +
            '<td class="py-space-2xs pr-space-sm">' + esc(r.email) + '</td>' +
            '<td class="py-space-2xs pr-space-sm text-primary font-bold">' + esc(r.plan) + '</td>' +
            '<td class="py-space-2xs pr-space-sm">' + esc(r.amount_try) + ' TL</td>' +
            '<td class="py-space-2xs pr-space-sm font-label-code text-label-code">' + esc(r.reference) + '</td>' +
            '<td class="py-space-2xs pr-space-sm font-label-code text-label-code">' + esc(r.created_at) + '</td>' +
            '<td class="py-space-2xs"><div class="flex gap-space-2xs">' +
            '<button class="px-space-xs py-space-3xs rounded bg-primary text-on-primary font-label-code text-label-code" data-action="decide" data-request-id="' + r.id + '" data-approve="true">Onayla</button>' +
            '<button class="px-space-xs py-space-3xs rounded bg-surface-container-high font-label-code text-label-code" data-action="decide" data-request-id="' + r.id + '" data-approve="false">Reddet</button>' +
            '</div></td></tr>';
        }).join('');
      });
    }).catch(function () {
      if (body) body.innerHTML = '<tr><td colspan="7" class="py-space-md text-center text-error">Bağlantı hatası.</td></tr>';
    });
  }

  function decideRequest(requestId, approve) {
    var box = document.getElementById('admin-invite-box');
    fetch('/api/admin/requests/' + requestId + (approve ? '/approve' : '/reject'), {
      method: 'POST', headers: authHeaders()
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          alert('Hata: ' + (data.message || res.status));
          return;
        }
        if (approve && data.invite_link && box) {
          box.classList.remove('hidden');
          box.textContent = 'Pro+ davet linki (tek kullanımlık, 48s): ' + data.invite_link;
        }
        loadAdminRequests();
        loadAdminUsers();
      });
    }).catch(function () { alert('Bağlantı hatası.'); });
  }

  // ── Event delegation (CSP-safe: no inline onclick needed) ──
  document.addEventListener('DOMContentLoaded', function () {
    loadAdminRequests();
    loadAdminUsers();

    // Refresh buttons
    var refreshUsersBtn = document.getElementById('admin-refresh-users');
    if (refreshUsersBtn) refreshUsersBtn.addEventListener('click', function () { loadAdminUsers(); });
    var refreshRequestsBtn = document.getElementById('admin-refresh-requests');
    if (refreshRequestsBtn) refreshRequestsBtn.addEventListener('click', function () { loadAdminRequests(); });

    // Delegated click handler for dynamically rendered buttons
    document.addEventListener('click', function (e) {
      var setPlanBtn = e.target.closest('[data-action="set-plan"]');
      if (setPlanBtn) {
        e.preventDefault();
        setUserPlan(setPlanBtn.getAttribute('data-user-id'), setPlanBtn.getAttribute('data-plan'));
        return;
      }
      var decideBtn = e.target.closest('[data-action="decide"]');
      if (decideBtn) {
        e.preventDefault();
        decideRequest(decideBtn.getAttribute('data-request-id'), decideBtn.getAttribute('data-approve') === 'true');
      }
    });
  });
})();
