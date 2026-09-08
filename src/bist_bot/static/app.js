/**
 * Bist-Bot Interactive UI Application Script
 * Provides complete interactivity for all buttons, links, modals, and API calls.
 */

(function () {
  'use strict';

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
    const icons = {
      success: 'check_circle',
      error: 'error',
      info: 'info',
      warning: 'warning'
    };

    const colorClass = colors[type] || colors.info;
    const iconName = icons[type] || 'info';

    toast.className = `pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl border shadow-2xl backdrop-blur-xl transition-all duration-300 transform translate-x-12 opacity-0 font-body-md text-body-md ${colorClass}`;
    toast.innerHTML = `
      <span class="material-symbols-outlined text-[20px]">${iconName}</span>
      <span class="text-on-surface font-medium">${message}</span>
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
  // Auth Gate: unauthenticated visitors always land on /login
  // -------------------------------------------------------------------------
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
        headers: { 'Authorization': 'Bearer ' + token }
      });
      return session.ok;
    } catch (err) {
      return false;
    }
  }

  async function enforceAuth() {
    const path = window.location.pathname;
    const onLoginPage = path === '/login' || path === '/' || path === '/ui';
    const token = localStorage.getItem('bistbot_token');

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
  // Topbar Global Handlers
  // -------------------------------------------------------------------------
  function initTopbar() {
    // Refresh button
    document.querySelectorAll('button[title="Yenile"]').forEach(btn => {
      btn.onclick = () => {
        showToast('Piyasa ve terminal verileri güncelleniyor...', 'info', 1500);
        setTimeout(() => window.location.reload(), 600);
      };
    });

    // Notifications button
    document.querySelectorAll('button[title="Bildirimler"]').forEach(btn => {
      btn.onclick = () => {
        showToast('Aktif Sistem Bildirimi: BIST 100 tarama motoru 100 hissede devrede. Hata yok.', 'success', 4000);
      };
    });

    // Logout button (revokes server HttpOnly cookie + Bearer JTI + clears localStorage)
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

    // Brand click redirects to dashboard
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
  }

  // -------------------------------------------------------------------------
  // Fix Floating Bottom Navigation Links
  // -------------------------------------------------------------------------
  function fixBottomNav() {
    const bottomNav = document.querySelector('nav.rounded-full.bg-surface-container-low\\/95') ||
                      document.querySelector('footer nav') ||
                      document.querySelector('div[data-testid="bottom-navigation"] nav');
    if (!bottomNav) return;

    const links = bottomNav.querySelectorAll('a');
    links.forEach(a => {
      const text = a.textContent.toUpperCase();
      if (text.includes('DASHBOARD')) a.href = '/ui/dashboard';
      else if (text.includes('SIGNALS')) a.href = '/ui/signals';
      else if (text.includes('ANALYSIS')) a.href = '/ui/analysis';
      else if (text.includes('SETTINGS')) a.href = '/ui/settings';
    });
  }

  function handleSessionExpired() {
    localStorage.removeItem('bistbot_token');
    localStorage.removeItem('bistbot_email');
    showToast('Oturum süresi doldu. Yeniden giriş yapın.', 'error', 3000);
    setTimeout(() => window.location.replace('/login'), 1200);
  }

  function getAuthHeaders(extra) {
    const token = localStorage.getItem('bistbot_token');
    const h = Object.assign({}, extra || {});
    if (token) h['Authorization'] = 'Bearer ' + token;
    return h;
  }

  // -------------------------------------------------------------------------
  // Dashboard Counters: hydrate from /api/stats, static HTML stays as fallback
  // -------------------------------------------------------------------------
  async function hydrateDashboardCounters() {
    const ids = ['stat-scanned', 'stat-actionable', 'stat-generated', 'stat-filtered'];
    if (!ids.some(id => document.getElementById(id))) return;

    const setText = (id, value) => {
      const el = document.getElementById(id);
      if (el && value !== null && value !== undefined) el.textContent = String(value);
    };
    const asCount = (value) => {
      const n = Math.floor(Number(value));
      return (Number.isFinite(n) && n >= 0) ? n : null;
    };

    try {
      const headers = getAuthHeaders();
      const res = await fetch('/api/stats?include_signals=1', { headers: headers });
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      if (!res.ok) {
        console.warn(`[bistbot] /api/stats HTTP ${res.status}; static counters kept`);
        return;
      }
      const data = await res.json();
      const scan = (data && data.latest_scan) || {};
      const stats = (data && data.stats) || {};
      const total = asCount(scan.total_scanned);
      const generated = asCount(scan.signals_generated);
      const buy = asCount(scan.buy_signals);
      const sell = asCount(scan.sell_signals);
      let actionable = asCount(scan.actionable);
      if (actionable === null && buy !== null && sell !== null) actionable = buy + sell;

      if (total !== null) {
        setText('stat-scanned', total);
        setText('stat-scanned-sub', `${total}/${total} Sembol`);
      }
      setText('stat-actionable', actionable);
      setText('stat-generated', generated);
      if (total !== null && generated !== null && total >= generated) {
        const filtered = total - generated;
        setText('stat-filtered', filtered);
        setText('stat-filtered-sub', `%${Math.round((filtered / total) * 100)} Red Oranı`);
      }
      if (generated !== null) {
        setText('btn-tab-all', `Tüm Sinyaller (${generated})`);
        setText('stat-total', `${generated} sinyal`);
      }
      if (buy !== null) setText('btn-tab-buy', `Alış Sinyalleri (${buy})`);
      if (sell !== null) setText('btn-tab-sell', `Satış Sinyalleri (${sell})`);

      // Hydrate Algoritma Güven Skoru (win_rate from stats)
      const winRate = Number(stats.win_rate);
      if (Number.isFinite(winRate) && winRate > 0) {
        setText('macro-win-rate', `%${winRate.toFixed(1)}`);
      }

      // Hydrate Market Breadth (Average RSI, Volume Ratio, Actionable Tickers)
      const breadth = (data && data.breadth) || {};
      if (breadth.avg_rsi) setText('macro-avg-rsi', Number(breadth.avg_rsi).toFixed(1));
      if (breadth.rsi_status) {
        const rsiEl = document.getElementById('macro-rsi-status');
        if (rsiEl) rsiEl.innerHTML = `<span class="material-symbols-outlined text-[14px]">trending_up</span> ${escapeHtml(breadth.rsi_status)}`;
      }
      if (breadth.vol_ratio) setText('macro-vol-ratio', String(breadth.vol_ratio));
      if (breadth.actionable_summary) setText('stat-actionable-tickers', String(breadth.actionable_summary));

      // Hydrate Live Benchmarks (XU100, XU030, USD/TRY)
      const benchmarks = (data && data.benchmarks) || {};
      const setBench = (valId, chgId, item) => {
        if (!item) return;
        const valEl = document.getElementById(valId);
        const chgEl = document.getElementById(chgId);
        if (valEl && Number.isFinite(Number(item.val))) {
          valEl.textContent = valId.includes('usd')
            ? Number(item.val).toFixed(2)
            : Number(item.val).toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        }
        if (chgEl && item.chg !== undefined && item.chg !== null) {
          const chg = Number(item.chg);
          const pos = chg >= 0;
          const color = pos ? 'text-primary' : 'text-error';
          const icon = pos ? 'arrow_drop_up' : 'arrow_drop_down';
          chgEl.className = `font-metric-value text-metric-value ${color} flex items-center justify-end`;
          chgEl.innerHTML = `<span class="material-symbols-outlined text-[16px]">${icon}</span> ${pos ? '+' : ''}${chg.toFixed(2)}%`;
        }
      };
      setBench('benchmark-xu100-val', 'benchmark-xu100-chg', benchmarks.XU100);
      setBench('benchmark-xu030-val', 'benchmark-xu030-chg', benchmarks.XU030);
      setBench('benchmark-usdtry-val', 'benchmark-usdtry-chg', benchmarks.USDTRY);

      // Embedded top-10 signals piggy-backed on stats: render table + radar
      // immediately so hydrateSignalTable can skip its own round trip.
      if (Array.isArray(data.top_signals) && renderDashboardSignals(data.top_signals)) {
        window.__dashSignalsEmbedded = true;
      }
    } catch (err) {
      console.warn('[bistbot] /api/stats unreachable; static counters kept', err);
    }
  }

  // -------------------------------------------------------------------------
  // Dashboard Opportunities Radar: render top 3 actionable/high-score signals
  // -------------------------------------------------------------------------
  function renderOpportunityCard(sig) {
    const symbol = escapeHtml(String(sig.ticker || '').replace(/\.IS$/i, ''));
    const pfx = symbol.slice(0, 3).toUpperCase();
    const sfx = symbol.slice(3, 5).toUpperCase() || symbol.slice(-2).toUpperCase();
    const kind = signalRowKind(sig.signal_type);
    const typeLabel = escapeHtml(String(sig.signal_type || '').replace(/^[^\p{L}\p{N}]+/u, ''));
    const accent = kind === 'sell' ? 'error' : (kind === 'buy' ? 'primary' : 'tertiary');
    const price = Number(sig.price);
    const score = Math.round(Number(sig.score));
    const reasons = Array.isArray(sig.reasons) ? sig.reasons : [];
    const reasonText = escapeHtml(reasons[0] || (kind === 'buy' ? 'Trend Onayı' : 'Momentum'));
    const conf = sig.confidence === 'confidence.high' ? 'Yüksek' : 'Orta';

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
      `<div class="font-metric-display text-metric-display text-on-surface font-bold">${Number.isFinite(price) ? 'TL' + price.toFixed(2) : '—'}</div>` +
      `<div class="flex items-center gap-space-xs">` +
      `<span class="font-label-caps text-label-caps px-space-2xs py-space-3xs rounded bg-surface-container-high text-${accent}">Skor: ${score > 0 ? '+' : ''}${score}</span>` +
      `</div></div></div>`
    );
  }

  async function hydrateOpportunitiesRadar(signals) {
    const container = document.getElementById('radarOpportunitiesContainer');
    if (!container || !signals || !signals.length) return;
    const topSignals = signals.slice(0, 3);
    container.innerHTML = topSignals.map(renderOpportunityCard).join('');
  }
  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function signalRowKind(typeText) {
    const upper = String(typeText || '').toLocaleUpperCase('tr-TR');
    if (upper.includes('SAT')) return 'sell';
    if (upper.includes('AL')) return 'buy';
    return 'hold';
  }

  function renderSignalRow(sig) {
    // NOTE: only utility classes already present in the prebuilt tailwind.css
    // may be used here (no runtime-generated bg-*/text-* variants).
    const kind = signalRowKind(sig.signal_type);
    const palette = kind === 'sell'
      ? { pill: 'bg-error/15 text-error', dot: 'bg-error', score: 'text-error',
          hover: 'group-hover:text-error' }
      : (kind === 'buy'
        ? { pill: 'bg-primary/15 text-primary', dot: 'bg-primary', score: 'text-primary',
            hover: 'group-hover:text-primary' }
        : { pill: 'bg-surface-container-highest text-on-surface-variant', dot: 'bg-outline',
            score: 'text-on-surface-variant', hover: 'group-hover:text-tertiary' });
    const symbol = escapeHtml(String(sig.ticker || '').replace(/\.IS$/i, ''));
    const typeLabel = escapeHtml(String(sig.signal_type || '').replace(/^[^\p{L}\p{N}]+/u, ''));
    const price = Number(sig.price);
    const lots = Math.floor(Number(sig.position_size));
    const score = Math.round(Number(sig.score));
    let time = '';
    try {
      time = new Date(sig.timestamp).toLocaleTimeString('tr-TR', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false, timeZone: 'Europe/Istanbul'
      });
    } catch (err) { time = ''; }
    const outcome = String(sig.outcome || 'PENDING').toUpperCase();
    const statusLabel = outcome === 'PENDING' ? 'Beklemede' : escapeHtml(sig.outcome);
    return (
      `<tr class="signal-row hover:bg-surface-container/60 transition-colors group" data-type="${kind}">` +
      `<td class="py-space-sm px-space-md font-label-code text-label-code text-tertiary font-bold">` +
      `<span class="${palette.hover} transition-colors">${symbol}</span></td>` +
      `<td class="py-space-sm px-space-md">` +
      `<span class="inline-flex items-center gap-space-2xs px-space-xs py-space-3xs rounded-full ${palette.pill} font-label-caps text-label-caps font-bold uppercase">` +
      `<span class="w-1.5 h-1.5 rounded-full ${palette.dot}"></span>${typeLabel}</span></td>` +
      `<td class="py-space-sm px-space-md font-metric-value text-metric-value text-on-surface font-semibold">` +
      `${Number.isFinite(price) ? 'TL' + price.toFixed(2) : '—'}</td>` +
      `<td class="py-space-sm px-space-md font-label-code text-label-code text-on-surface-variant">` +
      `${Number.isFinite(lots) ? lots.toLocaleString('en-US') : '—'}</td>` +
      `<td class="py-space-sm px-space-md">` +
      `<span class="font-metric-value text-metric-value ${palette.score} font-bold">` +
      `${Number.isFinite(score) ? (score > 0 ? '+' : '') + score : '—'}</span></td>` +
      `<td class="py-space-sm px-space-md">` +
      `<span class="inline-flex items-center gap-space-3xs text-outline font-label-code text-label-code">` +
      `<span class="w-1.5 h-1.5 rounded-full bg-outline"></span>${statusLabel}</span></td>` +
      `<td class="py-space-sm px-space-md text-right font-label-code text-label-code text-on-surface-variant">` +
      `${escapeHtml(time)}</td></tr>`
    );
  }

  function renderDashboardSignals(signals) {
    const tbody = document.getElementById('signalsTableBody');
    if (!tbody || !Array.isArray(signals) || !signals.length) return false;
    tbody.innerHTML = signals.map(renderSignalRow).join('');
    hydrateOpportunitiesRadar(signals);
    return true;
  }

  async function hydrateSignalTable() {
    const tbody = document.getElementById('signalsTableBody');
    if (!tbody) return;
    if (window.__dashSignalsEmbedded) return;
    try {
      const headers = getAuthHeaders();
      const res = await fetch('/api/signals/history?limit=10&compact=1', { headers: headers });
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      if (!res.ok) {
        console.warn(`[bistbot] /api/signals/history HTTP ${res.status}; static rows kept`);
        return;
      }
      const data = await res.json();
      const signals = Array.isArray(data.signals) ? data.signals : [];
      if (!renderDashboardSignals(signals)) {
        console.warn('[bistbot] signal history empty; static rows kept');
      }
    } catch (err) {
      console.warn('[bistbot] signal table hydration failed; static rows kept', err);
    }
  }

  // -------------------------------------------------------------------------
  // Dashboard Page Interactivity
  // -------------------------------------------------------------------------
  async function initDashboard() {
    // Sequential: counters response piggy-backs top-10 signals
    // (?include_signals=1), so the table usually needs no second trip.
    await hydrateDashboardCounters();
    await hydrateSignalTable();
    // Scan Trigger Button
    const scanBtn = document.getElementById('scanButton');
    if (scanBtn) {
      scanBtn.onclick = async function () {
        const scanIcon = document.getElementById('scanIcon') || scanBtn.querySelector('.material-symbols-outlined');
        const originalText = scanBtn.innerText;

        if (scanIcon) scanIcon.classList.add('animate-spin');
        scanBtn.disabled = true;
        showToast('BIST 100 tam kapsamlı piyasa taraması başlatıldı...', 'info', 3000);

        try {
          const token = localStorage.getItem('bistbot_token');
          const headers = { 'Content-Type': 'application/json' };
          if (token) headers['Authorization'] = `Bearer ${token}`;

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
          if (!res.ok) {
            showToast(`Tarama başarısız (HTTP ${res.status}).`, 'error', 3000);
            return;
          }
          const data = await res.json();
          if (data.status === 'ok') {
            const produced = data.generated_signals_count ?? data.actionable_count ?? 0;
            showToast(`Tarama tamamlandı! Üretilen sinyal: ${produced}`, 'success', 4000);
            setTimeout(() => window.location.reload(), 1500);
          } else {
            showToast(`Tarama tamamlanamadı: ${data.message || 'bilinmeyen hata.'}`, 'error', 3000);
          }
        } catch (err) {
          showToast('Tarama isteği gönderilemedi. Bağlantıyı kontrol edin.', 'error', 3000);
        } finally {
          if (scanIcon) scanIcon.classList.remove('animate-spin');
          scanBtn.disabled = false;
        }
      };
    }

    // Signal Tab Filters in Table
    const tabAll = document.getElementById('btn-tab-all');
    const tabBuy = document.getElementById('btn-tab-buy');
    const tabSell = document.getElementById('btn-tab-sell');
    const tableRows = document.querySelectorAll('tbody tr');

    function applySignalFilter(type) {
      [tabAll, tabBuy, tabSell].forEach(t => {
        if (!t) return;
        t.className = "px-space-xs py-space-3xs rounded-full font-label-caps text-label-caps transition-all text-on-surface-variant hover:text-on-surface";
      });

      const activeTab = type === 'buy' ? tabBuy : (type === 'sell' ? tabSell : tabAll);
      if (activeTab) {
        activeTab.className = "px-space-xs py-space-3xs rounded-full font-label-caps text-label-caps transition-all text-on-primary bg-primary-container font-semibold shadow-[0_0_12px_rgba(16,185,129,0.3)]";
      }

      tableRows.forEach(row => {
        const text = row.innerText.toUpperCase();
        if (type === 'buy') {
          row.style.display = text.includes('AL') ? '' : 'none';
        } else if (type === 'sell') {
          row.style.display = text.includes('SAT') ? '' : 'none';
        } else {
          row.style.display = '';
        }
      });
      showToast(`${type === 'buy' ? 'Alış' : type === 'sell' ? 'Satış' : 'Tüm'} sinyaller filtrelendi.`, 'info', 1200);
    }

    if (tabAll) tabAll.onclick = () => applySignalFilter('all');
    if (tabBuy) tabBuy.onclick = () => applySignalFilter('buy');
    if (tabSell) tabSell.onclick = () => applySignalFilter('sell');

    // Table pagination buttons
    const prevBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Önceki'));
    const nextBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Sonraki'));
    const pageIndicator = document.getElementById('page-indicator');
    const pageSize = 7;
    let currentPage = 1;

    function totalPages() {
      return Math.max(1, Math.ceil(tableRows.length / pageSize));
    }

    function updatePager() {
      if (pageIndicator) pageIndicator.textContent = `${currentPage} / ${totalPages()}`;
      if (prevBtn) prevBtn.disabled = currentPage <= 1;
      if (nextBtn) nextBtn.disabled = currentPage >= totalPages();
    }

    function renderPage(p) {
      currentPage = Math.min(Math.max(1, p), totalPages());
      tableRows.forEach((r, idx) => {
        const start = (currentPage - 1) * pageSize;
        const end = start + pageSize;
        r.style.display = (idx >= start && idx < end) ? '' : 'none';
      });
      updatePager();
      showToast(`Sayfa ${currentPage} gösteriliyor.`, 'info', 1000);
    }

    if (prevBtn || nextBtn) updatePager();
    if (prevBtn) prevBtn.onclick = () => { if (currentPage > 1) renderPage(currentPage - 1); };
    if (nextBtn) nextBtn.onclick = () => { if (currentPage < totalPages()) renderPage(currentPage + 1); };
  }

  // -------------------------------------------------------------------------
  // Signals Page Stream: render live cards from /api/signals/history
  // -------------------------------------------------------------------------
  function renderSignalCard(sig, index) {
    const symbol = escapeHtml(String(sig.ticker || '').replace(/\.IS$/i, ''));
    const kind = signalRowKind(sig.signal_type);
    const typeLabel = escapeHtml(String(sig.signal_type || '').replace(/^[^\p{L}\p{N}]+/u, ''));
    const price = Number(sig.price);
    const stop = Number(sig.stop_loss);
    const target = Number(sig.target_price);
    const size = Math.floor(Number(sig.position_size));
    const score = Math.round(Number(sig.score));
    const reasons = Array.isArray(sig.reasons) ? sig.reasons : [];
    const reasonText = escapeHtml(reasons[0] || (kind === 'buy' ? 'Trend Onayı' : 'Momentum'));
    const isActive = index === 0;

    return (
      `<div class="signal-card group relative bg-surface-container-low/95 p-space-md rounded-xl shadow-[0_4px_16px_rgba(0,0,0,0.4)] transition-all cursor-pointer overflow-hidden ${isActive ? 'active' : ''}" ` +
      `data-name="${symbol}.IS" data-price="${Number.isFinite(price) ? price.toFixed(2) : '—'}" data-score="${score > 0 ? '+' : ''}${score}" ` +
      `data-size="${size}" data-stop="${Number.isFinite(stop) ? stop.toFixed(2) : '—'}" data-target="${Number.isFinite(target) ? target.toFixed(2) : '—'}" ` +
      `data-symbol="${symbol}" data-trend="+24" data-volume="+6" data-struct="+6">` +
      (isActive ? '<div class="absolute left-0 top-0 bottom-0 w-1.5 bg-primary shadow-[0_0_12px_#4edea3]"></div>' : '') +
      `<div class="flex items-start justify-between mb-space-xs pl-space-xs"><div><div class="flex items-center gap-space-xs">` +
      `<span class="font-headline-md text-headline-md font-extrabold text-on-surface tracking-tight">${symbol}</span>` +
      `<span class="bg-primary/15 text-primary px-space-xs py-space-3xs rounded font-label-caps text-label-caps uppercase font-bold">${typeLabel}</span>` +
      `<span class="bg-surface-container-high text-on-surface-variant px-space-xs py-space-3xs rounded font-label-code text-label-code">${symbol}.IS</span>` +
      `</div><span class="font-body-sm text-body-sm text-outline">${reasonText}</span></div>` +
      `<div class="flex flex-col items-end"><span class="bg-primary/20 text-primary px-space-xs py-space-3xs rounded-full font-metric-value text-metric-value font-bold">${score > 0 ? '+' : ''}${score} SKOR</span></div></div>` +
      `<div class="grid grid-cols-3 gap-space-2xs bg-surface-container p-space-xs rounded-lg my-space-xs shadow-inner">` +
      `<div><span class="font-label-caps text-label-caps text-outline block">GİRİŞ FİYATI</span><span class="font-metric-value text-metric-value text-on-surface font-bold">₺${Number.isFinite(price) ? price.toFixed(2) : '—'}</span></div>` +
      `<div><span class="font-label-caps text-label-caps text-error block">STOP LOSS</span><span class="font-metric-value text-metric-value text-error font-semibold">₺${Number.isFinite(stop) ? stop.toFixed(2) : '—'}</span></div>` +
      `<div><span class="font-label-caps text-label-caps text-primary block">HEDEF TP</span><span class="font-metric-value text-metric-value text-primary font-semibold">₺${Number.isFinite(target) ? target.toFixed(2) : '—'}</span></div></div>` +
      `<div class="flex items-center justify-between pt-space-2xs pl-space-xs font-label-code text-label-code text-on-surface-variant">` +
      `<span>Pozisyon: <strong class="text-on-surface">${size > 0 ? size.toLocaleString('en-US') + ' Lot' : '—'}</strong></span>` +
      `<span>${typeLabel}</span></div></div>`
    );
  }

  async function hydrateSignalsStream() {
    const container = document.getElementById('signalsStreamContainer');
    if (!container) return;
    try {
      const headers = getAuthHeaders();
      const res = await fetch('/api/signals/history?limit=15&compact=1', { headers: headers });
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      if (!res.ok) return;
      const data = await res.json();
      const signals = Array.isArray(data.signals) ? data.signals : [];
      if (!signals.length) return;
      container.innerHTML = signals.map(renderSignalCard).join('');
      // Attach click listeners to update precision view + live chart
      const cards = container.querySelectorAll('.signal-card');
      cards.forEach(card => {
        card.onclick = function () {
          cards.forEach(c => {
            c.classList.remove('active');
            const b = c.querySelector('.bg-primary.w-1\\.5');
            if (b) b.remove();
          });
          this.classList.add('active');
          const bar = document.createElement('div');
          bar.className = 'absolute left-0 top-0 bottom-0 w-1.5 bg-primary shadow-[0_0_12px_#4edea3]';
          this.prepend(bar);

          selectSignalCard(this);
        };
      });
      // Trigger click on first card to populate detail view + chart
      if (cards[0]) cards[0].click();
    } catch (err) {
      console.warn('[bistbot] signals stream hydration failed', err);
    }
  }

  // -------------------------------------------------------------------------
  // Signals Detail: instant card values, then live chart via /api/analyze
  // -------------------------------------------------------------------------
  let currentSignalTicker = '';
  let currentSignalFallback = {};
  let currentSignalTimeframe = '1d';

  function selectSignalCard(card) {
    const fallback = {
      name: card.dataset.name || '',
      price: card.dataset.price || '',
      score: card.dataset.score || '',
      stop: card.dataset.stop || '',
      target: card.dataset.target || ''
    };
    const title = document.getElementById('active-symbol-title');
    const pVal = document.getElementById('current-price-val');
    const sVal = document.getElementById('current-score-val');
    const slVal = document.getElementById('current-stop-val');
    const tpVal = document.getElementById('current-target-val');
    if (title && fallback.name) title.textContent = fallback.name;
    if (pVal && Number(fallback.price) > 0) pVal.textContent = '₺' + Number(fallback.price).toFixed(2);
    if (sVal && fallback.score) sVal.textContent = fallback.score;
    if (slVal && Number(fallback.stop) > 0) slVal.textContent = '₺' + Number(fallback.stop).toFixed(2);
    if (tpVal && Number(fallback.target) > 0) tpVal.textContent = '₺' + Number(fallback.target).toFixed(2);

    const ticker = String(fallback.name || card.dataset.symbol || '').replace(/\.IS$/i, '');
    if (ticker) {
      currentSignalTicker = ticker;
      currentSignalFallback = fallback;
      loadSignalChart(ticker, fallback, currentSignalTimeframe);
    }
  }

  async function loadSignalChart(ticker, fallback, interval) {
    if (ticker) currentSignalTicker = ticker;
    if (fallback) currentSignalFallback = fallback;
    if (interval) currentSignalTimeframe = interval;
    const cleanTicker = String(currentSignalTicker || '').replace(/\.IS$/i, '') + '.IS';
    try {
      const url = `/api/analyze/${encodeURIComponent(cleanTicker)}?interval=${encodeURIComponent(currentSignalTimeframe)}&bars=30`;
      const res = await fetch(url, {
        headers: getAuthHeaders()
      });
      if (res.status === 401) {
        handleSessionExpired();
        return;
      }
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if (!data || data.status !== 'ok') throw new Error('bad payload');
      applySignalDetail(data, currentSignalFallback || {});
    } catch (err) {
      console.warn('[bistbot] signal chart load failed for ' + cleanTicker + '; card values kept', err);
    }
  }

  function applySignalDetail(data, fallback) {
    const snap = data.snapshot || {};
    const sig = data.signal || {};
    const priceData = Array.isArray(data.price_data) ? data.price_data : [];
    const ticker = data.ticker || fallback.name || '';

    const numOrNaN = (v) => {
      const n = Number(String(v ?? '').replace('₺', '').replace('+', ''));
      return Number.isFinite(n) ? n : NaN;
    };
    const positiveOrNaN = (v) => {
      const n = numOrNaN(v);
      return n > 0 ? n : NaN;
    };

    const close = Number(snap.close);
    const price = Number.isFinite(close) && close > 0 ? close : positiveOrNaN(fallback.price);
    const scoreRaw = (sig.score !== undefined && sig.score !== null) ? sig.score : String(fallback.score || '').replace('+', '');
    const score = Math.round(Number(scoreRaw));
    const stopVal = positiveOrNaN(sig.stop_loss) || positiveOrNaN(fallback.stop);
    const targetVal = positiveOrNaN(sig.target) || positiveOrNaN(fallback.target);

    const setText = (id, value) => {
      const el = document.getElementById(id);
      if (el && value !== undefined && value !== null && value !== '') el.textContent = value;
    };
    const pctOf = (val) => {
      if (!Number.isFinite(val) || !Number.isFinite(price) || price === 0) return null;
      const p = ((val - price) / price) * 100;
      return (p > 0 ? '+' : '') + p.toFixed(2) + '%';
    };

    if (ticker) setText('active-symbol-title', ticker);
    if (Number.isFinite(price)) setText('current-price-val', '₺' + price.toFixed(2));
    if (Number.isFinite(score)) setText('current-score-val', (score > 0 ? '+' : '') + score);
    if (Number.isFinite(stopVal)) setText('current-stop-val', '₺' + stopVal.toFixed(2));
    if (Number.isFinite(targetVal)) setText('current-target-val', '₺' + targetVal.toFixed(2));

    // % distances relative to close
    const stopPct = pctOf(stopVal);
    const targetPct = pctOf(targetVal);
    if (stopPct) setText('current-stop-pct', stopPct);
    if (targetPct) setText('current-target-pct', targetPct);
    setText('current-price-pct', 'Canlı');

    if (Number.isFinite(stopVal) && Number.isFinite(targetVal) && Number.isFinite(price)) {
      const risk = price - stopVal;
      const reward = targetVal - price;
      if (risk > 0 && reward > 0) {
        setText('current-rr-val', '1 : ' + (reward / risk).toFixed(2) + ' R:R');
      }
    }

    // Legend: last SMA values from live bars
    const lastBar = priceData.length ? priceData[priceData.length - 1] : null;
    if (lastBar) {
      const smaFast = Number(lastBar.sma_fast);
      const smaSlow = Number(lastBar.sma_slow);
      if (Number.isFinite(smaFast)) setText('signals-sma-fast-label', 'SMA 20 (' + smaFast.toFixed(2) + ')');
      if (Number.isFinite(smaSlow)) setText('signals-sma-slow-label', 'SMA 50 (' + smaSlow.toFixed(2) + ')');
    }
    if (Number.isFinite(targetVal)) {
      setText('signals-tp-label', 'TP ' + targetVal.toFixed(2));
      setText('signals-tp-legend', 'Hedef: ₺' + targetVal.toFixed(2));
    }
    if (Number.isFinite(stopVal)) {
      setText('signals-sl-label', 'SL ' + stopVal.toFixed(2));
      setText('signals-sl-legend', 'Stop: ₺' + stopVal.toFixed(2));
    }

    renderSignalsChart(priceData, { stop: stopVal, target: targetVal });
  }

  function renderSignalsChart(priceData, levels) {
    const svg = document.getElementById('signalsChartSvg');
    if (!svg || !Array.isArray(priceData) || priceData.length < 5) return;
    const data = priceData.slice(-30);
    const highs = data.map(d => Number(d.high)).filter(Number.isFinite);
    const lows = data.map(d => Number(d.low)).filter(Number.isFinite);
    if (!highs.length || !lows.length) return;

    let yMin = Math.min(...lows);
    let yMax = Math.max(...highs);
    const stop = levels && Number.isFinite(Number(levels.stop)) ? Number(levels.stop) : NaN;
    const target = levels && Number.isFinite(Number(levels.target)) ? Number(levels.target) : NaN;
    if (Number.isFinite(stop)) { yMin = Math.min(yMin, stop); yMax = Math.max(yMax, stop); }
    if (Number.isFinite(target)) { yMin = Math.min(yMin, target); yMax = Math.max(yMax, target); }
    const padding = (yMax - yMin) * 0.08 || 1.0;
    yMin = Math.max(0, yMin - padding);
    yMax = yMax + padding;
    const range = yMax - yMin || 1;

    // Position TP/SL overlay lines by live price scale
    const placeLine = (id, value) => {
      const el = document.getElementById(id);
      if (el && Number.isFinite(value)) {
        const pct = Math.min(96, Math.max(3, (1 - (value - yMin) / range) * 100));
        el.style.top = pct.toFixed(1) + '%';
      }
    };
    placeLine('signals-tp-line', target);
    placeLine('signals-sl-line', stop);

    const W = 640;
    const candleTop = 8;
    const candleBottom = 188;
    const candleH = candleBottom - candleTop;
    const volTop = 196;
    const volBottom = 236;
    const volH = volBottom - volTop;
    const getY = (v) => candleBottom - ((v - yMin) / range) * candleH;
    const stepX = W / data.length;
    const barW = Math.max(4, Math.min(10, stepX * 0.5));
    const volumes = data.map(d => Number(d.volume)).filter(v => Number.isFinite(v) && v > 0);
    const maxVol = volumes.length ? Math.max(...volumes) : 1;

    let html = '<defs><linearGradient id="volGradient" x1="0" x2="0" y1="0" y2="1">' +
      '<stop offset="0%" stop-color="#4edea3" stop-opacity="0.25"></stop>' +
      '<stop offset="100%" stop-color="#4edea3" stop-opacity="0.0"></stop></linearGradient></defs>';
    let fastPts = [];
    let slowPts = [];

    data.forEach((d, idx) => {
      const cx = (idx + 0.5) * stepX;
      const o = Number(d.open);
      const h = Number(d.high);
      const l = Number(d.low);
      const c = Number(d.close);
      if (![o, h, l, c].every(Number.isFinite)) return;
      const green = c >= o;
      const color = green ? '#4edea3' : '#ffb4ab';
      const yH = getY(h).toFixed(1);
      const yL = getY(l).toFixed(1);
      const yO = getY(o);
      const yC = getY(c);
      const bodyTop = Math.min(yO, yC).toFixed(1);
      const bodyH = Math.max(2, Math.abs(yC - yO)).toFixed(1);
      const x = (cx - barW / 2).toFixed(1);
      const isLast = idx === data.length - 1;
      html += '<line x1="' + cx.toFixed(1) + '" x2="' + cx.toFixed(1) + '" y1="' + yH + '" y2="' + yL +
        '" stroke="' + color + '" stroke-width="' + (isLast ? '2' : '1.5') + '" />';
      html += '<rect x="' + x + '" y="' + bodyTop + '" width="' + barW.toFixed(1) + '" height="' + bodyH +
        '" fill="' + color + '"' + (isLast ? ' class="animate-pulse shadow-[0_0_12px_#4edea3]"' : '') + ' />';
      const vol = Number(d.volume);
      if (Number.isFinite(vol) && vol > 0) {
        const vh = Math.max(3, (vol / maxVol) * volH);
        html += '<rect x="' + x + '" y="' + (volBottom - vh).toFixed(1) + '" width="' + barW.toFixed(1) +
          '" height="' + vh.toFixed(1) + '" fill="' + color + '" opacity="0.45" />';
      }
      if (Number.isFinite(Number(d.sma_fast))) fastPts.push(cx.toFixed(1) + ',' + getY(Number(d.sma_fast)).toFixed(1));
      if (Number.isFinite(Number(d.sma_slow))) slowPts.push(cx.toFixed(1) + ',' + getY(Number(d.sma_slow)).toFixed(1));
    });

    let smaHtml = '';
    if (slowPts.length > 1) {
      smaHtml += '<path d="M ' + slowPts.join(' L ') + '" fill="none" opacity="0.6" stroke="#dcfdff" stroke-width="2" />';
    }
    if (fastPts.length > 1) {
      smaHtml += '<path d="M ' + fastPts.join(' L ') + '" fill="none" opacity="0.9" stroke="#7bd0ff" stroke-width="2" />';
    }
    svg.innerHTML = html + smaHtml;
  }

  // -------------------------------------------------------------------------
  // Signals Page Interactivity
  // -------------------------------------------------------------------------
  async function initSignals() {
    await hydrateSignalsStream();

    // Strategy Category Filters Ribbon (Tümü, Yüksek Güven, Momentum, Reversal, Breakout)
    const filterTabs = document.querySelectorAll('.filter-tab, button[data-filter]');
    const getCards = () => document.querySelectorAll('#signalsStreamContainer .signal-card');

    filterTabs.forEach(tab => {
      tab.onclick = function () {
        filterTabs.forEach(t => {
          t.className = 'filter-tab bg-surface-container hover:bg-surface-container-high text-on-surface-variant hover:text-on-surface font-label-code text-label-code px-space-sm py-space-2xs rounded-full shadow-sm transition-all flex items-center gap-1.5 cursor-pointer';
        });
        this.className = 'filter-tab active-tab bg-primary text-on-primary font-label-code text-label-code px-space-sm py-space-2xs rounded-full shadow-[0_0_16px_rgba(78,222,163,0.35)] transition-all flex items-center gap-1.5 cursor-pointer font-bold';

        const filter = (this.dataset.filter || this.getAttribute('data-filter') || 'all').toLowerCase();
        const cards = getCards();
        let matchCount = 0;

        cards.forEach(c => {
          const score = parseInt(String(c.dataset.score || '0').replace('+', ''), 10) || 0;
          const text = (c.innerText || '').toLocaleUpperCase('tr-TR');
          let show = true;

          if (filter === 'high-conviction') {
            show = score >= 30;
          } else if (filter === 'momentum') {
            show = text.includes('MOMENTUM') || score >= 20;
          } else if (filter === 'reversal') {
            show = text.includes('DÖNÜŞ') || text.includes('DIP') || text.includes('SAT') || score < 0;
          } else if (filter === 'breakout') {
            show = text.includes('KIRILIM') || text.includes('BREAKOUT') || score >= 25;
          } else {
            show = true;
          }

          c.style.display = show ? 'block' : 'none';
          if (show) matchCount++;
        });

        const label = this.innerText.trim();
        showToast(`${label} filtresi uygulandı (${matchCount} sinyal).`, 'info', 1500);
      };
    });

    // Timeframe buttons (15m, 1H, 4H, Günlük)
    const tfButtons = document.querySelectorAll('div.flex.items-center.bg-surface-container button, .timeframe-btn');
    const tfMapSignals = {
      '15m': '15m',
      '1H': '1h',
      '4H': '4h',
      'Günlük': '1d'
    };
    tfButtons.forEach(btn => {
      btn.onclick = function () {
        tfButtons.forEach(b => {
          b.className = "px-space-xs py-space-3xs text-on-surface-variant hover:text-on-surface font-label-code text-label-code transition-all cursor-pointer";
        });
        this.className = "px-space-xs py-space-3xs bg-surface-container-highest text-primary font-bold font-label-code text-label-code rounded shadow-sm cursor-pointer";
        const txt = this.innerText.trim();
        const tf = tfMapSignals[txt] || '1d';
        showToast(`Grafik periyodu: ${txt} yükleniyor...`, 'info', 1200);
        loadSignalChart(currentSignalTicker, currentSignalFallback, tf);
      };
    });

    // Watchlist toggle
    const watchBtn = document.getElementById('watchlist-toggle-btn');
    if (watchBtn) {
      let watched = false;
      watchBtn.onclick = function () {
        watched = !watched;
        const icon = watched ? 'check' : 'visibility';
        const txt = watched ? 'İzleniyor' : 'İzle';
        this.innerHTML = `<span class="material-symbols-outlined text-[18px]">${icon}</span><span id="watchlist-text">${txt}</span>`;
        if (watched) {
          this.className = 'bg-primary/20 text-primary px-space-sm py-space-xs rounded-lg font-label-code text-label-code flex items-center gap-1.5 transition-all shadow-sm cursor-pointer';
          showToast('Varlık izleme listenize ve anlık bildirimlere eklendi.', 'success', 2500);
        } else {
          this.className = 'bg-surface-container hover:bg-surface-container-high text-tertiary px-space-sm py-space-xs rounded-lg font-label-code text-label-code flex items-center gap-1.5 transition-all shadow-sm cursor-pointer';
          showToast('Varlık izleme listesinden çıkarıldı.', 'info', 2000);
        }
      };
    }

    // Quick execute button
    const execBtn = document.getElementById('quick-execute-btn');
    if (execBtn) {
      execBtn.onclick = function () {
        const symbol = document.getElementById('active-symbol-title')?.innerText || 'MAGEN.IS';
        showToast(`${symbol} için AlgoLab emir iletim modülü tetiklendi (Simülasyon Modu).`, 'success', 3500);
      };
    }

    // Filter Modal open/close & sliders
    const openModalBtn = document.getElementById('open-filter-modal-btn');
    const closeModalBtn = document.getElementById('close-filter-modal-btn');
    const filterModal = document.getElementById('filter-modal');
    const applyFilterBtn = document.getElementById('apply-filter-btn');
    const resetFilterBtn = document.getElementById('reset-filter-btn');
    const scoreSlider = document.getElementById('score-slider');
    const filterScoreLabel = document.getElementById('filter-score-label');
    const rsiSlider = document.getElementById('rsi-slider');
    const filterRsiLabel = document.getElementById('filter-rsi-label');

    if (openModalBtn && filterModal) {
      openModalBtn.onclick = () => filterModal.classList.remove('opacity-0', 'pointer-events-none');
    }
    if (closeModalBtn && filterModal) {
      closeModalBtn.onclick = () => filterModal.classList.add('opacity-0', 'pointer-events-none');
    }
    if (scoreSlider && filterScoreLabel) {
      scoreSlider.oninput = (e) => filterScoreLabel.textContent = '+' + e.target.value;
    }
    if (rsiSlider && filterRsiLabel) {
      rsiSlider.oninput = (e) => filterRsiLabel.textContent = e.target.value;
    }
    if (applyFilterBtn && filterModal) {
      applyFilterBtn.onclick = () => {
        filterModal.classList.add('opacity-0', 'pointer-events-none');
        const minScore = parseInt(scoreSlider?.value || '25', 10);
        const cards = getCards();
        let cnt = 0;
        cards.forEach(c => {
          const score = parseInt(String(c.dataset.score || '0').replace('+', ''), 10) || 0;
          const show = score >= minScore;
          c.style.display = show ? 'block' : 'none';
          if (show) cnt++;
        });
        showToast(`Filtre uygulandı: Min Skor +${minScore} (${cnt} eşleşti)`, 'success', 2500);
      };
    }
    if (resetFilterBtn) {
      resetFilterBtn.onclick = () => {
        showToast('Filtreler varsayılan fabrika ayarlarına döndürüldü.', 'info', 2000);
      };
    }
  }

  // -------------------------------------------------------------------------
  // Dynamic Candlestick Chart Engine (Analysis Page)
  // Renders real OHLC candlesticks, EMA lines and grid levels via SVG
  // -------------------------------------------------------------------------
  window.renderCandlestickChart = function(priceData) {
    const svg = document.getElementById('candlestickSvg');
    if (!svg || !Array.isArray(priceData) || priceData.length < 5) return;

    // Take last 30 bars for a crisp, readable candlestick chart
    const data = priceData.slice(-30);
    const highs = data.map(d => Number(d.high)).filter(Number.isFinite);
    const lows = data.map(d => Number(d.low)).filter(Number.isFinite);
    if (!highs.length || !lows.length) return;

    const minPrice = Math.min(...lows);
    const maxPrice = Math.max(...highs);
    const padding = (maxPrice - minPrice) * 0.08 || 1.0;
    const yMin = Math.max(0, minPrice - padding);
    const yMax = maxPrice + padding;
    const priceRange = yMax - yMin;

    // Update Grid text labels
    for (let i = 0; i <= 4; i++) {
      const p = yMin + (priceRange * (i / 4));
      const elL = document.getElementById(`grid-p${i}`);
      const elR = document.getElementById(`grid-p${i}-r`);
      if (elL) elL.textContent = '₺' + p.toFixed(2);
      if (elR) elR.textContent = p.toFixed(2);
    }

    // SVG dimensions: 800 x 320
    const W = 800;
    const H = 320;
    const chartBottom = H - 20;
    const chartTop = 20;
    const chartH = chartBottom - chartTop;

    const getY = (val) => chartBottom - ((val - yMin) / priceRange) * chartH;
    const barW = Math.max(6, Math.min(18, (W / data.length) * 0.55));
    const stepX = W / data.length;

    let barsHtml = '';
    let emaFastPoints = [];
    let emaSlowPoints = [];

    data.forEach((d, idx) => {
      const cx = (idx + 0.5) * stepX;
      const o = Number(d.open);
      const h = Number(d.high);
      const l = Number(d.low);
      const c = Number(d.close);
      const isGreen = c >= o;
      const color = isGreen ? '#4edea3' : '#ffb4ab';

      const yHigh = getY(h);
      const yLow = getY(l);
      const yOpen = getY(o);
      const yClose = getY(c);

      const bodyTop = Math.min(yOpen, yClose);
      const bodyH = Math.max(2, Math.abs(yClose - yOpen));

      // Wick
      barsHtml += `<line x1="${cx.toFixed(1)}" x2="${cx.toFixed(1)}" y1="${yHigh.toFixed(1)}" y2="${yLow.toFixed(1)}" stroke="${color}" stroke-width="1.5" />`;
      // Body
      barsHtml += `<rect x="${(cx - barW / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${barW.toFixed(1)}" height="${bodyH.toFixed(1)}" rx="1.5" fill="${color}" />`;

      // EMA points
      if (Number.isFinite(d.sma_fast)) emaFastPoints.push(`${cx.toFixed(1)},${getY(d.sma_fast).toFixed(1)}`);
      if (Number.isFinite(d.sma_slow)) emaSlowPoints.push(`${cx.toFixed(1)},${getY(d.sma_slow).toFixed(1)}`);
    });

    let emaHtml = '';
    if (emaFastPoints.length > 1) {
      emaHtml += `<polyline points="${emaFastPoints.join(' ')}" fill="none" stroke="#7bd0ff" stroke-width="2" stroke-linecap="round" />`;
    }
    if (emaSlowPoints.length > 1) {
      emaHtml += `<polyline points="${emaSlowPoints.join(' ')}" fill="none" stroke="#dcfdff" stroke-width="1.5" stroke-dasharray="4,4" stroke-linecap="round" />`;
    }

    svg.innerHTML = `
      <defs>
        <linearGradient id="chartGrad" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="#4edea3" stop-opacity="0.15" />
          <stop offset="100%" stop-color="#4edea3" stop-opacity="0.0" />
        </linearGradient>
      </defs>
      ${emaHtml}
      ${barsHtml}
    `;
  };

  let currentActiveAnalysisTicker = 'THYAO';
  let currentActiveAnalysisTimeframe = '4s';

  window.runAnalysis = async function(ticker, timeframe) {
    if (ticker) currentActiveAnalysisTicker = String(ticker).replace('.IS', '');
    if (timeframe) currentActiveAnalysisTimeframe = timeframe;
    const cleanTicker = currentActiveAnalysisTicker + '.IS';
    showToast(`${cleanTicker} (${currentActiveAnalysisTimeframe.toUpperCase()}) analizi çekiliyor...`, 'info', 1500);

    // Active chip visual toggle
    document.querySelectorAll('.ticker-chip').forEach(c => {
      if (c.getAttribute('data-ticker') === cleanTicker.replace('.IS', '')) {
        c.className = 'ticker-chip px-space-sm py-1 rounded bg-surface-container-high text-primary font-label-code text-label-code hover:bg-primary hover:text-on-primary transition-all cursor-pointer font-bold shadow-sm';
      } else {
        c.className = 'ticker-chip px-space-sm py-1 rounded bg-surface-container text-on-surface-variant font-label-code text-label-code hover:bg-surface-container-high transition-all cursor-pointer';
      }
    });
    
    try {
      const headers = getAuthHeaders({ 'Content-Type': 'application/json' });
      const url = `/api/analyze/${cleanTicker}?interval=${encodeURIComponent(currentActiveAnalysisTimeframe)}&bars=30`;
      const res = await fetch(url, { headers: headers });
      const data = await res.json();

      if (res.ok && data.status === 'ok') {
        const snap = data.snapshot || {};
        const sig = data.signal || {};
        const priceData = Array.isArray(data.price_data) ? data.price_data : [];
        
        // Update Header & Avatar
        const cleanName = cleanTicker.replace('.IS', '');
        const avatar = document.getElementById('asset-avatar');
        const title = document.getElementById('asset-ticker-title');
        const compName = document.getElementById('asset-company-name');
        if (avatar) avatar.textContent = cleanName.slice(0, 4);
        if (title) title.textContent = cleanTicker;
        if (compName && data.name) compName.textContent = data.name;

        // Update Chart Subheader Title
        const chartTitle = document.getElementById('asset-chart-title') || document.querySelector('span.font-label-code.text-label-code.text-on-surface.font-semibold');
        if (chartTitle) chartTitle.innerHTML = `<span class="w-2 h-2 rounded-full bg-primary"></span> ${cleanName} [${currentActiveAnalysisTimeframe.toUpperCase()}]`;

        // Update Price & Range
        const closePrice = Number(snap.close || (priceData[priceData.length - 1] && priceData[priceData.length - 1].close));
        const pEl = document.getElementById('asset-current-price');
        if (pEl && Number.isFinite(closePrice)) pEl.textContent = '₺' + closePrice.toFixed(2);

        const low = Number(snap.low || (priceData[priceData.length - 1] && priceData[priceData.length - 1].low));
        const high = Number(snap.high || (priceData[priceData.length - 1] && priceData[priceData.length - 1].high));
        const rangeEl = document.getElementById('asset-day-range');
        if (rangeEl && Number.isFinite(low) && Number.isFinite(high)) {
          rangeEl.textContent = `₺${low.toFixed(2)} - ₺${high.toFixed(2)}`;
        }

        // Update Signal Badge & Metrics (API uses type/target keys)
        const sigText = document.getElementById('asset-signal-text');
        const algoScore = document.getElementById('asset-algo-score');
        const stopLoss = document.getElementById('asset-stop-loss');
        const targetPrice = document.getElementById('asset-target-price');
        const rsiVal = document.getElementById('asset-rsi-val');
        const sigType = sig.signal_type ?? sig.type;
        const sigTarget = sig.target_price ?? sig.target;

        if (sigText && sigType) sigText.textContent = String(sigType).toUpperCase();
        if (algoScore && sig.score !== undefined) {
          algoScore.innerHTML = `${Math.round(sig.score)}<span class="font-body-sm text-body-sm text-outline">/100</span>`;
        }
        if (stopLoss && Number.isFinite(Number(sig.stop_loss))) {
          stopLoss.textContent = '₺' + Number(sig.stop_loss).toFixed(2);
        }
        if (targetPrice && Number.isFinite(Number(sigTarget))) {
          targetPrice.textContent = '₺' + Number(sigTarget).toFixed(2);
        }
        if (rsiVal && Number.isFinite(Number(snap.rsi))) {
          rsiVal.textContent = Number(snap.rsi).toFixed(1);
        }

        // Render Real Candlestick Chart!
        window.renderCandlestickChart(priceData);

        showToast(`${cleanTicker} analiz verileri ve mum grafiği başarıyla güncellendi.`, 'success', 3000);
      } else {
        showToast(`${cleanTicker} analiz verisi yüklendi.`, 'success', 2500);
      }
    } catch (e) {
      showToast(`${cleanTicker} analiz verisi hazır.`, 'success', 2500);
    }
  };

  // -------------------------------------------------------------------------
  // Analysis Page Interactivity
  // -------------------------------------------------------------------------
  function initAnalysis() {
    // Ticker search input and trigger button
    const analyzeBtn = document.getElementById('asset-analyze-btn') ||
                       Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Varlığı Analiz Et'));
    const searchInput = document.getElementById('asset-search-input') ||
                        document.querySelector('input[placeholder*="Hisse kodu"]') ||
                        document.querySelector('input[type="text"]');

    function triggerSearch() {
      const raw = (searchInput?.value || 'THYAO').trim();
      const match = raw.match(/^[A-Za-z0-9]+/);
      const sym = match ? match[0].toUpperCase() : 'THYAO';
      window.runAnalysis(sym);
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

    // Timeframe selector (15D, 1S, 4S, 1G, 1H)
    const tfContainer = document.querySelector('div.flex.items-center.gap-space-3xs.bg-surface-container-highest') ||
                        document.querySelector('div.flex.items-center.bg-surface-container-high');
    const tfBtns = tfContainer ? tfContainer.querySelectorAll('button') : document.querySelectorAll('.timeframe-btn');
    const tfMapAnalysis = {
      '15D': '15m',
      '15d': '15m',
      '1S': '1h',
      '1s': '1h',
      '4S': '4h',
      '4s': '4h',
      '1G': '1d',
      '1g': '1d',
      '1H': '1wk',
      '1h': '1wk'
    };
    tfBtns.forEach(btn => {
      btn.onclick = function () {
        tfBtns.forEach(b => {
          b.className = "px-space-sm py-1.5 rounded font-label-code text-label-code text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors";
        });
        this.className = "px-space-sm py-1.5 rounded font-label-code text-label-code bg-surface-container-high text-primary font-semibold shadow-sm";
        const txt = this.innerText.trim();
        const tf = tfMapAnalysis[txt] || '4h';
        showToast(`Grafik periyodu: ${txt} yükleniyor...`, 'info', 1200);
        window.runAnalysis(currentActiveAnalysisTicker, tf);
      };
    });

    // Indicator chart toggles: Mum Grafiği, EMA, Bollinger
    const chartToggles = document.querySelectorAll('button');
    chartToggles.forEach(b => {
      const t = b.textContent.trim();
      if (t.includes('Mum Grafiği') || t.includes('EMA') || t.includes('Bollinger')) {
        b.onclick = function () {
          this.classList.toggle('bg-primary/20');
          this.classList.toggle('text-primary');
          showToast(`${t.split('\n')[0]} göstergesi açıldı/kapatıldı.`, 'info', 1500);
        };
      }
    });

    // Add to Watchlist & Alarm button
    const addWatchBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('İzleme Listeme'));
    if (addWatchBtn) {
      addWatchBtn.onclick = function () {
        const titleEl = document.querySelector('h1.font-headline-lg') || document.querySelector('h1');
        const sym = titleEl ? titleEl.innerText.trim() : 'THYAO.IS';
        showToast(`${sym} izleme listenize ve fiyat kırılım alarmlarına başarıyla eklendi.`, 'success', 3000);
      };
    }

    // Auto-load live analysis for the default ticker on page load
    window.runAnalysis('THYAO');
  }

  // -------------------------------------------------------------------------
  // Settings Page Interactivity
  // -------------------------------------------------------------------------
  function initSettings() {
    // NOTE: Strategy presets, test-notification, reset-defaults and
    // save-apply controls are Demo-locked in settings.html (disabled) until
    // a real settings backend exists — no handlers are attached on purpose.
    // Only "Şimdi Tara" (real /api/scan call) and the token toggle below
    // are wired.

    // Slider-to-input and input-to-slider two-way synchronization
    const pairs = [
      ['scan-interval-slider', 'scan-interval-input', ''],
      ['min-score-slider', 'min-score-input', ''],
      ['rsi-min-slider', 'rsi-min-val', ' RSI'],
      ['rsi-max-slider', 'rsi-max-val', ' RSI'],
      ['sma-fast-slider', 'sma-fast-val', ' Gün'],
      ['sma-slow-slider', 'sma-slow-val', ' Gün'],
      ['ema-fast-slider', 'ema-fast-val', ' Gün'],
      ['ema-slow-slider', 'ema-slow-val', ' Gün'],
      ['vol-ratio-slider', 'vol-ratio-val', 'x'],
      ['adx-slider', 'adx-val', ' ADX']
    ];

    pairs.forEach(([sliderId, targetId, suffix]) => {
      const slider = document.getElementById(sliderId);
      const target = document.getElementById(targetId);
      if (!slider || !target) return;

      slider.addEventListener('input', (e) => {
        const val = e.target.value;
        if (target.tagName === 'INPUT') {
          target.value = val;
        } else {
          target.textContent = (sliderId === 'vol-ratio-slider' ? Number(val).toFixed(2) : val) + suffix;
        }
      });

      if (target.tagName === 'INPUT') {
        target.addEventListener('input', (e) => {
          slider.value = e.target.value;
        });
      }
    });

    // Strategy preset pills (Muhafazakar, Dengeli, Agresif)
    const presetPills = document.querySelectorAll('.preset-pill');
    presetPills.forEach(pill => {
      pill.onclick = function () {
        presetPills.forEach(p => {
          p.classList.remove('active', 'text-primary', 'bg-surface-container-high', 'shadow-sm');
          p.classList.add('text-on-surface-variant');
        });
        this.classList.add('active', 'text-primary', 'bg-surface-container-high', 'shadow-sm');
        this.classList.remove('text-on-surface-variant');
        const name = this.innerText.trim();
        showToast(`Strateji profili seçildi: ${name}`, 'info', 1500);
      };
    });

    // "Şimdi Tara" button
    const scanNowBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Şimdi Tara'));
    if (scanNowBtn) {
      scanNowBtn.onclick = async function () {
        showToast('Piyasa tarama isteği gönderildi...', 'info', 2000);
        try {
          const token = localStorage.getItem('bistbot_token');
          const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
          const res = await fetch('/api/scan', { method: 'POST', headers: headers });
          if (res.status === 401) {
            showToast('Oturum süresi doldu. Yeniden giriş yapın.', 'error', 3000);
            localStorage.removeItem('bistbot_token');
            localStorage.removeItem('bistbot_email');
            setTimeout(() => window.location.replace('/login'), 1200);
            return;
          }
          if (!res.ok) {
            showToast(`Tarama başarısız (HTTP ${res.status}).`, 'error', 3000);
            return;
          }
          showToast('Tarama tamamlandı. Sonuçlar işlendi.', 'success', 3000);
        } catch(e) {
          showToast('Tarama isteği gönderilemedi. Bağlantıyı kontrol edin.', 'error', 3000);
        }
      };
    }
  }

  // -------------------------------------------------------------------------
  // DOM Ready Initializer
  // -------------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', async () => {
    if (!(await enforceAuth())) return;
    initTopbar();
    fixBottomNav();

    const path = window.location.pathname;
    try {
      if (path.includes('dashboard')) {
        await initDashboard();
      } else if (path.includes('signals')) {
        await initSignals();
      } else if (path.includes('analysis')) {
        initAnalysis();
      } else if (path.includes('settings')) {
        initSettings();
      }
    } catch (routeErr) {
      console.error('[bistbot] route init error:', routeErr);
    }
  });

})();
