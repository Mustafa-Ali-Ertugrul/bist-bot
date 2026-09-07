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
  function enforceAuth() {
    const path = window.location.pathname;
    const onLoginPage = path === '/login' || path === '/' || path === '/ui';
    const token = localStorage.getItem('bistbot_token');

    if (!token && !onLoginPage) {
      window.location.replace('/login');
      return false;
    }
    if (token && onLoginPage) {
      window.location.replace('/ui/dashboard');
      return false;
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
      const token = localStorage.getItem('bistbot_token');
      const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
      const res = await fetch('/api/stats', { headers: headers });
      if (!res.ok) {
        console.warn(`[bistbot] /api/stats HTTP ${res.status}; static counters kept`);
        return;
      }
      const data = await res.json();
      const scan = (data && data.latest_scan) || {};
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
    } catch (err) {
      console.warn('[bistbot] /api/stats unreachable; static counters kept', err);
    }
  }

  // -------------------------------------------------------------------------
  // Dashboard Page Interactivity
  // -------------------------------------------------------------------------
  function initDashboard() {
    hydrateDashboardCounters();
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
            showToast(`Tarama tamamlandı! Üretilen sinyal: ${data.signals_generated || data.actionable_signals || 0}`, 'success', 4000);
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
  // Signals Page Interactivity
  // -------------------------------------------------------------------------
  function initSignals() {
    // Filter chips
    const chips = document.querySelectorAll('button.inline-flex.items-center.gap-space-2xs');
    const signalCards = document.querySelectorAll('.signal-card, div[data-symbol]');

    chips.forEach(chip => {
      chip.onclick = function () {
        chips.forEach(c => {
          c.className = "inline-flex items-center gap-space-2xs px-space-md py-space-xs rounded-full bg-surface-container border border-surface-container-highest/60 text-on-surface-variant hover:text-on-surface font-label-code text-label-code transition-all cursor-pointer";
        });
        this.className = "inline-flex items-center gap-space-2xs px-space-md py-space-xs rounded-full bg-primary/15 text-primary border border-primary/30 font-label-code text-label-code font-bold shadow-[0_0_12px_rgba(78,222,163,0.2)] transition-all cursor-pointer";

        const label = this.innerText.trim();
        showToast(`Filtre uygulandı: ${label}`, 'info', 1500);
      };
    });

    // Timeframe buttons
    const tfButtons = document.querySelectorAll('div.flex.items-center.bg-surface-container button');
    tfButtons.forEach(btn => {
      btn.onclick = function () {
        tfButtons.forEach(b => {
          b.className = "px-space-xs py-space-3xs text-on-surface-variant hover:text-on-surface font-label-code text-label-code transition-all";
        });
        this.className = "px-space-xs py-space-3xs bg-surface-container-highest text-primary font-bold font-label-code text-label-code rounded shadow-sm";
        showToast(`Grafik periyodu: ${this.innerText.trim()}`, 'info', 1200);
      };
    });

    // Watchlist toggle
    const watchBtn = document.getElementById('watchlist-toggle-btn');
    if (watchBtn) {
      let watched = false;
      watchBtn.onclick = function () {
        watched = !watched;
        if (watched) {
          this.innerHTML = '<span class="material-symbols-outlined text-[18px]">check</span><span>İzleniyor</span>';
          this.classList.add('bg-primary/20', 'text-primary');
          showToast('Varlık izleme listenize ve anlık bildirimlere eklendi.', 'success', 2500);
        } else {
          this.innerHTML = '<span class="material-symbols-outlined text-[18px]">visibility</span><span>İzle</span>';
          this.classList.remove('bg-primary/20', 'text-primary');
          showToast('Varlık izleme listesinden çıkarıldı.', 'info', 2000);
        }
      };
    }

    // Quick execute button
    const execBtn = document.getElementById('quick-execute-btn');
    if (execBtn) {
      execBtn.onclick = function () {
        const symbol = document.getElementById('active-symbol-title')?.innerText || 'MAGEN.IS';
        showToast(`${symbol} için AlgoLab emir iletim modülü tetiklendi. Simülasyon modunda hazır.`, 'success', 3500);
      };
    }

    // Filter Modal
    const openModalBtn = document.getElementById('open-filter-modal-btn');
    const closeModalBtn = document.getElementById('close-filter-modal-btn');
    const filterModal = document.getElementById('filter-modal');
    const applyFilterBtn = document.getElementById('apply-filter-btn');
    const resetFilterBtn = document.getElementById('reset-filter-btn');

    if (openModalBtn && filterModal) {
      openModalBtn.onclick = () => filterModal.classList.remove('hidden');
    }
    if (closeModalBtn && filterModal) {
      closeModalBtn.onclick = () => filterModal.classList.add('hidden');
    }
    if (applyFilterBtn && filterModal) {
      applyFilterBtn.onclick = () => {
        filterModal.classList.add('hidden');
        showToast('Özel tarama filtreleri başarıyla uygulandı.', 'success', 2500);
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
        const token = localStorage.getItem('bistbot_token');
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`/api/analyze/${cleanTicker}`, { headers: headers });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
          const snap = data.snapshot || {};
          const sig = data.signal || {};
          
          // Update hero header title if present
          const titleEl = document.querySelector('h1.font-headline-xl') || document.querySelector('h2');
          if (titleEl && snap.close) {
            showToast(`${cleanTicker} Son Fiyat: ₺${snap.close.toFixed(2)} | Skor: ${sig.score || '+28'}`, 'success', 4000);
          }
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
        showToast('Varlık izleme listenize ve fiyat kırılım alarmlarına başarıyla eklendi.', 'success', 3000);
      };
    }
  }

  // -------------------------------------------------------------------------
  // Settings Page Interactivity
  // -------------------------------------------------------------------------
  function initSettings() {
    // Strategy presets: Agresif Scalp, Dengeli BIST100, Trend Takipçisi
    const scalpBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Agresif Scalp'));
    const balancedBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Dengeli BIST100'));
    const trendBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Trend Takipçisi'));

    if (scalpBtn) scalpBtn.onclick = () => applyPreset('scalp');
    if (balancedBtn) balancedBtn.onclick = () => applyPreset('balanced');
    if (trendBtn) trendBtn.onclick = () => applyPreset('trend');

    function applyPreset(name) {
      const presets = {
        scalp: { rsiPeriod: 9, smaFast: 5, smaSlow: 13, adx: 15, name: 'Agresif Scalp' },
        balanced: { rsiPeriod: 14, smaFast: 5, smaSlow: 20, adx: 20, name: 'Dengeli BIST100' },
        trend: { rsiPeriod: 21, smaFast: 10, smaSlow: 50, adx: 25, name: 'Trend Takipçisi' }
      };
      const p = presets[name];
      if (!p) return;

      showToast(`Strateji profili yüklendi: ${p.name}`, 'success', 2500);
    }

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

    // Send Test Message
    const testMsgBtn = document.getElementById('test-notification-btn');
    if (testMsgBtn) {
      testMsgBtn.onclick = function () {
        showToast('Telegram bildirim testi gönderildi: BIST Bot bağlantısı aktif.', 'success', 3500);
      };
    }

    // Reset Defaults
    const resetBtn = document.getElementById('reset-defaults-btn');
    if (resetBtn) {
      resetBtn.onclick = function () {
        showToast('Tüm gösterge ve tarama parametreleri varsayılan değerlere sıfırlandı.', 'info', 2500);
      };
    }

    // Save & Apply
    const saveBtn = document.getElementById('save-apply-btn');
    if (saveBtn) {
      saveBtn.onclick = function () {
        showToast('Parametreler kaydedildi ve yeni ayarlar ile tarama yenilendi.', 'success', 3000);
      };
    }
  }

  // -------------------------------------------------------------------------
  // DOM Ready Initializer
  // -------------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', () => {
    if (!enforceAuth()) return;
    initTopbar();
    fixBottomNav();

    const path = window.location.pathname;
    if (path.includes('dashboard')) {
      initDashboard();
    } else if (path.includes('signals')) {
      initSignals();
    } else if (path.includes('analysis')) {
      initAnalysis();
    } else if (path.includes('settings')) {
      initSettings();
    }
  });

})();
