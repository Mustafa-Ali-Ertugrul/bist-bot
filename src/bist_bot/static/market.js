/* Faz P3.1 market overview. CSP-safe. */
(function () {
  'use strict';

  function authHeaders() {
    var token = localStorage.getItem('bistbot_token');
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }

  function api(path) {
    return fetch(path, { headers: authHeaders() }).then(function (res) {
      if (res.status === 401) {
        window.location.replace('/login');
        throw new Error('auth');
      }
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.message || 'İstek başarısız');
        return data;
      });
    });
  }

  function esc(value) {
    return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function pct(value) {
    if (value === null || value === undefined) return '—';
    var n = Number(value);
    return (n > 0 ? '+' : '') + n.toLocaleString('tr-TR', { maximumFractionDigits: 2 }) + '%';
  }

  function money(value) {
    if (value === null || value === undefined) return '—';
    return Number(value).toLocaleString('tr-TR', { maximumFractionDigits: 0 });
  }

  function price(value) {
    if (value === null || value === undefined) return '—';
    return Number(value).toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function tone(value) {
    if (value === null || value === undefined) return '';
    return Number(value) >= 0 ? 'stock-positive' : 'stock-negative';
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function stockLink(code, label) {
    return '<a class="personal-nav" href="/ui/stock/' + encodeURIComponent(code) + '">' +
      esc(label == null ? code : label) + '</a>';
  }

  function renderLeaders(id, rows, mode) {
    var body = document.getElementById(id);
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="3" class="py-space-sm text-outline">Veri yok.</td></tr>';
      return;
    }
    body.innerHTML = rows.map(function (row) {
      var third = mode === 'volume'
        ? '<td class="text-right ' + tone(row.change_pct) + '">' + pct(row.change_pct) + '</td>'
        : '<td class="text-right ' + tone(row.change_pct) + '">' + pct(row.change_pct) + '</td>';
      var middle = mode === 'volume'
        ? '<td class="text-right">' + money(row.avg_volume_20) + '</td>'
        : '<td class="text-right">' + price(row.close) + '</td>';
      return '<tr><td class="sticky-col">' + stockLink(row.code, row.code) + '</td>' +
        middle + third + '</tr>';
    }).join('');
  }

  function renderSectors(rows) {
    var body = document.getElementById('market-sectors');
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5" class="py-space-sm text-outline">Veri yok.</td></tr>';
      return;
    }
    body.innerHTML = rows.map(function (row) {
      return '<tr>' +
        '<td class="sticky-col">' + esc(row.sector) + '</td>' +
        '<td class="text-right">' + money(row.count) + '</td>' +
        '<td class="text-right ' + tone(row.avg_change_pct) + '">' + pct(row.avg_change_pct) + '</td>' +
        '<td class="text-right ' + tone(row.median_change_pct) + '">' + pct(row.median_change_pct) + '</td>' +
        '<td class="text-right ' + tone(row.avg_ret_1m_pct) + '">' + pct(row.avg_ret_1m_pct) + '</td>' +
        '</tr>';
    }).join('');
  }

  function renderScans(rows) {
    var wrap = document.getElementById('market-scans');
    if (!wrap) return;
    if (!rows.length) {
      wrap.innerHTML = '<span class="font-body-sm text-body-sm text-outline">Tarama yok.</span>';
      return;
    }
    wrap.innerHTML = rows.map(function (row) {
      return '<a class="screen-button" href="/ui/screener?screen=' + encodeURIComponent(row.code) + '">' +
        esc(row.title) + ' <strong>' + money(row.count) + '</strong></a>';
    }).join(' ');
  }

  function render(data) {
    var index = data.index;
    setText('market-index', index ? price(index.close) : '—');
    var changeEl = document.getElementById('market-index-change');
    if (changeEl) {
      changeEl.textContent = index ? pct(index.change_pct) : 'Endeks verisi yok';
      changeEl.className = 'font-body-sm text-body-sm ' + (index ? tone(index.change_pct) : 'text-outline');
    }

    var breadth = data.breadth || {};
    setText('market-advancers', money(breadth.advancers));
    setText('market-decliners', money(breadth.decliners));
    setText('market-total', money(breadth.total));
    var total = Number(breadth.total || 0);
    setText('market-advancers-share', total ? '%' + Number((breadth.advancers / total) * 100).toFixed(1) + ' pay' : '—');
    setText('market-decliners-share', total ? '%' + Number((breadth.decliners / total) * 100).toFixed(1) + ' pay' : '—');
    setText('market-unchanged', money(breadth.unchanged) + ' değişmeyen');
    setText('market-asof', 'Veri tarihi: ' + (data.as_of || '—'));

    var leaders = data.leaders || {};
    renderLeaders('market-gainers', leaders.gainers || [], 'price');
    renderLeaders('market-losers', leaders.losers || [], 'price');
    renderLeaders('market-volume', leaders.volume || [], 'volume');
    renderSectors(data.sectors || []);
    renderScans(data.scans || []);
  }

  function loadDates() {
    var select = document.getElementById('market-date');
    if (!select) return;
    api('/api/screens').then(function (data) {
      var dates = data.dates || [];
      if (!dates.length) return;
      select.innerHTML = dates.slice(0, 20).map(function (value) {
        return '<option value="' + esc(value) + '">' + esc(value) + '</option>';
      }).join('');
      if (data.as_of) select.value = data.as_of;
    }).catch(function () { /* optional */ });
  }

  function load() {
    var select = document.getElementById('market-date');
    var asOf = select && select.value ? select.value : '';
    var path = '/api/market/overview' + (asOf ? '?as_of=' + encodeURIComponent(asOf) : '');
    setText('market-status', 'Hesaplanıyor…');
    api(path).then(function (data) {
      render(data);
      setText('market-status', '');
    }).catch(function (error) {
      setText('market-status', error.message);
    });
  }

  function boot() {
    loadDates();
    var reload = document.getElementById('market-reload');
    if (reload) reload.addEventListener('click', load);
    var select = document.getElementById('market-date');
    if (select) select.addEventListener('change', load);
    load();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
