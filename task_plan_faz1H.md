# Faz 1H — Final Plan (kod-doğrulanmış revizyon)

> Bu doküman, onaylanan Faz 1H kapsamının (1 + 2 + 3) kod üzerinde doğrulanmış
> halidir. Orijinal plandaki **4 hatalı varsayım** ve **7 eksik** işaretlenip
> düzeltilmiştir. Strateji parametre önerileri (eşik 30, EMA200 hard block, RSI
> veto, smoothing) Faz 2 signal-replay backtest'ine havale edilmiştir — bu
> dokümanda kapsam dışıdır.

---

## 0. İnceleme özeti — orijinal plandaki hatalar ve eksikler

| # | Tip | Bulgu | Kanıt | Etki |
|---|-----|-------|-------|------|
| H1 | ❌ Hata | `engine_filters.is_trade_actionable(signal, params)` **mevcut değil**. "Mevcut sözleşmeyi reuse et" talimatı uygulanamaz. | `grep -rn "is_trade_actionable" src tests` → 0 sonuç. Var olanlar: `Signal.is_actionable` (alan, `engine.py:394`), `StrategyEngine.get_actionable_signals` (tip-bazlı, `engine.py:595`), `engine_filters.is_buy_signal` (`engine_filters.py:89`) | Yeni helper **yazılmak zorunda**; tanımı netleşmeli (aşağıda) |
| H2 | ❌ Hata | "Davranış (scale/blocked) korunur, sadece self listeden düşer" — **yanlış**. `correlated` listesinin **uzunluğu** hem `correlation_scale` hem de blok kararını besliyor. | `correlation.py:100-113`: `len(correlated) > correlation_max_cluster` → block; `1.0 - len(correlated)*step` → scale | Self çıkarınca **scale artar / blok kalkabilir**. Bu bir davranış değişikliği ve aslında asıl bug'ın ta kendisi. Bilinçli kabul edilmeli + test edilmeli |
| H3 | ❌ Hata | Başarı kriteri "SAT sinyal mesajında R/R satırı" — **bugünkü kodla gözlemlenemez**. SAT sinyalleri Telegram detay mesajı almıyor. | `notification_service.py:43-45`: `if signal.score <= 0: continue` | Kriter ya yeniden yazılmalı (reasons/DB düzeyi) ya da kapsam genişler (önerilmez) |
| H4 | ❌ Hata | Test dosyası adları yanlış: `tests/test_notifier.py` **yok**. Ayrıca "Long trade plan not generated" assertion'ı **`tests/test_strategy.py:285`**'te ve plan bu dosyayı hiç anmıyor → build kırmızıya düşer. | `ls tests/` (test_notification_dispatch.py var, test_notifier.py yok); `grep -rn "Long trade plan" tests` | Doğrulama komutu yanlış dosya çağırıyor, kırılacak test listede yok |
| E1 | ➕ Eksik | Eski sinyalin actionable'lığı **DB'den okunamaz**: `buy_threshold` / `is_actionable` persist edilmiyor; `Signal(...)` default'ları (`20.0` / `False`) devreye giriyor. | `signals_repository.py:348-368` (`_signal_to_dict` bu iki alanı döndürmüyor), `database.py` SignalRecord'da kolon yok | Eşik, **yeni sinyalin `buy_threshold`**'undan alınmalı (single source of truth, #108) |
| E2 | ➕ Eksik | Short taraf `Signal.is_actionable` ile **asla** actionable olmuyor (`score >= buy_threshold`, skor negatif). Plan (a) şıkkı sells'i tamamen sönümlerdi. | `engine.py:394` | Helper **simetrik** olmalı: `abs(score) >= threshold` |
| E3 | ➕ Eksik | Skor > 0 olan her sinyal **zaten her taramada** detay mesajı alıyor → long taraf change bildirimi büyük ölçüde mükerrer. Skor < 0 için change bildirimi **tek Telegram yüzeyi**. | `notification_service.py:43-54` | Sönümleme tasarımı bu asimetriyi bilerek yapmalı (long'da agresif, short'ta korumacı) |
| E4 | ➕ Eksik | Sönümlenen değişimde `self.sleeper(1)` çağrılmamalı (tarama başına boşa saniyeler). | `signal_change_service.py:52` | 1 satır, plan atlamış |
| E5 | ➕ Eksik | Log tarafı "aynı kalsın" demek ölçüm sağlamıyor. `notified` / `suppress_reason` / `score_delta` alanları eklenmezse Faz 2'de sönümleme oranı ölçülemez (ölçüm-önce disiplini). | `signal_change_service.py:47-51` | Log şeması genişletilmeli |
| E6 | ➕ Eksik | Kısa devre koruması yok: `stop == price` → ZeroDivisionError; `previous["score"]` None gelirse `abs()` patlar. | `engine_meta.py:52-80`, `signal_change_service.py:35` | Guard'lar spesifikleşmeli |
| E7 | ➕ Eksik | Doğrulama komutları ortamla uyumsuz: `uv` sandbox'ta kurulu değil; proje CI'sı `pytest` + `ruff check .` + `ruff format --check .` + `mypy src/bist_bot --ignore-missing-imports` kullanıyor. `mypy --strict` proje standardı **değil** (repo strict-clean değil). | `.github/workflows/ci.yml:36-42,73-79`, `mypy.ini` (13 error code disabled) | Komut listesi CI ile hizalanmalı |
| N1 | ℹ️ Bilgi | `apply_buy_side_risk` non-buy dalı sadece SELL ailesi için değil, **HOLD adayları** için de çalışıyor; ancak HOLD adayları `analyze()` sonunda `None` dönüyor, sinyale dönüşmüyor. BUY→RADAR downgrade'i risk hesabından **sonra** olduğu için RADAR long'lar long planı koruyor. | `engine.py:497-552` | Davranış doğru; sadece `test_strategy.py`'deki HOLD fixture'ı yeni metni görecek |
| N2 | ℹ️ Bilgi | `engine.py:686` mypy hatası (reset_sectors) — teyit edildi, kapsam dışı. | plan notu | Değişiklik yok |

Çürütülen iddialar (R/R uyuşmazlığı, güven paradoksu) → aksiyon yok. Bu kararı koruyorum.

---

## 1. Goal (revize)

Uzman raporlarında kanıtla doğrulanan 3 gerçek sorunu **küçük, additive ve
geri-alınabilir** düzeltmelerle gidermek:

1. `signal_change` bildirim gürültüsünün sönümlenmesi (ölçülebilir log ile),
2. Short sinyallerin trade planı metnindeki bilgi boşluğu (R/R satırı),
3. Korelasyon listesinde/skalasında self-correlation kirliliği.

Strateji parametre değişiklikleri Faz 2 backtest'ine havale — **bu fazda hiçbir
eşik/veto/smoothing dokunuşu yok**.

---

## 2. Madde 1 — signal_change sönümleme

### 2.1 Actionability sözleşmesi (H1/E1/E2 düzeltmesi)

Repoda bugün **üç ayrı** "actionable" tanımı var:

| Tanım | Yer | Semantik |
|---|---|---|
| `Signal.is_actionable` | `engine.py:394` | `score >= params.buy_threshold` (yalnız long) |
| `get_actionable_signals()` | `engine.py:595` | `signal_type not in {HOLD, RADAR}` (WEAK_* dahil, execute/paper yolu) |
| `is_buy_signal()` | `engine_filters.py:89` | yön testi |

Bildirim gate'i için **yeni ve simetrik** bir helper eklenir (yeni actionable
mantığı icat etmek değil; mevcut skor-eşik sözleşmesini short'a aynalamak):

```python
# src/bist_bot/strategy/engine_filters.py  (additive)
def is_sell_signal(signal_type: SignalType) -> bool:
    """Return whether a signal opens or adds a short position."""
    return signal_type in {SignalType.STRONG_SELL, SignalType.SELL, SignalType.WEAK_SELL}


def is_trade_actionable(signal: Signal, threshold: float | None = None) -> bool:
    """Symmetric actionability for notification gating.

    Long side reuses the engine contract (score >= buy_threshold, #108).
    Short side mirrors it on the absolute score. RADAR/HOLD are never
    trade-actionable regardless of score.
    """
    limit = signal.buy_threshold if threshold is None else float(threshold)
    if signal.signal_type in {SignalType.HOLD, SignalType.RADAR}:
        return False
    if is_buy_signal(signal.signal_type):
        return signal.score >= limit
    if is_sell_signal(signal.signal_type):
        return abs(signal.score) >= limit
    return False
```

Eşik kaynağı: **yeni sinyalin `signal.buy_threshold`'u** (canlı `params`'tan
gelir, #108 single-source-of-truth). Eski sinyal DB'den threshold taşımadığı
için (E1) aynı canlı eşikle değerlendirilir; `SignalChangeService`'e `params`
enjekte etmeye gerek yoktur.

**Sonuç tablosu (gate davranışı):**

| Eski → Yeni | Bildirim | Neden |
|---|---|---|
| WEAK_BUY (+12) → RADAR (+21) | ❌ (Δ=9 < 15) | ikisi de non-actionable, küçük delta |
| RADAR (+22) → WEAK_BUY (+14) | ❌ (Δ=8) | aynı |
| WEAK_BUY (+12) → BUY (+25) | ✅ | yeni actionable |
| BUY (+25) → RADAR (+21) | ✅ | eski actionable (pozisyon sahibi bilmeli) |
| WEAK_SELL (−12) → SELL (−22) | ✅ | yeni actionable (short simetrisi, E2) |
| WEAK_SELL (−10) → WEAK_BUY (+3) | ❌ (Δ=13) | eşik-altı churn |
| WEAK_SELL (−10) → WEAK_BUY (+8) | ✅ (Δ=18) | delta kuralı |

### 2.2 Uygulama

`src/bist_bot/services/signal_change_service.py`:

- `from bist_bot.config.settings import settings` ve
  `from bist_bot.strategy.engine_filters import is_trade_actionable` importları.
- `__init__(..., min_score_delta: int | None = None)` — test edilebilirlik için
  enjekte edilebilir; `None` ise **çağrı anında**
  `getattr(settings, "SIGNAL_CHANGE_MIN_SCORE_DELTA", 15)` okunur (böylece
  `settings.override(...)` context manager'ı testlerde çalışır).
- Eski `Signal` kurulumunda `buy_threshold=signal.buy_threshold` da geçirilir
  (notifier/old-signal tutarlılığı).
- Gate:

```python
old_score = previous.get("score")
score_delta = abs(float(signal.score) - float(old_score)) if old_score is not None else float("inf")  # E6
threshold = signal.buy_threshold
should_notify = (
    is_trade_actionable(signal, threshold)
    or is_trade_actionable(old_signal, threshold)
    or score_delta >= self._min_score_delta()
)
if should_notify:
    self.notifier.send_signal_change(signal.ticker, old_signal, signal)
logger.info(
    "signal_changed",
    ticker=signal.ticker,
    old_signal=previous["signal_type"],
    new_signal=signal.signal_type.value,
    old_score=old_score,
    new_score=signal.score,
    score_delta=round(score_delta, 2) if score_delta != float("inf") else None,
    notified=should_notify,                       # E5 — Faz 2 ölçüm alanı
    suppress_reason=None if should_notify else "below_min_score_delta",
)
if should_notify:
    self.sleeper(1)      # E4 — sönümlenen değişimde uyuma
```

> Not: `logger.info("signal_changed", ...)` **her** değişimde çalışmaya devam
> eder (kapsam sözleşmesi). Yalnız Telegram gönderimi ve rate-limit uykusu
> gate'lenir.

### 2.3 Config

`src/bist_bot/config/subsettings.py` → `NotificationSettings` (SIGNAL_TTL_MINUTES
komşuluğu):

```python
    # Signal-change Telegram damping: type flips whose |Δscore| stays below this
    # value are logged but not pushed, unless either side is trade-actionable.
    SIGNAL_CHANGE_MIN_SCORE_DELTA: int = _get_int_env("SIGNAL_CHANGE_MIN_SCORE_DELTA", 15)
```

`Settings.__getattribute__` grup proxy'si sayesinde `settings.SIGNAL_CHANGE_MIN_SCORE_DELTA`
ve `settings.override(SIGNAL_CHANGE_MIN_SCORE_DELTA=0)` çalışır (`settings.py:122-136`).
Env değeri **import anında** okunur; runtime değişimi için `override` kullanılır.
`.env.example`'a bir satır eklenir (dokümantasyon; plan atlamıştı).

---

## 3. Madde 2 — Short trade plan metni (`engine_meta.py`)

### 3.1 `apply_buy_side_risk` short dalı

Her iki dalda (ATR **ve** %5/%8 fallback) aynı formül, tek yerde:

```python
        risk = final_stop - price          # stop > price  (short)
        reward = price - final_target      # target < price
        risk_reward_ratio = round(reward / risk, 2) if risk > 0 else 0.0   # E6 guard
        return RiskLevels(
            final_stop=final_stop,
            final_target=final_target,
            risk_reward_ratio=risk_reward_ratio,
            risk_pct=round(-risk / price * 100, 2),    # stops.py:236 ile aynı işaret sözleşmesi
            reward_pct=round(reward / price * 100, 2), # stops.py:237
            position_size=0,
            method_used=method_used,
        )
```

- `risk` / `reward` **yuvarlanmış** `final_stop` / `final_target` üzerinden
  hesaplanır → gösterilen stop/hedef ile R/R birebir tutarlı (başarı kriteri).
- İşaret sözleşmesi long tarafla (`stops.py:236-238`) aynı: `risk_pct` negatif,
  `reward_pct` pozitif, `risk_reward_ratio` pozitif.
- Beklenen değerler: ATR dalı `3.0*ATR / 2.0*ATR = 1.5`; fallback dalı
  `8% / 5% = 1.6`.
- `position_size=0` korunur (short sizing Faz 2).

### 3.2 `append_signal_reasons`

```python
    if not is_buy_signal(signal.signal_type):
        signal.reasons.append(
            f"R/R: 1:{risk_levels.risk_reward_ratio:.1f} | {risk_levels.method_used}"
        )
        return
```

- Pozisyon / risk bütçesi / volatilite / Kelly satırları **eklenmez** (sahte
  sayı yok — onaylı karar).
- **Onaylandı (D4):** R/R satırının hemen ardından tek açıklayıcı satır eklenir —
  `"Pozisyon boyutlandırma: yok (short sizing Faz 2)"`. Sayı üretmez, sessiz
  boşluğu açıklar:

```python
    if not is_buy_signal(signal.signal_type):
        signal.reasons.append(
            f"R/R: 1:{risk_levels.risk_reward_ratio:.1f} | {risk_levels.method_used}"
        )
        signal.reasons.append("Pozisyon boyutlandırma: yok (short sizing Faz 2)")
        return
```

### 3.3 Başarı kriteri düzeltmesi (H3)

Bugün SAT sinyalleri Telegram detay mesajı **almıyor** (`notification_service.py:43-45`,
`score <= 0 → continue`) ve `send_signal_change` reasons basmıyor. Dolayısıyla
kriter şöyle olmalı:

> SAT sinyalinin `signal.reasons[-1]` (ve DB `reasons`/`conditions` kolonu +
> dashboard detay görünümü) `R/R: 1:1.5 | Short trade plan: ATR-based ...`
> satırını içerir; R/R = `(fiyat − hedef) / (stop − fiyat)` ile tutarlıdır.

SAT sinyallerini Telegram detay akışına eklemek **kapsam dışıdır** (Madde 1'in
gürültü azaltma amacıyla doğrudan çelişir) → Faz 2 kararı.

### 3.4 Kırılacak mevcut test (H4)

`tests/test_strategy.py:285`:
```python
assert signal.reasons == ["Long trade plan not generated: signal is not buy-side"]
```
Bu satır yeni R/R assertion'ı ile güncellenecek (dosya plan listesinde yoktu,
eklendi).

---

## 4. Madde 3 — Self-correlation (`risk/correlation.py`)

### 4.1 Uygulama

`get_correlated_positions` iki dalda da self atlanır:

```python
    if global_corr_cache is not None and ticker in global_corr_cache.columns:
        for existing_ticker in portfolio_history:
            if existing_ticker == ticker:      # self-correlation = 1.0, gerçek küme değil
                continue
            ...
    ...
    for existing_ticker, history in portfolio_history.items():
        if existing_ticker == ticker:
            continue
        ...
```

### 4.2 Davranış etkisi — plan iddiası düzeltmesi (H2)

Self, listeden düştüğü için `len(correlated)` 1 azalır:

- `correlation_scale = max(min_scale, 1.0 - len*step)` → etkilenen tickerlarda
  **skala artar** (varsayılan step 0.35 → +0.35'e kadar),
- `len(correlated) > correlation_max_cluster` (default 2) → sınırdaki adaylarda
  **blok kalkabilir**.

Bu **kasıtlı ve doğru** bir düzeltmedir: `register_position` her buy sinyalinde
çağrıldığı için (`engine.py:551`) bir hisse ikinci kez sinyal ürettiğinde kendi
kendisiyle 1.0 korelasyona giriyor ve sahte küme cezası yiyordu. Ama "davranış
korunur" ifadesi yanlıştı; risk seviyesi **düşük-orta** olarak etiketlenmeli ve
CHANGELOG'da davranış değişikliği olarak not edilmelidir.

Etki yüzeyi: yalnız `portfolio_history` içinde **kendi ticker'ı bulunan**
adaylar (yani daha önce sinyal üretmiş / açık pozisyonu olan hisseler).
Diğer tüm adaylarda sonuç birebir aynı.

---

## 5. Dosya listesi (düzeltilmiş)

**Kaynak**
- `src/bist_bot/strategy/engine_filters.py` — ➕ `is_sell_signal`, `is_trade_actionable` (yeni, additive)
- `src/bist_bot/services/signal_change_service.py` — sönümleme gate'i + log alanları + sleeper düzeltmesi
- `src/bist_bot/config/subsettings.py` — `SIGNAL_CHANGE_MIN_SCORE_DELTA`
- `src/bist_bot/strategy/engine_meta.py` — short R/R + reason satırı
- `src/bist_bot/risk/correlation.py` — self-exclusion
- `.env.example` — yeni ayarın dokümantasyonu
- `CHANGELOG.md` — 3 madde + korelasyon davranış değişikliği notu

**Testler**
- `tests/test_signal_change_service.py` — sönümleme senaryoları (yeni)
- `tests/test_strategy.py` — ⚠️ **mevcut assertion güncellenmeli** (`:285`) + short R/R testi
- `tests/test_risk_manager.py` — self-exclusion testleri (pairwise dalı)
- `tests/test_risk_manager_extended.py` — self-exclusion (global cache dalı, mevcut `test_get_correlated_positions_uses_global_cache` komşuluğu)
- ~~`tests/test_notifier.py`~~ → **böyle bir dosya yok** (H4). Notifier tarafında değişiklik gerekmiyor; gerekirse `tests/test_notification_dispatch.py`.
- ~~`tests/test_signal_models_fixes.py`~~ → alakasız (Signal dataclass/TTL testleri), dokunulmaz.

---

## 6. Test senaryoları (kabul testleri)

**Madde 1 — `tests/test_signal_change_service.py`**
1. `radar_to_weak_buy_small_delta_is_suppressed`: RADAR(+21) → WEAK_BUY(+14), `is_actionable=False`, delta 7 → `send_signal_change` **çağrılmaz**, `sleeper` **çağrılmaz**, caplog'da `signal_changed` + `notified=False`.
2. `transition_into_actionable_notifies`: WEAK_BUY(+12) → BUY(+30, `is_actionable=True`) → bildirim **var**.
3. `transition_out_of_actionable_notifies`: BUY(+30) → RADAR(+21) (eski actionable, yeni değil) → bildirim **var**.
4. `short_side_actionable_notifies`: WEAK_SELL(−12) → SELL(−30) → bildirim **var** (simetri, E2).
5. `large_delta_notifies_even_when_both_non_actionable`: RADAR(+5) → WEAK_SELL(−12), delta 17 ≥ 15 → bildirim **var**.
6. `min_delta_setting_is_configurable`: `settings.override(SIGNAL_CHANGE_MIN_SCORE_DELTA=0)` → senaryo 1 artık bildirim **gönderir** (kill-switch doğrulaması).
7. `missing_previous_score_notifies`: `previous["score"] = None` → bildirim **var** (E6 fail-open).
8. Mevcut iki test korunur; ilki (BUY +20 → SELL −20) yeni gate ile hâlâ bildirim üretir (delta 40).

**Madde 2 — `tests/test_strategy.py`**
9. `short_plan_reports_risk_reward_atr`: ATR'li df → `risk_reward_ratio == 1.5`, reason `"R/R: 1:1.5 | Short trade plan: ATR-based"` ile başlar.
10. `short_plan_reports_risk_reward_fallback`: ATR yok/NaN → `1.6`, `"fixed 5% stop / 8% target"`.
11. R/R tutarlılığı: `pytest.approx((price - final_target) / (final_stop - price), rel=1e-2) == risk_reward_ratio`.
12. `:285` assertion'ı güncellenir; iki satır beklenir (R/R + "Pozisyon boyutlandırma: yok (short sizing Faz 2)") ve pozisyon/risk bütçesi **sayısı** içermediği assert edilir (`"Pozisyon:" not in ...`, `"Risk Bütçesi" not in ...`).

**Madde 3 — `tests/test_risk_manager*.py`**
13. `self_ticker_excluded_from_correlated_pairwise`: `register_position("AKBNK.IS", df)` → `apply_portfolio_risk("AKBNK.IS", df, ...)` → `correlated_tickers == []`, `correlation_scale == 1.0`.
14. `self_ticker_excluded_from_correlated_cache`: global cache dalında aynı sonuç.
15. `cluster_block_still_triggers_without_self`: self hariç 3 korele hisse → hâlâ `blocked_by_correlation is True` (regresyon koruması).
16. Mevcut `test_correlation_risk_limit_scales_position_and_matrix` (`AKBNK` aday, `XBANK` portföyde) etkilenmez → yeşil kalmalı.

---

## 7. Doğrulama komutları (ortam + CI hizalı — E7)

Sandbox'ta `uv` **kurulu değil** (`uv: command not found`) ve bağımlılıklar yok.
Adım 0 zorunlu:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r dev-requirements.txt
```
(`uv` mevcut bir ortamda `uv run ...` prefix'i ile aynı komutlar geçerlidir.)

```bash
# 1) Hedefli testler (dosya adları düzeltildi)
pytest tests/test_signal_change_service.py tests/test_strategy.py \
       tests/test_risk_manager.py tests/test_risk_manager_extended.py \
       tests/test_risk_persistence.py tests/test_scanner.py \
       tests/test_paper_trade_service.py tests/test_notification_dispatch.py -q

# 2) Regresyon (CI ile aynı)
pytest tests/ -q --tb=short

# 3) Lint + format (CI: ruff check . && ruff format --check .)
ruff check src/bist_bot/services/signal_change_service.py \
           src/bist_bot/strategy/engine_meta.py \
           src/bist_bot/strategy/engine_filters.py \
           src/bist_bot/risk/correlation.py \
           src/bist_bot/config/subsettings.py tests/
ruff format --check .

# 4) Tip kontrolü — proje standardı (CI ile aynı komut)
mypy src/bist_bot --ignore-missing-imports

# 5) (Opsiyonel, bilgi amaçlı) dokunulan modülde strict
mypy --strict src/bist_bot/strategy/engine_meta.py || true
```

> `mypy --strict` proje standardı değil: `mypy.ini` 13 error code'u kapatıyor ve
> repo strict-clean değil (`engine.py:686 reset_sectors` bilinen hata, kapsam
> dışı). Gate olarak (4) kullanılır; (5) yalnız bilgi amaçlıdır ve **yeni**
> strict hatası üretmemek hedeflenir.

---

## 8. Başarı kriterleri (düzeltilmiş)

1. **Sönümleme:** eşik-altı, |Δskor| < 15 tip geçişi → Telegram **yok**, `signal_changed` log'u **var** ve `notified=false, suppress_reason="below_min_score_delta", score_delta=<n>` alanlarını taşıyor.
2. **Kaçırma yok:** herhangi bir yönde (long veya short) actionable eşiğine giriş/çıkış → Telegram **var**.
3. **Kill-switch:** `SIGNAL_CHANGE_MIN_SCORE_DELTA=0` → eski davranış birebir geri gelir (yalnız actionable/delta≥0 → hepsi bildirilir).
4. **Short R/R:** SAT sinyalinin `reasons` listesi (DB + dashboard) `R/R: 1:X.X | Short trade plan: ...` satırını ve ardından `Pozisyon boyutlandırma: yok (short sizing Faz 2)` satırını içerir; R/R değeri `(fiyat − hedef) / (stop − fiyat)` ile ±0.05 tutarlıdır; pozisyon lot / risk bütçesi **sayısı** yoktur.
5. **Self-exclusion:** `Iliskili:` listesinde sinyalin kendi ticker'ı **yok**; kendi ticker'ı portföyde olan adayda `correlation_scale` bir kademe **artmış** olur (bilinçli davranış değişikliği); 3+ gerçek korele hissede blok **hâlâ** çalışır.
6. Tüm test paketi yeşil, `ruff check .` / `ruff format --check .` temiz, `mypy src/bist_bot --ignore-missing-imports` yeni hata üretmiyor.

---

## 9. Riskler

| Risk | Seviye | Azaltım |
|---|---|---|
| Sönümleme gerçek bir dönüşü kaçırır (eşik-altı churn içinde başlayan trend) | Düşük | Long tarafta change bildirimi zaten mükerrer (skor>0 her taramada detay mesajı alıyor, E3); short tarafta simetrik eşik korur; `notified=false` logu ile Faz 2'de ölçülür; `SIGNAL_CHANGE_MIN_SCORE_DELTA` ile anında gevşetilir |
| WEAK_BUY / WEAK_SELL execute yolunda (`get_actionable_signals` tip-bazlı, paper trade kuyruğuna giriyor) ama bildirim gate'i eşik-bazlı → eşik-altı paper trade'in *change* bildirimi susar | Düşük-orta | İlk sinyal detay mesajı (skor>0) etkilenmiyor; STRONG_SELL auto-execute her zaman actionable eşiğinin üstünde; kararı §10-D1'de açıkça onaya sunuyorum |
| Self-exclusion pozisyon büyüklüğünü artırır (skala 0.65 → 1.0 gibi) | Düşük-orta | Sadece kendi ticker'ı portföy geçmişinde olan adaylar; küme bloğu regresyon testiyle korunuyor; CHANGELOG'da davranış değişikliği olarak duyurulur |
| Short R/R'ın anlamlı görünüp sizing olmaması yanlış anlaşılır | Düşük | `position_size=0` korunur; §3.2 opsiyonel açıklama satırı |
| `engine.py:686` mypy hatası | Bilgi | Kapsam dışı, dokunulmaz |

---

## 10. Kararlar (kapandı — kullanıcı onayı 2026-08-19)

- **D1 — Gate'te "actionable" tanımı → EŞİK-BAZLI SİMETRİK** (§2.1). HOLD/RADAR
  asla actionable; long `score >= buy_threshold`, short `abs(score) >= buy_threshold`.
  Tip-bazlı alternatif reddedildi (emitted tipler BUY/SELL/RADAR olduğu için
  sönümlemeyi sıfırlardı).
- **D2 — Self-exclusion'ın skala/blok etkisi → KABUL.** Self tamamen hariç
  tutulur; `correlation_scale` artışı ve sınırdaki blok kalkması bilinçli
  düzeltmedir, CHANGELOG'da davranış değişikliği olarak duyurulur.
- **D3 — SAT detay mesajı (score<=0 gate'i) → KAPSAM DIŞI, Faz 2.** Madde 2'nin
  kabul kriteri reasons/DB/dashboard düzeyinde ölçülür.
- **D4 — Short reason açıklama satırı → EKLENİR** (§3.2).

Açık karar kalmadı.

## 11. Handoff

`@build`: §2–§4'ü **tam olarak** yazıldığı gibi uygula (D1–D4 kararları kapandı,
onay alındı). Değişiklikler additive; yeni `is_trade_actionable` helper'ı yalnız bildirim
gate'inde kullanılır — `engine.py`'deki `is_actionable` üretimi ve
`get_actionable_signals` sözleşmesi **değiştirilmez** (üç tanımın
birleştirilmesi Faz 2 mimari kalemi). §6'daki 16 test senaryosunu yaz, §7'deki
komutları çalıştır ve çıktıları raporla. Faz 2 (signal-replay backtest + uzman
sorularının analiz boyutları: eşik 30, EMA200 hard block, RSI veto, smoothing,
short sizing, actionable-tanım birleştirme) ayrı planlama adımıdır.
