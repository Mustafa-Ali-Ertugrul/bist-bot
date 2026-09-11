"""AppSec Round 4: UI XSS defence-in-depth regression guard.

login.html::showLoginError bugün yalnızca sunucu/tarayıcı kaynaklı mesajlar
alıyor; bu test, ileride kullanıcı kontrollü bir alan yansıtılırsa bile
HTML escape'in yerinde kalmasını güvence altına alır.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGIN_TEMPLATE = REPO_ROOT / "src" / "bist_bot" / "templates" / "stitch" / "login.html"
LOGIN_JS = REPO_ROOT / "src" / "bist_bot" / "static" / "login.js"
ADMIN_TEMPLATE = REPO_ROOT / "src" / "bist_bot" / "templates" / "stitch" / "admin.html"
ADMIN_JS = REPO_ROOT / "src" / "bist_bot" / "static" / "admin.js"


def _read_template() -> str:
    assert LOGIN_TEMPLATE.exists(), "login.html bulunamadı"
    return LOGIN_TEMPLATE.read_text(encoding="utf-8")


def _read_login_js() -> str:
    assert LOGIN_JS.exists(), "login.js bulunamadı"
    return LOGIN_JS.read_text(encoding="utf-8")


def _read_admin_js() -> str:
    assert ADMIN_JS.exists(), "admin.js bulunamadı"
    return ADMIN_JS.read_text(encoding="utf-8")


def test_show_login_error_escapes_html_entities() -> None:
    """showLoginError, msg'i innerHTML'e koymadan ÖNCE escape etmeli."""
    # CSP-safe: mantık login.html inline değil login.js içinde yaşar.
    content = _read_template() + "\n" + _read_login_js()
    js = _read_login_js()
    assert "safeMsg" in js, (
        "showLoginError mesajı escape edilmeden innerHTML'e yazılıyor — "
        "XSS defence-in-depth zinciri kırılmış olabilir."
    )
    # Escape map + safeMsg kullanımı birlikte var olmalı.
    assert "&amp;" in content
    assert "safeMsg" in content


def test_admin_template_escapes_user_data() -> None:
    """admin.html kullanıcı satırlarında esc() helper'ı kullanmalı."""
    assert ADMIN_TEMPLATE.exists(), "admin.html bulunamadı"
    # CSP-safe: esc() helper'ı inline değil admin.js içinde yaşar.
    content = _read_admin_js()
    assert "function esc(" in content
    # Kullanıcı verisi kolonları esc() ile yazılır.
    assert "esc(u.email)" in content
    assert "esc(r.email)" in content
