# Agentflow Step: 03-test

- Agent: flow-tester
- Model: 9router/gemini-3.1-flash-lite-preview
- Started: 2026-05-30T19:13:33.2200805+03:00
scan_logs tool placeholder
pytest_changed tool placeholder
market_data_health tool placeholder
config_audit tool placeholder
Build step fail. Error: Unauthorized: Internal server error.

`src/bist_bot/auth/passwords.py` exists, uses `werkzeug.security` and `bcrypt`. No registration logic found in `src/bist_bot/auth`. 

Next step: check `src/bist_bot/streamlit_app.py` for registration entry point.

## STDERR
[0m
> flow-tester · gemini-3.1-flash-lite-preview
[0m
[0m$ [0mpytest --version
pytest 9.0.3
[0m
[0m$ [0mdir src\bist_bot\auth
Directory: C:\Users\Ali\OneDrive\Masa�st�\bist_bot\src\bist_bot\auth


Mode                 LastWriteTime         Length Name                                                                 
----                 -------------         ------ ----                                                                 
d-----         1.05.2026     22:42                __pycache__                                                          
-a----        28.04.2026     09:26           1396 passwords.py                                                         
-a----        21.04.2026     18:24            168 __init__.py
[0m
[0m$ [0mtype src\bist_bot\auth\passwords.py
"""Modern password hashing with scrypt and legacy bcrypt fallback."""

from __future__ import annotations

from typing import cast

import bcrypt
from werkzeug.security import check_password_hash, generate_password_hash

_MODERN_HASH_PREFIX = "scrypt:"


def hash_password(password: str) -> str:
    return cast(str, generate_password_hash(password, method="scrypt"))


def _is_modern_hash(password_hash: str) -> bool:
    return password_hash.startswith((_MODERN_HASH_PREFIX, "pbkdf2:"))


def _is_bcrypt_hash(password_hash: str) -> bool:
    return password_hash.startswith(("$2a$", "$2b$", "$2y$"))


def verify_and_rehash_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    if not password_hash:
        return False, None

    if _is_modern_hash(password_hash):
        if not check_password_hash(password_hash, password):
            return False, None
        if not password_hash.startswith(_MODERN_HASH_PREFIX):
            return True, hash_password(password)
        return True, None

    if _is_bcrypt_hash(password_hash):
        try:
            verified = bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            return False, None
        if not verified:
            return False, None
        return True, hash_password(password)

    return False, None
[0m
[0m# [0mTodos
[•] Verify auth registration failure
[ ] Report registration failure diagnosis
[0m
