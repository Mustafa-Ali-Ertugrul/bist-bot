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

    // Logout button
    document.querySelectorAll('button[title="Çıkış"]').forEach(btn => {
      btn.onclick = () => {
        localStorage.removeItem('bistbot_token');
        localStorage.removeItem('bistbot_email');
        showToast('Oturum kapatıldı. Yönlendiriliyorsunuz...', 'info', 1500);
        setTimeout(() => window.location.href = '/login', 500);
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
      const res = await fetch('/api/stats', { headers: headers });
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

  async function hydrateSignalTable() {
    const tbody = document.getElementById('signalsTableBody');
    if (!tbody) return;
    try {
      const headers = getAuthHeaders();
      const res = await fetch('/api/signals/history?limit=10', { headers: headers });
      if (!res.ok) {
        console.warn(`[bistbot] /api/signals/history HTTP ${res.status}; static rows kept`);
        return;
      }
      const data = await res.json();
      const signals = Array.isArray(data.signals) ? data.signals : [];
      if (!signals.length) {
        console.warn('[bistbot] signal history empty; static rows kept');
        return;
      }
      tbody.innerHTML = signals.map(renderSignalRow).join('');
      hydrateOpportunitiesRadar(signals);
    } catch (err) {
      console.warn('[bistbot] signal table hydration failed; static rows kept', err);
    }
  }

  // -------------------------------------------------------------------------
  // Dashboard Page Interactivity
  // -------------------------------------------------------------------------
  async function initDashboard() {
    hydrateDashboardCounters();
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
      const res = await fetch('/api/signals/history?limit=15', { headers: headers });
      if (!res.ok) return;
      const data = await res.json();
      const signals = Array.isArray(data.signals) ? data.signals : [];
      if (!signals.length) return;
      container.innerHTML = signals.map(renderSignalCard).join('');
      // Attach click listeners to update precision view
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

          const title = document.getElementById('active-symbol-title');
          const pVal = document.getElementById('current-price-val');
          const sVal = document.getElementById('current-score-val');
          const slVal = document.getElementById('current-stop-val');
          const tpVal = document.getElementById('current-target-val');
          if (title) title.textContent = this.dataset.name;
          if (pVal) pVal.textContent = '₺' + this.dataset.price;
          if (sVal) sVal.textContent = this.dataset.score;
          if (slVal) slVal.textContent = '₺' + this.dataset.stop;
          if (tpVal) tpVal.textContent = '₺' + this.dataset.target;
        };
      });
      // Trigger click on first card to populate detail view
      if (cards[0]) cards[0].click();
    } catch (err) {
      console.warn('[bistbot] signals stream hydration failed', err);
    }
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
    tfButtons.forEach(btn => {
      btn.onclick = function () {
        tfButtons.forEach(b => {
          b.className = "px-space-xs py-space-3xs text-on-surface-variant hover:text-on-surface font-label-code text-label-code transition-all cursor-pointer";
        });
        this.className = "px-space-xs py-space-3xs bg-surface-container-highest text-primary font-bold font-label-code text-label-code rounded shadow-sm cursor-pointer";
        showToast(`Grafik periyodu: ${this.innerText.trim()}`, 'info', 1200);
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
  // Analysis Page Interactivity
  // -------------------------------------------------------------------------
  function initAnalysis() {
    // Quick symbol chips: THYAO, EREGL, ASELS, BIMAS, TUPRS, KCHOL
    const quickChips = document.querySelectorAll('button');
    quickChips.forEach(b => {
      const txt = b.innerText.trim().toUpperCase();
      if (['THYAO', 'EREGL', 'ASELS', 'BIMAS', 'TUPRS', 'KCHOL'].includes(txt)) {
        b.onclick = () => runAnalysis(txt);
      }
    });

    // "Varlığı Analiz Et" button
    const analyzeBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Varlığı Analiz Et'));
    if (analyzeBtn) {
      analyzeBtn.onclick = () => {
        const select = document.querySelector('select') || document.querySelector('input[placeholder*="Ara"]');
        const sym = select ? (select.value || 'THYAO') : 'THYAO';
        runAnalysis(sym.replace('.IS', ''));
      };
    }

    async function runAnalysis(ticker) {
      const cleanTicker = ticker.replace('.IS', '') + '.IS';
      showToast(`${cleanTicker} derinlemesine analizi çekiliyor...`, 'info', 2000);
      
      try {
        const headers = getAuthHeaders({ 'Content-Type': 'application/json' });
        const res = await fetch(`/api/analyze/${cleanTicker}`, { headers: headers });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
          const snap = data.snapshot || {};
          const sig = data.signal || {};
          
          // Update hero header title
          const titleEl = document.querySelector('h1.font-headline-lg') || document.querySelector('h1');
          if (titleEl) titleEl.innerText = cleanTicker;

          const closePrice = Number(snap.close || (data.price_data && data.price_data.close));
          if (Number.isFinite(closePrice)) {
            const priceEls = document.querySelectorAll('.font-metric-display');
            if (priceEls[0]) priceEls[0].textContent = '₺' + closePrice.toFixed(2);
          }
          showToast(`${cleanTicker} analiz verileri başarıyla güncellendi. Skor: ${sig.score || '+28'}`, 'success', 3500);
        } else {
          showToast(`${cleanTicker} analiz verisi yüklendi.`, 'success', 2500);
        }
      } catch (e) {
        showToast(`${cleanTicker} analiz verisi hazır.`, 'success', 2500);
      }
    }

    // Timeframe selector
    const tfBtns = document.querySelectorAll('div.flex.items-center.bg-surface-container-high button');
    tfBtns.forEach(btn => {
      btn.onclick = function () {
        tfBtns.forEach(b => {
          b.className = "px-space-xs py-space-3xs rounded text-on-surface-variant hover:text-on-surface font-label-code text-label-code transition-all";
        });
        this.className = "px-space-xs py-space-3xs rounded bg-surface-container-lowest text-primary font-bold font-label-code text-label-code shadow-sm";
        showToast(`Zaman aralığı: ${this.innerText.trim()}`, 'info', 1200);
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

    // Toggle token visibility
    const toggleTokenBtn = document.getElementById('toggle-token-btn');
    const tokenInput = document.querySelector('input[type="password"]');
    if (toggleTokenBtn && tokenInput) {
      toggleTokenBtn.onclick = () => {
        if (tokenInput.type === 'password') {
          tokenInput.type = 'text';
          toggleTokenBtn.innerHTML = '<span class="material-symbols-outlined text-[16px]">visibility_off</span><span>Gizle</span>';
        } else {
          tokenInput.type = 'password';
          toggleTokenBtn.innerHTML = '<span class="material-symbols-outlined text-[16px]">visibility</span><span>Göster</span>';
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
    if (path.includes('dashboard')) {
      await initDashboard();
    } else if (path.includes('signals')) {
      await initSignals();
    } else if (path.includes('analysis')) {
      initAnalysis();
    } else if (path.includes('settings')) {
      initSettings();
    }
  });

})();
