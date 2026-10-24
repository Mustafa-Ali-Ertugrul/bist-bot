/* Faz 3 stock page. CSP-safe: no inline handlers, no eval. */
(function () {
  'use strict';

  var code = (document.body && document.body.getAttribute('data-stock-code')) || '';
  var SCAN_LABELS = {
    rsi_dip: 'RSI Dip',
    sma_5_22: '5-22 Kesişimi',
    sma_50_200: '50-200 Kesişimi',
    hacim_sok: 'Hacim Şoku',
    zirve_52h: '52 Hafta Zirvesi',
    bb_sikisma: 'Bollinger Sıkışması',
    ucuz_karli: 'Ucuz ve Kârlı',
    satis_buyume: 'Satış Büyümesi'
  };

  function token() {
    return localStorage.getItem('bistbot_token');
  }

  function authHeaders() {
    var t = token();
    return t ? { 'Authorization': 'Bearer ' + t } : {};
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

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function num(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
    return Number(value).toLocaleString('tr-TR', {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0
    });
  }

  function pct(value) {
    if (value === null || value === undefined) return '—';
    var n = Number(value);
    return (n > 0 ? '+' : '') + n.toLocaleString('tr-TR', { maximumFractionDigits: 2 }) + '%';
  }

  function money(value) {
    if (value === null || value === undefined) return '—';
    var n = Number(value);
    if (Math.abs(n) >= 1e9) return (n / 1e9).toLocaleString('tr-TR', { maximumFractionDigits: 2 }) + ' milyar TL';
    if (Math.abs(n) >= 1e6) return (n / 1e6).toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + ' mn TL';
    return n.toLocaleString('tr-TR', { maximumFractionDigits: 0 }) + ' TL';
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function tone(value) {
    if (value === null || value === undefined) return '';
    return Number(value) >= 0 ? 'stock-positive' : 'stock-negative';
  }

  function kvRow(label, value) {
    return '<div class="stock-kv-row"><span>' + escapeHtml(label) + '</span><span>' +
      escapeHtml(value) + '</span></div>';
  }

  function metricCard(label, value, className) {
    return '<div class="stock-card"><div class="stock-card-label">' + escapeHtml(label) +
      '</div><div class="stock-card-value ' + (className || '') + '">' + escapeHtml(value) + '</div></div>';
  }

  // ------------------------------------------------------------------ profile
  function renderProfile(profile) {
    setText('stock-name', profile.name || '');
    setText('stock-sector', profile.sector || 'Sektör bilgisi yok');
    setText('stock-close', profile.last_close === null ? '—' : num(profile.last_close, 2) + ' TL');
    var change = document.getElementById('stock-change');
    if (change) {
      change.textContent = pct(profile.change_pct);
      change.className = 'font-metric-value text-metric-value ' + tone(profile.change_pct);
    }
    setText('stock-mcap', money(profile.market_cap_tl));
    setText('stock-asof', profile.as_of
      ? 'Gün sonu verisi · ' + profile.as_of + ' · düzeltilmiş kapanış'
      : 'Bu hisse için henüz gün sonu verisi yok');

    var buckets = [
      ['1 Hafta', profile.returns['1w']],
      ['1 Ay', profile.returns['1m']],
      ['3 Ay', profile.returns['3m']],
      ['Yıl Başından', profile.returns['ytd']],
      ['1 Yıl', profile.returns['1y']],
      ['3 Yıl', profile.returns['3y']]
    ];
    var grid = document.getElementById('returns-grid');
    if (grid) {
      grid.innerHTML = buckets.map(function (item) {
        return metricCard(item[0], pct(item[1]), tone(item[1]));
      }).join('');
    }

    var tech = profile.technical || {};
    var techGrid = document.getElementById('technical-grid');
    if (techGrid) {
      techGrid.innerHTML = [
        kvRow('RSI(14)', num(tech.rsi14, 1)),
        kvRow('SMA 50', tech.sma50 ? num(tech.sma50, 2) : 'yetersiz geçmiş'),
        kvRow('SMA 200', tech.sma200 ? num(tech.sma200, 2) : 'yetersiz geçmiş'),
        kvRow('SMA50 farkı', pct(tech.vs_sma50_pct)),
        kvRow('52 hafta yüksek', tech.high_52w ? num(tech.high_52w, 2) : '—'),
        kvRow('52 hafta düşük', tech.low_52w ? num(tech.low_52w, 2) : '—'),
        kvRow('Zirveden', pct(tech.from_high_pct)),
        kvRow('20g ort. hacim', tech.avg_volume_20 ? money(tech.avg_volume_20) : '—')
      ].join('');
    }

    var fund = profile.fundamentals || {};
    var ratios = fund.ratios || {};
    var ratioGrid = document.getElementById('ratios-grid');
    if (ratioGrid) {
      ratioGrid.innerHTML = [
        kvRow('F/K (son 12 ay)', ratios.pe_ttm ? num(ratios.pe_ttm, 2) : '—'),
        kvRow('PD/DD', ratios.pb ? num(ratios.pb, 2) : '—'),
        kvRow('Net kâr marjı', ratios.net_margin_pct === null ? '—' : pct(ratios.net_margin_pct)),
        kvRow('Özkaynak kârlılığı', ratios.roe_pct === null ? '—' : pct(ratios.roe_pct)),
        kvRow('Satış büyümesi (yıllık)', pct(ratios.sales_growth_yoy_pct)),
        kvRow('Son 12 ay satış', fund.ttm_sales ? money(fund.ttm_sales) : '—'),
        kvRow('Son 12 ay net kâr', fund.ttm_net_profit ? money(fund.ttm_net_profit) : '—'),
        kvRow('Son çeyrek', fund.latest_period || '—')
      ].join('');
    }
  }

  // -------------------------------------------------------------- fundamentals
  function renderFundamentals(payload) {
    var body = document.getElementById('quarters-body');
    if (!body) return;
    var rows = (payload && payload.quarters) || [];
    if (!rows.length) {
      body.innerHTML = '<tr><td class="py-space-xs" colspan="4">Bilanço verisi henüz yüklenmedi.</td></tr>';
      return;
    }
    body.innerHTML = rows.slice().reverse().map(function (row) {
      return '<tr class="border-b border-surface-container-high/30">' +
        '<td class="py-space-3xs">' + escapeHtml(row.period) + '</td>' +
        '<td class="py-space-3xs text-right">' + (row.sales === null ? '—' : num(row.sales, 0)) + '</td>' +
        '<td class="py-space-3xs text-right">' + (row.net_profit === null ? '—' : num(row.net_profit, 0)) + '</td>' +
        '<td class="py-space-3xs text-right">' + (row.equity === null ? '—' : num(row.equity, 0)) + '</td>' +
        '</tr>';
    }).join('');
  }

  // ------------------------------------------------------------------- screens
  function renderScans(hits) {
    var list = document.getElementById('scans-list');
    if (!list) return;
    if (!hits || !hits.length) {
      list.innerHTML = '<div class="stock-kv-row"><span>Son 30 günde eşleşme yok</span><span></span></div>';
      return;
    }
    list.innerHTML = hits.slice(0, 20).map(function (hit) {
      var label = SCAN_LABELS[hit.scan_id] || hit.scan_id;
      return kvRow(hit.as_of + ' · ' + label, hit.detail || '');
    }).join('');
  }

  // --------------------------------------------------------------------- chart
  var chart = null;
  var areaSeries = null;
  var volumeSeries = null;
  var sma50Series = null;
  var sma200Series = null;
  var chartBars = [];

  function sma(values, window) {
    var out = [];
    var sum = 0;
    for (var i = 0; i < values.length; i++) {
      sum += values[i];
      if (i >= window) sum -= values[i - window];
      if (i >= window - 1) out.push({ time: chartBars[i].time, value: sum / window });
    }
    return out;
  }

  function ensureChart() {
    if (chart || !window.LightweightCharts) return;
    var el = document.getElementById('stock-chart');
    if (!el) return;
    chart = window.LightweightCharts.createChart(el, {
      width: el.clientWidth || undefined,
      height: el.clientHeight || 420,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#9aa5a0' },
      localization: { locale: 'tr-TR' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.05)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)' },
      crosshair: { mode: 0 }
    });
    areaSeries = chart.addSeries(window.LightweightCharts.AreaSeries, {
      lineColor: '#4edea3',
      topColor: 'rgba(78,222,163,0.28)',
      bottomColor: 'rgba(78,222,163,0.02)',
      lineWidth: 2,
      priceLineVisible: false
    });
    volumeSeries = chart.addSeries(window.LightweightCharts.HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
      lastValueVisible: false,
      priceLineVisible: false
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    sma50Series = chart.addSeries(window.LightweightCharts.LineSeries, {
      color: '#f0b429', lineWidth: 1, priceLineVisible: false, lastValueVisible: false
    });
    sma200Series = chart.addSeries(window.LightweightCharts.LineSeries, {
      color: '#8ab4f8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false
    });

    var toggle50 = document.getElementById('toggle-sma50');
    var toggle200 = document.getElementById('toggle-sma200');
    if (toggle50) toggle50.addEventListener('change', applySmaVisibility);
    if (toggle200) toggle200.addEventListener('change', applySmaVisibility);
    window.addEventListener('resize', function () {
      if (chart && el.clientWidth) {
        chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
      }
    });
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(function () {
        if (chart && el.clientWidth) {
          chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
        }
      }).observe(el);
    }
  }

  function applySmaVisibility() {
    if (!chart) return;
    var t50 = document.getElementById('toggle-sma50');
    var t200 = document.getElementById('toggle-sma200');
    if (sma50Series) sma50Series.applyOptions({ visible: !t50 || t50.checked });
    if (sma200Series) sma200Series.applyOptions({ visible: !t200 || t200.checked });
  }

  function drawBars(bars) {
    ensureChart();
    if (!chart) return;
    chartBars = bars || [];
    areaSeries.setData(chartBars.map(function (bar) {
      return { time: bar.time, value: bar.close };
    }));
    volumeSeries.setData(chartBars.map(function (bar, index) {
      var up = index === 0 || bar.close >= chartBars[index - 1].close;
      return {
        time: bar.time,
        value: bar.volume || 0,
        color: up ? 'rgba(78,222,163,0.35)' : 'rgba(255,138,128,0.35)'
      };
    }));
    var closes = chartBars.map(function (bar) { return bar.close; });
    sma50Series.setData(sma(closes, 50));
    sma200Series.setData(sma(closes, 200));
    applySmaVisibility();
    chart.timeScale().fitContent();
  }

  function loadBars(rangeKey) {
    return api('/api/stocks/' + encodeURIComponent(code) + '/bars?range=' + encodeURIComponent(rangeKey))
      .then(function (data) { drawBars(data.bars || []); });
  }

  function wireRanges() {
    var buttons = document.querySelectorAll('.stock-range');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        var target = event.currentTarget;
        var rangeKey = target.getAttribute('data-range');
        for (var j = 0; j < buttons.length; j++) buttons[j].setAttribute('aria-pressed', 'false');
        target.setAttribute('aria-pressed', 'true');
        loadBars(rangeKey).catch(function () { /* keep the previous chart */ });
      });
    }
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
        }).catch(function () { /* silent: search is optional */ });
      }, 250);
    });
  }

  // ------------------------------------------------------------------ actions
  function renderActions(payload) {
    var body = document.getElementById('actions-body');
    var summary = document.getElementById('actions-summary');
    var rows = (payload && payload.actions) || [];
    var trailing = (payload && payload.trailing_dividend) || null;
    if (summary) {
      if (trailing && trailing.cash_per_share_tl) {
        summary.textContent = 'Son 12 ay brüt nakit temettü: ' + num(trailing.cash_per_share_tl, 4) +
          ' TL/hisse' + (trailing.yield_pct === null ? '' : ' · verim %' + num(trailing.yield_pct, 2));
      } else {
        summary.textContent = 'Son 12 ayda nakit temettü kaydı yok.';
      }
    }
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="6" class="py-space-sm text-outline">Kayıt yok.</td></tr>';
      return;
    }
    body.innerHTML = rows.map(function (row) {
      return '<tr class="border-b border-surface-container-high/30">' +
        '<td class="py-space-3xs">' + escapeHtml(row.action_date) + '</td>' +
        '<td class="py-space-3xs">' + escapeHtml(row.kind_label || row.kind) + '</td>' +
        '<td class="py-space-3xs text-right">' + (row.cash_per_share_tl ? num(row.cash_per_share_tl, 4) : '—') + '</td>' +
        '<td class="py-space-3xs text-right">' + (row.cash_ratio_pct ? '%' + num(row.cash_ratio_pct, 2) : '—') + '</td>' +
        '<td class="py-space-3xs text-right">' + (row.bonus_ratio_pct ? '%' + num(row.bonus_ratio_pct, 2) : '—') + '</td>' +
        '<td class="py-space-3xs text-right">' + (row.rights_ratio_pct ? '%' + num(row.rights_ratio_pct, 2) : '—') + '</td>' +
        '</tr>';
    }).join('');
  }

  // ---------------------------------------------------------------------- KAP
  function renderKap(rows) {
    var list = document.getElementById('kap-list');
    if (!list) return;
    if (!rows || !rows.length) {
      list.innerHTML = '<li>Bu hisse için kayıtlı KAP bildirimi yok. Liste günlük toplanır.</li>';
      return;
    }
    list.innerHTML = rows.slice(0, 20).map(function (row) {
      var date = (row.published_date || '').split('-');
      var shown = date.length === 3 ? date[2] + '.' + date[1] + '.' + date[0] : (row.published_date || '');
      return '<li class="py-space-3xs border-b border-surface-container-high/30">' +
        '<span class="text-outline">' + escapeHtml(shown) + '</span> · ' +
        '<a class="text-primary" target="_blank" rel="noopener noreferrer" href="' +
        escapeHtml(row.url) + '">' + escapeHtml(row.subject || 'Bildirim') + '</a></li>';
    }).join('');
  }

  function boot() {
    if (!code) return;
    wireRanges();
    wireSearch();
    api('/api/stocks/' + encodeURIComponent(code)).then(function (data) {
      renderProfile(data.profile);
    }).catch(function () {
      setText('stock-asof', 'Profil yüklenemedi.');
    });
    api('/api/stocks/' + encodeURIComponent(code) + '/fundamentals').then(function (data) {
      renderFundamentals(data.fundamentals);
    }).catch(function () { /* keep the empty state */ });
    api('/api/stocks/' + encodeURIComponent(code) + '/scans').then(function (data) {
      renderScans(data.scans);
    }).catch(function () { /* keep the empty state */ });
    api('/api/stocks/' + encodeURIComponent(code) + '/corporate-actions').then(function (data) {
      renderActions(data);
    }).catch(function () {
      var summary = document.getElementById('actions-summary');
      if (summary) summary.textContent = 'Temettü verisi yüklenemedi.';
    });
    api('/api/stocks/' + encodeURIComponent(code) + '/kap').then(function (data) {
      renderKap(data.disclosures);
    }).catch(function () {
      var list = document.getElementById('kap-list');
      if (list) list.innerHTML = '<li>KAP bildirimleri yüklenemedi.</li>';
    });
    loadBars('1y').catch(function () {
      var note = document.getElementById('chart-note');
      if (note) note.textContent = 'Bu hisse için grafik verisi henüz yüklenmedi.';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
