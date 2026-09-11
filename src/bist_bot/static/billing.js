/* BIST Bot – Billing page logic (CSP-safe, no inline handlers) */
(function () {
  'use strict';
  var selectedPlan = null;
  var billingInfo = null;

  function authHeaders() {
    var t = localStorage.getItem('bistbot_token');
    return t ? { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' } : {};
  }

  function selectBillingPlan(plan) {
    selectedPlan = plan;
    ['pro', 'pro_plus'].forEach(function (p) {
      var card = document.getElementById(p === 'pro' ? 'card-pro' : 'card-pro-plus');
      if (card) card.classList.toggle('border-primary', p === plan);
    });
    var st = document.getElementById('billing-status');
    if (st) st.textContent = plan === 'pro_plus'
      ? 'Pro+ seçildi: ödeme sonrası özel Telegram kanalı davet linki oluşturulur.'
      : 'Pro seçildi.';
  }

  function submitBillingClaim() {
    var st = document.getElementById('billing-status');
    if (!selectedPlan) {
      if (st) st.textContent = 'Lütfen önce bir plan seçin.';
      return;
    }
    if (st) st.textContent = 'Bildirim gönderiliyor...';
    fetch('/api/billing/claim', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ plan: selectedPlan })
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) {
          if (st) st.textContent = data.message || 'Bildirim alınamadı.';
          return;
        }
        var req = data.request || {};
        var ref = document.getElementById('billing-ref');
        if (ref) ref.textContent = req.reference || '—';
        if (st) st.textContent = data.duplicate
          ? 'Bu plan için zaten bekleyen bir bildiriminiz var. Onay sonrası planınız aktiflenir.'
          : 'Ödeme bildiriminiz alındı! Açıklamaya referans kodunu yazdığınızdan emin olun. Onay sonrası planınız aktiflenir.';
      });
    }).catch(function () {
      if (st) st.textContent = 'Bağlantı hatası, lütfen tekrar deneyin.';
    });
  }

  function loadBilling() {
    fetch('/api/billing/info', { headers: authHeaders() }).then(function (infoRes) {
      if (infoRes.ok) {
        return infoRes.json().then(function (info) {
          billingInfo = info;
          var iban = document.getElementById('billing-iban');
          if (iban && billingInfo.iban) iban.textContent = billingInfo.iban;
          var pp = document.getElementById('price-pro');
          if (pp && billingInfo.pro_price_try) pp.textContent = billingInfo.pro_price_try;
          var ppp = document.getElementById('price-pro-plus');
          if (ppp && billingInfo.pro_plus_price_try) ppp.textContent = billingInfo.pro_plus_price_try;
        });
      }
    }).catch(function () { /* ignore */ });

    fetch('/api/me/subscription', { headers: authHeaders() }).then(function (subRes) {
      if (subRes.ok) {
        return subRes.json().then(function (sub) {
          var labels = { trial: 'Deneme', pro: 'Pro', pro_plus: 'Pro+' };
          var name = document.getElementById('billing-plan-name');
          var detail = document.getElementById('billing-plan-detail');
          if (name) name.textContent = labels[sub.plan] || sub.plan;
          if (detail) {
            detail.textContent = sub.status === 'active'
              ? 'Planınız aktif. Kalan süre dolmadan yenileyebilirsiniz.'
              : 'Planınızın süresi dolmuş. Devam etmek için yukarıdan bir plan seçip ödemenizi bildirin.';
          }
        });
      }
    }).catch(function () { /* ignore */ });

    fetch('/api/billing/mine', { headers: authHeaders() }).then(function (mineRes) {
      if (mineRes.ok) {
        return mineRes.json().then(function (mine) {
          var pending = (mine.requests || []).find(function (r) { return r.status === 'pending'; });
          var st = document.getElementById('billing-status');
          if (pending) {
            var ref = document.getElementById('billing-ref');
            if (ref) ref.textContent = pending.reference;
            if (st) st.textContent = 'Bekleyen ödemeniz admin onayında. Referans: ' + pending.reference;
          }
        });
      }
    }).catch(function () { /* ignore */ });
  }

  // ── Event delegation (CSP-safe: no inline onclick needed) ──
  document.addEventListener('DOMContentLoaded', function () {
    loadBilling();

    document.addEventListener('click', function (e) {
      var planBtn = e.target.closest('[data-plan]');
      if (planBtn) {
        e.preventDefault();
        selectBillingPlan(planBtn.getAttribute('data-plan'));
        return;
      }
      if (e.target.closest('#billing-claim-btn')) {
        e.preventDefault();
        submitBillingClaim();
      }
    });
  });
})();
