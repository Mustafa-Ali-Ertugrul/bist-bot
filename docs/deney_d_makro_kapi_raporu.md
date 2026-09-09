# Deney D — Makro Rejim Kapısı Raporu

**Tarih:** 2026-08-28
**Git SHA:** `59c41f4d7e866e7a4c9fee106b0d58b6cdd3085f`
**Karar:** **RED** (canlı kapı veya varsayılan backtest davranışı değiştirilmedi)

---

## 1. Kurulum

### Makro rejim serisi

- Kaynak: `THYAO.IS`, `GARAN.IS`, `AKBNK.IS` — `~/.cache/bist_bot/wf_data/*_3y.parquet` (**cache-only, ağ yok**)
- Üretici: `bist_bot.strategy.regime.build_macro_regime_series()` (tek kez, 30 ticker koşusunda paylaşıldı)
- Benchmark temizliği: tz-aware → UTC → tz-naive, sıralama, tekrar eden tarihler `keep="last"`, NaN close düşürüldü
- Seri aralığı: **2023-08-28 .. 2026-08-27 (754 gün)** — ticker verisi sonu (2026-08-27) ile birebir aynı; staleness farkı **0 gün**

### Rejim dağılımı

| Rejim | Gün | Pay |
|---|---|---|
| BULL | 343 | %45.5 |
| SIDEWAYS | 209 | %27.7 |
| BEAR | 153 | %20.3 |
| UNKNOWN | 49 | %6.5 |

İlk 49 gün UNKNOWN (`MACRO_REGIME_MIN_BARS=50` warmup); UNKNOWN/NaN/seri öncesi tarihler girişi engellemez, BEAR barı sayılmaz.

### Toplama kuralı (canlı parity)

`aggregate_macro_regime(regime_votes)` — canlı `detect_macro_regime()` ile **birebir aynı kod** (refaktör edilip tek fonksiyona çıkarıldı):

1. Her benchmark için `detect_regime()` (ADX/DI + momentum kuralı, formül kopyalanmadı).
2. `MACRO_REGIME_MIN_BARS = 50`'den az geçmişi olan benchmark **oy vermez** (UNKNOWN sayılmaz — canlı koddaki `len < 50 → skip` davranışıyla aynı).
3. < 2 oy → tek oy (veya UNKNOWN); aksi halde **çoğunluk**, eşitlikte tie-break: **BULL > SIDEWAYS > BEAR > UNKNOWN**.

Parity, `tests/test_macro_regime.py::test_build_series_uses_detect_macro_regime_aggregation_rule` ile doğrulandı (seri değeri == son tarihte canlı `detect_macro_regime()` çıktısı).

### Benchmark cache hash'leri (SHA256)

```
2F6D9361...  THYAO_IS_3y.parquet
F2B12E81...  GARAN_IS_3y.parquet
00884A1A...  AKBNK_IS_3y.parquet
```
Observe ve enforce koşuları arasında hash'ler **değişmedi** (iki koşu arasında doğrulandı). Tam hash'ler: `results/expD_reproducibility.txt`.

### Komutlar

```powershell
# Smoke (3 hisse × 3 mod)
uv run python scripts/run_walk_forward_bist30.py --limit 3 --no-chase-block-enabled --macro-regime-mode {off,observe,enforce} --output results/smoke_expD_{...}.csv

# Tam 30 hisse paired
uv run python scripts/run_walk_forward_bist30.py --no-chase-block-enabled --macro-regime-mode observe  --output results/walk_forward_expD_macro_observe.csv
uv run python scripts/run_walk_forward_bist30.py --no-chase-block-enabled --macro-regime-mode enforce --output results/walk_forward_expD_macro_enforce.csv

# Per-signal A/B
uv run python scripts/evaluate_july_2026_predictions.py --macro-regime-mode observe  --output results/prediction_signals_macro_observe.csv
uv run python scripts/evaluate_july_2026_predictions.py --macro-regime-mode enforce --output results/prediction_signals_macro_enforce.csv

# Karar
uv run python scripts/analyze_macro_gate_experiment.py   # çıktı: results/expD_analysis_output.txt
```

`--force-download` kullanılmadı. Ortam değişkeni (`MACRO_REGIME_GATE_ENABLED`) backtest yolunu **etkilemez** — mod yalnızca constructor argümanıyla gelir.

## 2. Kapı tasarımı (uygulama özeti)

- `Backtester(macro_regime_series=..., macro_regime_mode={"off","observe","enforce"})`.
- `_apply_macro_entry_gate()` `_precalculate_signals()` içinde, tüm giriş filtrelerinden **sonra** ve mevcut tek `shift(1)`'den **hemen önce** uygulanır.
- Seri, ticker indeksine `reindex(method="ffill")` ile hizalanır (**bfill yok**); seri başı/NaN → UNKNOWN (engellemez, BEAR sayılmaz).
- Aday = `(rejim == BEAR) & enter_signal` (ham, shift öncesi). `observe` yalnız sayar; `enforce` adaylarda `enter_signal=False`. `score`, `exit_signal`, stop/hedef değişmez.
- Fail-fast: mod ≠ off + seri yok → `ValueError`; off + seri → `ValueError`; özel `signal_builder` → `ValueError`; intraday indeks → `ValueError`; monoton olmayan seri indeksi → `ValueError`; `backtester_factory` + gate modu → `ValueError`.
- Sayaçlar her `run()` başında sıfırlanır: `last_macro_bear_bars`, `last_macro_bear_entry_candidates`.
- Sinyal önbelleği: `_precalculate_signals` her `run()`'da yeniden hesaplanır (kalıcı cache yok) — cache anahtarına mod eklemeye gerek kalmadı.
- Canlı `src/bist_bot/strategy/engine.py` **değiştirilmedi** (yalnız `aggregate_macro_regime` refaktörü ile paylaşılan kural `regime.py`'de tek kaynak oldu).

## 3. Invariant sonuçları

| Invariant | Sonuç | Kanıt |
|---|---|---|
| off == observe (trade/return birebir) | **PASS** | smoke 3 hisse CSV diff: 0 fark; `test_observe_matches_off_exactly` |
| observe/enforce BEAR bar & aday sayıları aynı | **PASS** | 2879 bar / 97 aday iki CSV'de de aynı |
| enforce yeni trade/sinyal ekleyemez | **PASS** | enforce-only anahtar = **0**; `test_enforce_only_removes_trades_never_adds` |
| Ortak anahtarların getiri/exit/score'u aynı | **PASS** | 442 ortak sinyalde 0 uyumsuzluk |
| Nedensellik (≤t verisi) | **PASS** | `test_build_series_causality_vectorized_equals_brute_force` (örneklenen her tarihte vektörize == brute-force dilim) |
| UNKNOWN/BULL/SIDEWAYS engellemez; seri başı NaN → UNKNOWN | **PASS** | `test_bull_series_never_blocks`, `test_series_start_gap_treated_as_unknown_and_never_blocks` |
| score/exit/stop/target dokunulmaz | **PASS** | `test_score_and_exit_columns_untouched_by_enforce` |
| Kaskad etkisi yok | **PASS** | enforce ⊆ observe; günlük `last_buy_date` kuralı + kapı sinyal seviyesinde; smoke ve tam koşuda enforce-only = 0 |
| Backtest yolu env değişkeninden etkilenmez | **PASS** | mod yalnızca constructor argümanı; `MACRO_REGIME_GATE_ENABLED` okunmaz |
| Tam test paketi yeşil | **PASS** | 1384 passed, 2 skipped (mevcut psycopg2) |

## 4. Karar tablosu (analiz scripti çıktısı)

Deney **sonuçlu** idi: 153 BEAR gün, OOS'ta 97 BEAR giriş adayı, 66 engellenen sinyal.

| Kriter | Sonuç | Değer |
|---|---|---|
| Pozitif OOS ticker payı ≥ 21/30 ve ≥ observe | **FAIL** | observe 19/30 → enforce 17/30 |
| Mean & median OOS kötüleşmez | **FAIL** | mean +1.19% → +0.51%; median +1.01% → +0.75% |
| Ortalama max DD iyileşir | PASS | −7.02% → −6.00% |
| Overfit payı artmaz | **FAIL** | 46.7% → 50.0% |
| OOS trade ≥ %60–70 korunur | PASS | 266 → 222 (%83) |
| Per-signal net WR / Wilson LB / toplam net PnL kötüleşmez | **FAIL** | WR 47.44% → 47.74% (iyileşti); WilsonLB 43.13% → 43.12% (eşik altında, mikroskobik); **net PnL −88,784 → −94,617 TL (kötüleşti)** |
| Engellenen sinyallerin toplam net PnL'i ≤ 0 | **FAIL** | **+5,832 TL** (kapı net kârlı sinyalleri de engelledi) |

### Engellenen 66 sinyal

- n=66, net WR=%45.45, toplam **+5,832 TL** (100k TL/sinyal)
- Ticker dağılımı (ilk 5): ASTOR(6), KCHOL(6), PETKM(6), TOASO(5), DSTKF(4)
- Aylık dağılım: 2026-03 (n=21, −3,893 TL), 2025-04 (n=9, −24,796 TL), 2025-09 (n=6, **+30,965 TL**), 2025-05 (n=1, +20,927 TL), 2026-07 (n=3, −21,131 TL), diğer ay ~1–7 sinyal
- **2023-10 kırılımı: engellenen sinyal YOK** (o dönemde makro rejim BEAR değildi) — "yalnız 2023-10 iyileşip genel bozulma" senaryosu geçerli değil; bozulma tüm döneme yaygın.

## 5. Karar ve yorum

**RED.** Uygulama invariantlarının tamamı geçti (kapı doğru ve look-ahead içermeden çalışıyor), ancak strateji kriterlerinin 5'i başarısız:

1. Kapı, BEAR günlerde girişleri engelleyerek OOS getiriyi düşürdü (mean +1.19% → +0.51%, pozitif pay 19→17).
2. Engellenen 66 sinyalin toplamı **pozitif** (+5,832 TL): kapı, engellediği sinyallerde net olarak kârı da kesti; yalnızca DD'yi hafifçe iyileştirdi (−7.0% → −6.0%).
3. Per-signal toplam net PnL kötüleşti (−88.8k → −94.6k TL).

Not: bu backtest havuzunda per-signal net WR zaten %47 ve toplam PnL negatif; kapı "kayıp ayıklayıcı" olarak beklenen faydayı göstermedi. THYAO/GARAN/AKBNK proxy'si ile gerçek BIST30 genişliği arasındaki fark olası bir sınırlama (3 hisseli makro vekili).

**Sonraki adım yok** — canlı kapı ve varsayılan backtest bu kapsamda değiştirilmez. Kaldı ki kabul çıksaydı bile aktivasyon ayrı kullanıcı onayı gerektirecekti.

## 5a. Ek bulgu: baseline per-signal zararının kök nedeni (2026-08-28 analizi)

Per-signal baseline'ın (observe, 508 sinyal) toplamı −88.8k TL görünse de zarar **homojen değil**:

- **2023-10 tek başına −169.9k TL** (n=43, WR %16.3). O ay benchmarklar sert düştü (THYAO min −%16.3, GARAN min −%16.2, AKBNK min −%12.0); bot ay içinde **18 ayrı günde** alım üretti (düşen piyasada oversold/golden-cross kurulumları). Çıkış dağılımı: STOP_LOSS/STOP_GAP 86 sinyal −719k TL vs TAKE_PROFIT/TARGET_GAP 24 sinyal +319k TL.
- **2023-10 hariç: +81.2k TL, WR %50.3** (n=465).
- Skor kovaları arasında ayrışma yok (55+ bandı bile negatif) → sorun sinyal kalibrasyonu değil, rejim.
- Maliyet ~489 TL/sinyal (0.489%): 14 sinyali kazançtan zarara çeviriyor; ikincil etken.

**Kritik sınırlama:** rejim serisi 2023-10'un tamamında **UNKNOWN** — cache 2023-08-28'de başladığı için 50-bar warmup ~Kasım 2023'e kadar sürüyor. Yani kapının engellemesi en çok beklenen ay, bu deneyin değerlendirme kapsamında **yapısal olarak kör**. Canlı taramada kapının elinde tam geçmiş olur; bu körlük backtest cache artefaktıdır. Bu, Deney D'nin "kapı fayda sağlamadı" sonucunu değiştirmez (kriterler kalan ~2.7 yıllık dönemde ölçüldü) ama kapının potansiyel faydasının **bu veriyle alt sınırının ölçüldüğünü** gösterir.

## 6. Artefaktlar

- `results/walk_forward_expD_macro_observe.csv` / `..._enforce.csv` (yeni kolonlar: `macro_regime_mode`, `macro_bear_oos_bars`, `macro_bear_oos_entry_candidates`, `data_start`, `data_end`)
- `results/prediction_signals_macro_observe.csv` / `..._enforce.csv`
- `results/expD_analysis_output.txt` (karar tablosu tam çıktı), `results/expD_reproducibility.txt` (SHA + hash)
- Smoke: `results/smoke_expD_off.csv`, `smoke_expD_macro_observe.csv`, `smoke_expD_macro_enforce.csv`
- Kod: `src/bist_bot/strategy/regime.py`, `src/bist_bot/backtest/engine.py`, `src/bist_bot/validation/walk_forward.py`, 3 script
- Testler: `tests/test_macro_regime.py` (+8 test), `tests/test_macro_regime_backtest_gate.py` (+18 test)
