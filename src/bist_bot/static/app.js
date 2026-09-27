/**
 * Bist-Bot web terminal script.
 * Every number on the pages comes from the API; when data is missing the
 * UI shows "—" instead of an invented value.
 */

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Global fetch guard
  //  * 401 on an API call -> silently re-mint the access token from the
  //    HttpOnly refresh cookie once, then retry the original request.
  //  * 402 + sub_expired -> bounce to /ui/billing (server is authoritative).
  // -------------------------------------------------------------------------
  const _nativeFetch = window.fetch.bind(window);
  const _SUB_SAFE_PREFIXES = ['/api/me/subscription', '/api/billing/', '/api/auth/'];
  const _NO_REFRESH_PREFIXES = ['/api/auth/login', '/api/auth/register', '/api/auth/refresh', '/api/auth/logout'];
  let _refreshInFlight = null;

  function readCookie(name) {
    const prefix = name + '=';
    const part = document.cookie.split('; ').find(c => c.indexOf(prefix) === 0);
    return part ? decodeURIComponent(part.slice(prefix.length)) : '';
  }

  function refreshAccessToken() {
    if (!_refreshInFlight) {
      _refreshInFlight = (async () => {
        try {
          const res = await _nativeFetch('/api/auth/refresh', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRF-TOKEN': readCookie('csrf_refresh_token') }
          });
          if (!res.ok) return null;
          const data = await res.json();
          if (data && data.access_token) {
            localStorage.setItem('bistbot_token', data.access_token);
            return data.access_token;
          }
        } catch (e) { /* fall through: caller sees the original 401 */ }
        return null;
      })();
      _refreshInFlight.finally(() => { setTimeout(() => { _refreshInFlight = null; }, 0); });
    }
    return _refreshInFlight;
  }

  window.fetch = async function (input, init) {
    let response = await _nativeFetch(input, init);
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const isApi = typeof url === 'string' && url.indexOf('/api/') !== -1;
    try {
      if (response.status === 401 && isApi && !_NO_REFRESH_PREFIXES.some(p => url.indexOf(p) !== -1)) {
        const token = await refreshAccessToken();
        if (token) {
          const headers = new Headers((init && init.headers) || {});
          headers.set('Authorization', 'Bearer ' + token);
          response = await _nativeFetch(input, Object.assign({}, init || {}, { headers: headers }));
        }
      }
      const onBillingPage = window.location.pathname === '/ui/billing';
      if (
        response.status === 402 && isApi &&
        !_SUB_SAFE_PREFIXES.some(p => url.indexOf(p) !== -1) &&
        !onBillingPage
      ) {
        const data = await response.clone().json().catch(() => null);
        if (data && data.code === 'sub_expired') {
          window.location.replace('/ui/billing');
        }
      }
    } catch (e) { /* never break the original call */ }
    return response;
  };

  // -------------------------------------------------------------------------
  // Small formatting helpers
  // -------------------------------------------------------------------------
  const DASH = '—';

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function num(value) {
    if (value === null || value === undefined || value === '') return NaN;
    const n = Number(value);
    return Number.isFinite(n) ? n : NaN;
  }

  function positive(value) {
    const n = num(value);
    return n > 0 ? n : NaN;
  }

  function tl(value, digits = 2) {
    const n = num(value);
    return Number.isFinite(n)
      ? '₺' + n.toLocaleString('tr-TR', { minimumFractionDigits: digits, maximumFractionDigits: digits })
      : DASH;
  }

  function signedPct(value, digits = 2) {
    const n = num(value);
    if (!Number.isFinite(n)) return '';
    return (n > 0 ? '+' : '') + n.toFixed(digits) + '%';
  }

  function pctFrom(base, value) {
    const b = num(base);
    const v = num(value);
    if (!Number.isFinite(b) || !Number.isFinite(v) || b === 0) return NaN;
    return ((v - b) / b) * 100;
  }

  // API timestamps are UTC; naive ones (scan_log) carry no offset.
  function parseApiTime(value) {
    if (!value) return null;
    let s = String(value);
    if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += 'Z';
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  // Istanbul wall-clock parts, independent of the browser's locale quirks.
  function istanbulParts(value) {
    const d = parseApiTime(value);
    if (!d) return null;
    const parts = {};
    new Intl.DateTimeFormat('en-GB', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
      hour12: false, timeZone: 'Europe/Istanbul'
    }).formatToParts(d).forEach(p => { parts[p.type] = p.value; });
    return parts;
  }

  function fmtDateTime(value) {
    const p = istanbulParts(value);
    return p ? `${p.day}.${p.month}.${p.year} ${p.hour}:${p.minute}` : DASH;
  }

  function fmtShortDateTime(value) {
    const p = istanbulParts(value);
    return p ? `${p.day}.${p.month} ${p.hour}:${p.minute}` : DASH;
  }

  // price_data[].label is already Istanbul time: "YYYY-MM-DD HH:MM" or "YYYY-MM-DD".
  function fmtBarLabel(label, withDate) {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}))?/.exec(String(label || ''));
    if (!m) return String(label || '');
    const day = `${m[3]}.${m[2]}`;
    if (!m[4]) return day;
    return withDate ? `${day} ${m[4]}:${m[5]}` : `${m[4]}:${m[5]}`;
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = (value === null || value === undefined || value === '') ? DASH : String(value);
  }

  function setHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  }

  function signalRowKind(typeText) {
    const upper = String(typeText || '').toLocaleUpperCase('tr-TR');
    if (upper.includes('SAT')) return 'sell';
    if (upper.includes('AL')) return 'buy';
    return 'hold';
  }

  function signalTypeLabel(typeText) {
    return String(typeText || '').replace(/^[^\p{L}\p{N}]+/u, '').trim();
  }

  const CONFIDENCE_LABELS = {
    'confidence.high': 'Yüksek',
    'confidence.medium': 'Orta',
    'confidence.low': 'Düşük'
  };
  const OUTCOME_LABELS = {
    PENDING: 'Beklemede',
    TARGET_HIT: 'Hedef görüldü',
    STOP_HIT: 'Stop oldu',
    TIMEOUT: 'Süre doldu',
    EOD_CLOSE: 'Gün sonu kapandı',
    NOT_TRACKED: 'Takip edilmedi'
  };
  const REJECTION_REASON_LABELS = {
    score_filtered_sideways: 'Yatay piyasa: skor eşiğin altında',
    score_filtered_momentum: 'Momentum onayı yok',
    score_filtered_pv_confirmation: 'Fiyat-hacim onayı yok',
    score_zero_after_penalty: 'Cezalar sonrası skor sıfır',
    hold_neutral_zone: 'Nötr bölge (BEKLE)',
    confluence_failed: 'Zaman dilimi uyumu yok',
    confluence_soft_fail_short: 'Kısa vade uyumu zayıf',
    mtf_confluence_blocked: 'Çoklu zaman dilimi engeli',
    meta_model_blocked: 'Meta model engeli',
    session_limit_down_blocked: 'Taban fiyat koruması',
    sector_limit_blocked: 'Sektör limiti dolu',
    insufficient_history: 'Yetersiz fiyat geçmişi',
    adx_missing: 'ADX hesaplanamadı'
  };
  const REJECTION_STAGE_LABELS = {
    data: 'Veri',
    indicators: 'Göstergeler',
    scoring: 'Skorlama',
    classification: 'Sınıflandırma',
    confluence: 'Zaman dilimi uyumu',
    mtf: 'Çoklu zaman dilimi',
    risk: 'Risk'
  };
  const INTERVAL_LABELS = { '15m': '15 dakikalık', '60m': '1 saatlik', '1h': '1 saatlik', '4h': '4 saatlik', '1d': 'Günlük', '1wk': 'Haftalık' };

  // -------------------------------------------------------------------------
  // Global Toast Notifications
  // -------------------------------------------------------------------------
  function showToast(message, type = 'info', duration = 3500) {
    let container = document.getElementById('bb-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'bb-toast-container';
      container.className = 'fixed top-20 right-6 z-[9999] flex flex-col gap-2 pointer-events-none';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const colors = {
      success: 'bg-surface-container-high border-primary text-primary',
      error: 'bg-surface-container-high border-error text-error',
      info: 'bg-surface-container-high border-secondary text-secondary',
      warning: 'bg-surface-container-high border-[#ffb74d] text-[#ffb74d]'
    };
    const icons = { success: 'check_circle', error: 'error', info: 'info', warning: 'warning' };
    const colorClass = colors[type] || colors.info;
    const iconName = icons[type] || 'info';

    toast.className = `pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl border shadow-2xl backdrop-blur-xl transition-all duration-300 transform translate-x-12 opacity-0 font-body-md text-body-md ${colorClass}`;
    toast.innerHTML = `
      <span class="material-symbols-outlined text-[20px]">${iconName}</span>
      <span class="text-on-surface font-medium">${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);
    requestAnimationFrame(() => {
      toast.classList.remove('translate-x-12', 'opacity-0');
    });

    setTimeout(() => {
      toast.classList.add('translate-x-12', 'opacity-0');
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  // -------------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------------
  function getAuthHeaders(extra) {
    const token = localStorage.getItem('bistbot_token');
    const h = Object.assign({}, extra || {});
    if (token) h['Authorization'] = 'Bearer ' + token;
    return h;
  }

  function handleSessionExpired() {
    localStorage.removeItem('bistbot_token');
    localStorage.removeItem('bistbot_email');
    showToast('Oturum süresi doldu. Yeniden giriş yapın.', 'error', 3000);
    setTimeout(() => window.location.replace('/login'), 1200);
  }

  async function ensureSession(token) {
    // Confirm a usable session AND the UI cookie before any navigation.
    // Returns false without navigating, so a stale token can never
    // ping-pong between /login and a gated page (and burn rate limits).
    try {
      const verify = await fetch('/api/auth/verify', {
        headers: { 'Authorization': 'Bearer ' + token }
      });
      if (!verify.ok) return false;
      const session = await fetch('/api/auth/session', {
        method: 'POST',
        headers: getAuthHeaders()
      });
      return session.ok;
    } catch (err) {
      return false;
    }
  }

  async function enforceAuth() {
    const path = window.location.pathname;
    const onLoginPage = path === '/login' || path === '/' || path === '/ui';
    let token = localStorage.getItem('bistbot_token');
    if (!token && readCookie('csrf_refresh_token')) {
      // "Remember me" survives a cleared localStorage: the HttpOnly refresh
      // cookie can still mint a fresh access token.
      token = await refreshAccessToken();
    }

    if (!token && !onLoginPage) {
      window.location.replace('/login');
      return false;
    }
    if (token && onLoginPage) {
      if (await ensureSession(token)) {
        window.location.replace('/ui/dashboard');
        return false;
      }
      localStorage.removeItem('bistbot_token');
      localStorage.removeItem('bistbot_email');
      return true; // stay on the login page
    }
    return true;
  }

  // -------------------------------------------------------------------------
  // Shared data: /api/stats (benchmarks + latest scan) and /api/config
  // -------------------------------------------------------------------------
  let lastStats = null;
  let configPromise = null;
  let benchmarkRetryDone = false;

  async function fetchStats(includeSignals) {
    const res = await fetch(includeSignals ? '/api/stats?include_signals=1' : '/api/stats', { headers: getAuthHeaders() });
    if (res.status === 401) {
      handleSessionExpired();
      return null;
    }
    if (!res.ok) {
      console.warn(`[bistbot] /api/stats HTTP ${res.status}`);
      return null;
    }
    const data = await res.json();
    lastStats = data;
    hydrateHeader(data);
    // Right after an API restart the index cache is still empty (the server
    // fetches it in the background): ask once more instead of showing "—".
    if (!benchmarkRetryDone && !(data.benchmarks && data.benchmarks.XU100)) {
      benchmarkRetryDone = true;
      setTimeout(() => {
        fetch('/api/stats', { headers: getAuthHeaders() })
          .then(r => (r.ok ? r.json() : null))
          .then(d => { if (d) hydrateBenchmarks(d.benchmarks); })
          .catch(() => {});
      }, 5000);
    }
    return data;
  }

  function fetchConfig() {
    if (!configPromise) {
      configPromise = fetch('/api/config', { headers: getAuthHeaders() })
        .then(res => (res.ok ? res.json() : null))
        .catch(() => null);
    }
    return configPromise;
  }

  function hydrateBenchmarks(benchmarks) {
    if (!benchmarks) return;
    const updatePair = (baseKey, item) => {
      if (!item) return;
      ['benchmark-', 'header-'].forEach(prefix => {
        const vEl = document.getElementById(`${prefix}${baseKey}-val`);
        const cEl = document.getElementById(`${prefix}${baseKey}-chg`);
        if (vEl && Number.isFinite(num(item.val))) {
          vEl.textContent = baseKey.includes('usd')
            ? Number(item.val).toFixed(2)
            : Number(item.val).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        if (cEl) {
          const chg = num(item.chg);
          if (!Number.isFinite(chg)) {
            cEl.textContent = '';
          } else {
            const pos = chg >= 0;
            const color = pos ? 'text-primary' : 'text-error';
            const icon = pos ? 'arrow_drop_up' : 'arrow_drop_down';
            if (prefix === 'header-') {
              cEl.className = `font-label-code text-label-code ${color} flex items-center`;
              cEl.innerHTML = `<span class="material-symbols-outlined text-[14px]">${icon}</span>${signedPct(chg)}`;
            } else {
              cEl.className = `font-metric-value text-metric-value ${color} flex items-center justify-end`;
              cEl.innerHTML = `<span class="material-symbols-outlined text-[16px]">${icon}</span> ${signedPct(chg)}`;
            }
          }
        }
      });
      const asOf = document.getElementById(`benchmark-${baseKey}-asof`);
      if (asOf && item.as_of) {
        const [y, m, d] = String(item.as_of).split('-');
        asOf.textContent = `Kapanış ${d}.${m}.${y} · gecikmeli veri`;
      }
    };
    updatePair('xu100', benchmarks.XU100);
    updatePair('xu030', benchmarks.XU030);
    updatePair('usdtry', benchmarks.USDTRY);
    if (benchmarks.BIST_VOL) setText('header-bist-vol', benchmarks.BIST_VOL);
  }

  function hydrateHeader(data) {
    if (!data) return;
    hydrateBenchmarks(data.benchmarks);
    const scan = data.latest_scan || {};
    const status = document.getElementById('header-scan-status');
    if (status) {
      status.textContent = scan.timestamp
        ? `Tarama ${fmtShortDateTime(scan.timestamp)}`
        : 'Tarama yok';
      status.title = scanSummaryText(data);
    }
  }

  function scanSummaryText(data) {
    const scan = (data && data.latest_scan) || {};
    if (!scan.timestamp) return 'Henüz tarama verisi yok.';
    return `Son tarama ${fmtDateTime(scan.timestamp)}: ${scan.total_scanned ?? DASH} hisse tarandı, ` +
      `${scan.signals_generated ?? DASH} sinyal üretildi, ${scan.actionable ?? DASH} tanesi işleme uygun.`;
  }

  // -------------------------------------------------------------------------
  // Topbar
  // -------------------------------------------------------------------------
  function formatRemaining(totalSeconds) {
    const s = Math.max(0, Math.floor(totalSeconds || 0));
    const days = Math.floor(s / 86400);
    const hours = Math.floor((s % 86400) / 3600);
    const mins = Math.floor((s % 3600) / 60);
    if (days > 0) return hours > 0 ? `${days}g ${hours}s` : `${days}g`;
    if (hours > 0) return `${hours}s ${mins}d`;
    return `${mins}d`;
  }

  async function updateSubscriptionBadge() {
    const badge = document.getElementById('sub-countdown-badge');
    if (!badge || !localStorage.getItem('bistbot_token')) return;
    try {
      const res = await fetch('/api/me/subscription', { headers: getAuthHeaders() });
      if (!res.ok) return;
      const data = await res.json();
      const labels = { trial: 'Deneme', pro: 'Pro', pro_plus: 'Pro+' };
      badge.classList.remove('hidden');
      if (data.unlimited) {
        badge.textContent = 'Yönetici';
        badge.title = 'Yönetici hesabı: süresiz erişim';
      } else if (data.status === 'active') {
        badge.textContent = `${labels[data.plan] || 'Deneme'} • ${formatRemaining(data.remaining_seconds)}`;
        badge.classList.toggle('text-error', (data.remaining_seconds || 0) < 21600);
      } else {
        badge.textContent = 'Süresi doldu';
        badge.classList.add('text-error');
      }
    } catch (e) { /* badge stays hidden on failure */ }
  }

  const NAV_HEADER_ON = 'px-space-sm py-space-2xs rounded transition-all bg-surface-container-high text-primary font-bold';
  const NAV_HEADER_OFF = 'px-space-sm py-space-2xs rounded text-on-surface-variant hover:bg-surface-container hover:text-on-surface font-body-md text-body-md transition-all';
  const NAV_BOTTOM_ON = 'flex items-center gap-space-2xs px-space-lg py-space-xs rounded-full bg-primary/15 text-primary font-body-md text-body-md font-bold shadow-[0_0_12px_rgba(78,222,163,0.25)] transition-all';
  const NAV_BOTTOM_OFF = 'flex items-center gap-space-2xs px-space-md py-space-xs rounded-full text-on-surface-variant hover:text-on-surface hover:bg-surface-container font-body-md text-body-md transition-all';

  function syncActiveNav() {
    const path = window.location.pathname === '/' || window.location.pathname === '/ui'
      ? '/ui/dashboard' : window.location.pathname;
    document.querySelectorAll('header nav a[href^="/ui/"]').forEach(a => {
      const on = a.getAttribute('href') === path;
      a.className = on ? NAV_HEADER_ON : NAV_HEADER_OFF;
      if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    document.querySelectorAll('.bb-bottom-nav nav a[href^="/ui/"]').forEach(a => {
      a.className = a.getAttribute('href') === path ? NAV_BOTTOM_ON : NAV_BOTTOM_OFF;
    });
  }

  function initTopbar() {
    document.querySelectorAll('button[title="Yenile"]').forEach(btn => {
      btn.onclick = () => window.location.reload();
    });

    // Bell: the latest real scan summary (there is no separate inbox).
    document.querySelectorAll('button[title="Bildirimler"]').forEach(btn => {
      btn.onclick = async () => {
        const data = lastStats || await fetchStats(false);
        showToast(scanSummaryText(data), 'info', 6000);
      };
    });

    // Logout: revokes access + refresh tokens server-side, clears storage.
    document.querySelectorAll('button[title="Çıkış"]').forEach(btn => {
      btn.onclick = async () => {
        try {
          await fetch('/api/auth/logout', { method: 'POST', headers: getAuthHeaders() });
        } catch (e) { /* ignore network error on logout */ }
        localStorage.removeItem('bistbot_token');
        localStorage.removeItem('bistbot_email');
        showToast('Oturum kapatıldı. Yönlendiriliyorsunuz...', 'info', 1500);
        setTimeout(() => window.location.href = '/login', 400);
      };
    });

    const brand = document.querySelector('.bb-topbar-brand') || document.querySelector('header .font-headline-md');
    if (brand) {
      brand.style.cursor = 'pointer';
      brand.onclick = () => window.location.href = '/ui/dashboard';
    }

    // Show the logged-in operator email instead of the template placeholder.
    const storedEmail = localStorage.getItem('bistbot_email');
    if (storedEmail) {
      document.querySelectorAll('header span').forEach(el => {
        if (el.children.length === 0 && el.textContent.includes('@')) {
          el.textContent = storedEmail;
        }
      });
    }
    syncActiveNav();
  }

  // -------------------------------------------------------------------------
  // Scan trigger (dashboard + settings): real /api/scan call
  // -------------------------------------------------------------------------
  async function runScan(button) {
    const icon = button.querySelector('.material-symbols-outlined');
    if (icon) icon.classList.add('animate-spin');
    button.disabled = true;
    showToast('BIST 100 taraması başlatıldı; bu işlem birkaç dakika sürebilir...', 'info', 3000);
    try {
      const headers = getAuthHeaders({ 'Content-Type': 'application/json' });
      // Bearer header (not the HttpOnly UI cookie) authenticates this
      // POST, so no CSRF token dance is needed.
      const res = await fetch('/api/scan', { method: 'POST', headers: headers });
      if (res.status === 401) {
        showToast('Oturum süresi doldu. Yeniden giriş yapın.', 'error', 3000);
        localStorage.removeItem('bistbot_token');
        localStorage.removeItem('bistbot_email');
        setTimeout(() => window.location.replace('/login'), 1200);
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status !== 'ok') {
        showToast(`Tarama tamamlanamadı: ${data.message || 'HTTP ' + res.status}`, 'error', 4000);
        return;
      }
      const produced = data.generated_signals_count ?? data.actionable_count ?? 0;
      showToast(`Tarama tamamlandı: ${data.scanned_count ?? DASH} hisse, ${produced} sinyal.`, 'success', 4000);
      setTimeout(() => window.location.reload(), 1500);
    } catch (err) {
      showToast('Tarama isteği gönderilemedi. Bağlantıyı kontrol edin.', 'error', 3000);
    } finally {
      if (icon) icon.classList.remove('animate-spin');
      button.disabled = false;
    }
  }

  // -------------------------------------------------------------------------
  // Dashboard
  // -------------------------------------------------------------------------
  function rsiZoneLabel(rsi, oversold = 30, overbought = 70) {
    const v = num(rsi);
    if (!Number.isFinite(v)) return '';
    if (v <= oversold) return 'Aşırı satım bölgesi';
    if (v >= overbought) return 'Aşırı alım bölgesi';
    return 'Nötr bölge';
  }

  function renderStageStrip(breakdown) {
    const el = document.getElementById('scan-stage-strip');
    if (!el) return;
    const stages = (breakdown && Array.isArray(breakdown.by_stage)) ? breakdown.by_stage.slice(0, 4) : [];
    if (!stages.length) {
      el.innerHTML = '<div class="flex items-center gap-space-xs bg-surface-container/60 p-space-xs rounded-lg">' +
        '<span class="material-symbols-outlined text-outline text-[18px]">filter_alt</span><div>' +
        '<div class="font-label-caps text-label-caps text-outline">Eleme Aşamaları</div>' +
        '<div class="font-label-code text-label-code text-on-surface font-semibold">Son taramada eleme kaydı yok</div></div></div>';
      return;
    }
    el.innerHTML = stages.map(s => (
      '<div class="flex items-center gap-space-xs bg-surface-container/60 p-space-xs rounded-lg">' +
      '<span class="material-symbols-outlined text-error text-[18px]">do_not_disturb_on</span><div>' +
      `<div class="font-label-caps text-label-caps text-outline">${escapeHtml(REJECTION_STAGE_LABELS[s.stage] || s.stage)}</div>` +
      `<div class="font-label-code text-label-code text-on-surface font-semibold">${escapeHtml(s.count)} hisse elendi</div>` +
      '</div></div>'
    )).join('');
  }

  function renderReasonBars(breakdown) {
    const el = document.getElementById('scan-reason-list');
    if (!el) return;
    const reasons = (breakdown && Array.isArray(breakdown.by_reason)) ? breakdown.by_reason : [];
    const total = num(breakdown && breakdown.total_rejections);
    setText('scan-reason-total', Number.isFinite(total) ? `${total} hisse elendi` : DASH);
    if (!reasons.length) {
      el.innerHTML = '<div class="font-label-code text-label-code text-outline">Son taramada red kaydı yok.</div>';
      return;
    }
    const max = Math.max(...reasons.map(r => num(r.count) || 0), 1);
    el.innerHTML = reasons.slice(0, 6).map(r => {
      const width = Math.max(2, Math.round(((num(r.count) || 0) / max) * 100));
      return '<div class="space-y-space-3xs">' +
        '<div class="flex items-center justify-between font-label-code text-label-code">' +
        `<span class="text-on-surface-variant">${escapeHtml(REJECTION_REASON_LABELS[r.reason_code] || r.reason_code)}</span>` +
        `<strong class="text-on-surface">${escapeHtml(r.count)}</strong></div>` +
        `<div class="bb-bar-track"><div class="bb-bar-fill" style="width: ${width}%"></div></div></div>`;
    }).join('');
  }

  async function hydrateDashboardCounters() {
    if (!document.getElementById('stat-scanned')) return;
    try {
      const [data, cfg] = await Promise.all([fetchStats(true), fetchConfig()]);
      if (!data) return;
      const scan = data.latest_scan || {};
      const stats = data.stats || {};
      const breadth = data.breadth || {};
      const breakdown = scan.rejection_breakdown || data.rejection_breakdown || {};
      const total = num(scan.total_scanned);
      const generated = num(scan.signals_generated);
      const universe = cfg ? num(cfg.watchlist_size) : NaN;
      const hasScan = !!scan.timestamp;

      setText('stat-last-scan', hasScan ? fmtDateTime(scan.timestamp) : 'Henüz tarama yok');
      setText('stat-last-update', hasScan ? fmtShortDateTime(scan.timestamp) : DASH);
      setText('stat-scanned', hasScan ? total : DASH);
      if (hasScan && Number.isFinite(universe) && universe > 0) {
        setText('stat-scanned-sub', `${total}/${universe} sembol`);
        setText('stat-coverage', `%${Math.round((total / universe) * 100)} kapsam`);
        const bar = document.getElementById('stat-coverage-bar');
        if (bar) bar.style.width = `${Math.min(100, Math.round((total / universe) * 100))}%`;
      }
      setText('stat-actionable', hasScan ? scan.actionable : DASH);
      const buys = Array.isArray(breadth.buy_tickers) ? breadth.buy_tickers : [];
      const batchAt = breadth.batch_at ? fmtShortDateTime(breadth.batch_at) : '';
      setText('stat-actionable-tickers', buys.length ? `${buys.join(', ')} (${batchAt})` : 'Yok');
      setText('stat-generated', hasScan ? generated : DASH);
      const completed = num(stats.completed);
      setText('stat-completed', Number.isFinite(completed) ? `${completed} sinyal sonuçlandı` : DASH);
      const rejected = Number.isFinite(num(breakdown.total_rejections)) ? num(breakdown.total_rejections)
        : (Number.isFinite(total) && Number.isFinite(generated) ? total - generated : NaN);
      setText('stat-filtered', hasScan && Number.isFinite(rejected) ? rejected : DASH);
      if (hasScan && Number.isFinite(rejected) && total > 0) {
        setText('stat-filtered-sub', `%${Math.round((rejected / total) * 100)} red oranı`);
      }

      const avgRsi = num(breadth.avg_rsi);
      setText('macro-avg-rsi', Number.isFinite(avgRsi) ? avgRsi.toFixed(1) : DASH);
      const rsiEl = document.getElementById('macro-rsi-status');
      if (rsiEl) {
        rsiEl.textContent = Number.isFinite(avgRsi)
          ? `${rsiZoneLabel(avgRsi, cfg ? cfg.rsi_oversold : 30, cfg ? cfg.rsi_overbought : 70)} · ${batchAt}`
          : 'Kayıtlı sinyal yok';
      }
      const sigCount = num(breadth.signal_count);
      setText('macro-vol-ratio', sigCount > 0 ? `${breadth.volume_confirmed}/${sigCount}` : DASH);
      setText('macro-vol-sub', sigCount > 0 ? `Son sinyal grubu · ${batchAt}` : 'Kayıtlı sinyal yok');

      renderStageStrip(breakdown);
      renderReasonBars(breakdown);

      if (Array.isArray(data.top_signals) && renderDashboardSignals(data.top_signals)) {
        window.__dashSignalsEmbedded = true;
      }
    } catch (err) {
      console.warn('[bistbot] /api/stats unreachable', err);
    }
  }

  function renderOpportunityCard(sig) {
    const symbol = escapeHtml(String(sig.ticker || '').replace(/\.IS$/i, ''));
    const pfx = symbol.slice(0, 3).toUpperCase();
    const sfx = symbol.slice(3, 5).toUpperCase() || symbol.slice(-2).toUpperCase();
    const kind = signalRowKind(sig.signal_type);
    const typeLabel = escapeHtml(signalTypeLabel(sig.signal_type));
    const accent = kind === 'sell' ? 'error' : (kind === 'buy' ? 'primary' : 'tertiary');
    const score = Math.round(num(sig.score));
    const reasons = Array.isArray(sig.reasons) ? sig.reasons : [];
    const reasonText = escapeHtml(reasons[0] || DASH);
    const conf = CONFIDENCE_LABELS[sig.confidence] || DASH;

    return (
      `<div class="group bg-surface-container-low hover:bg-surface-container p-space-md rounded-xl transition-all duration-200 shadow-md hover:shadow-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-space-md">` +
      `<div class="flex items-center gap-space-md">` +
      `<div class="w-12 h-12 rounded-xl bg-surface-container-high flex flex-col items-center justify-center font-metric-value text-metric-value text-${accent} font-bold shadow-inner">` +
      `${escapeHtml(pfx)}<span class="font-label-caps text-[8px] text-outline">${escapeHtml(sfx)}</span></div>` +
      `<div><div class="flex items-center gap-space-xs">` +
      `<span class="font-headline-md text-headline-md text-on-surface font-extrabold">${symbol}</span>` +
      `<span class="inline-flex items-center px-space-xs py-space-3xs rounded-full bg-${accent}/10 text-${accent} font-label-caps text-label-caps uppercase">${typeLabel}</span></div>` +
      `<div class="flex items-center gap-space-xs font-label-code text-label-code text-outline mt-space-3xs">` +
      `<span class="material-symbols-outlined text-${accent} text-[14px]">auto_awesome</span>` +
      `<span>${reasonText} • Güven: <span class="text-${accent} font-bold">${conf}</span></span>` +
      `</div></div></div>` +
      `<div class="flex sm:flex-col items-baseline sm:items-end justify-between w-full sm:w-auto gap-space-xs">` +
      `<div class="font-metric-display text-metric-display text-on-surface font-bold">${tl(sig.price)}</div>` +
      `<div class="flex items-center gap-space-xs">` +
      `<span class="font-label-caps text-label-caps px-space-2xs py-space-3xs rounded bg-surface-container-high text-${accent}">Skor: ${Number.isFinite(score) ? (score > 0 ? '+' : '') + score : DASH}</span>` +
      `</div></div></div>`
    );
  }

  function hydrateOpportunitiesRadar(signals) {
    const container = document.getElementById('radarOpportunitiesContainer');
    if (!container) return;
    // Highest score first, one card per ticker (repeat signals would crowd the radar).
    const seen = new Set();
    const ranked = (signals || []).slice()
      .sort((a, b) => (num(b.score) || 0) - (num(a.score) || 0))
      .filter(s => !seen.has(s.ticker) && seen.add(s.ticker))
      .slice(0, 3);
    container.innerHTML = ranked.length
      ? ranked.map(renderOpportunityCard).join('')
      : '<div class="p-space-md rounded-xl bg-surface-container-low/60 text-on-surface-variant font-label-code text-label-code">Kayıtlı sinyal yok.</div>';
  }

  function renderSignalRow(sig) {
    // NOTE: only utility classes already present in the prebuilt tailwind.css
    // may be used here (no runtime-generated bg-*/text-* variants).
    const kind = signalRowKind(sig.signal_type);
    const palette = kind === 'sell'
      ? { pill: 'bg-error/15 text-error', dot: 'bg-error', score: 'text-error', hover: 'group-hover:text-error' }
      : (kind === 'buy'
        ? { pill: 'bg-primary/15 text-primary', dot: 'bg-primary', score: 'text-primary', hover: 'group-hover:text-primary' }
        : { pill: 'bg-surface-container-highest text-on-surface-variant', dot: 'bg-outline',
            score: 'text-on-surface-variant', hover: 'group-hover:text-tertiary' });
    const symbol = escapeHtml(String(sig.ticker || '').replace(/\.IS$/i, ''));
    const typeLabel = escapeHtml(signalTypeLabel(sig.signal_type));
    const lots = Math.floor(num(sig.position_size));
    const score = Math.round(num(sig.score));
    const outcome = String(sig.outcome || 'PENDING').toUpperCase();
    const statusLabel = escapeHtml(OUTCOME_LABELS[outcome] || outcome);
    return (
      `<tr class="signal-row hover:bg-surface-container/60 transition-colors group" data-type="${kind}">` +
      `<td class="py-space-sm px-space-md font-label-code text-label-code text-tertiary font-bold">` +
      `<span class="${palette.hover} transition-colors">${symbol}</span></td>` +
      `<td class="py-space-sm px-space-md">` +
      `<span class="inline-flex items-center gap-space-2xs px-space-xs py-space-3xs rounded-full ${palette.pill} font-label-caps text-label-caps font-bold uppercase">` +
      `<span class="w-1.5 h-1.5 rounded-full ${palette.dot}"></span>${typeLabel}</span></td>` +
      `<td class="py-space-sm px-space-md font-metric-value text-metric-value text-on-surface font-semibold">${tl(sig.price)}</td>` +
      `<td class="py-space-sm px-space-md font-label-code text-label-code text-on-surface-variant">` +
      `${lots > 0 ? lots.toLocaleString('tr-TR') : DASH}</td>` +
      `<td class="py-space-sm px-space-md">` +
      `<span class="font-metric-value text-metric-value ${palette.score} font-bold">` +
      `${Number.isFinite(score) ? (score > 0 ? '+' : '') + score : DASH}</span></td>` +
      `<td class="py-space-sm px-space-md">` +
      `<span class="inline-flex items-center gap-space-3xs text-outline font-label-code text-label-code">` +
      `<span class="w-1.5 h-1.5 rounded-full bg-outline"></span>${statusLabel}</span></td>` +
      `<td class="py-space-sm px-space-md text-right font-label-code text-label-code text-on-surface-variant">` +
      `${escapeHtml(fmtShortDateTime(sig.timestamp))}</td></tr>`
    );
  }

  function renderDashboardSignals(signals) {
    const tbody = document.getElementById('signalsTableBody');
    if (!tbody || !Array.isArray(signals)) return false;
    if (!signals.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="py-space-lg text-center text-outline font-label-code text-label-code">Kayıtlı sinyal yok.</td></tr>';
      hydrateOpportunitiesRadar([]);
      setText('stat-total', '0 sinyal');
      return true;
    }
    tbody.innerHTML = signals.map(renderSignalRow).join('');
    hydrateOpportunitiesRadar(signals);
    const counts = { all: signals.length, buy: 0, sell: 0 };
    signals.forEach(s => {
      const k = signalRowKind(s.signal_type);
      if (k === 'buy') counts.buy++;
      if (k === 'sell') counts.sell++;
    });
    setText('btn-tab-all', `Tüm Sinyaller (${counts.all})`);
    setText('btn-tab-buy', `Alış Sinyalleri (${counts.buy})`);
    setText('btn-tab-sell', `Satış Sinyalleri (${counts.sell})`);
    setText('stat-total', `${counts.all} sinyal`);
    return true;
  }

  async function hydrateSignalTable() {
    const tbody = document.getElementById('signalsTableBody');
    if (!tbody || window.__dashSignalsEmbedded) return;
    try {
      const res = await fetch('/api/signals/history?limit=10&compact=1', { headers: getAuthHeaders() });
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      if (!res.ok) {
        console.warn(`[bistbot] /api/signals/history HTTP ${res.status}`);
        tbody.innerHTML = '<tr><td colspan="7" class="py-space-lg text-center text-error font-label-code text-label-code">Sinyaller yüklenemedi.</td></tr>';
        return;
      }
      const data = await res.json();
      renderDashboardSignals(Array.isArray(data.signals) ? data.signals : []);
    } catch (err) {
      console.warn('[bistbot] signal table hydration failed', err);
    }
  }

  async function initDashboard() {
    // Sequential: counters response piggy-backs top-10 signals
    // (?include_signals=1), so the table usually needs no second trip.
    await hydrateDashboardCounters();
    await hydrateSignalTable();

    const scanBtn = document.getElementById('scanButton');
    if (scanBtn) scanBtn.onclick = function () { runScan(scanBtn); };

    // Table: type filter + pagination over the rendered rows.
    const tabs = { all: document.getElementById('btn-tab-all'), buy: document.getElementById('btn-tab-buy'), sell: document.getElementById('btn-tab-sell') };
    const TAB_ON = 'signal-tab-btn px-space-sm py-space-2xs rounded bg-surface-container-high text-primary font-label-code text-label-code font-bold cursor-pointer transition-all';
    const TAB_OFF = 'signal-tab-btn px-space-sm py-space-2xs rounded text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high font-label-code text-label-code cursor-pointer transition-all';
    const prevBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Önceki'));
    const nextBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Sonraki'));
    const pageSize = 7;
    let filter = 'all';
    let currentPage = 1;

    const matchingRows = () => Array.from(document.querySelectorAll('#signalsTableBody tr.signal-row'))
      .filter(r => filter === 'all' || r.dataset.type === filter);
    function totalPages() {
      return Math.max(1, Math.ceil(matchingRows().length / pageSize));
    }

    function renderPage(p) {
      currentPage = Math.min(Math.max(1, p), totalPages());
      const matched = matchingRows();
      document.querySelectorAll('#signalsTableBody tr.signal-row').forEach(r => { r.style.display = 'none'; });
      const start = (currentPage - 1) * pageSize;
      matched.slice(start, start + pageSize).forEach(r => { r.style.display = ''; });
      setText('page-indicator', `${currentPage} / ${totalPages()}`);
      if (prevBtn) prevBtn.disabled = currentPage <= 1;
      if (nextBtn) nextBtn.disabled = currentPage >= totalPages();
    }

    Object.entries(tabs).forEach(([key, btn]) => {
      if (!btn) return;
      btn.onclick = () => {
        filter = key;
        Object.entries(tabs).forEach(([k, b]) => { if (b) b.className = k === key ? TAB_ON : TAB_OFF; });
        renderPage(1);
      };
    });
    if (prevBtn) prevBtn.onclick = () => renderPage(currentPage - 1);
    if (nextBtn) nextBtn.onclick = () => renderPage(currentPage + 1);
    renderPage(1);
  }

  // -------------------------------------------------------------------------
  // Shared SVG chart helpers
  // -------------------------------------------------------------------------
  function renderAxisLabels(containerId, bars, intraday, slots) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!bars.length) {
      el.innerHTML = `<span>${DASH}</span>`;
      return;
    }
    const days = new Set(bars.map(b => String(b.label || b.date || '').slice(0, 10)));
    const withDate = intraday && days.size > 1;
    const n = Math.min(slots, bars.length);
    const picks = [];
    for (let i = 0; i < n; i++) {
      picks.push(bars[Math.round((i * (bars.length - 1)) / Math.max(1, n - 1))]);
    }
    el.innerHTML = picks.map((b, i) => {
      const text = escapeHtml(fmtBarLabel(b.label || b.date, withDate));
      return i === picks.length - 1 ? `<span class="text-primary font-bold">${text}</span>` : `<span>${text}</span>`;
    }).join('');
  }

  // -------------------------------------------------------------------------
  // Signals page: stored signals (cards) + live chart via /api/analyze
  // -------------------------------------------------------------------------
  let signalsData = [];
  let currentSignal = null;
  let currentSignalTimeframe = '15m';
  const signalFilterState = { tab: 'all', minScore: 0, maxRsi: 100, hasLevels: false };

  function reasonRsi(reasons) {
    for (const r of reasons || []) {
      const m = /RSI[^()]*\((\d+(?:\.\d+)?)\)/.exec(String(r));
      if (m) return Number(m[1]);
    }
    return NaN;
  }

  function renderSignalCard(sig, index) {
    const symbol = escapeHtml(String(sig.ticker || '').replace(/\.IS$/i, ''));
    const kind = signalRowKind(sig.signal_type);
    const typeLabel = escapeHtml(signalTypeLabel(sig.signal_type));
    const size = Math.floor(num(sig.position_size));
    const score = Math.round(num(sig.score));
    const reasons = Array.isArray(sig.reasons) ? sig.reasons : [];
    const accent = kind === 'sell' ? 'bg-error/15 text-error' : (kind === 'buy' ? 'bg-primary/15 text-primary' : 'bg-surface-container-highest text-on-surface-variant');
    const scoreAccent = kind === 'sell' ? 'bg-error/15 text-error' : (kind === 'buy' ? 'bg-primary/20 text-primary' : 'bg-surface-container-high text-on-surface-variant');

    return (
      `<div class="signal-card group relative bg-surface-container-low/95 p-space-md rounded-xl shadow-[0_4px_16px_rgba(0,0,0,0.4)] transition-all cursor-pointer overflow-hidden" ` +
      `data-index="${index}" data-kind="${kind}" data-confidence="${escapeHtml(sig.confidence || '')}" ` +
      `data-score="${Number.isFinite(score) ? score : 0}">` +
      `<div class="flex items-start justify-between mb-space-xs pl-space-xs"><div><div class="flex items-center gap-space-xs">` +
      `<span class="font-headline-md text-headline-md font-extrabold text-on-surface tracking-tight">${symbol}</span>` +
      `<span class="${accent} px-space-xs py-space-3xs rounded font-label-caps text-label-caps uppercase font-bold">${typeLabel}</span>` +
      `</div><span class="font-body-sm text-body-sm text-outline">${escapeHtml(reasons[0] || DASH)}</span></div>` +
      `<div class="flex flex-col items-end"><span class="${scoreAccent} px-space-xs py-space-3xs rounded-full font-metric-value text-metric-value font-bold">${Number.isFinite(score) ? (score > 0 ? '+' : '') + score : DASH} SKOR</span>` +
      `<span class="font-label-code text-label-code text-outline mt-space-3xs">${escapeHtml(fmtShortDateTime(sig.timestamp))}</span></div></div>` +
      `<div class="grid grid-cols-3 gap-space-2xs bg-surface-container p-space-xs rounded-lg my-space-xs shadow-inner">` +
      `<div><span class="font-label-caps text-label-caps text-outline block">GİRİŞ FİYATI</span><span class="font-metric-value text-metric-value text-on-surface font-bold">${tl(sig.price)}</span></div>` +
      `<div><span class="font-label-caps text-label-caps text-error block">STOP LOSS</span><span class="font-metric-value text-metric-value text-error font-semibold">${tl(positive(sig.stop_loss))}</span></div>` +
      `<div><span class="font-label-caps text-label-caps text-primary block">HEDEF</span><span class="font-metric-value text-metric-value text-primary font-semibold">${tl(positive(sig.target_price))}</span></div></div>` +
      `<div class="flex items-center justify-between pt-space-2xs pl-space-xs font-label-code text-label-code text-on-surface-variant">` +
      `<span>Pozisyon: <strong class="text-on-surface">${size > 0 ? size.toLocaleString('tr-TR') + ' lot' : DASH}</strong></span>` +
      `<span>Güven: ${escapeHtml(CONFIDENCE_LABELS[sig.confidence] || DASH)}</span></div></div>`
    );
  }

  function signalCardMatches(card, filter) {
    if (filter === 'buy' || filter === 'sell' || filter === 'hold') return card.dataset.kind === filter;
    if (filter === 'high-confidence') return card.dataset.confidence === 'confidence.high';
    return true;
  }

  function applySignalFilters() {
    const cards = document.querySelectorAll('#signalsStreamContainer .signal-card');
    let shown = 0;
    cards.forEach(c => {
      const sig = signalsData[Number(c.dataset.index)] || {};
      const rsi = reasonRsi(sig.reasons);
      const ok = signalCardMatches(c, signalFilterState.tab) &&
        Math.abs(num(sig.score) || 0) >= signalFilterState.minScore &&  // sells score negative
        (!Number.isFinite(rsi) || rsi <= signalFilterState.maxRsi) &&
        (!signalFilterState.hasLevels || (positive(sig.stop_loss) > 0 && positive(sig.target_price) > 0));
      c.style.display = ok ? 'block' : 'none';
      if (ok) shown++;
    });
    setText('sig-count-visible', shown);
    return shown;
  }

  function updateFilterCounts() {
    const cards = Array.from(document.querySelectorAll('#signalsStreamContainer .signal-card'));
    const counts = { all: cards.length, buy: 0, hold: 0, sell: 0, 'high-confidence': 0 };
    cards.forEach(c => {
      ['buy', 'hold', 'sell', 'high-confidence'].forEach(f => { if (signalCardMatches(c, f)) counts[f]++; });
    });
    Object.entries(counts).forEach(([k, v]) => setText(`filter-count-${k}`, v));
    setText('sig-count-buy', counts.buy);
    setText('sig-count-hold', counts.hold);
    setText('sig-count-sell', counts.sell);
    setText('sig-count-visible', counts.all);
  }

  function selectCard(card) {
    document.querySelectorAll('#signalsStreamContainer .signal-card').forEach(c => {
      const bar = c.querySelector('.bb-active-bar');
      if (bar) bar.remove();
    });
    const bar = document.createElement('div');
    bar.className = 'bb-active-bar absolute left-0 top-0 bottom-0 w-1.5 bg-primary shadow-[0_0_12px_#4edea3]';
    card.prepend(bar);
    showSignalDetail(signalsData[Number(card.dataset.index)]);
  }

  async function hydrateSignalsStream() {
    const container = document.getElementById('signalsStreamContainer');
    if (!container) return;
    try {
      const res = await fetch('/api/signals/history?limit=15&compact=1', { headers: getAuthHeaders() });
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      if (!res.ok) {
        container.innerHTML = '<div class="p-space-lg rounded-xl bg-surface-container-low/70 font-label-code text-label-code text-error">Sinyaller yüklenemedi.</div>';
        return;
      }
      const data = await res.json();
      signalsData = Array.isArray(data.signals) ? data.signals : [];
      if (!signalsData.length) {
        container.innerHTML = '<div class="p-space-lg rounded-xl bg-surface-container-low/70 font-label-code text-label-code text-outline">Kayıtlı sinyal yok.</div>';
        updateFilterCounts();
        return;
      }
      container.innerHTML = signalsData.map(renderSignalCard).join('');
      updateFilterCounts();
      container.querySelectorAll('.signal-card').forEach(card => {
        card.onclick = function () { selectCard(this); };
      });
      const first = container.querySelector('.signal-card');
      if (first) selectCard(first);
    } catch (err) {
      console.warn('[bistbot] signals stream hydration failed', err);
    }
  }

  function riskReward(kind, entry, stop, target) {
    if (![entry, stop, target].every(Number.isFinite)) return NaN;
    const risk = kind === 'sell' ? stop - entry : entry - stop;
    const reward = kind === 'sell' ? entry - target : target - entry;
    return risk > 0 && reward > 0 ? reward / risk : NaN;
  }

  function renderReasonItems(reasons, compactGrid) {
    if (!reasons.length) return '<div class="font-label-code text-label-code text-outline">Gerekçe kaydı yok.</div>';
    return reasons.map(r => (
      `<div class="flex items-start gap-space-xs bg-surface-container p-space-xs rounded-lg${compactGrid ? '' : ' hover:bg-surface-container-high transition-colors'}">` +
      '<span class="material-symbols-outlined text-primary text-[18px] shrink-0 mt-0.5">check_circle</span>' +
      `<span class="font-body-sm text-body-sm text-on-surface">${escapeHtml(r)}</span></div>`
    )).join('');
  }

  function showSignalDetail(sig) {
    if (!sig) return;
    currentSignal = sig;
    const kind = signalRowKind(sig.signal_type);
    const entry = num(sig.price);
    const stop = positive(sig.stop_loss);
    const target = positive(sig.target_price);
    const score = Math.round(num(sig.score));
    const reasons = Array.isArray(sig.reasons) ? sig.reasons : [];

    setText('active-symbol-title', sig.ticker);
    setText('active-signal-type', signalTypeLabel(sig.signal_type));
    setText('active-symbol-name', String(sig.ticker || '').replace(/\.IS$/i, ''));
    setText('current-score-val', Number.isFinite(score) ? (score > 0 ? '+' : '') + score : DASH);
    setText('current-score-sub', CONFIDENCE_LABELS[sig.confidence] ? `${CONFIDENCE_LABELS[sig.confidence]} güven` : '');
    setText('current-stop-val', tl(stop));
    setText('current-target-val', tl(target));
    setText('current-stop-pct', signedPct(pctFrom(entry, stop)) || ' ');
    setText('current-target-pct', signedPct(pctFrom(entry, target)) || ' ');
    setText('current-price-val', tl(entry));
    setText('current-price-pct', 'sinyal fiyatı');

    setText('signal-time', fmtDateTime(sig.timestamp));
    setText('signal-entry', tl(entry));
    setText('signal-confidence', CONFIDENCE_LABELS[sig.confidence] || DASH);
    const size = Math.floor(num(sig.position_size));
    setText('signal-size', size > 0 ? `${size.toLocaleString('tr-TR')} lot (${tl(size * entry, 0)})` : DASH);
    const rr = riskReward(kind, entry, stop, target);
    setText('current-rr-val', Number.isFinite(rr) ? `1 : ${rr.toFixed(2)}` : DASH);
    const outcome = String(sig.outcome || 'PENDING').toUpperCase();
    setText('signal-outcome', OUTCOME_LABELS[outcome] || outcome);

    setText('signal-reasons-count', `${reasons.length} gerekçe`);
    setHtml('signal-reasons-list', renderReasonItems(reasons, false));

    setText('signals-tp-legend', Number.isFinite(target) ? `Hedef: ${tl(target)}` : 'Hedef: —');
    setText('signals-sl-legend', Number.isFinite(stop) ? `Stop: ${tl(stop)}` : 'Stop: —');
    loadSignalChart();
  }

  async function loadSignalChart() {
    if (!currentSignal) return;
    const cleanTicker = String(currentSignal.ticker || '').replace(/\.IS$/i, '') + '.IS';
    const requested = cleanTicker + '|' + currentSignalTimeframe;
    try {
      const url = `/api/analyze/${encodeURIComponent(cleanTicker)}?interval=${encodeURIComponent(currentSignalTimeframe)}&bars=30&compact=1`;
      const res = await fetch(url, { headers: getAuthHeaders() });
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if (!data || data.status !== 'ok') throw new Error('bad payload');
      // Ignore late answers for a card/timeframe the user already left.
      if (requested !== String(currentSignal.ticker || '').replace(/\.IS$/i, '') + '.IS|' + currentSignalTimeframe) return;
      applySignalChart(data);
    } catch (err) {
      console.warn('[bistbot] signal chart load failed for ' + cleanTicker, err);
      const svg = document.getElementById('signalsChartSvg');
      if (svg) svg.innerHTML = '';
      const empty = document.getElementById('signals-chart-empty');
      if (empty) {
        empty.textContent = 'Grafik verisi alınamadı.';
        empty.classList.remove('hidden');
      }
    }
  }

  function applySignalChart(data) {
    const sig = currentSignal || {};
    const bars = Array.isArray(data.price_data) ? data.price_data.slice(-30) : [];
    const ind = data.indicators || {};
    const tf = data.timeframe || {};
    const last = bars.length ? bars[bars.length - 1] : null;
    const entry = num(sig.price);

    if (data.name) setText('active-symbol-name', data.name);
    if (last) {
      setText('current-price-val', tl(last.close));
      const diff = pctFrom(entry, last.close);
      setText('current-price-pct', Number.isFinite(diff) ? `sinyale göre ${signedPct(diff)}` : ' ');
      setText('signals-last-bar', `Son mum: ${fmtBarLabel(last.label || last.date, true)}`);
      setText('signals-sma-fast-label', Number.isFinite(num(last.sma_fast)) ? `SMA ${ind.sma_fast_period || ''} (${Number(last.sma_fast).toFixed(2)})` : `SMA ${ind.sma_fast_period || ''}`);
      setText('signals-sma-slow-label', Number.isFinite(num(last.sma_slow)) ? `SMA ${ind.sma_slow_period || ''} (${Number(last.sma_slow).toFixed(2)})` : `SMA ${ind.sma_slow_period || ''}`);
    }
    renderSignalsChart(bars, { stop: positive(sig.stop_loss), target: positive(sig.target_price) });
    renderAxisLabels('signals-x-axis', bars, !!tf.intraday, 6);
  }

  function renderSignalsChart(data, levels) {
    const svg = document.getElementById('signalsChartSvg');
    const empty = document.getElementById('signals-chart-empty');
    if (!svg) return;
    if (!Array.isArray(data) || data.length < 2) {
      svg.innerHTML = '';
      if (empty) {
        empty.textContent = 'Bu periyot için yeterli fiyat verisi yok.';
        empty.classList.remove('hidden');
      }
      return;
    }
    if (empty) empty.classList.add('hidden');
    const highs = data.map(d => num(d.high)).filter(Number.isFinite);
    const lows = data.map(d => num(d.low)).filter(Number.isFinite);
    if (!highs.length || !lows.length) return;

    let yMin = Math.min(...lows);
    let yMax = Math.max(...highs);
    const stop = levels ? num(levels.stop) : NaN;
    const target = levels ? num(levels.target) : NaN;
    if (Number.isFinite(stop)) { yMin = Math.min(yMin, stop); yMax = Math.max(yMax, stop); }
    if (Number.isFinite(target)) { yMin = Math.min(yMin, target); yMax = Math.max(yMax, target); }
    const padding = (yMax - yMin) * 0.08 || 1.0;
    yMin = Math.max(0, yMin - padding);
    yMax = yMax + padding;
    const range = yMax - yMin || 1;

    const W = 640;
    const candleTop = 8;
    const candleBottom = 188;
    const candleH = candleBottom - candleTop;
    const volTop = 196;
    const volBottom = 236;
    const volH = volBottom - volTop;
    const getY = (v) => candleBottom - ((v - yMin) / range) * candleH;

    // TP/SL overlays sit in the candle band (top 188 of 240 viewBox units).
    const placeLine = (id, labelId, value, prefix) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (!Number.isFinite(value)) {
        el.classList.add('hidden');
        return;
      }
      el.classList.remove('hidden');
      el.style.top = ((getY(value) / 240) * 100).toFixed(1) + '%';
      setText(labelId, `${prefix} ${value.toFixed(2)}`);
    };
    placeLine('signals-tp-line', 'signals-tp-label', target, 'TP');
    placeLine('signals-sl-line', 'signals-sl-label', stop, 'SL');

    const stepX = W / data.length;
    const barW = Math.max(4, Math.min(10, stepX * 0.5));
    const volumes = data.map(d => num(d.volume)).filter(v => Number.isFinite(v) && v > 0);
    const maxVol = volumes.length ? Math.max(...volumes) : 1;

    let html = '';
    const fastPts = [];
    const slowPts = [];
    data.forEach((d, idx) => {
      const cx = (idx + 0.5) * stepX;
      const o = num(d.open);
      const h = num(d.high);
      const l = num(d.low);
      const c = num(d.close);
      if (![o, h, l, c].every(Number.isFinite)) return;
      const color = c >= o ? '#4edea3' : '#ffb4ab';
      const bodyTop = Math.min(getY(o), getY(c)).toFixed(1);
      const bodyH = Math.max(2, Math.abs(getY(c) - getY(o))).toFixed(1);
      const x = (cx - barW / 2).toFixed(1);
      html += `<line x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${getY(h).toFixed(1)}" y2="${getY(l).toFixed(1)}" stroke="${color}" stroke-width="1.5" />`;
      html += `<rect x="${x}" y="${bodyTop}" width="${barW.toFixed(1)}" height="${bodyH}" fill="${color}" />`;
      const vol = num(d.volume);
      if (Number.isFinite(vol) && vol > 0) {
        const vh = Math.max(3, (vol / maxVol) * volH);
        html += `<rect x="${x}" y="${(volBottom - vh).toFixed(1)}" width="${barW.toFixed(1)}" height="${vh.toFixed(1)}" fill="${color}" opacity="0.45" />`;
      }
      if (Number.isFinite(num(d.sma_fast))) fastPts.push(cx.toFixed(1) + ',' + getY(num(d.sma_fast)).toFixed(1));
      if (Number.isFinite(num(d.sma_slow))) slowPts.push(cx.toFixed(1) + ',' + getY(num(d.sma_slow)).toFixed(1));
    });
    if (slowPts.length > 1) html += `<path d="M ${slowPts.join(' L ')}" fill="none" opacity="0.6" stroke="#dcfdff" stroke-width="2" />`;
    if (fastPts.length > 1) html += `<path d="M ${fastPts.join(' L ')}" fill="none" opacity="0.9" stroke="#7bd0ff" stroke-width="2" />`;
    svg.innerHTML = html;
  }

  async function initSignals() {
    const [, cfg] = await Promise.all([fetchStats(false), fetchConfig()]);
    const scan = (lastStats && lastStats.latest_scan) || {};
    setText('sig-count-scanned', scan.timestamp ? scan.total_scanned : DASH);
    setText('sig-last-scan', scan.timestamp ? `Son tarama: ${fmtDateTime(scan.timestamp)}.` : '');
    if (cfg) {
      setText('sig-tf-info', `Tetik: ${INTERVAL_LABELS[cfg.trigger_interval] || cfg.trigger_interval} · Trend: ${INTERVAL_LABELS[cfg.trend_interval] || cfg.trend_interval}`);
    }
    await hydrateSignalsStream();

    // Signal-type ribbon
    const filterTabs = document.querySelectorAll('button.filter-tab[data-filter]');
    const TAB_ON = 'filter-tab active-tab bg-primary text-on-primary font-label-code text-label-code px-space-sm py-space-2xs rounded-full shadow-[0_0_16px_rgba(78,222,163,0.35)] transition-all flex items-center gap-1.5 cursor-pointer font-bold';
    const TAB_OFF = 'filter-tab bg-surface-container hover:bg-surface-container-high text-on-surface-variant hover:text-on-surface font-label-code text-label-code px-space-sm py-space-2xs rounded-full shadow-sm transition-all flex items-center gap-1.5 cursor-pointer';
    filterTabs.forEach(tab => {
      tab.onclick = function () {
        filterTabs.forEach(t => { t.className = TAB_OFF; });
        this.className = TAB_ON;
        signalFilterState.tab = this.dataset.filter || 'all';
        applySignalFilters();
      };
    });

    // Timeframe buttons
    const TF_ON = 'timeframe-btn px-space-xs py-space-3xs rounded bg-surface-container-highest text-primary font-bold';
    const TF_OFF = 'timeframe-btn px-space-xs py-space-3xs rounded text-on-surface-variant hover:text-on-surface';
    const tfButtons = document.querySelectorAll('#signals-tf-group button[data-tf]');
    tfButtons.forEach(btn => {
      btn.onclick = function () {
        tfButtons.forEach(b => { b.className = TF_OFF; });
        this.className = TF_ON;
        currentSignalTimeframe = this.dataset.tf;
        loadSignalChart();
      };
    });

    // Filter modal
    const filterModal = document.getElementById('filter-modal');
    const scoreSlider = document.getElementById('score-slider');
    const rsiSlider = document.getElementById('rsi-slider');
    const levelsBox = document.getElementById('filter-has-levels');
    const syncLabels = () => {
      if (scoreSlider) setText('filter-score-label', '+' + scoreSlider.value);
      if (rsiSlider) setText('filter-rsi-label', rsiSlider.value);
    };
    const closeModal = () => filterModal && filterModal.classList.add('opacity-0', 'pointer-events-none');
    const openBtn = document.getElementById('open-filter-modal-btn');
    if (openBtn && filterModal) openBtn.onclick = () => filterModal.classList.remove('opacity-0', 'pointer-events-none');
    const closeBtn = document.getElementById('close-filter-modal-btn');
    if (closeBtn) closeBtn.onclick = closeModal;
    if (scoreSlider) scoreSlider.oninput = syncLabels;
    if (rsiSlider) rsiSlider.oninput = syncLabels;
    const applyBtn = document.getElementById('apply-filter-btn');
    if (applyBtn) {
      applyBtn.onclick = () => {
        signalFilterState.minScore = Number(scoreSlider ? scoreSlider.value : 0);
        signalFilterState.maxRsi = Number(rsiSlider ? rsiSlider.value : 100);
        signalFilterState.hasLevels = !!(levelsBox && levelsBox.checked);
        closeModal();
        showToast(`Filtre uygulandı: ${applySignalFilters()} sinyal gösteriliyor.`, 'success', 2500);
      };
    }
    const resetBtn = document.getElementById('reset-filter-btn');
    if (resetBtn) {
      resetBtn.onclick = () => {
        if (scoreSlider) scoreSlider.value = '0';
        if (rsiSlider) rsiSlider.value = '100';
        if (levelsBox) levelsBox.checked = false;
        syncLabels();
        Object.assign(signalFilterState, { minScore: 0, maxRsi: 100, hasLevels: false });
        closeModal();
        showToast(`Filtreler sıfırlandı: ${applySignalFilters()} sinyal gösteriliyor.`, 'info', 2000);
      };
    }
  }

  // -------------------------------------------------------------------------
  // Analysis page: /api/analyze for one ticker + timeframe
  // -------------------------------------------------------------------------
  let chartShowCandles = true;
  let chartShowEMA = true;
  let chartShowBollinger = false;
  let lastAnalysisBars = [];

  // Bollinger Bands from close prices (period 20, ±2σ), aligned with `data`
  function computeBollinger(closes, period, mult) {
    const up = [];
    const lo = [];
    for (let i = 0; i < closes.length; i++) {
      if (i + 1 < period || !closes.slice(i + 1 - period, i + 1).every(Number.isFinite)) {
        up.push(null);
        lo.push(null);
        continue;
      }
      const win = closes.slice(i + 1 - period, i + 1);
      const mean = win.reduce((a, b) => a + b, 0) / period;
      const sd = Math.sqrt(win.reduce((a, b) => a + (b - mean) * (b - mean), 0) / period);
      up.push(mean + mult * sd);
      lo.push(mean - mult * sd);
    }
    return { up: up, lo: lo };
  }

  window.renderCandlestickChart = function (priceData, opts) {
    const svg = document.getElementById('candlestickSvg');
    if (!svg) return;
    if (!Array.isArray(priceData) || priceData.length < 2) {
      svg.innerHTML = '<text x="400" y="160" fill="#86948a" font-family="JetBrains Mono" font-size="14" text-anchor="middle">Bu periyot için yeterli fiyat verisi yok</text>';
      return;
    }
    const show = Object.assign({ candles: true, ema: true, bollinger: false }, opts || {});
    const data = priceData.slice(-30);
    lastAnalysisBars = data;
    const closes = data.map(d => num(d.close));
    const band = computeBollinger(closes, 20, 2);
    const highs = data.map(d => num(d.high)).filter(Number.isFinite);
    const lows = data.map(d => num(d.low)).filter(Number.isFinite);
    const bandVals = show.bollinger ? band.up.concat(band.lo).filter(v => Number.isFinite(v)) : [];
    if (!highs.length || !lows.length) return;

    const minPrice = Math.min(Math.min(...lows), ...(bandVals.length ? [Math.min(...bandVals)] : [Infinity]));
    const maxPrice = Math.max(Math.max(...highs), ...(bandVals.length ? [Math.max(...bandVals)] : [-Infinity]));
    const padding = (maxPrice - minPrice) * 0.08 || 1.0;
    const yMin = Math.max(0, minPrice - padding);
    const yMax = maxPrice + padding;
    const priceRange = yMax - yMin;

    for (let i = 0; i <= 4; i++) {
      const p = yMin + (priceRange * (i / 4));
      const elL = document.getElementById(`grid-p${i}`);
      const elR = document.getElementById(`grid-p${i}-r`);
      if (elL) elL.textContent = '₺' + p.toFixed(2);
      if (elR) elR.textContent = p.toFixed(2);
    }

    const W = 800;
    const H = 320;
    const chartBottom = H - 20;
    const chartTop = 20;
    const chartH = chartBottom - chartTop;
    const getY = (val) => chartBottom - ((val - yMin) / priceRange) * chartH;
    const barW = Math.max(6, Math.min(18, (W / data.length) * 0.55));
    const stepX = W / data.length;

    let barsHtml = '';
    const smaFastPoints = [];
    const smaSlowPoints = [];
    const bollUpPoints = [];
    const bollLoPoints = [];

    data.forEach((d, idx) => {
      const cx = (idx + 0.5) * stepX;
      const o = num(d.open);
      const h = num(d.high);
      const l = num(d.low);
      const c = num(d.close);
      if ([o, h, l, c].every(Number.isFinite)) {
        const color = c >= o ? '#4edea3' : '#ffb4ab';
        const bodyTop = Math.min(getY(o), getY(c));
        const bodyH = Math.max(2, Math.abs(getY(c) - getY(o)));
        barsHtml += `<line x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${getY(h).toFixed(1)}" y2="${getY(l).toFixed(1)}" stroke="${color}" stroke-width="1.5" />`;
        barsHtml += `<rect x="${(cx - barW / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${barW.toFixed(1)}" height="${bodyH.toFixed(1)}" rx="1.5" fill="${color}" />`;
      }
      if (Number.isFinite(num(d.sma_fast))) smaFastPoints.push(`${cx.toFixed(1)},${getY(num(d.sma_fast)).toFixed(1)}`);
      if (Number.isFinite(num(d.sma_slow))) smaSlowPoints.push(`${cx.toFixed(1)},${getY(num(d.sma_slow)).toFixed(1)}`);
      if (Number.isFinite(band.up[idx])) bollUpPoints.push(`${cx.toFixed(1)},${getY(band.up[idx]).toFixed(1)}`);
      if (Number.isFinite(band.lo[idx])) bollLoPoints.push(`${cx.toFixed(1)},${getY(band.lo[idx]).toFixed(1)}`);
    });

    let smaHtml = '';
    if (show.ema && smaFastPoints.length > 1) {
      smaHtml += `<polyline points="${smaFastPoints.join(' ')}" fill="none" stroke="#7bd0ff" stroke-width="2" stroke-linecap="round" />`;
    }
    if (show.ema && smaSlowPoints.length > 1) {
      smaHtml += `<polyline points="${smaSlowPoints.join(' ')}" fill="none" stroke="#dcfdff" stroke-width="1.5" stroke-dasharray="4,4" stroke-linecap="round" />`;
    }
    let bollHtml = '';
    if (show.bollinger && bollUpPoints.length > 1 && bollLoPoints.length > 1) {
      const loReversed = bollLoPoints.slice().reverse();
      bollHtml += `<polygon points="${bollUpPoints.join(' ')} ${loReversed.join(' ')}" fill="#dcfdff" opacity="0.08" />`;
      bollHtml += `<polyline points="${bollUpPoints.join(' ')}" fill="none" stroke="#dcfdff" stroke-width="1.5" stroke-dasharray="3,3" />`;
      bollHtml += `<polyline points="${bollLoPoints.join(' ')}" fill="none" stroke="#dcfdff" stroke-width="1.5" stroke-dasharray="3,3" />`;
    }
    svg.innerHTML = `${bollHtml}${smaHtml}${show.candles ? barsHtml : ''}`;
  };

  function currentChartOpts() {
    return { candles: chartShowCandles, ema: chartShowEMA, bollinger: chartShowBollinger };
  }

  function rerenderAnalysisChart() {
    if (lastAnalysisBars.length >= 2) {
      window.renderCandlestickChart(lastAnalysisBars, currentChartOpts());
    }
  }

  function renderRsiChart(bars, oversold, overbought) {
    const svg = document.getElementById('analysis-rsi-svg');
    if (!svg) return;
    const W = 600;
    const H = 48;
    const y = (v) => H - (v / 100) * H;
    const vals = bars.map(b => num(b.rsi));
    const pts = [];
    vals.forEach((v, i) => {
      if (Number.isFinite(v)) pts.push(`${((i + 0.5) * (W / vals.length)).toFixed(1)},${y(v).toFixed(1)}`);
    });
    svg.innerHTML =
      `<line stroke="#3c4a42" stroke-dasharray="2,4" x1="0" x2="${W}" y1="${y(overbought).toFixed(1)}" y2="${y(overbought).toFixed(1)}"></line>` +
      `<line stroke="#3c4a42" stroke-dasharray="2,4" x1="0" x2="${W}" y1="${y(oversold).toFixed(1)}" y2="${y(oversold).toFixed(1)}"></line>` +
      (pts.length > 1 ? `<polyline points="${pts.join(' ')}" fill="none" stroke="#4edea3" stroke-width="2"></polyline>` : '');
  }

  const CROSS_LABELS = {
    GOLDEN_CROSS: 'Altın kesişim', DEATH_CROSS: 'Ölüm kesişimi', BULLISH: 'Yükseliş', BEARISH: 'Düşüş',
    NONE: 'Yok', MIDDLE: 'Bant içi', ABOVE_UPPER: 'Üst bant üstü', BELOW_LOWER: 'Alt bant altı'
  };

  function indicatorRow(label, value) {
    return `<div class="bb-setting-row"><span class="text-outline">${escapeHtml(label)}</span>` +
      `<span class="text-on-surface font-semibold">${escapeHtml(value)}</span></div>`;
  }

  function renderIndicators(snap, close, intervalLabel) {
    setText('analysis-indicators-tf', intervalLabel);
    const atr = num(snap.atr);
    const atrPct = Number.isFinite(atr) && close > 0 ? ` (%${((atr / close) * 100).toFixed(1)})` : '';
    const label = (v) => CROSS_LABELS[String(v || '').toUpperCase()] || (v ? String(v) : DASH);
    setHtml('analysis-indicators', [
      indicatorRow('RSI', Number.isFinite(num(snap.rsi)) ? Number(snap.rsi).toFixed(1) : DASH),
      indicatorRow('ADX (trend gücü)', Number.isFinite(num(snap.adx)) ? Number(snap.adx).toFixed(1) : DASH),
      indicatorRow('ATR (oynaklık)', Number.isFinite(atr) ? `${tl(atr)}${atrPct}` : DASH),
      indicatorRow('Hacim / 20 mum ort.', Number.isFinite(num(snap.volume_ratio)) ? `${Number(snap.volume_ratio).toFixed(2)}x` : DASH),
      indicatorRow('MACD kesişimi', label(snap.macd_cross)),
      indicatorRow('SMA kesişimi', label(snap.sma_cross)),
      indicatorRow('EMA kesişimi', label(snap.ema_cross)),
      indicatorRow('Bollinger konumu', label(snap.bb_position)),
      indicatorRow('Stokastik %K', Number.isFinite(num(snap.stoch_k)) ? Number(snap.stoch_k).toFixed(1) : DASH)
    ].join(''));
  }

  function renderPivots(pivots, close) {
    ['r2', 'r1', 'pp', 's1', 's2'].forEach(k => {
      const v = pivots ? num(pivots[k]) : NaN;
      setText(`pivot-${k}-val`, tl(v));
      setText(`pivot-${k}-pct`, signedPct(pctFrom(close, v)) || ' ');
    });
    if (pivots && pivots.basis_date) {
      const [y, m, d] = String(pivots.basis_date).split('-');
      setText('pivot-basis', `Klasik pivot · ${d}.${m}.${y} bazlı`);
    } else {
      setText('pivot-basis', 'Klasik pivot · veri yok');
    }
  }

  function renderPosition(sig, close) {
    const size = Math.floor(num(sig.position_size));
    const entry = positive(sig.price) || close;
    const stop = positive(sig.stop_loss);
    const target = positive(sig.target);
    const kind = signalRowKind(sig.type);
    const hasSignal = sig.type && sig.type !== 'N/A';
    if (!hasSignal || !(size > 0) || !Number.isFinite(stop) || !Number.isFinite(target)) {
      setText('pos-size', DASH);
      setText('pos-risk', DASH);
      setText('pos-reward', DASH);
      setText('pos-rr', 'R:R —');
      setText('pos-note', hasSignal
        ? 'Motor bu sinyal için pozisyon büyüklüğü önermedi.'
        : 'Bu periyotta sinyal yok; pozisyon önerisi hesaplanmaz.');
      return;
    }
    const risk = Math.abs(entry - stop) * size;
    const reward = Math.abs(target - entry) * size;
    const cost = size * entry;
    setText('pos-size', `${size.toLocaleString('tr-TR')} lot (${tl(cost, 0)})`);
    setText('pos-risk', `${tl(risk, 0)} (%${((risk / cost) * 100).toFixed(2)})`);
    setText('pos-reward', `${tl(reward, 0)} (%${((reward / cost) * 100).toFixed(2)})`);
    const rr = riskReward(kind, entry, stop, target);
    setText('pos-rr', Number.isFinite(rr) ? `R:R = 1:${rr.toFixed(2)}` : 'R:R —');
    setText('pos-note', 'Motorun bu periyottaki sinyaline göre hesaplanır; yatırım tavsiyesi değildir.');
  }

  let currentActiveAnalysisTicker = 'THYAO';
  let currentActiveAnalysisTimeframe = '1d';
  let analysisRequestSeq = 0;

  window.runAnalysis = async function (ticker, timeframe) {
    if (ticker) currentActiveAnalysisTicker = String(ticker).replace(/\.IS$/i, '').toUpperCase();
    if (timeframe) currentActiveAnalysisTimeframe = timeframe;
    const cleanTicker = currentActiveAnalysisTicker + '.IS';
    const seq = ++analysisRequestSeq;

    document.querySelectorAll('.ticker-chip').forEach(c => {
      c.className = c.getAttribute('data-ticker') === currentActiveAnalysisTicker
        ? 'ticker-chip px-space-sm py-1 rounded bg-surface-container-high text-primary font-label-code text-label-code hover:bg-primary hover:text-on-primary transition-all cursor-pointer font-bold shadow-sm'
        : 'ticker-chip px-space-sm py-1 rounded bg-surface-container text-on-surface-variant font-label-code text-label-code hover:bg-surface-container-high transition-all cursor-pointer';
    });

    // Uncached or unknown tickers can take a while at the data provider.
    const slowNotice = setTimeout(() => {
      if (seq === analysisRequestSeq) showToast(`${cleanTicker} verisi yükleniyor...`, 'info', 2500);
    }, 1500);
    try {
      const url = `/api/analyze/${encodeURIComponent(cleanTicker)}?interval=${encodeURIComponent(currentActiveAnalysisTimeframe)}&bars=30&compact=1`;
      const res = await fetch(url, { headers: getAuthHeaders() });
      clearTimeout(slowNotice);
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (seq !== analysisRequestSeq) return; // a newer request superseded this one
      if (!res.ok || data.status !== 'ok') {
        showToast(`${cleanTicker} için analiz verisi alınamadı${data.message ? ': ' + data.message : ''}.`, 'error', 3500);
        return;
      }
      applyAnalysis(data);
    } catch (e) {
      clearTimeout(slowNotice);
      if (seq === analysisRequestSeq) showToast(`${cleanTicker} analizi yüklenemedi. Bağlantıyı kontrol edin.`, 'error', 3500);
    }
  };

  function applyAnalysis(data) {
    const snap = data.snapshot || {};
    const sig = data.signal || {};
    const ind = data.indicators || {};
    const tf = data.timeframe || {};
    const bars = Array.isArray(data.price_data) ? data.price_data.slice(-30) : [];
    const last = bars.length ? bars[bars.length - 1] : null;
    const cleanName = String(data.ticker || '').replace(/\.IS$/i, '');
    const close = num(snap.close) || (last ? num(last.close) : NaN);
    const intervalLabel = INTERVAL_LABELS[tf.interval] || tf.interval || '';
    const hasSignal = sig.type && sig.type !== 'N/A';

    setText('asset-avatar', cleanName.slice(0, 3));
    setText('asset-ticker-title', data.ticker);
    setText('asset-company-name', data.name && data.name !== data.ticker ? data.name : cleanName);
    setText('asset-signal-text', hasSignal ? signalTypeLabel(sig.type) : 'Sinyal yok');
    setText('asset-current-price', tl(close));
    const chg = num(snap.change_pct);
    const chgEl = document.getElementById('asset-price-change');
    if (chgEl) {
      chgEl.textContent = Number.isFinite(chg) ? `${signedPct(chg)} (son mum)` : '';
      chgEl.className = `font-metric-value text-metric-value flex items-center ${chg >= 0 ? 'text-primary' : 'text-error'}`;
    }
    setText('asset-last-bar', last ? `Son mum: ${fmtBarLabel(last.label || last.date, true)} · ${intervalLabel}` : DASH);
    const session = data.session || null;
    if (session) {
      const [y, m, d] = String(session.date || '').split('-');
      setText('asset-range-label', tf.interval === '1wk' ? 'Haftalık Aralık' : `Gün Aralığı (${d}.${m})`);
      setText('asset-day-range', `${tl(session.low)} - ${tl(session.high)}`);
    }

    const score = num(sig.score);
    setText('asset-algo-score', hasSignal && Number.isFinite(score) ? (score > 0 ? '+' : '') + Math.round(score) : DASH);
    setText('asset-conf-label', hasSignal ? `${intervalLabel} · ${CONFIDENCE_LABELS[sig.confidence] || ''} güven` : `${intervalLabel} periyotta sinyal yok`);
    const stop = positive(sig.stop_loss);
    const target = positive(sig.target);
    setText('asset-stop-loss', tl(stop));
    setText('asset-stop-pct', Number.isFinite(stop) ? signedPct(pctFrom(close, stop)) : 'Sinyal yok');
    setText('asset-target-price', tl(target));
    setText('asset-target-pct', Number.isFinite(target) ? signedPct(pctFrom(close, target)) : 'Sinyal yok');
    const oversold = num(ind.rsi_oversold) || 30;
    const overbought = num(ind.rsi_overbought) || 70;
    const rsi = num(snap.rsi);
    setText('asset-rsi-period', ind.rsi_period || 14);
    setText('asset-rsi-val', Number.isFinite(rsi) ? rsi.toFixed(1) : DASH);
    setText('asset-rsi-label', rsiZoneLabel(rsi, oversold, overbought) || DASH);

    const title = document.getElementById('asset-chart-title');
    if (title) title.innerHTML = `<span class="w-2 h-2 rounded-full bg-primary"></span> ${escapeHtml(cleanName)} · ${escapeHtml(intervalLabel)}`;
    setText('asset-sma-fast', last && Number.isFinite(num(last.sma_fast)) ? `SMA(${ind.sma_fast_period}): ${Number(last.sma_fast).toFixed(2)}` : `SMA(${ind.sma_fast_period || ''}): ${DASH}`);
    setText('asset-sma-slow', last && Number.isFinite(num(last.sma_slow)) ? `SMA(${ind.sma_slow_period}): ${Number(last.sma_slow).toFixed(2)}` : `SMA(${ind.sma_slow_period || ''}): ${DASH}`);
    setText('asset-ema-long', Number.isFinite(num(ind.ema_long)) ? `EMA(${ind.ema_long_period}): ${Number(ind.ema_long).toFixed(2)}` : `EMA(${ind.ema_long_period || 200}): yetersiz veri`);

    window.renderCandlestickChart(bars, currentChartOpts());
    renderAxisLabels('analysis-x-axis', bars, !!tf.intraday, 5);

    setText('analysis-rsi-title', `RSI(${ind.rsi_period || 14}):`);
    setText('analysis-rsi-val', Number.isFinite(rsi) ? rsi.toFixed(1) : DASH);
    setText('analysis-rsi-status', rsiZoneLabel(rsi, oversold, overbought) ? `(${rsiZoneLabel(rsi, oversold, overbought)})` : ' ');
    setText('analysis-rsi-bounds', `Aşırı satım: ${oversold} • Aşırı alım: ${overbought}`);
    renderRsiChart(bars, oversold, overbought);

    const reasons = Array.isArray(sig.reasons) ? sig.reasons : [];
    setText('analysis-reasons-count', hasSignal ? `${reasons.length} gerekçe · ${intervalLabel}` : `${intervalLabel} periyotta sinyal yok`);
    setHtml('analysis-reasons-list', hasSignal
      ? renderReasonItems(reasons, true)
      : '<div class="font-label-code text-label-code text-outline">Motor bu periyotta sinyal üretmedi.</div>');

    renderIndicators(snap, close, intervalLabel);
    renderPivots(data.pivots, close);
    renderPosition(sig, close);
  }

  function initAnalysis() {
    const analyzeBtn = document.getElementById('asset-analyze-btn');
    const searchInput = document.getElementById('asset-search-input');

    function triggerSearch() {
      const raw = (searchInput && searchInput.value || 'THYAO').trim();
      const match = raw.match(/^[A-Za-z0-9]+/);
      window.runAnalysis(match ? match[0].toUpperCase() : 'THYAO');
    }
    if (analyzeBtn) {
      analyzeBtn.onclick = (e) => {
        e.preventDefault();
        triggerSearch();
      };
    }
    if (searchInput) {
      searchInput.onkeydown = (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          triggerSearch();
        }
      };
    }

    const TF_ON = 'analysis-tf-btn px-space-sm py-1.5 rounded font-label-code text-label-code bg-surface-container-high text-primary font-semibold shadow-sm';
    const TF_OFF = 'analysis-tf-btn px-space-sm py-1.5 rounded font-label-code text-label-code text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors';
    const tfBtns = document.querySelectorAll('#analysis-tf-group button[data-tf]');
    tfBtns.forEach(btn => {
      btn.onclick = function () {
        tfBtns.forEach(b => { b.className = TF_OFF; });
        this.className = TF_ON;
        window.runAnalysis(currentActiveAnalysisTicker, this.dataset.tf);
      };
    });

    // Indicator chart toggles: Mum Grafiği, SMA, Bollinger (real re-render)
    const BTN_ON = 'px-space-xs py-1 rounded text-primary font-label-code text-label-code bg-surface-container-high flex items-center gap-1 cursor-pointer';
    const BTN_OFF = 'px-space-xs py-1 rounded text-on-surface-variant hover:text-on-surface font-label-code text-label-code bg-surface-container flex items-center gap-1 cursor-pointer';
    function syncChartToggleButtons() {
      [['chart-btn-candles', chartShowCandles], ['chart-btn-ema', chartShowEMA], ['chart-btn-bollinger', chartShowBollinger]]
        .forEach(([id, on]) => {
          const b = document.getElementById(id);
          if (b) b.className = on ? BTN_ON : BTN_OFF;
        });
    }
    function wireChartToggle(id, get, set) {
      const b = document.getElementById(id);
      if (!b) return;
      b.onclick = function () {
        set(!get());
        syncChartToggleButtons();
        rerenderAnalysisChart();
      };
    }
    wireChartToggle('chart-btn-candles', () => chartShowCandles, v => { chartShowCandles = v; });
    wireChartToggle('chart-btn-ema', () => chartShowEMA, v => { chartShowEMA = v; });
    wireChartToggle('chart-btn-bollinger', () => chartShowBollinger, v => { chartShowBollinger = v; });
    syncChartToggleButtons();

    // Fullscreen: native API with fixed-overlay fallback
    const fsBtn = document.getElementById('chart-btn-fullscreen');
    const chartShell = document.getElementById('analysis-chart-shell');
    let fsFallbackOn = false;
    function setFsFallback(on) {
      fsFallbackOn = on;
      if (!chartShell) return;
      chartShell.style.position = on ? 'fixed' : '';
      chartShell.style.inset = on ? '0' : '';
      chartShell.style.zIndex = on ? '9990' : '';
      chartShell.style.overflow = on ? 'auto' : '';
      chartShell.style.borderRadius = on ? '0' : '';
      const icon = fsBtn ? fsBtn.querySelector('.material-symbols-outlined') : null;
      const active = on || !!document.fullscreenElement;
      if (icon) icon.textContent = active ? 'fullscreen_exit' : 'fullscreen';
      if (fsBtn) fsBtn.classList.toggle('text-primary', active);
    }
    if (fsBtn && chartShell) {
      fsBtn.onclick = async function () {
        if (document.fullscreenElement) {
          try { await document.exitFullscreen(); } catch (e) { /* ignore */ }
          setFsFallback(false);
          return;
        }
        if (fsFallbackOn) {
          setFsFallback(false);
          return;
        }
        try {
          if (chartShell.requestFullscreen) {
            await chartShell.requestFullscreen();
          } else {
            setFsFallback(true);
          }
        } catch (e) {
          setFsFallback(true);
        }
      };
      document.addEventListener('fullscreenchange', () => {
        if (!document.fullscreenElement) setFsFallback(false);
        const icon = fsBtn.querySelector('.material-symbols-outlined');
        if (icon) icon.textContent = document.fullscreenElement ? 'fullscreen_exit' : 'fullscreen';
      });
    }

    // CSP-safe delegation for ticker chip clicks (was inline onclick)
    document.addEventListener('click', function (e) {
      const chip = e.target.closest('.ticker-chip[data-ticker]');
      if (chip) {
        e.preventDefault();
        if (searchInput) searchInput.value = chip.getAttribute('data-ticker');
        window.runAnalysis(chip.getAttribute('data-ticker'));
      }
    });

    window.runAnalysis('THYAO');
  }

  // -------------------------------------------------------------------------
  // Settings page: read-only view of the live scanner configuration
  // -------------------------------------------------------------------------
  async function initSettings() {
    const [, cfg] = await Promise.all([fetchStats(false), fetchConfig()]);
    const scan = (lastStats && lastStats.latest_scan) || {};
    setText('cfg-last-scan', scan.timestamp ? `${fmtDateTime(scan.timestamp)} · ${scan.total_scanned} hisse` : 'Henüz tarama yok');
    if (cfg) {
      const f = (v, d = 0) => (Number.isFinite(num(v)) ? Number(v).toFixed(d) : DASH);
      setText('cfg-mode', cfg.paper_mode ? 'Paper test (gerçek emir yok)' : 'Canlı');
      setText('cfg-scan-interval', `${cfg.scan_interval_minutes} dakikada bir`);
      setText('cfg-market-hours', `${String(cfg.market_open_hour).padStart(2, '0')}:00 – ${String(cfg.market_close_hour).padStart(2, '0')}:00`);
      setText('cfg-intervals', `${INTERVAL_LABELS[cfg.trigger_interval] || cfg.trigger_interval} / ${INTERVAL_LABELS[cfg.trend_interval] || cfg.trend_interval}`);
      setText('cfg-watchlist', `${String(cfg.watchlist_source || '').toUpperCase()} · ${cfg.watchlist_size} hisse`);
      setText('cfg-provider', cfg.data_provider === 'yfinance' ? 'Yahoo Finance (gecikmeli)' : cfg.data_provider);
      setText('cfg-profile', cfg.strategy_profile);
      setText('cfg-buy-threshold', `≥ ${f(cfg.buy_threshold, 1)}`);
      setText('cfg-sell-threshold', `≤ ${f(cfg.sell_threshold, 1)}`);
      setText('cfg-max-actionable', num(cfg.max_actionable_score) >= 100 ? 'Sınırsız' : f(cfg.max_actionable_score, 1));
      setText('cfg-adx', f(cfg.adx_threshold, 0));
      setText('cfg-rsi', `${cfg.rsi_period} · ${cfg.rsi_oversold} / ${cfg.rsi_overbought}`);
      setText('cfg-sma', `${cfg.sma_fast} / ${cfg.sma_slow}`);
      setText('cfg-ema', `${cfg.ema_fast} / ${cfg.ema_slow} / ${cfg.ema_long}`);
      setText('cfg-volume-spike', `${f(cfg.volume_spike_multiplier, 2)}x`);
      setText('cfg-volume-confirm', `${f(cfg.volume_confirm_multiplier, 2)}x`);
    } else {
      showToast('Ayarlar okunamadı.', 'error', 3000);
    }

    const scanNowBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Şimdi Tara'));
    if (scanNowBtn) scanNowBtn.onclick = function () { runScan(scanNowBtn); };
  }

  // -------------------------------------------------------------------------
  // DOM Ready Initializer
  // -------------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', async () => {
    if (!(await enforceAuth())) return;
    initTopbar();
    updateSubscriptionBadge();

    const path = window.location.pathname;
    try {
      if (path.includes('dashboard')) {
        await initDashboard();
      } else if (path.includes('signals')) {
        await initSignals();
      } else if (path.includes('analysis')) {
        fetchStats(false);
        initAnalysis();
      } else if (path.includes('settings')) {
        await initSettings();
      } else if (path.includes('billing') || path.includes('admin')) {
        fetchStats(false);
      }
    } catch (routeErr) {
      console.error('[bistbot] route init error:', routeErr);
    }
  });

})();
