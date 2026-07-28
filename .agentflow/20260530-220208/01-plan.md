# Agentflow Step: 01-plan

- Agent: plan
- Model: opencode/deepseek-v4-flash-free
- Started: 2026-05-30T22:02:08.6738982+03:00
scan_logs tool placeholder
pytest_changed tool placeholder
market_data_health tool placeholder
config_audit tool placeholder
Let me inspect the current state of the registration code more closely.
Let me check the existing tests and the auth settings configuration more closely.
Let me check the current test status and the locale files for registration messages.
Let me run the full auth test suite to see all failures, and also check if `.env.example` has `ALLOW_PUBLIC_REGISTRATION`.
Now I have a complete picture. Here's the plan:

---

## Plan: "kayit olmayi ekle" — Fix Registration Tests

### Problem Restatement

Registration (kayıt olma) **already exists** in the codebase: a `POST /api/auth/register` endpoint in `dashboard.py` and a "Kayıt Ol" tab in `streamlit_app.py`. However, **3 tests are failing** due to Turkish character mismatches between test expectations and locale strings, making CI/verification fail.

### Relevant Files Inspected

| File | Status |
|------|--------|
| `src/bist_bot/dashboard.py` (lines 304–410) | Register endpoint + `create_user()` — looks correct |
| `src/bist_bot/streamlit_app.py` (lines 221–257) | "Kayıt Ol" UI tab — looks correct |
| `src/bist_bot/locales/tr.py` (lines 60–63) | Has proper Turkish locale strings |
| `src/bist_bot/config/subsettings.py` (line 296) | `ALLOW_PUBLIC_REGISTRATION` setting |
| `.env` | `ALLOW_PUBLIC_REGISTRATION=true` — already enabled |
| `tests/test_auth.py` (lines 180–198, 408–434) | **3 test assertions with wrong character encodings** |

### Failing Tests (3 failures in `tests/test_auth.py`)

| # | Test | Line | Expected (wrong) | Actual (correct) |
|---|------|------|-----------------|-----------------|
| 1 | `test_register_returns_403_when_public_registration_disabled` | 191 | `'Herkese acik kayit kapali'` | `'Herkese açık kayıt kapalı'` |
| 2 | `test_register_rejects_duplicate_email` | 419 | `'Bu email zaten kayitli'` | `'Bu e-posta zaten kayıtlı'` |
| 3 | `test_register_rejects_short_password` | 433 | `'Sifre en az 8 karakter olmali'` | `'Şifre en az 8 karakter olmalı'` |

The locale file (`tr.py`) uses proper Turkish Unicode characters (ç, ı, ö, ü, ş, ğ). The tests were written with ASCII approximations. The tests need to match the locale.

### Implementation Steps

1. **Fix `tests/test_auth.py` line 191**: Change `'Herkese acik kayit kapali'` → `'Herkese açık kayıt kapalı'`
2. **Fix `tests/test_auth.py` line 419**: Change `'Bu email zaten kayitli'` → `'Bu e-posta zaten kayıtlı'`
3. **Fix `tests/test_auth.py` line 433**: Change `'Sifre en az 8 karakter olmali'` → `'Şifre en az 8 karakter olmalı'`

### Risk Points

- **Low risk** — only test string literals are changing
- No production code, no config, no schema changes
- The register endpoint, `create_user()`, and Streamlit UI all remain untouched

### Verification Commands

```powershell
# After fixes:
python -m pytest tests/test_auth.py -v --tb=short

# Broader check for regressions:
python -m pytest tests/test_passwords.py -v

# Lint:
ruff check tests/test_auth.py
```

### Assumptions

- The user wants the registration feature to pass tests and work correctly, which it already does functionally
- The Turkish locale strings in `tr.py` are the correct/authoritative versions
- No additional registration features (email verification, password reset, etc.) are needed

### Handoff Instructions for Coding Stage

1. Read `tests/test_auth.py` — apply 3 edits (lines 191, 419, 433) replacing non-Turkish-ASCII strings with the proper Unicode Turkish strings from the locale
2. Run `python -m pytest tests/test_auth.py -q --tb=short` — confirm 24 passed, 0 failed
3. Run `ruff check tests/test_auth.py` — confirm no lint issues
4. Report result

---

Shall I proceed with this fix? The changes are purely in test assertions — no production code is affected.

## STDERR
[0m
> plan · deepseek-v4-flash-free
[0m
[0m• [0mExplore bist_bot codebase structure[90m Explore Agent[0m
[0m✓ [0mExplore bist_bot codebase structure[90m Explore Agent[0m
[0m→ [0mRead src/bist_bot/streamlit_app.py
[0m→ [0mRead .env
[0m→ [0mRead src/bist_bot/dashboard.py
[0m
[0m$ [0mGet-ChildItem -LiteralPath "tests" -Filter "*auth*" -Name
test_auth.py
[0m
[0m→ [0mRead src/bist_bot/config/settings.py
[0m→ [0mRead src/bist_bot/config/subsettings.py
[0m✱ [0mGrep "register|kayit|kaydol"[90m in src/bist_bot/locales · 3 matches[0m
[0m
[0m$ [0mcd C:\Users\Ali\OneDrive\Masaüstü\bist_bot; python -m pytest tests/test_auth.py -x -q --tb=short 2>&1
...F
================================== FAILURES ===================================
_________ test_register_returns_403_when_public_registration_disabled _________
tests\test_auth.py:191: in test_register_returns_403_when_public_registration_disabled
    assert payload["message"] == "Herkese acik kayit kapali"
E   AssertionError: assert 'Herkese a\xe7\u0131k kay\u0131t kapal\u0131' == 'Herkese acik kayit kapali'
E     
E     - Herkese acik kayit kapali
E     ?          ^^     ^       ^
E     + Herkese a\xe7\u0131k kay\u0131t kapal\u0131
E     ?          ^^     ^       ^
------------------------------ Captured log call ------------------------------
WARNING  bist_bot.db.database:app_logging.py:133 event=no_users_and_registration_disabled component=database message=Users table is empty and public registration is off. Set ADMIN_BOOTSTRAP_EMAIL and ADMIN_BOOTSTRAP_PASSWORD_HASH to seed an admin user. timestamp=2026-05-30T19:04:29.528995+00:00
=========================== short test summary info ===========================
FAILED tests/test_auth.py::test_register_returns_403_when_public_registration_disabled
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 3 passed in 18.70s
[0m
[0m→ [0mRead src/bist_bot/locales/tr.py
[0m→ [0mRead tests/test_auth.py
[0m✱ [0mGrep "ALLOW_PUBLIC_REGISTRATION|kayit|register"[90m 1 match[0m
[0m
[0m$ [0mcd C:\Users\Ali\OneDrive\Masaüstü\bist_bot; python -m pytest tests/test_auth.py -q --tb=line 2>&1
...F.....FF.............                                                 [100%]
================================== FAILURES ===================================
E   AssertionError: assert 'Herkese a\xe7\u0131k kay\u0131t kapal\u0131' == 'Herkese acik kayit kapali'
      
      - Herkese acik kayit kapali
      ?          ^^     ^       ^
      + Herkese a\xe7\u0131k kay\u0131t kapal\u0131
      ?          ^^     ^       ^
------------------------------ Captured log call ------------------------------
WARNING  bist_bot.db.database:app_logging.py:133 event=no_users_and_registration_disabled component=database message=Users table is empty and public registration is off. Set ADMIN_BOOTSTRAP_EMAIL and ADMIN_BOOTSTRAP_PASSWORD_HASH to seed an admin user. timestamp=2026-05-30T19:04:52.366060+00:00
C:\\Users\\Ali\\OneDrive\\Masa\xfcst\xfc\\bist_bot\\tests\\test_auth.py:191: AssertionError: assert 'Herkese a\xe7\u0131k kay\u0131t kapal\u0131' == 'Herkese acik kayit kapali'
E   AssertionError: assert 'Bu e-posta zaten kay\u0131tl\u0131' == 'Bu email zaten kayitli'
      
      - Bu email zaten kayitli
      + Bu e-posta zaten kay\u0131tl\u0131
C:\\Users\\Ali\\OneDrive\\Masa\xfcst\xfc\\bist_bot\\tests\\test_auth.py:419: AssertionError: assert 'Bu e-posta zaten kay\u0131tl\u0131' == 'Bu email zaten kayitli'
E   AssertionError: assert '\u015eifre en az ...rakter olmal\u0131' == 'Sifre en az ...rakter olmali'
      
      - Sifre en az 8 karakter olmali
      ? ^                           ^
      + \u015eifre en az 8 karakter olmal\u0131
      ? ^                           ^
C:\\Users\\Ali\\OneDrive\\Masa\xfcst\xfc\\bist_bot\\tests\\test_auth.py:433: AssertionError: assert '\u015eifre en az ...rakter olmal\u0131' == 'Sifre en az ...rakter olmali'
=========================== short test summary info ===========================
FAILED tests/test_auth.py::test_register_returns_403_when_public_registration_disabled
FAILED tests/test_auth.py::test_register_rejects_duplicate_email - AssertionE...
FAILED tests/test_auth.py::test_register_rejects_short_password - AssertionEr...
3 failed, 21 passed in 7.53s
[0m
