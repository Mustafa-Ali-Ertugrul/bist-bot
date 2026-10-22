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
      card('Portföy değeri', money(totals.value)),
      card('Kalan maliyet', money(totals.invested_cost)),
      card('Gerçekleşmemiş K/Z', money(totals.unrealized), pct(totals.return_pct) + ' (alışlara göre)'),
      card('Gerçekleşmiş K/Z', money(totals.realized)),
      card('Nakit', money(totals.cash))
    ];
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
    } else {
      cards.push(card('Kıyas', 'XU100 verisi yok', 'Gün sonu verisi birikince görünür'));
    }
    document.getElementById('summary-cards').innerHTML = cards.join('');

    var positionsBody = document.getElementById('positions-body');
    var positions = payload.positions || [];
    positionsBody.innerHTML = positions.length ? positions.map(function (row) {
      return '<tr>' +
        '<td><a href="/ui/stock/' + encodeURIComponent(row.code) + '">' + esc(row.code) + '</a></td>' +
        '<td class="text-right">' + num(row.quantity, 2) + '</td>' +
        '<td class="text-right">' + num(row.avg_cost, 2) + '</td>' +
        '<td class="text-right">' + num(row.price, 2) + '</td>' +
        '<td class="text-right">' + money(row.value) + '</td>' +
        '<td class="text-right">' + money(row.unrealized) + '<br><small>' + pct(row.unrealized_pct) + '</small></td>' +
        '<td class="text-right">' + pct(row.weight_pct) + '</td>' +
        '</tr>';
    }).join('') : '<tr><td colspan="7" class="py-space-sm">Pozisyon yok.</td></tr>';

    var txBody = document.getElementById('transactions-body');
    var transactions = payload.transactions || [];
    txBody.innerHTML = transactions.length ? transactions.map(function (tx) {
      return '<tr>' +
        '<td>' + esc(tx.trade_date) + '</td>' +
        '<td>' + esc(tx.ticker.replace('.IS', '')) + '</td>' +
        '<td>' + (tx.side === 'buy' ? 'Alış' : 'Satış') + '</td>' +
        '<td class="text-right">' + num(tx.quantity, 2) + '</td>' +
        '<td class="text-right">' + num(tx.price, 2) + '</td>' +
        '<td class="text-right">' + num(tx.commission_tl, 2) + '</td>' +
        '<td><button type="button" class="personal-remove" data-id="' + tx.id + '">Sil</button></td>' +
        '</tr>';
    }).join('') : '<tr><td colspan="7" class="py-space-sm">İşlem yok.</td></tr>';
    var buttons = txBody.querySelectorAll('button.personal-remove');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        var id = event.currentTarget.getAttribute('data-id');
        api('/api/portfolios/' + activeId + '/transactions/' + id, { method: 'DELETE' })
          .then(loadSummary).catch(function (error) { status(error.message); });
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
      note.textContent = benchmark.available
        ? 'Yeşil: portföy · Mavi: aynı nakit akışıyla XU100 · Sarı: para piyasası'
        : 'XU100 serisi yok; kıyas çizgileri gün sonu verisi birikince görünür.';
    }
  }

  function loadSummary() {
    if (!activeId) {
      document.getElementById('summary-cards').innerHTML = '';
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
      var payload = {
        ticker: form.ticker.value,
        side: form.side.value,
        trade_date: form.trade_date.value,
        quantity: form.quantity.value,
        price: form.price.value,
        commission_tl: form.commission_tl.value || 0
      };
      api('/api/portfolios/' + activeId + '/transactions', {
        method: 'POST', body: JSON.stringify(payload)
      }).then(function () {
        form.reset();
        document.getElementById('trade-status').textContent = 'İşlem kaydedildi.';
        return loadSummary();
      }).catch(function (error) {
        document.getElementById('trade-status').textContent = error.message;
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { wire(); load(); });
  } else {
    wire();
    load();
  }
})();
