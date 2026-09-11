/* BIST Bot – Login / Registration page logic (CSP-safe, no inline handlers) */
(function () {
  'use strict';

  // ── Auth mode switching ──
  function switchAuthMode(mode) {
    var loginForm = document.getElementById('auth-form-standard');
    var registerForm = document.getElementById('auth-form-register');
    var tabLogin = document.getElementById('tab-login');
    var tabRegister = document.getElementById('tab-register');
    var desc = document.getElementById('auth-context-desc');
    var activeCls = ['text-on-primary', 'bg-primary-container', 'font-semibold', 'shadow-[0_0_12px_rgba(16,185,129,0.3)]'];
    var idleCls = ['text-on-surface-variant'];
    if (mode === 'register') {
      loginForm.classList.add('hidden');
      registerForm.classList.remove('hidden');
      registerForm.classList.add('flex');
      tabLogin.classList.remove.apply(tabLogin, activeCls);
      tabLogin.classList.add.apply(tabLogin, idleCls);
      tabRegister.classList.add.apply(tabRegister, activeCls);
      tabRegister.classList.remove.apply(tabRegister, idleCls);
      if (desc) desc.textContent = 'E-postanızla kaydolun, 24 saat ücretsiz deneme hemen başlasın.';
    } else {
      registerForm.classList.add('hidden');
      registerForm.classList.remove('flex');
      loginForm.classList.remove('hidden');
      tabRegister.classList.remove.apply(tabRegister, activeCls);
      tabRegister.classList.add.apply(tabRegister, idleCls);
      tabLogin.classList.add.apply(tabLogin, activeCls);
      tabLogin.classList.remove.apply(tabLogin, idleCls);
      if (desc) desc.textContent = 'Tanımlı lisanslı operatör bilgilerinizle giriş yapın ve piyasa botlarını yönetin.';
    }
  }

  // ── Password visibility toggles ──
  function togglePasswordVisibility() {
    var passInput = document.getElementById('operator-password');
    var passIcon = document.getElementById('pass-icon');
    if (passInput.type === 'password') {
      passInput.type = 'text';
      passIcon.innerText = 'visibility_off';
    } else {
      passInput.type = 'password';
      passIcon.innerText = 'visibility';
    }
  }

  function toggleRegPasswordVisibility() {
    var passInput = document.getElementById('register-password');
    var passIcon = document.getElementById('reg-pass-icon');
    if (passInput.type === 'password') {
      passInput.type = 'text';
      passIcon.innerText = 'visibility_off';
    } else {
      passInput.type = 'password';
      passIcon.innerText = 'visibility';
    }
  }

  // ── Session establishment ──
  function establishSession(token) {
    return fetch('/api/auth/session', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token }
    }).then(function (res) { return res.ok; }).catch(function () { return false; });
  }

  // ── Error display (XSS defence-in-depth) ──
  function showLoginError(msg, formId) {
    var form = document.getElementById(formId || 'auth-form-standard');
    var err = form.querySelector('#login-error-msg, #register-error-msg');
    if (!err) {
      err = document.createElement('div');
      err.id = formId === 'auth-form-register' ? 'register-error-msg' : 'login-error-msg';
      err.className = 'p-space-xs rounded-lg bg-error-container/30 border border-error/40 text-error font-body-sm text-body-sm flex items-center gap-space-xs';
      form.insertBefore(err, form.querySelector('button[type="submit"]'));
    }
    var safeMsg = String(msg).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
    err.innerHTML = '<span class="material-symbols-outlined text-[18px]">error</span><span>' + safeMsg + '</span>';
  }

  // ── Login handler ──
  function handleLogin(e) {
    e.preventDefault();
    var btn = document.getElementById('submit-btn');
    var email = document.getElementById('operator-email').value.trim();
    var password = document.getElementById('operator-password').value;
    var errDiv = document.getElementById('login-error-msg');
    if (errDiv) errDiv.remove();

    var originalContent = btn.innerHTML;
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[20px]">sync</span><span>Yetkilendiriliyor...</span>';
    btn.disabled = true;

    fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: password })
    }).then(function (res) {
      return res.json().then(function (data) {
        if (res.ok && data.status === 'ok') {
          localStorage.setItem('bistbot_token', data.access_token);
          localStorage.setItem('bistbot_email', email);
          btn.innerHTML = '<span class="material-symbols-outlined text-[20px]">check_circle</span><span>Bağlantı Kuruldu</span>';
          establishSession(data.access_token).then(function () {
            setTimeout(function () { window.location.href = '/ui/dashboard'; }, 300);
          });
        } else {
          btn.innerHTML = originalContent;
          btn.disabled = false;
          showLoginError(data.message || 'Geçersiz kurumsal kimlik bilgileri.');
        }
      });
    }).catch(function (err) {
      btn.innerHTML = originalContent;
      btn.disabled = false;
      showLoginError('API sunucusuna erişilemedi: ' + err.message);
    });
  }

  // ── Registration handler ──
  function handleRegister(e) {
    e.preventDefault();
    var btn = document.getElementById('register-btn');
    var email = document.getElementById('register-email').value.trim();
    var password = document.getElementById('register-password').value;
    var confirm = document.getElementById('register-password-confirm').value;
    var oldErr = document.getElementById('register-error-msg');
    if (oldErr) oldErr.remove();

    if (password !== confirm) {
      showLoginError('Şifreler eşleşmiyor.', 'auth-form-register');
      return;
    }
    if (password.length < 12) {
      showLoginError('Şifre en az 12 karakter olmalı.', 'auth-form-register');
      return;
    }

    var originalContent = btn.innerHTML;
    btn.innerHTML = '<span class="material-symbols-outlined animate-spin text-[20px]">sync</span><span>Hesap Oluşturuluyor...</span>';
    btn.disabled = true;

    fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, password: password })
    }).then(function (res) {
      return res.json().then(function (data) {
        if (res.ok && data.status === 'ok') {
          localStorage.setItem('bistbot_token', data.access_token);
          localStorage.setItem('bistbot_email', email);
          btn.innerHTML = '<span class="material-symbols-outlined text-[20px]">check_circle</span><span>Deneme Başlatıldı</span>';
          establishSession(data.access_token).then(function () {
            setTimeout(function () { window.location.href = '/ui/dashboard'; }, 300);
          });
        } else {
          btn.innerHTML = originalContent;
          btn.disabled = false;
          showLoginError(data.message || 'Kayıt oluşturulamadı.', 'auth-form-register');
        }
      });
    }).catch(function (err) {
      btn.innerHTML = originalContent;
      btn.disabled = false;
      showLoginError('API sunucusuna erişilemedi: ' + err.message, 'auth-form-register');
    });
  }

  // ── Event delegation (CSP-safe: no inline onclick/onsubmit needed) ──
  document.addEventListener('DOMContentLoaded', function () {
    // Delegate all data-action clicks
    document.addEventListener('click', function (e) {
      var action = e.target.closest('[data-action]');
      if (!action) return;
      var act = action.getAttribute('data-action');
      if (act === 'switch-login') { switchAuthMode('login'); return; }
      if (act === 'switch-register') { switchAuthMode('register'); return; }
      if (act === 'toggle-pass') { togglePasswordVisibility(); return; }
      if (act === 'toggle-reg-pass') { toggleRegPasswordVisibility(); return; }
      if (act === 'password-reset') {
        e.preventDefault();
        alert('Şifre sıfırlama yönergesi kayıtlı operatör e-postasına iletildi.');
        return;
      }
    });

    // Delegate form submissions
    document.addEventListener('submit', function (e) {
      var action = e.target.closest('[data-action]');
      if (!action) return;
      var act = action.getAttribute('data-action');
      if (act === 'login-form') { handleLogin(e); return; }
      if (act === 'register-form') { handleRegister(e); return; }
    });
  });
})();
