/* Faz 8a scorecard. CSP-safe. */
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

  function setStatus(text) {
    var el = document.getElementById('score-status');
    if (el) el.textContent = text || '';
  }

  function render(scores) {
    var body = document.getElementById('score-body');
    var rows = [];
    scores.forEach(function (scan) {
      var horizons = scan.horizons || [];
      if (!horizons.length) {
        rows.push('<tr><td>' + esc(scan.title) + '</td><td colspan="8" class="text-outline">' +
          esc(scan.note || 'veri yok') + '</td></tr>');
        return;
      }
      horizons.forEach(function (score, index) {
        var status;
        if (!score.observations) {
          status = 'ileri getiri yok';
        } else if (score.reliable) {
          status = score.excess_vs_xu100_pct > 0 ? 'kanıtlı pozitif' : 'kanıtlı negatif';
        } else {
          status = 'yetersiz veri';
        }
        rows.push('<tr>' +
          '<td>' + (index === 0 ? esc(scan.title) : '') + '</td>' +          '<td class="text-right">' + num(score.horizon, 0) + 'g</td>' +
          '<td class="text-right">' + num(score.observations, 0) + '</td>' +
          '<td class="text-right">' + pct(score.scan_mean_pct) + '</td>' +
          '<td class="text-right">' + pct(score.xu100_mean_pct) + '</td>' +
          '<td class="text-right">' + pct(score.random_mean_pct) + '</td>' +
          '<td class="text-right ' + tone(score.excess_vs_xu100_pct) + '">' + pct(score.excess_vs_xu100_pct) + '</td>' +
          '<td class="text-right">' + num(score.t_stat, 2) + '</td>' +
          '<td>' + esc(status) + '</td>' +
          '</tr>');
      });
      var matured = horizons.some(function (score) { return score.observations > 0; });
      if (!matured && scan.note) {
        rows.push('<tr><td></td><td colspan="8" class="text-outline">' + esc(scan.note) +
          (scan.hit_days ? ' · ' + scan.hit_days + ' gün, ' + num(scan.hit_count, 0) + ' kayıt' : '') +
          '</td></tr>');
      }
    });
    body.innerHTML = rows.join('') || '<tr><td colspan="9" class="py-space-sm">Kayıtlı tarama sonucu yok.</td></tr>';
  }

  function load() {
    var since = document.getElementById('since').value;
    var horizons = document.getElementById('horizons').value;
    var query = '?horizons=' + encodeURIComponent(horizons);
    if (since) query += '&since=' + encodeURIComponent(since);
    setStatus('Hesaplanıyor…');
    api('/api/scores' + query).then(function (data) {
      render(data.scores || []);
      var when = data.computed_at ? new Date(data.computed_at).toLocaleString('tr-TR') : '—';
      var source = data.cached ? 'önbellekten' : 'yeni hesaplandı';
      setStatus('Hesaplama: ' + when + ' (' + source + ', önbellek ' +
        num(data.ttl_hours, 0) + ' saat)');
    }).catch(function (error) {
      setStatus(error.message);
    });
  }

  function boot() {
    document.getElementById('reload').addEventListener('click', load);
    load();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
