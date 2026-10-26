/* Faz P3.2 stock comparison. CSP-safe, inline-SVG chart. */
(function () {
  'use strict';

  var COLORS = ['#7dd3fc', '#fca5a5', '#a7f3d0', '#fcd34d'];

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

  function num(value, digits) {
    if (value === null || value === undefined) return '—';
    return Number(value).toLocaleString('tr-TR', {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0
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

  function renderChart(stocks) {
    var host = document.getElementById('compare-chart');
    if (!host) return;
    var series = stocks.filter(function (item) { return (item.series || []).length > 1; });
    if (!series.length) {
      host.innerHTML = '<p class="font-body-sm text-body-sm text-outline">Grafik için yeterli ortak geçmiş yok.</p>';
      return;
    }
    var values = [];
    series.forEach(function (item) {
      item.series.forEach(function (point) { values.push(point.value); });
    });
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    if (min === max) { min -= 1; max += 1; }
    // Shared time axis: one x position per calendar session across all series,
    // so a stock with missing sessions is not stretched against the others.
    var axis = {};
    series.forEach(function (item) {
      item.series.forEach(function (point) { axis[point.time] = true; });
    });
    var times = Object.keys(axis).sort();
    var position = {};
    times.forEach(function (time, index) { position[time] = index; });
    var width = 720;
    var height = Math.max(200, Math.round(host.clientHeight || 260));
    var pad = 28;
    var span = times.length > 1 ? times.length - 1 : 1;
    var paths = series.map(function (item, index) {
      var d = item.series.map(function (point, i) {
        var x = pad + (width - pad * 2) * (position[point.time] / span);
        var y = height - pad - (height - pad * 2) * ((point.value - min) / (max - min));
        return (i === 0 ? 'M' : 'L') + x.toFixed(1) + ' ' + y.toFixed(1);
      }).join(' ');
      return '<path d="' + d + '" fill="none" stroke="' + COLORS[index % COLORS.length] +
        '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
    }).join('');
    host.innerHTML = '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" ' +
      'aria-label="Normalize fiyat karşılaştırma grafiği" preserveAspectRatio="none" ' +
      'style="width:100%;height:100%">' +
      '<line x1="' + pad + '" y1="' + (height - pad) + '" x2="' + (width - pad) + '" y2="' + (height - pad) +
      '" stroke="#444" stroke-width="1"/>' + paths + '</svg>';

    var legend = document.getElementById('compare-legend');
    if (legend) {
      legend.innerHTML = series.map(function (item, index) {
        return '<span class="font-body-sm text-body-sm"><span class="oc-dot" style="display:inline-block;width:0.6rem;height:0.6rem;border-radius:999px;background:' +
          COLORS[index % COLORS.length] + '"></span> ' + esc(item.code) + '</span>';
      }).join('');
    }
  }

  function renderTable(stocks) {
    var body = document.getElementById('compare-body');
    if (!body) return;
    if (!stocks.length) {
      body.innerHTML = '<tr><td colspan="13" class="py-space-sm">Sonuç yok.</td></tr>';
      return;
    }
    body.innerHTML = stocks.map(function (item) {
      var t = item.technical || {};
      var f = item.fundamentals || {};
      return '<tr>' +
        '<td class="sticky-col"><a href="/ui/stock/' + encodeURIComponent(item.code) + '">' +
        esc(item.code) + '</a></td>' +
        '<td class="text-right">' + num(item.last_close, 2) + '</td>' +
        '<td class="text-right ' + tone(item.change_pct) + '">' + pct(item.change_pct) + '</td>' +
        '<td class="text-right ' + tone(item.returns && item.returns["1m"]) + '">' + pct(item.returns && item.returns["1m"]) + '</td>' +
        '<td class="text-right ' + tone(item.returns && item.returns["3m"]) + '">' + pct(item.returns && item.returns["3m"]) + '</td>' +
        '<td class="text-right ' + tone(item.returns && item.returns["1y"]) + '">' + pct(item.returns && item.returns["1y"]) + '</td>' +
        '<td class="text-right">' + num(t.rsi14, 1) + '</td>' +
        '<td class="text-right ' + tone(t.vs_sma50_pct) + '">' + pct(t.vs_sma50_pct) + '</td>' +
        '<td class="text-right">' + pct(t.from_high_pct) + '</td>' +
        '<td class="text-right">' + num(f.pe_ttm, 2) + '</td>' +
        '<td class="text-right">' + num(f.pb, 2) + '</td>' +
        '<td class="text-right ' + tone(f.roe_pct) + '">' + pct(f.roe_pct) + '</td>' +
        '<td class="text-right">' + esc(f.latest_period
          ? f.latest_period + (f.stale ? ' · gecikmiş' : '')
          : 'veri yok') + '</td>' +
        '</tr>';
    }).join('');
  }

  function run() {
    var raw = document.getElementById('compare-codes').value || '';
    var codes = raw.split(/[,\s]+/).filter(function (part) { return part.length; });
    if (!codes.length) {
      setText('compare-status', 'En az bir hisse kodu girin.');
      return;
    }
    if (codes.length > 4) {
      setText('compare-status', 'En fazla 4 hisse karşılaştırılır.');
      return;
    }
    var range = document.getElementById('compare-range').value;
    setText('compare-status', 'Yükleniyor…');
    api('/api/stocks/compare?codes=' + encodeURIComponent(codes.join(',')) +
      '&range=' + encodeURIComponent(range)).then(function (data) {
      var stocks = data.stocks || [];
      renderChart(stocks);
      renderTable(stocks);
      setText('compare-base', data.base_date ?
        'Ortak başlangıç seansı: ' + data.base_date : 'Ortak seans bulunamadı.');
      var missing = data.missing && data.missing.length ? ' · bulunamadı: ' + data.missing.join(', ') : '';
      setText('compare-status', (stocks.length ? stocks.length + ' hisse' : 'Sonuç yok') + missing);
      if (window.history && window.history.replaceState) {
        window.history.replaceState(null, '', '/ui/compare?codes=' +
          encodeURIComponent(codes.join(',')) + '&range=' + encodeURIComponent(range));
      }
    }).catch(function (error) { setText('compare-status', error.message); });
  }

  function boot() {
    var params = new URLSearchParams(window.location.search || '');
    var prefill = params.get('codes');
    if (prefill) document.getElementById('compare-codes').value = prefill.replace(/,/g, ', ');
    var range = params.get('range');
    if (range) document.getElementById('compare-range').value = range;
    document.getElementById('compare-run').addEventListener('click', run);
    document.getElementById('compare-codes').addEventListener('keydown', function (event) {
      if (event.key === 'Enter') { event.preventDefault(); run(); }
    });
    if (prefill) run();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
