/* Faz 4 screener. CSP-safe: no inline handlers. */
(function () {
  'use strict';

  var fields = [];
  var fieldByCode = {};
  var catalog = { screens: [], dates: [], as_of: null };
  var savedScreens = [];
  var watchlists = [];
  var currentScan = null;
  var currentDate = null;
  var currentSort = 'market_cap_tl';
  var currentOrder = 'desc';
  var currentPageSize = 50;
  var currentOffset = 0;
  var lastVisibleTotal = 0;
  var currentFilterTitle = null;
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
      var pressed = (mode === 'screen' && currentScan === screen.code) ? 'true' : 'false';
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
        currentOffset = 0;
        var savedSelect = document.getElementById('saved-filter-select');
        if (savedSelect) savedSelect.value = '';
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
      currentOffset = 0;
      if (mode === 'screen') loadScreenRows();
      else if (mode === 'filter') applyFilter(currentFilterTitle, true);
    });
  }

  function updateOrderButton() {
    var btn = document.getElementById('screen-order');
    if (!btn) return;
    btn.textContent = currentOrder === 'asc' ? '↑ Artan' : '↓ Azalan';
  }

  function updateSortHeaders() {
    var headers = document.querySelectorAll('th[data-sort-field]');
    for (var i = 0; i < headers.length; i++) {
      var field = headers[i].getAttribute('data-sort-field');
      if (field && field === currentSort) {
        headers[i].setAttribute('aria-sort', currentOrder === 'asc' ? 'ascending' : 'descending');
      } else {
        headers[i].setAttribute('aria-sort', 'none');
      }
    }
  }

  function fillSort() {
    var select = document.getElementById('screen-sort');
    if (!select) return;
    fieldByCode = {};
    fields.forEach(function (field) {
      fieldByCode[field.code] = field;
    });
    select.innerHTML = fields.map(function (field) {
      return '<option value="' + escapeHtml(field.code) + '">' + escapeHtml(field.label) + '</option>';
    }).join('');
    select.value = currentSort;
    select.addEventListener('change', function () {
      currentSort = select.value || 'market_cap_tl';
      currentOffset = 0;
      updateSortHeaders();
      if (mode === 'screen') loadScreenRows();
      else if (mode === 'filter') applyFilter(currentFilterTitle, true);
    });
  }

  function fillFilterSelects(sectors, screens) {
    var sector = document.getElementById('filter-sector');
    var screen = document.getElementById('filter-screen');
    if (sector && sector.options.length <= 1) {
      (sectors || []).forEach(function (name) {
        var option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        sector.appendChild(option);
      });
    }
    if (screen && screen.options.length <= 1) {
      (screens || []).forEach(function (item) {
        var option = document.createElement('option');
        option.value = item.code;
        option.textContent = item.title;
        screen.appendChild(option);
      });
    }
  }

  function activeMetricFieldCode() {
    if (highlightField) return highlightField;
    if (currentSort && currentSort !== 'close' && currentSort !== 'change_pct' && currentSort !== 'market_cap_tl') {
      return currentSort;
    }
    return null;
  }

  function formatMetricValue(fieldCode, value) {
    if (value === null || value === undefined) return '—';
    var field = fieldCode ? fieldByCode[fieldCode] : null;
    if (!field) return num(value, 2);
    if (field.unit === 'pct') return pct(value);
    if (field.unit === 'tl') return money(value);
    if (field.unit === 'x') return num(value, 2) + 'x';
    return num(value, 2);
  }

  function updatePagination(payload) {
    var total = Number(payload.visible_total != null ? payload.visible_total : (payload.total || 0));
    lastVisibleTotal = total;
    var returned = (payload.rows || []).length;
    var prevBtn = document.getElementById('screen-prev-page');
    var nextBtn = document.getElementById('screen-next-page');
    if (prevBtn) prevBtn.disabled = currentOffset <= 0;
    if (nextBtn) nextBtn.disabled = (currentOffset + currentPageSize) >= total;
    if (total === 0 || returned === 0) {
      setText('screen-page-info', '0 / 0');
    } else {
      var startIdx = currentOffset + 1;
      var endIdx = currentOffset + returned;
      setText('screen-page-info', startIdx + '–' + endIdx + ' / ' + total);
    }
  }

  // --------------------------------------------------------------- table render
  function renderRows(payload) {
    var body = document.getElementById('screen-body');
    if (!body) return;
    var selectAll = document.getElementById('select-all-rows');
    if (selectAll) selectAll.checked = false;
    var rows = payload.rows || [];
    var dynamicCode = activeMetricFieldCode();
    var metricHeader = document.getElementById('screen-metric-header');
    if (metricHeader) {
      if (mode === 'screen' && rows.length && rows[0].scan_value !== undefined && !dynamicCode) {
        metricHeader.textContent = 'Tarama Değeri';
        metricHeader.setAttribute('data-sort-field', '');
      } else if (dynamicCode && fieldByCode[dynamicCode]) {
        metricHeader.textContent = fieldByCode[dynamicCode].label;
        metricHeader.setAttribute('data-sort-field', dynamicCode);
      } else {
        metricHeader.textContent = 'Değer';
        metricHeader.setAttribute('data-sort-field', '');
      }
    }
    updateSortHeaders();
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="8" class="py-space-sm">Sonuç yok.</td></tr>';
    } else {
      body.innerHTML = rows.map(function (row) {
        var m = row.metrics || {};
        var formattedVal = '—';
        if (dynamicCode && m[dynamicCode] !== undefined) {
          formattedVal = formatMetricValue(dynamicCode, m[dynamicCode]);
        } else if (row.scan_value !== undefined) {
          formattedVal = num(row.scan_value, 2);
        }
        return '<tr>' +
          '<td><input type="checkbox" data-select-code="' + escapeHtml(row.code) + '" aria-label="' + escapeHtml(row.code) + ' seç"/></td>' +
          '<td class="sticky-col"><a href="/ui/stock/' + encodeURIComponent(row.code) + '">' + escapeHtml(row.code) + '</a></td>' +
          '<td>' + escapeHtml(row.name || '') + '</td>' +
          '<td>' + escapeHtml(row.sector || '—') + '</td>' +
          '<td class="text-right">' + num(m.close, 2) + '</td>' +
          '<td class="text-right">' + pct(m.change_pct) + '</td>' +
          '<td class="text-right">' + formattedVal + '</td>' +
          '<td class="text-right">' + money(m.market_cap_tl) + '</td>' +
          '</tr>';
      }).join('');
    }
    var meta = (payload.total || 0) + ' sonuç · ' + (payload.as_of || '—');
    if (payload.plan_truncated || payload.truncated) {
      meta += ' · ücretsiz görünümde ilk ' + (payload.allowed_limit || payload.limit || payload.returned) + ' sonuç gösteriliyor';
    }
    setText('screen-meta', meta);
    updatePagination(payload);
    updateCompareLink();
  }

  function loadScreenRows() {
    if (!currentScan) return;
    highlightField = null;
    var query = '?limit=' + encodeURIComponent(currentPageSize) +
      '&offset=' + encodeURIComponent(currentOffset) +
      '&sort=' + encodeURIComponent(currentSort) +
      '&order=' + encodeURIComponent(currentOrder);
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
    row.querySelector('[data-role="value2"]').classList.toggle('hidden', opSelect.value !== 'between');
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

  function applyFilter(title, keepOffset) {
    var collected = collectConditions();
    if (collected.error) {
      setText('filter-status', collected.error);
      return;
    }
    if (!keepOffset) currentOffset = 0;
    mode = 'filter';
    currentFilterTitle = title || null;
    renderScreens();
    highlightField = collected.conditions.length ? collected.conditions[0].field : null;
    setText('filter-status', 'Filtre uygulanıyor…');
    var body = {
      conditions: collected.conditions,
      sector: (document.getElementById('filter-sector') || {}).value || null,
      scan_id: (document.getElementById('filter-screen') || {}).value || null,
      sort: currentSort,
      order: currentOrder,
      limit: currentPageSize,
      offset: currentOffset
    };
    if (currentDate) body.as_of = currentDate;
    api('/api/screener/query', { method: 'POST', body: JSON.stringify(body) })
      .then(function (payload) {
        renderRows(payload);
        setText('screen-title', currentFilterTitle || 'Filtre sonuçları');
        setText('screen-description', collected.conditions.length + ' koşul');
        setText('filter-status', '');
      })
      .catch(function (error) {
        setText('filter-status', error.message);
      });
  }

  function exportCsv() {
    var path;
    var opts = { headers: authHeaders() };
    var filename = 'bist-tarama.csv';
    if (mode === 'filter') {
      var collected = collectConditions();
      if (collected.error) {
        setText('filter-status', collected.error);
        return;
      }
      var body = {
        conditions: collected.conditions,
        sector: (document.getElementById('filter-sector') || {}).value || null,
        scan_id: (document.getElementById('filter-screen') || {}).value || null,
        sort: currentSort,
        order: currentOrder
      };
      if (currentDate) body.as_of = currentDate;
      path = '/api/screener/query.csv';
      opts.method = 'POST';
      opts.body = JSON.stringify(body);
      filename = 'bist-filtre-' + (currentDate || 'guncel') + '.csv';
    } else {
      if (!currentScan) return;
      var query = '?sort=' + encodeURIComponent(currentSort) + '&order=' + encodeURIComponent(currentOrder);
      if (currentDate) query += '&as_of=' + encodeURIComponent(currentDate);
      path = '/api/screens/' + encodeURIComponent(currentScan) + '.csv' + query;
      filename = 'bist-tarama-' + currentScan + '-' + (currentDate || 'guncel') + '.csv';
    }
    fetch(path, opts).then(function (res) {
      if (!res.ok) throw new Error('CSV indirilemedi');
      return res.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }).catch(function (error) {
      setText('screen-meta', error.message);
    });
  }

  function loadWatchlistsForBulk() {
    return api('/api/watchlists').then(function (data) {
      watchlists = data.watchlists || [];
      var select = document.getElementById('bulk-watchlist-select');
      if (!select) return;
      select.innerHTML = '<option value="">Liste seçin</option>' +
        watchlists.map(function (w) {
          return '<option value="' + escapeHtml(w.id) + '">' + escapeHtml(w.name) + '</option>';
        }).join('');
      if (watchlists.length === 1) select.value = String(watchlists[0].id);
    }).catch(function () { /* optional */ });
  }

  function updateCompareLink() {
    var link = document.getElementById('compare-selected');
    if (!link) return;
    var checked = document.querySelectorAll('#screen-body input[data-select-code]:checked');
    var codes = [];
    for (var i = 0; i < checked.length && codes.length < 4; i++) {
      codes.push(checked[i].getAttribute('data-select-code'));
    }
    var href = '/ui/compare';
    if (codes.length) href += '?codes=' + encodeURIComponent(codes.join(','));
    link.setAttribute('href', href);
    link.textContent = codes.length ? 'Karşılaştır (' + codes.length + ')' : 'Karşılaştır';
  }

  function addSelectedToWatchlist() {
    var select = document.getElementById('bulk-watchlist-select');
    var wlId = select ? select.value : '';
    var checked = document.querySelectorAll('#screen-body input[data-select-code]:checked');
    var codes = [];
    for (var i = 0; i < checked.length; i++) {
      codes.push(checked[i].getAttribute('data-select-code'));
    }
    if (!codes.length) {
      setText('bulk-watchlist-status', 'En az bir hisse seçin.');
      return;
    }
    var ensureList = wlId ? Promise.resolve(wlId) : api('/api/watchlists', {
      method: 'POST',
      body: JSON.stringify({ name: 'Ana Liste' })
    }).then(function (created) {
      return loadWatchlistsForBulk().then(function () {
        return String(created.id);
      });
    });
    ensureList.then(function (targetId) {
      return api('/api/watchlists/' + encodeURIComponent(targetId) + '/items/bulk', {
        method: 'POST',
        body: JSON.stringify({ tickers: codes })
      });
    }).then(function (res) {
      var msg = (res.added || 0) + ' eklendi';
      if (res.skipped) msg += ', ' + res.skipped + ' zaten listede';
      if (res.limit_reached) msg += ' (liste kotası doldu)';
      setText('bulk-watchlist-status', msg);
    }).catch(function (error) {
      setText('bulk-watchlist-status', error.message);
    });
  }

  // ------------------------------------------------------------- saved filters
  function savedIdFromUrl() {
    var match = /[?&]saved=([^&]+)/.exec(window.location.search || '');
    return match ? decodeURIComponent(match[1]) : null;
  }

  function scanIdFromUrl() {
    var match = /[?&]screen=([^&]+)/.exec(window.location.search || '');
    return match ? decodeURIComponent(match[1]) : null;
  }

  function renderSavedOptions() {
    var select = document.getElementById('saved-filter-select');
    if (!select) return;
    var previous = select.value;
    select.innerHTML = '<option value="">Kayıtlı filtre seçin</option>' +
      savedScreens.map(function (item) {
        return '<option value="' + escapeHtml(item.id) + '">' + escapeHtml(item.name) + '</option>';
      }).join('');
    if (previous) select.value = previous;
  }

  function loadSavedScreens() {
    return api('/api/saved-screens').then(function (data) {
      savedScreens = data.screens || [];
      renderSavedOptions();
    }).catch(function () { /* optional */ });
  }

  function applySavedFilter(screenId) {
    var saved = savedScreens.filter(function (item) {
      return String(item.id) === String(screenId);
    })[0];
    if (!saved) {
      setText('filter-status', 'Kayıtlı filtre bulunamadı.');
      return;
    }
    var payload = saved.payload || {};
    var container = document.getElementById('condition-rows');
    if (container) container.innerHTML = '';
    (payload.conditions || []).forEach(function (condition) {
      addCondition(condition.field, condition.op, condition.value, condition.value2);
    });
    var sector = document.getElementById('filter-sector');
    if (sector) sector.value = payload.sector || '';
    var screen = document.getElementById('filter-screen');
    if (screen) screen.value = payload.scan_id || '';
    var select = document.getElementById('saved-filter-select');
    if (select) select.value = String(saved.id);
    applyFilter(saved.name);
  }

  function saveFilter() {
    var nameInput = document.getElementById('save-filter-name');
    var button = document.getElementById('save-filter');
    var name = ((nameInput || {}).value || '').trim();
    if (!name) {
      setText('filter-status', 'Filtre adı boş olamaz.');
      return;
    }
    var collected = collectConditions();
    if (collected.error) {
      setText('filter-status', collected.error);
      return;
    }
    if (button.disabled) return;
    button.disabled = true;
    setText('filter-status', 'Kaydediliyor…');
    api('/api/saved-screens', {
      method: 'POST',
      body: JSON.stringify({
        name: name,
        payload: {
          conditions: collected.conditions,
          sector: (document.getElementById('filter-sector') || {}).value || null,
          scan_id: (document.getElementById('filter-screen') || {}).value || null
        }
      })
    })
      .then(function (created) {
        setText('filter-status', 'Filtre kaydedildi.');
        nameInput.value = '';
        return loadSavedScreens().then(function () {
          var select = document.getElementById('saved-filter-select');
          if (select && created && created.id) select.value = String(created.id);
        });
      })
      .catch(function (error) {
        setText('filter-status', error.message);
      })
      .then(function () {
        button.disabled = false;
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

  function reloadActiveView() {
    if (mode === 'screen') loadScreenRows();
    else if (mode === 'filter') applyFilter(currentFilterTitle, true);
  }

  function boot() {
    wireSearch();
    document.getElementById('add-condition').addEventListener('click', function () {
      addCondition();
    });
    document.getElementById('apply-filter').addEventListener('click', function () {
      applyFilter();
    });
    document.getElementById('reset-filter').addEventListener('click', function () {
      document.getElementById('condition-rows').innerHTML = '';
      document.getElementById('filter-sector').value = '';
      document.getElementById('filter-screen').value = '';
      var savedSelect = document.getElementById('saved-filter-select');
      if (savedSelect) savedSelect.value = '';
      setText('filter-status', '');
    });
    var orderBtn = document.getElementById('screen-order');
    if (orderBtn) {
      orderBtn.addEventListener('click', function () {
        currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
        currentOffset = 0;
        updateOrderButton();
        updateSortHeaders();
        reloadActiveView();
      });
    }
    var sortHeaders = document.querySelectorAll('th[data-sort-field]');
    for (var i = 0; i < sortHeaders.length; i++) {
      sortHeaders[i].addEventListener('click', function (event) {
        var field = event.currentTarget.getAttribute('data-sort-field');
        if (!field) return;
        if (currentSort === field) {
          currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
        } else {
          currentSort = field;
          currentOrder = 'desc';
          var sortSelect = document.getElementById('screen-sort');
          if (sortSelect) sortSelect.value = currentSort;
        }
        currentOffset = 0;
        updateOrderButton();
        updateSortHeaders();
        reloadActiveView();
      });
    }
    var csvBtn = document.getElementById('export-csv');
    if (csvBtn) csvBtn.addEventListener('click', exportCsv);
    var pageSizeSelect = document.getElementById('screen-page-size');
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener('change', function () {
        currentPageSize = Number(pageSizeSelect.value) || 50;
        currentOffset = 0;
        reloadActiveView();
      });
    }
    var prevBtn = document.getElementById('screen-prev-page');
    if (prevBtn) {
      prevBtn.addEventListener('click', function () {
        if (currentOffset <= 0) return;
        currentOffset = Math.max(0, currentOffset - currentPageSize);
        reloadActiveView();
      });
    }
    var nextBtn = document.getElementById('screen-next-page');
    if (nextBtn) {
      nextBtn.addEventListener('click', function () {
        if (currentOffset + currentPageSize >= lastVisibleTotal) return;
        currentOffset += currentPageSize;
        reloadActiveView();
      });
    }
    var selectAll = document.getElementById('select-all-rows');
    if (selectAll) {
      selectAll.addEventListener('change', function () {
        var boxes = document.querySelectorAll('#screen-body input[data-select-code]');
        for (var j = 0; j < boxes.length; j++) {
          boxes[j].checked = selectAll.checked;
        }
        updateCompareLink();
      });
    }
    var screenBody = document.getElementById('screen-body');
    if (screenBody) {
      screenBody.addEventListener('change', function (event) {
        if (event.target && event.target.getAttribute && event.target.getAttribute('data-select-code')) {
          updateCompareLink();
        }
      });
    }
    var bulkAddBtn = document.getElementById('bulk-watchlist-add');
    if (bulkAddBtn) bulkAddBtn.addEventListener('click', addSelectedToWatchlist);
    var saveButton = document.getElementById('save-filter');
    if (saveButton) saveButton.addEventListener('click', saveFilter);
    var savedSelect = document.getElementById('saved-filter-select');
    if (savedSelect) {
      savedSelect.addEventListener('change', function () {
        if (savedSelect.value) applySavedFilter(savedSelect.value);
      });
    }

    loadWatchlistsForBulk();
    updateCompareLink();
    Promise.all([api('/api/screens/fields'), api('/api/screens'), loadSavedScreens()]).then(function (results) {
      fields = results[0].fields || [];
      catalog = results[1];
      fillSort();
      fillDates();
      renderScreens();
      fillFilterSelects(results[0].sectors || [], catalog.screens || []);
      setText('catalog-date', catalog.as_of ? 'Son seans: ' + catalog.as_of : 'Henüz tarama çalışmadı');
      var savedId = savedIdFromUrl();
      if (savedId) {
        applySavedFilter(savedId);
        return;
      }
      if (catalog.screens && catalog.screens.length) {
        var requestedScan = scanIdFromUrl();
        var known = requestedScan && catalog.screens.filter(function (item) {
          return item.code === requestedScan;
        }).length;
        currentScan = known ? requestedScan : catalog.screens[0].code;
        renderScreens();
        loadScreenRows();
      }
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
