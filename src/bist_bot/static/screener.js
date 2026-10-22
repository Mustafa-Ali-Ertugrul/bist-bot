/* Faz 4 screener. CSP-safe: no inline handlers. */
(function () {
  'use strict';

  var fields = [];
  var catalog = { screens: [], dates: [], as_of: null };
  var currentScan = null;
  var currentDate = null;
  var currentSort = 'market_cap_tl';
  var highlightField = null;
  var mode = 'screen'; // "screen" | "filter"

  function authHeaders() {
    var token = localStorage.getItem('bistbot_token');
    return token ? { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' } : {};
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

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function num(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return Number(value).toLocaleString('tr-TR', {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0
    });
  }

  function money(value) {
    if (value === null || value === undefined) return '—';
    var n = Number(value);
    if (Math.abs(n) >= 1e9) return (n / 1e9).toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + ' milyar';
    if (Math.abs(n) >= 1e6) return (n / 1e6).toLocaleString('tr-TR', { maximumFractionDigits: 0 }) + ' mn';
    return num(n, 0);
  }

  function pct(value) {
    if (value === null || value === undefined) return '—';
    var n = Number(value);
    return (n > 0 ? '+' : '') + n.toLocaleString('tr-TR', { maximumFractionDigits: 2 }) + '%';
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  // --------------------------------------------------------------- catalog UI
  function renderScreens() {
    var list = document.getElementById('screen-list');
    if (!list) return;
    var items = (catalog.screens || []).map(function (screen) {
      var pressed = currentScan === screen.code ? 'true' : 'false';
      return '<li><button type="button" data-scan="' + escapeHtml(screen.code) + '" aria-pressed="' +
        pressed + '"><span><strong>' + escapeHtml(screen.title) + '</strong><br><small>' +
        escapeHtml(screen.description) + '</small></span><span class="screen-count">' +
        num(screen.count, 0) + '</span></button></li>';
    });
    list.innerHTML = items.join('');
    var buttons = list.querySelectorAll('button[data-scan]');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        currentScan = event.currentTarget.getAttribute('data-scan');
        mode = 'screen';
        renderScreens();
        loadScreenRows();
      });
    }
  }

  function fillDates() {
    var select = document.getElementById('screen-date');
    if (!select) return;
    var dates = catalog.dates || [];
    select.innerHTML = dates.map(function (item) {
      return '<option value="' + escapeHtml(item) + '">' + escapeHtml(item) + '</option>';
    }).join('');
    currentDate = dates.length ? dates[0] : null;
    select.addEventListener('change', function () {
      currentDate = select.value || null;
      if (mode === 'screen') loadScreenRows();
    });
  }

  function fillSort() {
    var select = document.getElementById('screen-sort');
    if (!select) return;
    select.innerHTML = fields.map(function (field) {
      return '<option value="' + escapeHtml(field.code) + '">' + escapeHtml(field.label) + '</option>';
    }).join('');
    select.value = currentSort;
    select.addEventListener('change', function () {
      currentSort = select.value || 'market_cap_tl';
      if (mode === 'screen') loadScreenRows();
    });
  }

  function fillFilterSelects() {
    var sector = document.getElementById('filter-sector');
    var screen = document.getElementById('filter-screen');
    if (sector && sector.options.length <= 1) {
      api('/api/screens/fields').then(function (data) {
        (data.sectors || []).forEach(function (name) {
          var option = document.createElement('option');
          option.value = name;
          option.textContent = name;
          sector.appendChild(option);
        });
      }).catch(function () { /* optional */ });
    }
    if (screen && screen.options.length <= 1) {
      (catalog.screens || []).forEach(function (item) {
        var option = document.createElement('option');
        option.value = item.code;
        option.textContent = item.title;
        screen.appendChild(option);
      });
    }
  }

  // --------------------------------------------------------------- table render
  function renderRows(payload) {
    var body = document.getElementById('screen-body');
    if (!body) return;
    var rows = payload.rows || [];
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="7" class="py-space-sm">Sonuç yok.</td></tr>';
    } else {
      body.innerHTML = rows.map(function (row) {
        var m = row.metrics || {};
        var value;
        if (row.scan_value !== undefined) {
          value = row.scan_value;
        } else if (highlightField) {
          value = m[highlightField];
        } else {
          value = null;
        }
        return '<tr>' +
          '<td><a href="/ui/stock/' + encodeURIComponent(row.code) + '">' + escapeHtml(row.code) + '</a></td>' +
          '<td>' + escapeHtml(row.name || '') + '</td>' +
          '<td>' + escapeHtml(row.sector || '—') + '</td>' +
          '<td class="text-right">' + num(m.close, 2) + '</td>' +
          '<td class="text-right">' + pct(m.change_pct) + '</td>' +
          '<td class="text-right">' + num(value, 2) + '</td>' +
          '<td class="text-right">' + money(m.market_cap_tl) + '</td>' +
          '</tr>';
      }).join('');
    }
    var meta = (payload.total || 0) + ' sonuç · ' + (payload.as_of || '—');
    if (payload.truncated) {
      meta += ' · ücretsiz görünümde ilk ' + payload.returned + ' sonuç gösteriliyor';
    }
    setText('screen-meta', meta);
  }

  function loadScreenRows() {
    if (!currentScan) return;
    highlightField = null;
    var query = '?limit=50&sort=' + encodeURIComponent(currentSort);
    if (currentDate) query += '&as_of=' + encodeURIComponent(currentDate);
    api('/api/screens/' + encodeURIComponent(currentScan) + query).then(function (payload) {
      renderRows(payload);
      var screen = (catalog.screens || []).filter(function (item) {
        return item.code === currentScan;
      })[0];
      if (screen) {
        setText('screen-title', screen.title);
        setText('screen-description', screen.description);
      }
    }).catch(function (error) {
      setText('screen-meta', error.message);
    });
  }

  // ------------------------------------------------------------- custom filter
  function fieldOptions(selected) {
    return fields.map(function (field) {
      return '<option value="' + escapeHtml(field.code) + '"' +
        (field.code === selected ? ' selected' : '') + '>' + escapeHtml(field.label) + '</option>';
    }).join('');
  }

  function addCondition(field, op, value, value2) {
    var container = document.getElementById('condition-rows');
    if (!container) return;
    if (container.children.length >= 10) {
      setText('filter-status', 'En fazla 10 koşul eklenebilir.');
      return;
    }
    var row = document.createElement('div');
    row.className = 'screen-condition';
    row.innerHTML =
      '<select class="screen-control" data-role="field">' + fieldOptions(field) + '</select>' +
      '<select class="screen-control" data-role="op">' +
      '<option value="&gt;">&gt;</option><option value="&gt;=">&gt;=</option>' +
      '<option value="&lt;">&lt;</option><option value="&lt;=">&lt;=</option>' +
      '<option value="between">arasında</option></select>' +
      '<input class="screen-control" data-role="value" type="number" step="any" placeholder="değer" value="' +
      escapeHtml(value == null ? '' : value) + '"/>' +
      '<input class="screen-control hidden" data-role="value2" type="number" step="any" placeholder="üst sınır" value="' +
      escapeHtml(value2 == null ? '' : value2) + '"/>' +
      '<button type="button" class="screen-button-remove" data-role="remove">Sil</button>';
    container.appendChild(row);
    var opSelect = row.querySelector('[data-role="op"]');
    opSelect.value = op || '>';
    opSelect.addEventListener('change', function () {
      row.querySelector('[data-role="value2"]').classList.toggle('hidden', opSelect.value !== 'between');
    });
    row.querySelector('[data-role="remove"]').addEventListener('click', function () {
      container.removeChild(row);
    });
    return row;
  }

  function collectConditions() {
    var rows = document.querySelectorAll('#condition-rows .screen-condition');
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var field = rows[i].querySelector('[data-role="field"]').value;
      var op = rows[i].querySelector('[data-role="op"]').value;
      var raw = rows[i].querySelector('[data-role="value"]').value;
      if (raw === '') return { error: 'Her koşul için bir değer girin.' };
      var item = { field: field, op: op, value: Number(raw) };
      if (op === 'between') {
        var raw2 = rows[i].querySelector('[data-role="value2"]').value;
        if (raw2 === '') return { error: 'Aralık için üst sınır girin.' };
        item.value2 = Number(raw2);
      }
      out.push(item);
    }
    return { conditions: out };
  }

  function applyFilter() {
    var collected = collectConditions();
    if (collected.error) {
      setText('filter-status', collected.error);
      return;
    }
    mode = 'filter';
    highlightField = collected.conditions.length ? collected.conditions[0].field : null;
    setText('filter-status', 'Filtre uygulanıyor…');
    var body = {
      conditions: collected.conditions,
      sector: (document.getElementById('filter-sector') || {}).value || null,
      scan_id: (document.getElementById('filter-screen') || {}).value || null,
      sort: currentSort,
      order: 'desc',
      limit: 50
    };
    if (currentDate) body.as_of = currentDate;
    api('/api/screener/query', { method: 'POST', body: JSON.stringify(body) })
      .then(function (payload) {
        renderRows(payload);
        setText('screen-title', 'Filtre sonuçları');
        setText('screen-description', collected.conditions.length + ' koşul');
        setText('filter-status', '');
      })
      .catch(function (error) {
        setText('filter-status', error.message);
      });
  }

  // -------------------------------------------------------------------- search
  function wireSearch() {
    var input = document.getElementById('stock-search');
    var results = document.getElementById('search-results');
    if (!input || !results) return;
    var timer = null;
    input.addEventListener('input', function () {
      var query = input.value.trim();
      if (timer) clearTimeout(timer);
      if (query.length < 2) {
        results.classList.add('hidden');
        results.innerHTML = '';
        return;
      }
      timer = setTimeout(function () {
        api('/api/stocks/search?q=' + encodeURIComponent(query)).then(function (data) {
          var items = data.results || [];
          if (!items.length) {
            results.classList.add('hidden');
            return;
          }
          results.innerHTML = items.map(function (item) {
            return '<a href="/ui/stock/' + encodeURIComponent(item.code) + '">' +
              escapeHtml(item.code) + ' · ' + escapeHtml(item.name) + '</a>';
          }).join('');
          results.classList.remove('hidden');
        }).catch(function () { /* optional */ });
      }, 250);
    });
  }

  function boot() {
    wireSearch();
    document.getElementById('add-condition').addEventListener('click', function () {
      addCondition();
    });
    document.getElementById('apply-filter').addEventListener('click', applyFilter);
    document.getElementById('reset-filter').addEventListener('click', function () {
      document.getElementById('condition-rows').innerHTML = '';
      document.getElementById('filter-sector').value = '';
      document.getElementById('filter-screen').value = '';
      setText('filter-status', '');
    });

    Promise.all([api('/api/screens/fields'), api('/api/screens')]).then(function (results) {
      fields = results[0].fields || [];
      catalog = results[1];
      fillSort();
      fillDates();
      renderScreens();
      fillFilterSelects();
      if (catalog.screens && catalog.screens.length) {
        currentScan = catalog.screens[0].code;
        renderScreens();
        loadScreenRows();
      }
      setText('catalog-date', catalog.as_of ? 'Son seans: ' + catalog.as_of : 'Henüz tarama çalışmadı');
    }).catch(function (error) {
      setText('screen-meta', error.message);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
