"""AppSec Round 4: UI XSS defence-in-depth regression guard.

login.html::showLoginError bugün yalnızca sunucu/tarayıcı kaynaklı mesajlar
alıyor; bu test, ileride kullanıcı kontrollü bir alan yansıtılırsa bile
HTML escape'in yerinde kalmasını güvence altına alır.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGIN_TEMPLATE = REPO_ROOT / "src" / "bist_bot" / "templates" / "stitch" / "login.html"


def _read_template() -> str:
    assert LOGIN_TEMPLATE.exists(), "login.html bulunamadı"
    return LOGIN_TEMPLATE.read_text(encoding="utf-8")


def test_show_login_error_escapes_html_entities() -> None:
    """showLoginError, msg'i innerHTML'e koymadan ÖNCE escape etmeli."""
    content = _read_template()
    assert "safeMsg" in content, (
        "showLoginError mesajı escape edilmeden innerHTML'e yazılıyor — "
        "XSS defence-in-depth zinciri kırılmış olabilir."
    )
    # Escape map + safeMsg kullanımı birlikte var olmalı.
    assert "&amp;" in content
    assert "safeMsg" in content


def test_admin_template_escapes_user_data() -> None:
    """admin.html kullanıcı satırlarında esc() helper'ı kullanmalı."""
    admin = REPO_ROOT / "src" / "bist_bot" / "templates" / "stitch" / "admin.html"
    assert admin.exists(), "admin.html bulunamadı"
    content = admin.read_text(encoding="utf-8")
    assert "function esc(" in content
    # Kullanıcı verisi kolonları esc() ile yazılır.
    assert "esc(u.email)" in content
    assert "esc(r.email)" in content
