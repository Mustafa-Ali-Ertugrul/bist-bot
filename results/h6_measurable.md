# H6 — MTF Confluence SMA20/EMA200 Eğim Çelişkisi Nötrleştirme

## ADIM 0 — Ölçülebilirlik Doğrulaması (read-only)

**Soru:** `detect_regime` / `get_trend_bias` walk-forward/backtest yolu tarafından çağrılıyor mu?

### Bulgular

#### `calculate_score_and_reasons` (backtest'te tetikleniyor — KESİN)

- **`backtest/engine.py:127, 159`** — `_precalculate_signals`:
  ```python
  from bist_bot.strategy.engine_filters import calculate_score_and_reasons
  ...
  result = calculate_score_and_reasons(p, "", df.iloc[:i+1], last=last, prev=prev, ...)
  ```
  → Backtest skoru ÜRETİR. H1/H3/H5/H8 blokları burada çalışır.

- **`backtest/engine.py:1124, 1152`** — `_calculate_score`:
  Aynı `calculate_score_and_reasons` çağrısı (fallback yolu).

- **`engine_filters.py:148`** — `calculate_score_and_reasons` içinde:
  ```python
  regime = detect_regime(df)
  ```
  → `detect_regime` KESİN tetikleniyor (her satırda).

#### `get_trend_bias` (backtest'te tetikleniyor mu? — HAYIR)

- **`strategy/engine.py:224-225, 281`** — `_get_trend_bias` run-time'da çağrılır:
  ```python
  trend_bias = self._get_trend_bias(trend_df)   # engine.py:281
  ```
  → Sadece canlı `StrategyEngine` yolu. **Backtest `engine.py` bu yola girmez.**

- **`backtest/engine.py`'de `get_trend_bias` çağrısı yok.** `grep` ile doğrulandı.

- **`engine_filters.py:408` — `passes_multi_timeframe_confluence`**→ Backtest `apply_confluence`/`get_trend_bias` yolunu kullanmıyor.

#### Karar Matrisi

| Fonksiyon | Backtest'te çağrılıyor mu? | Notlar |
|---|---|---|
| `detect_regime` | **EVET** (her satırda, `calculate_score_and_reasons` içinde) | H6 fix'i burada etkili olacak |
| `get_trend_bias` | **HAYIR** (sadece canlı `StrategyEngine._prepare_analysis_frame`) | H6 fix'i `get_trend_bias` içine konursa backtest kör kalır |
| `apply_confluence` | **HAYIR** (canlı `engine.py` yolunda) | MTF confluence backtest'te devre dışı |

### Sonuç — ADIM 0: **KISMEN EVET**

- Backtest yolu `calculate_score_and_reasons` üzerinden `detect_regime`'i çağırıyor → **H6 fix'i eğer `calculate_score_and_reasons` içine konursa walk-forward'da tetiklenir.**
- Ödev metni zaten "ADIM 1 — FIX (`calculate_score_and_reasons` içinde, regime çağrısından sonra)" diyor → bu doğru yerleşim. Fix'in ölçülebilir olduğu doğrulandı.

**ÖNEMLİ NOT:** `get_trend_bias`'a dokunmıyoruz. Fix, `calculate_score_and_reasons`'ın içinde, `detect_regime` çağrısından hemen sonra, SMA20 ve EMA200 eğimlerini çeker ve çelişki varsa `detect_regime`'in döndürdüğü rejime değil **doğrudan skora/reason'a** yansır. Fakat görev "TrendBias'ı NÖTR yap" diyor — `TrendBias` sadece canlı yolunda var. Çözüm: `calculate_score_and_reasons` içine yerel bir "mtf confluence block" adımı koyacağız; SMA20/EMA200 çelişkisi varsa skora topla etkisi değil, **reason ekle + `agreement_ratio`/skor yolunu bozmadan** işaretle. Daha uygun yol: çelişki varsa, doğrudan `score`'u `0`'a bastırma **yok** (bu backtest'i bozar); bunun yerine **regime'i SIDEWAYS'e zorla** (zaten SIDEWAYS'da `sideways_score_multiplier` ile skor düşer ve `score < buy_threshold` ise `None` dönüp satır filtrelenir).

Daha temiz yaklaşım: H6, `get_trend_bias`'ın "LONG döner ama SMA20 aşağı bakıyor" hatasını düzeltmeli. `get_trend_bias` her ne kadar backtest'te çağrılmasa da, canlı yol için düzeltme yapılır.
Backtest için: `calculate_score_and_reasons`'a SMA20/EMA200 çelişki kontrolü ekle — çelişki varsa `regime`'i SIDEWAYS'e zorla (var olan `sideways_score_multiplier` + `score < buy_threshold` filtresidance).

Bu çift yollu yapı `backtest↔regime parity`'i HATIRLIyacaktır.`backtest` kendi `regime`'ini hesaplar (`detect_regime`) ve `calculate_score_and_reasons` içinde `regime == SIDEWAYS` ise `score *= sideways_score_multiplier`. Yani H6 fix'ini `calculate_score_and_reasons` içine koyarsak **backtest ve canlı paralel çalışır.**

### ADIM 0 Sonucu: **EVET — ADIM 1'e geç**

Fix'i `calculate_score_and_reasons` içine koyacağız. Bu, hem canlı (`StrategyEngine`) hem backtest (`Backtester._precalculate_signals`) yolunda tetiklenir.

## ADIM 1 — Fix Planı

Yer: `src/bist_bot/strategy/engine_filters.py:calculate_score_and_reasons` (regime çağrısından sonra, satır 148 sonrası).

1. SMA20 eğimi: `sma_20_last - sma_20_prev` (slope_lookback=40).
2. EMA200 eğimi: `ema_long_last - ema_long_prev` (slope_lookback=40).
3. Çelişki: `(sma_20_slope > 0) != (ema_200_slope > 0)` ve ikisi de `!= 0`.
4. Çelişki + `mtf_confluence_block_enabled` (default True) → `regime`'i `SIDEWAYS`'e zorla.
5. Reason: "MTF çelişki (SMA20/EMA200 zıt eğim) → confluence nötr".

`get_trend_bias`'a da aynı çelişki kontrolü eklenir (canlı yolu için): çelişki varsa `NEUTRAL` döner.

## ADIM 2-3 Planı

Walk-forward scriptlerine sayaç + CLI arg eklenecek (görev metnine göre).

Durum: **Devam ediliyor → ADIM 1**
