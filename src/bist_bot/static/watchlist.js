/* Faz 5 watchlists. CSP-safe. */
(function () {
  'use strict';
  var lists = [];
  var activeId = null;

  function authHeaders() {
    var t = localStorage.getItem('bistbot_token');
    return t ? { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' } : {};
  }

  function api(path, options) {
    var opts = options || {};
    opts.headers = Object.assign({}, authHeaders(), opts.headers || {});
    return fetch(path, opts).then(function (res) {
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

  function esc(v) {
    return String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function num(v, d) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
    return Number(v).toLocaleString('tr-TR', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
  }

  function pct(v) {
    if (v === null || v === undefined) return '—';
    var n = Number(v);
    return (n > 0 ? '+' : '') + n.toLocaleString('tr-TR', { maximumFractionDigits: 2 }) + '%';
  }

  function status(text) {
    var el = document.getElementById('watch-status');
    if (el) el.textContent = text || '';
  }

  function renderTabs() {
    var container = document.getElementById('lists');
    container.innerHTML = lists.map(function (list) {
      return '<button type="button" data-id="' + list.id + '" aria-pressed="' +
        (list.id === activeId ? 'true' : 'false') + '">' + esc(list.name) +
        ' <span class="screen-count">' + (list.tickers || []).length + '</span></button>';
    }).join('');
    var buttons = container.querySelectorAll('button');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        activeId = Number(event.currentTarget.getAttribute('data-id'));
        render();
      });
    }
  }

  function activeList() {
    return lists.filter(function (list) { return list.id === activeId; })[0] || null;
  }

  function renderRows() {
    var body = document.getElementById('watch-body');
    var list = activeList();
    var nameEl = document.getElementById('active-list-name');
    if (nameEl) nameEl.textContent = list ? list.name : 'Liste seçin';
    if (!list) {
      body.innerHTML = '<tr><td colspan="9" class="py-space-sm">Liste oluşturun veya seçin.</td></tr>';
      return;
    }
    if (!(list.rows || []).length) {
      body.innerHTML = '<tr><td colspan="9" class="py-space-sm">Bu listede hisse yok.</td></tr>';
      return;
    }
    body.innerHTML = list.rows.map(function (row) {
      var alertHref = '/ui/alerts?ticker=' + encodeURIComponent(row.code) +
        (row.close !== null && row.close !== undefined ? '&price=' + encodeURIComponent(row.close) : '');
      return '<tr>' +
        '<td class="sticky-col"><a href="/ui/stock/' + encodeURIComponent(row.code) + '">' + esc(row.code) + '</a></td>' +
        '<td>' + esc(row.name || '') + '</td>' +
        '<td>' + esc(row.sector || '—') + '</td>' +
        '<td class="text-right">' + num(row.close, 2) + '</td>' +
        '<td class="text-right">' + pct(row.change_pct) + '</td>' +
        '<td class="text-right">' + pct(row.ret_1m) + '</td>' +
        '<td class="text-right">' + num(row.rsi14, 1) + '</td>' +
        '<td class="text-right">' + num(row.pe_ttm, 2) + '</td>' +
        '<td class="text-right"><a class="personal-nav" href="' + alertHref + '">Alarm</a> ' +
        '<button type="button" class="personal-remove" data-ticker="' + esc(row.code) + '.IS">Çıkar</button></td>' +
        '</tr>';
    }).join('');
    var removeButtons = body.querySelectorAll('button.personal-remove');
    for (var i = 0; i < removeButtons.length; i++) {
      removeButtons[i].addEventListener('click', function (event) {
        var ticker = event.currentTarget.getAttribute('data-ticker');
        api('/api/watchlists/' + activeId + '/items/' + encodeURIComponent(ticker.replace('.IS', '')), {
          method: 'DELETE'
        }).then(load).catch(function (error) { status(error.message); });
      });
    }
  }

  function render() {
    renderTabs();
    renderRows();
  }

  function load() {
    return api('/api/watchlists').then(function (data) {
      lists = data.watchlists || [];
      if (!lists.some(function (list) { return list.id === activeId; })) {
        activeId = lists.length ? lists[0].id : null;
      }
      render();
    }).catch(function (error) { status(error.message); });
  }

  function wire() {
    document.getElementById('create-list').addEventListener('click', function () {
      var input = document.getElementById('list-name');
      var name = input.value.trim();
      if (!name) return;
      api('/api/watchlists', { method: 'POST', body: JSON.stringify({ name: name }) })
        .then(function (data) {
          input.value = '';
          activeId = data.id;
          return load();
        }).catch(function (error) { status(error.message); });
    });

    document.getElementById('delete-list').addEventListener('click', function () {
      if (!activeId) return;
      api('/api/watchlists/' + activeId, { method: 'DELETE' })
        .then(function () { activeId = null; return load(); })
        .catch(function (error) { status(error.message); });
    });

    document.getElementById('add-ticker-btn').addEventListener('click', function () {
      var input = document.getElementById('add-ticker');
      var code = input.value.trim().toUpperCase();
      if (!activeId) {
        status('Önce bir izleme listesi oluşturun.');
        return;
      }
      if (!code) return;
      api('/api/watchlists/' + activeId + '/items', {
        method: 'POST', body: JSON.stringify({ ticker: code })
      }).then(function () { input.value = ''; status(''); return load(); })
        .catch(function (error) { status(error.message); });
    });

    var tickerInput = document.getElementById('add-ticker');
    var datalist = document.getElementById('ticker-suggestions');
    if (tickerInput && datalist) {
      var searchTimer = null;
      tickerInput.addEventListener('input', function () {
        var q = tickerInput.value.trim();
        if (searchTimer) clearTimeout(searchTimer);
        if (q.length < 2) {
          datalist.innerHTML = '';
          return;
        }
        searchTimer = setTimeout(function () {
          api('/api/stocks/search?q=' + encodeURIComponent(q)).then(function (data) {
            var items = data.results || [];
            datalist.innerHTML = items.map(function (item) {
              return '<option value="' + esc(item.code) + '">' + esc(item.code) + ' · ' + esc(item.name || '') + '</option>';
            }).join('');
          }).catch(function () { /* optional */ });
        }, 200);
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { wire(); load(); });
  } else {
    wire();
    load();
  }
})();
