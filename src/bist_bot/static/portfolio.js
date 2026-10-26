/* Faz 5 manual portfolio + benchmarks. CSP-safe. */
(function () {
  'use strict';
  var portfolios = [];
  var activeId = null;
  var chart = null;
  var seriesByName = {};

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

  function money(v) {
    if (v === null || v === undefined) return '—';
    return num(v, 0) + ' TL';
  }

  function pct(v) {
    if (v === null || v === undefined) return '—';
    var n = Number(v);
    return (n > 0 ? '+' : '') + n.toLocaleString('tr-TR', { maximumFractionDigits: 2 }) + '%';
  }

  function status(text) {
    var el = document.getElementById('portfolio-status');
    if (el) el.textContent = text || '';
  }

  function card(label, value, extra) {
    return '<div class="stock-card"><div class="stock-card-label">' + esc(label) +
      '</div><div class="stock-card-value">' + esc(value) + '</div>' +
      (extra ? '<div class="font-body-sm text-body-sm text-outline">' + esc(extra) + '</div>' : '') +
      '</div>';
  }

  function renderTabs() {
    var container = document.getElementById('portfolios');
    container.innerHTML = portfolios.map(function (item) {
      return '<button type="button" data-id="' + item.id + '" aria-pressed="' +
        (item.id === activeId ? 'true' : 'false') + '">' + esc(item.name) + '</button>';
    }).join('');
    var buttons = container.querySelectorAll('button');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        activeId = Number(event.currentTarget.getAttribute('data-id'));
        loadSummary();
      });
    }
  }

  function renderSummary(payload) {
    var nameEl = document.getElementById('active-portfolio-name');
    nameEl.textContent = (portfolios.filter(function (p) { return p.id === activeId; })[0] || {}).name || 'Portföy';
    var totals = payload.totals || {};
    var benchmark = payload.benchmark || {};
    var cards = [
      card('Portföy değeri', money(totals.value), pct(totals.return_pct) + ' (dış sermayeye göre)'),
      card('Dış sermaye', money(totals.net_invested)),
      card('Kalan maliyet', money(totals.invested_cost)),
      card('Gerçekleşmemiş K/Z', money(totals.unrealized)),
      card('Gerçekleşmiş K/Z', money(totals.realized)),
      card('Nakit', money(totals.cash))
    ];
    var transactions = payload.transactions || [];
    if (benchmark.available) {
      cards.push(card('XU100 eşdeğeri', money(benchmark.xu100_value), 'fark: ' + pct(benchmark.vs_xu100)));
      if (benchmark.money_market_source === 'unset') {
        cards.push(card('Para piyasası eşdeğeri', 'tanımlı değil', 'MONEY_MARKET_ANNUAL_RATE_PCT ayarlanınca hesaplanır'));
      } else {
        var mmLabel = benchmark.money_market_source === 'assumption'
          ? 'varsayım %' + num(benchmark.money_market_rate_pct, 1) + ' yıllık'
          : 'fon serisi';
        cards.push(card('Para piyasası eşdeğeri', money(benchmark.money_market_value),
          'fark: ' + pct(benchmark.vs_money_market) + ' · ' + mmLabel));
      }
    } else if (transactions.length) {
      cards.push(card('Kıyas', 'XU100 verisi yok', 'Gün sonu verisi birikince görünür'));
    }
    document.getElementById('summary-cards').innerHTML = cards.join('');

    var positionsBody = document.getElementById('positions-body');
    var positions = payload.positions || [];
    positionsBody.innerHTML = positions.length ? positions.map(function (row) {
      return '<tr>' +
        '<td class="sticky-col"><a href="/ui/stock/' + encodeURIComponent(row.code) + '">' + esc(row.code) + '</a></td>' +
        '<td class="text-right">' + num(row.quantity, 2) + '</td>' +
        '<td class="text-right">' + num(row.avg_cost, 2) + '</td>' +
        '<td class="text-right">' + num(row.price, 2) + '</td>' +
        '<td class="text-right">' + money(row.value) + '</td>' +
        '<td class="text-right">' + money(row.unrealized) + '<br><small>' + pct(row.unrealized_pct) + '</small></td>' +
        '<td class="text-right">' + money(row.realized_pnl !== undefined ? row.realized_pnl : 0) + '</td>' +
        '<td class="text-right">' + pct(row.weight_pct) + '</td>' +
        '</tr>';
    }).join('') : '<tr><td colspan="8" class="py-space-sm">Pozisyon yok.</td></tr>';

    var closedNote = document.getElementById('closed-positions-note');
    var closedPositions = payload.closed_positions || [];
    if (closedNote) {
      if (closedPositions.length) {
        closedNote.textContent = 'Kapanan pozisyonlar (gerçekleşen K/Z): ' + closedPositions.map(function (cp) {
          return cp.code + ' (' + money(cp.realized_pnl) + ')';
        }).join(' · ');
      } else {
        closedNote.textContent = '';
      }
    }

    var txBody = document.getElementById('transactions-body');
    txBody.innerHTML = transactions.length ? transactions.map(function (tx) {
      var codeClean = tx.ticker.replace('.IS', '');
      return '<tr>' +
        '<td>' + esc(tx.trade_date) + '</td>' +
        '<td class="sticky-col">' + esc(codeClean) + '</td>' +
        '<td>' + (tx.side === 'buy' ? 'Alış' : 'Satış') + '</td>' +
        '<td class="text-right">' + num(tx.quantity, 2) + '</td>' +
        '<td class="text-right">' + num(tx.price, 2) + '</td>' +
        '<td class="text-right">' + num(tx.commission_tl, 2) + '</td>' +
        '<td class="text-right">' +
        '<button type="button" class="personal-nav" data-edit-id="' + tx.id + '" data-ticker="' + esc(codeClean) + '" data-side="' + esc(tx.side) + '" data-date="' + esc(tx.trade_date) + '" data-qty="' + esc(tx.quantity) + '" data-price="' + esc(tx.price) + '" data-comm="' + esc(tx.commission_tl) + '">Düzenle</button> ' +
        '<button type="button" class="personal-remove" data-id="' + tx.id + '">Sil</button></td>' +
        '</tr>';
    }).join('') : '<tr><td colspan="7" class="py-space-sm">İşlem yok.</td></tr>';
    var editButtons = txBody.querySelectorAll('button[data-edit-id]');
    for (var j = 0; j < editButtons.length; j++) {
      editButtons[j].addEventListener('click', function (event) {
        var btn = event.currentTarget;
        var form = document.getElementById('trade-form');
        if (!form) return;
        form.transaction_id.value = btn.getAttribute('data-edit-id');
        form.ticker.value = btn.getAttribute('data-ticker');
        form.side.value = btn.getAttribute('data-side');
        form.trade_date.value = btn.getAttribute('data-date');
        form.quantity.value = btn.getAttribute('data-qty');
        form.price.value = btn.getAttribute('data-price');
        form.commission_tl.value = btn.getAttribute('data-comm');
        var titleEl = document.getElementById('trade-form-title');
        if (titleEl) titleEl.textContent = 'İşlem Düzenle (#' + form.transaction_id.value + ')';
        var cancelBtn = document.getElementById('cancel-edit-trade');
        if (cancelBtn) cancelBtn.classList.remove('hidden');
      });
    }
    var buttons = txBody.querySelectorAll('button.personal-remove');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        var id = event.currentTarget.getAttribute('data-id');
        api('/api/portfolios/' + activeId + '/transactions/' + id, { method: 'DELETE' })
          .then(function () {
            var ts = document.getElementById('trade-status');
            if (ts) ts.textContent = '';
            return loadSummary();
          })
          .catch(function (error) {
            var ts = document.getElementById('trade-status');
            if (ts) ts.textContent = error.message;
            status(error.message);
          });
      });
    }

    drawChart(payload.series || [], benchmark);
  }

  function ensureChart() {
    if (chart || !window.LightweightCharts) return;
    var el = document.getElementById('portfolio-chart');
    chart = window.LightweightCharts.createChart(el, {
      width: el.clientWidth || undefined,
      height: el.clientHeight || 360,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#9aa5a0' },
      localization: { locale: 'tr-TR' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)' }
    });
    seriesByName.portfolio = chart.addSeries(window.LightweightCharts.LineSeries, {
      color: '#4edea3', lineWidth: 2, priceLineVisible: false
    });
    seriesByName.xu100 = chart.addSeries(window.LightweightCharts.LineSeries, {
      color: '#8ab4f8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false
    });
    seriesByName.money_market = chart.addSeries(window.LightweightCharts.LineSeries, {
      color: '#f0b429', lineWidth: 1, priceLineVisible: false, lastValueVisible: false
    });
    var resize = function () {
      if (chart && el.clientWidth) chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
    };
    window.addEventListener('resize', resize);
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(resize).observe(el);
  }

  function drawChart(series, benchmark) {
    ensureChart();
    if (!chart) return;
    seriesByName.portfolio.setData(series.map(function (p) {
      return { time: p.time, value: p.portfolio };
    }));
    seriesByName.xu100.setData(series.filter(function (p) { return p.xu100 !== null; })
      .map(function (p) { return { time: p.time, value: p.xu100 }; }));
    seriesByName.money_market.setData(series.map(function (p) {
      return { time: p.time, value: p.money_market };
    }));
    seriesByName.money_market.applyOptions({ visible: benchmark.money_market_source !== 'unset' });
    chart.timeScale().fitContent();
    var note = document.getElementById('chart-note');
    if (note) {
      if (!series.length) {
        note.textContent = 'İşlem eklediğinizde portföy ve kıyas eğrileri burada görünür.';
      } else {
        note.textContent = benchmark.available
          ? 'Yeşil: portföy · Mavi: aynı nakit akışıyla XU100 · Sarı: para piyasası'
          : 'XU100 serisi yok; kıyas çizgileri gün sonu verisi birikince görünür.';
      }
    }
  }

  function loadSummary() {
    if (!activeId) {
      var nameEl = document.getElementById('active-portfolio-name');
      if (nameEl) nameEl.textContent = 'Portföy seçin';
      document.getElementById('summary-cards').innerHTML = '';
      var positionsBody = document.getElementById('positions-body');
      if (positionsBody) positionsBody.innerHTML = '<tr><td colspan="7" class="py-space-sm">Portföy seçin.</td></tr>';
      var txBody = document.getElementById('transactions-body');
      if (txBody) txBody.innerHTML = '<tr><td colspan="7" class="py-space-sm">Portföy seçin.</td></tr>';
      var ts = document.getElementById('trade-status');
      if (ts) ts.textContent = '';
      drawChart([], {});
      return;
    }
    renderTabs();
    return api('/api/portfolios/' + activeId).then(function (payload) {
      renderSummary(payload);
      status('');
    }).catch(function (error) { status(error.message); });
  }

  function load() {
    return api('/api/portfolios').then(function (data) {
      portfolios = data.portfolios || [];
      if (!portfolios.some(function (p) { return p.id === activeId; })) {
        activeId = portfolios.length ? portfolios[0].id : null;
      }
      renderTabs();
      return loadSummary();
    }).catch(function (error) { status(error.message); });
  }

  function wire() {
    document.getElementById('create-portfolio').addEventListener('click', function () {
      var input = document.getElementById('portfolio-name');
      var name = input.value.trim();
      if (!name) return;
      api('/api/portfolios', { method: 'POST', body: JSON.stringify({ name: name }) })
        .then(function (data) { input.value = ''; activeId = data.id; return load(); })
        .catch(function (error) { status(error.message); });
    });

    document.getElementById('delete-portfolio').addEventListener('click', function () {
      if (!activeId) return;
      api('/api/portfolios/' + activeId, { method: 'DELETE' })
        .then(function () { activeId = null; return load(); })
        .catch(function (error) { status(error.message); });
    });

    document.getElementById('trade-form').addEventListener('submit', function (event) {
      event.preventDefault();
      if (!activeId) {
        status('Önce bir portföy oluşturun.');
        return;
      }
      var form = event.target;
      var txId = form.transaction_id ? form.transaction_id.value : '';
      var payload = {
        ticker: form.ticker.value,
        side: form.side.value,
        trade_date: form.trade_date.value,
        quantity: form.quantity.value,
        price: form.price.value,
        commission_tl: form.commission_tl.value || 0
      };
      var path = txId
        ? '/api/portfolios/' + activeId + '/transactions/' + encodeURIComponent(txId)
        : '/api/portfolios/' + activeId + '/transactions';
      var method = txId ? 'PUT' : 'POST';
      api(path, {
        method: method, body: JSON.stringify(payload)
      }).then(function () {
        form.reset();
        if (form.transaction_id) form.transaction_id.value = '';
        var titleEl = document.getElementById('trade-form-title');
        if (titleEl) titleEl.textContent = 'İşlem Ekle';
        var cancelBtn = document.getElementById('cancel-edit-trade');
        if (cancelBtn) cancelBtn.classList.add('hidden');
        document.getElementById('trade-status').textContent = txId ? 'İşlem güncellendi.' : 'İşlem kaydedildi.';
        return loadSummary();
      }).catch(function (error) {
        document.getElementById('trade-status').textContent = error.message;
      });
    });

    var cancelBtn = document.getElementById('cancel-edit-trade');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        var form = document.getElementById('trade-form');
        if (form) {
          form.reset();
          if (form.transaction_id) form.transaction_id.value = '';
        }
        var titleEl = document.getElementById('trade-form-title');
        if (titleEl) titleEl.textContent = 'İşlem Ekle';
        cancelBtn.classList.add('hidden');
      });
    }

    function runCsvImport(dryRun) {
      if (!activeId) {
        status('Önce bir portföy oluşturun.');
        return;
      }
      var csvInput = document.getElementById('csv-import-input');
      var csvStatus = document.getElementById('csv-import-status');
      var csvText = csvInput ? csvInput.value : '';
      if (!csvText.trim()) {
        if (csvStatus) csvStatus.textContent = 'CSV metni girin.';
        return;
      }
      api('/api/portfolios/' + activeId + '/transactions/import', {
        method: 'POST',
        body: JSON.stringify({ csv: csvText, dry_run: dryRun })
      }).then(function (res) {
        if (dryRun) {
          if (res.valid) {
            if (csvStatus) csvStatus.textContent = 'Geçerli: ' + (res.valid_count || 0) + ' işlem hazır.';
          } else {
            var firstErr = (res.errors && res.errors[0] && res.errors[0].message) || 'Hata var';
            if (csvStatus) csvStatus.textContent = 'Hata (' + (res.errors || []).length + '): ' + firstErr;
          }
        } else {
          if (csvInput) csvInput.value = '';
          if (csvStatus) csvStatus.textContent = (res.imported || 0) + ' işlem içe aktarıldı.';
          return loadSummary();
        }
      }).catch(function (error) {
        if (csvStatus) csvStatus.textContent = error.message;
      });
    }

    var previewCsvBtn = document.getElementById('csv-preview-btn');
    if (previewCsvBtn) previewCsvBtn.addEventListener('click', function () { runCsvImport(true); });
    var importCsvBtn = document.getElementById('csv-import-btn');
    if (importCsvBtn) importCsvBtn.addEventListener('click', function () { runCsvImport(false); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { wire(); load(); });
  } else {
    wire();
    load();
  }
})();
