/* Faz 6 alerts page. CSP-safe. */
(function () {
  'use strict';
  var screens = [];

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

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function show(id, visible) {
    var el = document.getElementById(id);
    if (el) el.classList.toggle('hidden', !visible);
  }

  function syncForm() {
    var kind = document.getElementById('alert-kind').value;
    show('alert-scan', kind === 'screen');
    show('alert-ticker', kind !== 'screen');
    show('alert-op', kind === 'price');
    show('alert-threshold', kind !== 'screen');
    show('watch-only-wrap', kind === 'screen');
  }

  function renderTelegram(status) {
    if (status.linked) {
      setText('telegram-status', 'Bağlı' + (status.username ? ' (@' + status.username + ')' : '') +
        ' · ' + (status.linked_at || '').slice(0, 16).replace('T', ' '));
    } else if (status.bot_username) {
      setText('telegram-status', 'Bağlı değil. Bağla butonuyla tek kullanımlık bağlantı oluşturun.');
    } else {
      setText('telegram-status', 'Telegram botu yapılandırılmadı (TELEGRAM_USER_BOT_USERNAME).');
    }
  }

  function loadTelegram() {
    return api('/api/alerts/telegram').then(renderTelegram)
      .catch(function (error) { setText('telegram-status', error.message); });
  }

  function loadScreens() {
    return api('/api/screens').then(function (data) {
      screens = data.screens || [];
      var select = document.getElementById('alert-scan');
      select.innerHTML = screens.map(function (item) {
        return '<option value="' + esc(item.code) + '">' + esc(item.title) + '</option>';
      }).join('');
    }).catch(function () { /* optional */ });
  }

  function renderAlerts(alerts) {
    var list = document.getElementById('alert-list');
    if (!alerts.length) {
      list.innerHTML = '<div class="stock-kv-row"><span>Henüz alarm yok</span><span></span></div>';
      return;
    }
    list.innerHTML = alerts.map(function (alert) {
      var title;
      if (alert.kind === 'screen') {
        var scan = screens.filter(function (item) { return item.code === alert.target; })[0];
        title = 'Tarama: ' + (scan ? scan.title : alert.target) + (alert.only_watchlist ? ' (izleme listem)' : '');
      } else if (alert.kind === 'price') {
        title = alert.target.replace('.IS', '') + ' ' +
          (alert.op === 'above' ? '≥' : '≤') + ' ' + alert.threshold + ' TL';
      } else {
        title = alert.target.replace('.IS', '') + ' günlük değişim ≥ %' + Math.abs(alert.threshold);
      }
      return '<div class="stock-kv-row"><span>' + esc(title) + '</span><span>' +
        '<button type="button" class="personal-remove" data-id="' + alert.id + '">Sil</button></span></div>';
    }).join('');
    var buttons = list.querySelectorAll('button.personal-remove');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        api('/api/alerts/' + event.currentTarget.getAttribute('data-id'), { method: 'DELETE' })
          .then(loadAlerts).catch(function (error) { setText('alert-status', error.message); });
      });
    }
  }

  function loadAlerts() {
    return api('/api/alerts').then(function (data) { renderAlerts(data.alerts || []); })
      .catch(function (error) { setText('alert-status', error.message); });
  }

  function renderSaved(screensList) {
    var list = document.getElementById('saved-list');
    if (!screensList.length) {
      list.innerHTML = '<div class="stock-kv-row"><span>Kayıtlı filtre yok</span><span></span></div>';
      return;
    }
    list.innerHTML = screensList.map(function (item) {
      return '<div class="stock-kv-row"><span>' + esc(item.name) + '</span><span>' +
        '<button type="button" class="personal-remove" data-id="' + item.id + '">Sil</button></span></div>';
    }).join('');
    var buttons = list.querySelectorAll('button.personal-remove');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener('click', function (event) {
        api('/api/saved-screens/' + event.currentTarget.getAttribute('data-id'), { method: 'DELETE' })
          .then(loadSaved).catch(function (error) { setText('alert-status', error.message); });
      });
    }
  }

  function loadSaved() {
    return api('/api/saved-screens').then(function (data) { renderSaved(data.screens || []); })
      .catch(function () { /* optional */ });
  }

  function wire() {
    document.getElementById('alert-kind').addEventListener('change', syncForm);
    syncForm();

    document.getElementById('link-telegram').addEventListener('click', function () {
      api('/api/alerts/telegram/link', { method: 'POST' }).then(function (data) {
        var link = document.getElementById('telegram-link');
        link.href = data.url;
        link.classList.remove('hidden');
        setText('link-hint', 'Bağlantı 15 dakika geçerli ve tek kullanım içindir. Telegram\'da Start\'a basın.');
      }).catch(function (error) { setText('link-hint', error.message); });
    });

    document.getElementById('unlink-telegram').addEventListener('click', function () {
      api('/api/alerts/telegram', { method: 'DELETE' })
        .then(loadTelegram).catch(function (error) { setText('link-hint', error.message); });
    });

    document.getElementById('alert-form').addEventListener('submit', function (event) {
      event.preventDefault();
      var kind = document.getElementById('alert-kind').value;
      var body = { kind: kind };
      if (kind === 'screen') {
        body.target = document.getElementById('alert-scan').value;
        body.only_watchlist = document.getElementById('alert-watch-only').checked;
      } else {
        body.target = document.getElementById('alert-ticker').value;
        body.threshold = document.getElementById('alert-threshold').value;
        if (kind === 'price') body.op = document.getElementById('alert-op').value;
      }
      api('/api/alerts', { method: 'POST', body: JSON.stringify(body) })
        .then(function () {
          setText('alert-status', 'Alarm eklendi.');
          event.target.reset();
          syncForm();
          return loadAlerts();
        })
        .catch(function (error) { setText('alert-status', error.message); });
    });

    document.getElementById('preview').addEventListener('click', function () {
      setText('preview-text', 'Oluşturuluyor…');
      api('/api/alerts/preview').then(function (data) {
        document.getElementById('preview-text').textContent = data.text || 'Bugün tetiklenen bir alarm yok.';
      }).catch(function (error) { setText('preview-text', error.message); });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      wire(); loadScreens(); loadTelegram(); loadAlerts(); loadSaved();
    });
  } else {
    wire(); loadScreens(); loadTelegram(); loadAlerts(); loadSaved();
  }
})();
